/* Mehrere Runner im Dashboard (Design 0.8.0, #94): Reiterauswahl, „+N“, gemerkte Wahl und die Umrechnung
   eines Eintrags aus runner[] in die Ansicht, die die Karten kennen. Reine Logik ohne DOM, damit sie sich
   mit node prüfen lässt (tests/js/runner.test.mjs). Im Browser als globales RUNNER. Texte stehen nicht
   hier, sondern in dashboard.js (Übersetzung: t()). */
'use strict';

const RUNNER = (() => {
  const SCHLUESSEL = 'runner-monitor.runner';  // localStorage: Runner-ID des gewählten Runners
  const MAX_REITER = 3;                        // ab 4 Runnern: drei Reiter + „+N“
  const DIENSTE = { github: 'GitHub', forgejo: 'Forgejo', gitea: 'Gitea', gitlab: 'GitLab' };

  const speicherStandard = () => { try { return typeof localStorage === 'undefined' ? null : localStorage; } catch (e) { return null; } };

  /* Gemerkte Runner-ID oder null (nichts gespeichert, Speicher gesperrt). */
  function laden(speicher = speicherStandard()) {
    try {
      const v = speicher.getItem(SCHLUESSEL);
      return typeof v === 'string' && v ? v : null;
    } catch (e) { return null; }
  }
  /* true, wenn gespeichert; Speicher gesperrt → false, die Wahl gilt dann nur in dieser Sitzung. */
  function speichern(id, speicher = speicherStandard()) {
    if (typeof id !== 'string' || !id) return false;
    try { speicher.setItem(SCHLUESSEL, id); return true; } catch (e) { return false; }
  }

  const ids = (liste) => (Array.isArray(liste) ? liste : []).map((r) => r && r.id).filter((i) => typeof i === 'string' && i);

  /* Gemerkte Wahl samt gültiger Wahl. Der Wunsch ändert sich nur durch die Wahl des Benutzers; die gültige
     Wahl folgt der Liste (fehlt der Runner, etwa vor dem ersten runner-Ereignis oder kurz beim Neustart des
     Sammlers, gilt vorläufig der erste – der Wunsch bleibt und greift wieder, sobald es den Runner gibt). */
  function wahl(speicher = speicherStandard()) {
    const w = { wunsch: laden(speicher), gewaehlt: null };
    w.liste = (liste) => { w.gewaehlt = waehle(liste, w.wunsch); return w.gewaehlt; };
    w.waehle = (id, liste) => {
      if (!ids(liste).includes(id)) return false;
      w.wunsch = id; w.gewaehlt = id; speichern(id, speicher); return true;
    };
    return w;
  }

  /* Gültige Wahl: der Wunsch, wenn es den Runner gibt, sonst der erste. Ohne Runner null. */
  function waehle(liste, wunsch) {
    const alle = ids(liste);
    return alle.includes(wunsch) ? wunsch : (alle[0] || null);
  }

  /* Welche Runner als Reiter stehen und welche hinter „+N“. Bis 3 Runner: alle. Ab 4: Index 0, 1 und der
     gewählte (bzw. Index 2), die übrigen in der Liste. Reihenfolge der Reiter wie in der Liste. */
  function reiter(liste, gewaehlt) {
    const alle = ids(liste);
    if (alle.length <= MAX_REITER) return { sichtbar: alle, rest: [], mehr: false };
    const i = alle.indexOf(gewaehlt);
    const sichtbar = [0, 1, i >= 2 ? i : 2].map((n) => alle[n]);
    return { sichtbar, rest: alle.filter((x) => !sichtbar.includes(x)), mehr: true };
  }

  /* Kurzzustand für Reiter und Liste: art = Farbklasse (laeuft = --brand, ok = --success, fehler = --danger,
     warn = --warning, neutral), wort = Schlüssel des Zustandstexts (der Zustand steht immer auch als Text). */
  function zustand(r) {
    // Ohne Unit (faehig.status false) gibt es keinen Dienst: Reiter und Karte zeigen beide „Kein Dienst“ (Review #114)
    const z = r && r.faehig && r.faehig.status === false ? 'fehlt' : r && r.status && r.status.zustand;
    return {
      job: { art: 'laeuft', wort: 'job' }, bereit: { art: 'ok', wort: 'bereit' },
      gestoppt: { art: 'fehler', wort: 'gestoppt' }, offline: { art: 'warn', wort: 'offline' },
      aktiv: { art: 'ok', wort: 'aktiv' }, fehlt: { art: 'neutral', wort: 'fehlt' },   // ohne Dienst: neutral, kein Alarm
    }[z] || { art: 'neutral', wort: 'unbekannt' };
  }

  /* Anzeigename des Dienstes für die Plakette; ‚unbekannt‘ liefert null (der Aufrufer übersetzt). */
  const dienstName = (dienst) => DIENSTE[dienst] || null;

  /* Woher das Live-Log des Runners kommt – nur aus faehig.logs und runner[].log, nie aus dem Dienstnamen:
     'seiten' (Ausgabe der Schritte, GitHub), 'journal' (Journal der Unit, #95), 'datei' (Log-Datei aus
     runner.json, noch nicht angezeigt) oder null (kein Log, z. B. ohne Unit). */
  function logQuelle(r) {
    const log = r && r.log, faehig = (r && r.faehig) || {};
    if (!faehig.logs || !log || typeof log !== 'object') return null;
    if (log.art === 'journal') return typeof log.unit === 'string' && log.unit ? 'journal' : null;
    return ['seiten', 'datei'].includes(log.art) ? log.art : null;
  }
  /* Runner-ID für /events?journal=…, wenn das Live-Log dieses Runners das Journal ist, sonst null. */
  const journalZiel = (r) => (logQuelle(r) === 'journal' ? r.id : null);
  const journalUrl = (id) => (id ? `/events?journal=${encodeURIComponent(id)}` : '/events');

  /* Zeilen fürs Log: ohne Schritte (faehig.schritte false) und im Journal gibt es keine Schritt-Trenner. */
  const logZeilen = (zeilen, mitTrennern) => (Array.isArray(zeilen) ? zeilen : []).filter((z) => z && (mitTrennern || z.art !== 'schritt'));

  /* Eintrag aus runner[] → die Form, die renderStatus() und renderWorkflows() kennen (Altformat der
     Bereiche „status“ und „workflows“). basis: Werte der VM (vm, monitorVersion, system).
     Steuerung nur über faehig{…} (README › „Nicht verfügbar“ ehrlich zeigen), nie über den Dienstnamen:
     nurGrund = keine Jobs (Grundüberwachung: kein „Online bei …“, keine „Letzten Jobs“, „Jobs nicht verfügbar“),
     ohneSchritte = Jobs ja, Schritte nein („Schritte nicht verfügbar“, keine Trenner, kein Schritt-Chip).
     anbieter dient nur der Anzeige (Plakette, „Online bei GitHub“). */
  function ansicht(r, basis = {}) {
    const s = r.status || {};
    const faehig = r.faehig || {};
    const quelle = logQuelle(r);
    const unit = typeof r.unit === 'string' ? r.unit : '';
    // Ohne Labels vom Dienst (Grundüberwachung) steht die Unit als Label in der Kopfzeile (Design 0.8.0: „buildagent.service“)
    const labels = Array.isArray(r.labels) && r.labels.length ? r.labels : (!faehig.jobs && unit ? [unit] : []);
    return {
      vm: basis.vm || '', runner: r.name || r.id, id: r.id, eingerichtet: true, labels,
      version: r.version || '', monitorVersion: basis.monitorVersion, system: basis.system,
      dienst: faehig.status === false ? { zustand: 'fehlt', seit: null, grund: null } : (s.dienst || { zustand: 'fehlt', seit: null, grund: null }),
      github: s.beimDienst || { zustand: 'unbekannt', seit: null },
      job: faehig.jobs ? (r.job || null) : null, letzteJobs: faehig.jobs && Array.isArray(r.letzteJobs) ? r.letzteJobs : [],
      anbieter: r.dienst, unit,
      nurGrund: !faehig.jobs, ohneSchritte: !!faehig.jobs && !faehig.schritte,
      logQuelle: quelle, journalUnit: quelle === 'journal' ? r.log.unit : '',
      zustand: s.zustand || null,  // „unbekannt“: Dienst liefert keinen lesbaren Stand (Forgejo/Gitea, #93)
    };
  }

  /* Meldung aus meldungen[] → betrifft sie einen anderen als den gewählten Runner? */
  const fremd = (meldung, gewaehlt) => !!(meldung && meldung.runner && meldung.runner !== gewaehlt);

  /* Neustarts für die kv-Zeile der Grundüberwachung: NRestarts von systemd zählt die automatischen Neustarts
     (Restart=) seit dem letzten Start von Hand. Liefert {art: 'keine'|'zahl'|'unbekannt', n}. */
  function neustarts(dienst) {
    const n = dienst && dienst.neustarts;
    if (!Number.isInteger(n) || n < 0) return { art: 'unbekannt', n: null };
    return n === 0 ? { art: 'keine', n: 0 } : { art: 'zahl', n };
  }


  /* Alter des letzten guten Stands (#123): Schlägt die Abfrage beim Dienst fehl, behält der Sammler den letzten
     guten Stand – Job, „Online bei …“ und Zahlen. Kurz ist das normal (der Kartenfuß nennt die Zeit); nach 2 Min.
     steht ein Hinweis mit dem Alter, nach 10 Min. gilt der Stand als veraltet: „Zustand unbekannt“ statt eines
     Jobs, der stundenlang „läuft“. Ohne Abfrage (kein Token, Grundüberwachung) gibt es nichts, was veralten könnte.
     jobs = jobsJeRepository (abgefragt = letzte erfolgreiche Abfrage), jetzt in Millisekunden. */
  const ALT_HINWEIS = 120, ALT_VERALTET = 600;
  const AUSFALL = ['nicht-erreichbar', 'kontingent', 'fehler', 'token-ungueltig', 'keine-rechte'];
  function alter(jobs, jetzt = Date.now()) {
    if (!jobs || !AUSFALL.includes(jobs.abfrage)) return { stufe: 'frisch', sekunden: 0, seit: null };
    const seit = jobs.abgefragt ? ms(jobs.abgefragt) : NaN;
    if (!Number.isFinite(seit)) return { stufe: 'veraltet', sekunden: null, seit: null };  // nie ein guter Stand
    const s = Math.max(0, Math.round((jetzt - seit) / 1000));
    return { stufe: s >= ALT_VERALTET ? 'veraltet' : s >= ALT_HINWEIS ? 'hinweis' : 'frisch', sekunden: s, seit };
  }
  const ms = (z) => (z == null ? NaN : (typeof z === 'number' ? (z < 1e12 ? z * 1000 : z) : Date.parse(z)));

  return { ALT_HINWEIS, ALT_VERALTET, alter, SCHLUESSEL, MAX_REITER, laden, speichern, waehle, wahl, reiter, zustand, dienstName, ansicht, fremd,
    logQuelle, journalZiel, journalUrl, logZeilen, neustarts };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = RUNNER;
