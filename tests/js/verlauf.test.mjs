// Verlauf mit festen Zeitfenstern (#89). Läuft mit `node --test tests/js/*.test.mjs` (in der CI)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const V = createRequire(import.meta.url)('../../web/verlauf.js');
const reihe = (n, f = i => (i * 37) % 100) => Array.from({ length: n }, (_, i) => f(i));

test('Zeitraum: nur 30/120/300/600, sonst 10 Min.', () => {
  for (const r of [30, 120, 300, 600]) assert.equal(V.zeitraum(r), r);
  for (const r of ['120', 120.4]) assert.equal(V.zeitraum(r), 120);
  for (const r of [null, undefined, '', 'abc', 0, 60, -30, 1e9]) assert.equal(V.zeitraum(r), 600);
});

test('Eimergrößen nach Design', () => {
  assert.deepEqual(V.EIMER, { 30: 1, 120: 1, 300: 3, 600: 5 });
});

test('neuer Wert ändert nur den rechten Rand (feste Eimergrenzen)', () => {
  const h = reihe(900, i => (i * 7919) % 1009);   // ungleichmäßig, damit Verwechslungen auffallen
  for (const r of [30, 120, 300, 600]) {
    const bs = V.EIMER[r], schritt = 300 / (r - 1);
    for (let versatz = 0; versatz < bs * 2; versatz++) {
      const ende = 10_000 + versatz, n = 700;
      const vorher = V.punkte(h.slice(0, n), ende, r);
      const nachher = V.punkte(h.slice(0, n + 1), ende + 1, r);
      // Punkte nach absoluter Endsekunde des Eimers ordnen (x → Sekunde zurückrechnen)
      const nachSekunde = (p, e) => new Map(p.map(([x, v]) => [Math.round(e + 1 - r + x / schritt), [x, v]]));
      const a = nachSekunde(vorher, ende), b = nachSekunde(nachher, ende + 1);
      let gleich = 0;
      for (const [s, [x, v]] of b) {
        if (s >= Math.floor(ende / bs) * bs) continue;  // rechter Rand (offener Eimer): darf sich ändern
        if (!a.has(s)) continue;                     // links neu hereingewandert / Rand
        const [x0, v0] = a.get(s);
        if (s - bs + 1 < ende + 2 - r) continue;      // linker Rand: Eimer ist angeschnitten
        assert.equal(v, v0, `r=${r} v=${versatz}: Eimer bis Sekunde ${s} hat sich geändert`);
        assert.ok(Math.abs(x0 - schritt - x) < 1e-9, `r=${r}: Punkt springt statt zu wandern`);
        gleich++;
      }
      assert.ok(gleich >= Math.floor(r / bs) - 3, `r=${r} v=${versatz}: zu wenige unveränderte Eimer (${gleich})`);
      // Der rechte Rand ist „jetzt“
      assert.equal(nachher.at(-1)[0], 300);
    }
  }
});

test('Eimergrenze hängt an der absoluten Sekunde, nicht am Listenende', () => {
  // 5-s-Eimer: Werte 0..9 in Sekunde 100..109 → Eimer 100–104 und 105–109
  const h = [0, 0, 0, 0, 0, 10, 10, 10, 10, 10];
  const p = V.punkte(h, 109, 600);
  assert.deepEqual(p.map(([, v]) => v), [0, 0, 10]);
  // eine Sekunde später, ein neuer Wert: angebrochener Eimer 110 rechts, die alten bleiben
  const q = V.punkte([...h, 50], 110, 600);
  assert.deepEqual(q.map(([, v]) => v), [0, 0, 10, 50]);
});

test('letzter Wert bei x = 300 („jetzt“), ältester bei 0', () => {
  for (const r of [30, 120, 300, 600]) {
    for (const n of [1, 2, 7, 29, 30, 31, 150, 600]) {
      const p = V.punkte(reihe(n), 5000 + n, r);
      assert.equal(p[0][0], 0, `r=${r} n=${n}`);
      assert.equal(p.at(-1)[0], 300, `r=${r} n=${n}`);
      for (let i = 1; i < p.length; i++) assert.ok(p[i][0] > p[i - 1][0], 'x steigt');
    }
  }
});

test('kürzerer Verlauf füllt die ganze Breite, ein Wert ist eine waagerechte Linie', () => {
  const p = V.punkte([42], 7, 600);
  assert.deepEqual(p, [[0, 42], [300, 42]]);
  const q = V.punkte(reihe(150), 3000, 600);    // 2,5 Min. bei Zeitraum 10 Min.
  assert.equal(q[0][0], 0); assert.equal(q.at(-1)[0], 300);
  assert.equal(V.voll(150, 600), false); assert.equal(V.voll(150, 120), true);
});

test('Zeitraum 30 s zeigt nur die letzten 30 Werte', () => {
  const h = reihe(600, i => (i < 570 ? 0 : 80));
  const p = V.punkte(h, 1000, 30);
  assert.ok(p.every(([, v]) => v === 80));
  assert.equal(p.length, 30);
});

test('Mittelwert für CPU/RAM, Maximum für Netz', () => {
  const h = [0, 0, 100, 0, 0];   // ein Eimer zu 5 s (Sekunde 0..4)
  assert.deepEqual(V.punkte(h, 4, 600).map(([, v]) => v), [20, 20]);
  assert.deepEqual(V.punkte(h, 4, 600, 'max').map(([, v]) => v), [100, 100]);
});

test('Pfade: Skala begrenzt, Fläche geschlossen, leer ohne Werte', () => {
  assert.deepEqual(V.pfade([], 1, 600), ['', '']);
  const [linie, flaeche] = V.pfade([200, 200], 1, 30, 100);
  assert.equal(linie, 'M0.0,2.0 L300.0,2.0');
  assert.ok(flaeche.endsWith(' L300.0,46 L0.0,46 Z'));
});

test('Netz-Spitze im gewählten Zeitraum, Untergrenze 64 KB/s', () => {
  const rx = reihe(600, i => (i === 10 ? 5e6 : 1e3)), tx = reihe(600, () => 2e3);
  assert.deepEqual(V.spitze([rx, tx], 600, 64e3), { spitze: 5e6, skala: 5e6 });
  assert.deepEqual(V.spitze([rx, tx], 120, 64e3), { spitze: 2e3, skala: 64e3 });
});

test('Lücken und kaputte Werte werfen nicht', () => {
  const p = V.punkte([1, null, NaN, 3, undefined, 5], 20, 30);
  assert.ok(p.length > 0);
  assert.ok(p.every(([x, v]) => Number.isFinite(x) && Number.isFinite(v)));
});
