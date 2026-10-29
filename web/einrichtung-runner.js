/* Einrichtung im Browser, Schritte „Runner“, „Anbinden“ und „Fertig“ (Design 0.8.0, #96): Wahl je Fund,
   Zusammenfassung, Blöcke zum Anbinden, Einträge für /api/einrichtung/runner/zuordnung und die Zeilen
   von „Fertig“. Reine Logik ohne DOM und ohne Texte (die stehen in einrichtung.js, übersetzt mit t()),
   geprüft mit `node --test tests/js/*.test.mjs`. Im Browser als globales EINR.

   Wahl je Fund: vollständig unterstützt → 'an' | 'aus'; erkannt, noch nicht unterstützt → 'grund' |
   'ignorieren'; unbekannt → 'offen' | 'grund' | 'ignorieren'.
   Gespeichert wird in runner.json nur, was sich gegenüber der Zuordnung ändert, und nur die Felder,
   die die Oberfläche setzen darf (E-22): stand ('grund' | 'ignoriert' | null = wie erkannt), dienst,
   name, unit, log. Ein übersprungener Runner im Schritt „Anbinden“ wird nicht gespeichert – er bleibt
   „noch nicht angebunden“ und lässt sich später auf der VM anbinden. */
'use strict';

const EINR = (() => {
  const DIENSTE = { github: 'GitHub', forgejo: 'Forgejo', gitea: 'Gitea', gitlab: 'GitLab' };
  const DIENST_WAHL = ['github', 'forgejo', 'gitea', 'gitlab', 'unbekannt'];
  const GRAD = { sicher: 'ok', wahrscheinlich: 'warn', unklar: 'neutral' };
  const LOG_WURZELN = ['/var/log/', '/opt/', '/srv/'];

  /* Anzeigename des Dienstes; „unbekannt“ übersetzt der Aufrufer. */
  const dienstName = (d) => DIENSTE[d] || 'unbekannt';

  /* Wie erkennung.als_id: Kleinbuchstaben, Ziffern, . _ -, höchstens 64 Zeichen. */
  function alsId(text) {
    const sauber = String(text || '').toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '');
    return sauber.slice(0, 64) || 'runner';
  }

  /* Startwert der Wahl aus Einstufung und gespeichertem Stand. */
  function startWahl(f) {
    const stand = (f.zuordnung && f.zuordnung.stand) || f.stand;
    if (stand === 'ignoriert') return f.einstufung === 'voll' ? 'aus' : 'ignorieren';
    if (f.einstufung === 'voll') return 'an';
    if (stand === 'grund') return 'grund';
    if (f.einstufung === 'teil') return 'grund';  // Vorgabe im Design: Grundüberwachung
    return 'offen';
  }

  /* Neue Funde (nach „Neu erkennen“) bekommen ihren Startwert, bekannte behalten die Wahl. */
  function mischeWahl(funde, wahl) {
    const neu = {};
    for (const f of funde) neu[f.id] = f.id in (wahl || {}) ? wahl[f.id] : startWahl(f);
    return neu;
  }

  /* Stand rechts im Kopf eines Funds: 'anbinden' | 'ignoriert' | 'grund' | 'offen' (Klasse wie im Design). */
  function stand(f, w) {
    if (f.einstufung === 'voll') return w === 'an' ? { art: 'anbinden', cls: 'ok' } : { art: 'ignoriert', cls: 'mut' };
    if (w === 'grund') return { art: 'grund', cls: 'mut' };
    if (w === 'ignorieren') return { art: 'ignoriert', cls: 'mut' };
    return { art: 'offen', cls: 'warn' };
  }

  /* Fuß von Schritt 3: „2 anbinden · 1 Grundüberwachung · 1 offen“ (nur Teile mit n > 0). */
  function summe(funde, wahl) {
    const z = { anbinden: 0, grund: 0, offen: 0 };
    for (const f of funde) {
      const w = wahl[f.id];
      if (f.einstufung === 'voll' && w === 'an') z.anbinden++;
      else if (f.einstufung !== 'voll' && w === 'grund') z.grund++;
      else if (w === 'offen') z.offen++;
    }
    return z;
  }

  /* Runner für Schritt 4: übernommen und vollständig unterstützt. */
  const anbinden = (funde, wahl) => funde.filter((f) => f.einstufung === 'voll' && wahl[f.id] === 'an');

  /* Organisation aus dem Server eines GitHub-Funds („https://github.com/beispiel-org“). */
  function orgAus(server) {
    const m = /^https:\/\/github\.com\/([A-Za-z0-9][A-Za-z0-9-]{0,38})\/?$/.exec(String(server || ''));
    return m ? m[1] : '';
  }

  /* Host eines Servers für den Link zur Token-Seite – nur, wenn die Erkennung ihn bestätigt hat
     (Grad „sicher“: Unit vorhanden und Server hat geantwortet, E-17) und nur über https. */
  function tokenSeite(f) {
    if (!f || f.grad !== 'sicher') return null;
    const m = /^https:\/\/([a-z0-9.-]+(?::\d{1,5})?)(\/[A-Za-z0-9._~%/-]*)?$/.exec(String(f.server || ''));
    if (!m) return null;
    const basis = `https://${m[1]}${(m[2] || '').replace(/\/+$/, '')}`;
    if (f.dienst === 'forgejo' || f.dienst === 'gitea') return { host: m[1], url: `${basis}/user/settings/applications` };
    if (f.dienst === 'gitlab') return { host: m[1], url: `${basis}/-/user_settings/personal_access_tokens` };
    return null;
  }

  /* Prüfung des Formulars „Zuordnen“ wie auf dem Server (runner_monitor/einrichtung.py) – nur für die
     Rückmeldung am Feld; der Server prüft selbst. Gibt {feld: 'name'|'unit'|'log'} zurück. */
  function pruefeFormular(w, neu) {
    const fehler = {};
    const name = String(w.name || '').trim(), unit = String(w.unit || '').trim(), log = String(w.log || '').trim();
    if (name && !/^[A-Za-z0-9][A-Za-z0-9._@+-]{0,63}$/.test(name)) fehler.name = 'name';
    if ((unit || neu) && !/^(?:[A-Za-z0-9:_.@-]|\\x[0-9a-fA-F]{2}){1,200}\.service$/.test(unit)) fehler.unit = 'unit';
    if (unit.startsWith('-')) fehler.unit = 'unit';
    if (log) {
      const teile = log.split('/').slice(1);
      const ok = LOG_WURZELN.some((w2) => log.startsWith(w2)) && !log.includes('//') && !teile.includes('..')
        && !teile.some((t) => t.startsWith('.') || t.includes('runner-monitor'))
        && /^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.log$/.test(teile[teile.length - 1] || '');
      if (!ok) fehler.log = 'log';
    }
    if (!DIENST_WAHL.includes(w.dienst || 'unbekannt')) fehler.dienst = 'dienst';
    return fehler;
  }

  /* Einträge für POST /api/einrichtung/runner/zuordnung – nur, was sich gegenüber runner.json ändert.
     `formular[id]` = gespeicherte Werte aus „Zuordnen“ ({dienst, name, unit, log}). */
  function eintraege(funde, wahl, formular = {}) {
    const liste = [];
    for (const f of funde) {
      const w = wahl[f.id], z = f.zuordnung || {}, alt = z.stand || null;
      let neuStand;
      if (f.einstufung === 'voll') neuStand = w === 'aus' ? 'ignoriert' : null;
      else if (w === 'ignorieren') neuStand = 'ignoriert';
      else if (w === 'grund') neuStand = 'grund';
      else neuStand = null;
      const e = { id: f.id, stand: neuStand };
      const form = formular[f.id];
      if (form && w === 'grund') {
        // Nur Felder, die vom jetzigen Stand abweichen; leer = wie erkannt (Feld entfällt in runner.json).
        const leer = (x) => String(x || '').trim() || null;
        const werte = { dienst: DIENST_WAHL.includes(form.dienst) ? form.dienst : 'unbekannt', name: leer(form.name), unit: leer(form.unit), log: leer(form.log) };
        const jetzt = f.neu ? { dienst: null, name: null, unit: null, log: null } : { dienst: f.dienst, name: f.name, unit: f.unit || null, log: z.log || null };
        for (const k of ['dienst', 'name', 'unit', 'log']) if (werte[k] !== jetzt[k]) e[k] = werte[k];
      }
      if (neuStand !== alt || Object.keys(e).length > 2) liste.push(e);
    }
    return liste;
  }

  /* Zeilen von „Fertig“: je entschiedenem Fund {id, name, dienst, art: 'ok'|'grund'|'aus', stand:
     'angebunden'|'grund'|'ignoriert', detail: 'token'|'server'|'grund'|null}. Offene fehlen (wie im Design). */
  function zusammenfassung(funde, wahl, { zu = {}, angebunden = {} } = {}) {
    const zeilen = [];
    for (const f of funde) {
      const w = wahl[f.id];
      if (w === 'offen') continue;
      const basis = { id: f.id, name: f.name, dienst: f.dienst };
      if (f.einstufung === 'voll' && w === 'an') {
        if (!zu[f.id] && angebunden[f.id]) zeilen.push({ ...basis, art: 'ok', stand: 'angebunden', detail: f.primaer ? 'token' : 'server' });
        else zeilen.push({ ...basis, art: 'grund', stand: 'grund', detail: 'grund' });
      } else if (w === 'grund') {
        zeilen.push({ ...basis, art: 'grund', stand: 'grund', detail: 'grund' });
      } else {
        zeilen.push({ ...basis, art: 'aus', stand: 'ignoriert', detail: null });
      }
    }
    return zeilen;
  }

  /* Hat „Neu erkennen“ etwas geändert? (andere IDs oder andere Stände) */
  function gleicheFunde(a, b) {
    const s = (l) => (l || []).map((f) => `${f.id}:${f.dienst}:${f.einstufung}`).sort().join('|');
    return s(a) === s(b);
  }

  /* Nächster bzw. vorheriger Schritt: ohne Runner zum Anbinden von 3 direkt zu 5 und zurück. */
  const weiterVon = (schritt, anzahlAnbinden) => (schritt === 3 && !anzahlAnbinden ? 5 : Math.min(5, schritt + 1));
  const zurueckVon = (schritt, anzahlAnbinden) => (schritt === 5 && !anzahlAnbinden ? 3 : Math.max(1, schritt - 1));

  return { DIENSTE, DIENST_WAHL, GRAD, dienstName, alsId, startWahl, mischeWahl, stand, summe, anbinden, orgAus,
    tokenSeite, pruefeFormular, eintraege, zusammenfassung, gleicheFunde, weiterVon, zurueckVon };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = EINR;
