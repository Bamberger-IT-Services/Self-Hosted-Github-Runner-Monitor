/* Verlauf mit festen Zeitfenstern (Design 0.8.0, #89). Reine Rechenlogik ohne DOM, damit sie
   sich mit node prüfen lässt (tests/js/verlauf.test.mjs). Im Browser als globales VERLAUF.

   Die Werte kommen einmal je Sekunde. Sie werden in Eimer fester Größe gruppiert, deren Grenzen
   am absoluten Messzeitpunkt hängen (Eimer = floor(t / bs)), nicht am Ende der Liste. So wandert
   die Kurve jede Sekunde um eine Messung nach links, und nur der rechte Rand ändert sich.
   Bisher wurde vom Listenende aus gruppiert; dabei verschoben sich jede Sekunde alle Grenzen. */
'use strict';

const VERLAUF = (() => {
  const ZEITRAEUME = [30, 120, 300, 600];          // Sekunden
  const EIMER = { 30: 1, 120: 1, 300: 3, 600: 5 };  // Sekunden je Eimer
  const STANDARD = 600;
  const MAX_WERTE = 600;                            // so viele hält der Server (10 Min.)

  /* Gespeicherter oder übergebener Wert → gültiger Zeitraum, sonst 10 Min. */
  function zeitraum(wert) {
    const n = parseInt(wert, 10);
    return ZEITRAEUME.includes(n) ? n : STANDARD;
  }

  /* Stützpunkte [x, wert] einer Reihe.
     h      Werte, ältester zuerst, je Sekunde einer
     ende   absolute Sekunde des letzten Werts (z. B. Unix-Zeit gerundet)
     r      Zeitraum in Sekunden, agg 'mittel' (CPU, RAM) oder 'max' (Netz: Spitzen bleiben sichtbar)
     x läuft von 0 (ältester gezeigter Wert) bis 300 (jetzt). Weniger Werte als r: über die
     ganze Breite gestreckt. */
  function punkte(h, ende, r = STANDARD, agg = 'mittel') {
    r = zeitraum(r);
    const bs = EIMER[r], L = h.length;
    if (!L) return [];
    const nS = ende + 1;                     // erste Sekunde nach dem letzten Wert
    const erste = nS - L;                    // absolute Sekunde von h[0]
    const spanne = Math.max(2, Math.min(r, L));
    const a0 = nS - spanne;                  // erste gezeigte Sekunde
    const pts = [];
    for (let q = Math.floor(a0 / bs); q * bs < nS; q++) {
      const von = Math.max(q * bs, a0), bis = Math.min((q + 1) * bs, nS);
      let s = 0, c = 0, mx = -Infinity;
      for (let k = von; k < bis; k++) {
        const v = h[k - erste];
        if (v == null || !Number.isFinite(v)) continue;
        s += v; c++; if (v > mx) mx = v;
      }
      if (!c) continue;
      const x = Math.min(300, Math.max(0, (bis - 1 - a0) / (spanne - 1) * 300));
      pts.push([x, agg === 'max' ? mx : s / c]);
    }
    if (pts.length && pts[0][0] > 0) pts.unshift([0, pts[0][1]]);  // Fläche beginnt immer links
    return pts;
  }

  /* SVG-Pfade [Linie, Fläche] für viewBox 0 0 300 46; max = Skala (100 % bzw. Netz-Spitze). */
  function pfade(h, ende, r, max = 100, agg = 'mittel') {
    const pts = punkte(h, ende, r, agg);
    if (!pts.length) return ['', ''];
    const y = v => 45 - Math.max(0, Math.min(1, v / (max || 1))) * 43;
    const linie = 'M' + pts.map(([x, v]) => `${x.toFixed(1)},${y(v).toFixed(1)}`).join(' L');
    return [linie, `${linie} L300.0,46 L0.0,46 Z`];
  }

  /* Höchster Wert der letzten r Sekunden (Netz-Skala), mindestens untergrenze. */
  function spitze(reihen, r, untergrenze = 0) {
    let m = 0;
    for (const h of reihen) for (let i = Math.max(0, h.length - zeitraum(r)); i < h.length; i++) if (h[i] > m) m = h[i];
    return { spitze: m, skala: Math.max(m, untergrenze) };
  }

  /* Reicht der Verlauf für den ganzen Zeitraum? Sonst steht links „seit hh:mm“. */
  const voll = (n, r) => n >= zeitraum(r);

  return { ZEITRAEUME, EIMER, STANDARD, MAX_WERTE, zeitraum, punkte, pfade, spitze, voll };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VERLAUF;
