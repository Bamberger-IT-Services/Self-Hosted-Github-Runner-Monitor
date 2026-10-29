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

test('ansicht reicht „unbekannt“ und nicht zuordenbare Jobs durch (#93)', () => {
  const r = { id: 'runner-vm-02', name: 'runner-vm-02', dienst: 'forgejo', faehig: { jobs: true, schritte: true },
    status: { zustand: 'unbekannt', dienst: { zustand: 'aktiv', seit: 1 }, beimDienst: { zustand: 'unbekannt', seit: null } }, job: null };
  assert.equal(R.ansicht(r).zustand, 'unbekannt');
  assert.equal(R.zustand(r).wort, 'unbekannt');
  const j = R.ansicht({ ...r, status: { ...r.status, zustand: 'job' }, job: { name: '', zuordenbar: false } });
  assert.equal(j.job.zuordenbar, false);
  assert.equal(R.ansicht({ id: 'x' }).zustand, null);
});
