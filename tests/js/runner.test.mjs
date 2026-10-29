// Mehrere Runner im Dashboard (Design 0.8.0, #94): Wahl, Reiter, „+N“, Ansicht. Läuft mit `node --test tests/js/*.test.mjs`
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';

const R = createRequire(import.meta.url)('../../web/runner.js');
const liste = (n) => Array.from({ length: n }, (_, i) => ({ id: `runner-vm-0${i + 1}`, name: `runner-vm-0${i + 1}` }));
const speicher = (start = {}) => {
  const d = { ...start };
  return { getItem: (k) => (k in d ? d[k] : null), setItem: (k, v) => { d[k] = String(v); }, d };
};

test('Wahl: Schlüssel und Runner-ID in localStorage', () => {
  assert.equal(R.SCHLUESSEL, 'runner-monitor.runner');
  const s = speicher();
  assert.equal(R.laden(s), null);
  assert.equal(R.speichern('runner-vm-02', s), true);
  assert.equal(s.d['runner-monitor.runner'], 'runner-vm-02');
  assert.equal(R.laden(s), 'runner-vm-02');
});

test('Wahl: gesperrter Speicher wirft nicht', () => {
  const gesperrt = { getItem() { throw new Error('gesperrt'); }, setItem() { throw new Error('gesperrt'); } };
  assert.equal(R.laden(gesperrt), null);
  assert.equal(R.speichern('x', gesperrt), false);
  assert.equal(R.laden(null), null);
  assert.equal(R.speichern('', speicher()), false);
});

test('gültige Wahl: Wunsch nur, wenn es den Runner gibt, sonst der erste', () => {
  const l = liste(3);
  assert.equal(R.waehle(l, 'runner-vm-03'), 'runner-vm-03');
  assert.equal(R.waehle(l, 'weg'), 'runner-vm-01');
  assert.equal(R.waehle(l, null), 'runner-vm-01');
  assert.equal(R.waehle([], 'runner-vm-01'), null);
  assert.equal(R.waehle(null, 'x'), null);
});

test('Reiter: bis 3 Runner alle, keine „+N“', () => {
  for (const n of [1, 2, 3]) {
    const r = R.reiter(liste(n), 'runner-vm-01');
    assert.equal(r.sichtbar.length, n);
    assert.deepEqual(r.rest, []);
    assert.equal(r.mehr, false);
  }
});

test('Reiter: ab 4 Runnern 0, 1 und der gewählte (sonst 2), Rest hinter „+N“', () => {
  const l = liste(5);
  let r = R.reiter(l, 'runner-vm-01');
  assert.deepEqual(r.sichtbar, ['runner-vm-01', 'runner-vm-02', 'runner-vm-03']);
  assert.deepEqual(r.rest, ['runner-vm-04', 'runner-vm-05']);
  assert.equal(r.mehr, true);
  r = R.reiter(l, 'runner-vm-05');
  assert.deepEqual(r.sichtbar, ['runner-vm-01', 'runner-vm-02', 'runner-vm-05']);
  assert.deepEqual(r.rest, ['runner-vm-03', 'runner-vm-04']);
  r = R.reiter(l, 'runner-vm-04');
  assert.deepEqual(r.sichtbar, ['runner-vm-01', 'runner-vm-02', 'runner-vm-04']);
  r = R.reiter(l, 'runner-vm-02');   // schon sichtbar: Reiter 2 bleibt der dritte Platz
  assert.deepEqual(r.sichtbar, ['runner-vm-01', 'runner-vm-02', 'runner-vm-03']);
  assert.equal(R.reiter(liste(4), 'runner-vm-01').rest.length, 1);
});

test('Reiter: jeder Runner steht genau einmal da (sichtbar oder Rest)', () => {
  for (const n of [4, 5, 8]) for (const g of liste(n)) {
    const r = R.reiter(liste(n), g.id);
    assert.deepEqual([...r.sichtbar, ...r.rest].sort(), liste(n).map((x) => x.id).sort());
    assert.ok(r.sichtbar.includes(g.id), `${g.id} ist sichtbar`);
    assert.equal(r.sichtbar.length, 3);
  }
});

