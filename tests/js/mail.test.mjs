// E-Mail-Vorlagen für Fehler, Idee und Update-Fehler (#98). Läuft mit `node --test tests/js/*.test.mjs`
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';

const M = createRequire(import.meta.url)('../../web/mail.js');

// t() wie in der Oberfläche: Platzhalter ersetzen, Text sonst unverändert (Deutsch)
const t = (text, w) => (w ? text.replace(/\{(\w+)\}/g, (m, k) => (k in w ? String(w[k]) : m)) : text);
const tEn = (text, w) => t({ 'Was ist passiert?': 'What happened?', 'Runner-Monitor {v} – Fehler': 'Runner Monitor {v} – bug' }[text] || text, w);

const angaben = {
  version: '0.8.0', system: 'Ubuntu 24.04.1 LTS, Python 3.12', browser: 'Mozilla/5.0 (X11; Linux x86_64) Test/1.0',
  runner: [{ name: 'runner-vm-01', dienst: 'GitHub', version: '2.338.1' }],
  gewaehlt: { name: 'runner-vm-01', zustand: 'Dienst aktiv' },
};

function teile(url) {
  assert.ok(url.startsWith(`mailto:${M.ADRESSE}?subject=`));
  const q = new URLSearchParams(url.slice(url.indexOf('?') + 1));
  return { betreff: q.get('subject'), text: q.get('body') };
}

test('Fehler: Betreff, Text und technische Angaben', () => {
  const { betreff, text } = teile(M.fehler(angaben, t));
  assert.equal(betreff, 'Runner-Monitor 0.8.0 – Fehler');
  for (const s of ['Was ist passiert?', 'Was hätte passieren sollen?', 'So lässt es sich nachstellen:',
    'Version: Runner-Monitor 0.8.0', 'System: Ubuntu 24.04.1 LTS, Python 3.12', 'Runner: runner-vm-01 (GitHub 2.338.1)',
    'Gewählt: runner-vm-01 · Dienst aktiv', 'Browser: Mozilla/5.0', 'Bitte keine Tokens oder Passwörter mitschicken.']) {
    assert.ok(text.includes(s), s);
  }
  assert.ok(text.includes('\r\n'), 'Zeilenumbrüche als CRLF');
});

test('Kodierung: Umlaute und Sonderzeichen überstehen den Weg durch die Adresse', () => {
  const url = M.fehler(angaben, t);
  assert.ok(!/[^\x21-\x7e]/.test(url), 'nur ASCII ohne Leerzeichen und Umbrüche');
  assert.ok(url.includes('%C3%A4'), 'ä als UTF-8');
  assert.equal(url.split('&').length, 2, 'genau ein & zwischen subject und body');
  const { text } = teile(M.fehler({ ...angaben, system: 'Ä&ö=ü?#% ß' }, t));
  assert.ok(text.includes('System: Ä&ö=ü?#% ß'));
});

test('Sprache folgt t()', () => {
  const { betreff, text } = teile(M.fehler(angaben, tEn));
  assert.equal(betreff, 'Runner Monitor 0.8.0 – bug');
  assert.ok(text.includes('What happened?'));
});

test('Idee: Betreff, Abschnitte, Version', () => {
  const { betreff, text } = teile(M.idee(angaben, t));
  assert.equal(betreff, 'Runner-Monitor 0.8.0 – Idee');
  for (const s of ['Worum geht es?', 'Warum wäre das hilfreich?', 'Version: Runner-Monitor 0.8.0']) assert.ok(text.includes(s), s);
});

test('Update-Fehler: Betreff mit neuer Version, Platz für das Journal', () => {
  const { betreff, text } = teile(M.updateFehler({ ...angaben, neu: '0.8.1', meldung: 'Neustart ohne Antwort' }, t));
  assert.equal(betreff, 'Runner-Monitor – Update auf 0.8.1 fehlgeschlagen');
  assert.ok(text.includes('journalctl -u runner-monitor-update -n 50'));
  assert.ok(text.includes('Meldung: Neustart ohne Antwort'));
  assert.ok(text.includes('0.8.1'));
});

test('Keine Tokens im Text', () => {
  const geheim = 'ghp_' + 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4';
  const pat = 'github_pat_' + '11ABCDEFG0abcdefghijkl_mnopqrstuv';
  const a = { ...angaben, system: `x ${geheim}`, browser: pat, runner: [{ name: 'r', dienst: 'GitHub', version: geheim }] };
  for (const url of [M.fehler(a, t), M.idee(a, t), M.updateFehler({ ...a, neu: '1', meldung: `Token ${pat}` }, t)]) {
    const roh = decodeURIComponent(url);
    assert.ok(!roh.includes(geheim) && !roh.includes(pat) && !roh.includes('ghp_') && !roh.includes('github_pat_'));
  }
});

test('Länge der Adresse bleibt vertretbar, auch mit langem userAgent', () => {
  const lang = { ...angaben, browser: 'Mozilla/5.0 ' + 'x'.repeat(2000) };
  for (const url of [M.fehler(lang, t), M.idee(lang, t), M.updateFehler({ ...lang, neu: '0.8.1', meldung: 'm'.repeat(300) }, t)]) {
    assert.ok(url.length < 2000, `Länge ${url.length}`);
  }
});

test('Fehlende Angaben ergeben Striche statt "undefined"', () => {
  const { text } = teile(M.fehler({}, t));
  assert.ok(!text.includes('undefined') && !text.includes('null'));
  assert.ok(text.includes('Runner: –'));
});

test('Oberfläche verlinkt nicht mehr auf GitHub-Issues', () => {
  for (const f of ['dashboard.js', 'mail.js', 'dashboard.html']) {
    const s = readFileSync(new URL(`../../web/${f}`, import.meta.url), 'utf8');
    assert.ok(!/issues\/new/.test(s), f);
  }
});
