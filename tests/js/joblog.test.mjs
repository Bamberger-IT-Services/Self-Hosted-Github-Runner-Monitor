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
  assert.equal(R.mitJobLog('journal', { ...jl, aktiv: false }, 'runner-vm-02'), 'journal');   // nicht aktiv, nicht beendet
  assert.equal(R.mitJobLog('journal', { ...jl, aktiv: false, beendet: true }, 'runner-vm-02'), 'joblog');   // E-35 b: bleibt stehen
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

/* Ablauf wie im Dashboard (dashboard.js › case 'joblog' und setzeLogQuelle): Journal läuft, Job startet (joblog
   aktiv), Job endet – die Ausgabe bleibt stehen (E-35 b), das Journal puffert weiter; der nächste Job ersetzt die
   Ausgabe, ein Wechsel des Runners führt zurück aufs Journal, mit allen Zeilen, die inzwischen kamen. */
function dashboard(id = 'runner-vm-02') {
  const S = { id, quelle: 'journal', puffer: { journal: [], joblog: [] }, jobLog: null, gezeigt: [] };
  const zeige = (q) => { S.gezeigt = q === 'journal' || q === 'joblog' ? [...S.puffer[q]] : []; };
  S.empfange = (bereich, d) => {
    if (bereich === 'journal') { S.puffer.journal = R.puffer(S.puffer.journal, d); if (S.quelle === 'journal') S.gezeigt.push(...d.zeilen); return; }
    if (d.runner !== S.id) return;
    const e = R.jobLogEmpfang(S.jobLog, S.puffer.joblog, d);
    S.puffer.joblog = e.puffer; S.jobLog = e.jobLog;
    const neu = R.mitJobLog('journal', S.jobLog, S.id);
    if (neu !== S.quelle) { S.quelle = neu; zeige(neu); } else if (neu === 'joblog') { if (e.leeren) S.gezeigt = []; S.gezeigt.push(...e.zeilen); }
  };
  S.runnerWechsel = (neuId) => { S.id = neuId; S.jobLog = null; S.puffer = { journal: [], joblog: [] }; S.quelle = 'journal'; S.gezeigt = []; };
  S.text = () => S.gezeigt.map((z) => z.text || z.name);
  return S;
}
const START = { runner: 'runner-vm-02', neu: true, aktiv: true, job: 41, schritt: { nr: 2, von: 4, name: 'Tests' },
  zeilen: [{ art: 'schritt', nr: 2, von: 4, name: 'Tests' }, { text: 'Ran 584 tests' }] };

test('Job-Ende: die Ausgabe bleibt stehen, das Journal puffert weiter (E-35 b)', () => {
  const S = dashboard();
  S.empfange('journal', { neu: true, zeilen: [{ text: 'task 2991 repo is beispiel-org/web-portal' }] });
  S.empfange('joblog', { runner: 'runner-vm-02', neu: true, aktiv: false, zeilen: [] });   // Anmelden ohne Job
  assert.equal(S.quelle, 'journal');
  assert.equal(S.jobLog.beendet, false);
  S.empfange('joblog', START);
  assert.equal(S.quelle, 'joblog');
  assert.deepEqual(S.text(), ['Tests', 'Ran 584 tests']);
  S.empfange('journal', { zeilen: [{ text: 'level=debug fetch' }] });                    // gepuffert, nicht gezeigt
  S.empfange('joblog', { runner: 'runner-vm-02', aktiv: true, job: 41, schritt: START.schritt, zeilen: [{ text: 'OK' }] });
  assert.deepEqual(S.text(), ['Tests', 'Ran 584 tests', 'OK']);
  // letzter Stand des Lesers (gleicher Lauf, aktiv false), dann fehlt er in joblog.json: neuer, leerer Stand
  S.empfange('joblog', { runner: 'runner-vm-02', aktiv: false, job: 41, schritt: START.schritt, zeilen: [{ text: 'Cleaning up' }] });
  S.empfange('joblog', { runner: 'runner-vm-02', neu: true, aktiv: false, job: null, schritt: null, zeilen: [] });
  assert.equal(S.quelle, 'joblog');
  assert.deepEqual(S.text(), ['Tests', 'Ran 584 tests', 'OK', 'Cleaning up']);
  assert.deepEqual([S.jobLog.aktiv, S.jobLog.beendet, S.jobLog.job, S.jobLog.schritt.name], [false, true, 41, 'Tests']);
  S.empfange('journal', { zeilen: [{ text: 'task 41 finished' }] });                     // läuft weiter in den Puffer
  S.empfange('joblog', { runner: 'runner-vm-02', neu: true, aktiv: false, zeilen: [] }); // Neuverbinden: bleibt
  assert.equal(S.quelle, 'joblog');
  assert.deepEqual(S.puffer.journal.map((z) => z.text), ['task 2991 repo is beispiel-org/web-portal', 'level=debug fetch', 'task 41 finished']);
});

