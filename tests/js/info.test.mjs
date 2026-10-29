// Info & Hilfe (Design 0.8.0, #97, #123): Runner-Liste, Verbindungen, Anleitungen je Dienst. Läuft mit `node --test tests/js/*.test.mjs`
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const INFO = require('../../web/info.js');
const EINR = require('../../web/einrichtung-runner.js');
const t = (text, w) => (w ? text.replace(/\{(\w+)\}/g, (m, k) => (k in w ? String(w[k]) : m)) : text);
const p2 = (v) => String(v).padStart(2, '0');
const ms = (z) => (typeof z === 'number' ? (z < 1e12 ? z * 1000 : z) : Date.parse(z));
const RM = {
  ms, zahl: (x) => String(x), mehrzahl: (n, a, b) => (n === 1 ? a : b),
  hm: (z) => { const d = new Date(ms(z)); return `${p2(d.getHours())}:${p2(d.getMinutes())}`; },
  zeit: (z) => { const d = new Date(ms(z)); return `${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}`; },
  tm: (z) => { const d = new Date(ms(z)); return `${p2(d.getDate())}.${p2(d.getMonth() + 1)}.`; },
  datum: (z) => `${RM.tm(z)}${new Date(ms(z)).getFullYear()}`,
};
const JETZT = Date.UTC(2026, 9, 29, 12, 0, 0);
const f = { t, RM, jetzt: JETZT };
const sek = JETZT / 1000;

const fund = (id, dienst, extra = {}) => ({ id, name: id, dienst, server: null, version: null, grad: 'sicher', einstufung: 'teil', stand: 'offen', unit: `${id}.service`, anbindung: 'ohne-server', zuordnung: {}, ...extra });
const gh = (extra = {}) => ({ abfrage: 'ok', abgefragt: sek - 5, naechste: sek + 25, org: 'beispiel-org', tokenAblauf: sek + 74 * 86400, kontingent: { limit: 5000, frei: 4812, reset: sek + 2400 }, repos: [], runnerGrund: '', ...extra });
const runner = (id, dienst, extra = {}) => ({ id, name: id, dienst, server: 'https://git.example.org', org: 'beispiel-org', unit: `${id}.service`, stand: 'angebunden', faehig: { status: true, jobs: true, schritte: true, logs: true, updates: false }, jobsJeRepository: gh(), ...extra });

test('Befehl und Token-Datei nur mit gültiger Runner-ID', () => {
  assert.equal(INFO.befehlZugang('runner-vm-01'), 'sudo /opt/runner-monitor/aktuell/einrichten.sh zugang runner-vm-01');
  assert.equal(INFO.tokenDatei('runner-vm-02'), '/etc/runner-monitor/zugang/runner-vm-02.token');
  assert.equal(INFO.befehlZugang('x; rm -rf /'), 'sudo /opt/runner-monitor/aktuell/einrichten.sh zugang RUNNER');
  assert.equal(INFO.tokenDatei('../../etc/passwd'), '/etc/runner-monitor/zugang/RUNNER.token');
  // Regel wie einrichten.sh: a-z 0-9 _ am Rand, dazu . - im Inneren, höchstens 64 Zeichen
  assert.equal(INFO.tokenDatei('_agent'), '/etc/runner-monitor/zugang/_agent.token');
  assert.equal(INFO.tokenDatei('-agent'), '/etc/runner-monitor/zugang/RUNNER.token');
  assert.equal(INFO.tokenDatei('agent.'), '/etc/runner-monitor/zugang/RUNNER.token');
  assert.equal(INFO.tokenDatei('a'.repeat(64)), `/etc/runner-monitor/zugang/${'a'.repeat(64)}.token`);
  assert.equal(INFO.tokenDatei('a'.repeat(65)), '/etc/runner-monitor/zugang/RUNNER.token');
});

test('Server für Befehle: nur Schema, Host, Port und einfacher Pfad', () => {
  assert.equal(INFO.serverBasis('https://git.example.org'), 'https://git.example.org');
  assert.equal(INFO.serverBasis('https://git.example.org:3000/'), 'https://git.example.org:3000');
  assert.equal(INFO.serverBasis('https://git.example.org/gitea/'), 'https://git.example.org/gitea');
  assert.equal(INFO.serverBasis('https://x.example.org;reboot'), null);
  assert.equal(INFO.serverBasis('ftp://x'), null);
  assert.equal(INFO.serverBasis(null), null);
  assert.equal(INFO.einheit('forgejo-runner.service'), "'forgejo-runner.service'");
  assert.equal(INFO.einheit("a'; rm"), null);
  assert.equal(INFO.einheit('-x.service'), null);
});

