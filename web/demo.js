/* Runner-Monitor – Demo-Simulator. Nur mit ?demo aktiv: erzeugt dieselben Daten wie der Dienst,
   ohne Server. Alle Namen und Adressen sind erfunden (öffentliches Repository). */
'use strict';

window.RM_DEMO = (() => {
  const GiB = 1024 ** 3, GB = 1e9;
  const jetzt = () => Date.now() / 1000;
  const zufall = (a, b) => a + Math.random() * (b - a);
  // Versionen wie im Entwurf: installiert = Version des Servers (/api/health), verfügbar = nächste Minor-Version
  let INST = '0.0.0', NEU = '0.1.0';
  const naechste = (v) => { const t = v.split('.').map(Number); return `${t[0] || 0}.${(t[1] || 0) + 1}.0`; };
  let grund = '';  // ?grund=oom-kill: Ursache des gestoppten Dienstes (#68)
  let api, takt = 0, kerne = 8, zustand = 'job', gh = 'ok', upd = 'aktuell', verlaufS = 600, schritteLokal = false;
  let cpuSchnitt = 40, job = null, schrittNr = 1, zeilenImSchritt = 0, updSchritt = 0;
  const START = jetzt() - 3 * 86400 - 4 * 3600;
  const REPOS = [
    ['web-portal', true], ['api-dienst', true], ['dokumentation', false], ['infrastruktur', true],
    ['mobile-app', true], ['werkzeuge', false], ['datenimport', true], ['vorlagen', false],
  ];
  const JOB = {
    repo: 'web-portal', privat: true, workflow: 'CI', name: 'test', ref: { art: 'PR', name: '#142', titel: 'Suche im Kundenbereich' },
    schritte: ['Set up job', 'Checkout', 'Node einrichten', 'Abhängigkeiten', 'Lint', 'Tests', 'Build', 'Complete job'],
  };
  const AUSGABE = {
    Checkout: ['Syncing repository: beispiel-org/web-portal', '\u001b[36m[command]\u001b[0m/usr/bin/git checkout --progress --force refs/remotes/pull/142/merge', 'HEAD is now at 3f2a9c1 Merge into main'],
    'Node einrichten': ['Found in cache @ /opt/hostedtoolcache/node/22.11.0/x64', '\u001b[32m✓\u001b[0m node v22.11.0'],
    Abhängigkeiten: ['\u001b[36m[command]\u001b[0mnpm ci', 'added 812 packages in 14s', '\u001b[33mnpm warn\u001b[0m deprecated inflight@1.0.6'],
    Lint: ['\u001b[36m[command]\u001b[0mnpm run lint', '\u001b[1m✔ No ESLint warnings or errors\u001b[0m'],
    Tests: ['\u001b[2m RUN \u001b[0m v2.1.4 /home/runner/_work/web-portal', ' \u001b[32m✓\u001b[0m src/suche.test.ts \u001b[2m(24 tests)\u001b[0m \u001b[33m412ms\u001b[0m', ' \u001b[32m✓\u001b[0m src/konto.test.ts \u001b[2m(18 tests)\u001b[0m 288ms', ' \u001b[31m×\u001b[0m src/export.test.ts > CSV mit Umlauten \u001b[2m(flaky, 1 retry)\u001b[0m', ' \u001b[32m✓\u001b[0m src/export.test.ts \u001b[2m(9 tests)\u001b[0m 1.2s'],
    Build: ['\u001b[36m[command]\u001b[0mnpm run build', '\u001b[1m\u001b[34mvite\u001b[0m building for production...', '\u001b[32m✓\u001b[0m 1 204 modules transformed.', 'dist/assets/index-8f2c.js  \u001b[1m412.31 kB\u001b[0m'],
  };
  const PROZ = [['Runner.Worker', 'github-runner'], ['node vitest run', 'github-runner'], ['dockerd', 'root'], ['Runner.Listener', 'github-runner'], ['containerd', 'root'], ['python3 -m runner_monitor', 'runner-monitor'], ['systemd-journald', 'root'], ['sshd: verwaltung', 'root']];

  // Ein Schritt wie vom Server: {nr, von, name}; ?schritte=lokal = Liste von GitHub fehlt noch (Design 0.4.0)
  const schritt = (nr) => (schritteLokal ? { nr, von: null, name: '' } : { nr, von: JOB.schritte.length, name: JOB.schritte[nr - 1] });
  const status = () => {
    const t = jetzt();
    const dienst = zustand === 'gestoppt' ? { zustand: 'gestoppt', seit: t - 760, grund: grund || null } : { zustand: 'aktiv', seit: START + 3600, grund: null };
    const github = zustand === 'offline' || zustand === 'gestoppt' ? { zustand: 'offline', seit: t - 1240 } : gh === 'kein-token' ? { zustand: 'unbekannt', seit: null } : { zustand: 'online', seit: null };
    return {
      vm: 'runner-vm', runner: 'runner-vm-01', eingerichtet: true, labels: ['self-hosted', 'linux', 'x64', 'docker'], version: '2.329.0', monitorVersion: INST,
      dienst, github,
      job: ['job', 'platte', 'volllast', 'getrennt'].includes(zustand) && job ? { ...JOB, schritte: schritteLokal ? [] : JOB.schritte, start: job.start, schritt: schritt(schrittNr) } : null,
      letzteJobs: [
        { repo: 'api-dienst', workflow: 'CI', name: 'build', ergebnis: 'erfolg', dauer: 274, ende: t - 860 },
        { repo: 'web-portal', workflow: 'Deploy', name: 'staging', ergebnis: 'fehler', dauer: 92, ende: t - 2400 },
        { repo: 'dokumentation', workflow: 'Pages', name: 'build', ergebnis: 'erfolg', dauer: 41, ende: t - 5100 },
        { repo: 'infrastruktur', workflow: 'Plan', name: 'terraform', ergebnis: 'abgebrochen', dauer: 18, ende: t - 9000 },
        { repo: 'api-dienst', workflow: 'CI', name: 'test', ergebnis: 'erfolg', dauer: 336, ende: t - 12600 },
      ],
    };
  };
  const workflows = () => {
    const t = jetzt(), aktiv = ['job', 'platte', 'volllast'].includes(zustand);
    const fehler = ['nicht-erreichbar', 'kein-token'].includes(gh) ? gh : 'ok';
    return {
      org: 'beispiel-org', abfrage: fehler, abgefragt: fehler === 'ok' ? t - (takt % 30) : t - 380, versucht: t - (takt % 30), naechste: t + 30 - (takt % 30),
      tokenAblauf: gh === 'ablauf' ? t + 9 * 86400 : t + 74 * 86400,
      kontingent: { limit: 5000, frei: 4812, reset: t + 2400 },
      repos: REPOS.map(([name, privat], i) => ({ name, privat, laeuft: aktiv && i === 0 ? 1 : 0, wartet: zustand === 'gestoppt' ? (i < 3 ? 2 - (i > 0) : 0) : (aktiv && i === 1 ? 1 : 0) })),
      fehler: '', runnerGrund: '',
    };
  };
  const update = () => {
    const t = jetzt();
    const neueste = { geprueft: t - 3100, version: upd === 'aktuell' ? INST : NEU, veroeffentlicht: t - 2 * 86400, url: 'https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/releases', notizen: ['Mehrere Runner auf einer VM', 'Log-Suche im Live-Log', 'Kleinere Korrekturen in der Einrichtung'],
      aenderungen: upd === 'aktuell' ? [] : [
        { version: NEU, url: 'https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/releases', neu: ['Log-Suche im Live-Log', 'Kleinere Korrekturen in der Einrichtung'], einmalig: '' },
        { version: INST.split('.').map((x, i) => i === 2 ? Number(x) + 1 : x).join('.'), url: 'https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/releases', neu: ['Runner-Dienst übersteht Speichermangel', 'Grund für gestoppten Dienst im Dashboard'], einmalig: 'Empfohlen: `sudo /opt/runner-monitor/aktuell/einrichten.sh runner` einmal ausführen.' },
      ] };
    const st = upd === 'laeuft' ? { zustand: 'laeuft', schritt: Math.min(5, 1 + Math.floor(updSchritt / 4)), version: NEU, zeit: t - updSchritt }
      : upd === 'fehler' ? { zustand: 'fehler', schritt: 5, version: NEU, zeit: t - 300, meldung: 'die neue Version hat nach dem Neustart nicht geantwortet' } : {};
    return { installiert: INST, neueste, status: st, auto: false };
  };
  const platten = () => {
    const frei = zustand === 'platte' ? 18.4 * GB : 61.2 * GB;
    return [
      { pfad: '/', gesamt: 128 * GB, frei, belegt: 128 * GB - frei, schwelleFrei: 25 * GB },
      { pfad: '/var/lib/docker', gesamt: 256 * GB, frei: 171 * GB, belegt: 85 * GB },
    ];
  };

  /* Seit #92 (E-19, additiv): zusätzlich runner[] und meldungen[] wie GET /api/zustand bzw. die
     Ereignisse „runner“ und „meldungen“; die Oberfläche nutzt sie seit #94 (Reiter, Meldungen mit Runner).
     ?runner=N (1 bis 5, Design 0.8.0): 2 = + Forgejo-Runner (Grundüberwachung), 3 = + unbekannter Runner
     (Grundüberwachung, gestoppt bei ?zustand=gestoppt), 4 = + Gitea-Runner (bereit), 5 = + GitLab-Runner
     (offline beim Server). Die Runner ab 4 zeigen vorweg, wie ein Dienst mit Jobs aussieht (Anbindung folgt mit #93/#99). */
  let runnerAnzahl = 1;
  const FAEHIG_VOLL = { status: true, jobs: true, schritte: true, logs: true, updates: false };
  const FAEHIG_GRUND = { status: true, jobs: false, schritte: false, logs: true, updates: false };
  // ?faehig=teilweise (Design 0.8.0 › „Teilweise · Job ohne Schritte“): runner-vm-01 liefert Jobs, aber keine Schritte
  const FAEHIG_TEIL = { status: true, jobs: true, schritte: false, logs: true, updates: false };
  let faehigWahl = 'voll';
  // ?forgejo=angebunden (Design 0.8.0 › „Verbindungen · GitHub und Forgejo“): runner-vm-02 mit Jobs statt Grundüberwachung
  // ?forgejo=unsichtbar (#145): angebunden, aber der Runner fehlt in den Runner-Listen, die das Token lesen darf
  let forgejoAngebunden = false, forgejoUnsichtbar = false;
  // ?anbieter=kein-token|nicht-erreichbar|token-ungueltig (#123): Abfrage der Runner ab runner-vm-02 (Forgejo, Gitea, GitLab) mit Fehler;
  // ?anbieteralter=N: Alter ihres letzten guten Stands in Sekunden (Standard 900 = veraltet; 200 = Hinweis mit Alter)
  let anbieterAbfrage = 'ok', anbieterAlter = 900;
  // Grundüberwachung (#95): Dienst mit NRestarts (neustarts) und InactiveEnterTimestamp (letzterStopp) wie runner.dienst_status
  const grundRunner = (id, name, dienst, unit, einstufung, stand, dienstZustand, mehr = {}) => {
    const t = jetzt(), aktiv = dienstZustand === 'aktiv';
    const dienstSt = aktiv ? { zustand: 'aktiv', seit: mehr.seit || START + 7200, grund: null, neustarts: mehr.neustarts || 0, letzterStopp: mehr.letzterStopp || null }
      : { zustand: 'gestoppt', seit: t - 760, grund: grund || null, neustarts: mehr.neustarts || 0, letzterStopp: t - 760 };
    return {
      id, name, dienst, server: null, org: null, unit, stand, einstufung, version: null, labels: [], faehig: FAEHIG_GRUND,
      status: { zustand: aktiv ? 'aktiv' : 'gestoppt', dienst: dienstSt, beimDienst: null },
      job: null, letzteJobs: null, jobsJeRepository: null, log: { art: 'journal', unit },
    };
  };
  // Runner mit Jobs und Schritten, aber ohne laufenden Job (Zustand bereit oder offline beim Server)
  const vollRunner = (id, dienst, unit, labels, offline, unsichtbar = false) => {
    const t = jetzt(), w = workflows();
    const beimDienst = unsichtbar ? { zustand: 'unbekannt', seit: null, sichtbar: false } : offline ? { zustand: 'offline', seit: START + 86400 } : { zustand: 'online', seit: null };
    return {
      id, name: id, dienst, server: dienst === 'gitlab' ? 'https://gitlab.example.org' : 'https://git.example.org', org: dienst === 'gitlab' ? null : 'beispiel-org', unit, stand: 'angebunden', einstufung: 'voll',
      version: dienst === 'gitea' ? 'act_runner 0.2.11' : dienst === 'forgejo' ? 'Forgejo Runner 9.1' : 'GitLab Runner 17.5', labels, faehig: FAEHIG_VOLL,
      status: { zustand: unsichtbar ? 'aktiv' : offline ? 'offline' : 'bereit', dienst: { zustand: 'aktiv', seit: START + 9000, grund: null }, beimDienst },
      job: null, letzteJobs: [{ repo: 'datenimport', workflow: 'Import', name: 'nachts', ergebnis: 'erfolg', dauer: 128, ende: t - 720 }],
      jobsJeRepository: { ...w, abfrage: anbieterAbfrage, abgefragt: anbieterAbfrage === 'ok' ? t - (takt % 30) : t - anbieterAlter, naechste: t + 30 - (takt % 30), tokenAblauf: null,  // Forgejo, Gitea und GitLab melden kein Ablaufdatum (E-18: nur, was der Dienst liefert)
        kontingent: {}, repos: anbieterAbfrage === 'kein-token' ? [] : REPOS.map(([name, privat]) => ({ name, privat, laeuft: 0, wartet: 0 })),
        runnerGrund: unsichtbar ? 'Runner beim Dienst nicht sichtbar (globaler Runner? Token-Rechte)' : '' },
      log: { art: 'journal', unit },
    };
  };
  const runnerListeAlle = () => {
    const st = status(), w = workflows();
    const zust = st.dienst.zustand === 'gestoppt' ? 'gestoppt' : st.job ? 'job' : st.github.zustand === 'offline' ? 'offline' : 'bereit';
    const unit = 'actions.runner.beispiel-org.runner-vm-01.service';
    const teil = faehigWahl === 'teilweise';
    // Wie der Server (anbieter.eintrag): ohne Fähigkeit „schritte“ kein Schritt und keine Schrittliste
    const job = st.job && teil ? { ...st.job, schritt: null, schritte: [] } : st.job;
    const liste = [{
      id: 'runner-vm-01', name: st.runner, dienst: 'github', server: 'https://github.com', org: w.org, unit,
      stand: gh === 'kein-token' ? 'offen' : 'angebunden', einstufung: 'voll', version: st.version, labels: st.labels, faehig: teil ? FAEHIG_TEIL : FAEHIG_VOLL,
      status: { zustand: zust, dienst: st.dienst, beimDienst: st.github }, job, letzteJobs: st.letzteJobs, jobsJeRepository: w,
      log: { art: 'seiten', unit },
    }];
    if (runnerAnzahl >= 2) liste.push(forgejoAngebunden ? vollRunner('runner-vm-02', 'forgejo', 'forgejo-runner.service', forgejoUnsichtbar ? [] : ['ubuntu-latest'], false, forgejoUnsichtbar)
      : grundRunner('runner-vm-02', 'runner-vm-02', 'forgejo', 'forgejo-runner.service', 'voll', 'grund', 'aktiv', { neustarts: 2, letzterStopp: jetzt() - 26 * 3600 }));
    if (runnerAnzahl >= 3) liste.push(grundRunner('buildagent', 'buildagent', 'unbekannt', 'buildagent.service', 'unbekannt', 'grund', zustand === 'gestoppt' ? 'gestoppt' : 'aktiv',
      { seit: jetzt() - (6 * 86400 + 4 * 3600 + 900) }));
    if (runnerAnzahl >= 4) liste.push(vollRunner('runner-vm-03', 'gitea', 'gitea-runner.service', ['linux', 'arm64'], false));
    if (runnerAnzahl >= 5) liste.push(vollRunner('runner-vm-04', 'gitlab', 'gitlab-runner.service', ['docker', 'shell'], true));
    if (neuGefunden) liste.push(grundRunner(NEU_ID(), NEU_ID(), 'gitea', 'act_runner-2.service', 'teil', 'offen', 'aktiv'));
    return liste;
  };
  // Zuordnung aus der Oberfläche (Info › Runner): Namen und Dienst überschreiben, ignorierte Runner fehlen in runner[]
  const runnerListe = () => runnerListeAlle().filter((r) => (zuordn[r.id] || {}).stand !== 'ignoriert').map((r) => {
    const z = zuordn[r.id] || {};
    return { ...r, ...(z.name ? { name: z.name } : {}), ...(z.dienst ? { dienst: z.dienst } : {}), ...(z.stand === 'grund' ? { stand: 'grund' } : {}) };
  });

  /* Info › Runner (#97): Funde wie GET /api/einrichtung/runner, im Speicher. „Neu erkennen“ findet beim ersten Mal
     einen neuen Gitea-Runner (Design: „1 neuer Runner gefunden“), danach „Keine Änderung“. */
  let neuGefunden = false, erkennungen = 0, erkZeit = jetzt() - 7 * 60;
  const zuordn = {};
  const NEU_ID = () => (runnerAnzahl >= 4 ? 'runner-vm-05' : 'runner-vm-03');
  const GRAD = { 'runner-vm-01': 'sicher', 'runner-vm-02': 'sicher', buildagent: 'unklar', 'runner-vm-03': 'sicher', 'runner-vm-04': 'wahrscheinlich', 'runner-vm-05': 'sicher' };
  const SERVER_FUND = { github: 'https://github.com/beispiel-org', forgejo: 'https://git.example.org', gitea: 'https://git.example.org:3000', gitlab: 'https://gitlab.example.org' };
  function fundVon(r) {
    const z = zuordn[r.id] || {}, primaer = r.id === 'runner-vm-01', mitAdapter = ['forgejo', 'gitea', 'gitlab'].includes(r.dienst);
    return {
      id: r.id, name: z.name || r.name, dienst: z.dienst || r.dienst, server: SERVER_FUND[r.dienst] || r.server || null, version: r.version, grad: GRAD[r.id] || 'unklar',
      merkmale: [`systemd-Unit ${r.unit}`], einstufung: r.einstufung, stand: z.stand || r.stand, unit: r.unit, faehig: r.faehig, aktiv: true, grund: null,
      zuordnung: { ...z }, primaer, anbindung: primaer ? 'github' : r.stand === 'angebunden' ? 'angebunden' : mitAdapter ? 'ohne-server' : 'ohne-adapter',
    };
  }
  function funde() {
    return JSON.parse(JSON.stringify({ zeit: erkZeit, runner: runnerListeAlle().map(fundVon), auftrag: { erkennung: false, zuordnung: false } }));
  }
  function erkennen() {
    erkennungen++;
    if (erkennungen === 1) neuGefunden = true;
    return new Promise((ok) => setTimeout(() => { erkZeit = jetzt(); if (api) runnerSenden(); ok(); }, 1600));
  }
  function zuordnung(eintraege) {
    for (const e of eintraege) {
      const z = zuordn[e.id] || (zuordn[e.id] = {});
      if ('stand' in e) { if (e.stand === null) delete z.stand; else z.stand = e.stand; }
      for (const k of ['dienst', 'name', 'unit', 'log']) if (k in e) { if (e[k] === null) delete z[k]; else z[k] = e[k]; }
    }
    if (api) runnerSenden();
  }
  const meldungenListe = (liste) => {
    const M = [];
    for (const r of liste) {
      const b = { runner: r.id, dienst: r.dienst }, d = r.status.dienst, j = r.jobsJeRepository;
      if (d.zustand === 'gestoppt') M.push({ id: 'gestoppt', stufe: 'fehler', ...b, daten: { seit: d.seit, grund: d.grund } });
      if (r.status.beimDienst && r.status.beimDienst.zustand === 'offline' && d.zustand === 'aktiv') M.push({ id: 'offline', stufe: 'fehler', ...b, daten: { seit: r.status.beimDienst.seit } });
      if (j && j.abfrage === 'nicht-erreichbar') M.push({ id: 'abfrage', stufe: 'warn', ...b, daten: { abfrage: j.abfrage, abgefragt: j.abgefragt, naechste: j.naechste } });
      if (j && j.abfrage === 'kein-token') M.push({ id: 'token', stufe: 'neutral', ...b, daten: { abfrage: j.abfrage } });
      if (j && j.tokenAblauf && j.tokenAblauf - jetzt() <= 14 * 86400) M.push({ id: 'token', stufe: 'warn', ...b, daten: { tokenAblauf: j.tokenAblauf } });
    }
    for (const p of platten()) if (p.schwelleFrei && p.frei < p.schwelleFrei) M.push({ id: 'platte', stufe: 'warn', runner: null, dienst: null, daten: { pfad: p.pfad, frei: p.frei, schwelleFrei: p.schwelleFrei } });
    const rang = { fehler: 0, warn: 1, neutral: 2 };
    return M.sort((a, b) => rang[a.stufe] - rang[b.stufe]);
  };
  function runnerSenden() {
    const liste = runnerListe();
    api.empfange('runner', liste);
    api.empfange('meldungen', meldungenListe(liste));
  }

  /* Journal je Unit (#95) wie /events?journal=<id>: erst der Stand („neu“), dann neue Zeilen. Zeilen von
     systemd ohne Vorsatz, sonst „kennung[pid]: text“ wie runner_monitor/journal.py. Alle Werte erfunden. */
  let journalId = null;
  const JOURNAL = {
    buildagent: { unit: 'buildagent.service', start: 'Started buildagent.service - Build Agent.', ende: 'Stopped buildagent.service - Build Agent.', zeilen: [
      [252, 'buildagent[2187]: connected to 192.0.2.40:443'], [188, 'buildagent[2187]: task 8812 received'],
      [187, 'buildagent[2187]: pulling registry.example.org/ci/node:22'], [171, 'buildagent[2187]: container 3f9a2c started'],
      [96, 'buildagent[2187]: container 3f9a2c exited (0) after 1m15s'], [95, 'buildagent[2187]: task 8812 done'],
      [40, 'buildagent[2187]: waiting for work'], [10, 'buildagent[2187]: heartbeat ok']], takt: 'buildagent[2187]: heartbeat ok' },
    'runner-vm-02': { unit: 'forgejo-runner.service', start: 'Started forgejo-runner.service - Forgejo Runner.', ende: 'Stopped forgejo-runner.service - Forgejo Runner.', zeilen: [
      [300, 'forgejo-runner[1432]: level=info msg="Starting runner daemon"'], [298, 'forgejo-runner[1432]: level=info msg="runner: runner-vm-02, with version: v9.1.0"'],
      [297, 'forgejo-runner[1432]: level=info msg="[poller 0] launched"'], [60, 'forgejo-runner[1432]: level=info msg="task 214 repo is beispiel-org/werkzeuge"'],
      [20, 'forgejo-runner[1432]: level=info msg="task 214 finished"']], takt: 'forgejo-runner[1432]: level=debug msg="[poller 0] fetch: no task"' },
  };
  function journal(id) {
    journalId = id || null;
    if (!api) return;
    const j = JOURNAL[journalId], t = jetzt();
    if (!journalId) {  // zurück zur Ausgabe der Schritte: wie ein neuer Strom mit Stand
      api.empfange('log', { neu: true, ereignisse: job ? [{ art: 'start', zeit: job.start, repo: JOB.repo, workflow: JOB.workflow, name: JOB.name }] : [], zeilen: job ? [{ art: 'schritt', zeit: t - 5, ...schritt(schrittNr) }] : [] });
      return;
    }
    if (!j) { api.empfange('journal', { unit: null, neu: true, zeilen: [], ereignisse: [] }); return; }
    // gestoppt (?zustand=gestoppt): seit 760 s still, davor wie sonst
    const gestoppt = journalId === 'buildagent' && zustand === 'gestoppt', vorher = gestoppt ? 770 : 0;
    const zeilen = [{ zeit: t - 310 - vorher, text: j.start }, ...j.zeilen.map(([vorS, text]) => ({ zeit: t - vorS - vorher, text }))];
    const ereignisse = [{ art: 'dienst-gestartet', zeit: t - 310 - vorher }];
    if (gestoppt) { zeilen.push({ zeit: t - 760, text: j.ende }); ereignisse.push({ art: 'dienst-gestoppt', zeit: t - 760 }); }
    api.empfange('journal', { unit: j.unit, neu: true, zeilen, ereignisse });
  }
  function journalTakt() {
    const j = JOURNAL[journalId];
    if (!j || (journalId === 'buildagent' && zustand === 'gestoppt')) return;
    api.empfange('journal', { unit: j.unit, zeilen: [{ zeit: jetzt(), text: j.takt }], ereignisse: [] });
  }

  function system(erst) {
    const ziel = zustand === 'gestoppt' || zustand === 'offline' ? 4 : zustand === 'volllast' ? 96 : job ? 58 : 6;
    cpuSchnitt += (ziel - cpuSchnitt) * 0.25 + zufall(-4, 4);
    cpuSchnitt = Math.max(1, Math.min(100, cpuSchnitt));
    const k = Array.from({ length: kerne }, () => Math.max(0, Math.min(100, cpuSchnitt + zufall(-22, 22))));
    const ram = (zustand === 'volllast' ? 29 : job ? 11.4 : 4.1) * GiB + zufall(-0.2, 0.2) * GiB;
    const d = { zeit: jetzt(), kerne: k, cpu: k.reduce((a, b) => a + b, 0) / kerne, last: [cpuSchnitt / 100 * kerne * 0.9, cpuSchnitt / 100 * kerne * 0.8, cpuSchnitt / 100 * kerne * 0.7], ram: { belegt: ram, gesamt: 32 * GiB }, swap: { belegt: 0.2 * GiB, gesamt: 4 * GiB }, start: START };
    // Netz: beim Job lädt der Runner Images und Pakete, im Leerlauf nur ein paar KB/s (Werte wie im Design 0.3.0)
    const voll = zustand === 'volllast', busy = voll || !!job || ['job', 'platte'].includes(zustand);
    const rx = voll ? zufall(30e6, 58e6) : busy ? zufall(1.6e6, 3.1e6) : zufall(2.6e3, 6e3);
    d.netz = { empfangen: Math.round(rx), gesendet: Math.round(rx * (busy ? zufall(0.09, 0.13) : zufall(0.18, 0.3))), schnittstellen: ['eth0'] };
    if (erst) d.verlauf = verlauf(voll, busy);
    return d;
  }
  /* 10 Minuten Vorgeschichte wie im Design: erst Ruhe, dann startet der Job (Images laden = Netzspitze). */
  function verlauf(voll, busy) {
    const cpu = [], ram = [], netz = [];
    for (let i = 0; i < 600; i++) {
      let c, r, rx;
      if (busy) {
        const zr = voll ? 28.9 : 11.5;
        if (i < 170) { c = zufall(2, 8); r = 4.2; rx = zufall(2e3, 7e3); }
        else if (i < 200) { const k = (i - 170) / 30; c = 8 + k * (voll ? 82 : 47); r = 4.2 + k * (zr - 4.2); rx = voll ? zufall(62e6, 86e6) : zufall(8e6, 13.5e6); }
        else { c = voll ? ((i % 97) < 6 ? zufall(60, 75) : zufall(85, 99)) : zufall(45, 68); r = zr + zufall(-0.25, 0.25); rx = voll ? zufall(30e6, 58e6) : zufall(1.6e6, 3.1e6); }
        if (i === 186) rx = voll ? 89.3e6 : 14.8e6;
      } else {
        c = (i % 143) < 4 ? zufall(12, 20) : zufall(1.5, 7); r = 4.2 + zufall(-0.04, 0.04);
        rx = (i % 151) < 3 ? zufall(12e3, 18e3) : zufall(2.6e3, 6e3);
      }
      cpu.push(c); ram.push(r / 32 * 100); netz.push([Math.round(rx), Math.round(rx * (busy && i >= 170 ? zufall(0.02, 0.14) : zufall(0.2, 0.3)))]);
    }
    // ?verlauf=120: Monitor wurde vor 2 Minuten neu gestartet (Design 0.4.0, Option „Verlauf“)
    const n = verlaufS;
    return { cpu: cpu.slice(-n), ram: ram.slice(-n), netz: netz.slice(-n), start: jetzt() - n };
  }
  // Ohne Job wie im Design: der Listener wartet, sonst ist es ruhig
  const PROZ_RUHE = [[3091, 'github-runner', 0.7, 3.5, '/opt/actions-runner/bin/Runner.Listener run --startuptype service'], [3725, 'runner-monitor', 0.5, 2.0, 'python3 -m runner_monitor'], [2774, 'root', 0.3, 4.6, '/usr/bin/dockerd -H fd:// --containerd=/run/containerd/containerd.sock'], [3408, 'root', 0.1, 2.7, '/usr/bin/containerd'], [402, 'root', 0.0, 0.2, '/usr/lib/systemd/systemd-journald'], [655, 'root', 0.0, 0.1, 'sshd: /usr/sbin/sshd -D [listener]']];
  const prozesse = () => (job ? PROZ.slice(0, 6).map(([befehl, benutzer], i) => ({ pid: 2140 + i * 317, benutzer, cpu: Math.max(0.1, cpuSchnitt * (0.9 - i * 0.16) * zufall(0.8, 1.2)), ram: Math.max(0.1, 7 - i + zufall(-0.5, 0.5)), befehl }))
    : PROZ_RUHE.filter(p => zustand !== 'gestoppt' || !p[4].includes('Runner.')).map(([pid, benutzer, cpu, ram, befehl]) => ({ pid, benutzer, cpu: cpu > 0.05 ? cpu * zufall(0.85, 1.12) : cpu, ram, befehl })));

  function logTakt() {
    if (!job || !['job', 'platte', 'volllast'].includes(zustand)) return;
    const name = JOB.schritte[schrittNr - 1];
    const zeilen = AUSGABE[name] || [`\u001b[2m${name}\u001b[0m`];
    if (zeilenImSchritt < zeilen.length) { api.empfange('log', { zeilen: [{ art: 'zeile', zeit: jetzt(), text: zeilen[zeilenImSchritt] }] }); zeilenImSchritt++; return; }
    if (schrittNr >= JOB.schritte.length) {
      api.empfange('log', { ereignisse: [{ art: 'ende', zeit: jetzt(), repo: JOB.repo, workflow: JOB.workflow, name: JOB.name, ergebnis: 'erfolg', dauer: jetzt() - job.start }] });
      job = null; setTimeout(() => { if (zustand === 'job') neuerJob(); }, 6000); return;
    }
    schrittNr++; zeilenImSchritt = 0;
    api.empfange('log', { zeilen: [{ art: 'schritt', zeit: jetzt(), ...schritt(schrittNr) }] });
    api.empfange('status', status()); runnerSenden();
  }
  function neuerJob() {
    job = { start: jetzt() - 95 }; schrittNr = 3; zeilenImSchritt = 0;
    api.empfange('log', { neu: true, ereignisse: [{ art: 'start', zeit: jetzt() - 95, repo: JOB.repo, workflow: JOB.workflow, name: JOB.name }], zeilen: [{ art: 'schritt', zeit: jetzt() - 60, ...schritt(3) }] });
    api.empfange('status', status()); runnerSenden();
  }

  function alles(erst) {
    api.empfange('status', status());
    api.empfange('system', system(erst));
    api.empfange('prozesse', prozesse());
    api.empfange('platten', platten());
    api.empfange('workflows', workflows());
    api.empfange('update', update());
    runnerSenden();
  }

  function leiste() {
    const box = document.getElementById('demo'); box.hidden = false;
    const gruppe = (id, werte, aktuell, setze) => {
      const el = document.getElementById(id);
      el.innerHTML = werte.map(([v, n]) => `<button type="button" class="seg-knopf" data-wert="${v}" aria-pressed="${v === aktuell}">${n}</button>`).join('');
      el.addEventListener('click', (e) => {
        const b = e.target.closest('[data-wert]'); if (!b) return;
        el.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
        setze(b.dataset.wert);
      });
    };
    gruppe('demo-zustand', [['job', 'Job'], ['leerlauf', 'Leerlauf'], ['volllast', 'Volllast'], ['gestoppt', 'Gestoppt'], ['offline', 'Offline'], ['platte', 'Platte knapp'], ['getrennt', 'Getrennt']], zustand, (v) => {
      zustand = v;
      if (v === 'getrennt') { api.setzeVerbindung('getrennt'); return; }
      if (['job', 'platte', 'volllast'].includes(v)) { if (!job) neuerJob(); } else if (job) { job = null; api.empfange('log', { neu: true }); }
      alles(false);
    });
    gruppe('demo-github', [['ok', 'GitHub ok'], ['kein-token', 'Kein Token'], ['nicht-erreichbar', 'Nicht erreichbar'], ['ablauf', 'Token läuft ab']], gh, (v) => { gh = v; alles(false); });
    gruppe('demo-update', [['aktuell', 'Aktuell'], ['verfuegbar', 'Update da'], ['laeuft', 'Update läuft'], ['fehler', 'Update Fehler']], upd, (v) => { upd = v; updSchritt = 0; api.empfange('update', update()); });
    gruppe('demo-kerne', [['4', '4 Kerne'], ['8', '8'], ['16', '16']], String(kerne), (v) => { kerne = Number(v); api.empfange('system', system(false)); });
  }

  function start(a) {
    api = a;
    fetch('/api/health').then(r => (r.ok ? r.json() : {})).then((d) => {
      if (d.version) { INST = d.version; NEU = naechste(INST); api.empfange('status', status()); api.empfange('update', update()); }
    }).catch(() => {});
    const p = new URLSearchParams(location.search);
    zustand = p.get('zustand') || zustand; grund = p.get('grund') || ''; gh = p.get('github') || gh; upd = p.get('update') || upd;
    if (p.get('kerne')) kerne = Number(p.get('kerne'));
    const rn = parseInt(p.get('runner'), 10); if (rn >= 1 && rn <= 5) runnerAnzahl = rn;
    if (p.get('faehig') === 'teilweise') faehigWahl = 'teilweise';
    forgejoAngebunden = ['angebunden', 'unsichtbar'].includes(p.get('forgejo'));
    forgejoUnsichtbar = p.get('forgejo') === 'unsichtbar';
    if (['kein-token', 'nicht-erreichbar', 'token-ungueltig'].includes(p.get('anbieter'))) anbieterAbfrage = p.get('anbieter');
    if (parseInt(p.get('anbieteralter'), 10) > 0) anbieterAlter = parseInt(p.get('anbieteralter'), 10);
    schritteLokal = p.get('schritte') === 'lokal';
    const vl = parseInt(p.get('verlauf'), 10); if (vl >= 30 && vl <= 600) verlaufS = vl;
    if (p.get('leiste') !== '0') leiste();
    if (['job', 'platte', 'volllast'].includes(zustand)) neuerJob();
    alles(true);
    // ?gewaehlt=N (1 bis 5, wie im Design): Runner N wählen, z. B. ?runner=3&gewaehlt=3 = buildagent (Grundüberwachung)
    const gw = parseInt(p.get('gewaehlt'), 10);
    if (gw >= 1 && gw <= runnerAnzahl && api.waehleRunner) api.waehleRunner(runnerListe()[gw - 1].id);
    if (zustand === 'getrennt') { api.setzeVerbindung('getrennt'); }
    setInterval(() => {
      if (zustand === 'getrennt') return;
      takt++;
      api.empfange('system', system(false));
      if (takt % 2 === 0) api.empfange('prozesse', prozesse());
      if (takt % 2 === 0) logTakt();
      if (takt % 2 === 0) runnerSenden();
      if (takt % 10 === 0) journalTakt();
      if (takt % 5 === 0) { api.empfange('workflows', workflows()); api.empfange('platten', platten()); }
      if (upd === 'laeuft') { updSchritt++; if (updSchritt > 22) upd = 'erfolg-demo'; api.empfange('update', upd === 'erfolg-demo' ? { installiert: NEU, neueste: { version: NEU, geprueft: jetzt() }, status: { zustand: 'erfolg', zeit: jetzt() }, auto: false } : update()); }
    }, 1000);
  }

  return { start, journal, funde, erkennen, zuordnung, updateStarten: () => { upd = 'laeuft'; updSchritt = 0; api.empfange('update', update()); }, pruefen: () => setTimeout(() => { const d = update(); d.neueste = { ...d.neueste, geprueft: jetzt() }; api.empfange('update', d); }, 1500) };
})();
