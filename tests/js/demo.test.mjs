// Demo-Simulator (?demo) liefert seit #92 zusätzlich runner[] und meldungen[] im Format von /api/zustand
// (E-19) – und die Skripte der Oberfläche sind gültiges JavaScript. Läuft mit `node --test tests/js/*.test.mjs`
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import vm from 'node:vm';

const WEB = new URL('../../web/', import.meta.url);
// Felder eines Eintrags in runner[] wie im Backend (tests/test_anbieter.py, EINTRAG_SCHLUESSEL)
const EINTRAG = ['dienst', 'einstufung', 'faehig', 'id', 'job', 'jobsJeRepository', 'labels', 'letzteJobs', 'log', 'name', 'org',
  'server', 'stand', 'status', 'unit', 'version'];

function starteDemo(suche) {
  const empfangen = [];
  const intervalle = [];
  const gewaehlt = [];
  const kontext = {
    window: {}, location: { search: suche }, URLSearchParams, Date, Math, console,
    fetch: () => Promise.resolve({ ok: false }),
    setInterval: (f) => { intervalle.push(f); return intervalle.length; },
    setTimeout: () => 0,
  };
  vm.createContext(kontext);
  vm.runInContext(readFileSync(new URL('demo.js', WEB), 'utf8'), kontext);
  kontext.window.RM_DEMO.start({ empfange: (b, d) => empfangen.push([b, JSON.parse(JSON.stringify(d))]), setzeVerbindung: () => {}, waehleRunner: (id) => gewaehlt.push(id) });
  return { empfangen, gewaehlt, demo: kontext.window.RM_DEMO, takt: () => intervalle.forEach(f => f()) };
}

const letzte = (empfangen, bereich) => empfangen.filter(([b]) => b === bereich).at(-1)[1];

test('alle Skripte der Oberfläche sind gültig', () => {
  for (const name of readdirSync(WEB).filter(n => n.endsWith('.js'))) {
    assert.doesNotThrow(() => new vm.Script(readFileSync(new URL(name, WEB), 'utf8'), { filename: name }), name);
  }
});

test('ein Runner: Eintrag wie im Backend, Job mit Schritt', () => {
  const { empfangen } = starteDemo('?demo&leiste=0');
  const liste = letzte(empfangen, 'runner');
  assert.equal(liste.length, 1);
  const r = liste[0];
  assert.deepEqual(Object.keys(r).sort(), EINTRAG);
  assert.equal(r.dienst, 'github');
  assert.deepEqual(r.faehig, { status: true, jobs: true, schritte: true, logs: true, updates: false });
  assert.equal(r.status.zustand, 'job');
  assert.deepEqual(Object.keys(r.job.schritt).sort(), ['name', 'nr', 'von']);
  assert.equal(r.log.art, 'seiten');
  // die bisherigen Bereiche kommen weiter
  for (const b of ['status', 'system', 'prozesse', 'platten', 'workflows', 'update']) assert.ok(empfangen.some(([x]) => x === b), b);
});

test('drei Runner: Grundüberwachung ohne Jobs, Meldung mit Runner-ID', () => {
  const { empfangen, takt } = starteDemo('?demo&leiste=0&runner=3&zustand=gestoppt');
  takt(); takt();
  const liste = letzte(empfangen, 'runner');
  assert.deepEqual(liste.map(r => r.id), ['runner-vm-01', 'runner-vm-02', 'buildagent']);
  for (const r of liste) assert.deepEqual(Object.keys(r).sort(), EINTRAG, r.id);
  const grund = liste[1];
  assert.equal(grund.faehig.jobs, false);
  assert.equal(grund.job, null);
  assert.equal(grund.jobsJeRepository, null);
  assert.deepEqual(grund.log, { art: 'journal', unit: 'forgejo-runner.service' });
  const meldungen = letzte(empfangen, 'meldungen');
  assert.ok(meldungen.some(m => m.id === 'gestoppt' && m.runner === 'runner-vm-01' && m.stufe === 'fehler'));
  assert.ok(meldungen.some(m => m.id === 'gestoppt' && m.runner === 'buildagent'));
  assert.equal(meldungen[0].stufe, 'fehler');
});

