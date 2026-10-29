/* Runner-Monitor – Dashboard (Design v1). Daten kommen per Server-Sent Events von /events.
   Bereiche und Felder: docs/FUNKTIONSWEISE.md › „Datenformat“. Mit ?demo statt /events der
   Simulator aus demo.js (für Entwicklung, Bildschirmfotos und Vorführung). */
'use strict';

(() => {
  const { $, IC, esc, zahl, zeit, hm, tm, wt, datum, dauer, vor, seit, mehrzahl, ms, t } = RM;
  I18N.wendeAn();  // statische Texte im HTML (data-t …) und <html lang>
  const GiB = 1024 ** 3, GB = 1e9;
  const REPO = 'Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor';
  const MAX_ZEILEN = 1500;
  // Volle Pfadangabe: ./einrichten.sh gibt es nur im entpackten Ordner, dieser Pfad gilt immer nach der Installation.
  const SKRIPT = 'sudo /opt/runner-monitor/aktuell/einrichten.sh';
  // systemd-„Result“ eines gestoppten Runner-Dienstes → Ursache in Worten (#68)
  const STOPP_GRUND = {
    'oom-kill': t('Speicher voll (OOM-Killer)'),
    'exit-code': t('mit Fehlercode beendet'), 'signal': t('von einem Signal beendet'), 'core-dump': t('abgestürzt'),
    'timeout': t('Zeitüberschreitung beim Starten oder Stoppen'), 'start-limit-hit': t('zu viele Startversuche'),
    'watchdog': t('vom Watchdog beendet'), 'resources': t('Ressourcen fehlten beim Start'),
  };
  const stoppGrund = (st) => st && st.dienst && st.dienst.grund ? (STOPP_GRUND[st.dienst.grund] || st.dienst.grund) : '';
  const UPDATE_SCHRITTE = [[t('Release herunterladen'), t('Archiv und Prüfsumme')], [t('Prüfsumme prüfen'), t('SHA-256 stimmt')], [t('Installieren'), t('alte Version gesichert')], [t('Monitor neu starten'), t('kurz nicht erreichbar')], [t('Funktion prüfen'), t('Daten kommen an')]];

  /* Zeitraum der Verläufe: nur im Browser gemerkt (Sekunden); ungültig oder Speicher gesperrt → 10 Min. */
  function zeitraumLaden() {
    try { return VERLAUF.zeitraum(localStorage.getItem('runner-monitor.zeitraum')); } catch (e) { return VERLAUF.STANDARD; }
  }
  function zeitraumSpeichern(r) {
    try { localStorage.setItem('runner-monitor.zeitraum', String(r)); } catch (e) { /* gesperrt: gilt nur für diese Seite */ }
  }

  const S = {
    status: null, system: null, prozesse: [], platten: [], workflows: null, update: null,
    cpuH: [], ramH: [], netzH: [], ende: null, zeitraum: zeitraumLaden(), ereignisse: [], zeilenN: 0, puffer: [],
    verbindung: 'verbindet', letzteDaten: 0,
    umbruch: true, angehalten: false, hoch: false, pruefung: null, wfOffen: false, info: null, kerneN: 0,
    // Mehrere Runner (#94): runner[]/meldungen[] aus dem Server; status/workflows sind dann die Ansicht des
    // gewählten Runners, sonst (Altformat ohne runner) die Bereiche „status“/„workflows“ selbst.
    runner: null, meldungenSrv: null, wahl: RUNNER.wahl(), statusAlt: null, workflowsAlt: null, mehrOffen: false, logFremd: false,
    // Live-Log je Runner (#95): Quelle des gewählten Runners ('seiten' | 'journal' | 'datei' | null) und die
    // Runner-ID, deren Journal der aktuelle Live-Strom liefert (/events?journal=…; null = keins).
    logQuelle: 'seiten', journalUnit: '', stromJournal: null, journalFehler: null,
    // Info › Runner (#97): Funde der Erkennung, „Neu erkennen“, neue Funde, offenes Formular / offene Box
    anlRunner: null,  // Runner, dessen Zugangsdaten-Anleitung der Link bei „Zugangsdaten ändern“ zeigt
    ir: { funde: null, zeit: null, erkZeit: null, geladen: 0, fehler: false, erk: 'ruhe', aktiv: false, neu: [], form: null, zugang: null, werte: {}, formFehler: {}, meldung: '', sendet: false },
  };

  /* ------------------------------------------------------------ ANSI → Segmente */
  function ansi(raw) {
    const segs = []; let st = { b: 0, d: 0, i: 0, u: 0, f: 0, g: 0 };
    const re = /\u001b\[([0-9;]*)m/g; let last = 0, m;
    const push = t => { if (!t) return; const c = []; if (st.b) c.push('a1'); if (st.d) c.push('a2'); if (st.i) c.push('a3'); if (st.u) c.push('a4'); if (st.f) c.push('f' + st.f); if (st.g) c.push('b' + st.g); segs.push({ t, c: c.join(' ') }); };
    while ((m = re.exec(raw))) {
      push(raw.slice(last, m.index).replace(/\u001b\[[0-9;?]*[A-Za-z]/g, '')); last = re.lastIndex;
      const k = (m[1] || '0').split(';').map(Number);
      for (let i = 0; i < k.length; i++) {
        const v = k[i];
        if (v === 38 || v === 48) { i += (k[i + 1] === 5 ? 2 : 4); continue; }
        if (v === 0) st = { b: 0, d: 0, i: 0, u: 0, f: 0, g: 0 };
        else if (v === 1) st.b = 1; else if (v === 2) st.d = 1; else if (v === 3) st.i = 1; else if (v === 4) st.u = 1;
        else if (v === 22) { st.b = 0; st.d = 0; } else if (v === 23) st.i = 0; else if (v === 24) st.u = 0;
        else if ((v >= 30 && v <= 37) || (v >= 90 && v <= 97)) st.f = v; else if (v === 39) st.f = 0;
        else if (v >= 40 && v <= 47) st.g = v; else if (v === 49) st.g = 0;
      }
    }
    push(raw.slice(last).replace(/\u001b\[[0-9;?]*[A-Za-z]/g, ''));
    return segs;
  }
  const istFehler = raw => /\u001b\[(?:1;)?(?:31|91)m|##\[error\]|(^|\s)(ERROR|FAIL)\b/.test(raw);

  /* ------------------------------------------------------------ Federn (Dämpfung 1,0) */
  const reduziert = matchMedia('(prefers-reduced-motion: reduce)');
  const federn = new Map(); let federLoop = 0, federZeit = 0;
  const ANTWORT = 0.55;
  function feder(el, ziel) {
    ziel = Math.max(0, Math.min(1, ziel || 0));
    const f = federn.get(el);
    if (!f || reduziert.matches || document.hidden) { federn.set(el, { x: ziel, v: 0, ziel }); el.style.transform = `scaleX(${ziel})`; return; }
    f.ziel = ziel;
    if (!federLoop) { federZeit = performance.now(); federLoop = requestAnimationFrame(federSchritt); }
  }
  function federSchritt(jetzt) {
    const dt = Math.min(0.05, (jetzt - federZeit) / 1000); federZeit = jetzt;
    const w = 2 * Math.PI / ANTWORT; let aktiv = false;
    for (const [el, f] of federn) {
      if (!el.isConnected) { federn.delete(el); continue; }
      if (Math.abs(f.x - f.ziel) < 1e-4 && Math.abs(f.v) < 1e-3) continue;
      f.v += (-w * w * (f.x - f.ziel) - 2 * w * f.v) * dt; f.x += f.v * dt; aktiv = true;
      el.style.transform = `scaleX(${f.x.toFixed(4)})`;
    }
    federLoop = aktiv ? requestAnimationFrame(federSchritt) : 0;
  }

  /* ------------------------------------------------------------ Mehrere Runner (Design 0.8.0, #94) */
  /* Rechenlogik (Wahl, Reiter, „+N“, Ansicht eines Runners): runner.js. Ohne runner[] (Altformat) bleibt alles
     wie bisher; mit einem Runner gibt es keine Reiter und die Ansicht ist die von 0.4.0. */
  const mehrereRunner = () => Array.isArray(S.runner) && S.runner.length > 1;
  const gewaehlterRunner = () => (S.runner || []).find((r) => r.id === S.wahl.gewaehlt) || null;

  /* status/workflows aus dem gewählten Runner ableiten (oder die Altbereiche übernehmen). */
  function abgleich() {
    if (Array.isArray(S.runner) && S.runner.length) {
      S.wahl.liste(S.runner);
      const r = gewaehlterRunner(), b = S.statusAlt || {};
      S.status = RUNNER.ansicht(r, { vm: b.vm, monitorVersion: b.monitorVersion, system: b.system });
      S.workflows = r.jobsJeRepository || null;
      setzeLogQuelle(S.status.logQuelle, RUNNER.journalZiel(r), S.status.journalUnit);
      if (S.status.ohneSchritte) ohneTrenner();
    } else {
      S.status = S.statusAlt; S.workflows = S.workflowsAlt; S.wahl.gewaehlt = null;
      setzeLogQuelle('seiten', null, '');
    }
  }

  /* Live-Log des gewählten Runners: Ausgabe der Schritte (Ereignis „log“) oder Journal der Unit (Ereignis
     „journal“, nur für die Runner-ID im Live-Strom). Wechselt die Quelle, wird das Log geleert; wechselt der
     Runner mit Journal, verbindet sich der Strom mit dem neuen Ziel neu (Server schickt dann den Stand). */
  function setzeLogQuelle(quelle, ziel, unit) {
    const alt = S.logQuelle;
    S.logQuelle = quelle; S.journalUnit = unit || '';
    S.logFremd = quelle !== 'seiten' && quelle !== 'journal';
    if (alt !== quelle && (alt === 'journal' || quelle === 'journal')) leereLog();
    if (ziel !== S.stromJournal) { S.stromJournal = ziel; S.journalFehler = null; if (quelle === 'journal') leereLog(); wechsleJournal(); }
  }
  /* Liefert der Runner keine Schritte, gibt es auch keine Trenner – auch nicht solche, die vor runner[] kamen. */
  function ohneTrenner() {
    for (const tr of $('term-innen').querySelectorAll('.trenner')) { tr.remove(); S.zeilenN--; }
    S.puffer = RUNNER.logZeilen(S.puffer, false);
  }
  function leereLog() {
    S.ereignisse = []; $('term-innen').replaceChildren(); S.zeilenN = 0; S.puffer = [];
    renderEreignisse(); renderPause();
  }
  function zeilenAn(zeilen) {
    if (!zeilen.length) return;
    if (S.angehalten || S.hoch) { S.puffer.push(...zeilen); if (S.puffer.length > MAX_ZEILEN) S.puffer.splice(0, S.puffer.length - MAX_ZEILEN); renderPause(); } else haengeAn(zeilen);
  }
  function renderAlles() { renderReiter(); renderKopf(); renderStatus(); renderWorkflows(); renderLogKopf(); }

  function waehleRunner(id) {
    if (!id || id === S.wahl.gewaehlt || !S.wahl.waehle(id, S.runner)) { S.mehrOffen = false; renderReiter(); return; }
    S.mehrOffen = false; S.anlRunner = null;
    abgleich();
    // Karten sofort neu zeichnen, auch wenn die Sperre gegen Neuzeichnen (Fokus in der Karte) sonst greifen würde
    $('workflows').dataset.letzte = ''; $('workflows').dataset.html = ''; $('status').dataset.html = '';
    renderAlles();
  }

  /* Zustandstext je Schlüssel aus RUNNER.zustand(); der Zustand steht immer auch als Wort, nie nur als Farbe. */
  const zustandsWort = () => ({ job: t('Job läuft'), bereit: t('Bereit'), gestoppt: t('Gestoppt'), offline: t('Offline'), aktiv: t('Dienst aktiv'), fehlt: t('Kein Dienst'), unbekannt: t('Unbekannt') });
  const dienstText = (r) => RUNNER.dienstName(r.dienst) || t('unbekannt');

  function renderReiter() {
    const liste = S.runner || [], mehrere = mehrereRunner();
    const tabs = $('rw-tabs'), pop = $('rw-pop');
    $('raster').classList.toggle('rw-c', mehrere);
    const lr = $('log-runner'), gw = gewaehlterRunner();
    lr.hidden = !mehrere; lr.textContent = mehrere && gw ? gw.name : '';
    if (!mehrere) { tabs.hidden = true; pop.hidden = true; tabs.dataset.html = ''; pop.dataset.html = ''; S.mehrOffen = false; return; }
    const { sichtbar, rest, mehr } = RUNNER.reiter(liste, S.wahl.gewaehlt);
    if (!mehr) S.mehrOffen = false;
    const wort = zustandsWort(), von = (id) => liste.find((r) => r.id === id);
    const tab = (r) => {
      const z = RUNNER.zustand(r, Date.now()), an = r.id === S.wahl.gewaehlt;
      return `<button type="button" role="tab" class="rw-t${an ? ' an' : ''}" aria-selected="${an}" tabindex="${an ? 0 : -1}" aria-controls="status workflows" data-aktion="runner-waehlen" data-runner="${esc(r.id)}" title="${esc(`${r.name} · ${dienstText(r)} · ${wort[z.wort]}`)}"><span class="rw-z1"><span class="punkt ${z.art}" aria-hidden="true"></span><span class="rw-name">${esc(r.name)}</span></span><span class="rw-z2"><span class="${z.art}">${wort[z.wort]}</span></span></button>`;
    };
    let html = `<div class="rw-liste" role="tablist" aria-label="${esc(t('Runner wählen'))}">${sichtbar.map((id) => tab(von(id))).join('')}</div>`;
    let popHtml = '';
    if (mehr) {
      const uebrige = rest.map(von);
      const titel = `${t('Weitere Runner')}: ${uebrige.map((r) => `${r.name} ${wort[RUNNER.zustand(r, Date.now()).wort]}`).join(', ')}`;
      html += `<button type="button" class="rw-t rw-mehr${S.mehrOffen ? ' an' : ''}" id="rw-mehr" aria-haspopup="listbox" aria-expanded="${S.mehrOffen}" aria-controls="rw-pop" aria-label="${esc(titel)}" title="${esc(titel)}" data-aktion="runner-mehr"><span class="rw-z1">+${rest.length}</span><span class="rw-z2">${uebrige.map((r) => `<span class="punkt ${RUNNER.zustand(r, Date.now()).art}" aria-hidden="true"></span>`).join('')}</span></button>`;
      popHtml = uebrige.map((r) => {
        const z = RUNNER.zustand(r, Date.now());
        return `<button type="button" role="option" class="rw-pz" aria-selected="${r.id === S.wahl.gewaehlt}" tabindex="-1" data-aktion="runner-waehlen" data-runner="${esc(r.id)}"><span class="punkt ${z.art}" aria-hidden="true"></span><span class="rw-name">${esc(r.name)}</span><span class="label">${esc(dienstText(r))}</span><span class="rw-zt ${z.art}">${wort[z.wort]}</span></button>`;
      }).join('');
    }
    const spalten = mehr ? 'repeat(3, minmax(0, 1fr)) 64px' : `repeat(${sichtbar.length}, minmax(0, 1fr))`;
    // Fokus merken: das Neuzeichnen ersetzt die Knöpfe (nur bei Änderung, nicht jede Sekunde)
    const fokus = document.activeElement, merke = fokus && fokus.closest('#rw-tabs, #rw-pop') ? (fokus.dataset.runner ? `[data-runner="${CSS.escape(fokus.dataset.runner)}"]` : '#rw-mehr') : null;
    if (tabs.dataset.html !== html) { tabs.innerHTML = html; tabs.dataset.html = html; }
    tabs.style.gridTemplateColumns = spalten; tabs.hidden = false;
    pop.hidden = !(mehr && S.mehrOffen);
    if (pop.dataset.html !== popHtml) { pop.innerHTML = popHtml; pop.dataset.html = popHtml; }
    if (merke) { const z = (pop.hidden ? null : pop.querySelector(merke)) || tabs.querySelector(merke) || tabs.querySelector('.rw-t.an'); if (z && z !== document.activeElement) z.focus(); }
  }

  /* Bedienung der Reiter per Tastatur (Tab-Muster): Pfeile links/rechts, Pos1/Ende; die Wahl folgt dem Fokus. */
  $('rw-tabs').addEventListener('keydown', (e) => {
    const knoepfe = [...$('rw-tabs').querySelectorAll('.rw-t')], i = knoepfe.indexOf(document.activeElement);
    if (i < 0) return;
    if (e.key === 'Escape' && S.mehrOffen) { e.preventDefault(); e.stopPropagation(); schliesseMehr(true); return; }
    const ziel = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: knoepfe.length - 1 }[e.key];
    if (e.key === 'ArrowDown' && knoepfe[i].id === 'rw-mehr') { e.preventDefault(); oeffneMehr(true); return; }
    if (ziel === undefined) return;
    e.preventDefault();
    const k = knoepfe[(ziel + knoepfe.length) % knoepfe.length];
    if (k.dataset.runner) { waehleRunner(k.dataset.runner); const a = $('rw-tabs').querySelector(`[data-runner="${CSS.escape(k.dataset.runner)}"]`); if (a) a.focus(); } else k.focus();
  });
  function oeffneMehr(fokus) {
    S.mehrOffen = true; renderReiter();
    const pz = [...$('rw-pop').querySelectorAll('.rw-pz')];
    if (fokus && pz[0]) pz[0].focus();
  }
  function schliesseMehr(zurueck) {
    if (!S.mehrOffen) return;
    S.mehrOffen = false; renderReiter();
    if (zurueck) { const k = $('rw-mehr'); if (k) k.focus(); }
  }
  $('rw-pop').addEventListener('keydown', (e) => {
    const pz = [...$('rw-pop').querySelectorAll('.rw-pz')], i = pz.indexOf(document.activeElement);
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); schliesseMehr(true); return; }
    const ziel = { ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: pz.length - 1 }[e.key];
    if (ziel === undefined || !pz.length) return;
    e.preventDefault(); pz[(ziel + pz.length) % pz.length].focus();
  });
  document.addEventListener('click', (e) => { if (S.mehrOffen && !e.target.closest('#rw-pop, #rw-mehr')) schliesseMehr(false); }, true);
  // Verlässt der Fokus Liste und „+N“ per Tab, schließt die Liste
  for (const el of [$('rw-pop'), $('rw-tabs')]) {
    el.addEventListener('focusout', (e) => { if (S.mehrOffen && e.relatedTarget && !e.relatedTarget.closest('#rw-pop, #rw-mehr')) schliesseMehr(false); });
  }

  /* ------------------------------------------------------------ Empfang */
  function setzeVerbindung(v) {
    if (S.verbindung === v) return;
    S.verbindung = v; renderKopf(); renderStatus(); renderWorkflows();
  }

  function empfange(bereich, d) {
    S.letzteDaten = Date.now(); wartezeit = 2000;
    if (S.verbindung !== 'verbunden') setzeVerbindung('verbunden');
    switch (bereich) {
      case 'status': S.statusAlt = d; abgleich(); renderKopf(); renderStatus(); renderLogKopf(); break;
      case 'runner': S.runner = Array.isArray(d) ? d : null; abgleich(); renderAlles(); break;
      case 'meldungen': S.meldungenSrv = Array.isArray(d) ? d : null; renderKopf(); break;
      case 'system':
        S.system = d;
        // S.ende = absolute Sekunde des letzten Werts; die Eimergrenzen der Verläufe hängen daran (verlauf.js)
        if (d.verlauf) {
          S.cpuH = d.verlauf.cpu.slice(-VERLAUF.MAX_WERTE); S.ramH = d.verlauf.ram.slice(-VERLAUF.MAX_WERTE); S.netzH = (d.verlauf.netz || []).slice(-VERLAUF.MAX_WERTE);
          S.ende = Math.round(d.zeit);
        } else {
          S.cpuH.push(d.cpu); S.ramH.push(d.ram.gesamt ? d.ram.belegt / d.ram.gesamt * 100 : 0);
          if (d.netz) S.netzH.push([d.netz.empfangen, d.netz.gesendet]);
          S.ende = S.ende == null ? Math.round(d.zeit) : S.ende + 1;
          if (S.cpuH.length > VERLAUF.MAX_WERTE) { S.cpuH.shift(); S.ramH.shift(); }
          if (S.netzH.length > VERLAUF.MAX_WERTE) S.netzH.shift();
        }
        renderSystem(); break;
      case 'prozesse': S.prozesse = d; renderProzesse(); break;
      case 'platten': S.platten = d; renderPlatten(); renderKopf(); break;
      case 'workflows': S.workflowsAlt = d; abgleich(); renderWorkflows(); renderKopf(); break;
      case 'update':
        S.update = d;
        if (S.pruefung && S.pruefung.zustand === 'laeuft' && d.neueste && d.neueste.geprueft && d.neueste.geprueft !== S.pruefung.vorher) S.pruefung = { zustand: 'fertig', bis: Date.now() + 8000 };
        renderKopf(); if (S.info) renderInfo(); break;
      case 'log':
      case 'journal': {
        // „log“ = Ausgabe der Schritte (GitHub-Runner), „journal“ = Journal der Unit des gewählten Runners (#95).
        // Angezeigt wird nur die Quelle des gewählten Runners; Trenner nur, wenn er Schritte liefert.
        if ((bereich === 'journal') !== (S.logQuelle === 'journal')) break;
        if (d.neu) { leereLog(); S.journalFehler = bereich === 'journal' ? (d.hinweis || null) : null; }
        if (d.ereignisse && d.ereignisse.length) { S.ereignisse.push(...d.ereignisse); S.ereignisse = S.ereignisse.slice(-20); renderEreignisse(); }
        zeilenAn(RUNNER.logZeilen(d.zeilen, bereich === 'log' && !(S.status && S.status.ohneSchritte)));
        renderLeer(); break;
      }
      default: break;
    }
  }

  /* ------------------------------------------------------------ Meldungen (Kopfzeile Mitte) */
  function meldungen() {
    const M = [], st = S.status, w = S.workflows, u = S.update, jetzt = Date.now();
    if (S.verbindung === 'getrennt' && S.letzteDaten) M.push({ id: 'monitor', cls: 'fehler', ic: IC.getrennt(18), titel: t('Verbindung zum Monitor unterbrochen'), text: t('Stand {z} ({vor}) · neuer Versuch läuft', { z: zeit(S.letzteDaten), vor: vor((jetzt - S.letzteDaten) / 1000) }) });
    const us = u && u.status;
    if (us && us.zustand === 'laeuft') M.push({ id: 'update', cls: 'laeuft', ic: IC.update(), link: t('Details'), titel: t('Update auf {v} läuft', { v: us.version || '' }), text: t('{schritt} ({nr}/5) · Runner arbeitet weiter', { schritt: (UPDATE_SCHRITTE[(us.schritt || 1) - 1] || UPDATE_SCHRITTE[0])[0], nr: us.schritt || 1 }) });
    if (us && us.zustand === 'fehler' && jetzt - ms(us.zeit) < 86400000) M.push({ id: 'update', cls: 'fehler', ic: IC.x(18), link: t('Details'), titel: t('Update fehlgeschlagen'), text: t('Version {v} wurde wiederhergestellt und läuft', { v: u.installiert }) });
    const srv = Array.isArray(S.meldungenSrv) && Array.isArray(S.runner) && S.runner.length;
    const sm = srv ? serverMeldungen() : [];
    if (srv) M.push(...sm.filter((e) => !e.nach));  // Token-Ablauf kommt wie in 0.4.0 nach „Platte knapp“
    else {
    if (st && st.dienst.zustand === 'gestoppt') M.push({ id: 'gestoppt', cls: 'fehler', ic: IC.x(18), titel: t('Runner-Dienst gestoppt'), text: (st.dienst.grund === 'oom-kill' ? t('Speicher voll – ein Job hat den Arbeitsspeicher gesprengt.') + ' ' : stoppGrund(st) ? `${stoppGrund(st)}. ` : '') + t('Jobs bleiben in der Warteschlange') + (w && w.abfrage === 'ok' ? ' ' + t('({n} warten)', { n: w.repos.reduce((a, r) => a + r.wartet, 0) }) : '') });
    if (st && st.dienst.zustand === 'fehlt') M.push({ id: 'runner', cls: 'warn', ic: IC.warn(18), titel: t('Kein Runner eingerichtet'), text: t('auf dieser VM wurde kein GitHub-Runner gefunden') });
    if (st && st.github.zustand === 'offline' && st.dienst.zustand === 'aktiv') M.push({ id: 'offline', cls: 'fehler', ic: IC.x(18), titel: t('Runner offline bei GitHub'), text: `${st.github.seit ? t('seit {z}', { z: zeit(st.github.seit) }) + ' · ' : ''}${t('Jobs werden nicht zugestellt')}` });
    if (w && ['nicht-erreichbar', 'kontingent', 'fehler'].includes(w.abfrage)) M.push({ id: 'github', cls: 'warn', ic: IC.warn(18), titel: w.abfrage === 'kontingent' ? t('GitHub-Kontingent erschöpft') : t('GitHub nicht erreichbar'), text: t('Workflows zeigen den Stand von {z}', { z: w.abgefragt ? zeit(w.abgefragt) : '–' }) + (w.naechste ? ' · ' + t('neuer Versuch in {n} s', { n: Math.max(0, Math.round((ms(w.naechste) - jetzt) / 1000)) }) : '') });
    if (w && ['token-ungueltig', 'keine-rechte'].includes(w.abfrage)) M.push({ id: 'token', cls: 'fehler', ic: IC.schluessel(18), titel: w.abfrage === 'token-ungueltig' ? t('GitHub-Token ungültig oder abgelaufen') : t('GitHub-Token ohne Zugriff'), text: t('Workflows werden nicht mehr abgefragt') });
    if (w && w.abfrage === 'kein-token') M.push({ id: 'token', cls: 'neutral', ic: IC.schluessel(18), titel: t('Kein GitHub-Token'), text: t('Workflows und GitHub-Status sind aus') });
    }
    for (const p of S.platten || []) {
      if (p.schwelleFrei && p.frei < p.schwelleFrei) M.push({ id: 'platte', cls: 'warn', ic: IC.warn(18), titel: t('Platte knapp: {n} GB frei', { n: zahl(p.frei / GB, 1) }), text: t('unter {n} GB räumt der Runner vor jedem Job auf', { n: zahl(p.schwelleFrei / GB, 0) }) });
    }
    M.push(...sm.filter((e) => e.nach));
    if (!srv && w && w.tokenAblauf) {
      const tage = Math.ceil((ms(w.tokenAblauf) - jetzt) / 86400000);
      if (tage <= 14 && tage > 0) M.push({ id: 'token', cls: 'warn', ic: IC.schluessel(18), titel: t('GitHub-Token läuft in {n} {tage} ab', { n: tage, tage: mehrzahl(tage, t('Tag'), t('Tagen')) }), text: t('am {d} – danach bleiben die Workflows leer', { d: datum(w.tokenAblauf) }) });
    }
    if (u && u.neueste && u.neueste.version && vergleiche(u.neueste.version, u.installiert) > 0 && !(us && us.zustand === 'laeuft')) M.push({ id: 'update', cls: 'laeuft', ic: IC.update(), link: t('Was ist neu?'), titel: t('Version {v} verfügbar', { v: u.neueste.version }), text: t('installiert ist {v}', { v: u.installiert }) });
    if (us && us.zustand === 'erfolg' && jetzt - ms(us.zeit) < 3600000) M.push({ id: 'update', cls: 'ok', ic: IC.ok(18), link: t('Was ist neu?'), titel: t('Aktualisiert auf {v}', { v: u.installiert }), text: t('um {z} · alles läuft', { z: hm(us.zeit) }) });
    return M;
  }

  /* Meldungen aus meldungen[] (Server: nur Art und Werte, die Texte entstehen hier). Bei mehreren Runnern
     nennt der Titel den Runner („runner-vm-02: Dienst gestoppt“); betrifft sie einen nicht gewählten Runner,
     heißt der Knopf „Anzeigen“ und wechselt zu ihm. Platten, Verbindung und Updates des Monitors kommen
     weiter aus dem Browser. */
  function serverMeldungen() {
    const mehrere = mehrereRunner(), jetzt = Date.now(), M = [];
    const ANLEITUNG = { gestoppt: 'gestoppt', fehlt: 'runner', offline: 'offline', pausiert: 'offline', abfrage: 'github', token: 'token' };
    for (const m of S.meldungenSrv) {
      if (m.id === 'platte' || !ANLEITUNG[m.id]) continue;
      const r = (S.runner || []).find((x) => x.id === m.runner), d = m.daten || {}, j = r && r.jobsJeRepository;
      const vor = mehrere && r ? `${r.name}: ` : '';
      const gh = !m.dienst || m.dienst === 'github', dn = RUNNER.dienstName(m.dienst) || t('Dienst');
      let e = null;
      if (m.id === 'gestoppt') {
        const grund = d.grund ? (STOPP_GRUND[d.grund] || d.grund) : '';
        const wartend = j && j.abfrage === 'ok' ? ` ${t('({n} warten)', { n: j.repos.reduce((a, x) => a + x.wartet, 0) })}` : '';
        e = { cls: 'fehler', ic: IC.x(18), titel: vor ? t('Dienst gestoppt') : t('Runner-Dienst gestoppt'),
          text: (d.grund === 'oom-kill' ? t('Speicher voll – ein Job hat den Arbeitsspeicher gesprengt.') + ' ' : grund ? `${grund}. ` : '') + t('Jobs bleiben in der Warteschlange') + wartend };
      } else if (m.id === 'fehlt') {
        e = m.runner ? { cls: 'warn', ic: IC.warn(18), titel: t('Kein Dienst'), text: t('Der Dienst dieses Runners wurde nicht gefunden') }
          : { cls: 'warn', ic: IC.warn(18), titel: t('Kein Runner eingerichtet'), text: t('auf dieser VM wurde kein Runner gefunden') };
      } else if (m.id === 'offline') {
        e = { cls: 'fehler', ic: IC.x(18), titel: vor ? t('Offline bei {dienst}', { dienst: RUNNER.dienstName(m.dienst) || 'GitHub' }) : t('Runner offline bei {dienst}', { dienst: RUNNER.dienstName(m.dienst) || 'GitHub' }), text: `${d.seit ? t('seit {z}', { z: zeit(d.seit) }) + ' · ' : ''}${t('Jobs werden nicht zugestellt')}` };
      } else if (m.id === 'pausiert') {
        // GitLab: bewusst pausiert – kein „Offline“, ein laufender Job wird noch fertig (Review #121)
        e = { cls: 'warn', ic: IC.warn(18), titel: t('Pausiert bei {dienst}', { dienst: dn }),
          text: d.job ? t('nimmt keine neuen Jobs an, der laufende Job läuft weiter') : t('nimmt keine neuen Jobs an') };
      } else if (m.id === 'abfrage') {
        // Forgejo, Gitea, GitLab (#115): Dienst im Titel statt „GitHub“; GitHub-Texte wie in 0.4.0
        const stand = { z: d.abgefragt ? zeit(d.abgefragt) : '–' };
        e = { cls: 'warn', ic: IC.warn(18), titel: gh ? (d.abfrage === 'kontingent' ? t('GitHub-Kontingent erschöpft') : t('GitHub nicht erreichbar'))
          : (d.abfrage === 'kontingent' ? t('{dienst}-Kontingent erschöpft', { dienst: dn }) : t('{dienst} nicht erreichbar', { dienst: dn })),
          text: (gh ? t('Workflows zeigen den Stand von {z}', stand) : t('Jobs zeigen den Stand von {z}', stand)) + (d.naechste ? ' · ' + t('neuer Versuch in {n} s', { n: Math.max(0, Math.round((ms(d.naechste) - jetzt) / 1000)) }) : '') };
      } else if (m.id === 'token') {
        if (d.tokenAblauf) {
          const tage = Math.ceil((ms(d.tokenAblauf) - jetzt) / 86400000);
          if (tage > 14 || tage <= 0) continue;
          const w = { n: tage, tage: mehrzahl(tage, t('Tag'), t('Tagen')), dienst: dn };
          e = { nach: true, cls: 'warn', ic: IC.schluessel(18), titel: gh ? t('GitHub-Token läuft in {n} {tage} ab', w) : t('{dienst}-Token läuft in {n} {tage} ab', w),
            text: gh ? t('am {d} – danach bleiben die Workflows leer', { d: datum(d.tokenAblauf) }) : t('am {d} – danach bleiben die Jobs leer', { d: datum(d.tokenAblauf) }) };
        } else if (d.abfrage === 'kein-token') e = { cls: 'neutral', ic: IC.schluessel(18), titel: gh ? t('Kein GitHub-Token') : t('Kein {dienst}-Token', { dienst: dn }), text: gh ? t('Workflows und GitHub-Status sind aus') : t('Jobs und Status bei {dienst} sind aus', { dienst: dn }) };
        else {
          const titel = d.abfrage === 'token-ungueltig' ? (gh ? t('GitHub-Token ungültig oder abgelaufen') : t('{dienst}-Token ungültig oder abgelaufen', { dienst: dn }))
            : (gh ? t('GitHub-Token ohne Zugriff') : t('{dienst}-Token ohne Zugriff', { dienst: dn }));
          e = { cls: 'fehler', ic: IC.schluessel(18), titel, text: gh ? t('Workflows werden nicht mehr abgefragt') : t('Jobs werden nicht mehr abgefragt') };
        }
      }
      if (!e) continue;
      e.titel = vor + e.titel; e.id = ANLEITUNG[m.id];
      if (mehrere && RUNNER.fremd(m, S.wahl.gewaehlt)) { e.link = t('Anzeigen'); e.runner = m.runner; }
      M.push(e);
    }
    // Ein Runner: Reihenfolge wie in 0.4.0 (Dienst, Offline, Abfrage, Token); mehrere: Schwere wie vom Server
    if (!mehrere) { const rang = ['gestoppt', 'runner', 'offline', 'github', 'token']; M.sort((a, b) => rang.indexOf(a.id) - rang.indexOf(b.id)); }
    return M;
  }

  function vergleiche(a, b) {
    const t = v => String(v || '').split('-')[0].split('.').map(n => parseInt(n, 10) || 0);
    const x = t(a), y = t(b);
    for (let i = 0; i < 3; i++) { if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0) ? 1 : -1; }
    return 0;
  }

  /* ------------------------------------------------------------ Kopf */
  function bezug() { return S.verbindung === 'verbunden' ? Date.now() : (S.letzteDaten || Date.now()); }

  function renderKopf() {
    const st = S.status, jetzt = Date.now();
    if (st) {
      $('vm-name').textContent = st.vm || '–'; $('runner-name').textContent = st.runner || t('kein Runner');
      const plakette = mehrereRunner() ? [RUNNER.dienstName(st.anbieter) || t('unbekannt')] : [];  // Dienst als erstes Label
      const lb = [...plakette, ...(st.labels || [])].map(l => `<span class="label">${esc(l)}</span>`).join('');
      if ($('labels').innerHTML !== lb) $('labels').innerHTML = lb;
      document.title = `Runner-Monitor · ${st.vm}`;
    }
    const live = $('live');
    if (S.verbindung === 'verbunden') { live.className = 'live ok'; live.innerHTML = `<span class="punkt"></span><span>${t('Verbunden')}</span><span class="live-zeit">${t('aktualisiert {z}', { z: zeit(S.letzteDaten) })}</span>`; }
    else if (S.verbindung === 'getrennt') { live.className = 'live weg'; live.innerHTML = `${IC.getrennt()}<span>${t('Getrennt')}</span><span class="live-zeit">${S.letzteDaten ? t('Stand {z}', { z: zeit(S.letzteDaten) }) : t('noch keine Daten')}</span>`; }
    else { live.className = 'live neutral'; live.innerHTML = `<span class="punkt"></span><span>${t('Verbinde …')}</span>`; }
    $('uhr-datum').textContent = `${wt(jetzt)} ${tm(jetzt)}`; $('uhr-zeit').textContent = zeit(jetzt);
    $('raster').classList.toggle('veraltet', S.verbindung === 'getrennt' && !!S.letzteDaten);

    const M = meldungen(), box = $('meldungen');
    if (!M.length) { box.replaceChildren(); return; }
    const m = M[0];
    const html = `<div class="meldung ${m.cls}">${m.ic}<b>${esc(m.titel)}</b><span class="meldung-text">${esc(m.text)}</span>${M.length > 1 ? `<span class="meldung-mehr">${t('+{n} weitere', { n: M.length - 1 })}</span>` : ''}<button type="button" class="meldung-link" ${m.runner ? `data-aktion="runner-waehlen" data-runner="${esc(m.runner)}"` : `data-aktion="info" data-anleitung="${m.id}"`}>${esc(m.link || t('Was tun?'))}</button></div>`;
    if (box.dataset.html !== html) { box.innerHTML = html; box.dataset.html = html; }
  }

  function renderModus() {
    const th = RM.thema();
    const name = { system: t('Auto'), hell: t('Hell'), dunkel: t('Dunkel') }[th];
    const ic = { system: IC.auto(), hell: IC.sonne(), dunkel: IC.mond() }[th];
    const folgt = { system: t('Hell'), hell: t('Dunkel'), dunkel: t('Automatisch') }[th];
    const k = $('k-modus'); k.innerHTML = `${ic}${name}`; k.setAttribute('aria-label', t('Darstellung {a}, umschalten auf {b}', { a: name, b: folgt }));
  }

  /* ------------------------------------------------------------ Runner-Status */
  function renderStatus() {
    const st = S.status; if (!st) return;
    const jetzt = Date.now(), ref = bezug(), w = S.workflows;
    const dn = RUNNER.dienstName(st.anbieter) || 'GitHub';  // Dienst des Runners (ohne runner[]: GitHub)
    // Grundüberwachung (faehig.jobs false, #95): Dienst, Neustarts und Journal; ohne „Online bei …“ und „Letzte Jobs“.
    // Teilweise (Jobs ja, Schritte nein): „Schritte nicht verfügbar“. Gesteuert nur über faehig (RUNNER.ansicht).
    const grund = !!st.nurGrund, ohneSchritte = !!st.ohneSchritte;
    // „unbekannt“ (#93): Runner-Liste oder Läufe beim Dienst nicht lesbar – dann nie „Bereit“ behaupten
    // Alter des letzten guten Stands (#123): fällt die Abfrage länger aus, bleibt Job/Online-Status nicht stehen
    const alt = grund ? { stufe: 'frisch' } : RUNNER.alter(w, jetzt);
    const veraltet = alt.stufe === 'veraltet' && st.dienst.zustand === 'aktiv';
    const unbekannt = (st.zustand === 'unbekannt' || veraltet) && st.dienst.zustand === 'aktiv';
    // #145: Abfrage in Ordnung, der Runner fehlt nur in den lesbaren Runner-Listen – „Dienst aktiv“ mit Hinweis, nie „Bereit“
    const nichtSichtbar = !grund && !veraltet && !!st.nichtSichtbar;
    const art = st.dienst.zustand === 'fehlt' ? 'fehlt' : st.dienst.zustand === 'gestoppt' ? 'gestoppt' : grund ? 'aktiv' : veraltet ? 'unbekannt' : st.github.zustand === 'offline' ? 'offline' : st.job ? 'job' : unbekannt ? 'unbekannt' : nichtSichtbar ? 'aktiv' : 'bereit';
    const nichtZuordenbar = art === 'job' && st.job.zuordenbar === false;  // beschäftigt, Job nicht gefunden (#93)
    const pillD = st.dienst.zustand === 'aktiv' ? `<span class="pill ok">${IC.ok(13, 1.7)}${t('Dienst aktiv')}</span>` : st.dienst.zustand === 'fehlt' ? `<span class="pill neutral">${IC.unklar()}${t('Kein Dienst')}</span>` : `<span class="pill fehler">${IC.x(13, 1.7)}${t('Dienst gestoppt')}</span>`;
    const g = veraltet ? 'unbekannt' : st.github.zustand;
    const pillG = g === 'online' ? `<span class="pill ok">${IC.ok(13, 1.7)}${t('Online bei {dienst}', { dienst: dn })}</span>` : g === 'offline' ? `<span class="pill fehler">${IC.x(13, 1.7)}${t('Offline bei {dienst}', { dienst: dn })}</span>`
      // #145: „nicht sichtbar“ auch bei „Job läuft“ (Job über die UUID aus .runner zugeordnet)
      : !grund && !veraltet && st.github.sichtbar === false ? `<span class="pill neutral">${IC.unklar()}${t('{dienst}: nicht sichtbar', { dienst: dn })}</span>`
        : `<span class="pill neutral">${IC.unklar()}${t('{dienst}: unbekannt', { dienst: dn })}</span>`;
    // Runner aus runner[] ohne Dienst (keine Unit, Unit weg): neutral „Kein Dienst“ wie sein Reiter (Review #114).
    // „Kein Runner“ mit Einrichtungsbefehl nur, wenn es gar keinen Runner gibt (Altformat ohne runner[], ohne id).
    const keinDienst = art === 'fehlt' && !!st.id;
    const kopf = keinDienst ? ['neutral', IC.unklar(28), t('Kein Dienst')] : {
      aktiv: ['ok', IC.ok(28, 1.3), t('Dienst aktiv')],
      job: ['laeuft', IC.play(28, 1.3), t('Job läuft')], bereit: ['ok', IC.ok(28, 1.3), t('Bereit')], fehlt: ['warn', IC.warn(28, 1.3), t('Kein Runner')],
      gestoppt: ['fehler', IC.stop(28), t('Dienst gestoppt')], offline: ['warn', IC.warn(28, 1.3), t('Offline bei {dienst}', { dienst: dn })],
      unbekannt: ['neutral', IC.unklar(28), t('Zustand unbekannt')],
    }[art];
    const l0 = (st.letzteJobs || [])[0];
    const letzter = l0 ? `${l0.repo ? esc(l0.repo) + ' · ' : ''}${l0.workflow ? esc(l0.workflow) + ' · ' : ''}${esc(l0.name)} · ${vor((jetzt - ms(l0.ende)) / 1000)}` : '–';
    let mitte, dyn = null;
    if (nichtZuordenbar) {
      const dienstSeit = st.dienst.seit ? t('aktiv seit {d}', { d: seit((jetzt - ms(st.dienst.seit)) / 1000) }) : t('aktiv');
      mitte = `<div class="job-repo">${t('Job nicht zuordenbar')}</div>`
        + `<p class="zustand-text">${t('{dienst} meldet den Runner als beschäftigt, der Job lässt sich aber keinem Repository der Organisation zuordnen.', { dienst: dn })}</p>`
        + `<dl class="kv"><div class="kv-z"><dt>${t('Dienst')}</dt><dd>${dienstSeit}</dd></div><div class="kv-z"><dt>${t('Letzter Job')}</dt><dd>${letzter}</dd></div></dl>`;
    } else if (art === 'job') {
      // Ein Schritt aus einer Quelle (Server, Design 0.4.0). Ohne Liste von GitHub: „3 von –“,
      // Name gedämpft, ein gestrichelter Rest – der Aufbau bleibt gleich, wenn GitHub nachliefert.
      // Gerüst nur mit der Zahl der Segmente; Zahl, Name, Klassen und Laufzeit setzt dynamik() unten
      // direkt – so wird der Block beim Nachtragen nicht neu aufgebaut und die Übergänge wirken.
      const j = st.job, { nr, von } = schrittVon(j), segN = von || nr + 1;
      const segs = '<span class="seg"></span>'.repeat(segN);
      dyn = { ...schrittVon(j), segN, ohneSchritte, laufzeit: j.start ? dauer((ref - ms(j.start)) / 1000) : '–' };
      mitte = `
        <div>
          <div class="job-repo">${esc(j.repo || j.name)}${j.privat ? IC.schloss() : ''}</div>
          ${j.workflow ? `<div class="job-pfad">${t('Workflow')} <b>${esc(j.workflow)}</b><span class="sep">›</span>${t('Job')} <b>${esc(j.name)}</b></div>` : `<div class="job-pfad">${t('Job')} <b>${esc(j.name)}</b></div>`}
          ${j.ref ? `<div class="job-ref"><span>${esc(j.ref.art)}</span><span class="ref">${esc(j.ref.name)}</span><span class="ref-titel">${esc(j.ref.titel || '')}</span></div>` : ''}
        </div>
        ${ohneSchritte ? `<div class="schritt">
          <div class="zeile-k"><span>${t('Aktueller Schritt')}</span></div>
          <div class="schritt-name mut">${t('Schritte nicht verfügbar')}</div>
          <div class="zeile-k ohne-schritte">${t('Der Dienst meldet keine Schritte – Job und Laufzeit bleiben sichtbar.')}</div>` : `<div class="schritt">
          <div class="zeile-k"><span>${t('Aktueller Schritt')}</span><span class="schritt-zahl"></span></div>
          <div class="schritt-name"></div>
          <div class="segmente" data-spalten="${segN}">${segs}</div>`}
        </div>
        <div class="zahlen">
          <div><div class="zeile-k">${t('Laufzeit')}</div><div class="zahl-gross laufzeit"></div></div>
          <div><div class="zeile-k">${t('Gestartet')}</div><div class="zahl-mittel">${j.start ? zeit(j.start) : '–'}</div><div class="zahl-sub">${j.start ? `${wt(j.start)}, ${tm(j.start)}` : ''}</div></div>
        </div>`;
    } else {
      const text = {
        aktiv: nichtSichtbar ? t('Der Dienst läuft. {dienst} zeigt den Runner in keiner Runner-Liste, die das Token lesen darf (globaler Runner? Token-Rechte) – ob er dort online ist, ist unbekannt. Laufende Jobs erscheinen, sobald sie sich dem Runner zuordnen lassen.', { dienst: dn })
          : t('Nur Grundüberwachung: Dienst, Neustarts und Log. Jobs und Schritte sind ohne Anbindung an den Dienst nicht verfügbar.'),
        bereit: t('Wartet auf den nächsten Job. Neue Jobs starten automatisch.'),
        gestoppt: grund ? t('Nur Grundüberwachung: Dienst, Neustarts und Log. Jobs und Schritte sind ohne Anbindung an den Dienst nicht verfügbar.') : t('Der Runner-Dienst läuft nicht. Neue Jobs bleiben bei {dienst} in der Warteschlange, bis er wieder startet.', { dienst: dn })
          + (st.dienst.grund === 'oom-kill' ? ' ' + t('Ein Job hat den Arbeitsspeicher gesprengt – mehr RAM oder Swap hilft.') : ''),
        offline: t('Der Dienst läuft, aber {dienst} sieht den Runner nicht. Jobs werden ihm gerade nicht zugestellt.', { dienst: dn }),
        unbekannt: veraltet && alt.seit ? t('Der Dienst läuft, aber der letzte Stand von {dienst} ist von {z} ({vor}) – ob ein Job läuft, ist unbekannt. Verbindung und Rechte des Tokens prüfen.', { dienst: dn, z: zeit(alt.seit), vor: vor((jetzt - alt.seit) / 1000) })
          : t('Der Dienst läuft, aber {dienst} liefert gerade keinen lesbaren Stand – ob ein Job läuft, ist unbekannt. Verbindung und Rechte des Tokens prüfen.', { dienst: dn }),
        fehlt: keinDienst ? t('Für diesen Runner wurde kein Dienst gefunden.') : t('Auf dieser VM ist kein GitHub-Runner eingerichtet. Das Einrichtungsskript kann ihn mit einrichten.'),
      }[art];
      const wartend = w && w.abfrage === 'ok' ? w.repos.reduce((a, r) => a + r.wartet, 0) : null;
      const dienstSeit = st.dienst.seit ? (art === 'gestoppt' ? t('gestoppt seit {z} ({vor})', { z: zeit(st.dienst.seit), vor: vor((jetzt - ms(st.dienst.seit)) / 1000) }) : t('aktiv seit {d}', { d: seit((jetzt - ms(st.dienst.seit)) / 1000) })) : (art === 'gestoppt' ? t('gestoppt') : art === 'fehlt' ? t('nicht vorhanden') : t('aktiv'));
      // Grundüberwachung: Dienst (Unit · aktiv seit …), Neustarts (NRestarts) und Letzter Stopp (InactiveEnterTimestamp)
      const ns = RUNNER.neustarts(st.dienst), stopp = st.dienst.letzterStopp;
      const kv = keinDienst ? (st.unit ? [[t('Dienst'), `${esc(st.unit)} · ${dienstSeit}`]] : [])
        // gestoppt: wann, steht unter „Letzter Stopp“ – die Dienstzeile bleibt kurz
        : grund ? [[t('Dienst'), (st.unit ? esc(st.unit) + ' · ' : '') + (art === 'gestoppt' && stopp ? t('gestoppt') : dienstSeit)], ...(art === 'gestoppt' && stoppGrund(st) ? [[t('Grund'), esc(stoppGrund(st))]] : []),
        [t('Neustarts'), ns.art === 'keine' ? t('keine') : ns.art === 'zahl' ? t('{n} automatisch', { n: ns.n }) : '–'],
        [t('Letzter Stopp'), stopp ? `${tm(stopp)} ${hm(stopp)} (${vor((jetzt - ms(stopp)) / 1000)})` : '–']]
        : art === 'gestoppt' ? [[t('Dienst'), dienstSeit], ...(stoppGrund(st) ? [[t('Grund'), esc(stoppGrund(st))]] : []), [t('Wartende Jobs'), wartend == null ? t('unbekannt') : t('{n} in der Warteschlange', { n: wartend })], [t('Letzter Job'), letzter]]
        : art === 'offline' ? [[t('Dienst'), dienstSeit], [t('Bei {dienst}', { dienst: dn }), st.github.seit ? t('offline seit {z} ({vor})', { z: zeit(st.github.seit), vor: vor((jetzt - ms(st.github.seit)) / 1000) }) : t('offline')], [t('Letzter Job'), letzter]]
        : art === 'fehlt' ? [['Runner', t('nicht gefunden in /opt/actions-runner')], [t('Einrichten'), `${SKRIPT} runner`]]
        : [[t('Dienst'), dienstSeit], ...(nichtSichtbar ? [[t('Bei {dienst}', { dienst: dn }), t('nicht sichtbar')]] : []), [t('Letzter Job'), letzter], [t('Runner-Version'), esc(st.version || '–')]];
      mitte = `<p class="zustand-text">${text}</p><dl class="kv">${kv.map(([k, v]) => `<div class="kv-z"><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl>`
        + (art === 'gestoppt' || art === 'offline' ? `<button type="button" class="link-knopf" data-aktion="info" data-anleitung="logs">${IC.datei()}${t('Runner-Logs abrufen ›')}</button>` : '')
        + (nichtSichtbar ? `<button type="button" class="link-knopf" data-aktion="info" data-anleitung="token">${t('Anleitung: Token-Rechte ›')}</button>` : '');
    }
    const ERG = { erfolg: ['ok', IC.ok(), t('Erfolg')], fehler: ['fehler', IC.x(), t('Fehler')], abgebrochen: ['neutral', IC.abbr(), t('Abgebrochen')] };
    const letzte = (st.letzteJobs || []).slice(0, 5).map(j => {
      const e = ERG[j.ergebnis] || ERG.abgebrochen;
      const wf = [j.workflow, j.name].filter(Boolean).map(esc).join(' · ');
      return `<div class="jobzeile"><span class="erg ${e[0]}">${e[1]}${e[2]}</span><span class="jz-name">${esc(j.repo || '')}${j.repo ? ' ' : ''}<span class="jz-wf">${j.repo ? '· ' : ''}${wf}</span></span><span class="r">${j.dauer != null ? dauer(j.dauer) : '–'}</span><span class="jz-ende">${hm(j.ende)}</span></div>`;
    }).join('');
    const html = `
      <div class="karte-kopf"><span class="karte-titel">${t('Runner-Status')}</span><div class="pillen">${pillD}${grund ? '' : pillG}</div></div>
      <div class="zustand ${kopf[0]}">${kopf[1]}<span class="zustand-titel">${kopf[2]}</span></div>
      ${mitte}
      ${alt.stufe === 'hinweis' && alt.seit ? `<div class="hinweis warn alt-hinweis">${IC.warn()}<div>${t('Stand von {z} ({vor})', { z: zeit(alt.seit), vor: vor(alt.sekunden) })} <span>${t('– {dienst} liefert seitdem keine neuen Daten.', { dienst: dn })}</span></div></div>` : ''}
      ${grund ? '' : `<div class="letzte"><div class="letzte-titel">${t('Letzte Jobs')}</div>${letzte || `<div class="leer">${t('Seit dem Start des Monitors noch keine Jobs.')}</div>`}</div>`}`;
    // nur bei Änderung neu schreiben – sonst gehen Klicks und Fokus auf Knöpfen der Karte verloren
    const karte = $('status');
    if (karte.dataset.html !== html) {
      karte.innerHTML = html; karte.dataset.html = html;
      // Spaltenzahl der Schritt-Segmente per CSSOM (CSP erlaubt keine style-Attribute)
      const segs = karte.querySelector('.segmente');
      if (segs) segs.style.gridTemplateColumns = `repeat(${segs.dataset.spalten}, minmax(0, 1fr))`;
    }
    if (dyn) {
      const setze = (el, x) => { if (el && el.textContent !== x) el.textContent = x; };
      setze(karte.querySelector('.laufzeit'), dyn.laufzeit);
      if (dyn.ohneSchritte) return;  // „Schritte nicht verfügbar“ bleibt stehen
      setze(karte.querySelector('.schritt-zahl'), t('{nr} von {von}', { nr: dyn.nr, von: dyn.von || '–' }));
      const nm = karte.querySelector('.schritt-name');
      setze(nm, dyn.name || t('Schritt {nr}', { nr: dyn.nr })); if (nm) nm.classList.toggle('mut', !dyn.name);
      karte.querySelectorAll('.segmente .seg').forEach((sg, i) => {
        sg.className = `seg${i < dyn.nr - 1 ? ' fertig' : i === dyn.nr - 1 ? ' aktiv' : dyn.von ? '' : ' unbekannt'}`;
      });
    }
  }

  /* ------------------------------------------------------------ Workflows */
  function renderWorkflows() {
    const w = S.workflows, el = $('workflows');
    if (S.status && S.status.nurGrund) {
      // Runner ohne Jobs (faehig.jobs false, Grundüberwachung): ruhiger Leerzustand wie im Design (Aufbau wie „Kein Token“),
      // Unit als Pfad, „Runner zuordnen ›“ öffnet Info & Hilfe (Zuordnung ändern kommt mit dem Info-Blatt, #97)
      const unit = S.status.unit ? `<div class="leer-pfad">${esc(S.status.unit)}</div>` : '';
      const leer = `<div class="karte-kopf"><span class="karte-titel">${t('Jobs je Repository')}</span><span class="karte-meta">${t('keine Anbindung')}</span></div><div class="leerzustand"><span class="leer-ic">${IC.schluessel(26, 1.2)}</span><div class="leer-titel">${t('Jobs nicht verfügbar')}</div><div class="leer-text">${t('Für diesen Runner gibt es keine Anbindung an den Dienst. Dienst, Auslastung und Log laufen normal weiter.')}</div>${unit}<button type="button" class="link-knopf" data-aktion="runner-zuordnen" data-runner="${esc(S.status.id || '')}">${t('Runner zuordnen ›')}</button></div><div class="wf-fuss"><div class="wf-zeit">${t('Abfrage aus')}</div></div>`;
      if (el.dataset.html !== leer) { el.innerHTML = leer; el.dataset.html = leer; }
      return;
    }
    if (!w) return;
    if (el.contains(document.activeElement) && el.dataset.letzte && Date.now() - Number(el.dataset.letzte) < 5000) return;
    el.dataset.letzte = String(Date.now());
    const jetzt = Date.now();
    // Dienst des gewählten Runners (#123): Texte, Pfad und „Was tun?“ gelten für ihn, nicht für GitHub
    const dn = RUNNER.dienstName(S.status && S.status.anbieter) || 'GitHub', gw = gewaehlterRunner();
    const tokenPfad = S.status && S.status.id ? INFO.tokenDatei(S.status.id) : '/etc/runner-monitor/github-token';
    let inhalt = '', fuss = '', zeitText = '';
    if (w.abfrage === 'ausstehend') {
      // E-25: neu angebunden, die erste Abfrage beim Dienst läuft noch – keine Meldung „Kein Token“
      inhalt = `<div class="leerzustand"><span class="leer-ic">${IC.uhr(26, 1.2)}</span><div class="leer-titel">${t('Wird abgefragt …')}</div><div class="leer-text">${t('Die erste Abfrage beim Dienst läuft.')}</div></div>`;
      fuss = `<div class="wf-zeit">${t('Abfrage läuft')}</div>`;
    } else if (w.abfrage === 'kein-token') {
      inhalt = `<div class="leerzustand"><span class="leer-ic">${IC.schluessel(26, 1.2)}</span><div class="leer-titel">${t('Kein {dienst}-Token eingerichtet', { dienst: dn })}</div><div class="leer-text">${t('Ohne Token bleibt dieser Bereich leer. Runner-Status, Auslastung und Log laufen normal weiter.')}</div><div class="leer-pfad">${esc(tokenPfad)}</div><button type="button" class="link-knopf" data-aktion="info" data-anleitung="token">${t('Anleitung: Token einrichten ›')}</button></div>`;
      fuss = `<div class="wf-zeit">${t('Abfrage aus')}</div>`;
    } else {
      const aktiv = w.repos.filter(r => r.laeuft || r.wartet), ruhig = w.repos.filter(r => !r.laeuft && !r.wartet);
      const L = aktiv.reduce((a, r) => a + r.laeuft, 0), W = aktiv.reduce((a, r) => a + r.wartet, 0);
      const alt = !['ok'].includes(w.abfrage);
      inhalt = `<div class="wf-inhalt${alt ? ' alt' : ''}">
        <div class="summen">
          <div class="summe laeuft">${IC.play(16)}<span class="summe-zahl">${L}</span><span class="summe-text">${mehrzahl(L, t('läuft'), t('laufen'))}</span></div>
          <div class="summe wartet">${IC.uhr()}<span class="summe-zahl">${W}</span><span class="summe-text">${mehrzahl(W, t('wartet'), t('warten'))}</span></div>
        </div>
        ${aktiv.map(r => `<div class="repo"><span class="repo-name">${esc(r.name)}${r.privat ? IC.schloss(12) : ''}</span><span class="repo-pillen">${r.laeuft ? `<span class="pill laeuft">${IC.dreieck()}${r.laeuft} ${mehrzahl(r.laeuft, t('läuft'), t('laufen'))}</span>` : ''}${r.wartet ? `<span class="pill wartet">${IC.uhr(12, 1.7)}${r.wartet} ${mehrzahl(r.wartet, t('wartet'), t('warten'))}</span>` : ''}</span></div>`).join('')}
        ${aktiv.length ? '' : `<div class="alle-ruhig">${IC.ok()}${t('Nichts läuft, nichts wartet')}</div>`}
        ${ruhig.length ? `<button type="button" class="ruhig-knopf" data-aktion="wf-offen" aria-expanded="${S.wfOffen}">${IC.chev(S.wfOffen)}${aktiv.length ? t('{n} weitere ruhig', { n: ruhig.length }) : t('Alle {n} Repositories ruhig', { n: ruhig.length })}</button>` : ''}
        ${S.wfOffen ? `<div class="ruhig-liste">${ruhig.map(r => `<span class="ruhig-repo">${esc(r.name)}</span>`).join('')}</div>` : ''}
      </div>`;
      if (alt) {
        const texte = { 'nicht-erreichbar': t('{dienst} nicht erreichbar', { dienst: dn }), kontingent: t('API-Kontingent erschöpft'), 'token-ungueltig': t('Token ungültig oder abgelaufen'), 'keine-rechte': t('Token ohne Zugriff auf die Organisation'), fehler: t('Abfrage fehlgeschlagen') };
        fuss += `<div class="hinweis warn">${IC.warn()}<div>${texte[w.abfrage] || t('Abfrage fehlgeschlagen')} <span>${t('– angezeigt wird der Stand von {z} ({vor}).', { z: w.abgefragt ? zeit(w.abgefragt) : '–', vor: w.abgefragt ? vor((jetzt - ms(w.abgefragt)) / 1000) : '–' })}${w.naechste ? ' ' + t('Neuer Versuch in {n} s.', { n: Math.max(0, Math.round((ms(w.naechste) - jetzt) / 1000)) }) : ''}</span></div></div>`;
      }
      if (w.tokenAblauf) {
        const tage = Math.ceil((ms(w.tokenAblauf) - jetzt) / 86400000);
        if (tage <= 14) fuss += `<div class="hinweis warn">${IC.schluessel()}<div>${tage > 0 ? t('Token läuft in {n} {tage} ab', { n: tage, tage: mehrzahl(tage, t('Tag'), t('Tagen')) }) : t('Token ist abgelaufen')} <span>${t('({d}). Danach bleibt dieser Bereich leer.', { d: datum(w.tokenAblauf) })}</span></div></div>`;
      }
      const nx = w.naechste ? Math.max(0, Math.round((ms(w.naechste) - jetzt) / 1000)) : null;
      zeitText = alt ? t('Letzte erfolgreiche Abfrage {z}', { z: w.abgefragt ? zeit(w.abgefragt) : '–' }) : t('Abgefragt {z}', { z: zeit(w.abgefragt) }) + (S.verbindung === 'verbunden' && nx != null ? ' · ' + t('nächste in {n} s', { n: nx }) : '');
      fuss += '<div class="wf-zeit"></div>';
    }
    const orgText = w.org || INFO.ohneSchema(gw && gw.server) || '–';
    const meta = ['kein-token', 'ausstehend'].includes(w.abfrage) ? esc(orgText) : `${esc(orgText)} · ${t('{n} Repositories', { n: w.repos.length })}`;
    const html = `<div class="karte-kopf"><span class="karte-titel">${t('Jobs je Repository')}</span><span class="karte-meta">${meta}</span></div>${inhalt}<div class="wf-fuss">${fuss}</div>`;
    // nur bei Änderung neu schreiben; die sekündlich wechselnde Zeitzeile per textContent
    if (el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; }
    const zt = el.querySelector('.wf-zeit'); if (zt && zeitText && zt.textContent !== zeitText) zt.textContent = zeitText;
  }

  /* ------------------------------------------------------------ Auslastung */
  /* Verläufe mit festen Zeitfenstern (Design 0.8.0): Rechenlogik in verlauf.js. Der Zeitraum gilt für
     alle Verläufe der Karte; CPU/RAM zeigen den Mittelwert je Eimer, das Netz das Maximum. */
  function spark(h, max = 100, agg = 'mittel') { return VERLAUF.pfade(h, S.ende == null ? 0 : S.ende, S.zeitraum, max, agg); }
  /* Texte je Zeitraum, als feste Schlüssel für die Übersetzung (tests/test_i18n.py). */
  function zeitraumTexte(r) {
    return {
      30: { achse: t('vor 30 s'), aria: t('der letzten 30 Sekunden') },
      120: { achse: t('vor 2 Min.'), aria: t('der letzten 2 Minuten') },
      300: { achse: t('vor 5 Min.'), aria: t('der letzten 5 Minuten') },
      600: { achse: t('vor 10 Min.'), aria: t('der letzten 10 Minuten') },
    }[r];
  }
  /* Achse links: „vor 2 Min.“ bei vollem Verlauf, sonst ab wann gemessen wird („seit 14:02“). */
  function achseVon() {
    if (S.ende == null || VERLAUF.voll(S.cpuH.length, S.zeitraum)) return zeitraumTexte(S.zeitraum).achse;
    return t('seit {z}', { z: hm(S.ende + 1 - S.cpuH.length) });
  }
  function renderZeitraum() {
    document.querySelectorAll('#zeitraum .seg-knopf').forEach((b) => { b.setAttribute('aria-pressed', String(Number(b.dataset.zeitraum) === S.zeitraum)); });
    const z = zeitraumTexte(S.zeitraum).aria;
    $('cpu-svg').setAttribute('aria-label', t('CPU-Verlauf {zr}', { zr: z }));
    $('ram-svg').setAttribute('aria-label', t('RAM-Verlauf {zr}', { zr: z }));
    $('netz-svg').setAttribute('aria-label', t('Netzwerk-Verlauf {zr}, empfangen und gesendet', { zr: z }));
  }

  /* Bytes je Sekunde, dezimal wie bei Netzwerken üblich (1 MB/s = 1 000 000 B/s). */
  function rate(b) {
    for (const [e, f] of [['GB/s', 1e9], ['MB/s', 1e6], ['KB/s', 1e3]]) {
      if (b >= f * 0.9995) { const v = b / f; return [zahl(v, v < 99.95 ? 1 : 0), e]; }
    }
    return [zahl(Math.round(b || 0), 0), 'B/s'];
  }
  function setzeRate(id, b) { const [w, e] = rate(b); $(id).textContent = w; $(id + '-e').textContent = e; }
  function renderSystem() {
    const d = S.system; if (!d) return;
    const n = d.kerne.length;
    $('sys-meta').textContent = t('{n} Kerne · {ram} GB RAM · läuft seit {d}', { n, ram: zahl(d.ram.gesamt / GiB, 0), d: seit((Date.now() - ms(d.start)) / 1000) });
    $('cpu').textContent = zahl(d.cpu, 0);
    const k = $('kerne');
    if (S.kerneN !== n) {
      S.kerneN = n;
      k.style.gridTemplateRows = `repeat(${Math.ceil(n / 2)}, minmax(12px, 24px))`;
      k.innerHTML = d.kerne.map((_, i) => `<div class="kern"><span class="kern-l">${i + 1}</span><span class="balken"><span class="fuell"></span></span><span class="kern-w"></span></div>`).join('');
    }
    [...k.children].forEach((row, i) => { feder(row.children[1].firstChild, d.kerne[i] / 100); row.children[2].textContent = `${zahl(d.kerne[i], 0)} %`; });
    const [cl, cf] = spark(S.cpuH), [rl, rf] = spark(S.ramH);
    $('cpu-linie').setAttribute('d', cl); $('cpu-flaeche').setAttribute('d', cf);
    $('ram-linie').setAttribute('d', rl); $('ram-flaeche').setAttribute('d', rf);
    $('ram').textContent = `${zahl(d.ram.belegt / GiB, 1)} GB`; $('ram-gesamt').textContent = `/ ${zahl(d.ram.gesamt / GiB, 0)} GB`;
    feder($('ram-fuell'), d.ram.gesamt ? d.ram.belegt / d.ram.gesamt : 0);
    $('ram-pct').textContent = `${zahl(d.ram.gesamt ? d.ram.belegt / d.ram.gesamt * 100 : 0, 0)} %`;
    feder($('swap-fuell'), d.swap.gesamt ? d.swap.belegt / d.swap.gesamt : 0);
    $('swap').textContent = `${zahl(d.swap.belegt / GiB, 1)} / ${zahl(d.swap.gesamt / GiB, 1)} GB`;
    if (d.netz) {
      setzeRate('netz-rx', d.netz.empfangen); setzeRate('netz-tx', d.netz.gesendet);
      // Skala nach der Spitze im gewählten Zeitraum, mindestens 64 KB/s – so bleibt der Leerlauf ruhig.
      const { spitze, skala } = VERLAUF.spitze([S.netzH.map(w => w[0]), S.netzH.map(w => w[1])], S.zeitraum, 64e3);
      const [rl2, rf2] = spark(S.netzH.map(w => w[0]), skala, 'max'), [tl] = spark(S.netzH.map(w => w[1]), skala, 'max');
      $('netz-rx-linie').setAttribute('d', rl2); $('netz-rx-flaeche').setAttribute('d', rf2); $('netz-tx-linie').setAttribute('d', tl);
      const [w, e] = rate(spitze); $('netz-spitze').textContent = t('Spitze {w} {e}', { w, e });
    }
    renderZeitraum();
    const von = achseVon();
    document.querySelectorAll('.achse-von').forEach((el) => { if (el.textContent !== von) el.textContent = von; });
    $('l1').textContent = zahl(d.last[0], 2); $('l5').textContent = zahl(d.last[1], 2); $('l15').textContent = zahl(d.last[2], 2); $('kerne-n').textContent = n;
  }

  function renderProzesse() {
    // Pfade auf den letzten Teil kürzen, z. B. „node vitest run“
    const kurz = b => b.split(' ').map(t => (t.includes('/') && !t.startsWith('fd:') ? t.replace(/\/+$/, '').split('/').pop() || t : t)).join(' ');
    $('prozesse').innerHTML = (S.prozesse || []).slice(0, 6).map(p => `<div class="pz"><span class="mut">${p.pid}</span><span class="eng">${esc(p.benutzer)}</span><span class="r">${zahl(p.cpu, 1)}</span><span class="r mut">${zahl(p.ram, 1)}</span><span class="cmd" title="${esc(p.befehl)}">${esc(kurz(p.befehl))}</span></div>`).join('');
  }

  function renderPlatten() {
    const liste = S.platten || [];
    $('pl-anzahl').textContent = `${liste.length} ${mehrzahl(liste.length, t('Laufwerk'), t('Laufwerke'))}`;
    const box = $('platten');
    if (box.children.length !== liste.length || box.dataset.pfade !== liste.map(p => p.pfad).join('|')) {
      box.dataset.pfade = liste.map(p => p.pfad).join('|');
      box.innerHTML = liste.map(() => `<div class="pl-z"><div class="pl-z-kopf"><span class="mono pl-pfad"></span><span class="pl-frei-k"></span><span class="karte-meta"></span></div><div class="pl-balken" role="img"><span class="pl-teil"></span><span class="pl-teil ueber"></span><span class="pl-marke"></span></div><div class="pl-unten"></div></div>`).join('');
    }
    liste.forEach((p, i) => {
      const el = box.children[i];
      const hs = p.schwelleFrei > 0, sb = p.gesamt - p.schwelleFrei, knapp = hs && p.frei < p.schwelleFrei;
      const sPct = hs ? sb / p.gesamt * 100 : 100;
      el.querySelector('.pl-pfad').textContent = p.pfad;
      const frei = el.querySelector('.pl-frei-k'); frei.textContent = t('{n} GB frei', { n: zahl(p.frei / GB, 1) }); frei.classList.toggle('warn', knapp);
      el.querySelector('.karte-meta').textContent = t('{a} von {b} GB', { a: zahl(p.belegt / GB, 1), b: zahl(p.gesamt / GB, 0) });
      const balken = el.querySelector('.pl-balken');
      balken.setAttribute('aria-label', t('{pfad}: {a} von {b} GB belegt, {c} GB frei', { pfad: p.pfad, a: zahl(p.belegt / GB, 1), b: zahl(p.gesamt / GB, 0), c: zahl(p.frei / GB, 1) }));
      const [a, b] = balken.querySelectorAll('.pl-teil');
      a.style.width = `${Math.min(p.belegt, hs ? sb : p.gesamt) / p.gesamt * 100}%`;
      b.style.left = `${sPct}%`; b.style.width = `${hs ? Math.max(0, p.belegt - sb) / p.gesamt * 100 : 0}%`;
      const marke = balken.querySelector('.pl-marke'); marke.hidden = !hs; marke.style.left = `${sPct}%`;
      const unten = el.querySelector('.pl-unten');
      const html = !hs ? '' : knapp
        ? `<div class="hinweis warn pl-warn">${IC.warn(14)}<div>${t('Unter {n} GB frei', { n: zahl(p.schwelleFrei / GB, 0) })} <span>${t('– der Runner räumt vor jedem Job auf.')}</span></div></div>`
        : `<div class="pl-legende"><span>${t('Aufräumen unter {n} GB frei', { n: zahl(p.schwelleFrei / GB, 0) })}</span></div>`;
      if (unten.dataset.html !== html) { unten.innerHTML = html; unten.dataset.html = html; }
      const leg = unten.querySelector('.pl-legende span'); if (leg) leg.style.right = `${100 - sPct}%`;
    });
  }

  /* job.schritt = {nr, von, name} vom Server; von = null, solange GitHub keine Schrittliste geliefert hat. */
  function schrittVon(j) {
    const s = j && typeof j.schritt === 'object' && j.schritt ? j.schritt : {};
    return { nr: Math.max(1, Number(s.nr) || 1), von: Number(s.von) || null, name: s.name || '' };
  }

  /* ------------------------------------------------------------ Live-Log */
  function renderLogKopf() {
    const st = S.status, j = st && st.job, chip = $('schritt-chip');
    $('ereignisse').hidden = S.logFremd; $('term').hidden = S.logFremd;
    if (S.logQuelle === 'journal') {
      // Journal der Unit (Grundüberwachung, „teilweise“): Chip nennt die Quelle, keine Schritte
      chip.hidden = false; chip.textContent = t('Journal · {unit}', { unit: S.journalUnit });
    } else if (j && j.zuordenbar !== false && st.dienst.zustand === 'aktiv' && !S.logFremd && !st.ohneSchritte) {
      const { nr, von, name } = schrittVon(j);
      chip.hidden = false; chip.textContent = t('Schritt {nr}/{von}', { nr, von: von || '–' }) + (name ? ' · ' + name : '');
    } else chip.hidden = true;
    const aria = S.logQuelle === 'journal' ? t('Journal von {unit}', { unit: S.journalUnit }) : t('Ausgabe des laufenden Schritts');
    if ($('term').getAttribute('aria-label') !== aria) $('term').setAttribute('aria-label', aria);
    renderLeer();
  }

  function renderEreignisse() {
    const E = S.ereignisse.slice(-3).map(e => {
      const was = [e.repo, e.workflow].filter(Boolean).map(esc).join(' · ') + (e.repo || e.workflow ? ' / ' : '') + esc(e.name || '');
      if (e.art === 'start') return [e.zeit, 'laeuft', IC.play(), t('Job gestartet'), was, ''];
      if (e.art === 'ende') { const ok = e.ergebnis === 'erfolg'; const cls = ok ? 'ok' : e.ergebnis === 'fehler' ? 'fehler' : 'neutral'; return [e.zeit, cls, ok ? IC.ok() : e.ergebnis === 'fehler' ? IC.x() : IC.abbr(), t('Job beendet'), was, `${ok ? t('Erfolg') : e.ergebnis === 'fehler' ? t('Fehler') : t('Abgebrochen')}${e.dauer != null ? ' · ' + dauer(e.dauer) : ''}`]; }
      if (e.art === 'dienst-gestoppt') return [e.zeit, 'fehler', IC.x(), t('Dienst gestoppt'), t('Runner-Dienst: inactive (dead)'), ''];
      if (e.art === 'dienst-gestartet') return [e.zeit, 'ok', IC.ok(), t('Dienst gestartet'), t('Runner-Dienst: active (running)'), ''];
      return [e.zeit, 'warn', IC.warn(14), t('Hinweis'), esc(e.name || ''), ''];
    });
    $('ereignisse').innerHTML = E.map(([z, cls, ic, titel, text, rechts]) => `<div class="ev"><span class="ev-zeit">${zeit(z)}</span><span class="${cls}">${ic}</span><span class="ev-text"><b>${titel}</b> · ${text}</span><span class="ev-rechts ${cls}">${rechts}</span></div>`).join('');
  }

  function zeileEl(z) {
    const div = document.createElement('div');
    if (z.art === 'schritt') {
      div.className = 'trenner';
      div.innerHTML = `<span class="tr-nr">${t('Schritt {nr}/{von}', { nr: Number(z.nr) || 1, von: Number(z.von) || '–' })}</span><span class="tr-name">${esc(z.name || '')}</span><span class="tr-linie"></span><span class="tr-zeit">${zeit(z.zeit)}</span>`;
    } else if (z.art === 'luecke') {
      // Journal: eine Flut von Zeilen in einem Takt – die ältesten wurden nicht übertragen (Server, journal.py)
      const n = Math.max(1, Number(z.n) || 1);
      div.className = 'z luecke';
      div.innerHTML = `<span class="zt">${zeit(z.zeit)}</span><span class="zx">${esc(t('… {n} {zeilen} ausgelassen', { n, zeilen: mehrzahl(n, t('Zeile'), t('Zeilen')) }))}</span>`;
    } else {
      div.className = 'z' + (istFehler(z.text) ? ' fehler' : '');
      div.innerHTML = `<span class="zt">${zeit(z.zeit)}</span><span class="zx">${ansi(z.text).map(s => (s.c ? `<span class="${s.c}">${esc(s.t)}</span>` : esc(s.t))).join('')}</span>`;
    }
    return div;
  }
  function haengeAn(zeilen) {
    const innen = $('term-innen'), frag = document.createDocumentFragment();
    for (const z of zeilen) frag.appendChild(zeileEl(z));
    innen.appendChild(frag); S.zeilenN += zeilen.length;
    while (S.zeilenN > MAX_ZEILEN && innen.firstChild) { innen.firstChild.remove(); S.zeilenN--; }
  }
  function renderLeer() {
    const leer = $('term-leer'), st = S.status;
    leer.hidden = !S.logFremd && (S.zeilenN > 0 || S.puffer.length > 0);
    const text = S.logFremd ? (S.logQuelle === 'datei' ? t('Die Ausgabe dieses Runners wird hier noch nicht angezeigt.') : t('Ohne Dienst gibt es für diesen Runner kein Log.'))
      : S.logQuelle === 'journal' ? (S.journalFehler === 'grenze' ? t('Das Journal kann gerade nicht angezeigt werden – zu viele sind gleichzeitig geöffnet.') : t('Noch keine Einträge im Journal von {unit}.', { unit: S.journalUnit }))
      : st && st.dienst.zustand === 'gestoppt' ? t('Der Runner-Dienst ist gestoppt – es kommt keine Ausgabe.')
      : st && st.github.zustand === 'offline' ? t('Kein Schritt läuft. {dienst} stellt dem Runner gerade keine Jobs zu.', { dienst: RUNNER.dienstName(st.anbieter) || 'GitHub' })
      : t('Kein Schritt läuft. Die Ausgabe erscheint hier, sobald ein Job startet.');
    if (leer.textContent !== text) leer.textContent = text;
  }
  function renderPause() {
    const k = $('k-pause');
    k.innerHTML = S.angehalten ? `${IC.dreieck(12)}${t('Weiter')}` : `${IC.pause()}${t('Anhalten')}`;
    k.setAttribute('aria-pressed', String(S.angehalten));
    $('term').classList.toggle('pausiert', S.angehalten);
    const neu = `${S.puffer.length} ${mehrzahl(S.puffer.length, t('neue Zeile'), t('neue Zeilen'))}`;
    $('pause-hinweis').hidden = !S.angehalten;
    $('pause-text').textContent = `${t('Angehalten')} · ${neu}`;
    // Hochgescrollt ist ein eigener Zustand mit eigener Pille (Design 0.3.0), „Anhalten“ hat Vorrang.
    $('scroll-hinweis').hidden = !(S.hoch && !S.angehalten);
    $('scroll-text').textContent = `${t('Mitlaufen angehalten')} · ${neu}`;
  }
  function leerePuffer() { const p = S.puffer; S.puffer = []; if (p.length) haengeAn(p); }
  function umschaltenPause() {
    S.angehalten = !S.angehalten;
    if (!S.angehalten && !S.hoch) { leerePuffer(); $('term').scrollTop = 0; }
    renderPause(); renderLeer();
  }
  function setzeUmbruch(an) {
    S.umbruch = an; $('term').classList.toggle('kurz', !an);
    $('k-umbrechen').setAttribute('aria-pressed', String(an)); $('k-abschneiden').setAttribute('aria-pressed', String(!an));
  }

  /* ------------------------------------------------------------ Info & Hilfe */
  /* Anleitungen „Was tun, wenn …“ für den gewählten Runner (Texte, Befehle mit seiner Unit: info.js). */
  function anleitungen() {
    const st = S.status || { dienst: {}, github: {} }, w = S.workflows || {}, u = S.update || {}, us = u.status || {};
    const r = gewaehlterRunner() || {}, zr = S.anlRunner && (S.runner || []).find((x) => x.id === S.anlRunner);
    return INFO.anleitungen({
      dienst: st.anbieter || r.dienst || 'github', id: st.id || r.id || '', unit: st.unit || r.unit || '', server: r.server || '', org: r.org || w.org || '',
      grund: st.dienst && st.dienst.grund, vm: st.vm, abfrage: w.abfrage,
      tokenAblauf: !!(w.tokenAblauf && (ms(w.tokenAblauf) - Date.now()) < 14 * 86400000),
      gestoppt: st.dienst.zustand === 'gestoppt', fehlt: st.dienst.zustand === 'fehlt', offline: st.github.zustand === 'offline',
      knapp: (S.platten || []).some(p => p.schwelleFrei && p.frei < p.schwelleFrei), getrennt: S.verbindung === 'getrennt',
      updFehler: us.zustand === 'fehler', updNeu: !!(u.neueste && vergleiche(u.neueste.version, u.installiert) > 0),
    }, t, zr && { dienst: zr.dienst, id: zr.id, server: zr.server || '', org: zr.org || '' });
  }

  /* „Jetzt prüfen“: fragt GitHub sofort nach einer neuen Version (über den root-Sammler, höchstens
     einmal je Minute). Zustand in S.pruefung: laeuft → fertig/frisch/keine-antwort, verschwindet nach einigen Sekunden. */
  function pruefKnopf(u, us, neu) {
    const p = S.pruefung, jetzt = Date.now();
    if (p && p.bis && jetzt > p.bis) S.pruefung = null;
    if (p && p.zustand === 'laeuft' && jetzt - p.start > 45000) S.pruefung = { zustand: 'keine-antwort', bis: jetzt + 30000 };
    const q = S.pruefung, zst = q ? q.zustand : 'ruhe', updLaeuft = us.zustand === 'laeuft';
    const fehlerGh = zst === 'fertig' && u.neueste && u.neueste.fehler;
    const qn = INFO.updateQuelle(u.quelle, t).name;  // GitHub oder Forgejo (#138)
    const ICO = {
      dreh: '<svg class="upd-dreh" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M8 1.5a6.5 6.5 0 106.5 6.5"/></svg>',
      ruhe: '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13.5 8a5.5 5.5 0 11-1.61-3.89"/><path d="M13.5 2.5v3h-3"/></svg>',
      ok: '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="8" r="6.5"/><path d="M5.2 8.2l1.9 1.9 3.7-4"/></svg>',
      neu: '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="8" r="6.5"/><path d="M8 4.8v6M5.4 8.6L8 11.2l2.6-2.6"/></svg>',
      x: '<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="6.5"/><path d="M5.8 5.8l4.4 4.4M10.2 5.8l-4.4 4.4"/></svg>',
    };
    let text = '';
    if (zst === 'laeuft') text = `<span class="pruef-text mut">${t('Frage {q} nach neuen Versionen …', { q: qn })}</span>`;
    else if (zst === 'frisch') text = `<span class="pruef-text mut">${t('Gerade erst geprüft – Stand siehe oben.')}</span>`;
    else if (zst === 'fertig' && !fehlerGh) text = neu ? `<span class="pruef-text laeuft">${ICO.neu}${t('Version {v} ist verfügbar.', { v: esc(u.neueste.version) })}</span>` : `<span class="pruef-text ok">${ICO.ok}${t('Auf dem neuesten Stand.')}</span>`;
    else if (updLaeuft) text = `<span class="pruef-text mut">${t('Gesperrt, solange das Update läuft.')}</span>`;
    const aus = zst === 'laeuft' || updLaeuft;
    let html = `<div class="pruef"><button type="button" class="knopf" data-aktion="update-pruefen"${aus ? ' disabled' : ''} title="${t('{q} sofort nach einer neuen Version fragen (sonst alle 6 Std.)', { q: qn })}">${zst === 'laeuft' ? ICO.dreh : ICO.ruhe}${t('Jetzt prüfen')}</button><span aria-live="polite" class="pruef-live">${text}</span></div>`;
    if (fehlerGh) html += `<div class="hinweis fehler pruef-fehler" role="alert">${ICO.x}<div>${t('{q} nicht erreichbar:', { q: qn })} <span>${t('{f}. Der nächste automatische Versuch folgt in 6 Std.', { f: esc(u.neueste.fehler) })}</span></div></div>`;
    if (zst === 'keine-antwort') html += `<div class="hinweis fehler pruef-fehler" role="alert">${ICO.x}<div class="hinweis-voll">${t('Keine Antwort vom Sammler.')} <span>${t('Auf der VM prüfen:')}</span>${codeBox('journalctl -u runner-monitor-sammler -n 30')}</div></div>`;
    return html;
  }

  /* Befehlsblock mit Knopf „Kopieren“. Über http im LAN gibt es navigator.clipboard nicht (nur in
     sicheren Kontexten), deshalb Rückfall auf execCommand('copy') mit unsichtbarem Textfeld. */
  function codeBox(code) {
    return `<div class="code-box"><pre class="code">${esc(code)}</pre><button type="button" class="kopier" data-aktion="kopieren" data-code="${esc(code)}">${t('Kopieren')}</button></div>`;
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

  function oeffneInfo(id) {
    S.info = id || 'alle';
    const ebene = $('info-ebene');
    if (ebene.querySelector('.info.raus')) ebene.replaceChildren(); // gerade beim Schließen: neu aufbauen
    ebene.hidden = false;
    renderInfo();
    irLade();  // Funde der Erkennung (Info › Runner)
    const aside = ebene.querySelector('.info');
    if (aside) aside.focus();
    const ziel = id && id !== 'alle' && document.getElementById(`anl-${id}`);
    if (ziel) ziel.scrollIntoView({ block: 'start' });
  }
  /* „Runner zuordnen ›“ im Leerzustand der Karte: Info öffnen, zum Abschnitt Runner springen, Formular auf. */
  function oeffneRunnerZuordnung(id) {
    oeffneInfo('alle');
    const f = id && irFund(id);
    if (f) { S.ir.form = id; S.ir.zugang = null; S.ir.werte[id] = INFO.formStart(f); S.ir.formFehler[id] = {}; renderInfo(`[data-feld="dienst"][data-runner="${CSS.escape(id)}"]`); }
    const z = document.getElementById('abschnitt-runner');
    if (z) z.scrollIntoView({ block: 'start' });
  }
  function schliesseInfo() {
    const ebene = $('info-ebene'), aside = ebene.querySelector('.info');
    S.info = null; S.anlRunner = null;
    if (aside && !reduziert.matches) {
      aside.classList.add('raus');
      setTimeout(() => { if (!S.info) { ebene.hidden = true; ebene.replaceChildren(); } }, 240);
    } else { ebene.hidden = true; ebene.replaceChildren(); }
    $('k-info').focus();
  }

  // Inline-Code aus Release-Notizen (`…`) nach dem Maskieren als <code> zeigen
  const mitCode = (text) => esc(text).replace(/`([^`]+)`/g, '<code class="inl">$1</code>');

  // Was sich gegenüber der installierten Version ändert (#78): je Version „Neu in X“ und
  // „Einmalig nach dem Update“; neueste offen, ältere eingeklappt.
  function aenderungenHtml(u) {
    const quelle = INFO.updateQuelle(u.quelle, t);
    const liste = (u.neueste.aenderungen && u.neueste.aenderungen.length) ? u.neueste.aenderungen
      : (u.neueste.notizen && u.neueste.notizen.length ? [{ version: u.neueste.version, url: u.neueste.url, neu: u.neueste.notizen, einmalig: '' }] : []);
    if (!liste.length) return '';
    const block = (r) => `${r.einmalig ? `<div class="upd-einmalig"><span class="upd-einmalig-titel">${t('Einmalig nach dem Update:')}</span> ${mitCode(r.einmalig)}</div>` : ''}`
      + (r.neu && r.neu.length ? `<ul>${r.neu.map(n => `<li>${mitCode(n)}</li>`).join('')}</ul>` : '')
      + `<a href="${esc(r.url || quelle.releases || `https://github.com/${REPO}/releases`)}" rel="noopener" target="_blank">${t('Release-Notiz {v} auf {q} ↗', { v: esc(r.version), q: quelle.name })}</a>`;
    const [erste, ...aeltere] = liste;
    const titel = liste.length > 1 ? t('Neu seit {v} · {n} Versionen', { v: esc(u.installiert), n: liste.length }) : t('Neu in {v}', { v: esc(erste.version) });
    return `<div class="upd-neu"><div class="upd-neu-titel">${titel}</div>`
      + (liste.length > 1 ? `<div class="upd-version">${esc(erste.version)}</div>` : '') + block(erste)
      + aeltere.map(r => `<details class="upd-aelter"><summary>${esc(r.version)}</summary>${block(r)}</details>`).join('')
      + '</div>';
  }

  /* Ohne runner[] (Altformat) ist der Runner ein GitHub-Runner. */
  const istGitHub = (st) => !st.anbieter || st.anbieter === 'github';
  /* „Forgejo Runner 9.1“ trägt den Dienst schon in der Version – dann nicht noch einmal davorsetzen. */
  const runnerVersion = (st) => {
    if (!st.version) return '–';
    const name = istGitHub(st) ? 'actions-runner' : (RUNNER.dienstName(st.anbieter) || '');
    return (String(st.version).toLowerCase().startsWith(name.toLowerCase()) ? esc(st.version) : `${esc(name)} ${esc(st.version)}`).trim();
  };
  /* Alle Runner für die Fehler-Mail: Name, Dienst, Version (mail.js nennt sie „Runner:“). */
  function runnerAngaben() {
    if (Array.isArray(S.runner) && S.runner.length) return S.runner.map((r) => ({ name: r.name, dienst: RUNNER.dienstName(r.dienst) || t('unbekannt'), version: r.version || '' }));
    const st = S.status || {};
    return st.runner ? [{ name: st.runner, dienst: 'GitHub', version: st.version || '' }] : [];
  }

  function infoTeile() {
    const st = S.status || {}, w = S.workflows || {}, u = S.update || {}, us = u.status || {};
    const jetzt = Date.now();
    const neu = u.neueste && u.neueste.version && vergleiche(u.neueste.version, u.installiert) > 0;
    // Technische Angaben für die Mail (web/mail.js); was der aktuelle Stand hergibt
    const dz = st.dienst && st.dienst.zustand;
    const mailAngaben = {
      version: u.installiert || st.monitorVersion || '', system: st.system || '', browser: navigator.userAgent,
      runner: runnerAngaben(),
      gewaehlt: Array.isArray(S.runner) && S.runner.length ? (gewaehlterRunner() ? { name: gewaehlterRunner().name, zustand: RUNNER.zustand(gewaehlterRunner(), Date.now()).wort === 'job' ? t('Job') : zustandsWort()[RUNNER.zustand(gewaehlterRunner(), Date.now()).wort] } : null) : st.runner && dz && dz !== 'fehlt' ? { name: st.runner, zustand: dz === 'gestoppt' ? t('Gestoppt') : st.github && st.github.zustand === 'offline' ? t('Offline') : st.job ? t('Job') : t('Bereit') } : null,
    };
    const kv = (liste) => `<dl class="kv">${liste.map(([k, v, cls]) => `<div class="kv-z"><dt>${k}</dt><dd class="${cls || ''}">${v}</dd></div>`).join('')}</dl>`;

    // Updates
    const quelle = INFO.updateQuelle(u.quelle, t);
    let upd = kv([
      [t('Installiert'), esc(u.installiert || '–')],
      [t('Neueste'), u.neueste && u.neueste.version ? (neu ? t('{v} · erschienen am {d}', { v: esc(u.neueste.version), d: u.neueste.veroeffentlicht ? datum(u.neueste.veroeffentlicht) : '–' }) : t('{v} – auf dem neuesten Stand', { v: esc(u.neueste.version) })) : (u.neueste && u.neueste.fehler ? t('nicht abrufbar') : t('noch nicht geprüft')), neu ? 'laeuft' : 'ok'],
      [t('Geprüft'), u.neueste && u.neueste.geprueft ? t('{tag} {z} bei {q} · alle 6 Std.', { tag: tm(u.neueste.geprueft) === tm(jetzt) ? t('heute') : tm(u.neueste.geprueft), z: hm(u.neueste.geprueft), q: quelle.name }) : '–'],
      [t('Quelle'), esc(quelle.text), quelle.http ? 'warn' : ''],
      ['Runner', `${runnerVersion(st)}${istGitHub(st) ? ' · ' + t('aktualisiert sich selbst') : ''}`],
    ]);
    upd += pruefKnopf(u, us, neu);
    if (neu) upd += aenderungenHtml(u);
    if (us.zustand === 'laeuft' || us.zustand === 'fehler') {
      const nr = us.schritt || 1;
      const zeilen = UPDATE_SCHRITTE.map((s, i) => {
        if (us.zustand === 'fehler') { const f = i + 1 === nr; const fertig = i + 1 < nr; return `<li class="${fertig ? '' : f ? '' : 'offen'}">${fertig ? IC.ok(16) : f ? `<span class="fehler">${IC.x(16)}</span>` : IC.offen()}<span>${s[0]}</span><span class="upd-zusatz">${f ? esc(us.meldung || '') : ''}</span></li>`; }
        return `<li class="${i + 1 === nr ? 'aktiv' : i + 1 > nr ? 'offen' : ''}">${i + 1 < nr ? `<span class="ok">${IC.ok(16)}</span>` : i + 1 === nr ? IC.dreh() : IC.offen()}<span>${s[0]}</span><span class="upd-zusatz">${i + 1 < nr ? s[1] : i + 1 === nr ? t('läuft …') : ''}</span></li>`;
      }).join('') + (us.zustand === 'fehler' ? `<li><span class="ok">${IC.ok(16)}</span><span>${t('Version {v} wiederhergestellt', { v: esc(u.installiert) })}</span><span class="upd-zusatz">${t('läuft wieder')}</span></li>` : '');
      upd += `<ol class="upd-schritte" aria-live="polite">${zeilen}</ol>`;
    }
    if (us.zustand === 'fehler') upd += `<div class="hinweis fehler">${IC.x(15)}<div>${t('Update fehlgeschlagen')} <span>– ${t('{m}. Version {v} wurde automatisch wiederhergestellt. Details:', { m: esc(us.meldung || t('die neue Version hat nach dem Neustart nicht geantwortet')), v: esc(u.installiert) })} <code class="inl">journalctl -u runner-monitor-update -n 50</code></span></div></div>`;
    if (us.zustand === 'erfolg' && jetzt - ms(us.zeit) < 3600000) upd += `<div class="hinweis ok">${IC.ok(15)}<div>${t('Aktualisiert auf {v}', { v: esc(u.installiert) })} <span>– ${t('um {z}. Dienst läuft, alle Daten kommen an.', { z: hm(us.zeit) })}</span></div></div>`;
    const bereit = !u.neueste || u.neueste.bereit !== false;  // Paket hängt schon am Release (#63)
    if (neu && !bereit && us.zustand !== 'laeuft') upd += `<div class="upd-aktion"><p class="info-notiz">${t('Version {v} wird gerade bereitgestellt – das Paket ist in ein bis zwei Minuten da. Der Monitor prüft von selbst erneut.', { v: esc(u.neueste.version) })}</p></div>`;
    else if (neu && us.zustand !== 'laeuft') {
      const fehl = us.zustand === 'fehler';
      const hinweisZeit = `<p class="info-notiz">${t('Dauert etwa eine Minute. Der Monitor ist dabei kurz nicht erreichbar, der Runner und laufende Jobs arbeiten weiter.')}</p>`;
      const melden = fehl ? `<a class="knopf" href="${esc(MAIL.updateFehler({ ...mailAngaben, alt: u.installiert, neu: us.version || u.neueste.version, meldung: us.meldung || t('die neue Version hat nach dem Neustart nicht geantwortet') }, t))}">${t('Fehler melden')}</a>` : '';
      upd += `<div class="upd-aktion${fehl ? ' zeile' : ''}"><button type="button" class="knopf primaer gross" data-aktion="update-starten">${IC.herunter()}${fehl ? t('Erneut versuchen') : t('Jetzt auf {v} aktualisieren', { v: esc(u.neueste.version) })}</button>${fehl ? melden + '</div>' + hinweisZeit : hinweisZeit + '</div>'}`;
    } else if (us.zustand === 'fehler') {
      upd += `<div class="upd-aktion zeile"><a class="knopf" href="${esc(MAIL.updateFehler({ ...mailAngaben, alt: u.installiert, neu: us.version || '', meldung: us.meldung || t('die neue Version hat nach dem Neustart nicht geantwortet') }, t))}">${t('Fehler melden')}</a></div>`;
    }
    upd += `<label class="upd-auto"><input type="checkbox" data-aktion="update-auto" ${u.auto ? 'checked' : ''}>${t('Automatisch aktualisieren – nachts ab 3 Uhr, sobald kein Job läuft')}</label>`;
    const as = u.autoStand || {};
    if (u.auto && neu && us.zustand !== 'laeuft' && as.version === u.neueste.version) {
      if (as.zustand === 'vorgemerkt') upd += `<p class="info-notiz">${t('Update auf {v} vorgemerkt – startet, sobald der Runner keinen Job mehr hat (bis 7 Uhr).', { v: esc(as.version) })}</p>`;
      else if (as.zustand === 'verschoben') upd += `<p class="info-notiz">${t('Letzte Nacht lief bis 7 Uhr durchgehend ein Job – nächster Versuch in der kommenden Nacht ab 3 Uhr.')}</p>`;
    }

    const th = RM.thema(), sp = I18N.wahl();
    const modi = [['system', t('Automatisch')], ['hell', t('Hell')], ['dunkel', t('Dunkel')]].map(([v, n]) => `<button type="button" class="seg-knopf" data-aktion="thema" data-thema="${v}" aria-pressed="${th === v}">${n}</button>`).join('');
    const sprachen = [['auto', t('Automatisch'), ''], ['de', 'Deutsch', ' lang="de"'], ['en', 'English', ' lang="en"']].map(([v, n, l]) => `<button type="button" class="seg-knopf" data-aktion="sprache" data-sprache="${v}" aria-pressed="${sp === v}"${l}>${n}</button>`).join('');

    const anl = anleitungen().map(a => {
      const offen = S.info === a.id;
      return `<div class="anl" id="anl-${a.id}"><button type="button" class="anl-kopf" data-aktion="anleitung" data-anleitung="${a.id}" aria-expanded="${offen}">${IC.chev(offen)}<span class="anl-titel">${a.titel}</span>${a.aktiv ? `<span class="pill ${a.cls || 'warn'}">${t('jetzt aktiv')}</span>` : ''}</button>${offen ? `<p class="anl-wann">${a.wann}</p><ol class="anl-schritte">${a.schritte.map(([text, code]) => `<li><span>${esc(text)}</span>${code ? codeBox(code) : ''}</li>`).join('')}</ol>` : ''}</div>`;
    }).join('');

    // Verbindungen: je angebundenem Dienst eine Gruppe; Felder nur, wenn der Zustand sie hergibt, sonst „–“
    const verbs = INFO.verbindungen(S.runner, { t, RM, jetzt });
    const verb = verbs.length ? verbs.map((v) => `<div class="vb-titel"><span class="label">${esc(v.dienst)}</span><span>${esc(v.titel)}</span><span class="mut">· ${esc(v.runner)}</span></div><dl class="kv">${v.kv.map(([k, x, cls, tick]) => `<div class="kv-z"><dt>${k}</dt><dd class="${cls || ''}">${tick ? `<span data-tick="${tick}" data-runner="${esc(v.id)}"></span>` : esc(x)}</dd></div>`).join('')}</dl>`).join('')
      : `<p class="info-notiz keine-oben">${t('Kein Runner ist an einen Dienst angebunden. Dienst, Auslastung und Log laufen trotzdem. Anbinden: unter „Runner“ den Befehl bei „Zugangsdaten ändern“ auf der VM ausführen.')}</p>`;
    const ueber = kv([
      ['Version', esc(u.installiert || st.monitorVersion || '–')],
      [t('Adresse'), esc(location.host)],
      [t('Dienst'), t('runner-monitor (systemd, eigener Benutzer)')],
      [t('Aktualisierung'), t('Systemwerte jede Sekunde, Dienste (GitHub, Forgejo) alle 30 s')],
    ]);

    // Teile einzeln austauschen statt das ganze Blatt neu zu bauen: Sonst startet die Einblend-
    // Animation bei jeder Aktualisierung neu, Auswahl und Fokus gehen verloren.
    return {
      eyebrow: `${esc(st.vm || '')}${st.runner ? ' · ' + esc(st.runner) : ''}`,
      upd,
      modi: `<div class="info-zeile"><span class="mut">${t('Modus')}</span><div class="segment" role="group" aria-label="${t('Hell oder dunkel')}">${modi}</div></div><p class="info-notiz">${t('„Automatisch“ folgt der Einstellung des Systems. Die Wahl gilt nur für diesen Browser.')}</p><div class="info-zeile sprach-zeile"><span class="mut">${t('Sprache')}</span><div class="segment" role="group" aria-label="${t('Sprache')}">${sprachen}</div></div><p class="info-notiz">${t('„Automatisch“ folgt der Sprache des Systems. Andere Sprachen als Deutsch zeigen Englisch. Die Wahl gilt nur für diesen Browser.')}</p>`,
      anl,
      verb,
      runner: runnerHtml(),
      ueber: `<p class="info-text">${t('Live-Dashboard für selbst gehostete CI-Runner auf einer VM – GitHub Actions, Forgejo, Gitea, GitLab, andere mit Grundüberwachung: Runner-Status, Auslastung mit Netzwerk, Prozesse, Platten, Jobs je Repository und Live-Log. Fehler und Hinweise erscheinen als Meldung in der Mitte der Kopfzeile, „Was tun?“ führt zur passenden Anleitung.')}</p>${ueber}<p class="info-text umbruch">${t('Ersteller:')} Bamberger IT Services · <a class="verweis" href="https://bamberger-it-services.de" rel="noopener" target="_blank">bamberger-it-services.de</a><br>${t('Quellcode und Doku:')} <a class="verweis" href="https://github.com/${REPO}" rel="noopener" target="_blank">github.com/${REPO}</a></p>`,
      issue: `<p class="info-text">${t('Fehler und Wünsche gehen per E-Mail an')} <a class="verweis" href="mailto:${MAIL.ADRESSE}">${MAIL.ADRESSE}</a>${t('. Der Knopf öffnet das E-Mail-Programm mit Betreff und einer Vorlage, in der die technischen Angaben schon stehen:')}</p>${kv([
        ['Version', `Runner-Monitor ${esc(u.installiert || st.monitorVersion || '–')}`],
        ['System', esc(st.system || '–')],
        // Beginnt die Version schon mit dem Dienst („Forgejo Runner 9.1“), wird er nicht doppelt genannt (wie in mail.js)
        ['Runner', runnerAngaben().map((r) => { const dv = (r.dienst && r.version && String(r.version).toLowerCase().startsWith(String(r.dienst).toLowerCase()) ? [r.version] : [r.dienst, r.version]).filter(Boolean).join(' '); return `${esc(r.name)} (${esc(dv)})`; }).join(', ') || '–'],
        ['Browser', t('wird automatisch ergänzt')],
      ])}<div class="knopf-reihe"><a class="knopf" href="${esc(MAIL.fehler(mailAngaben, t))}">${IC.brief()}${t('Fehler melden')}</a><a class="knopf" href="${esc(MAIL.idee(mailAngaben, t))}">${t('Idee vorschlagen')}</a></div><p class="info-notiz">${t('Vor dem Absenden prüfen: Keine Tokens oder Passwörter mitschicken. Log-Ausschnitte nur gekürzt einfügen.')}</p>`,
    };
  }

  const INFO_GERUEST = `
      <div class="info-scrim" data-aktion="info-zu"></div>
      <aside class="info" role="dialog" aria-modal="true" aria-labelledby="info-titel" tabindex="-1">
        <div class="info-kopf">
          <div class="info-kopf-text"><div class="vm-eyebrow" data-teil="eyebrow"></div><h2 class="info-titel" id="info-titel">${esc(t('Info & Hilfe'))}</h2></div>
          <div class="info-kopf-knoepfe"><button type="button" class="knopf" data-aktion="abmelden">${t('Abmelden')}</button><button type="button" class="knopf" data-aktion="info-zu">${t('Schließen')}</button></div>
        </div>
        <div class="info-body">
          <div class="info-spalten">
            <div class="info-spalte">
              <section class="info-abschnitt" id="abschnitt-runner" aria-labelledby="runner-h"><div data-teil="runner"></div></section>
              <section class="info-abschnitt" id="abschnitt-verbindungen"><h3 class="info-h">${t('Verbindungen')}</h3><div data-teil="verb"></div></section>
              <section class="info-abschnitt"><h3 class="info-h">${t('Was tun, wenn …')}</h3><div data-teil="anl"></div></section>
            </div>
            <div class="info-spalte">
              <section class="info-abschnitt"><h3 class="info-h">${t('Updates')}</h3><div data-teil="upd"></div></section>
              <section class="info-abschnitt"><h3 class="info-h">${t('Darstellung')}</h3><div data-teil="modi"></div></section>
              <section class="info-abschnitt"><h3 class="info-h">${t('Über diesen Monitor')}</h3><div data-teil="ueber"></div></section>
              <section class="info-abschnitt"><h3 class="info-h">${t('Fehler gefunden oder Idee?')}</h3><div data-teil="issue"></div></section>
            </div>
          </div>
        </div>
      </aside>`;

  /* Selektor, mit dem sich ein Bedienelement des Blatts nach dem Neuzeichnen wiederfinden lässt. */
  function fokusSelektor(el) {
    const d = el.dataset || {};
    if (!d.aktion) return null;
    let sel = `[data-aktion="${d.aktion}"]`;
    for (const k of ['runner', 'anleitung', 'thema', 'sprache', 'feld']) if (d[k]) sel += `[data-${k}="${CSS.escape(d[k])}"]`;
    return sel;
  }

  /* Blatt zeichnen. fokus: Selektor des Elements, das danach den Fokus bekommt (sonst bleibt der Fokus
     auf dem Bedienelement, auch wenn sein Teil neu gezeichnet wurde). Beim Tippen im Formular bleibt der
     Teil „Runner“ unberührt – die Eingabe wird nicht unterbrochen. */
  function renderInfo(fokus) {
    if (!S.info) return;
    const ebene = $('info-ebene');
    if (!ebene.querySelector('.info')) ebene.innerHTML = INFO_GERUEST;
    const teile = infoTeile();
    const aktiv = document.activeElement, imBlatt = aktiv && ebene.contains(aktiv);
    const tippt = imBlatt && aktiv.matches('input, select, textarea');
    const merke = imBlatt ? fokusSelektor(aktiv) : null;
    for (const [name, html] of Object.entries(teile)) {
      const el = ebene.querySelector(`[data-teil="${name}"]`);
      if (!el || el.dataset.html === html) continue;
      if (tippt && !fokus && el.contains(aktiv)) continue;
      el.innerHTML = html; el.dataset.html = html;
    }
    const ziel = fokus || (document.activeElement === document.body && merke ? merke : null);
    if (ziel) { const z = ebene.querySelector(ziel); if (z) z.focus(); }
    tickInfo();
  }

  /* Werte, die sich jede Sekunde ändern, nur als Text setzen. */
  function tickInfo() {
    for (const el of $('info-ebene').querySelectorAll('[data-tick="naechste"]')) {
      const r = (S.runner || []).find((x) => x.id === el.dataset.runner);
      el.textContent = INFO.naechste(r, { t, RM, jetzt: Date.now() });
    }
  }

  /* ------------------------------------------------------------ Info › Runner (#97) */
  /* Die Liste kommt von GET /api/einrichtung/runner (angemeldet, wie in der Einrichtung): alle Funde der
     Erkennung samt Grad, auch ignorierte. Ändern geht über die vorhandenen Endpunkte (Auftrag an den Sammler,
     der runner.json schreibt, E-22); Server, Organisation und Token nie – dafür steht der Befehl für die VM da. */
  const warte = (zeitMs) => new Promise((ok) => setTimeout(ok, zeitMs));
  const irFunde = () => S.ir.funde || INFO.fundeAusRunner(S.runner);
  const irFund = (id) => irFunde().find((f) => f.id === id) || null;

  function runnerHtml() {
    const ir = S.ir, jetzt = Date.now(), fm = { t, RM, jetzt };
    const funde = irFunde(), zeilen = INFO.runnerZeilen({ funde, runner: S.runner, neu: ir.neu, zeit: ir.funde ? ir.zeit : null }, fm);
    const aktive = funde.filter((f) => f.stand !== 'ignoriert').length;
    const status = ir.fehler && ir.erk !== 'laeuft' ? t('Die Liste der Erkennung ist gerade nicht abrufbar – angezeigt wird der Stand des Monitors.')
      : INFO.erkennenText({ erk: ir.erk, zeit: ir.zeit, erkZeit: ir.erkZeit, anzahl: aktive, ignoriert: funde.length - aktive }, fm);
    const laeuft = ir.erk === 'laeuft';
    const dreh = '<svg class="upd-dreh" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M8 1.5a6.5 6.5 0 106.5 6.5"/></svg>';
    const ruhe = '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13.5 8a5.5 5.5 0 11-1.61-3.89"/><path d="M13.5 2.5v3h-3"/></svg>';
    const neuZ = zeilen.filter((z) => z.istNeu);
    const neuBar = neuZ.length ? `<div class="ir-neu" role="status"><span>${neuZ.length === 1 ? t('1 neuer Runner gefunden:') : t('{n} neue Runner gefunden:', { n: neuZ.length })} <b>${neuZ.map((z) => esc(z.name)).join(', ')}</b>${neuZ.length === 1 ? ` <span class="label">${esc(neuZ[0].dienst)}</span>` : ''}</span><span class="ir-neu-knoepfe"><button type="button" class="knopf primaer" data-aktion="ir-neu-uebernehmen">${t('Übernehmen')}</button><button type="button" class="knopf" data-aktion="ir-neu-ignorieren">${t('Ignorieren')}</button></span></div>` : '';
    const liste = zeilen.map((z, i) => {
      const id = esc(z.id), formOffen = ir.form === z.id, zugOffen = ir.zugang === z.id;
      const kvHtml = `<dl class="kv">${z.kv.map(([k, v, cls]) => `<div class="kv-z"><dt>${k}</dt><dd class="${cls || ''}">${esc(v)}</dd></div>`).join('')}</dl>`;
      const aktionen = `<div class="ir-aktionen"><button type="button" class="link-knopf" data-aktion="ir-form" data-runner="${id}" aria-expanded="${formOffen}"${formOffen ? ` aria-controls="ir-form-${id}"` : ''}>${t('Zuordnung ändern')}</button><button type="button" class="link-knopf" data-aktion="ir-ignorieren" data-runner="${id}">${z.ignoriert ? t('Wieder anzeigen') : t('Ignorieren')}</button>${z.hatZugang ? `<button type="button" class="link-knopf" data-aktion="ir-zugang" data-runner="${id}" aria-expanded="${zugOffen}"${zugOffen ? ` aria-controls="ir-zugang-${id}"` : ''}>${t('Zugangsdaten ändern')}</button>` : ''}</div>`;
      return `<div class="ir${i === 0 ? ' ir-erst' : ''}" data-runner="${id}"><div class="ir-kopf"><span class="punkt ${z.punkt}" aria-hidden="true"></span><span class="ir-name">${esc(z.name)}</span><span class="label">${esc(z.dienst)}</span><span class="pill ${z.pilleCls}">${z.pille}</span></div>${kvHtml}${aktionen}${formOffen ? irFormular(z.fund) : ''}${zugOffen ? irZugang(z) : ''}</div>`;
    }).join('');
    const leer = zeilen.length ? '' : `<p class="info-notiz">${t('Es wurde noch kein Runner erkannt. Unter „Was tun, wenn …“ › „Kein Runner eingerichtet“ steht, wie ein Runner eingerichtet wird.')}</p>`;
    return `<div class="info-zeile ir-kopfzeile"><h3 class="info-h" id="runner-h">${t('Runner')}</h3><button type="button" class="knopf" data-aktion="ir-erkennen"${laeuft ? ' disabled' : ''}>${laeuft ? dreh : ruhe}${t('Neu erkennen')}</button></div>`
      + `<p class="info-notiz ir-status" aria-live="polite">${esc(status)}</p>`
      + (ir.meldung ? `<div class="hinweis fehler ir-meldung" role="alert">${IC.x(15)}<div>${esc(ir.meldung)}</div></div>` : '')
      + neuBar + liste + leer;
  }

  function irFormular(f) {
    const ir = S.ir, w = ir.werte[f.id] || INFO.formStart(f), fe = ir.formFehler[f.id] || {}, id = esc(f.id);
    const opt = EINR.DIENST_WAHL.map((d) => `<option value="${d}"${(w.dienst || 'unbekannt') === d ? ' selected' : ''}>${esc(d === 'unbekannt' ? t('anderer') : EINR.dienstName(d))}</option>`).join('');
    const hinweis = (feld, text) => (fe[feld] ? `<span class="ir-hinweis" id="ir-${id}-${feld}-h">${text}</span>` : '');
    const attr = (feld) => (fe[feld] ? ` aria-invalid="true" aria-describedby="ir-${id}-${feld}-h"` : '');
    return `<div class="ir-box" role="group" aria-label="${t('Zuordnung ändern')}" id="ir-form-${id}"><div class="ir-form">`
      + `<label class="ir-feld">${t('Dienst')}<select data-feld="dienst" data-runner="${id}">${opt}</select></label>`
      + `<label class="ir-feld">${t('Anzeigename')}<input data-feld="name" data-runner="${id}" value="${esc(w.name)}" maxlength="64" autocapitalize="none" spellcheck="false"${attr('name')}>${hinweis('name', t('Nur Buchstaben, Ziffern und . _ @ + - (höchstens 64 Zeichen).'))}</label>`
      + `<label class="ir-feld">${t('systemd-Unit')}<input class="mono" data-feld="unit" data-runner="${id}" value="${esc(w.unit)}" placeholder="buildagent.service" maxlength="200" autocapitalize="none" spellcheck="false"${attr('unit')}>${hinweis('unit', t('Erwartet wird ein Name wie buildagent.service.'))}</label>`
      + `<label class="ir-feld">${t('Log-Pfad')}<input class="mono" data-feld="log" data-runner="${id}" value="${esc(w.log)}" placeholder="${esc(t('leer = Journal der Unit'))}" maxlength="400" autocapitalize="none" spellcheck="false"${attr('log')}>${hinweis('log', t('Nur eine .log-Datei unter /var/log, /opt oder /srv.'))}</label>`
      + `</div><div class="ir-knoepfe"><button type="button" class="knopf primaer" data-aktion="ir-form-speichern" data-runner="${id}"${ir.sendet ? ' disabled' : ''}>${t('Speichern')}</button><button type="button" class="knopf" data-aktion="ir-form-abbrechen" data-runner="${id}">${t('Abbrechen')}</button></div></div>`;
  }
  function irZugang(z) {
    return `<div class="ir-box" id="ir-zugang-${esc(z.id)}"><span class="ir-text">${t('Zugangsdaten werden aus Sicherheitsgründen nur auf der VM geändert. Der Befehl fragt Server, Organisation und Token ab und prüft die Verbindung:')}</span>${codeBox(z.befehl)}<button type="button" class="link-knopf" data-aktion="anleitung-zeigen" data-anleitung="token" data-runner="${esc(z.id)}">${t('Anleitung: Zugangsdaten für {dienst} ›', { dienst: z.dienst })}</button></div>`;
  }

  /* Funde laden: im Browser vom Server, in der Demo aus demo.js. false, wenn es nicht ging. */
  async function irLade() {
    let d = null;
    try {
      if (DEMO) d = window.RM_DEMO ? window.RM_DEMO.funde() : null;
      else { const r = await fetch('/api/einrichtung/runner', { credentials: 'same-origin' }); d = r.ok ? await r.json() : null; }
    } catch (f) { d = null; }
    S.ir.geladen = Date.now();
    if (!d || !Array.isArray(d.runner)) { S.ir.fehler = true; renderInfo(); return null; }
    S.ir.funde = d.runner; S.ir.zeit = d.zeit || null; S.ir.fehler = false;
    renderInfo();
    return d;
  }

  async function irErkennen() {
    const ir = S.ir;
    if (ir.erk === 'laeuft') return;
    const vorher = irFunde().map((f) => ({ ...f }));
    ir.erk = 'laeuft'; ir.meldung = ''; renderInfo();
    let fertig = false;
    if (DEMO) { await window.RM_DEMO.erkennen(); fertig = !!(await irLade()); } else {
      const r = await RM.sende('/api/einrichtung/runner/erkennen', {});
      if (!r.ok) { ir.erk = 'ruhe'; ir.meldung = r.daten.fehler ? RM.serverText(r.daten) : t('Nicht gespeichert.'); renderInfo(); return; }
      const seit = r.daten.seit || Date.now() / 1000;
      for (let i = 0; i < 45 && !fertig; i++) {  // Takt des Sammlers 2 s, Erkennung höchstens 60 s
        await warte(2000);
        const d = await irLade();
        fertig = !!(d && d.zeit && d.zeit >= seit - 1);
      }
    }
    if (!fertig) { ir.erk = 'zeit'; renderInfo(); return; }
    ir.erkZeit = ir.zeit || Date.now() / 1000;
    const neu = INFO.neueFunde(vorher, irFunde());
    for (const id of neu) if (!ir.neu.includes(id)) ir.neu.push(id);
    ir.erk = !neu.length && EINR.gleicheFunde(vorher, irFunde()) ? 'keine' : 'ruhe';
    renderInfo('[data-aktion="ir-erkennen"]');
  }

  /* Auftrag zur Zuordnung. true, wenn angenommen; sonst steht der Grund in S.ir.meldung. */
  async function irSende(eintraege) {
    const ir = S.ir; ir.meldung = ''; ir.sendet = true;
    let ok = true;
    if (DEMO) window.RM_DEMO.zuordnung(eintraege);
    else {
      const r = await RM.sende('/api/einrichtung/runner/zuordnung', { runner: eintraege });
      if (!r.ok) { ok = false; ir.meldung = r.daten.fehler ? RM.serverText(r.daten) : t('Nicht gespeichert.'); }
    }
    ir.sendet = false;
    await irLade();
    return ok;
  }

  function irAktion(a, b) {
    const ir = S.ir, id = b.dataset.runner, f = id ? irFund(id) : null;
    const knopf = id ? `[data-aktion="${a}"][data-runner="${CSS.escape(id)}"]` : `[data-aktion="${a}"]`;
    if (a === 'ir-erkennen') irErkennen();
    else if (a === 'ir-form' && f) {
      if (ir.form === id) { ir.form = null; renderInfo(knopf); } else { ir.form = id; ir.zugang = null; ir.werte[id] = INFO.formStart(f); ir.formFehler[id] = {}; ir.meldung = ''; renderInfo(`[data-feld="dienst"][data-runner="${CSS.escape(id)}"]`); }
    } else if (a === 'ir-form-abbrechen' && f) { ir.form = null; renderInfo(`[data-aktion="ir-form"][data-runner="${CSS.escape(id)}"]`); }
    else if (a === 'ir-form-speichern' && f) irSpeichern(f);
    else if (a === 'ir-zugang' && f) { ir.zugang = ir.zugang === id ? null : id; if (ir.zugang) ir.form = null; renderInfo(knopf); }
    else if (a === 'ir-ignorieren' && f) irSende([{ id, stand: f.stand === 'ignoriert' ? null : 'ignoriert' }]).then(() => renderInfo(knopf));
    else if (a === 'ir-neu-uebernehmen') {
      // Übernehmen = zur Kenntnis genommen: der Fund steht schon in der Liste, es ändert sich nichts in runner.json.
      const ids = ir.neu.slice(); ir.neu = [];
      const letzter = ids.map(irFund).filter(Boolean).pop();
      if (letzter && INFO.hatZugang(letzter)) { ir.zugang = letzter.id; ir.form = null; }
      renderInfo(letzter && INFO.hatZugang(letzter) ? `[data-aktion="ir-zugang"][data-runner="${CSS.escape(letzter.id)}"]` : '[data-aktion="ir-erkennen"]');
    } else if (a === 'ir-neu-ignorieren') {
      const ids = ir.neu.slice(); ir.neu = [];
      irSende(ids.map((x) => ({ id: x, stand: 'ignoriert' }))).then(() => renderInfo('[data-aktion="ir-erkennen"]'));
    }
  }

  async function irSpeichern(f) {
    const ir = S.ir, w = ir.werte[f.id] || INFO.formStart(f);
    const fehler = EINR.pruefeFormular(w, false);
    ir.formFehler[f.id] = fehler;
    if (Object.keys(fehler).length) { renderInfo(`[data-feld="${Object.keys(fehler)[0]}"][data-runner="${CSS.escape(f.id)}"]`); return; }
    const e = INFO.formEintrag(f, w, EINR.DIENST_WAHL);
    const ok = INFO.geaendert(e) ? await irSende([e]) : true;
    if (ok) ir.form = null;
    renderInfo(ok ? `[data-aktion="ir-form"][data-runner="${CSS.escape(f.id)}"]` : '[data-aktion="ir-form-speichern"]');
  }

  /* Eingaben im Formular merken (ohne neu zu zeichnen). */
  const irEingabe = (e) => {
    const el = e.target.closest ? e.target.closest('[data-feld][data-runner]') : null;
    if (!el) return;
    const id = el.dataset.runner, w = S.ir.werte[id];
    if (w) { w[el.dataset.feld] = el.value; if (S.ir.formFehler[id]) delete S.ir.formFehler[id][el.dataset.feld]; }
  };
  document.addEventListener('input', irEingabe);
  document.addEventListener('change', irEingabe);

  /* Tab bleibt im Blatt (Dialog): vom letzten Element zurück zum ersten und umgekehrt. */
  function fokusFalle(e) {
    const aside = $('info-ebene').querySelector('.info'); if (!aside) return;
    const liste = [...aside.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')].filter((el) => el.offsetParent !== null);
    if (!liste.length) return;
    const erst = liste[0], letzt = liste[liste.length - 1], a = document.activeElement;
    if (e.shiftKey && (a === erst || a === aside || !aside.contains(a))) { e.preventDefault(); letzt.focus(); }
    else if (!e.shiftKey && (a === letzt || !aside.contains(a))) { e.preventDefault(); erst.focus(); }
  }

  /* ------------------------------------------------------------ Bedienung */
  document.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-aktion]'); if (!b) return;
    const a = b.dataset.aktion;
    if (a === 'runner-waehlen') { waehleRunner(b.dataset.runner); const z = $('rw-tabs').querySelector(b.closest('#rw-pop') ? '.rw-t.an' : '[data-runner="' + CSS.escape(b.dataset.runner) + '"]'); if (z && b.closest('#rw-pop, #rw-tabs')) z.focus(); }
    else if (a === 'runner-mehr') { if (S.mehrOffen) schliesseMehr(false); else oeffneMehr(e.detail === 0); }  // detail 0: Tastatur (Enter, Leertaste) → Fokus in die Liste
    else if (a === 'info') oeffneInfo(b.dataset.anleitung);
    else if (a.startsWith('ir-')) irAktion(a, b);
    else if (a === 'runner-zuordnen') oeffneRunnerZuordnung(b.dataset.runner);
    else if (a === 'anleitung-zeigen') { S.anlRunner = b.dataset.runner || null; S.info = b.dataset.anleitung; renderInfo(`#anl-${b.dataset.anleitung} .anl-kopf`); const z = document.getElementById(`anl-${b.dataset.anleitung}`); if (z) z.scrollIntoView({ block: 'start', behavior: reduziert.matches ? 'auto' : 'smooth' }); }
    else if (a === 'info-zu') schliesseInfo();
    else if (a === 'anleitung') { S.info = S.info === b.dataset.anleitung ? 'alle' : b.dataset.anleitung; renderInfo(); }
    else if (a === 'thema') { RM.setzeThema(b.dataset.thema); renderModus(); renderInfo(); }
    else if (a === 'sprache') { if (b.dataset.sprache !== I18N.wahl()) { if (I18N.setzeSprache(b.dataset.sprache)) location.reload(); /* Speicher gesperrt: Wahl nicht möglich, keine Änderung */ } }
    else if (a === 'zeitraum') { S.zeitraum = VERLAUF.zeitraum(b.dataset.zeitraum); zeitraumSpeichern(S.zeitraum); renderZeitraum(); renderSystem(); }
    else if (a === 'wf-offen') { S.wfOffen = !S.wfOffen; $('workflows').dataset.letzte = ''; $('workflows').dataset.html = ''; renderWorkflows(); }
    else if (a === 'abmelden') { if (!DEMO) await RM.sende('/api/abmelden'); location.href = '/anmelden'; }
    else if (a === 'kopieren') kopiere(b);
    else if (a === 'update-pruefen') {
      const g = S.update && S.update.neueste && S.update.neueste.geprueft;
      if (g && Date.now() - ms(g) < 60000) { S.pruefung = { zustand: 'frisch', bis: Date.now() + 5000 }; renderInfo(); return; }
      S.pruefung = { zustand: 'laeuft', start: Date.now(), vorher: g || null }; renderInfo();
      if (DEMO) { window.RM_DEMO.pruefen(); return; }
      const r = await RM.sende('/api/update/pruefen');
      if (!r.ok) { S.pruefung = { zustand: 'keine-antwort', bis: Date.now() + 30000 }; renderInfo(); }
    }
    else if (a === 'update-starten') {
      b.disabled = true;
      if (DEMO) { window.RM_DEMO.updateStarten(); return; }
      const r = await RM.sende('/api/update/starten');
      if (!r.ok) { b.disabled = false; b.insertAdjacentHTML('afterend', `<p class="info-notiz fehler">${esc(r.daten.fehler ? RM.serverText(r.daten) : t('Update konnte nicht gestartet werden.'))}</p>`); }
    }
  });
  document.addEventListener('change', async (e) => {
    const el = e.target.closest('[data-aktion="update-auto"]'); if (!el) return;
    if (DEMO) { S.update = { ...S.update, auto: el.checked }; return; }
    await RM.sende('/api/update/auto', { an: el.checked });
  });
  document.addEventListener('keydown', (e) => {
    if (!S.info) return;
    if (e.key === 'Tab') { fokusFalle(e); return; }
    if (e.key !== 'Escape') return;
    // Ein offenes Formular oder eine Box im Blatt schließt zuerst, erst dann das Blatt
    const box = e.target.closest ? e.target.closest('.ir-box') : null;
    if (box && S.ir.form) { e.preventDefault(); const id = S.ir.form; S.ir.form = null; renderInfo(`[data-aktion="ir-form"][data-runner="${CSS.escape(id)}"]`); return; }
    if (box && S.ir.zugang) { e.preventDefault(); const id = S.ir.zugang; S.ir.zugang = null; renderInfo(`[data-aktion="ir-zugang"][data-runner="${CSS.escape(id)}"]`); return; }
    schliesseInfo();
  });
  $('k-modus').addEventListener('click', () => {
    const folgt = { system: 'hell', hell: 'dunkel', dunkel: 'system' }[RM.thema()];
    RM.setzeThema(folgt); renderModus(); renderInfo();
  });
  $('k-info').innerHTML = `${IC.info()}${esc(t('Info & Hilfe'))}`;
  $('k-info').addEventListener('click', () => oeffneInfo('alle'));
  $('k-pause').addEventListener('click', umschaltenPause);
  /* Im Log hochscrollen hält das Mitlaufen an (neue Zeilen werden gesammelt), zurück nach
     unten läuft es wieder mit. Wegen column-reverse ist scrollTop unten 0 und oben negativ. */
  $('term').addEventListener('scroll', () => {
    const oben = Math.abs($('term').scrollTop) > 6;
    if (oben && !S.hoch) { S.hoch = true; renderPause(); }
    else if (!oben && S.hoch) { S.hoch = false; if (!S.angehalten) leerePuffer(); renderPause(); renderLeer(); }
  }, { passive: true });
  $('k-zum-ende').addEventListener('click', () => $('term').scrollTo({ top: 0, behavior: reduziert.matches ? 'auto' : 'smooth' }));
  $('k-weiter').addEventListener('click', umschaltenPause);
  $('k-umbrechen').addEventListener('click', () => setzeUmbruch(true));
  $('k-abschneiden').addEventListener('click', () => setzeUmbruch(false));
  $('vm-icon').innerHTML = IC.server();
  renderModus(); renderPause(); renderKopf(); renderLeer();

  /* Sekundentakt: Uhr, Laufzeiten, „vor …“, Wachhund für die Verbindung */
  setInterval(() => {
    if (S.verbindung === 'verbunden' && S.letzteDaten && Date.now() - S.letzteDaten > 5000) setzeVerbindung('getrennt');
    // Der Server schickt jede Sekunde Daten. Bleiben sie aus, obwohl die Verbindung offen scheint
    // (Server hat den Strom verworfen, Netz hängt), selbst neu verbinden – mit wachsender Wartezeit.
    if (quelle && Date.now() - (S.letzteDaten || seitStart) > STILLE_MAX && Date.now() - letzterVersuch > wartezeit) {
      wartezeit = Math.min(wartezeit * 2, 30000); verbinde();
    }
    renderReiter(); renderKopf(); renderStatus(); renderWorkflows(); if (S.info) renderInfo();
    if (S.info && Date.now() - S.ir.geladen > 60000 && !S.ir.form && S.ir.erk !== 'laeuft') irLade();
  }, 1000);

  /* ------------------------------------------------------------ Verbindung */
  const DEMO = new URLSearchParams(location.search).has('demo');
  const STILLE_MAX = 10000, seitStart = Date.now();
  let quelle = null, letzterVersuch = 0, wartezeit = 2000, neuTimer = 0;
  function verbinde() {
    clearTimeout(neuTimer);
    if (quelle) quelle.close();
    letzterVersuch = Date.now();
    // Mit Journal-Runner: /events?journal=<id> – der Server liefert dann zusätzlich das Journal seiner Unit (#95)
    quelle = new EventSource(RUNNER.journalUrl(S.stromJournal));
    for (const b of ['status', 'system', 'prozesse', 'platten', 'container', 'workflows', 'update', 'log', 'journal', 'runner', 'meldungen']) {
      quelle.addEventListener(b, (e) => { try { empfange(b, JSON.parse(e.data)); } catch (f) { console.error(b, f); } });
    }
    quelle.onopen = () => setzeVerbindung('verbunden');
    quelle.onerror = () => {
      setzeVerbindung('getrennt');
      // Abgemeldet (z. B. Sitzung abgelaufen)? Dann zur Anmeldung. /api/sitzung: 200 angemeldet, 401 nicht.
      fetch('/api/sitzung', { credentials: 'same-origin' }).then(r => { if (r.status === 401) location.href = '/anmelden'; }).catch(() => {});
      // Bei Netzfehlern verbindet EventSource sich selbst neu; nach einer Fehlantwort (z. B. während
      // eines Updates) gibt es auf – dann selbst neu versuchen.
      if (quelle.readyState === EventSource.CLOSED) { neuTimer = setTimeout(verbinde, wartezeit); wartezeit = Math.min(wartezeit * 2, 30000); }
    };
  }
  /* Anderer Runner mit Journal (oder keiner mehr): Live-Strom mit dem neuen Ziel neu verbinden; der Server
     schickt dann den Stand (log/journal mit „neu“). In der Demo liefert demo.js das Journal selbst. */
  function wechsleJournal() {
    if (DEMO) { if (window.RM_DEMO) window.RM_DEMO.journal(S.stromJournal); return; }
    if (quelle) verbinde();
  }
  renderZeitraum();  // gespeicherte Wahl sofort zeigen, auch vor den ersten Daten
  if (DEMO) {
    const s = document.createElement('script');
    s.src = '/static/demo.js';
    s.onload = () => window.RM_DEMO.start({ empfange, setzeVerbindung, S, renderKopf, waehleRunner });
    document.head.appendChild(s);
  } else verbinde();
})();
