/* Runner-Monitor – Dashboard (Design v1). Daten kommen per Server-Sent Events von /events.
   Bereiche und Felder: docs/FUNKTIONSWEISE.md › „Datenformat“. Mit ?demo statt /events der
   Simulator aus demo.js (für Entwicklung, Bildschirmfotos und Vorführung). */
'use strict';

(() => {
  const { $, IC, esc, zahl, zeit, hm, tm, wt, datum, dauer, vor, seit, mehrzahl, ms } = RM;
  const GiB = 1024 ** 3, GB = 1e9;
  const REPO = 'Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor';
  const MAX_ZEILEN = 1500;
  // Volle Pfadangabe: ./einrichten.sh gibt es nur im entpackten Ordner, dieser Pfad gilt immer nach der Installation.
  const SKRIPT = 'sudo /opt/runner-monitor/aktuell/einrichten.sh';
  const UPDATE_SCHRITTE = [['Release herunterladen', 'Archiv und Prüfsumme'], ['Prüfsumme prüfen', 'SHA-256 stimmt'], ['Installieren', 'alte Version gesichert'], ['Monitor neu starten', 'kurz nicht erreichbar'], ['Funktion prüfen', 'Daten kommen an']];

  const S = {
    status: null, system: null, prozesse: [], platten: [], workflows: null, update: null,
    cpuH: [], ramH: [], netzH: [], ereignisse: [], zeilenN: 0, puffer: [],
    verbindung: 'verbindet', letzteDaten: 0,
    umbruch: true, angehalten: false, hochgescrollt: false, pruefung: null, wfOffen: false, info: null, kerneN: 0,
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

  /* ------------------------------------------------------------ Empfang */
  function setzeVerbindung(v) {
    if (S.verbindung === v) return;
    S.verbindung = v; renderKopf(); renderStatus(); renderWorkflows();
  }

  function empfange(bereich, d) {
    S.letzteDaten = Date.now();
    if (S.verbindung !== 'verbunden') setzeVerbindung('verbunden');
    switch (bereich) {
      case 'status': S.status = d; renderKopf(); renderStatus(); renderLogKopf(); break;
      case 'system':
        S.system = d;
        if (d.verlauf) { S.cpuH = d.verlauf.cpu.slice(-600); S.ramH = d.verlauf.ram.slice(-600); S.netzH = (d.verlauf.netz || []).slice(-600); }
        else {
          S.cpuH.push(d.cpu); S.ramH.push(d.ram.gesamt ? d.ram.belegt / d.ram.gesamt * 100 : 0);
          if (d.netz) S.netzH.push([d.netz.empfangen, d.netz.gesendet]);
          if (S.cpuH.length > 600) { S.cpuH.shift(); S.ramH.shift(); }
          if (S.netzH.length > 600) S.netzH.shift();
        }
        renderSystem(); break;
      case 'prozesse': S.prozesse = d; renderProzesse(); break;
      case 'platten': S.platten = d; renderPlatten(); renderKopf(); break;
      case 'workflows': S.workflows = d; renderWorkflows(); renderKopf(); break;
      case 'update':
        S.update = d;
        if (S.pruefung && S.pruefung.zustand === 'laeuft' && d.neueste && ms(d.neueste.geprueft) >= S.pruefung.start - 1000) S.pruefung = { zustand: 'fertig', bis: Date.now() + 8000 };
        renderKopf(); if (S.info) renderInfo(); break;
      case 'log':
        if (d.neu) { S.ereignisse = []; $('term-innen').replaceChildren(); S.zeilenN = 0; S.puffer = []; }
        if (d.ereignisse && d.ereignisse.length) { S.ereignisse.push(...d.ereignisse); S.ereignisse = S.ereignisse.slice(-20); renderEreignisse(); }
        if (d.zeilen && d.zeilen.length) { if (S.angehalten) { S.puffer.push(...d.zeilen); renderPause(); } else haengeAn(d.zeilen); }
        renderLeer(); break;
      default: break;
    }
  }

  /* ------------------------------------------------------------ Meldungen (Kopfzeile Mitte) */
  function meldungen() {
    const M = [], st = S.status, w = S.workflows, u = S.update, jetzt = Date.now();
    if (S.verbindung === 'getrennt' && S.letzteDaten) M.push({ id: 'monitor', cls: 'fehler', ic: IC.getrennt(18), titel: 'Verbindung zum Monitor unterbrochen', text: `Stand ${zeit(S.letzteDaten)} (${vor((jetzt - S.letzteDaten) / 1000)}) · neuer Versuch läuft` });
    const us = u && u.status;
    if (us && us.zustand === 'laeuft') M.push({ id: 'update', cls: 'laeuft', ic: IC.update(), link: 'Details', titel: `Update auf ${us.version || ''} läuft`, text: `${(UPDATE_SCHRITTE[(us.schritt || 1) - 1] || UPDATE_SCHRITTE[0])[0]} (${us.schritt || 1}/5) · Runner arbeitet weiter` });
    if (us && us.zustand === 'fehler' && jetzt - ms(us.zeit) < 86400000) M.push({ id: 'update', cls: 'fehler', ic: IC.x(18), link: 'Details', titel: 'Update fehlgeschlagen', text: `Version ${u.installiert} wurde wiederhergestellt und läuft` });
    if (st && st.dienst.zustand === 'gestoppt') M.push({ id: 'gestoppt', cls: 'fehler', ic: IC.x(18), titel: 'Runner-Dienst gestoppt', text: 'Jobs bleiben in der Warteschlange' + (w && w.abfrage === 'ok' ? ` (${w.repos.reduce((a, r) => a + r.wartet, 0)} warten)` : '') });
    if (st && st.dienst.zustand === 'fehlt') M.push({ id: 'runner', cls: 'warn', ic: IC.warn(18), titel: 'Kein Runner eingerichtet', text: 'auf dieser VM wurde kein GitHub-Runner gefunden' });
    if (st && st.github.zustand === 'offline' && st.dienst.zustand === 'aktiv') M.push({ id: 'offline', cls: 'fehler', ic: IC.x(18), titel: 'Runner offline bei GitHub', text: `${st.github.seit ? 'seit ' + zeit(st.github.seit) + ' · ' : ''}Jobs werden nicht zugestellt` });
    if (w && ['nicht-erreichbar', 'kontingent', 'fehler'].includes(w.abfrage)) M.push({ id: 'github', cls: 'warn', ic: IC.warn(18), titel: w.abfrage === 'kontingent' ? 'GitHub-Kontingent erschöpft' : 'GitHub nicht erreichbar', text: `Workflows zeigen den Stand von ${w.abgefragt ? zeit(w.abgefragt) : '–'}` + (w.naechste ? ` · neuer Versuch in ${Math.max(0, Math.round((ms(w.naechste) - jetzt) / 1000))} s` : '') });
    if (w && ['token-ungueltig', 'keine-rechte'].includes(w.abfrage)) M.push({ id: 'token', cls: 'fehler', ic: IC.schluessel(18), titel: w.abfrage === 'token-ungueltig' ? 'GitHub-Token ungültig oder abgelaufen' : 'GitHub-Token ohne Zugriff', text: 'Workflows werden nicht mehr abgefragt' });
    if (w && w.abfrage === 'kein-token') M.push({ id: 'token', cls: 'neutral', ic: IC.schluessel(18), titel: 'Kein GitHub-Token', text: 'Workflows und GitHub-Status sind aus' });
    for (const p of S.platten || []) {
      if (p.schwelleFrei && p.frei < p.schwelleFrei) M.push({ id: 'platte', cls: 'warn', ic: IC.warn(18), titel: `Platte knapp: ${zahl(p.frei / GB, 1)} GB frei`, text: `unter ${zahl(p.schwelleFrei / GB, 0)} GB räumt der Runner vor jedem Job auf` });
    }
    if (w && w.tokenAblauf) {
      const tage = Math.ceil((ms(w.tokenAblauf) - jetzt) / 86400000);
      if (tage <= 14 && tage > 0) M.push({ id: 'token', cls: 'warn', ic: IC.schluessel(18), titel: `GitHub-Token läuft in ${tage} ${mehrzahl(tage, 'Tag', 'Tagen')} ab`, text: `am ${datum(w.tokenAblauf)} – danach bleiben die Workflows leer` });
    }
    if (u && u.neueste && u.neueste.version && vergleiche(u.neueste.version, u.installiert) > 0 && !(us && us.zustand === 'laeuft')) M.push({ id: 'update', cls: 'laeuft', ic: IC.update(), link: 'Was ist neu?', titel: `Version ${u.neueste.version} verfügbar`, text: `installiert ist ${u.installiert}` });
    if (us && us.zustand === 'erfolg' && jetzt - ms(us.zeit) < 3600000) M.push({ id: 'update', cls: 'ok', ic: IC.ok(18), link: 'Was ist neu?', titel: `Aktualisiert auf ${u.installiert}`, text: `um ${hm(us.zeit)} · alles läuft` });
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
      $('vm-name').textContent = st.vm || '–'; $('runner-name').textContent = st.runner || 'kein Runner';
      const lb = (st.labels || []).map(l => `<span class="label">${esc(l)}</span>`).join('');
      if ($('labels').innerHTML !== lb) $('labels').innerHTML = lb;
      document.title = `Runner-Monitor · ${st.vm}`;
    }
    const live = $('live');
    if (S.verbindung === 'verbunden') { live.className = 'live ok'; live.innerHTML = `<span class="punkt"></span><span>Verbunden</span><span class="live-zeit">aktualisiert ${zeit(S.letzteDaten)}</span>`; }
    else if (S.verbindung === 'getrennt') { live.className = 'live weg'; live.innerHTML = `${IC.getrennt()}<span>Getrennt</span><span class="live-zeit">${S.letzteDaten ? 'Stand ' + zeit(S.letzteDaten) : 'noch keine Daten'}</span>`; }
    else { live.className = 'live neutral'; live.innerHTML = '<span class="punkt"></span><span>Verbinde …</span>'; }
    $('uhr-datum').textContent = `${wt(jetzt)} ${tm(jetzt)}`; $('uhr-zeit').textContent = zeit(jetzt);
    $('raster').classList.toggle('veraltet', S.verbindung === 'getrennt' && !!S.letzteDaten);

    const M = meldungen(), box = $('meldungen');
    if (!M.length) { box.replaceChildren(); return; }
    const m = M[0];
    const html = `<div class="meldung ${m.cls}">${m.ic}<b>${esc(m.titel)}</b><span class="meldung-text">${esc(m.text)}</span>${M.length > 1 ? `<span class="meldung-mehr">+${M.length - 1} weitere</span>` : ''}<button type="button" class="meldung-link" data-aktion="info" data-anleitung="${m.id}">${esc(m.link || 'Was tun?')}</button></div>`;
    if (box.dataset.html !== html) { box.innerHTML = html; box.dataset.html = html; }
  }

  function renderModus() {
    const t = RM.thema();
    const name = { system: 'Auto', hell: 'Hell', dunkel: 'Dunkel' }[t];
    const ic = { system: IC.auto(), hell: IC.sonne(), dunkel: IC.mond() }[t];
    const folgt = { system: 'Hell', hell: 'Dunkel', dunkel: 'Automatisch' }[t];
    const k = $('k-modus'); k.innerHTML = `${ic}${name}`; k.setAttribute('aria-label', `Darstellung ${name}, umschalten auf ${folgt}`);
  }

  /* ------------------------------------------------------------ Runner-Status */
  function renderStatus() {
    const st = S.status; if (!st) return;
    const jetzt = Date.now(), ref = bezug(), w = S.workflows;
    const art = st.dienst.zustand === 'fehlt' ? 'fehlt' : st.dienst.zustand === 'gestoppt' ? 'gestoppt' : st.github.zustand === 'offline' ? 'offline' : st.job ? 'job' : 'bereit';
    const pillD = st.dienst.zustand === 'aktiv' ? `<span class="pill ok">${IC.ok(13, 1.7)}Dienst aktiv</span>` : st.dienst.zustand === 'fehlt' ? `<span class="pill neutral">${IC.unklar()}Kein Dienst</span>` : `<span class="pill fehler">${IC.x(13, 1.7)}Dienst gestoppt</span>`;
    const g = st.github.zustand;
    const pillG = g === 'online' ? `<span class="pill ok">${IC.ok(13, 1.7)}Online bei GitHub</span>` : g === 'offline' ? `<span class="pill fehler">${IC.x(13, 1.7)}Offline bei GitHub</span>` : `<span class="pill neutral">${IC.unklar()}GitHub: unbekannt</span>`;
    const kopf = {
      job: ['laeuft', IC.play(28, 1.3), 'Job läuft'], bereit: ['ok', IC.ok(28, 1.3), 'Bereit'], fehlt: ['warn', IC.warn(28, 1.3), 'Kein Runner'],
      gestoppt: ['fehler', IC.stop(28), 'Dienst gestoppt'], offline: ['warn', IC.warn(28, 1.3), 'Offline bei GitHub'],
    }[art];
    const l0 = (st.letzteJobs || [])[0];
    const letzter = l0 ? `${l0.repo ? esc(l0.repo) + ' · ' : ''}${l0.workflow ? esc(l0.workflow) + ' · ' : ''}${esc(l0.name)} · ${vor((jetzt - ms(l0.ende)) / 1000)}` : '–';
    let mitte;
    if (art === 'job') {
      const j = st.job, n = (j.schritte || []).length, nr = j.schritt || 1;
      const schrittName = n ? j.schritte[Math.min(nr, n) - 1] : `Schritt ${nr}`;
      mitte = `
        <div>
          <div class="job-repo">${esc(j.repo || j.name)}${j.privat ? IC.schloss() : ''}</div>
          ${j.workflow ? `<div class="job-pfad">Workflow <b>${esc(j.workflow)}</b><span class="sep">›</span>Job <b>${esc(j.name)}</b></div>` : `<div class="job-pfad">Job <b>${esc(j.name)}</b></div>`}
          ${j.ref ? `<div class="job-ref"><span>${esc(j.ref.art)}</span><span class="ref">${esc(j.ref.name)}</span><span class="ref-titel">${esc(j.ref.titel || '')}</span></div>` : ''}
        </div>
        <div class="schritt">
          <div class="zeile-k"><span>Aktueller Schritt</span><span>${n ? `${nr} von ${n}` : `Nr. ${nr}`}</span></div>
          <div class="schritt-name">${esc(schrittName)}</div>
          ${n ? `<div class="segmente" data-spalten="${n}">${j.schritte.map((_, i) => `<span class="seg${i < nr - 1 ? ' fertig' : i === nr - 1 ? ' aktiv' : ''}"></span>`).join('')}</div>` : ''}
        </div>
        <div class="zahlen">
          <div><div class="zeile-k">Laufzeit</div><div class="zahl-gross">${j.start ? dauer((ref - ms(j.start)) / 1000) : '–'}</div></div>
          <div><div class="zeile-k">Gestartet</div><div class="zahl-mittel">${j.start ? zeit(j.start) : '–'}</div><div class="zahl-sub">${j.start ? `${wt(j.start)}, ${tm(j.start)}` : ''}</div></div>
        </div>`;
    } else {
      const text = {
        bereit: 'Wartet auf den nächsten Job. Neue Jobs starten automatisch.',
        gestoppt: 'Der Runner-Dienst läuft nicht. Neue Jobs bleiben bei GitHub in der Warteschlange, bis er wieder startet.',
        offline: 'Der Dienst läuft, aber GitHub sieht den Runner nicht. Jobs werden ihm gerade nicht zugestellt.',
        fehlt: 'Auf dieser VM ist kein GitHub-Runner eingerichtet. Das Einrichtungsskript kann ihn mit einrichten.',
      }[art];
      const wartend = w && w.abfrage === 'ok' ? w.repos.reduce((a, r) => a + r.wartet, 0) : null;
      const dienstSeit = st.dienst.seit ? (art === 'gestoppt' ? `gestoppt seit ${zeit(st.dienst.seit)} (${vor((jetzt - ms(st.dienst.seit)) / 1000)})` : `aktiv seit ${seit((jetzt - ms(st.dienst.seit)) / 1000)}`) : (art === 'gestoppt' ? 'gestoppt' : art === 'fehlt' ? 'nicht vorhanden' : 'aktiv');
      const kv = art === 'gestoppt' ? [['Dienst', dienstSeit], ['Wartende Jobs', wartend == null ? 'unbekannt' : `${wartend} in der Warteschlange`], ['Letzter Job', letzter]]
        : art === 'offline' ? [['Dienst', dienstSeit], ['Bei GitHub', st.github.seit ? `offline seit ${zeit(st.github.seit)} (${vor((jetzt - ms(st.github.seit)) / 1000)})` : 'offline'], ['Letzter Job', letzter]]
        : art === 'fehlt' ? [['Runner', 'nicht gefunden in /opt/actions-runner'], ['Einrichten', `${SKRIPT} runner`]]
        : [['Dienst', dienstSeit], ['Letzter Job', letzter], ['Runner-Version', esc(st.version || '–')]];
      mitte = `<p class="zustand-text">${text}</p><dl class="kv">${kv.map(([k, v]) => `<div class="kv-z"><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl>`
        + (art === 'gestoppt' || art === 'offline' ? `<button type="button" class="link-knopf" data-aktion="info" data-anleitung="logs">${IC.datei()}Runner-Logs abrufen ›</button>` : '');
    }
    const ERG = { erfolg: ['ok', IC.ok(), 'Erfolg'], fehler: ['fehler', IC.x(), 'Fehler'], abgebrochen: ['neutral', IC.abbr(), 'Abgebrochen'] };
    const letzte = (st.letzteJobs || []).slice(0, 5).map(j => {
      const e = ERG[j.ergebnis] || ERG.abgebrochen;
      const wf = [j.workflow, j.name].filter(Boolean).map(esc).join(' · ');
      return `<div class="jobzeile"><span class="erg ${e[0]}">${e[1]}${e[2]}</span><span class="jz-name">${esc(j.repo || '')}${j.repo ? ' ' : ''}<span class="jz-wf">${j.repo ? '· ' : ''}${wf}</span></span><span class="r">${j.dauer != null ? dauer(j.dauer) : '–'}</span><span class="jz-ende">${hm(j.ende)}</span></div>`;
    }).join('');
    $('status').innerHTML = `
      <div class="karte-kopf"><span class="karte-titel">Runner-Status</span><div class="pillen">${pillD}${pillG}</div></div>
      <div class="zustand ${kopf[0]}">${kopf[1]}<span class="zustand-titel">${kopf[2]}</span></div>
      ${mitte}
      <div class="letzte"><div class="letzte-titel">Letzte Jobs</div>${letzte || '<div class="leer">Seit dem Start des Monitors noch keine Jobs.</div>'}</div>`;
    // Spaltenzahl der Schritt-Segmente per CSSOM (CSP erlaubt keine style-Attribute)
    const segs = $('status').querySelector('.segmente');
    if (segs) segs.style.gridTemplateColumns = `repeat(${segs.dataset.spalten}, minmax(0, 1fr))`;
  }

  /* ------------------------------------------------------------ Workflows */
  function renderWorkflows() {
    const w = S.workflows, el = $('workflows'); if (!w) return;
    if (el.contains(document.activeElement) && el.dataset.letzte && Date.now() - Number(el.dataset.letzte) < 5000) return;
    el.dataset.letzte = String(Date.now());
    const jetzt = Date.now();
    let inhalt = '', fuss = '';
    if (w.abfrage === 'kein-token') {
      inhalt = `<div class="leerzustand"><span class="leer-ic">${IC.schluessel(26, 1.2)}</span><div class="leer-titel">Kein GitHub-Token eingerichtet</div><div class="leer-text">Ohne Token bleibt dieser Bereich leer. Runner-Status, Auslastung und Log laufen normal weiter.</div><div class="leer-pfad">/etc/runner-monitor/github-token</div><button type="button" class="link-knopf" data-aktion="info" data-anleitung="token">Anleitung: Token einrichten ›</button></div>`;
      fuss = '<div class="wf-zeit">Abfrage aus</div>';
    } else {
      const aktiv = w.repos.filter(r => r.laeuft || r.wartet), ruhig = w.repos.filter(r => !r.laeuft && !r.wartet);
      const L = aktiv.reduce((a, r) => a + r.laeuft, 0), W = aktiv.reduce((a, r) => a + r.wartet, 0);
      const alt = !['ok'].includes(w.abfrage);
      inhalt = `<div class="wf-inhalt${alt ? ' alt' : ''}">
        <div class="summen">
          <div class="summe laeuft">${IC.play(16)}<span class="summe-zahl">${L}</span><span class="summe-text">${mehrzahl(L, 'läuft', 'laufen')}</span></div>
          <div class="summe wartet">${IC.uhr()}<span class="summe-zahl">${W}</span><span class="summe-text">${mehrzahl(W, 'wartet', 'warten')}</span></div>
        </div>
        ${aktiv.map(r => `<div class="repo"><span class="repo-name">${esc(r.name)}${r.privat ? IC.schloss(12) : ''}</span><span class="repo-pillen">${r.laeuft ? `<span class="pill laeuft">${IC.dreieck()}${r.laeuft} ${mehrzahl(r.laeuft, 'läuft', 'laufen')}</span>` : ''}${r.wartet ? `<span class="pill wartet">${IC.uhr(12, 1.7)}${r.wartet} ${mehrzahl(r.wartet, 'wartet', 'warten')}</span>` : ''}</span></div>`).join('')}
        ${aktiv.length ? '' : `<div class="alle-ruhig">${IC.ok()}Nichts läuft, nichts wartet</div>`}
        ${ruhig.length ? `<button type="button" class="ruhig-knopf" data-aktion="wf-offen" aria-expanded="${S.wfOffen}">${IC.chev(S.wfOffen)}${aktiv.length ? `${ruhig.length} weitere ruhig` : `Alle ${ruhig.length} Repositories ruhig`}</button>` : ''}
        ${S.wfOffen ? `<div class="ruhig-liste">${ruhig.map(r => `<span class="ruhig-repo">${esc(r.name)}</span>`).join('')}</div>` : ''}
      </div>`;
      if (alt) {
        const texte = { 'nicht-erreichbar': 'GitHub nicht erreichbar', kontingent: 'API-Kontingent erschöpft', 'token-ungueltig': 'Token ungültig oder abgelaufen', 'keine-rechte': 'Token ohne Zugriff auf die Organisation', fehler: 'Abfrage fehlgeschlagen' };
        fuss += `<div class="hinweis warn">${IC.warn()}<div>${texte[w.abfrage] || 'Abfrage fehlgeschlagen'} <span>– angezeigt wird der Stand von ${w.abgefragt ? zeit(w.abgefragt) : '–'}.${w.naechste ? ` Neuer Versuch in ${Math.max(0, Math.round((ms(w.naechste) - jetzt) / 1000))} s.` : ''}</span></div></div>`;
      }
      if (w.tokenAblauf) {
        const tage = Math.ceil((ms(w.tokenAblauf) - jetzt) / 86400000);
        if (tage <= 14) fuss += `<div class="hinweis warn">${IC.schluessel()}<div>${tage > 0 ? `Token läuft in ${tage} ${mehrzahl(tage, 'Tag', 'Tagen')} ab` : 'Token ist abgelaufen'} <span>(${datum(w.tokenAblauf)}). Danach bleibt dieser Bereich leer.</span></div></div>`;
      }
      const nx = w.naechste ? Math.max(0, Math.round((ms(w.naechste) - jetzt) / 1000)) : null;
      fuss += `<div class="wf-zeit">${alt ? `Letzte erfolgreiche Abfrage ${w.abgefragt ? zeit(w.abgefragt) : '–'}` : `Abgefragt ${zeit(w.abgefragt)}${S.verbindung === 'verbunden' && nx != null ? ` · nächste in ${nx} s` : ''}`}</div>`;
    }
    const meta = w.abfrage === 'kein-token' ? esc(w.org) : `${esc(w.org)} · ${w.repos.length} Repositories`;
    el.innerHTML = `<div class="karte-kopf"><span class="karte-titel">Workflows</span><span class="karte-meta">${meta}</span></div>${inhalt}<div class="wf-fuss">${fuss}</div>`;
  }

  /* ------------------------------------------------------------ Auslastung */
  // 600 Werte = 10 Minuten, 120 Stützpunkte zu je 5 s. Kürzerer Verlauf liegt rechtsbündig („jetzt“ rechts).
  function spark(h) {
    const N = 600, n = 120, b = N / n, off = N - Math.min(h.length, N), daten = h.slice(-N), pts = [];
    for (let i = 0; i < n; i++) {
      let s = 0, c = 0;
      for (let g = i * b; g < (i + 1) * b; g++) { const j = g - off; if (j >= 0 && j < daten.length) { s += daten[j]; c++; } }
      if (!c) continue;
      pts.push(`${(i * 300 / (n - 1)).toFixed(1)},${(45 - Math.max(0, Math.min(100, s / c)) / 100 * 43).toFixed(1)}`);
    }
    if (!pts.length) return ['', ''];
    const linie = 'M' + pts.join(' L');
    return [linie, `${linie} L${pts[pts.length - 1].split(',')[0]},46 L${pts[0].split(',')[0]},46 Z`];
  }

  /* Bytes je Sekunde, dezimal wie bei Netzwerken üblich (1 MB/s = 1 000 000 B/s). */
  function rate(b) {
    if (!b || b < 1000) return [zahl(b || 0, 0), 'B/s'];
    if (b < 1e6) return [zahl(b / 1e3, b < 1e4 ? 1 : 0), 'KB/s'];
    if (b < 1e9) return [zahl(b / 1e6, b < 1e8 ? 1 : 0), 'MB/s'];
    return [zahl(b / 1e9, 2), 'GB/s'];
  }
  function setzeRate(id, b) { const [w, e] = rate(b); $(id).innerHTML = `${w}<small>${e}</small>`; }
  function renderSystem() {
    const d = S.system; if (!d) return;
    const n = d.kerne.length;
    $('sys-meta').textContent = `${n} Kerne · ${zahl(d.ram.gesamt / GiB, 0)} GB RAM · läuft seit ${seit((Date.now() - ms(d.start)) / 1000)}`;
    $('cpu').textContent = zahl(d.cpu, 0);
    const k = $('kerne');
    if (S.kerneN !== n) {
      S.kerneN = n;
      k.style.gridTemplateRows = `repeat(${Math.ceil(n / 2)}, minmax(12px, 22px))`;
      k.innerHTML = d.kerne.map((_, i) => `<div class="kern"><span class="kern-l">${i + 1}</span><span class="balken"><span class="fuell"></span></span><span class="kern-w"></span></div>`).join('');
    }
    [...k.children].forEach((row, i) => { feder(row.children[1].firstChild, d.kerne[i] / 100); row.children[2].textContent = `${zahl(d.kerne[i], 0)} %`; });
    const [cl, cf] = spark(S.cpuH), [rl, rf] = spark(S.ramH);
    $('cpu-linie').setAttribute('d', cl); $('cpu-flaeche').setAttribute('d', cf);
    $('ram-linie').setAttribute('d', rl); $('ram-flaeche').setAttribute('d', rf);
    $('ram').textContent = `${zahl(d.ram.belegt / GiB, 1)} GB`; $('ram-gesamt').textContent = ` / ${zahl(d.ram.gesamt / GiB, 0)} GB`;
    feder($('ram-fuell'), d.ram.gesamt ? d.ram.belegt / d.ram.gesamt : 0);
    $('ram-pct').textContent = `${zahl(d.ram.gesamt ? d.ram.belegt / d.ram.gesamt * 100 : 0, 0)} %`;
    feder($('swap-fuell'), d.swap.gesamt ? d.swap.belegt / d.swap.gesamt : 0);
    $('swap').textContent = `${zahl(d.swap.belegt / GiB, 1)} / ${zahl(d.swap.gesamt / GiB, 1)} GB`;
    if (d.netz) {
      setzeRate('netz-rx', d.netz.empfangen); setzeRate('netz-tx', d.netz.gesendet);
      setzeRate('netz-spitze', S.netzH.reduce((m, [rx, tx]) => Math.max(m, rx, tx), 0));
    }
    $('l1').textContent = zahl(d.last[0], 2); $('l5').textContent = zahl(d.last[1], 2); $('l15').textContent = zahl(d.last[2], 2); $('kerne-n').textContent = n;
  }

  function renderProzesse() {
    // Pfade auf den letzten Teil kürzen, z. B. „node vitest run“
    const kurz = b => b.split(' ').map(t => (t.includes('/') && !t.startsWith('fd:') ? t.replace(/\/+$/, '').split('/').pop() || t : t)).join(' ');
    $('prozesse').innerHTML = (S.prozesse || []).slice(0, 6).map(p => `<div class="pz"><span class="mut">${p.pid}</span><span class="eng">${esc(p.benutzer)}</span><span class="r">${zahl(p.cpu, 1)}</span><span class="r mut">${zahl(p.ram, 1)}</span><span class="cmd" title="${esc(p.befehl)}">${esc(kurz(p.befehl))}</span></div>`).join('');
  }

  function renderPlatten() {
    const liste = S.platten || [];
    $('pl-anzahl').textContent = `${liste.length} ${mehrzahl(liste.length, 'Laufwerk', 'Laufwerke')}`;
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
      const frei = el.querySelector('.pl-frei-k'); frei.textContent = `${zahl(p.frei / GB, 1)} GB frei`; frei.classList.toggle('warn', knapp);
      el.querySelector('.karte-meta').textContent = `${zahl(p.belegt / GB, 1)} von ${zahl(p.gesamt / GB, 0)} GB`;
      const balken = el.querySelector('.pl-balken');
      balken.setAttribute('aria-label', `${p.pfad}: ${zahl(p.belegt / GB, 1)} von ${zahl(p.gesamt / GB, 0)} GB belegt, ${zahl(p.frei / GB, 1)} GB frei`);
      const [a, b] = balken.querySelectorAll('.pl-teil');
      a.style.width = `${Math.min(p.belegt, hs ? sb : p.gesamt) / p.gesamt * 100}%`;
      b.style.left = `${sPct}%`; b.style.width = `${hs ? Math.max(0, p.belegt - sb) / p.gesamt * 100 : 0}%`;
      const marke = balken.querySelector('.pl-marke'); marke.hidden = !hs; marke.style.left = `${sPct}%`;
      const unten = el.querySelector('.pl-unten');
      const html = !hs ? '' : knapp
        ? `<div class="hinweis warn pl-warn">${IC.warn(14)}<div>Unter ${zahl(p.schwelleFrei / GB, 0)} GB frei <span>– der Runner räumt vor jedem Job auf.</span></div></div>`
        : `<div class="pl-legende"><span>Aufräumen unter ${zahl(p.schwelleFrei / GB, 0)} GB frei</span></div>`;
      if (unten.dataset.html !== html) { unten.innerHTML = html; unten.dataset.html = html; }
      const leg = unten.querySelector('.pl-legende span'); if (leg) leg.style.right = `${100 - sPct}%`;
    });
  }

  /* ------------------------------------------------------------ Live-Log */
  function renderLogKopf() {
    const j = S.status && S.status.job, chip = $('schritt-chip');
    if (j && S.status.dienst.zustand === 'aktiv') {
      const n = (j.schritte || []).length, nr = j.schritt || 1;
      chip.hidden = false; chip.textContent = n ? `Schritt ${nr}/${n} · ${j.schritte[Math.min(nr, n) - 1]}` : `Schritt ${nr}`;
    } else chip.hidden = true;
    renderLeer();
  }

  function renderEreignisse() {
    const E = S.ereignisse.slice(-3).map(e => {
      const was = [e.repo, e.workflow].filter(Boolean).map(esc).join(' · ') + (e.repo || e.workflow ? ' / ' : '') + esc(e.name || '');
      if (e.art === 'start') return [e.zeit, 'laeuft', IC.play(), 'Job gestartet', was, ''];
      if (e.art === 'ende') { const ok = e.ergebnis === 'erfolg'; const cls = ok ? 'ok' : e.ergebnis === 'fehler' ? 'fehler' : 'neutral'; return [e.zeit, cls, ok ? IC.ok() : e.ergebnis === 'fehler' ? IC.x() : IC.abbr(), 'Job beendet', was, `${ok ? 'Erfolg' : e.ergebnis === 'fehler' ? 'Fehler' : 'Abgebrochen'}${e.dauer != null ? ' · ' + dauer(e.dauer) : ''}`]; }
      if (e.art === 'dienst-gestoppt') return [e.zeit, 'fehler', IC.x(), 'Dienst gestoppt', 'Runner-Dienst: inactive (dead)', ''];
      if (e.art === 'dienst-gestartet') return [e.zeit, 'ok', IC.ok(), 'Dienst gestartet', 'Runner-Dienst: active (running)', ''];
      return [e.zeit, 'warn', IC.warn(14), 'Hinweis', esc(e.name || ''), ''];
    });
    $('ereignisse').innerHTML = E.map(([t, cls, ic, titel, text, rechts]) => `<div class="ev"><span class="ev-zeit">${zeit(t)}</span><span class="${cls}">${ic}</span><span class="ev-text"><b>${titel}</b> · ${text}</span><span class="ev-rechts ${cls}">${rechts}</span></div>`).join('');
  }

  function zeileEl(z) {
    const div = document.createElement('div');
    if (z.art === 'schritt') {
      div.className = 'trenner';
      div.innerHTML = `<span class="tr-nr">Schritt ${z.nr}${z.von ? '/' + z.von : ''}</span><span class="tr-name">${esc(z.name)}</span><span class="tr-linie"></span><span class="tr-zeit">${zeit(z.zeit)}</span>`;
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
    leer.hidden = S.zeilenN > 0 || S.puffer.length > 0;
    leer.textContent = st && st.dienst.zustand === 'gestoppt' ? 'Der Runner-Dienst ist gestoppt – es kommt keine Ausgabe.'
      : st && st.github.zustand === 'offline' ? 'Kein Schritt läuft. GitHub stellt dem Runner gerade keine Jobs zu.'
      : 'Kein Schritt läuft. Die Ausgabe erscheint hier, sobald ein Job startet.';
  }
  function renderPause() {
    const k = $('k-pause');
    k.innerHTML = S.angehalten ? `${IC.dreieck(12)}Weiter` : `${IC.pause()}Anhalten`;
    k.setAttribute('aria-pressed', String(S.angehalten));
    $('term').classList.toggle('pausiert', S.angehalten);
    $('pause-hinweis').hidden = !S.angehalten;
    $('pause-text').textContent = `Angehalten · ${S.puffer.length} ${mehrzahl(S.puffer.length, 'neue Zeile', 'neue Zeilen')}`;
  }
  function umschaltenPause() {
    S.angehalten = !S.angehalten; S.hochgescrollt = false;
    if (!S.angehalten) { const p = S.puffer; S.puffer = []; if (p.length) haengeAn(p); $('term').scrollTop = 0; }
    renderPause(); renderLeer();
  }
  function setzeUmbruch(an) {
    S.umbruch = an; $('term').classList.toggle('kurz', !an);
    $('k-umbrechen').setAttribute('aria-pressed', String(an)); $('k-abschneiden').setAttribute('aria-pressed', String(!an));
  }

  /* ------------------------------------------------------------ Info & Hilfe */
  function anleitungen() {
    const st = S.status || { dienst: {}, github: {} }, w = S.workflows || {}, u = S.update || {}, us = u.status || {};
    const knapp = (S.platten || []).some(p => p.schwelleFrei && p.frei < p.schwelleFrei);
    const tokenAblauf = w.tokenAblauf && (ms(w.tokenAblauf) - Date.now()) < 14 * 86400000;
    return [
      { id: 'token', titel: 'GitHub-Token einrichten oder erneuern', aktiv: ['kein-token', 'token-ungueltig', 'keine-rechte'].includes(w.abfrage) || tokenAblauf, wann: 'Wenn „Kein GitHub-Token“, „Token ungültig“ oder „Token läuft ab“ gemeldet wird.', schritte: [
        ['Auf github.com: Profilbild › Settings › Developer settings › Personal access tokens › Fine-grained tokens › „Generate new token“.'],
        ['Resource owner: die Organisation, nicht das eigene Konto. Repository access: All repositories. Ablauf zum Beispiel 1 Jahr.'],
        ['Nur lesende Rechte: Repository › Actions „Read-only“ (Metadata kommt automatisch dazu). Für den Online-Status des Runners zusätzlich Organization › Self-hosted runners „Read-only“.'],
        ['Verlangt die Organisation eine Freigabe, das Token unter Organisation › Settings › Personal access tokens › Pending requests freigeben. Vorher meldet der Monitor „ohne Zugriff“.'],
        ['Auf der VM das Token eintragen (Eingabe bleibt unsichtbar, nur root kann die Datei lesen). Das Skript fragt auch nach der Organisation – Enter behält die bisherige:', `${SKRIPT} token`],
        ['Die nächste Abfrage (spätestens nach 30 s) übernimmt es. Prüfen, ob GitHub das Token annimmt (200 = in Ordnung, 401 = ungültig, 403/404 = kein Zugriff):', `sudo bash -c 'curl -s -o /dev/null -w "%{http_code}\\n" -H "Authorization: Bearer $(cat /etc/runner-monitor/github-token)" "https://api.github.com/orgs/${w.org || 'ORGANISATION'}/repos?per_page=1"'`],
      ] },
      { id: 'github', titel: 'GitHub nicht erreichbar', aktiv: ['nicht-erreichbar', 'kontingent', 'fehler'].includes(w.abfrage), wann: 'Wenn die Abfrage der Workflows fehlschlägt. Die Karte zeigt dann den letzten Stand.', schritte: [
        ['Zuerst den Status von GitHub prüfen: githubstatus.com.'],
        ['Von der VM aus testen, ob die API antwortet:', 'curl -sI https://api.github.com | head -1'],
        ['Antwort 401: Token ungültig oder abgelaufen, siehe „GitHub-Token einrichten oder erneuern“. Antwort 403: API-Kontingent erschöpft, die Abfrage setzt bis zum Reset aus.'],
        ['Keine Antwort: DNS, Firewall oder Proxy der VM prüfen. Letzte Meldungen des Sammlers:', 'journalctl -u runner-monitor-sammler -n 30'],
      ] },
      { id: 'gestoppt', titel: 'Runner-Dienst gestoppt', aktiv: st.dienst.zustand === 'gestoppt', cls: 'fehler', wann: 'Wenn der systemd-Dienst des Runners nicht läuft. Jobs bleiben dann in der Warteschlange.', schritte: [
        ['Status und letzte Meldungen ansehen:', "systemctl status 'actions.runner.*'"],
        ['Dienst starten:', "sudo systemctl start 'actions.runner.*'"],
        ['Startet er nicht, das Protokoll prüfen:', "journalctl -u 'actions.runner.*' -n 50"],
        ['Wartende Jobs laufen danach von selbst an. Woran es lag, steht in den Logs – siehe „Runner-Logs abrufen“.'],
      ] },
      { id: 'offline', titel: 'Runner offline bei GitHub', aktiv: st.github.zustand === 'offline', cls: 'fehler', wann: 'Wenn der Dienst läuft, GitHub den Runner aber nicht sieht.', schritte: [
        ['Netz der VM prüfen:', 'curl -sI https://github.com | head -1'],
        ['Dienst neu starten, damit er sich neu anmeldet:', "sudo systemctl restart 'actions.runner.*'"],
        ['Wurde der Runner in GitHub entfernt (Organisation › Settings › Actions › Runners), neu registrieren:', `${SKRIPT} runner --umziehen`],
        ['Warum die Verbindung fehlt, steht im Diagnoseprotokoll – siehe „Runner-Logs abrufen“.'],
      ] },
      { id: 'logs', titel: 'Runner-Logs abrufen (Diagnose)', aktiv: st.dienst.zustand === 'gestoppt' || st.github.zustand === 'offline', cls: st.dienst.zustand === 'gestoppt' ? 'fehler' : 'warn', wann: 'Wenn der Runner-Dienst stoppt, abstürzt, offline ist oder Jobs nicht annimmt. Alle Befehle auf der VM ausführen.', schritte: [
        ['Dienst-Protokoll: Start, Stopp, Abstürze, Job-Start und -Ende. Die letzten 100 Zeilen:', "journalctl -u 'actions.runner.*' -n 100 --no-pager"],
        ['Dasselbe live mitlesen (Strg+C beendet):', "journalctl -u 'actions.runner.*' -f"],
        ['Diagnoseprotokoll des Runners: Anmeldung bei GitHub, Verbindungsfehler, Updates. Neueste Datei:', 'sudo tail -n 100 "$(ls -t /opt/actions-runner/_diag/Runner_*.log | head -1)"'],
        ['Protokoll des letzten Jobs (Worker), wenn ein Job abbricht oder hängt:', 'sudo tail -n 100 "$(ls -t /opt/actions-runner/_diag/Worker_*.log | head -1)"'],
        ['Ausgabe der einzelnen Schritte, eine Datei je Schritt:', 'ls -lt /opt/actions-runner/_diag/pages/ | head'],
        ['Logs abgeschlossener Jobs liegen bei GitHub: Repository › Actions › Lauf öffnen › Job › „Download log archive“.'],
        ['Alles gebündelt zum Weitergeben:', "sudo tar czf ~/runner-diag.tgz -C /opt/actions-runner _diag\njournalctl -u 'actions.runner.*' --since today > ~/runner-journal.txt"],
      ] },
      { id: 'platte', titel: 'Platte knapp', aktiv: knapp, wann: 'Wenn auf „/“ weniger als die Aufräumschwelle (25 GB) frei ist.', schritte: [
        ['Der Runner räumt dann vor jedem Job selbst auf. Sofort aufräumen:', 'sudo runner-aufraeumen'],
        ['Wer belegt den Platz?', 'docker system df'],
        ['Freien Platz an Proxmox zurückgeben:', 'sudo fstrim -av'],
        ['Reicht das dauerhaft nicht, die Platte der VM in Proxmox vergrößern (Runbook docs/runbooks/platte-voll.md).'],
      ] },
      { id: 'monitor', titel: 'Verbindung zum Monitor unterbrochen', aktiv: S.verbindung === 'getrennt', cls: 'fehler', wann: 'Wenn diese Seite keine Daten mehr von der VM bekommt. Sie zeigt dann den letzten Stand.', schritte: [
        ['Die Seite versucht es selbst weiter. Ist die VM im Netz erreichbar?', `ping ${st.vm || 'runner-vm'}`],
        ['Monitor-Dienst auf der VM neu starten:', 'sudo systemctl restart runner-monitor'],
        ['Letzte Meldungen des Monitors:', 'journalctl -u runner-monitor -n 30'],
      ] },
      { id: 'update', titel: 'Monitor aktualisieren', aktiv: us.zustand === 'fehler' || (u.neueste && vergleiche(u.neueste.version, u.installiert) > 0), cls: us.zustand === 'fehler' ? 'fehler' : 'warn', wann: 'Wenn eine neue Version gemeldet wird oder ein Update fehlgeschlagen ist.', schritte: [
        ['Am einfachsten oben in „Updates“ auf „Jetzt aktualisieren“ klicken. Ein Hilfsdienst auf der VM lädt das offizielle Release, prüft die Prüfsumme, installiert es und startet den Monitor neu. Antwortet die neue Version nicht, stellt er die alte wieder her.'],
        ['Oder per SSH auf der VM:', `${SKRIPT} aktualisieren`],
        ['Protokoll des letzten Updates:', 'journalctl -u runner-monitor-update -n 50'],
        ['Zur vorherigen Version zurück:', `${SKRIPT} zurueck`],
      ] },
    ];
  }

  /* „Jetzt prüfen“: fragt GitHub sofort nach einer neuen Version (über den root-Sammler, höchstens
     einmal je Minute). Zustand in S.pruefung: laeuft → fertig/frisch/keine-antwort, verschwindet nach einigen Sekunden. */
  function pruefKnopf(u, us, neu) {
    const p = S.pruefung, jetzt = Date.now();
    if (p && p.bis && jetzt > p.bis) S.pruefung = null;
    if (p && p.zustand === 'laeuft' && jetzt - p.start > 45000) S.pruefung = { zustand: 'keine-antwort', bis: jetzt + 30000 };
    const q = S.pruefung;
    const text = !q ? '' : q.zustand === 'laeuft' ? 'Frage GitHub nach neuen Versionen …'
      : q.zustand === 'frisch' ? 'Gerade erst geprüft – Stand siehe oben.'
      : q.zustand === 'keine-antwort' ? 'Keine Antwort vom Sammler. Auf der VM prüfen: journalctl -u runner-monitor-sammler -n 30'
      : u.neueste && u.neueste.fehler ? `GitHub nicht erreichbar: ${esc(u.neueste.fehler)}`
      : neu ? `Version ${esc(u.neueste.version)} ist verfügbar.` : 'Auf dem neuesten Stand.';
    const cls = !q ? '' : q.zustand === 'keine-antwort' || (q.zustand === 'fertig' && u.neueste && u.neueste.fehler) ? 'fehler' : q.zustand === 'fertig' && !neu ? 'ok' : '';
    const aus = (q && q.zustand === 'laeuft') || us.zustand === 'laeuft';
    return `<div class="upd-pruefen"><button type="button" class="knopf" data-aktion="update-pruefen"${aus ? ' disabled' : ''}>${q && q.zustand === 'laeuft' ? IC.dreh() : IC.update()}Jetzt prüfen</button>${text ? `<span class="info-notiz ${cls}" role="status">${text}</span>` : ''}</div>`;
  }

  function oeffneInfo(id) {
    S.info = id || 'alle';
    const ebene = $('info-ebene');
    if (ebene.querySelector('.info.raus')) ebene.replaceChildren(); // gerade beim Schließen: neu aufbauen
    ebene.hidden = false;
    renderInfo();
    const aside = ebene.querySelector('.info');
    if (aside) aside.focus();
    const ziel = id && ebene.querySelector(`[data-anleitung="${id}"]`);
    if (ziel) ziel.scrollIntoView({ block: 'start' });
  }
  function schliesseInfo() {
    const ebene = $('info-ebene'), aside = ebene.querySelector('.info');
    S.info = null;
    if (aside && !reduziert.matches) {
      aside.classList.add('raus');
      setTimeout(() => { if (!S.info) { ebene.hidden = true; ebene.replaceChildren(); } }, 240);
    } else { ebene.hidden = true; ebene.replaceChildren(); }
    $('k-info').focus();
  }

  function infoTeile() {
    const st = S.status || {}, w = S.workflows || {}, u = S.update || {}, us = u.status || {};
    const jetzt = Date.now();
    const neu = u.neueste && u.neueste.version && vergleiche(u.neueste.version, u.installiert) > 0;
    const kv = (liste) => `<dl class="kv">${liste.map(([k, v, cls]) => `<div class="kv-z"><dt>${k}</dt><dd class="${cls || ''}">${v}</dd></div>`).join('')}</dl>`;

    // Updates
    let upd = kv([
      ['Installiert', esc(u.installiert || '–')],
      ['Neueste', u.neueste && u.neueste.version ? (neu ? `${esc(u.neueste.version)} · erschienen am ${u.neueste.veroeffentlicht ? datum(u.neueste.veroeffentlicht) : '–'}` : `${esc(u.neueste.version)} – auf dem neuesten Stand`) : (u.neueste && u.neueste.fehler ? 'nicht abrufbar' : 'noch nicht geprüft'), neu ? 'laeuft' : 'ok'],
      ['Geprüft', u.neueste && u.neueste.geprueft ? `${tm(u.neueste.geprueft) === tm(jetzt) ? 'heute' : tm(u.neueste.geprueft)} ${hm(u.neueste.geprueft)} bei GitHub · alle 6 Std.` : '–'],
      ['Runner', `${st.version ? 'actions-runner ' + esc(st.version) : '–'} · aktualisiert sich selbst`],
    ]);
    upd += pruefKnopf(u, us, neu);
    if (neu && u.neueste.notizen && u.neueste.notizen.length) upd += `<div class="upd-neu"><div class="upd-neu-titel">Neu in ${esc(u.neueste.version)}</div><ul>${u.neueste.notizen.map(n => `<li>${esc(n)}</li>`).join('')}</ul><a href="${esc(u.neueste.url || `https://github.com/${REPO}/releases`)}" rel="noopener" target="_blank">Alle Änderungen auf GitHub ↗</a></div>`;
    if (us.zustand === 'laeuft' || us.zustand === 'fehler') {
      const nr = us.schritt || 1;
      const zeilen = UPDATE_SCHRITTE.map((s, i) => {
        if (us.zustand === 'fehler') { const f = i + 1 === nr; const fertig = i + 1 < nr; return `<li class="${fertig ? '' : f ? '' : 'offen'}">${fertig ? IC.ok(16) : f ? `<span class="fehler">${IC.x(16)}</span>` : IC.offen()}<span>${s[0]}</span><span class="upd-zusatz">${f ? esc(us.meldung || '') : ''}</span></li>`; }
        return `<li class="${i + 1 === nr ? 'aktiv' : i + 1 > nr ? 'offen' : ''}">${i + 1 < nr ? `<span class="ok">${IC.ok(16)}</span>` : i + 1 === nr ? IC.dreh() : IC.offen()}<span>${s[0]}</span><span class="upd-zusatz">${i + 1 < nr ? s[1] : i + 1 === nr ? 'läuft …' : ''}</span></li>`;
      }).join('') + (us.zustand === 'fehler' ? `<li><span class="ok">${IC.ok(16)}</span><span>Version ${esc(u.installiert)} wiederhergestellt</span><span class="upd-zusatz">läuft wieder</span></li>` : '');
      upd += `<ol class="upd-schritte" aria-live="polite">${zeilen}</ol>`;
    }
    if (us.zustand === 'fehler') upd += `<div class="hinweis fehler">${IC.x(15)}<div>Update fehlgeschlagen <span>– ${esc(us.meldung || 'die neue Version hat nach dem Neustart nicht geantwortet')}. Version ${esc(u.installiert)} wurde automatisch wiederhergestellt. Details: <code class="inl">journalctl -u runner-monitor-update -n 50</code></span></div></div>`;
    if (us.zustand === 'erfolg' && jetzt - ms(us.zeit) < 3600000) upd += `<div class="hinweis ok">${IC.ok(15)}<div>Aktualisiert auf ${esc(u.installiert)} <span>– um ${hm(us.zeit)}. Dienst läuft, alle Daten kommen an.</span></div></div>`;
    if (neu && us.zustand !== 'laeuft') upd += `<div class="upd-aktion"><button type="button" class="knopf primaer gross" data-aktion="update-starten">${IC.herunter()}${us.zustand === 'fehler' ? 'Erneut versuchen' : `Jetzt auf ${esc(u.neueste.version)} aktualisieren`}</button><p class="info-notiz">Dauert etwa eine Minute. Der Monitor ist dabei kurz nicht erreichbar, der Runner und laufende Jobs arbeiten weiter.</p></div>`;
    upd += `<label class="upd-auto"><input type="checkbox" data-aktion="update-auto" ${u.auto ? 'checked' : ''}>Automatisch aktualisieren – nachts um 3 Uhr, nur wenn kein Job läuft</label>`;

    const t = RM.thema();
    const modi = [['system', 'Automatisch'], ['hell', 'Hell'], ['dunkel', 'Dunkel']].map(([v, n]) => `<button type="button" class="seg-knopf" data-aktion="thema" data-thema="${v}" aria-pressed="${t === v}">${n}</button>`).join('');

    const anl = anleitungen().map(a => {
      const offen = S.info === a.id;
      return `<div class="anl"><button type="button" class="anl-kopf" data-aktion="anleitung" data-anleitung="${a.id}" aria-expanded="${offen}">${IC.chev(offen)}<span class="anl-titel">${a.titel}</span>${a.aktiv ? `<span class="pill ${a.cls || 'warn'}">jetzt aktiv</span>` : ''}</button>${offen ? `<p class="anl-wann">${a.wann}</p><ol class="anl-schritte">${a.schritte.map(([text, code]) => `<li><span>${esc(text)}</span>${code ? `<pre class="code">${esc(code)}</pre>` : ''}</li>`).join('')}</ol>` : ''}</div>`;
    }).join('');

    const tage = w.tokenAblauf ? Math.ceil((ms(w.tokenAblauf) - jetzt) / 86400000) : null;
    const kont = w.kontingent || {};
    const gh = kv([
      ['Organisation', esc(w.org || '–')],
      ['Token', w.abfrage === 'kein-token' ? 'nicht eingerichtet' : w.abfrage === 'token-ungueltig' ? 'ungültig oder abgelaufen' : 'hinterlegt, nur lesend', ['kein-token', 'token-ungueltig'].includes(w.abfrage) ? 'warn' : ''],
      ['Rechte', 'Actions, Metadata, Self-hosted runners – je Read-only' + (w.runnerGrund ? ` <span class="warn">(${esc(w.runnerGrund)})</span>` : '')],
      ['Ablauf', w.tokenAblauf ? `${datum(w.tokenAblauf)} (in ${tage} ${mehrzahl(tage, 'Tag', 'Tagen')})` : '–', tage != null && tage <= 14 ? 'warn' : ''],
      ['Letzte Abfrage', w.abfrage === 'kein-token' ? 'aus' : w.abfrage === 'ok' ? `${zeit(w.abgefragt)} · erfolgreich` : `fehlgeschlagen · letzte erfolgreiche ${w.abgefragt ? zeit(w.abgefragt) : '–'}`, w.abfrage !== 'ok' && w.abfrage !== 'kein-token' ? 'warn' : ''],
      ['Nächste Abfrage', '<span data-tick="naechste"></span>'],
      ['API-Kontingent', kont.limit ? `${zahl(kont.frei)} von ${zahl(kont.limit)} frei, Reset ${hm(kont.reset)}` : '–'],
      ['Token-Datei', '/etc/runner-monitor/github-token'],
    ]) + `<p class="info-notiz">Token oder Organisation ändern geht nur auf der VM, die Seite ist nur zum Anschauen. Das Skript fragt das Token verdeckt ab und startet die Dienste neu:</p><pre class="code">${esc(SKRIPT)} token</pre><p class="info-notiz">Schritt für Schritt: „Was tun, wenn …“ › <button type="button" class="link-knopf" data-aktion="info" data-anleitung="token">GitHub-Token einrichten oder erneuern</button></p>`;
    const ueber = kv([
      ['Version', esc(u.installiert || st.monitorVersion || '–')],
      ['Adresse', esc(location.host)],
      ['Dienst', 'runner-monitor (systemd, eigener Benutzer)'],
      ['Aktualisierung', 'Systemwerte jede Sekunde, GitHub alle 30 s'],
    ]);
    const issue = (vorlage) => `https://github.com/${REPO}/issues/new?template=${vorlage}&version=${encodeURIComponent(u.installiert || '')}&runner=${encodeURIComponent(st.version || '')}&browser=${encodeURIComponent(navigator.userAgent.slice(0, 120))}`;

    // Teile einzeln austauschen statt das ganze Blatt neu zu bauen: Sonst startet die Einblend-
    // Animation bei jeder Aktualisierung neu, Auswahl und Fokus gehen verloren.
    return {
      eyebrow: `${esc(st.vm || '')}${st.runner ? ' · ' + esc(st.runner) : ''}`,
      upd,
      modi: `<div class="info-zeile"><span class="mut">Modus</span><div class="segment" role="group" aria-label="Hell oder dunkel">${modi}</div></div><p class="info-notiz">„Automatisch“ folgt der Einstellung des Systems. Die Wahl gilt nur für diesen Browser.</p>`,
      anl,
      gh,
      ueber: `<p class="info-text">Live-Dashboard für den selbst gehosteten GitHub-Actions-Runner: Runner-Status, Auslastung, Prozesse, Platten, Workflows je Repository und Live-Log. Fehler und Hinweise erscheinen als Meldung in der Mitte der Kopfzeile, „Was tun?“ führt zur passenden Anleitung.</p>${ueber}<p class="info-text">Ersteller: Bamberger IT Services · <a class="verweis" href="https://bamberger-it-services.de" rel="noopener" target="_blank">bamberger-it-services.de</a><br>Quellcode und Doku: <a class="verweis" href="https://github.com/${REPO}" rel="noopener" target="_blank">github.com/${REPO}</a></p>`,
      issue: `<p class="info-text">Fehler und Wünsche landen als Issue im öffentlichen GitHub-Repository. Die Knöpfe öffnen eine vorbereitete Vorlage mit Version, Runner-Version und Browser.</p><div class="knopf-reihe"><a class="knopf" href="${issue('fehler.yml')}" rel="noopener" target="_blank">${IC.kaefer()}Fehler melden ↗</a><a class="knopf" href="${issue('idee.yml')}" rel="noopener" target="_blank">Idee vorschlagen ↗</a></div><p class="info-notiz">Vor dem Absenden prüfen: keine IP-Adressen, Rechnernamen, Tokens oder Passwörter in das Issue schreiben – das Repository ist öffentlich.</p>`,
    };
  }

  const INFO_GERUEST = `
      <div class="info-scrim" data-aktion="info-zu"></div>
      <aside class="info" role="dialog" aria-modal="true" aria-labelledby="info-titel" tabindex="-1">
        <div class="info-kopf">
          <div><div class="vm-eyebrow" data-teil="eyebrow"></div><h2 class="info-titel" id="info-titel">Info &amp; Hilfe</h2></div>
          <div class="knopf-reihe"><button type="button" class="knopf" data-aktion="abmelden">Abmelden</button><button type="button" class="knopf" data-aktion="info-zu">Schließen</button></div>
        </div>
        <div class="info-body">
          <section class="info-abschnitt"><h3 class="info-h">Updates</h3><div data-teil="upd"></div></section>
          <section class="info-abschnitt"><h3 class="info-h">Darstellung</h3><div data-teil="modi"></div></section>
          <section class="info-abschnitt"><h3 class="info-h">Was tun, wenn …</h3><div data-teil="anl"></div></section>
          <section class="info-abschnitt"><h3 class="info-h">GitHub-Verbindung</h3><div data-teil="gh"></div></section>
          <section class="info-abschnitt"><h3 class="info-h">Über diesen Monitor</h3><div data-teil="ueber"></div></section>
          <section class="info-abschnitt"><h3 class="info-h">Fehler gefunden oder Idee?</h3><div data-teil="issue"></div></section>
        </div>
      </aside>`;

  function renderInfo() {
    if (!S.info) return;
    const ebene = $('info-ebene');
    if (!ebene.querySelector('.info')) ebene.innerHTML = INFO_GERUEST;
    const teile = infoTeile();
    for (const [name, html] of Object.entries(teile)) {
      const el = ebene.querySelector(`[data-teil="${name}"]`);
      if (el && el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; }
    }
    tickInfo();
  }

  /* Werte, die sich jede Sekunde ändern, nur als Text setzen. */
  function tickInfo() {
    const el = $('info-ebene').querySelector('[data-tick="naechste"]'); if (!el) return;
    const w = S.workflows || {};
    el.textContent = w.naechste && w.abfrage !== 'kein-token' ? `in ${Math.max(0, Math.round((ms(w.naechste) - Date.now()) / 1000))} s (alle 30 s)` : '–';
  }

  /* ------------------------------------------------------------ Bedienung */
  document.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-aktion]'); if (!b) return;
    const a = b.dataset.aktion;
    if (a === 'info') oeffneInfo(b.dataset.anleitung);
    else if (a === 'info-zu') schliesseInfo();
    else if (a === 'anleitung') { S.info = S.info === b.dataset.anleitung ? 'alle' : b.dataset.anleitung; renderInfo(); }
    else if (a === 'thema') { RM.setzeThema(b.dataset.thema); renderModus(); renderInfo(); }
    else if (a === 'wf-offen') { S.wfOffen = !S.wfOffen; $('workflows').dataset.letzte = ''; renderWorkflows(); }
    else if (a === 'abmelden') { if (!DEMO) await RM.sende('/api/abmelden'); location.href = '/anmelden'; }
    else if (a === 'update-pruefen') {
      const g = S.update && S.update.neueste && S.update.neueste.geprueft;
      if (g && Date.now() - ms(g) < 60000) { S.pruefung = { zustand: 'frisch', bis: Date.now() + 5000 }; renderInfo(); return; }
      S.pruefung = { zustand: 'laeuft', start: Date.now() }; renderInfo();
      if (DEMO) { window.RM_DEMO.pruefen(); return; }
      const r = await RM.sende('/api/update/pruefen');
      if (!r.ok) { S.pruefung = { zustand: 'keine-antwort', bis: Date.now() + 30000 }; renderInfo(); }
    }
    else if (a === 'update-starten') {
      b.disabled = true;
      if (DEMO) { window.RM_DEMO.updateStarten(); return; }
      const r = await RM.sende('/api/update/starten');
      if (!r.ok) { b.disabled = false; b.insertAdjacentHTML('afterend', `<p class="info-notiz fehler">${esc(r.daten.fehler || 'Update konnte nicht gestartet werden.')}</p>`); }
    }
  });
  document.addEventListener('change', async (e) => {
    const el = e.target.closest('[data-aktion="update-auto"]'); if (!el) return;
    if (DEMO) { S.update = { ...S.update, auto: el.checked }; return; }
    await RM.sende('/api/update/auto', { an: el.checked });
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && S.info) schliesseInfo(); });
  $('k-modus').addEventListener('click', () => {
    const folgt = { system: 'hell', hell: 'dunkel', dunkel: 'system' }[RM.thema()];
    RM.setzeThema(folgt); renderModus(); renderInfo();
  });
  $('k-info').innerHTML = `${IC.info()}Info`;
  $('k-info').addEventListener('click', () => oeffneInfo('alle'));
  $('k-pause').addEventListener('click', umschaltenPause);
  /* Im Log hochscrollen hält das Mitlaufen an (neue Zeilen werden gesammelt), zurück nach
     unten läuft es wieder mit. Wegen column-reverse ist scrollTop unten 0 und oben negativ. */
  $('term').addEventListener('scroll', () => {
    const oben = Math.abs($('term').scrollTop) > 8;
    if (oben && !S.angehalten) { S.angehalten = true; S.hochgescrollt = true; renderPause(); }
    else if (!oben && S.angehalten && S.hochgescrollt) umschaltenPause();
  }, { passive: true });
  $('k-weiter').addEventListener('click', umschaltenPause);
  $('k-umbrechen').addEventListener('click', () => setzeUmbruch(true));
  $('k-abschneiden').addEventListener('click', () => setzeUmbruch(false));
  $('vm-icon').innerHTML = IC.server();
  renderModus(); renderPause(); renderKopf(); renderLeer();

  /* Sekundentakt: Uhr, Laufzeiten, „vor …“, Wachhund für die Verbindung */
  setInterval(() => {
    if (S.verbindung === 'verbunden' && S.letzteDaten && Date.now() - S.letzteDaten > 5000) setzeVerbindung('getrennt');
    renderKopf(); renderStatus(); renderWorkflows(); if (S.info) renderInfo();
  }, 1000);

  /* ------------------------------------------------------------ Verbindung */
  const DEMO = new URLSearchParams(location.search).has('demo');
  function verbinde() {
    const quelle = new EventSource('/events');
    for (const b of ['status', 'system', 'prozesse', 'platten', 'container', 'workflows', 'update', 'log']) {
      quelle.addEventListener(b, (e) => { try { empfange(b, JSON.parse(e.data)); } catch (f) { console.error(b, f); } });
    }
    quelle.onopen = () => setzeVerbindung('verbunden');
    quelle.onerror = () => {
      setzeVerbindung('getrennt');
      // Abgemeldet (z. B. Sitzung abgelaufen)? Dann zur Anmeldung.
      // Jede /api/-Adresse antwortet ohne Sitzung mit 401, mit Sitzung hier mit 404.
      fetch('/api/sitzung', { credentials: 'same-origin' }).then(r => { if (r.status === 401) location.href = '/anmelden'; }).catch(() => {});
    };
  }
  if (DEMO) {
    const s = document.createElement('script');
    s.src = '/static/demo.js';
    s.onload = () => window.RM_DEMO.start({ empfange, setzeVerbindung, S, renderKopf });
    document.head.appendChild(s);
  } else verbinde();
})();