test('Einstufung: ignoriert, neu, angebunden, Grundüberwachung, noch nicht angebunden', () => {
  assert.equal(INFO.einstufung(fund('a', 'gitea', { stand: 'ignoriert' }), null, true).art, 'ignoriert');
  assert.equal(INFO.einstufung(fund('a', 'gitea'), null, true).art, 'neu');
  assert.deepEqual(INFO.einstufung(fund('a', 'forgejo'), { stand: 'angebunden' }, false), { art: 'angebunden', cls: 'ok' });
  assert.equal(INFO.einstufung(fund('a', 'forgejo', { stand: 'grund' }), null, false).art, 'grund');
  assert.deepEqual(INFO.einstufung(fund('a', 'forgejo'), null, false), { art: 'noch', cls: 'warn' });   // Adapter da, Zugangsdaten fehlen
  assert.equal(INFO.einstufung(fund('a', 'github', { anbindung: 'github' }), { stand: 'offen' }, false).art, 'noch');   // kein Token
  assert.equal(INFO.einstufung(fund('b', 'unbekannt', { anbindung: 'ohne-adapter' }), null, false).art, 'grund');
});

test('neue Funde: nur IDs, die vorher fehlten und nicht ignoriert sind', () => {
  const vor = [fund('a', 'github')], nach = [fund('a', 'github'), fund('b', 'gitea'), fund('c', 'gitea', { stand: 'ignoriert' })];
  assert.deepEqual(INFO.neueFunde(vor, nach), ['b']);
  assert.deepEqual(INFO.neueFunde(nach, nach), []);
  assert.deepEqual(INFO.neueFunde(null, null), []);
});

test('Formular: nur geänderte Felder, Stand bleibt, kein Server/Organisation/Token (E-22)', () => {
  const fu = fund('buildagent', 'unbekannt', { unit: 'buildagent.service', zuordnung: { stand: 'grund', log: '/var/log/buildagent/agent.log' } });
  const w0 = INFO.formStart(fu);
  assert.deepEqual(w0, { dienst: 'unbekannt', name: 'buildagent', unit: 'buildagent.service', log: '/var/log/buildagent/agent.log' });
  const e0 = INFO.formEintrag(fu, w0, EINR.DIENST_WAHL);
  assert.deepEqual(e0, { id: 'buildagent', stand: 'grund' });
  assert.equal(INFO.geaendert(e0), false);
  const e1 = INFO.formEintrag(fu, { ...w0, dienst: 'gitea', name: 'Build Agent', log: '' }, EINR.DIENST_WAHL);
  assert.deepEqual(e1, { id: 'buildagent', stand: 'grund', dienst: 'gitea', name: 'Build Agent', log: null });
  assert.equal(INFO.geaendert(e1), true);
  assert.deepEqual(Object.keys(e1).filter((k) => !['id', 'stand', 'dienst', 'name', 'unit', 'log'].includes(k)), []);
  assert.equal(INFO.formEintrag(fund('x', 'gitea'), { dienst: 'kaputt', name: '', unit: '', log: '' }, EINR.DIENST_WAHL).dienst, 'unbekannt');
  // ein ignorierter Fund bleibt beim Ändern der Zuordnung ignoriert, ein erkannter bleibt „wie erkannt“
  assert.equal(INFO.formEintrag(fund('x', 'gitea', { zuordnung: { stand: 'ignoriert' } }), { dienst: 'gitea', name: 'x', unit: 'x.service' }, EINR.DIENST_WAHL).stand, 'ignoriert');
  assert.equal(INFO.formEintrag(fund('x', 'gitea'), { dienst: 'gitea', name: 'x', unit: 'x.service' }, EINR.DIENST_WAHL).stand, null);
});

