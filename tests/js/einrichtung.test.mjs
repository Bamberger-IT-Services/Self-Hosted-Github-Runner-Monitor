// Einrichtung, Schritte „Runner“, „Anbinden“, „Fertig“ (Design 0.8.0, #96). Läuft mit `node --test tests/js/*.test.mjs`
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';

const E = createRequire(import.meta.url)('../../web/einrichtung-runner.js');
const f = (id, einstufung, mehr = {}) => ({ id, name: id, dienst: einstufung === 'voll' ? 'github' : 'unbekannt', einstufung, stand: 'offen', grad: 'sicher', zuordnung: {}, ...mehr });
const DREI = [f('runner-vm-01', 'voll', { primaer: true }), f('runner-vm-02', 'voll', { dienst: 'forgejo', server: 'https://git.example.org' }), f('buildagent', 'unbekannt', { unit: 'buildagent.service', grad: 'unklar' })];

test('Startwerte wie im Design: voll an, teil Grundüberwachung, unbekannt offen', () => {
  assert.equal(E.startWahl(f('a', 'voll')), 'an');
  assert.equal(E.startWahl(f('a', 'teil')), 'grund');
  assert.equal(E.startWahl(f('a', 'unbekannt')), 'offen');
  assert.equal(E.startWahl(f('a', 'voll', { stand: 'ignoriert' })), 'aus');
  assert.equal(E.startWahl(f('a', 'teil', { zuordnung: { stand: 'ignoriert' } })), 'ignorieren');
  assert.equal(E.startWahl(f('a', 'unbekannt', { stand: 'grund' })), 'grund');
});

test('Neu erkennen: bekannte Funde behalten die Wahl, neue bekommen den Startwert', () => {
  const w = E.mischeWahl([f('a', 'voll'), f('b', 'teil')], { a: 'aus', weg: 'an' });
  assert.deepEqual(w, { a: 'aus', b: 'grund' });
  assert.ok(E.gleicheFunde([f('a', 'voll')], [f('a', 'voll', { name: 'x' })]));
  assert.ok(!E.gleicheFunde([f('a', 'voll')], [f('a', 'voll'), f('b', 'teil')]));
});

test('Stand und Fuß „2 anbinden · 1 offen“', () => {
  const w = E.mischeWahl(DREI, {});
  assert.deepEqual(E.summe(DREI, w), { anbinden: 2, grund: 0, offen: 1 });
  assert.deepEqual(E.stand(DREI[0], 'an'), { art: 'anbinden', cls: 'ok' });
  assert.deepEqual(E.stand(DREI[0], 'aus'), { art: 'ignoriert', cls: 'mut' });
  assert.deepEqual(E.stand(DREI[2], 'offen'), { art: 'offen', cls: 'warn' });
  assert.deepEqual(E.stand(DREI[2], 'grund'), { art: 'grund', cls: 'mut' });
  assert.deepEqual(E.summe(DREI, { ...w, 'runner-vm-02': 'aus', buildagent: 'grund' }), { anbinden: 1, grund: 1, offen: 0 });
});

test('Anbinden: nur übernommene, vollständig unterstützte Runner; ohne sie von 3 direkt zu 5', () => {
  const w = E.mischeWahl(DREI, {});
  assert.deepEqual(E.anbinden(DREI, w).map((x) => x.id), ['runner-vm-01', 'runner-vm-02']);
  assert.deepEqual(E.anbinden(DREI, { ...w, 'runner-vm-02': 'aus' }).map((x) => x.id), ['runner-vm-01']);
  assert.equal(E.weiterVon(3, 0), 5);
  assert.equal(E.weiterVon(3, 1), 4);
  assert.equal(E.zurueckVon(5, 0), 3);
  assert.equal(E.zurueckVon(5, 2), 4);
  assert.equal(E.zurueckVon(4, 2), 3);
});

test('Einträge für runner.json: nur Änderungen, nur erlaubte Felder', () => {
  const w = E.mischeWahl(DREI, {});
  assert.deepEqual(E.eintraege(DREI, w), []);  // nichts geändert
  const liste = E.eintraege(DREI, { ...w, 'runner-vm-02': 'aus', buildagent: 'ignorieren' });
  assert.deepEqual(liste, [{ id: 'runner-vm-02', stand: 'ignoriert' }, { id: 'buildagent', stand: 'ignoriert' }]);
  // vorher ignoriert, jetzt wieder übernommen → Stand „wie erkannt“ (null)
  const alt = [f('a', 'voll', { zuordnung: { stand: 'ignoriert' } })];
  assert.deepEqual(E.eintraege(alt, { a: 'an' }), [{ id: 'a', stand: null }]);
  // Zuordnen mit Formular
  const z = E.eintraege(DREI, { ...w, buildagent: 'grund' }, { buildagent: { dienst: 'gitlab', name: 'Build-Agent', unit: 'buildagent.service', log: '/var/log/b/agent.log' } });
  assert.deepEqual(z, [{ id: 'buildagent', stand: 'grund', dienst: 'gitlab', name: 'Build-Agent', log: '/var/log/b/agent.log' }]);
  for (const e of [...liste, ...z]) assert.deepEqual(Object.keys(e).filter((k) => !['id', 'stand', 'dienst', 'name', 'unit', 'log'].includes(k)), []);
});