test('Neuer Job nach dem Ende: dessen Ausgabe ersetzt die alte', () => {
  const S = dashboard();
  S.empfange('joblog', START);
  S.empfange('joblog', { runner: 'runner-vm-02', neu: true, aktiv: false, zeilen: [] });
  assert.equal(S.jobLog.beendet, true);
  S.empfange('joblog', { runner: 'runner-vm-02', neu: true, aktiv: true, job: 42, schritt: { nr: 1, von: 3, name: 'Set up job' }, zeilen: [{ text: 'neuer Job' }] });
  assert.equal(S.quelle, 'joblog');
  assert.deepEqual([S.jobLog.aktiv, S.jobLog.beendet, S.jobLog.job], [true, false, 42]);
  assert.deepEqual(S.text(), ['neuer Job']);
  assert.deepEqual(S.puffer.joblog.map((z) => z.text), ['neuer Job']);
});

test('Runner-Wechsel nach dem Ende: zurück aufs Journal', () => {
  const S = dashboard();
  S.empfange('joblog', START);
  S.empfange('joblog', { runner: 'runner-vm-02', neu: true, aktiv: false, zeilen: [] });
  assert.equal(S.quelle, 'joblog');
  S.runnerWechsel('runner-vm-03');
  S.empfange('journal', { neu: true, zeilen: [{ text: 'Journal von runner-vm-03' }] });
  S.empfange('joblog', { runner: 'runner-vm-03', neu: true, aktiv: false, zeilen: [] });
  assert.equal(S.quelle, 'journal');
  assert.deepEqual(S.text(), ['Journal von runner-vm-03']);
  // Ereignisse für den alten Runner zählen nicht mehr
  S.empfange('joblog', { runner: 'runner-vm-02', neu: true, aktiv: true, zeilen: [{ text: 'fremd' }] });
  assert.equal(S.quelle, 'journal');
});

test('Job-Log-Stand: beendet nur nach einem eigenen Job mit Ausgabe, nie mit Hinweis', () => {
  const aktiv = { runner: 'runner-vm-02', aktiv: true, beendet: false, job: 7, schritt: { nr: 3, von: 5, name: 'Tests' }, hinweis: null };
  const ende = { runner: 'runner-vm-02', neu: true, aktiv: false, zeilen: [] };
  assert.equal(R.jobLogStand(aktiv, ende).beendet, true);
  assert.equal(R.jobLogStand(aktiv, ende, false).beendet, false);                          // ohne Ausgabe: Journal
  assert.equal(R.jobLogStand(null, ende).beendet, false);                                   // Fenster neu geöffnet
  assert.equal(R.jobLogStand({ ...aktiv, runner: 'runner-vm-03' }, ende).beendet, false);   // anderer Runner
  assert.equal(R.jobLogStand(aktiv, { ...ende, hinweis: 'keine-rechte' }).beendet, false);  // Sammler kann nicht lesen
  assert.equal(R.mitJobLog('journal', R.jobLogStand(aktiv, { ...ende, hinweis: 'zu-gross' }), 'runner-vm-02'), 'journal');
  assert.equal(R.mitJobLog('journal', R.jobLogStand(aktiv, ende), 'runner-vm-02'), 'joblog');
  assert.equal(R.mitJobLog('seiten', R.jobLogStand(aktiv, ende), 'runner-vm-02'), 'seiten');
  const e = R.jobLogEmpfang(aktiv, [{ text: 'a' }], ende);
  assert.deepEqual([e.leeren, e.puffer.map((z) => z.text), e.zeilen], [false, ['a'], []]);
  const f = R.jobLogEmpfang(null, [{ text: 'a' }], ende);                                   // kein Job vorher: „neu“ leert
  assert.deepEqual([f.leeren, f.puffer], [true, []]);
});

test('Dashboard: Ereignis „joblog“ abonniert, nur für den Runner des Live-Stroms, Puffer und Chip', () => {
  const d = readFileSync(new URL('../../web/dashboard.js', import.meta.url), 'utf8');
  assert.match(d, /'log', 'journal', 'joblog', 'runner'/);
  assert.match(d, /case 'joblog':/);
  assert.match(d, /d\.runner !== S\.stromJournal\) break;/);
  assert.match(d, /RUNNER\.mitJobLog\(S\.status\.logQuelle, S\.jobLog, r\.id\)/);
  assert.match(d, /RUNNER\.jobLogSchritt\(S\.jobLog, j\)/);
  assert.match(d, /RUNNER\.jobLogEmpfang\(S\.jobLog, S\.nebenPuffer\.joblog, d, MAX_ZEILEN\)/);
  assert.match(d, /if \(e\.leeren\) leereLog\(\);/);
  assert.match(d, /t\('Job beendet'\)/);
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