test('Statuszeile: Suche, keine Änderung, Anzahl und Zeitpunkt', () => {
  const z = (o) => INFO.erkennenText({ erk: 'ruhe', zeit: sek - 600, anzahl: 3, ignoriert: 0, ...o }, f);
  assert.equal(z({ erk: 'laeuft' }), 'Suche Runner …');
  assert.match(z({ erk: 'keine', erkZeit: sek }), /^Keine Änderung · geprüft um \d\d:\d\d$/);
  assert.match(z({}), /^3 Runner erkannt · zuletzt heute \d\d:\d\d, automatisch alle 6 Std\.$/);
  assert.match(z({ anzahl: 1 }), /^1 Runner erkannt/);
  assert.match(z({ anzahl: 0 }), /^Kein Runner erkannt/);
  assert.match(z({ ignoriert: 1 }), /\(1 ignoriert\)$/);
  assert.match(z({ zeit: sek - 3 * 86400 }), /zuletzt \d\d\.\d\d\. \d\d:\d\d/);
  assert.match(z({ zeit: null }), /^Noch keine Erkennung/);
  assert.match(z({ erk: 'zeit' }), /antwortet nicht/);
});

test('Runner-Zeilen: Plakette, Pille, kv und Zugangsdaten nur als Befehl', () => {
  const funde = [
    fund('runner-vm-01', 'github', { server: 'https://github.com/beispiel-org', anbindung: 'github' }),
    fund('buildagent', 'unbekannt', { grad: 'unklar', anbindung: 'ohne-adapter' }),
    fund('runner-vm-03', 'gitea', { server: 'https://git.example.org:3000' }),
    fund('alt', 'forgejo', { stand: 'ignoriert' }),
  ];
  const z = INFO.runnerZeilen({ funde, runner: [{ id: 'runner-vm-01', stand: 'angebunden' }], neu: ['runner-vm-03'], zeit: sek - 600 }, f);
  assert.deepEqual(z.map((x) => [x.name, x.dienst, x.pille]), [['runner-vm-01', 'GitHub', 'angebunden'], ['buildagent', 'unbekannt', 'Grundüberwachung'], ['runner-vm-03', 'Gitea', 'neu gefunden'], ['alt', 'Forgejo', 'ignoriert']]);
  assert.deepEqual(z.map((x) => x.pilleCls), ['ok', 'neutral', 'laeuft', 'neutral']);
  assert.equal(z[0].kv[0][1], 'github.com/beispiel-org');                      // GitHub ohne https:// wie im Entwurf
  assert.equal(z[2].kv[0][1], 'https://git.example.org:3000');
  assert.equal(z[1].kv.find(([k]) => k === 'Sicherheitsgrad')[2], 'warn');
  assert.equal(z[2].kv.find(([k]) => k === 'Letzte Erkennung')[1], 'gerade eben');
  assert.equal(z[1].hatZugang, false);
  assert.equal(z[2].hatZugang, true);
  assert.equal(z[2].befehl, 'sudo /opt/runner-monitor/aktuell/einrichten.sh zugang runner-vm-03');
  assert.equal(z[3].ignoriert, true);
  assert.equal(z[3].istNeu, false);
});

test('Funde aus runner[], wenn die Liste der Erkennung fehlt', () => {
  const l = INFO.fundeAusRunner([runner('runner-vm-01', 'github', { server: 'https://github.com', einstufung: 'voll' }), runner('b', 'unbekannt', { stand: 'grund', unit: null })]);
  assert.equal(l.length, 2);
  assert.equal(l[0].anbindung, 'angebunden');
  assert.equal(l[1].grad, null);
  const z = INFO.runnerZeilen({ funde: l, runner: [], neu: [], zeit: null }, f);
  assert.equal(z[1].kv.some(([k]) => k === 'Sicherheitsgrad'), false);
  assert.equal(z[0].kv.find(([k]) => k === 'Letzte Erkennung')[1], '–');
  assert.deepEqual(INFO.fundeAusRunner(null), []);
});