test('Zustände und Farbklassen wie im Design', () => {
  const z = (s) => R.zustand({ status: { zustand: s } });
  assert.deepEqual(z('job'), { art: 'laeuft', wort: 'job' });
  assert.deepEqual(z('bereit'), { art: 'ok', wort: 'bereit' });
  assert.deepEqual(z('gestoppt'), { art: 'fehler', wort: 'gestoppt' });
  assert.deepEqual(z('offline'), { art: 'warn', wort: 'offline' });
  assert.deepEqual(z('aktiv'), { art: 'ok', wort: 'aktiv' });   // Grundüberwachung: „Dienst aktiv“
  assert.deepEqual(z('unbekannt'), { art: 'neutral', wort: 'unbekannt' });
  assert.deepEqual(R.zustand({}), { art: 'neutral', wort: 'unbekannt' });
});

test('Dienst-Plakette: Anbieter mit Namen, sonst null', () => {
  assert.equal(R.dienstName('github'), 'GitHub');
  assert.equal(R.dienstName('forgejo'), 'Forgejo');
  assert.equal(R.dienstName('gitea'), 'Gitea');
  assert.equal(R.dienstName('gitlab'), 'GitLab');
  assert.equal(R.dienstName('unbekannt'), null);
  assert.equal(R.dienstName(undefined), null);
});

test('Ansicht: Runner mit Jobs → Altformat der Karten', () => {
  const r = {
    id: 'runner-vm-01', name: 'runner-vm-01', dienst: 'github', version: '2.338.1', labels: ['self-hosted', 'linux'],
    faehig: { status: true, jobs: true, schritte: true, logs: true, updates: false },
    status: { zustand: 'job', dienst: { zustand: 'aktiv', seit: 1, grund: null }, beimDienst: { zustand: 'online', seit: null } },
    job: { repo: 'web-portal', schritt: { nr: 3, von: 8, name: 'Abhängigkeiten' } }, letzteJobs: [{ name: 'build' }],
  };
  const a = R.ansicht(r, { vm: 'runner-vm', monitorVersion: '0.8.0' });
  assert.equal(a.vm, 'runner-vm');
  assert.equal(a.runner, 'runner-vm-01');
  assert.deepEqual(a.labels, ['self-hosted', 'linux']);
  assert.equal(a.dienst.zustand, 'aktiv');
  assert.equal(a.github.zustand, 'online');
  assert.equal(a.job.schritt.nr, 3);
  assert.equal(a.nurGrund, false);
  assert.equal(a.anbieter, 'github');
});

test('Ansicht: Grundüberwachung ohne Jobs und Anbindung', () => {
  const r = {
    id: 'buildagent', name: 'buildagent', dienst: 'unbekannt', labels: [],
    faehig: { status: true, jobs: false, schritte: false, logs: true, updates: false },
    status: { zustand: 'aktiv', dienst: { zustand: 'aktiv', seit: 1, grund: null }, beimDienst: null },
    job: null, letzteJobs: null, jobsJeRepository: null,
  };
  const a = R.ansicht(r, { vm: 'runner-vm' });
  assert.equal(a.nurGrund, true);
  assert.equal(a.job, null);
  assert.deepEqual(a.letzteJobs, []);
  assert.equal(a.github.zustand, 'unbekannt');
  assert.deepEqual(a.labels, []);
});

test('Meldung eines anderen Runners: „Anzeigen“ nur bei nicht gewähltem Runner', () => {
  assert.equal(R.fremd({ runner: 'runner-vm-02' }, 'runner-vm-01'), true);
  assert.equal(R.fremd({ runner: 'runner-vm-01' }, 'runner-vm-01'), false);
  assert.equal(R.fremd({ runner: null }, 'runner-vm-01'), false);   // betrifft die VM
  assert.equal(R.fremd(null, 'runner-vm-01'), false);
});

test('Dateiname passt zur Auslieferung (nur a-z, 0-9, Bindestrich) und steht vor dashboard.js', () => {
  assert.match('runner.js', /^[a-z0-9-]+\.(css|js|svg)$/);
  const html = readFileSync(new URL('../../web/dashboard.html', import.meta.url), 'utf8');
  assert.ok(html.indexOf('/static/runner.js') > 0);
  assert.ok(html.indexOf('/static/runner.js') < html.indexOf('/static/dashboard.js'));
});

test('gemerkte Wahl überlebt die Reihenfolge status vor runner und einen kurz fehlenden Runner', () => {
  const s = speicher({ 'runner-monitor.runner': 'runner-vm-03' });
  const w = R.wahl(s);
  assert.equal(w.wunsch, 'runner-vm-03');
  assert.equal(w.liste(null), null);                    // status kommt zuerst, runner[] noch nicht da
  assert.equal(w.liste([]), null);
  assert.equal(w.wunsch, 'runner-vm-03');               // der Wunsch bleibt
  assert.equal(w.liste(liste(3)), 'runner-vm-03');      // jetzt gilt die gemerkte Wahl
  assert.equal(w.liste(liste(2)), 'runner-vm-01');      // Runner kurz weg: vorläufig der erste
  assert.equal(s.d['runner-monitor.runner'], 'runner-vm-03');   // die Speicherung bleibt unberührt
  assert.equal(w.liste(liste(3)), 'runner-vm-03');      // und greift wieder
});