test('fünf Runner (Design 0.8.0): vier Dienste, Zustände je Runner, Meldung von einem anderen Runner', () => {
  const { empfangen } = starteDemo('?demo&leiste=0&runner=5');
  const liste = letzte(empfangen, 'runner');
  assert.deepEqual(liste.map(r => r.id), ['runner-vm-01', 'runner-vm-02', 'buildagent', 'runner-vm-03', 'runner-vm-04']);
  assert.deepEqual(liste.map(r => r.status.zustand), ['job', 'aktiv', 'aktiv', 'bereit', 'offline']);
  for (const r of liste) assert.deepEqual(Object.keys(r).sort(), EINTRAG, r.id);
  assert.equal(liste[4].status.beimDienst.zustand, 'offline');
  const m = letzte(empfangen, 'meldungen').find(x => x.runner === 'runner-vm-04');
  assert.equal(m.id, 'offline');
});

test('ein, drei und fünf Runner über ?runner=N', () => {
  for (const n of [1, 3, 5]) assert.equal(letzte(starteDemo(`?demo&leiste=0&runner=${n}`).empfangen, 'runner').length, n);
  assert.equal(letzte(starteDemo('?demo&leiste=0&runner=9').empfangen, 'runner').length, 1);
});

/* ------------------------------------------------------------ Grundüberwachung und „teilweise“ (#95) */
test('Grundüberwachung: Dienst mit Neustarts und letztem Stopp, ?gewaehlt=3 wählt buildagent', () => {
  const { empfangen, gewaehlt } = starteDemo('?demo&leiste=0&runner=3&gewaehlt=3');
  assert.deepEqual(gewaehlt, ['buildagent']);
  const ba = letzte(empfangen, 'runner')[2];
  assert.equal(ba.status.zustand, 'aktiv');
  assert.deepEqual(Object.keys(ba.status.dienst).sort(), ['grund', 'letzterStopp', 'neustarts', 'seit', 'zustand']);
  assert.equal(ba.status.dienst.neustarts, 0);
  assert.equal(ba.status.dienst.letzterStopp, null);
  assert.deepEqual(ba.log, { art: 'journal', unit: 'buildagent.service' });
});

test('Journal wie /events?journal=<id>: Stand mit „neu“, dann neue Zeilen, ohne Trenner', () => {
  const { empfangen, demo, takt } = starteDemo('?demo&leiste=0&runner=3');
  demo.journal('buildagent');
  const stand = letzte(empfangen, 'journal');
  assert.equal(stand.unit, 'buildagent.service');
  assert.equal(stand.neu, true);
  assert.ok(stand.zeilen.length >= 5);
  assert.ok(stand.zeilen.every((z) => typeof z.text === 'string' && !z.art), 'keine Schritt-Trenner im Journal');
  assert.equal(stand.zeilen[0].text, 'Started buildagent.service - Build Agent.');
  assert.match(stand.zeilen[1].text, /^buildagent\[\d+\]: /);
  assert.equal(stand.ereignisse[0].art, 'dienst-gestartet');
  const vorher = empfangen.filter(([b]) => b === 'journal').length;
  for (let i = 0; i < 10; i++) takt();
  assert.ok(empfangen.filter(([b]) => b === 'journal').length > vorher, 'neue Zeilen kommen nach');
  // zurück zur Ausgabe der Schritte: neuer Stand für „log“
  demo.journal(null);
  assert.equal(letzte(empfangen, 'log').neu, true);
  // gestoppt: letzte Zeile „Stopped …“
  const g = starteDemo('?demo&leiste=0&runner=3&zustand=gestoppt');
  g.demo.journal('buildagent');
  const gs = letzte(g.empfangen, 'journal');
  assert.match(gs.zeilen.at(-1).text, /^Stopped buildagent\.service/);
  assert.equal(gs.ereignisse.at(-1).art, 'dienst-gestoppt');
});

test('Teilweise (?faehig=teilweise): Jobs ja, Schritte nein – wie der Server ohne Schritt', () => {
  const { empfangen } = starteDemo('?demo&leiste=0&faehig=teilweise');
  const r = letzte(empfangen, 'runner')[0];
  assert.deepEqual(r.faehig, { status: true, jobs: true, schritte: false, logs: true, updates: false });
  assert.equal(r.status.zustand, 'job');
  assert.equal(r.job.schritt, null);
  assert.deepEqual(r.job.schritte, []);
  assert.ok(r.letzteJobs.length > 0, 'Letzte Jobs bleiben');
  const voll = letzte(starteDemo('?demo&leiste=0').empfangen, 'runner')[0];
  assert.equal(voll.faehig.schritte, true);
});
