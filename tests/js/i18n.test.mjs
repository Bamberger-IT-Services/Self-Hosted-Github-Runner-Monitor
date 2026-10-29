// Sprachwahl Automatisch / Deutsch / English (#90). Läuft mit `node --test tests/js/*.test.mjs`
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const I = createRequire(import.meta.url)('../../web/i18n.js');

const speicher = (start = {}) => {
  const d = { ...start };
  return { d, getItem: k => (k in d ? d[k] : null), setItem: (k, v) => { d[k] = String(v); }, removeItem: k => { delete d[k]; } };
};
const gesperrt = { getItem() { throw new Error('gesperrt'); }, setItem() { throw new Error('gesperrt'); }, removeItem() { throw new Error('gesperrt'); } };

test('Automatisch: erste Systemsprache mit de → Deutsch, alles andere → Englisch', () => {
  for (const s of ['de', 'de-DE', 'de-AT', 'de-CH', 'DE-de', 'de_DE']) assert.equal(I.aufloesen('auto', [s, 'en-US']), 'de', s);
  for (const s of ['en', 'en-US', 'fr-FR', 'nl', 'da', 'deu', 'dex-XX', '', 'zh-Hans']) assert.equal(I.aufloesen('auto', [s, 'de']), 'en', s);
  assert.equal(I.aufloesen('auto', []), 'en');
  assert.equal(I.aufloesen('auto', undefined), 'en');
  assert.equal(I.aufloesen('auto', [null]), 'en');
});

test('feste Wahl gilt unabhängig vom System', () => {
  assert.equal(I.aufloesen('de', ['en-US']), 'de');
  assert.equal(I.aufloesen('en', ['de-DE']), 'en');
});

test('Wahl wird unter runner-monitor.sprache gemerkt (auto|de|en)', () => {
  const s = speicher();
  assert.equal(I.wahlLesen(s), 'auto');
  for (const w of ['de', 'en', 'auto']) {
    assert.equal(I.wahlSpeichern(w, s), true);
    assert.equal(s.d['runner-monitor.sprache'], w);
    assert.equal(I.wahlLesen(s), w);
  }
});

test('ungültige Wahl wird nicht gespeichert und gilt als auto', () => {
  const s = speicher();
  for (const w of ['fr', '', null, undefined, 'DE']) assert.equal(I.wahlSpeichern(w, s), false);
  assert.deepEqual(s.d, {});
  assert.equal(I.wahlLesen(speicher({ 'runner-monitor.sprache': 'klingonisch' })), 'auto');
});

test('gesperrter Speicher: automatisch, kein Fehler', () => {
  assert.equal(I.wahlLesen(gesperrt), 'auto');
  assert.equal(I.wahlSpeichern('en', gesperrt), false);
  assert.equal(I.wahlLesen(null), 'auto');
});

test('alter Schlüssel rm-sprache wird einmal übernommen', () => {
  const s = speicher({ 'rm-sprache': 'en' });
  assert.equal(I.wahlLesen(s), 'en');
  assert.deepEqual(s.d, { 'runner-monitor.sprache': 'en' });
  assert.equal(I.wahlLesen(s), 'en');
  assert.equal(I.wahlLesen(speicher({ 'rm-sprache': 'xx' })), 'auto');
  // der neue Schlüssel hat Vorrang
  const t = speicher({ 'rm-sprache': 'en', 'runner-monitor.sprache': 'de' });
  assert.equal(I.wahlLesen(t), 'de');
});

test('Übernahme des alten Schlüssels klappt auch, wenn Schreiben scheitert', () => {
  const nurLesen = { getItem: k => (k === 'rm-sprache' ? 'en' : null), setItem() { throw new Error('voll'); }, removeItem() { throw new Error('voll'); } };
  assert.equal(I.wahlLesen(nurLesen), 'en');
});

test('Englisch: Platzhalter stimmen, Hinweistext vorhanden', () => {
  assert.equal(I.WAHLEN.join(), 'auto,de,en');
  const ph = x => (x.match(/\{(\w+)\}/g) || []).sort().join();
  for (const [de, en] of Object.entries(I.EN)) assert.equal(ph(de), ph(en), de);
  assert.ok(I.EN['„Automatisch“ folgt der Sprache des Systems. Andere Sprachen als Deutsch zeigen Englisch. Die Wahl gilt nur für diesen Browser.']);
});
