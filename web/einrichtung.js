/* Runner-Monitor – Ersteinrichtung im Browser (Design 0.8.0: Setup-Web, #96).
   Schritte: 1 Code · 2 Zugang · 3 Runner · 4 Anbinden · 5 Fertig → Anmeldung. Ansprache „Sie“ (E-10).
   Logik ohne DOM (Wahl, Zusammenfassung, Einträge) in einrichtung-runner.js (EINR), Texte hier mit t().
   Zugangsdaten (E-22): Ein Token-Feld gibt es nur für den GitHub-Runner des Monitors (Weg seit 0.4.0);
   alle anderen Runner bekommen ihre Zugangsdaten auf der VM (einrichten.sh zugang <runner>). */
'use strict';

(() => {
  const { $, IC, esc, t } = RM;
  I18N.wendeAn(); RM.sprachKnopf($('sprache'));
  document.title = `${t('Einrichtung')} · Runner-Monitor`;
  const TITEL = [t('Code'), t('Zugang'), t('Runner'), t('Anbinden'), t('Fertig')];
  const SKRIPT = 'sudo /opt/runner-monitor/aktuell/einrichten.sh';
  const DOKU = 'https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/blob/main/docs/FUNKTIONSWEISE.md';
  const E = {
    codeOk: false, schritt: 1, pruefung: {}, runnerAnzahl: null, nutzer: 'admin', zugang: false, fertig: false,
    // Schritt 3
    geladen: false, ladeFehler: false, funde: [], hand: [], zeit: null, vm: '', gh: {},
    wahl: {}, begr: {}, form: null, formWerte: {}, formFehler: {}, formular: {}, erk: 'ruhe', erkZeit: null, ohneRunner: false,
    // Schritt 4 – Tokens stehen nie hier, nur im Feld
    zu: {}, pruef: {}, org: {}, angebunden: {},
  };

  const ICO = {
    ok: '<svg class="ok" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="8" r="6.5"/><path d="M5.2 8.2l1.9 1.9 3.7-4"/></svg>',
    warn: '<svg class="warn" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 1.9l6.4 11.3H1.6z"/><path d="M8 6.3v3.2M8 11.4v.1"/></svg>',
    x: '<svg class="fehler" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="6.5"/><path d="M5.8 5.8l4.4 4.4M10.2 5.8l-4.4 4.4"/></svg>',
    aus: '<svg class="mut" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="6.5"/><path d="M5 8h6"/></svg>',
    grund: '<svg class="mut" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="6.5"/><path d="M8 4.8V8l2 1.3"/></svg>',
    info: '<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="6.5"/><path d="M8 7.2v4M8 4.9v.1"/></svg>',
    neu: '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13.5 8a5.5 5.5 0 11-1.6-3.9"/><path d="M12.2 1.8v2.6H9.6"/></svg>',
    dreh: '<svg class="dreh" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="M8 1.8a6.2 6.2 0 106.2 6.2"/></svg>',
    lupe: '<svg class="mut" viewBox="0 0 16 16" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" aria-hidden="true"><circle cx="7" cy="7" r="4.6"/><path d="M10.4 10.4l3.6 3.6"/></svg>',
    haken: `<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-label="${t('erledigt')}" role="img"><path d="M3.5 8.4l3 3 6-6.6"/></svg>`,
    fertig: '<svg class="fertig-ic" viewBox="0 0 16 16" width="44" height="44" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="8" r="6.6"/><path d="M5.2 8.2l1.9 1.9 3.7-4"/></svg>',
  };
  const ERG = {  // Ergebnisliste „Verbindung prüfen“: Symbol mit Text für Screenreader (Design)
    ok: ICO.ok.replace('aria-hidden="true"', `role="img" aria-label="${t('erfüllt')}"`),
    warn: ICO.warn.replace('aria-hidden="true"', `role="img" aria-label="${t('Hinweis')}"`),
    x: ICO.x.replace('aria-hidden="true"', `role="img" aria-label="${t('Fehler')}"`),
  };
  const zeile = (art, html) => `<div class="zeile">${ICO[art]}<span>${html}</span></div>`;
  const listenZeile = (art, titel, text) => `<div class="zeile">${ICO[art]}<b>${titel}</b><span class="mut">${text}</span></div>`;
  const meldung = (text) => `<div class="meldung-box fehler" role="alert">${ICO.x}<span>${esc(text)}</span></div>`;
  const plak = (d) => `<span class="plak">${esc(d === 'unbekannt' || !EINR.DIENSTE[d] ? t('unbekannt') : EINR.dienstName(d))}</span>`;
  const codeblock = (code) => `<div class="codeblock"><span>${esc(code)}</span><button type="button" data-aktion="kopieren" data-code="${esc(code)}">${t('Kopieren')}</button></div>`;
  const serverKurz = (s) => String(s || '').replace(/^https?:\/\//, '');

  /* Server-Antworten lesen (GET), wirft nie */
  async function hole(pfad) {
    try {
      const r = await fetch(pfad, { credentials: 'same-origin' });
      return { ok: r.ok, status: r.status, daten: r.ok ? await r.json() : {} };
    } catch (e) { return { ok: false, status: 0, daten: {} }; }
  }
  const warte = (ms) => new Promise((ok) => setTimeout(ok, ms));

  function kopf() {
    const p = E.pruefung || {};
    $('kopf-icon').innerHTML = IC.server();
    $('kopf-host').textContent = p.vm ? `${p.vm} · ${location.host}` : location.host;
  }

  function stepper() {
    $('stepper').innerHTML = TITEL.map((titel, i) => {
      const nr = i + 1, cls = nr < E.schritt ? 'fertig' : nr === E.schritt ? 'aktiv' : '';
      return `${i ? '<span class="st-linie"></span>' : ''}<span class="st ${cls}"${nr === E.schritt ? ' aria-current="step"' : ''}><span class="st-nr">${nr < E.schritt ? ICO.haken : nr}</span><span class="st-text">${titel}</span></span>`;
    }).join('');
  }

  const alleFunde = () => [...E.funde, ...E.hand.filter((h) => !E.funde.some((f) => f.id === h.id))];
  const bloecke = () => EINR.anbinden(alleFunde(), E.wahl);
  const vmName = () => E.vm || (E.pruefung || {}).vm || 'runner-vm';
  const eyebrow = (nr) => `<div class="eyebrow">${t('Schritt {nr} von 5', { nr })}</div>`;

  /* ------------------------------------------------------------ Schritt 1 und 2 */

  function s1(fehler) {
    const p = E.pruefung || {}, r = p.runner || {}, fw = p.firewall || {}, port = esc(p.port || 8090);
    let runnerZeile;
    if (E.runnerAnzahl != null) {
      runnerZeile = E.runnerAnzahl > 0
        ? zeile('ok', E.runnerAnzahl === 1 ? t('1 Runner gefunden – Auswahl im Schritt „Runner“') : t('{n} Runner gefunden – Auswahl im Schritt „Runner“', { n: E.runnerAnzahl }))
        : zeile('warn', t('Kein Runner gefunden – Wege im Schritt „Runner“'));
    } else {
      runnerZeile = r.gefunden ? zeile('ok', r.aktiv === false ? t('Runner {name} gefunden, Dienst nicht aktiv', { name: `<b>&#160;${esc(r.name || '')}&#160;</b>` }) : t('Runner {name} gefunden, Dienst aktiv', { name: `<b>&#160;${esc(r.name || '')}&#160;</b>` }))
        : zeile('warn', t('Kein GitHub-Runner gefunden, der Monitor zeigt dann nur die VM. Später einrichten: {befehl}', { befehl: `<code>${SKRIPT} runner</code>` }));
    }
    const erledigt = p.zeit ? `<div class="erkannt"><div class="erkannt-titel">${t('Vom Skript erledigt')}</div>
        ${runnerZeile}
        ${zeile('ok', t('Monitor-Dienst läuft als eigener Benutzer, nicht als root'))}
        ${fw.aktiv ? zeile('ok', t('Firewall aktiv: Port {port} nur aus dem lokalen Netz{netz}, SSH bleibt erlaubt', { port, netz: fw.netz ? ' ' + esc(fw.netz) : '' })) : zeile('warn', t('Firewall (ufw) nicht aktiv: Port {port} ist für alle erreichbar, die die VM erreichen', { port }))}
      </div>` : '';
    return `<section aria-label="${t('Schritt 1: Einrichtungscode')}" class="karte-inhalt">
      ${eyebrow(1)}
      <h1>${t('Einrichtung abschließen')}</h1>
      <p class="einl">${t('Das Skript auf der VM ist durchgelaufen. Geben Sie den Einrichtungscode ein, den es am Ende angezeigt hat. So kann niemand sonst im Netz diesen Monitor übernehmen.')}</p>
      ${erledigt}${fehler || ''}
      <div class="feld">
        <label for="code">${t('Einrichtungscode')}</label>
        <input id="code" class="gross" placeholder="XXXX-XXXX" autocomplete="one-time-code" autocapitalize="characters" spellcheck="false" maxlength="9" required>
        <span class="feld-hinweis">${t('Code verloren oder abgelaufen? Neuen Code auf der VM anzeigen:')} <code>${SKRIPT} code</code></span>
      </div>
      <div class="fuss"><span class="mut fuss-text">${t('Der Code gilt 60 Minuten.')}</span><span class="luecke"></span><button type="submit" class="knopf primaer">${t('Weiter|schritt')}</button></div>
    </section>`;
  }

  function s2(fehler) {
    return `<section aria-label="${t('Schritt 2: Zugang schützen')}" class="karte-inhalt">
      ${eyebrow(2)}
      <h1>${t('Zugang schützen')}</h1>
      <p class="einl">${t('Der Monitor ist nur mit Benutzername und Passwort erreichbar. Damit melden Sie sich gleich nach der Einrichtung an. Auf Wunsch bleibt der Browser 30 Tage angemeldet.')}</p>
      ${fehler || ''}
      ${E.zugang ? `<div class="erkannt">${zeile('ok', t('Zugang {nutzer} ist angelegt. Ändern später mit {befehl}.', { nutzer: `<b>&#160;${esc(E.nutzer)}&#160;</b>`, befehl: `<code>${SKRIPT} passwort</code>` }))}</div>` : `<div class="breit-420">
        <div class="feld"><label for="nutzer">${t('Benutzername')}</label><input id="nutzer" autocomplete="username" autocapitalize="none" spellcheck="false" maxlength="64" value="${esc(E.nutzer)}" required></div>
        <div class="feld"><label for="pw">${t('Passwort')}</label><input id="pw" type="password" autocomplete="new-password" maxlength="128" required>
          <div class="staerke" id="staerke" aria-hidden="true"><span></span><span></span><span></span><span></span></div>
          <span class="feld-hinweis" id="pw-hinweis">${t('Mindestens 12 Zeichen.')}</span>
        </div>
        <div class="feld"><label for="pw2">${t('Passwort wiederholen')}</label><input id="pw2" type="password" autocomplete="new-password" maxlength="128" required>
          <span class="feld-hinweis" id="pw2-hinweis">&#160;</span>
        </div>
      </div>`}
      <p class="feld-hinweis hinweis-hash">${t('Auf der VM wird nur ein Hash gespeichert, nur für root lesbar. Ändern später mit {befehl}.', { befehl: `<code>${SKRIPT} passwort</code>` })}</p>
      <div class="fuss"><button type="button" class="knopf" data-aktion="zurueck">${t('Zurück')}</button><span class="luecke"></span><button type="submit" class="knopf primaer">${t('Weiter|schritt')}</button></div>
    </section>`;
  }

  /* ------------------------------------------------------------ Schritt 3: Runner */

  const GRAD_TEXT = () => ({ sicher: t('sicher'), wahrscheinlich: t('wahrscheinlich'), unklar: t('unklar') });
  const ART_TEXT = () => ({ voll: t('vollständig unterstützt'), teil: t('erkannt, noch nicht unterstützt'), unbekannt: t('unbekannt') });
  const STAND_TEXT = () => ({ anbinden: t('wird angebunden'), ignoriert: t('ignoriert'), grund: t('Grundüberwachung'), offen: t('Entscheidung offen') });
  const DIENST_OPTION = (d) => (d === 'unbekannt' ? t('anderer') : EINR.dienstName(d));

  function erkText() {
    const z = E.erkZeit || E.zeit, um = z ? RM.hm(z) : '';
    if (E.erk === 'laeuft') return t('Suche Runner …');
    if (E.erk === 'zeit') return t('Die Erkennung antwortet nicht. Bitte später erneut versuchen.');
    if (E.erk === 'fertig') return t('Keine Änderung · geprüft um {zeit}', { zeit: um });
    if (!z) return t('Noch keine Erkennung. Der Monitor sucht beim Start und alle 6 Stunden.');
    const n = alleFunde().length;
    if (!n) return t('Erkannt um {zeit}', { zeit: um });
    return n === 1 ? t('1 Runner gefunden · erkannt um {zeit}', { zeit: um }) : t('{n} Runner gefunden · erkannt um {zeit}', { n, zeit: um });
  }

  function formularHtml(f) {
    const w = E.formWerte[f.id] || {}, fe = E.formFehler[f.id] || {}, id = esc(f.id);
    const opt = EINR.DIENST_WAHL.map((d) => `<option value="${d}"${(w.dienst || 'unbekannt') === d ? ' selected' : ''}>${esc(DIENST_OPTION(d))}</option>`).join('');
    const hinweis = (feld, text) => (fe[feld] ? `<span class="feld-hinweis warn" id="f-${id}-${feld}-h">${text}</span>` : '');
    const fehlt = (feld) => (fe[feld] ? ` class="falsch${feld === 'name' ? '' : ' mono'}" aria-invalid="true" aria-describedby="f-${id}-${feld}-h"` : (feld === 'name' ? '' : ' class="mono"'));
    return `<div class="zuordnen-form" role="group" aria-label="${t('Zuordnen')}" data-id="${id}">
      <div class="feld"><label for="f-${id}-dienst">${t('Dienst')}</label><select id="f-${id}-dienst" data-form="dienst">${opt}</select></div>
      <div class="feld"><label for="f-${id}-name">${t('Anzeigename')}</label><input id="f-${id}-name" data-form="name" value="${esc(w.name || '')}" maxlength="64" autocapitalize="none" spellcheck="false"${fehlt('name')}>${hinweis('name', fe.name === 'doppelt' ? t('Diesen Namen hat schon ein anderer Runner.') : t('Nur Buchstaben, Ziffern und . _ @ + - (höchstens 64 Zeichen).'))}</div>
      <div class="feld"><label for="f-${id}-unit">${t('systemd-Unit')}</label><input id="f-${id}-unit" data-form="unit" value="${esc(w.unit || '')}" placeholder="buildagent.service" maxlength="200" autocapitalize="none" spellcheck="false"${fehlt('unit')}>${hinweis('unit', t('Erwartet wird ein Name wie buildagent.service.'))}</div>
      <div class="feld"><label for="f-${id}-log">${t('Log-Pfad')}</label><input id="f-${id}-log" data-form="log" value="${esc(w.log || '')}" placeholder="${t('leer = Journal der Unit')}" maxlength="400" autocapitalize="none" spellcheck="false"${fehlt('log')}>${fe.log ? hinweis('log', t('Nur eine .log-Datei unter /var/log, /opt oder /srv.')) : `<span class="feld-hinweis">${t('Leer lassen, um das Journal der Unit zu zeigen.')}</span>`}</div>
      <div class="zuordnen-fuss"><button type="button" class="knopf klein primaer" data-aktion="form-speichern" data-id="${id}">${t('Zuordnung speichern')}</button><button type="button" class="knopf klein" data-aktion="form-abbrechen" data-id="${id}">${t('Abbrechen')}</button></div>
    </div>`;
  }

  function fundHtml(f) {
    const w = E.wahl[f.id], id = esc(f.id), bo = !!E.begr[f.id], fo = E.form === f.id;
    const st = EINR.stand(f, w), merk = f.merkmale || [];
    let aktion = '';
    if (f.einstufung === 'voll') {
      const an = w === 'an';
      aktion = `<div class="aktion"><span class="schalter-z"><button type="button" role="switch" class="schalter${an ? ' an' : ''}" aria-checked="${an}" aria-label="${t('Übernehmen')}" data-aktion="schalter" data-id="${id}"><span></span></button>${t('Übernehmen')}</span><span class="aktion-text">${an ? t('Zugangsdaten im nächsten Schritt „Anbinden“') : t('Wird nicht überwacht')}</span></div>`;
    } else if (f.einstufung === 'teil') {
      const knopf = (wert, text) => `<button type="button" role="radio" class="${w === wert ? 'an' : ''}" aria-checked="${w === wert}" data-aktion="${wert}" data-id="${id}">${text}</button>`;
      aktion = `<div class="einr-hinweis warn">${ICO.info}<span class="einr-hinweis-text">${t('Nur Grundüberwachung: Dienst, CPU, RAM, Platte, Log, Neustarts. Jobs und Schritte fehlen.')} <a href="${DOKU}" rel="noopener" target="_blank">${t('Wie ein Anbieter ergänzt wird ↗')}</a></span></div>
        <div class="aktion"><div class="wahl" role="radiogroup" aria-label="${t('Überwachung von {name}', { name: esc(f.name) })}">${knopf('grund', t('Grundüberwachung'))}${knopf('ignorieren', t('Ignorieren'))}</div></div>`;
    } else if (fo) {
      aktion = formularHtml(f);
    } else if (w === 'grund') {
      const fw = E.formular[f.id] || {};
      aktion = `<div class="aktion"><span class="aktion-text">${t('Zugeordnet: {dienst} · {unit} · Grundüberwachung', { dienst: esc(DIENST_OPTION(fw.dienst || f.dienst || 'unbekannt')), unit: esc(fw.unit || f.unit || '–') })}</span><button type="button" class="link-knopf" data-aktion="zuordnen" data-id="${id}">${t('Ändern')}</button></div>`;
    } else if (w === 'ignorieren') {
      aktion = `<div class="aktion"><span class="aktion-text">${t('Wird ignoriert und nicht angezeigt.')}</span><button type="button" class="link-knopf" data-aktion="offen" data-id="${id}">${t('Rückgängig')}</button></div>`;
    } else {
      aktion = `<div class="aktion"><button type="button" class="knopf klein primaer" data-aktion="zuordnen" data-id="${id}">${t('Zuordnen')}</button><button type="button" class="knopf klein" data-aktion="ignorieren" data-id="${id}">${t('Ignorieren')}</button><span class="aktion-text">${t('Dienst unklar – zuordnen, dann wird er mit Grundüberwachung angezeigt.')}</span></div>`;
    }
    const begr = merk.length ? `<div><button type="button" class="link-knopf" data-aktion="begr" data-id="${id}" aria-expanded="${bo}">${IC.chev(bo)}${bo ? t('Begründung ausblenden ({n} Merkmale)', { n: merk.length }) : t('Begründung ({n} Merkmale)', { n: merk.length })}</button></div>
      ${bo ? `<ul class="begr">${merk.map((m) => `<li>${esc(m)}</li>`).join('')}</ul>` : ''}` : '';
    return `<article class="fund${bo || fo ? ' offen-e' : ''}" aria-label="${esc(f.name)}" data-id="${id}">
      <div class="fund-kopf"><span class="fund-name">${esc(f.name)}</span>${plak(f.dienst)}<span class="pill ${EINR.GRAD[f.grad] || 'neutral'}">${esc(GRAD_TEXT()[f.grad] || f.grad || '')}</span><span class="fund-stand ${st.cls}">${STAND_TEXT()[st.art]}</span></div>
      <div class="fund-meta"><span>${t('Server')} <b>${esc((f.dienst === 'github' ? serverKurz(f.server) : f.server) || '–')}</b></span><span>${t('Version')} <b>${esc(f.version || '–')}</b></span><span>${t('Einstufung')} <b class="fund-art">${ART_TEXT()[f.einstufung] || ''}</b></span></div>
      ${begr}
      ${aktion}
    </article>`;
  }

  function leerHtml() {
    return `<div class="leer-box">
      ${ICO.lupe}
      <div class="leer-titel">${t('Kein Runner gefunden')}</div>
      <div class="mut leer-text">${t('Auf {vm} läuft kein Dienst, der wie ein CI-Runner aussieht. Der Monitor kann trotzdem die VM überwachen.', { vm: esc(vmName()) })}</div>
      <div class="wege">
        <div class="weg"><span class="weg-titel">${t('Runner einrichten')}</span><span class="feld-hinweis">${t('Auf der VM ausführen, danach „Neu erkennen“.')}</span>${codeblock(`${SKRIPT} runner`)}</div>
        <div class="weg"><span class="weg-titel">${t('Von Hand zuordnen')}</span><span class="feld-hinweis">${t('Läuft der Runner unter einem ungewöhnlichen Namen? Unit und Log angeben.')}</span><button type="button" class="knopf klein" data-aktion="hand">${t('Zuordnen')}</button></div>
        <div class="weg"><span class="weg-titel">${t('Ohne Runner fortfahren')}</span><span class="feld-hinweis">${t('Nur die VM überwachen: CPU, RAM, Netz, Prozesse, Platten.')}</span><button type="button" class="knopf klein" data-aktion="ohne-runner">${t('Nur VM überwachen')}</button></div>
      </div>
    </div>`;
  }

  function s3(fehler) {
    const funde = alleFunde();
    let inhalt;
    if (!E.geladen) inhalt = E.ladeFehler ? meldung(t('Die Funde konnten nicht geladen werden.')) : `<p class="mut">${t('Funde werden geladen …')}</p>`;
    else inhalt = funde.length ? `<div class="funde">${funde.map(fundHtml).join('')}</div>` : leerHtml();
    const z = EINR.summe(funde, E.wahl), teile = [];
    if (z.anbinden) teile.push(t('{n} anbinden', { n: z.anbinden }));
    if (z.grund) teile.push(t('{n} Grundüberwachung', { n: z.grund }));
    if (z.offen) teile.push(t('{n} offen', { n: z.offen }));
    const laeuft = E.erk === 'laeuft';
    return `<section aria-label="${t('Schritt 3: Runner erkennen')}" class="karte-inhalt">
      ${eyebrow(3)}
      <h1>${t('Welche Runner laufen auf dieser VM?')}</h1>
      <p class="einl">${t('Der Monitor hat Dienste, Prozesse und Konfigurationsdateien auf {vm} durchsucht. Prüfen Sie die Funde und legen Sie je Runner fest, wie er überwacht wird.', { vm: esc(vmName()) })}</p>
      ${fehler || ''}
      <div class="werkzeug"><button type="button" class="knopf klein" data-aktion="erkennen"${laeuft ? ' disabled' : ''}>${laeuft ? ICO.dreh : ICO.neu}${t('Neu erkennen')}</button><span class="werkzeug-text" role="status">${esc(erkText())}</span></div>
      <div class="koerper">${inhalt}</div>
      <div class="fuss"><button type="button" class="knopf" data-aktion="zurueck">${t('Zurück')}</button><span class="luecke"></span><span class="mut fuss-text">${teile.join(' · ')}</span><button type="submit" class="knopf primaer">${t('Weiter|schritt')}</button></div>
    </section>`;
  }

  /* ------------------------------------------------------------ Schritt 4: Anbinden */

  function pruefHtml(id) {
    const p = E.pruef[id];
    if (!p || !p.ergebnisse) return '';
    return p.ergebnisse.map((x) => `<div class="zeile">${x.ok ? ERG.ok : x.warn ? ERG.warn : ERG.x}<span>${esc(RM.serverText(x, 'text'))}</span></div>`).join('');
  }
  const pruefText = (id) => { const p = E.pruef[id]; return p && p.laeuft ? t('Prüfe …') : p && p.ergebnisse ? t('Erneut prüfen') : t('Verbindung prüfen'); };

  function anleitung(f) {
    const liste = (punkte) => `<ol>${punkte.map((p) => `<li>${p}</li>`).join('')}</ol>`;
    const vm = !f.primaer;
    if (f.dienst === 'github') {
      return `<div class="anl-titel">${t('So erstellen Sie das Token')}</div>${liste([
        t('Auf GitHub ein „Fine-grained token“ anlegen (Link unten).'),
        t('Resource owner: die Organisation. Repository access: {alle}.', { alle: '<b>All repositories</b>' }),
        t('Repository-Rechte: {a} und {m} jeweils „Read-only“.', { a: '<b>Actions</b>', m: '<b>Metadata</b>' }),
        t('Optional Organisations-Recht {r} „Read-only“ für den Online-Status.', { r: '<b>Self-hosted runners</b>' }),
        vm ? t('Ablauf z. B. 90 Tage. Dann den Befehl links auf der VM ausführen und das Token dort einfügen.') : t('Ablauf z. B. 90 Tage. Der Monitor warnt 14 Tage vorher. Token links einfügen.'),
      ])}<a href="https://github.com/settings/personal-access-tokens/new" rel="noopener" target="_blank">${t('Token-Seite auf GitHub öffnen ↗')}</a>`;
    }
    const seite = EINR.tokenSeite(f);
    const link = seite ? `<a href="${esc(seite.url)}" rel="noopener" target="_blank">${t('Token-Seite auf {host} öffnen ↗', { host: esc(seite.host) })}</a>` : '';
    if (f.dienst === 'gitlab') {
      return `<div class="anl-titel">${t('So erstellen Sie das Token')}</div>${liste([
        t('In GitLab anmelden: Benutzereinstellungen › Zugriffstokens › „Neues Token hinzufügen“.'),
        t('Bereich {s} wählen und ein Ablaufdatum setzen.', { s: '<b>read_api</b>' }),
        t('Den Befehl links auf der VM ausführen und das Token dort einfügen (die Eingabe bleibt unsichtbar).'),
      ])}${link}`;
    }
    return `<div class="anl-titel">${t('So erstellen Sie das Token')}</div>${liste([
      t('Auf dem Server anmelden: Einstellungen › Anwendungen › „Neues Token generieren“.'),
      t('Name z. B. runner-monitor, Ablaufdatum setzen.'),
      t('Rechte: repository und organization jeweils „Lesen“ (genaue Liste folgt aus der API-Prüfung).'),
      t('Optional: Zugriff auf Actions-Runner der Organisation „Lesen“ für den Online-Status.'),
      t('Den Befehl links auf der VM ausführen und das Token dort einfügen (die Eingabe bleibt unsichtbar).'),
    ])}${link}`;
  }

  function felderHtml(f) {
    const id = esc(f.id), knopf = `<button type="button" class="knopf klein" data-aktion="pruefen" data-id="${id}"${(E.pruef[f.id] || {}).laeuft ? ' disabled' : ''}>${pruefText(f.id)}</button><div class="pruef" role="status" data-pruef="${id}">${pruefHtml(f.id)}</div>`;
    if (f.primaer) {
      const aus = EINR.orgAus(f.server), org = E.org[f.id] != null ? E.org[f.id] : (aus || E.gh.org || '');
      const erkannt = !!aus && org === aus;
      const gespeichert = !!E.angebunden[f.id];
      return `<div class="feld"><label for="org-${id}">${t('Organisation')}</label><input id="org-${id}" data-feld="org" data-id="${id}" autocapitalize="none" spellcheck="false" maxlength="39" value="${esc(org)}" placeholder="beispiel-org">${erkannt ? `<span class="feld-hinweis">${t('Aus der Runner-Konfiguration erkannt.')}</span>` : ''}</div>
        <div class="feld"><label for="token-${id}">${t('Fine-grained Token')}</label><input id="token-${id}" data-feld="token" data-id="${id}" class="mono" type="password" placeholder="github_pat_…" autocomplete="off" spellcheck="false">${gespeichert ? `<span class="feld-hinweis">${t('Ein Token ist hinterlegt. Leer lassen, um es zu behalten.')}</span>` : ''}</div>
        ${knopf}`;
    }
    return `<div class="feld"><label for="server-${id}">${t('Server')}</label><input id="server-${id}" class="mono" readonly value="${esc(f.server || '')}" placeholder="–"><span class="feld-hinweis">${t('Vorschlag aus der Erkennung. Server, Organisation und Token tragen Sie aus Sicherheitsgründen auf der VM ein:')}</span></div>
      ${codeblock(`${SKRIPT} zugang ${f.id}`)}
      ${knopf}`;
  }

  function s4(fehler) {
    const liste = bloecke(), einzeln = liste.length <= 1, nur = einzeln ? liste[0] : null;
    const html = liste.map((f) => {
      const id = esc(f.id);
      if (!einzeln && E.zu[f.id]) {
        return `<div class="block zu">${`<span class="fund-name">${esc(f.name)}</span>`}${plak(f.dienst)}<span class="mut klein-text">${t('Ohne Anbindung: nur Grundüberwachung')}</span><span class="luecke"></span><button type="button" class="link-knopf" data-aktion="doch" data-id="${id}">${t('Doch anbinden')}</button></div>`;
      }
      const zwei = `<div class="zwei"><div>${felderHtml(f)}</div><div class="anl">${anleitung(f)}</div></div>`;
      if (einzeln) return zwei;
      return `<div class="block" data-id="${id}"><div class="block-kopf"><span class="fund-name">${esc(f.name)}</span>${plak(f.dienst)}<span class="mut mono block-server">${esc(serverKurz(f.server))}</span><span class="luecke"></span><button type="button" class="link-knopf" data-aktion="zu" data-id="${id}">${t('Überspringen – nur Grundüberwachung')}</button></div>${zwei}</div>`;
    }).join('');
    const dienst = nur ? EINR.dienstName(nur.dienst) : '';
    return `<section aria-label="${t('Schritt 4: Anbinden')}" class="karte-inhalt">
      ${eyebrow(4)}
      <h1>${nur ? t('{dienst} anbinden', { dienst: esc(dienst) }) : t('Runner anbinden')}<span class="optional">${t('optional')}</span></h1>
      <p class="einl">${nur ? t('Mit einem nur lesenden Token zeigt der Monitor, welche Jobs je Repository laufen und warten, und ob {dienst} den Runner sieht. Ohne Token funktioniert alles andere trotzdem.', { dienst: esc(dienst) }) : t('Je Runner ein nur lesendes Token für den jeweiligen Dienst. Damit zeigt der Monitor Jobs, Schritte und den Online-Status. Jeder Runner lässt sich einzeln überspringen.')}</p>
      ${fehler || ''}
      <div class="koerper">${html}</div>
      <div class="fuss"><button type="button" class="knopf" data-aktion="zurueck">${t('Zurück')}</button><span class="luecke"></span>${einzeln ? `<button type="button" class="knopf" data-aktion="ohne-anbindung">${t('Ohne Anbindung fortfahren')}</button>` : ''}<button type="submit" class="knopf primaer">${t('Weiter|schritt')}</button></div>
      <p class="feld-hinweis hinweis-nachholen">${t('Später auf der VM nachholen oder ändern:')} <code>${SKRIPT} zugang &lt;runner&gt;</code></p>
    </section>`;
  }

  /* ------------------------------------------------------------ Schritt 5: Fertig */

  function s5(fehler) {
    const p = E.pruefung || {}, fw = p.firewall || {}, port = esc(p.port || 8090);
    const funde = alleFunde(), zeilen = E.ohneRunner ? [] : EINR.zusammenfassung(funde, E.wahl, { zu: E.zu, angebunden: E.angebunden });
    const ICON = { ok: ICO.ok, grund: ICO.grund, aus: ICO.aus };
    const STAND = { angebunden: t('angebunden'), grund: t('Grundüberwachung'), ignoriert: t('ignoriert') };
    const detail = (z) => {
      if (z.detail === 'grund') return t('Dienst, Auslastung, Log');
      const a = E.angebunden[z.id] || {};
      if (z.detail === 'token') return `${esc(a.org || '')}${a.ablauf ? ' · ' + t('Token bis {d}', { d: RM.datum(a.ablauf) }) : ''}`;
      if (z.detail === 'server') return esc(serverKurz((funde.find((f) => f.id === z.id) || {}).server));
      return '';
    };
    let runner = zeilen.map((z) => `<div class="zeile">${ICON[z.art]}<b>${esc(z.name)}</b>${plak(z.dienst)}<span class="stand-text ${z.art === 'ok' ? 'ok' : 'mut'}">${STAND[z.stand]}</span><span class="mut">${detail(z)}</span></div>`).join('');
    if (!runner) runner = funde.length && !E.ohneRunner ? listenZeile('aus', t('Kein Runner übernommen'), t('offene Funde erscheinen mit Grundüberwachung')) : listenZeile('aus', t('Kein Runner gefunden'), t('der Monitor zeigt nur die VM'));
    return `<section aria-label="${t('Schritt 5: Fertig')}" class="karte-inhalt">
      ${ICO.fertig}
      <h1>${t('Alles eingerichtet')}</h1>
      <p class="einl">${t('Der Monitor läuft. Legen Sie die Adresse als Lesezeichen an. Auf einem zweiten Bildschirm kann die Seite dauerhaft offen bleiben.')}</p>
      ${fehler || ''}
      <div class="koerper">
        <div class="liste">
          ${listenZeile('ok', t('Zugang geschützt'), t('Benutzer {n}', { n: esc(E.nutzer) }))}
          ${fw.aktiv ? listenZeile('ok', t('Firewall aktiv'), fw.netz ? t('Port {port} nur aus {netz}', { port, netz: esc(fw.netz) }) : t('Port {port} nur aus dem lokalen Netz', { port })) : listenZeile('warn', t('Firewall nicht aktiv'), t('Port {port} ist für alle erreichbar, die die VM erreichen', { port }))}
        </div>
        <div class="erkannt-titel liste-titel">${t('Runner auf {vm}', { vm: esc(vmName()) })}</div>
        <div class="liste">${runner}</div>
      </div>
      <p class="feld-hinweis hinweis-ende">${t('Diese Einrichtung lässt sich nicht erneut im Browser aufrufen. Runner und Zugangsdaten ändern Sie später auf der VM mit {befehl}. Hilfe finden Sie im Monitor unter „Info & Hilfe“.', { befehl: `<code>${SKRIPT}</code>` })}</p>
      <div class="fuss"><button type="button" class="knopf" data-aktion="zurueck">${t('Zurück')}</button><span class="luecke"></span><button type="submit" class="knopf primaer" id="zum-monitor">${t('Zum Monitor anmelden')}</button></div>
    </section>`;
  }

  /* ------------------------------------------------------------ Zeichnen */

  function zeichne(fehler) {
    stepper();
    const k = $('karte');
    // Eingaben, die nicht im Zustand stehen (Token), über das Neuzeichnen retten – nur innerhalb dieses Aufrufs.
    const behalten = [...k.querySelectorAll('input[data-feld="token"]')].map((el) => [el.id, el.value]);
    k.innerHTML = [s1, s2, s3, s4, s5][E.schritt - 1](fehler);
    // Einblenden nur beim Wechsel des Schritts, nicht bei jeder Wahl im selben Schritt
    if (E.gezeichnet === E.schritt) k.querySelector('.karte-inhalt').classList.add('still');
    E.gezeichnet = E.schritt;
    for (const [id, wert] of behalten) { const el = $(id); if (el) el.value = wert; }
    verdrahte();
  }

  function zeichnePruef(id) {
    const ziel = document.querySelector(`[data-pruef="${CSS.escape(id)}"]`);
    if (ziel) ziel.innerHTML = pruefHtml(id);
    const knopf = document.querySelector(`[data-aktion="pruefen"][data-id="${CSS.escape(id)}"]`);
    if (knopf) { knopf.textContent = pruefText(id); knopf.disabled = !!(E.pruef[id] || {}).laeuft; }
  }

  async function gehe(n) {
    E.schritt = n;
    zeichne();
    if (n === 3 && !E.geladen) { await ladeRunner(); if (E.schritt === 3) zeichne(); }
    const k = document.querySelector('.karte-inhalt h1');
    if (k && n > 1) { k.setAttribute('tabindex', '-1'); k.focus({ preventScroll: true }); }
  }

  /* ------------------------------------------------------------ Daten */

  function uebernehme(d) {
    E.funde = Array.isArray(d.runner) ? d.runner : [];
    E.zeit = d.zeit || null;
    E.gh = d.github || {};
    E.vm = d.vm || E.vm;
    E.wahl = EINR.mischeWahl(alleFunde(), E.wahl);
    E.geladen = true; E.ladeFehler = false;
  }

  async function ladeRunner() {
    const r = await hole('/api/einrichtung/runner');
    if (r.ok) uebernehme(r.daten); else E.ladeFehler = true;
    return r;
  }

  async function erkennen() {
    if (E.erk === 'laeuft') return;
    const vorher = alleFunde().map((f) => ({ ...f }));
    E.erk = 'laeuft'; zeichne();
    const r = await RM.sende('/api/einrichtung/runner/erkennen', {});
    if (!r.ok) { E.erk = 'ruhe'; if (E.schritt === 3) zeichne(meldung(r.daten.fehler ? RM.serverText(r.daten) : t('Nicht gespeichert.'))); return; }
    const seit = r.daten.seit || Date.now() / 1000;
    for (let i = 0; i < 45; i++) {  // Sammler-Takt 2 s, Erkennung höchstens 60 s
      await warte(2000);
      const d = await hole('/api/einrichtung/runner');
      if (d.ok && d.daten.zeit && d.daten.zeit >= seit - 1) {
        uebernehme(d.daten);
        E.erkZeit = d.daten.zeit;
        E.erk = EINR.gleicheFunde(vorher, alleFunde()) ? 'fertig' : 'ruhe';
        if (E.schritt === 3) zeichne();
        return;
      }
    }
    E.erk = 'zeit';
    if (E.schritt === 3) zeichne();
  }

  /* Verbindung prüfen: mit eingegebenem Token im Webserver (nur gegen api.github.com, wie seit 0.4.0),
     ohne Token über den Sammler mit dem auf der VM hinterlegten Token (Ergebnis aus github.json). */
  async function pruefen(f) {
    const id = f.id;
    const org = (($(`org-${id}`) || {}).value || '').trim(), token = (($(`token-${id}`) || {}).value || '').trim();
    if (f.primaer && token) {
      if (!org) { E.pruef[id] = { ergebnisse: [{ fehler: true, text: t('Bitte Organisation und Token eingeben.') }] }; zeichnePruef(id); return false; }
      E.org[id] = org;
      E.pruef[id] = { laeuft: true }; zeichnePruef(id);
      const r = await RM.sende('/api/einrichtung/github/pruefen', { org, token });
      E.pruef[id] = { ok: !!(r.daten && r.daten.ok), ergebnisse: (r.daten && r.daten.ergebnisse) || [{ fehler: true, text: r.daten.fehler ? RM.serverText(r.daten) : t('Prüfung fehlgeschlagen.') }] };
      zeichnePruef(id);
      return E.pruef[id].ok;
    }
    E.pruef[id] = { laeuft: true }; zeichnePruef(id);
    const r = await RM.sende('/api/einrichtung/runner/pruefen', { id });
    if (r.ok && r.daten.fertig) { E.pruef[id] = { ok: !!r.daten.ok, ergebnisse: r.daten.ergebnisse || [] }; zeichnePruef(id); return E.pruef[id].ok; }
    if (!r.ok) { E.pruef[id] = { ergebnisse: [{ fehler: true, text: r.daten.fehler ? RM.serverText(r.daten) : t('Prüfung fehlgeschlagen.') }] }; zeichnePruef(id); return false; }
    const seit = r.daten.seit;
    for (let i = 0; i < 25; i++) {  // nächste Abfrage des Sammlers (Takt 2 s, Abfrage bis etwa 30 s)
      await warte(2000);
      const d = await hole('/api/einrichtung/runner');
      const gh = (d.daten && d.daten.github) || {};
      if (d.ok && gh.abgefragt && gh.abgefragt >= seit - 1 && gh.pruefung) {
        E.gh = gh;
        E.pruef[id] = { ok: !!gh.pruefung.ok, ergebnisse: gh.pruefung.ergebnisse || [] };
        if (gh.pruefung.ok) {
          const erst = (gh.pruefung.ergebnisse || [])[0] || {};
          E.angebunden[id] = { org: gh.org || '', ablauf: erst.ablauf || null };
        }
        zeichnePruef(id);
        return E.pruef[id].ok;
      }
    }
    E.pruef[id] = { ergebnisse: [{ fehler: true, text: t('Keine Antwort vom Sammler.') }] };
    zeichnePruef(id);
    return false;
  }

  /* ------------------------------------------------------------ Handlungen */

  async function weiter3() {
    const liste = EINR.eintraege(alleFunde(), E.wahl, E.formular);
    if (liste.length) {
      const r = await RM.sende('/api/einrichtung/runner/zuordnung', { runner: liste });
      if (!r.ok) { zeichne(meldung(r.daten.fehler ? RM.serverText(r.daten) : t('Nicht gespeichert.'))); return; }
      // Lokal nachziehen, damit „Zurück“ und erneutes „Weiter“ nichts doppelt schicken
      for (const e of liste) {
        const f = alleFunde().find((x) => x.id === e.id);
        if (!f) continue;
        const z = { ...(f.zuordnung || {}) };
        for (const [k, v] of Object.entries(e)) { if (k === 'id') continue; if (v === null) delete z[k]; else z[k] = v; }
        f.zuordnung = z;
        if (f.neu) f.neu = false;
        if (e.dienst) f.dienst = e.dienst;
        if ('unit' in e) f.unit = e.unit;
        if ('name' in e && e.name) f.name = e.name;
      }
    }
    gehe(EINR.weiterVon(3, bloecke().length));
  }

  async function weiter4() {
    const liste = bloecke(), einzeln = liste.length <= 1;
    for (const f of liste) {
      if (E.zu[f.id] || !f.primaer) continue;
      const org = (($(`org-${f.id}`) || {}).value || '').trim(), token = (($(`token-${f.id}`) || {}).value || '').trim();
      if (!token) {
        if (E.angebunden[f.id]) continue;
        zeichne(meldung(einzeln ? t('Bitte Organisation und Token eingeben – oder „Ohne Anbindung fortfahren“.') : t('Bitte Organisation und Token eingeben – oder „Überspringen – nur Grundüberwachung“.')));
        return;
      }
      if (!org) { zeichne(meldung(t('Bitte Organisation und Token eingeben.'))); return; }
      if (!(await pruefen(f))) return;
      const r = await RM.sende('/api/einrichtung/github/speichern', { org, token });
      if (!r.ok) { zeichne(meldung(r.daten.fehler ? RM.serverText(r.daten) : t('Nicht gespeichert.'))); return; }
      const erst = ((E.pruef[f.id] || {}).ergebnisse || [])[0] || {};
      E.angebunden[f.id] = { org, ablauf: erst.ablauf || null };
      E.org[f.id] = org;
      const feld = $(`token-${f.id}`); if (feld) feld.value = '';  // gespeichert: nicht länger im Feld halten
    }
    gehe(5);
  }

  function oeffneFormular(f) {
    const fw = E.formular[f.id] || {};
    E.form = f.id;
    E.formFehler[f.id] = {};
    E.formWerte[f.id] = {
      dienst: fw.dienst || (f.zuordnung || {}).dienst || (f.dienst && f.dienst !== 'unbekannt' ? f.dienst : 'unbekannt'),
      name: fw.name != null ? fw.name : (f.neu ? '' : f.name || ''),
      unit: fw.unit != null ? fw.unit : (f.unit || ''),
      log: fw.log != null ? fw.log : ((f.zuordnung || {}).log || ''),
    };
  }

  function speichereFormular(f) {
    const w = E.formWerte[f.id] || {};
    const fehler = EINR.pruefeFormular(w, !!f.neu);
    let ziel = f;
    if (f.neu && !fehler.name && !fehler.unit) {
      const neueId = EINR.alsId(String(w.name || '').trim() || String(w.unit || '').replace(/\.service$/, ''));
      if (E.funde.some((x) => x.id === neueId) || E.hand.some((x) => x !== f && x.id === neueId)) fehler.name = 'doppelt';
      else if (neueId !== f.id) {
        // Vorläufige ID des neuen Eintrags durch die endgültige ersetzen (wie erkennung.als_id)
        delete E.wahl[f.id]; delete E.formWerte[f.id];
        f.id = neueId; ziel = f;
        E.formWerte[neueId] = w;
      }
    }
    if (Object.keys(fehler).length) { E.formFehler[ziel.id] = fehler; E.form = ziel.id; return; }
    E.formular[ziel.id] = { ...w };
    if (ziel.neu) { ziel.name = String(w.name || '').trim() || ziel.id; ziel.unit = String(w.unit || '').trim(); ziel.dienst = w.dienst || 'unbekannt'; }
    E.wahl[ziel.id] = 'grund';
    E.form = null; E.formFehler[ziel.id] = {};
  }

  async function kopiere(knopf) {
    const text = knopf.dataset.code || '';
    let ok = false;
    try { if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); ok = true; } } catch (f) { ok = false; }
    if (!ok) {
      const feld = document.createElement('textarea');
      feld.value = text; feld.setAttribute('readonly', ''); feld.className = 'kopier-puffer';
      document.body.appendChild(feld); feld.select();
      try { ok = document.execCommand('copy'); } catch (f) { ok = false; }
      feld.remove();
    }
    knopf.textContent = ok ? t('Kopiert ✓') : t('Bitte markieren');
    clearTimeout(knopf._zeit); knopf._zeit = setTimeout(() => { knopf.textContent = t('Kopieren'); }, 1600);
  }

  function klick(e) {
    const el = e.target.closest('[data-aktion]');
    if (!el || el.disabled) return;
    const aktion = el.dataset.aktion, id = el.dataset.id, f = id ? alleFunde().find((x) => x.id === id) : null;
    const neu = (fokus) => { zeichne(); if (fokus) { const z = document.querySelector(fokus); if (z) z.focus(); } };
    const sel = (a) => `[data-aktion="${a}"][data-id="${CSS.escape(id || '')}"]`;
    switch (aktion) {
      case 'zurueck':
        if (E.schritt === 5 && E.ohneRunner) { E.ohneRunner = false; gehe(3); return; }
        gehe(E.schritt >= 3 ? EINR.zurueckVon(E.schritt, bloecke().length) : Math.max(1, E.schritt - 1));
        return;
      case 'kopieren': kopiere(el); return;
      case 'erkennen': erkennen(); return;
      case 'begr': E.begr[id] = !E.begr[id]; neu(sel('begr')); return;
      case 'schalter': E.wahl[id] = E.wahl[id] === 'an' ? 'aus' : 'an'; neu(sel('schalter')); return;
      case 'grund': E.wahl[id] = 'grund'; neu(sel('grund')); return;
      case 'ignorieren': E.wahl[id] = 'ignorieren'; if (E.form === id) E.form = null; neu(f && f.einstufung === 'teil' ? sel('ignorieren') : sel('offen')); return;
      case 'offen': E.wahl[id] = 'offen'; neu(sel('zuordnen')); return;
      case 'zuordnen': if (f) { oeffneFormular(f); neu(`#f-${CSS.escape(id)}-dienst`); } return;
      case 'form-abbrechen':
        E.form = null;
        if (f && f.neu && !E.formular[id]) { E.hand = E.hand.filter((h) => h !== f); delete E.wahl[id]; }
        neu(sel('zuordnen'));
        return;
      case 'form-speichern':
        if (f) { speichereFormular(f); const fehler = E.formFehler[f.id] || {}; const erstes = ['name', 'unit', 'log'].find((k) => fehler[k]); neu(erstes ? `#f-${CSS.escape(f.id)}-${erstes}` : `[data-aktion="zuordnen"][data-id="${CSS.escape(f.id)}"]`); }
        return;
      case 'hand': {
        const vorl = { id: `neu-${E.hand.length + 1}`, name: '', dienst: 'unbekannt', einstufung: 'unbekannt', grad: 'unklar', stand: 'offen', merkmale: [], neu: true, zuordnung: {} };
        E.hand.push(vorl); E.wahl[vorl.id] = 'offen'; oeffneFormular(vorl); E.formWerte[vorl.id].name = '';
        neu(`#f-${CSS.escape(vorl.id)}-dienst`);
        return;
      }
      case 'ohne-runner': E.ohneRunner = true; gehe(5); return;
      case 'zu': E.zu[id] = true; neu(sel('doch')); return;
      case 'doch': E.zu[id] = false; neu(sel('zu')); return;
      case 'ohne-anbindung': for (const b of bloecke()) E.zu[b.id] = true; gehe(5); return;
      case 'pruefen': if (f) pruefen(f); return;
      default:
    }
  }

  function eingabe(e) {
    const el = e.target;
    if (el.dataset.form) {
      const box = el.closest('[data-id]');
      if (!box) return;
      const w = E.formWerte[box.dataset.id] || (E.formWerte[box.dataset.id] = {});
      w[el.dataset.form] = el.value;
    } else if (el.dataset.feld === 'org') {
      E.org[el.dataset.id] = el.value.trim();
    }
  }

  /* Passwortstärke wie im Design: Länge, Groß/klein, Ziffer oder Sonderzeichen; unter 12 Zeichen höchstens 1 Punkt. */
  function staerke(pw) {
    const n = pw.length;
    let pkt = 0;
    if (n >= 8) pkt++; if (n >= 12) pkt++;
    if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) pkt++;
    if (/[0-9]/.test(pw) || /[^A-Za-z0-9]/.test(pw)) pkt++;
    if (n < 12) pkt = Math.min(pkt, 1);
    const text = n === 0 ? t('Mindestens 12 Zeichen.') : n < 12 ? t('Noch {n} Zeichen bis zur Mindestlänge.', { n: 12 - n }) : t('{stufe} · {n} Zeichen', { stufe: ['', t('Schwach'), t('In Ordnung'), t('Gut'), t('Stark')][pkt], n });
    return { pkt, text, warn: n > 0 && n < 12 };
  }

  let sendet = false;
  function verdrahte() {
    if (E.schritt === 1) {
      const c = $('code');
      c.addEventListener('input', () => {
        let v = c.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 8);
        if (v.length > 4) v = v.slice(0, 4) + '-' + v.slice(4);
        c.value = v; c.classList.remove('falsch');
      });
      c.focus();
    } else if (E.schritt === 2 && !E.zugang) {
      const pw = $('pw'), pw2 = $('pw2');
      const pruefe = () => {
        const s = staerke(pw.value);
        [...$('staerke').children].forEach((x, i) => x.classList.toggle('an', i < s.pkt));
        const h = $('pw-hinweis'); h.textContent = s.text; h.classList.toggle('warn', s.warn);
        const h2 = $('pw2-hinweis'), gleich = pw2.value.length > 0 && pw.value === pw2.value;
        h2.textContent = pw2.value.length === 0 ? ' ' : gleich ? t('✓ Stimmt überein') : t('Stimmt noch nicht überein');
        h2.classList.toggle('ok', gleich); h2.classList.toggle('warn', pw2.value.length > 0 && !gleich);
      };
      pw.addEventListener('input', pruefe); pw2.addEventListener('input', pruefe);
      $('nutzer').focus();
    }
  }

  async function absenden(e) {
    e.preventDefault();
    if (sendet) return;
    sendet = true;
    try {
      if (E.schritt === 1) {
        const c = $('code');
        if (E.codeOk && !c.value) { gehe(2); return; }  // schon angenommen (z. B. nach „Zurück“)
        if (c.value.replace('-', '').length !== 8) { c.classList.add('falsch'); return; }
        const r = await RM.sende('/api/einrichtung/code', { code: c.value });
        if (r.ok) { E.codeOk = true; gehe(2); } else zeichne(meldung(r.daten.fehler ? RM.serverText(r.daten) : t('Code nicht angenommen.')));
      } else if (E.schritt === 2) {
        if (E.zugang) { gehe(3); return; }
        const pw = $('pw'), pw2 = $('pw2');
        E.nutzer = $('nutzer').value.trim();
        if (!E.nutzer) { zeichne(meldung(t('Bitte einen Benutzernamen eingeben.'))); return; }
        if (pw.value.length < 12) { pw.classList.add('falsch'); pw.focus(); return; }
        if (pw.value !== pw2.value) { pw2.classList.add('falsch'); pw2.focus(); return; }
        const r = await RM.sende('/api/einrichtung/zugang', { nutzer: E.nutzer, passwort: pw.value });
        if (r.ok) { E.zugang = true; gehe(3); } else zeichne(meldung(r.daten.fehler ? RM.serverText(r.daten) : t('Zugang nicht angelegt.')));
      } else if (E.schritt === 3) {
        if (E.form) { const f = alleFunde().find((x) => x.id === E.form); if (f) { speichereFormular(f); zeichne(); return; } }
        await weiter3();
      } else if (E.schritt === 4) {
        await weiter4();
      } else {
        // Erst hier ist die Einrichtung abgeschlossen; bis dahin geht „Zurück“ noch.
        if (!E.fertig) { await RM.sende('/api/einrichtung/fertig'); E.fertig = true; }
        location.href = '/anmelden';
      }
    } finally { sendet = false; }
  }

  const karte = $('karte');
  karte.addEventListener('submit', absenden);
  karte.addEventListener('click', klick);
  karte.addEventListener('input', eingabe);
  karte.addEventListener('change', eingabe);

  hole('/api/einrichtung/status').then((r) => {
    const d = r.daten || {};
    E.pruefung = d.pruefung || {};
    E.runnerAnzahl = typeof d.runnerAnzahl === 'number' ? d.runnerAnzahl : null;
    if (d.codeGueltig) { E.codeOk = true; E.schritt = 2; }
    kopf(); zeichne();
  });
})();
