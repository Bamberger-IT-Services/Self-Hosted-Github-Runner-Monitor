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
    const z = r && r.status && r.status.zustand;
    return {
      job: { art: 'laeuft', wort: 'job' }, bereit: { art: 'ok', wort: 'bereit' },
      gestoppt: { art: 'fehler', wort: 'gestoppt' }, offline: { art: 'warn', wort: 'offline' },
      aktiv: { art: 'ok', wort: 'aktiv' }, fehlt: { art: 'neutral', wort: 'fehlt' },   // ohne Dienst: neutral, kein Alarm
    }[z] || { art: 'neutral', wort: 'unbekannt' };
  }

  /* Anzeigename des Dienstes für die Plakette; ‚unbekannt‘ liefert null (der Aufrufer übersetzt). */
  const dienstName = (dienst) => DIENSTE[dienst] || null;

  /* Eintrag aus runner[] → die Form, die renderStatus() und renderWorkflows() kennen (Altformat der
     Bereiche „status“ und „workflows“). basis: Werte der VM (vm, monitorVersion, system).
     nurGrund = der Dienst liefert keine Jobs (Grundüberwachung): die Karten zeigen dann keine Jobs. */
  function ansicht(r, basis = {}) {
    const s = r.status || {};
    const faehig = r.faehig || {};
    return {
      vm: basis.vm || '', runner: r.name || r.id, id: r.id, eingerichtet: true, labels: Array.isArray(r.labels) ? r.labels : [],
      version: r.version || '', monitorVersion: basis.monitorVersion, system: basis.system,
      dienst: s.dienst || { zustand: 'fehlt', seit: null, grund: null },
      github: s.beimDienst || { zustand: 'unbekannt', seit: null },
      job: r.job || null, letzteJobs: Array.isArray(r.letzteJobs) ? r.letzteJobs : [],
      anbieter: r.dienst, nurGrund: !faehig.jobs, ohneSchritte: !!faehig.jobs && !faehig.schritte,
      zustand: s.zustand || null,  // „unbekannt“: Dienst liefert keinen lesbaren Stand (Forgejo/Gitea, #93)
    };
  }

  /* Meldung aus meldungen[] → betrifft sie einen anderen als den gewählten Runner? */
  const fremd = (meldung, gewaehlt) => !!(meldung && meldung.runner && meldung.runner !== gewaehlt);

  return { SCHLUESSEL, MAX_REITER, laden, speichern, waehle, wahl, reiter, zustand, dienstName, ansicht, fremd };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = RUNNER;
