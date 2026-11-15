// Job-Log laufender Forgejo-/Gitea-Jobs im Live-Log (#176): Umschalten Journal ↔ Job-Log, Puffer, Chip, Hinweis
// in Info. Läuft mit `node --test tests/js/*.test.mjs`
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';

const R = createRequire(import.meta.url)('../../web/runner.js');
const INFO = createRequire(import.meta.url)('../../web/info.js');

test('Job-Log ersetzt das Journal nur bei aktivem Job desselben Runners', () => {
  const jl = { runner: 'runner-vm-02', aktiv: true, schritt: { nr: 3, von: 5, name: 'Tests' } };
  assert.equal(R.mitJobLog('journal', jl, 'runner-vm-02'), 'joblog');
  assert.equal(R.mitJobLog('journal', { ...jl, aktiv: false }, 'runner-vm-02'), 'journal');   // Job zu Ende: zurück
  assert.equal(R.mitJobLog('journal', { ...jl, aktiv: 'ja' }, 'runner-vm-02'), 'journal');   // nur true zählt
  assert.equal(R.mitJobLog('journal', jl, 'runner-vm-03'), 'journal');                       // anderer Runner
  assert.equal(R.mitJobLog('journal', null, 'runner-vm-02'), 'journal');
  assert.equal(R.mitJobLog('seiten', jl, 'runner-vm-02'), 'seiten');                         // GitHub: Schritt-Seiten bleiben
  assert.equal(R.mitJobLog('datei', jl, 'runner-vm-02'), 'datei');
  assert.equal(R.mitJobLog(null, jl, 'runner-vm-02'), null);
  assert.equal(R.mitJobLog('journal', jl, ''), 'journal');
});

test('Puffer: „neu“ ersetzt, sonst anhängen, begrenzt, kaputte Zeilen raus', () => {
  let p = R.puffer([], { neu: true, zeilen: [{ text: 'a' }, { text: 'b' }] });
  p = R.puffer(p, { zeilen: [{ text: 'c' }, null, 'x'] });
  assert.deepEqual(p.map((z) => z.text), ['a', 'b', 'c']);
  assert.deepEqual(R.puffer(p, { neu: true, zeilen: [] }), []);
  assert.deepEqual(R.puffer(p, null), p);
  assert.deepEqual(R.puffer(undefined, { zeilen: 'kaputt' }), []);
  const viele = Array.from({ length: 30 }, (_, i) => ({ text: String(i) }));
  assert.deepEqual(R.puffer([], { zeilen: viele }, 10).map((z) => z.text), viele.slice(-10).map((z) => z.text));
});

test('Schritt-Chip: aus dem Job-Log, sonst aus der Abfrage', () => {
  const job = { schritt: { nr: 2, von: 5, name: 'checkout' } };
  assert.deepEqual(R.jobLogSchritt({ schritt: { nr: 3, von: 5, name: 'Tests' } }, job), { nr: 3, von: 5, name: 'Tests' });
  assert.deepEqual(R.jobLogSchritt({ schritt: null }, job), job.schritt);
  assert.equal(R.jobLogSchritt(null, null), null);
});

/* Ablauf wie im Dashboard: Journal läuft, Job startet (joblog aktiv), Job endet – das Journal ist danach mit allen
   Zeilen wieder da, die während des Jobs kamen; beim nächsten Job kommt das Job-Log mit seinem Stand. */