test('Verbindungen: je angebundenem Dienst eine Gruppe, nur vorhandene Felder, sonst „–“', () => {
  const liste = [
    runner('runner-vm-01', 'github', { server: 'https://github.com' }),
    runner('runner-vm-02', 'forgejo', { jobsJeRepository: gh({ kontingent: {}, tokenAblauf: null }) }),
    { id: 'buildagent', name: 'buildagent', dienst: 'unbekannt', faehig: { jobs: false }, jobsJeRepository: null },
    runner('runner-vm-04', 'gitlab', { org: null, jobsJeRepository: gh({ org: '', kontingent: {}, tokenAblauf: null }) }),
  ];
  const v = INFO.verbindungen(liste, f);
  assert.deepEqual(v.map((x) => [x.dienst, x.titel, x.runner]), [['GitHub', 'beispiel-org', 'runner-vm-01'], ['Forgejo', 'beispiel-org', 'runner-vm-02'], ['GitLab', 'git.example.org', 'runner-vm-04']]);
  const kv = (i) => Object.fromEntries(v[i].kv.map(([k, w]) => [k, w]));
  assert.deepEqual(v[0].kv.map(([k]) => k), ['Server', 'Organisation', 'Token', 'Rechte (nötig)', 'Ablauf', 'Letzte Abfrage', 'Nächste Abfrage', 'API-Kontingent', 'Token-Datei']);
  assert.equal(kv(0)['Token-Datei'], '/etc/runner-monitor/zugang/runner-vm-01.token');
  assert.match(kv(0).Ablauf, /in 74 Tagen\)$/);
  assert.match(kv(0)['API-Kontingent'], /^4812 von 5000 frei, Reset /);
  assert.equal(kv(1).Ablauf, '–');                                              // Forgejo liefert kein Ablaufdatum
  assert.equal(kv(1)['API-Kontingent'], 'vom Server nicht gemeldet');          // nichts erfinden
  assert.equal(kv(1)['Rechte (nötig)'], 'repository, organization – je Lesen');
  assert.equal(kv(2)['Rechte (nötig)'], 'read_api');
  assert.equal(kv(0).Token, 'hinterlegt');                                     // „nur lesend“ wäre nicht belegt
  assert.equal(kv(2).Organisation, '–');
  assert.equal(v[0].kv.find(([k]) => k === 'Nächste Abfrage')[3], 'naechste');
  assert.deepEqual(INFO.verbindungen(null, f), []);
});

test('Verbindungen: kein Token, ungültig, Abfrage fehlgeschlagen', () => {
  const kv = (j) => Object.fromEntries(INFO.verbindungen([runner('a', 'github', { jobsJeRepository: gh(j) })], f)[0].kv.map(([k, w, c]) => [k, [w, c]]));
  assert.deepEqual(kv({ abfrage: 'kein-token' }).Token, ['nicht eingerichtet', 'warn']);
  assert.equal(kv({ abfrage: 'kein-token' })['Letzte Abfrage'][0], 'aus');
  assert.equal(kv({ abfrage: 'kein-token' })['API-Kontingent'][0], '4812 von 5000 frei, Reset ' + RM.hm(sek + 2400));
  assert.deepEqual(kv({ abfrage: 'token-ungueltig' }).Token, ['ungültig oder abgelaufen', 'warn']);
  assert.deepEqual(kv({ abfrage: 'keine-rechte' }).Token, ['ohne Zugriff', 'warn']);
  assert.match(kv({ abfrage: 'nicht-erreichbar', abgefragt: sek - 380 })['Letzte Abfrage'][0], /^fehlgeschlagen · letzte erfolgreiche /);
  assert.equal(kv({ abfrage: 'nicht-erreichbar' })['Letzte Abfrage'][1], 'warn');
  assert.equal(kv({ tokenAblauf: sek + 9 * 86400 }).Ablauf[1], 'warn');
  assert.equal(kv({ runnerGrund: 'Recht fehlt' })['Rechte (nötig)'][1], 'warn');
  // erste Abfrage läuft noch (E-25): weder Fehler noch Token-Aussage
  assert.deepEqual(kv({ abfrage: 'ausstehend' })['Letzte Abfrage'], ['wird abgefragt', '']);
  assert.equal(kv({ abfrage: 'ausstehend' }).Token[0], '–');
});

test('„Nächste Abfrage“ als Text', () => {
  assert.equal(INFO.naechste(runner('a', 'github'), f), 'in 25 s (alle 30 s)');
  assert.equal(INFO.naechste(runner('a', 'github', { jobsJeRepository: gh({ abfrage: 'kein-token' }) }), f), '–');
  assert.equal(INFO.naechste(null, f), '–');
});

const ctx = (extra = {}) => ({ dienst: 'github', id: 'runner-vm-01', unit: 'actions.runner.beispiel-org.runner-vm-01.service', server: 'https://github.com', org: 'beispiel-org', vm: 'runner-vm', ...extra });
const anl = (c, id) => INFO.anleitungen(c, t).find((a) => a.id === id);
const codes = (a) => a.schritte.map(([, c]) => c).filter(Boolean).join('\n');