test('Von Hand angelegter Runner schickt alle Angaben', () => {
  const neu = { id: 'buildagent', name: 'buildagent', dienst: 'unbekannt', einstufung: 'unbekannt', neu: true, zuordnung: {} };
  const z = E.eintraege([neu], { buildagent: 'grund' }, { buildagent: { dienst: 'unbekannt', name: '', unit: 'buildagent.service', log: '' } });
  assert.deepEqual(z, [{ id: 'buildagent', stand: 'grund', dienst: 'unbekannt', unit: 'buildagent.service' }]);
  assert.equal(E.alsId('Build Agent!'), 'build-agent');
  assert.equal(E.alsId('..'), 'runner');
});

test('Formular „Zuordnen“ prüft wie der Server', () => {
  assert.deepEqual(E.pruefeFormular({ dienst: 'unbekannt', name: 'Build-Agent', unit: 'buildagent.service', log: '/var/log/b/agent.log' }), {});
  assert.deepEqual(E.pruefeFormular({ name: '', unit: '', log: '' }, true), { unit: 'unit' });  // neu: Unit nötig
  assert.deepEqual(E.pruefeFormular({ name: 'a b', unit: 'x', log: '/etc/shadow' }), { name: 'name', unit: 'unit', log: 'log' });
  for (const log of ['/opt/forgejo/.runner', '/var/log/runner-monitor/a.log', '/var/log/../etc/a.log', '/var/log//a.log', '/var/log/a.txt']) {
    assert.deepEqual(E.pruefeFormular({ log }), { log: 'log' }, log);
  }
  assert.deepEqual(E.pruefeFormular({ dienst: 'woodpecker' }), { dienst: 'dienst' });
});

test('Fertig: angebunden, Grundüberwachung, ignoriert; offene fehlen', () => {
  const w = { 'runner-vm-01': 'an', 'runner-vm-02': 'an', buildagent: 'offen' };
  let z = E.zusammenfassung(DREI, w, { angebunden: { 'runner-vm-01': { org: 'beispiel-org' } } });
  assert.deepEqual(z.map((x) => [x.id, x.stand, x.detail]), [['runner-vm-01', 'angebunden', 'token'], ['runner-vm-02', 'grund', 'grund']]);
  z = E.zusammenfassung(DREI, { ...w, 'runner-vm-02': 'aus', buildagent: 'grund' }, { zu: { 'runner-vm-01': true }, angebunden: { 'runner-vm-01': {} } });
  assert.deepEqual(z.map((x) => [x.id, x.art, x.stand]), [['runner-vm-01', 'grund', 'grund'], ['runner-vm-02', 'aus', 'ignoriert'], ['buildagent', 'grund', 'grund']]);
});

test('Organisation aus der Erkennung, Link zur Token-Seite nur bei bestätigtem Server', () => {
  assert.equal(E.orgAus('https://github.com/beispiel-org'), 'beispiel-org');
  assert.equal(E.orgAus('https://github.example.org/beispiel-org'), '');
  assert.deepEqual(E.tokenSeite({ dienst: 'forgejo', grad: 'sicher', server: 'https://git.example.org' }), { host: 'git.example.org', url: 'https://git.example.org/user/settings/applications' });
  assert.deepEqual(E.tokenSeite({ dienst: 'gitlab', grad: 'sicher', server: 'https://gitlab.example.org/' }).url, 'https://gitlab.example.org/-/user_settings/personal_access_tokens');
  assert.equal(E.tokenSeite({ dienst: 'forgejo', grad: 'wahrscheinlich', server: 'https://git.example.org' }), null);
  assert.equal(E.tokenSeite({ dienst: 'forgejo', grad: 'sicher', server: 'http://192.0.2.10' }), null);
  assert.equal(E.tokenSeite({ dienst: 'forgejo', grad: 'sicher', server: 'javascript:alert(1)' }), null);
});

test('Einrichtung: kein Inline-Skript, keine style-Attribute, Sie-Ansprache, Dateinamen', () => {
  const html = readFileSync(new URL('../../web/einrichtung.html', import.meta.url), 'utf8');
  const js = readFileSync(new URL('../../web/einrichtung.js', import.meta.url), 'utf8');
  assert.doesNotMatch(html, /<script>(?!<\/script>)|<script(?![^>]*src=)[^>]*>/);
  assert.doesNotMatch(html + js, /\sstyle="/);
  assert.doesNotMatch(js, /\bonclick=|\bonchange=/i);
  assert.ok(html.indexOf('einrichtung-runner.js') < html.indexOf('/static/einrichtung.js'));
  // Ansprache „Sie“ (E-10): keine Du-Formen in den Texten der Einrichtung
  for (const m of js.matchAll(/\bt\('((?:[^'\\]|\\.)*)'/g)) assert.doesNotMatch(m[1], /\b(du|dein|deine|dich|dir)\b/i, m[1]);
  for (const name of ['einrichtung-runner.js', 'einrichtung.js']) assert.match(name, /^[a-z0-9-]+\.(css|js|svg)$/);
});
