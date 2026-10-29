// Doku-Links auf den Tag der laufenden Version (#132, E-28). `node --test tests/js/*.test.mjs`
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const DOKU = createRequire(import.meta.url)('../../web/doku.js');
const B = 'https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/blob/';

test('ohne bekannte Version: main als Rückfall', () => {
  DOKU.setzeVersion('');
  assert.equal(DOKU.url('FUNKTIONSWEISE.md'), `${B}main/docs/FUNKTIONSWEISE.md`);
});

test('mit Release-Version: Tag und Anker', () => {
  DOKU.setzeVersion('0.8.1');
  assert.equal(DOKU.url('EINRICHTUNG.md', 'gitlab-anbinden'), `${B}v0.8.1/docs/EINRICHTUNG.md#gitlab-anbinden`);
});

test('Entwicklungsstand oder Unsinn: main', () => {
  for (const v of ['0.9.0-dev', 'dev', null, undefined, '1.2']) {
    DOKU.setzeVersion(v);
    assert.ok(DOKU.url('UPDATE.md').startsWith(`${B}main/`), String(v));
  }
});