test('Umschalten Journal → Job-Log → Journal ohne Verlust', () => {
  const S = { quelle: 'journal', puffer: { journal: [], joblog: [] }, jobLog: null, gezeigt: [] };
  const zeige = (q) => { S.gezeigt = q === 'journal' || q === 'joblog' ? [...S.puffer[q]] : []; };
  const empfange = (bereich, d) => {
    if (bereich === 'journal') { S.puffer.journal = R.puffer(S.puffer.journal, d); if (S.quelle === 'journal') S.gezeigt.push(...d.zeilen); return; }
    S.puffer.joblog = R.puffer(S.puffer.joblog, d);
    S.jobLog = { runner: d.runner, aktiv: d.aktiv === true, schritt: d.schritt || null };
    const neu = R.mitJobLog('journal', S.jobLog, 'runner-vm-02');
    if (neu !== S.quelle) { S.quelle = neu; zeige(neu); } else if (neu === 'joblog') { if (d.neu) S.gezeigt = []; S.gezeigt.push(...d.zeilen); }
  };
  empfange('journal', { neu: true, zeilen: [{ text: 'task 2991 repo is beispiel-org/web-portal' }] });
  empfange('joblog', { runner: 'runner-vm-02', neu: true, aktiv: false, zeilen: [] });   // Anmelden ohne Job
  assert.equal(S.quelle, 'journal');
  empfange('joblog', { runner: 'runner-vm-02', neu: true, aktiv: true, zeilen: [{ art: 'schritt', nr: 2, von: 4, name: 'Tests' }, { text: 'Ran 584 tests' }] });
  assert.equal(S.quelle, 'joblog');
  assert.deepEqual(S.gezeigt.map((z) => z.text || z.name), ['Tests', 'Ran 584 tests']);
  empfange('journal', { zeilen: [{ text: 'level=debug fetch' }] });                    // wird gepuffert, nicht gezeigt
  empfange('joblog', { runner: 'runner-vm-02', aktiv: true, zeilen: [{ text: 'OK' }] });
  assert.deepEqual(S.gezeigt.map((z) => z.text || z.name), ['Tests', 'Ran 584 tests', 'OK']);
  empfange('joblog', { runner: 'runner-vm-02', aktiv: false, zeilen: [] });            // Job zu Ende
  assert.equal(S.quelle, 'journal');
  assert.deepEqual(S.gezeigt.map((z) => z.text), ['task 2991 repo is beispiel-org/web-portal', 'level=debug fetch']);
});

test('Dashboard: Ereignis „joblog“ abonniert, nur für den Runner des Live-Stroms, Puffer und Chip', () => {
  const d = readFileSync(new URL('../../web/dashboard.js', import.meta.url), 'utf8');
  assert.match(d, /'log', 'journal', 'joblog', 'runner'/);
  assert.match(d, /case 'joblog':/);
  assert.match(d, /d\.runner !== S\.stromJournal\) break;/);
  assert.match(d, /RUNNER\.mitJobLog\(S\.status\.logQuelle, S\.jobLog, r\.id\)/);
  assert.match(d, /RUNNER\.jobLogSchritt\(S\.jobLog, j\)/);
  assert.match(d, /z\.art === 'gekuerzt'/);
});

test('Info › Verbindungen: Hinweis nur, wenn der Sammler das Job-Log nicht lesen kann', () => {
  const t = (s, w = {}) => s.replace(/\{(\w+)\}/g, (_, k) => w[k]);
  const RM = { ms: (z) => z * 1000, zeit: () => '10:00', zahl: String, hm: () => '10:00', datum: () => '1.1.', mehrzahl: (n, a, b) => (n === 1 ? a : b) };
  const r = (jobLog) => ({ id: 'runner-vm-02', name: 'runner-vm-02', dienst: 'forgejo', server: 'https://git.example.org', org: 'beispiel-org',
    faehig: { jobs: true }, jobsJeRepository: { abfrage: 'ok', abgefragt: 1 }, ...(jobLog ? { jobLog } : {}) });
  const kv = (jobLog) => INFO.verbindungen([r(jobLog)], { t, RM, jetzt: 2000 })[0].kv;
  assert.equal(kv(null).find(([k]) => k === 'Job-Log'), undefined);
  assert.equal(kv({ hinweis: 'erfunden' }).find(([k]) => k === 'Job-Log'), undefined);
  const zeile = kv({ hinweis: 'keine-rechte' }).find(([k]) => k === 'Job-Log');
  assert.deepEqual([zeile[0], zeile[2]], ['Job-Log', 'warn']);
  assert.match(zeile[1], /Token darf die Job-Logs nicht lesen/);
  assert.match(kv({ hinweis: 'nicht-unterstuetzt' }).find(([k]) => k === 'Job-Log')[1], /nicht angeboten/);
  assert.match(kv({ hinweis: 'zu-gross' }).find(([k]) => k === 'Job-Log')[1], /Range/);
});