test('Anleitungen: Reihenfolge und Kennungen bleiben, Titel neutral', () => {
  const l = INFO.anleitungen(ctx(), t);
  assert.deepEqual(l.map((a) => a.id), ['token', 'github', 'gestoppt', 'runner', 'offline', 'logs', 'platte', 'monitor', 'update']);
  const titel = Object.fromEntries(l.map((a) => [a.id, a.titel]));
  assert.equal(titel.token, 'Zugangsdaten einrichten oder erneuern');
  assert.equal(titel.github, 'Dienst nicht erreichbar (GitHub, Forgejo …)');
  assert.equal(titel.offline, 'Runner offline beim Dienst');
});

test('Anleitungen: Zugangsdaten mit Unterpunkten je Dienst und dem Befehl für den gewählten Runner', () => {
  const a = anl(ctx({ dienst: 'forgejo', id: 'runner-vm-02', server: 'https://git.example.org' }), 'token');
  const text = a.schritte.map(([x]) => x).join('\n');
  assert.match(text, /GitHub · /);
  assert.match(text, /Forgejo \/ Gitea · /);
  assert.match(text, /GitLab · /);
  assert.match(codes(a), /einrichten\.sh zugang runner-vm-02/);
  assert.match(codes(a), /Authorization: token \$\(sudo cat \/etc\/runner-monitor\/zugang\/runner-vm-02\.token\)/);
  assert.match(codes(a), /https:\/\/git\.example\.org\/api\/v1\/orgs\/beispiel-org/);
  assert.doesNotMatch(codes(a), /github-token|api\.github\.com/);
  assert.match(codes(anl(ctx({ dienst: 'gitlab', id: 'g1', server: 'https://gitlab.example.org' }), 'token')), /PRIVATE-TOKEN.*\n.*gitlab\.example\.org\/api\/v4\/personal_access_tokens\/self/);
  assert.match(codes(anl(ctx(), 'token')), /api\.github\.com\/orgs\/beispiel-org\//);
  assert.doesNotMatch(codes(anl(ctx({ dienst: 'unbekannt' }), 'token')), /curl/);
  // Aktiv bei Meldungen zu Token / Ablauf
  assert.equal(anl(ctx({ abfrage: 'kein-token' }), 'token').aktiv, true);
  assert.equal(anl(ctx({ abfrage: 'ok' }), 'token').aktiv, false);
  assert.equal(anl(ctx({ tokenAblauf: true }), 'token').aktiv, true);
});

test('Anleitungen: Zugangsdaten für einen anderen Runner (Link bei „Zugangsdaten ändern“)', () => {
  const z = { dienst: 'forgejo', id: 'runner-vm-02', server: 'https://git.example.org', org: 'beispiel-org' };
  const a = INFO.anleitungen(ctx(), t, z).find((x) => x.id === 'token');
  assert.match(codes(a), /einrichten\.sh zugang runner-vm-02/);
  assert.match(codes(a), /zugang\/runner-vm-02\.token/);
  assert.doesNotMatch(codes(a), /runner-vm-01|api\.github\.com/);
  // alle anderen Anleitungen bleiben beim gewählten Runner
  assert.match(codes(INFO.anleitungen(ctx(), t, z).find((x) => x.id === 'gestoppt')), /actions\.runner\.beispiel-org\.runner-vm-01\.service/);
});

test('Anleitungen: kein Zugangs-Token und keine Server-Adresse mit Sonderzeichen im Befehl', () => {
  const alles = INFO.anleitungen(ctx({ dienst: 'gitea', server: 'https://x.example.org; reboot', org: "a'b", unit: "evil';id", id: '../x' }), t);
  const code = alles.flatMap((a) => a.schritte.map(([, c]) => c || '')).join('\n');
  assert.doesNotMatch(code, /reboot|evil|a'b|\.\.\/x/);
  assert.match(code, /https:\/\/SERVER/);
  assert.match(code, /orgs\/ORGANISATION/);                                      // sichtbarer Platzhalter statt eines erfundenen Namens
  assert.doesNotMatch(code, /<[a-z.]+>|beispiel-org/);   // keine spitzen Platzhalter (Shell-Umleitung)
});

test('Anleitungen: „Dienst nicht erreichbar“ je Dienst', () => {
  const g = anl(ctx({ abfrage: 'nicht-erreichbar' }), 'github');
  assert.equal(g.aktiv, true);
  assert.match(codes(g), /curl -sI https:\/\/api\.github\.com/);
  assert.match(g.schritte[0][0], /githubstatus\.com/);
  const fj = anl(ctx({ dienst: 'forgejo', server: 'https://git.example.org', abfrage: 'kontingent' }), 'github');
  assert.equal(fj.aktiv, true);
  assert.match(codes(fj), /curl -sI https:\/\/git\.example\.org\/api\/v1\/version/);
  assert.doesNotMatch(fj.schritte.map(([x]) => x).join(' ') + codes(fj), /githubstatus|api\.github\.com/);
  assert.match(codes(fj), /journalctl -u runner-monitor-sammler/);
  const gl = anl(ctx({ dienst: 'gitlab', server: 'https://gitlab.example.org' }), 'github');
  assert.match(codes(gl), /gitlab\.example\.org\/users\/sign_in/);
  const http = anl(ctx({ dienst: 'gitea', server: 'http://192.0.2.10:3000' }), 'github');
  assert.match(http.schritte.map(([x]) => x).join(' '), /http_erlaubt/);
  assert.doesNotMatch(anl(fj.aktiv ? ctx({ dienst: 'gitea', server: 'https://git.example.org' }) : ctx(), 'github').schritte.map(([x]) => x).join(' '), /http_erlaubt/);
  const u = anl(ctx({ dienst: 'unbekannt' }), 'github');
  assert.match(u.schritte[0][0], /Grundüberwachung/);
});

test('Anleitungen: Befehle mit der Unit des gewählten Runners', () => {
  const c = ctx({ dienst: 'forgejo', unit: 'forgejo-runner.service', gestoppt: true, grund: 'oom-kill' });
  const g = anl(c, 'gestoppt');
  assert.equal(g.aktiv, true);
  assert.match(codes(g), /systemctl status 'forgejo-runner\.service'/);
  assert.match(codes(g), /sudo systemctl start 'forgejo-runner\.service'/);
  assert.match(codes(g), /journalctl -u 'forgejo-runner\.service' -n 50/);
  assert.match(codes(g), /free -h/);
  assert.doesNotMatch(codes(g), /einrichten\.sh runner|actions\.runner/);          // Speicher-Fix des Skripts gilt nur für GitHub-Runner
  assert.match(codes(anl(ctx({ gestoppt: true, grund: 'oom-kill' }), 'gestoppt')), /einrichten\.sh runner/);
  const o = anl(ctx({ dienst: 'gitlab', unit: 'gitlab-runner.service', server: 'https://gitlab.example.org', offline: true }), 'offline');
  assert.equal(o.aktiv, true);
  assert.match(codes(o), /systemctl restart 'gitlab-runner\.service'/);
  assert.match(codes(o), /curl -sI https:\/\/gitlab\.example\.org \| head -1/);
  assert.doesNotMatch(codes(o), /runner --umziehen/);
  assert.match(codes(anl(ctx({ offline: true }), 'offline')), /runner --umziehen/);
  const l = anl(c, 'logs');
  assert.match(codes(l), /journalctl -u 'forgejo-runner\.service' -n 100/);
  assert.doesNotMatch(codes(l), /_diag/);
  assert.match(codes(anl(ctx(), 'logs')), /_diag\/pages/);
  // ohne bekannte Unit: GitHub fällt auf das Muster zurück, andere Dienste auf einen Platzhalter
  assert.match(codes(anl(ctx({ unit: '' }), 'gestoppt')), /systemctl status 'actions\.runner\.\*'/);
  assert.match(codes(anl(ctx({ dienst: 'gitea', unit: '' }), 'gestoppt')), /'UNIT\.service'/);
});

test('Anleitungen: Kein Runner, Platte, Monitor, Update behalten ihre Flags', () => {
  assert.equal(anl(ctx({ fehlt: true }), 'runner').aktiv, true);
  assert.match(codes(anl(ctx(), 'runner')), /einrichten\.sh runner/);
  assert.equal(anl(ctx({ knapp: true }), 'platte').aktiv, true);
  assert.equal(anl(ctx({ getrennt: true }), 'monitor').cls, 'fehler');
  assert.match(codes(anl(ctx({ vm: 'runner-vm' }), 'monitor')), /ping runner-vm/);
  assert.match(codes(anl(ctx({ vm: 'x; y' }), 'monitor')), /ping runner-vm/);
  assert.equal(anl(ctx({ updFehler: true }), 'update').cls, 'fehler');
  assert.equal(anl(ctx({ updNeu: true }), 'update').aktiv, true);
});

test('Texte nennen Zugangsdaten nur als Befehl: nirgends ein Token-Feld oder Token-Wert', () => {
  const alle = JSON.stringify(INFO.anleitungen(ctx(), t));
  assert.doesNotMatch(alle, /ghp_|github_pat_|glpat-/);
});