test('Benutzerwahl ändert den Wunsch und speichert; unbekannte ID nicht', () => {
  const s = speicher();
  const w = R.wahl(s);
  assert.equal(w.waehle('runner-vm-09', liste(3)), false);
  assert.equal(s.d['runner-monitor.runner'], undefined);
  assert.equal(w.waehle('runner-vm-02', liste(3)), true);
  assert.equal(w.gewaehlt, 'runner-vm-02');
  assert.equal(s.d['runner-monitor.runner'], 'runner-vm-02');
  assert.equal(w.liste(liste(3)), 'runner-vm-02');
});

test('Runner ohne Dienst: neutral, kein Alarm', () => {
  assert.deepEqual(R.zustand({ status: { zustand: 'fehlt' } }), { art: 'neutral', wort: 'fehlt' });
});

/* ------------------------------------------------------------ Grundüberwachung und „teilweise“ (#95) */
const FAEHIG = {
  voll: { status: true, jobs: true, schritte: true, logs: true, updates: false },
  teil: { status: true, jobs: true, schritte: false, logs: true, updates: false },
  grund: { status: true, jobs: false, schritte: false, logs: true, updates: false },
  ohne: { status: false, jobs: false, schritte: false, logs: false, updates: false },
};
const eintrag = (dienst, faehig, log) => ({
  id: 'r1', name: 'r1', dienst, unit: 'buildagent.service', labels: [], faehig,
  status: { zustand: faehig.status ? 'aktiv' : 'fehlt', dienst: { zustand: faehig.status ? 'aktiv' : 'fehlt', seit: 1, grund: null, neustarts: 0, letzterStopp: null }, beimDienst: null },
  job: { name: 'build', start: 1, schritt: null, schritte: [] }, letzteJobs: [{ name: 'x' }], jobsJeRepository: null, log,
});

test('Steuerung nur über faehig, nie über den Dienstnamen', () => {
  // Gleiche Fähigkeiten → gleiche Ansicht, egal welcher Dienst (README › „Nicht verfügbar“ ehrlich zeigen)
  const LOG = { art: 'journal', unit: 'buildagent.service' };
  for (const [art, faehig] of Object.entries(FAEHIG)) {
    const ansichten = ['github', 'forgejo', 'gitea', 'gitlab', 'unbekannt', 'gibt-es-nicht'].map((d) => {
      const a = R.ansicht(eintrag(d, faehig, LOG));
      return { nurGrund: a.nurGrund, ohneSchritte: a.ohneSchritte, logQuelle: a.logQuelle, journalUnit: a.journalUnit, job: !!a.job,
        letzte: a.letzteJobs.length, dienst: a.dienst.zustand, zustand: R.zustand(eintrag(d, faehig, LOG)), ziel: R.journalZiel(eintrag(d, faehig, LOG)) };
    });
    for (const a of ansichten) assert.deepEqual(a, ansichten[0], art);
  }
  // und umgekehrt: andere Fähigkeiten beim selben Dienst ändern die Ansicht
  const g = R.ansicht(eintrag('github', FAEHIG.grund, LOG)), t = R.ansicht(eintrag('github', FAEHIG.teil, LOG));
  assert.equal(g.nurGrund, true);
  assert.equal(g.job, null);                // ohne Fähigkeit „jobs“ kein Job, auch wenn einer mitkäme
  assert.deepEqual(g.letzteJobs, []);
  assert.equal(t.nurGrund, false);
  assert.equal(t.ohneSchritte, true);
  assert.equal(t.job.name, 'build');
  assert.equal(R.ansicht(eintrag('unbekannt', FAEHIG.voll, LOG)).ohneSchritte, false);
});

