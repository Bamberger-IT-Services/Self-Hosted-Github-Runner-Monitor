/* Runner-Monitor – Demo-Simulator. Nur mit ?demo aktiv: erzeugt dieselben Daten wie der Dienst,
   ohne Server. Alle Namen und Adressen sind erfunden (öffentliches Repository). */
'use strict';

window.RM_DEMO = (() => {
  const GiB = 1024 ** 3, GB = 1e9;
  const jetzt = () => Date.now() / 1000;
  const zufall = (a, b) => a + Math.random() * (b - a);
  let api, takt = 0, kerne = 8, zustand = 'job', gh = 'ok', upd = 'aktuell';
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

  const status = () => {
    const t = jetzt();
    const dienst = zustand === 'gestoppt' ? { zustand: 'gestoppt', seit: t - 760 } : { zustand: 'aktiv', seit: START + 3600 };
    const github = zustand === 'offline' ? { zustand: 'offline', seit: t - 1240 } : gh === 'kein-token' ? { zustand: 'unbekannt', seit: null } : { zustand: 'online', seit: null };
    return {
      vm: 'runner-vm', runner: 'runner-vm-01', eingerichtet: true, labels: ['self-hosted', 'linux', 'x64', 'docker'], version: '2.329.0', monitorVersion: '0.1.0',
      dienst, github,
      job: ['job', 'platte', 'volllast', 'getrennt'].includes(zustand) && job ? { ...JOB, start: job.start, schritt: schrittNr } : null,
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
    const neueste = { geprueft: t - 3100, version: upd === 'aktuell' ? '0.1.0' : '0.2.0', veroeffentlicht: t - 2 * 86400, url: 'https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/releases', notizen: ['Mehrere Runner auf einer VM', 'Log-Suche im Live-Log', 'Kleinere Korrekturen in der Einrichtung'] };
    const st = upd === 'laeuft' ? { zustand: 'laeuft', schritt: Math.min(5, 1 + Math.floor(updSchritt / 4)), version: '0.2.0', zeit: t - updSchritt }
      : upd === 'fehler' ? { zustand: 'fehler', schritt: 5, version: '0.2.0', zeit: t - 300, meldung: 'die neue Version hat nach dem Neustart nicht geantwortet' } : {};
    return { installiert: '0.1.0', neueste, status: st, auto: false };
  };
  const platten = () => {
    const frei = zustand === 'platte' ? 18.4 * GB : 61.2 * GB;
    return [
      { pfad: '/', gesamt: 128 * GB, frei, belegt: 128 * GB - frei, schwelleFrei: 25 * GB },
      { pfad: '/var/lib/docker', gesamt: 256 * GB, frei: 171 * GB, belegt: 85 * GB },
    ];
  };

  function system(erst) {
    const ziel = zustand === 'gestoppt' || zustand === 'offline' ? 4 : zustand === 'volllast' ? 96 : job ? 58 : 6;
    cpuSchnitt += (ziel - cpuSchnitt) * 0.25 + zufall(-4, 4);
    cpuSchnitt = Math.max(1, Math.min(100, cpuSchnitt));
    const k = Array.from({ length: kerne }, () => Math.max(0, Math.min(100, cpuSchnitt + zufall(-22, 22))));
    const ram = (zustand === 'volllast' ? 29 : job ? 11.4 : 4.1) * GiB + zufall(-0.2, 0.2) * GiB;
    const d = { zeit: jetzt(), kerne: k, cpu: k.reduce((a, b) => a + b, 0) / kerne, last: [cpuSchnitt / 100 * kerne * 0.9, cpuSchnitt / 100 * kerne * 0.8, cpuSchnitt / 100 * kerne * 0.7], ram: { belegt: ram, gesamt: 32 * GiB }, swap: { belegt: 0.2 * GiB, gesamt: 4 * GiB }, start: START };
    if (erst) d.verlauf = { cpu: Array.from({ length: 600 }, (_, i) => 30 + 25 * Math.sin(i / 40) + zufall(-6, 6)), ram: Array.from({ length: 600 }, (_, i) => 30 + 6 * Math.sin(i / 90)) };
    return d;
  }
  const prozesse = () => PROZ.slice(0, 6).map(([befehl, benutzer], i) => ({ pid: 2140 + i * 317, benutzer, cpu: Math.max(0.1, cpuSchnitt * (0.9 - i * 0.16) * zufall(0.8, 1.2)), ram: Math.max(0.1, 7 - i + zufall(-0.5, 0.5)), befehl }));

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
    api.empfange('log', { zeilen: [{ art: 'schritt', zeit: jetzt(), nr: schrittNr, von: JOB.schritte.length, name: JOB.schritte[schrittNr - 1] }] });
    api.empfange('status', status());
  }
  function neuerJob() {
    job = { start: jetzt() - 95 }; schrittNr = 3; zeilenImSchritt = 0;
    api.empfange('log', { neu: true, ereignisse: [{ art: 'start', zeit: jetzt() - 95, repo: JOB.repo, workflow: JOB.workflow, name: JOB.name }], zeilen: [{ art: 'schritt', zeit: jetzt() - 60, nr: 3, von: JOB.schritte.length, name: JOB.schritte[2] }] });
    api.empfange('status', status());
  }

  function alles(erst) {
    api.empfange('status', status());
    api.empfange('system', system(erst));
    api.empfange('prozesse', prozesse());
    api.empfange('platten', platten());
    api.empfange('workflows', workflows());
    api.empfange('update', update());
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
    const p = new URLSearchParams(location.search);
    zustand = p.get('zustand') || zustand; gh = p.get('github') || gh; upd = p.get('update') || upd;
    if (p.get('kerne')) kerne = Number(p.get('kerne'));
    if (p.get('leiste') !== '0') leiste();
    if (['job', 'platte', 'volllast'].includes(zustand)) neuerJob();
    alles(true);
    if (zustand === 'getrennt') { api.setzeVerbindung('getrennt'); }
    setInterval(() => {
      if (zustand === 'getrennt') return;
      takt++;
      api.empfange('system', system(false));
      if (takt % 2 === 0) api.empfange('prozesse', prozesse());
      if (takt % 2 === 0) logTakt();
      if (takt % 5 === 0) { api.empfange('workflows', workflows()); api.empfange('platten', platten()); }
      if (upd === 'laeuft') { updSchritt++; if (updSchritt > 22) upd = 'erfolg-demo'; api.empfange('update', upd === 'erfolg-demo' ? { installiert: '0.2.0', neueste: { version: '0.2.0', geprueft: jetzt() }, status: { zustand: 'erfolg', zeit: jetzt() }, auto: false } : update()); }
    }, 1000);
  }

  return { start, updateStarten: () => { upd = 'laeuft'; updSchritt = 0; api.empfange('update', update()); } };
})();