test('dashboard.js entscheidet Karten und Log nicht nach dem Dienstnamen', () => {
  const js = readFileSync(new URL('../../web/dashboard.js', import.meta.url), 'utf8');
  for (const name of ['abgleich', 'setzeLogQuelle', 'renderStatus', 'renderWorkflows', 'renderLogKopf', 'renderLeer']) {
    const start = js.indexOf(`function ${name}(`);
    assert.ok(start > 0, name);
    const rumpf = js.slice(start, js.indexOf('\n  }\n', start));
    assert.doesNotMatch(rumpf, /istGitHub\(|anbieter\s*===|\.dienst\s*===|===\s*'(github|forgejo|gitea|gitlab)'/, name);
  }
});

test('Reiter und Karte gleich: ohne Unit „Kein Dienst“ statt „Unbekannt“ (Review #114)', () => {
  const ohne = eintrag('forgejo', FAEHIG.ohne, null);
  ohne.status = { zustand: 'unbekannt', dienst: { zustand: 'fehlt' }, beimDienst: null };  // auch ein älterer Server
  assert.deepEqual(R.zustand(ohne), { art: 'neutral', wort: 'fehlt' });
  assert.equal(R.ansicht(ohne).dienst.zustand, 'fehlt');
  assert.equal(R.ansicht(ohne).logQuelle, null);
});

test('Log-Quelle und Journal-Ziel', () => {
  assert.equal(R.logQuelle(eintrag('x', FAEHIG.grund, { art: 'journal', unit: 'buildagent.service' })), 'journal');
  assert.equal(R.logQuelle(eintrag('x', FAEHIG.voll, { art: 'seiten', unit: 'u.service' })), 'seiten');
  assert.equal(R.logQuelle(eintrag('x', FAEHIG.grund, { art: 'datei', unit: 'u.service' })), 'datei');
  assert.equal(R.logQuelle(eintrag('x', { ...FAEHIG.grund, logs: false }, { art: 'journal', unit: 'u.service' })), null);
  assert.equal(R.logQuelle(eintrag('x', FAEHIG.grund, { art: 'journal', unit: '' })), null);
  assert.equal(R.logQuelle(eintrag('x', FAEHIG.grund, { art: 'anders' })), null);
  assert.equal(R.logQuelle(null), null);
  assert.equal(R.journalZiel(eintrag('x', FAEHIG.grund, { art: 'journal', unit: 'buildagent.service' })), 'r1');
  assert.equal(R.journalZiel(eintrag('x', FAEHIG.voll, { art: 'seiten', unit: 'u.service' })), null);
  assert.equal(R.journalUrl('runner vm/02'), '/events?journal=runner%20vm%2F02');
  assert.equal(R.journalUrl(null), '/events');
  const a = R.ansicht(eintrag('x', FAEHIG.grund, { art: 'journal', unit: 'buildagent.service' }));
  assert.equal(a.journalUnit, 'buildagent.service');
  assert.equal(a.unit, 'buildagent.service');
});

test('Log: Trenner nur mit Schritten, Journal ohne Trenner', () => {
  const zeilen = [{ art: 'schritt', nr: 1 }, { zeit: 1, text: 'a' }, { zeit: 2, art: 'luecke', n: 3 }, null];
  assert.deepEqual(R.logZeilen(zeilen, true).map((z) => z.art || 'zeile'), ['schritt', 'zeile', 'luecke']);
  assert.deepEqual(R.logZeilen(zeilen, false).map((z) => z.art || 'zeile'), ['zeile', 'luecke']);
  assert.deepEqual(R.logZeilen(undefined, true), []);
});

test('Neustarts aus NRestarts', () => {
  assert.deepEqual(R.neustarts({ neustarts: 0 }), { art: 'keine', n: 0 });
  assert.deepEqual(R.neustarts({ neustarts: 3 }), { art: 'zahl', n: 3 });
  for (const w of [null, undefined, -1, 1.5, '3']) assert.deepEqual(R.neustarts({ neustarts: w }), { art: 'unbekannt', n: null });
  assert.deepEqual(R.neustarts(null), { art: 'unbekannt', n: null });
});

test('ansicht reicht „unbekannt“ und nicht zuordenbare Jobs durch (#93)', () => {
  const r = { id: 'runner-vm-02', name: 'runner-vm-02', dienst: 'forgejo', faehig: { jobs: true, schritte: true },
    status: { zustand: 'unbekannt', dienst: { zustand: 'aktiv', seit: 1 }, beimDienst: { zustand: 'unbekannt', seit: null } }, job: null };
  assert.equal(R.ansicht(r).zustand, 'unbekannt');
  assert.equal(R.zustand(r).wort, 'unbekannt');
  const j = R.ansicht({ ...r, status: { ...r.status, zustand: 'job' }, job: { name: '', zuordenbar: false } });
  assert.equal(j.job.zuordenbar, false);
  assert.equal(R.ansicht({ id: 'x' }).zustand, null);
});
