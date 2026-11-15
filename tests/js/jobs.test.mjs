// Laufende und wartende Jobs je Repository (Design 0.9.0, #171): Restzeit, Texte, Aufklappen, wartende Läufe, gemerkte
// Höhe des Live-Logs. Läuft mit `node --test tests/js/*.test.mjs`
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';

const J = createRequire(import.meta.url)('../../web/jobs.js');
const I18N = createRequire(import.meta.url)('../../web/i18n.js');

const JETZT = Date.UTC(2026, 10, 15, 17, 0, 0);          // 15.11.2026 17:00:00 UTC
const sek = (n) => n * 1000;
const p2 = (v) => String(v).padStart(2, '0');
// Hilfen wie in dashboard.js, aber deutsch, ohne DOM und ohne Zeitzone (UTC)
const f = {
  t: (text, w) => (w ? text.replace(/\{(\w+)\}/g, (m, k) => (k in w ? String(w[k]) : m)) : text),
  esc: (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
  IC: { dreieck: () => '<svg class="dreieck"></svg>', uhr: () => '<svg class="uhr"></svg>', schloss: () => '<svg class="schloss"></svg>', chev: (o) => `<svg class="chev${o ? ' offen' : ''}"></svg>` },
  dauer: (s) => { s = Math.round(s); const m = Math.floor(s / 60); return `${m}:${p2(s % 60)}`; },
  seit: (s) => { s = Math.round(s); if (s < 60) return `${s} s`; const m = Math.floor(s / 60); return m < 60 ? `${m} Min.` : `${Math.floor(m / 60)} Std. ${m % 60} Min.`; },
  hm: (z) => { const d = new Date(z); return `${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}`; },
  zeit: (z) => { const d = new Date(z < 1e12 ? z * 1000 : z); return `${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}:${p2(d.getUTCSeconds())}`; },
  mehrzahl: (n, eins, viele) => (n === 1 ? eins : viele),
};

const vor = (s) => (JETZT - sek(s)) / 1000;                // Unix-Sekunden, s Sekunden vor „jetzt“
const job = (extra = {}) => ({
  repo: 'web-portal', privat: true, workflow: 'ci', name: 'test', ref: { art: 'PR', name: '#142', titel: 'Suche im Kundenbereich' },
  runner: 'runner-vm-01', eigener: true, start: vor(402), schritt: { nr: 7, von: 8, name: 'Build', start: vor(95) }, vergleich: { median: 660, anzahl: 5 }, ...extra,
});

/* ---------------------------------------------------------------- Restzeit */

test('Restzeit: noch n Sekunden, Fertigzeit und Anteil', () => {
  const r = J.restzeit(vor(402), { median: 660, anzahl: 5 }, JETZT);
  assert.equal(r.art, 'rest');
  assert.equal(Math.round(r.rest), 258);
  assert.equal(r.fertig, JETZT + 258 * 1000);
  assert.ok(Math.abs(r.anteil - 402 / 660) < 1e-9);
  assert.equal(r.median, 660);
  assert.equal(r.anzahl, 5);
});

test('Restzeit: Median überschritten – „länger als üblich“, nie eine negative Zeit', () => {
  for (const lauf of [660, 661, 5000]) {
    const r = J.restzeit(vor(lauf), { median: 660, anzahl: 3 }, JETZT);
    assert.equal(r.art, 'laenger', String(lauf));
    assert.equal(r.rest, undefined);
    assert.equal(r.anteil, 1);
  }
});

test('Restzeit: ohne brauchbare Vergleichswerte keine Schätzung', () => {
  for (const v of [null, undefined, {}, { median: 0, anzahl: 1 }, { median: -5, anzahl: 1 }, { median: 'x', anzahl: 1 }, { median: NaN }, { median: Infinity }]) {
    assert.equal(J.restzeit(vor(60), v, JETZT).art, 'keine', JSON.stringify(v));
  }
  // ohne Beginn lässt sich nichts rechnen
  for (const s of [null, undefined, 'kein Datum']) assert.equal(J.restzeit(s, { median: 600, anzahl: 5 }, JETZT).art, 'keine');
});

test('Restzeit: Beginn in der Zukunft (Uhren) zählt als 0 Sekunden, ISO-Zeit und Millisekunden gehen auch', () => {
  assert.equal(J.restzeit(vor(-30), { median: 600, anzahl: 1 }, JETZT).anteil, 0);
  assert.equal(Math.round(J.restzeit(new Date(JETZT - 60000).toISOString(), { median: 600, anzahl: 1 }, JETZT).rest), 540);
  assert.equal(Math.round(J.restzeit(JETZT - 60000, { median: 600, anzahl: 1 }, JETZT).rest), 540);
});

test('Restzeit: Texte „noch ca.“, „ca. HH:MM fertig“, „länger als üblich“, „keine Schätzung“', () => {
  const rest = J.restText(J.restzeit(vor(402), { median: 660, anzahl: 5 }, JETZT), f);
  assert.equal(rest.haupt, 'noch ca. 4 Min.');
  assert.equal(rest.sub, 'ca. 17:04 fertig · üblich ca. 11 Min.');
  assert.equal(rest.cls, '');
  assert.equal(rest.pct, '61 %');
  assert.match(rest.titel, /Median der letzten 5 erfolgreichen Läufe/);
  assert.equal(rest.aria, '61 % der üblichen Laufzeit');
  assert.ok(rest.anteil > 0.6 && rest.anteil < 0.62);

  const lang = J.restText(J.restzeit(vor(900), { median: 600, anzahl: 5 }, JETZT), f);
  assert.deepEqual([lang.haupt, lang.sub, lang.cls, lang.anteil], ['länger als üblich', 'üblich ca. 10 Min.', 'lang', 1]);

  const keine = J.restText(J.restzeit(vor(900), null, JETZT), f);
  assert.deepEqual([keine.haupt, keine.cls, keine.anteil, keine.pct], ['keine Schätzung', 'keine', 0, '']);
});

test('Restzeit: ein Vergleichslauf heißt „letzter Lauf“, Rundung auf ganze Minuten, mindestens eine, Stunden', () => {
  assert.match(J.restText(J.restzeit(vor(10), { median: 400, anzahl: 1 }, JETZT), f).titel, /^Dauer des letzten erfolgreichen Laufs/);
  assert.equal(J.restText(J.restzeit(vor(580), { median: 600, anzahl: 2 }, JETZT), f).haupt, 'noch ca. 1 Min.');     // 20 s
  assert.equal(J.restText(J.restzeit(vor(0), { median: 5400, anzahl: 2 }, JETZT), f).haupt, 'noch ca. 1 Std. 30 Min.');
});

/* ---------------------------------------------------------------- Gruppieren, Aufklappen */

test('nachRepo: laufende und wartende Jobs je Repository, Fehlendes und Fehlerhaftes ergibt leere Listen', () => {
  const je = J.nachRepo({ laufende: [job(), job({ name: 'lint' }), { repo: 'api-dienst' }, null, 5, { name: 'ohne Repo' }], wartende: [{ repo: 'api-dienst', workflow: 'ci' }] });
  assert.deepEqual(Object.keys(je.laufende).sort(), ['api-dienst', 'web-portal']);
  assert.equal(je.laufende['web-portal'].length, 2);
  assert.equal(je.wartende['api-dienst'].length, 1);
  for (const leer of [null, undefined, {}, { laufende: 'x', wartende: {} }]) { const j = J.nachRepo(leer); assert.deepEqual([Object.keys(j.laufende), Object.keys(j.wartende)], [[], []]); }
});

test('aufgeklappt: die Wahl gilt, sonst offen, wenn dort etwas läuft', () => {
  assert.equal(J.istOffen({}, 'a', 1), true);
  assert.equal(J.istOffen({}, 'a', 0), false);
  assert.equal(J.istOffen({ a: false }, 'a', 2), false);
  assert.equal(J.istOffen({ a: true }, 'a', 0), true);
  assert.equal(J.istOffen(null, 'a', 1), true);
});

/* ---------------------------------------------------------------- HTML */

const alle = (h) => h.replace(/\s+/g, ' ');

test('Repository mit laufendem Job: Knopf zum Aufklappen, Workflow und Job, Branch/PR, Runner, Schritt „7 von 8“', () => {
  const h = J.repoHtml({ name: 'web-portal', privat: true, laeuft: 1, wartet: 0 }, J.nachRepo({ laufende: [job()] }), {}, f);
  assert.match(h, /<button type="button" class="repo repo-kopf" data-aktion="repo-offen" data-repo="web-portal" aria-expanded="true" aria-controls="rd-web-portal">/);
  assert.match(h, /class="chev offen"/);
  assert.match(h, /1 läuft/);
  assert.match(h, /Workflow <b>ci<\/b><span class="sep"> › <\/span>Job <b>test<\/b>/);
  assert.match(h, /<span>PR<\/span><span class="ref">#142<\/span><span class="ref-titel">Suche im Kundenbereich<\/span>/);
  assert.match(h, /Runner runner-vm-01/);
  assert.match(h, /Aktueller Schritt<\/span><span>7 von 8<\/span>/);
  assert.match(h, /<div class="lj-schritt">Build <span class="dauer">seit <span data-live="dauer" data-start="\d+"><\/span><\/span><\/div>/);
  assert.equal((h.match(/class="seg /g) || []).length, 8);
  assert.equal((h.match(/class="seg fertig"/g) || []).length, 6);
  assert.match(h, /class="seg aktiv"/);
  assert.match(h, /data-spalten="8"/);
  assert.match(h, /Läuft seit<\/span><span>gestartet 16:53:18<\/span>/);
  assert.match(h, /data-live="rest" data-start="\d+" data-median="660" data-anzahl="5"/);
  assert.doesNotMatch(h, /style=/, 'CSP: keine style-Attribute');
  assert.doesNotMatch(h, /<script|onclick/i);
});

test('zugeklapptes Repository zeigt nur die Zeile; ohne Wahl ist „läuft“ offen, „wartet“ zu', () => {
  const je = J.nachRepo({ laufende: [job()], wartende: [{ repo: 'api-dienst', workflow: 'ci', seit: vor(300), pos: 1, ref: { art: 'Branch', name: 'main' } }] });
  const zu = J.repoHtml({ name: 'web-portal', privat: false, laeuft: 1, wartet: 0 }, je, { 'web-portal': false }, f);
  assert.match(zu, /aria-expanded="false"/);
  assert.doesNotMatch(zu, /repo-detail|class="lj"/);
  const wart = J.repoHtml({ name: 'api-dienst', privat: true, laeuft: 0, wartet: 1 }, je, {}, f);
  assert.match(wart, /aria-expanded="false"/);
  assert.match(wart, /class="schloss"/);
  assert.match(wart, /1 wartet/);
  assert.doesNotMatch(wart, /class="lw"/);
  assert.match(J.repoHtml({ name: 'api-dienst', privat: true, laeuft: 0, wartet: 1 }, je, { 'api-dienst': true }, f), /class="lw"/);
});

test('wartende Läufe: Position nur wenn ableitbar, blockierte ohne, „wartet seit“ live', () => {
  const je = J.nachRepo({ wartende: [
    { repo: 'api-dienst', workflow: 'ci', ref: { art: 'Branch', name: 'main' }, seit: vor(492), pos: 1, blockiert: false },
    { repo: 'api-dienst', workflow: 'release', ref: { art: 'Tag', name: 'v1.4.0' }, seit: vor(60), pos: null, blockiert: false },
    { repo: 'api-dienst', workflow: 'deploy', ref: { art: 'PR', name: '#9' }, seit: vor(30), pos: null, blockiert: true },
    { repo: 'api-dienst', workflow: 'ohne-zeit', ref: null, seit: null, pos: 2 },
  ] });
  const h = alle(J.repoHtml({ name: 'api-dienst', privat: true, laeuft: 0, wartet: 4 }, je, { 'api-dienst': true }, f));
  assert.match(h, /Wartet auf einen Runner/);
  assert.match(h, /<span class="lw-pos">Pos\. 1<\/span><span class="lw-name">Workflow <b>ci<\/b><span class="mut">Branch main<\/span><\/span><span class="lw-seit">wartet seit <span data-live="seit" data-start="\d+"><\/span><\/span>/);
  assert.match(h, /<span class="lw-pos">–<\/span><span class="lw-name">Workflow <b>release<\/b>/);
  assert.match(h, /<span class="lw-pos" title="[^"]+">blockiert<\/span><span class="lw-name">Workflow <b>deploy<\/b>/);
  assert.match(h, /<b>ohne-zeit<\/b><\/span><span class="lw-seit"><\/span>/);   // ohne Zeit kein „wartet seit“
});

test('laufender Job eines anderen Runners ohne Schritte, ohne Beginn und ohne Job-Namen', () => {
  const h = alle(J.laufendHtml({ repo: 'dokumentation', workflow: 'Pages', name: '', ref: null, runner: null, eigener: false, start: null, schritt: null, vergleich: null }, f));
  assert.match(h, /Workflow <b>Pages<\/b><\/div>/);
  assert.doesNotMatch(h, /Job <b>/);
  assert.match(h, /anderer Runner/);
  assert.match(h, /Schritte nicht verfügbar/);
  assert.match(h, /<div class="lj-zahl">–<\/div>/);
  assert.match(h, /data-live="rest" data-start=""/);
});

test('Schritt ohne Liste („3 von –“) und ohne Namen', () => {
  const h = J.laufendHtml(job({ schritt: { nr: 3, von: null, name: '', start: null } }), f);
  assert.match(h, /3 von –/);
  assert.match(h, /<div class="lj-schritt mut">Schritt 3<\/div>/);
  assert.equal((h.match(/class="seg /g) || []).length, 4);
  assert.equal((h.match(/class="seg unbekannt"/g) || []).length, 1);   // gestrichelter Rest wie im Runner-Status
});

test('Namen aus fremden Antworten werden maskiert', () => {
  const bos = '<img src=x onerror=alert(1)>"\'';
  const h = J.repoHtml({ name: bos, privat: false, laeuft: 1, wartet: 1 }, J.nachRepo({
    laufende: [{ repo: bos, workflow: bos, name: bos, ref: { art: bos, name: bos, titel: bos }, runner: bos, eigener: true, start: vor(5), schritt: { nr: 1, von: 2, name: bos, start: null } }],
    wartende: [{ repo: bos, workflow: bos, ref: { art: bos, name: bos }, seit: vor(5), pos: 1 }],
  }), { [bos]: true }, f);
  assert.doesNotMatch(h, /<img/);
  assert.match(h, /&lt;img src=x onerror=alert\(1\)&gt;/);
});

test('Restzeit-Block der Runner-Karte: Kopf, Balken und leere Texte (setzt tick)', () => {
  const h = J.restHtml(job(), f, true);
  assert.match(h, /^<div class="rest-karte" data-live="rest"/);
  assert.match(h, /Geschätzte Restzeit<\/span><span class="rest-pct"><\/span>/);
  assert.match(h, /<div class="fort" role="img"><span><\/span><\/div>/);
  assert.doesNotMatch(h, /style=/);
  assert.doesNotMatch(J.restHtml(job(), f, false), /rest-pct|class="fort"/);
});

/* ---------------------------------------------------------------- tick (Attrappe statt DOM) */

function el(daten = {}, kinder = {}) {
  const klassen = new Set();
  const x = {
    dataset: daten, textContent: '', title: '', style: {}, attrs: {}, kinder, klassen,
    classList: { toggle: (k, an) => (an ? klassen.add(k) : klassen.delete(k)) },
    getAttribute: (k) => x.attrs[k] ?? null, setAttribute: (k, v) => { x.attrs[k] = v; },
    querySelector: (s) => kinder[s] || null,
    querySelectorAll: (s) => (s === '.rest, .fort' ? [kinder['.rest'], kinder['.fort']].filter(Boolean) : []),
  };
  return x;
}

test('tick setzt Laufzeit, „wartet seit“ und Restzeit und das Gitter der Segmente – nur per CSSOM', () => {
  const dauer = el({ live: 'dauer', start: String(JETZT - sek(402)) });
  const seit = el({ live: 'seit', start: String(JETZT - sek(492)) });
  const balken = el(), fort = el(), rest = el(), sub = el(), pct = el();
  const restBlock = el({ live: 'rest', start: String(JETZT - sek(402)), median: '660', anzahl: '5' }, { '.rest': rest, '.rest-sub': sub, '.rest-pct': pct, '.fort': fort, '.fort span': balken });
  const seg = el({ spalten: '8' });
  const wurzel = { querySelectorAll: (s) => (s === '[data-live]' ? [dauer, seit, restBlock] : s === '.segmente[data-spalten]' ? [seg] : []) };
  J.tick(wurzel, f, JETZT);
  assert.equal(dauer.textContent, '6:42');
  assert.equal(seit.textContent, '8 Min.');
  assert.equal(rest.textContent, 'noch ca. 4 Min.');
  assert.equal(sub.textContent, 'ca. 17:04 fertig · üblich ca. 11 Min.');
  assert.equal(pct.textContent, '61 %');
  assert.equal(balken.style.transform, 'scaleX(0.609)');
  assert.equal(fort.attrs['aria-label'], '61 % der üblichen Laufzeit');
  assert.match(rest.title, /Median der letzten 5/);
  assert.equal(seg.style.gridTemplateColumns, 'repeat(8, minmax(0, 1fr))');
  // eine Minute später ist der Median überschritten: „länger als üblich“, Balken voll, Warnfarbe
  J.tick(wurzel, f, JETZT + sek(300));
  assert.equal(dauer.textContent, '11:42');
  assert.equal(rest.textContent, 'länger als üblich');
  assert.equal(balken.style.transform, 'scaleX(1.000)');
  assert.ok(rest.klassen.has('lang') && fort.klassen.has('lang') && !rest.klassen.has('keine'));
  // ohne Vergleichswerte: „keine Schätzung“
  const ohne = el({ live: 'rest', start: String(JETZT - sek(10)) }, { '.rest': el(), '.rest-sub': el(), '.rest-pct': el(), '.fort': el(), '.fort span': el() });
  J.tick({ querySelectorAll: (s) => (s === '[data-live]' ? [ohne] : []) }, f, JETZT);
  assert.equal(ohne.kinder['.rest'].textContent, 'keine Schätzung');
  assert.ok(ohne.kinder['.rest'].klassen.has('keine'));
  assert.equal(ohne.kinder['.fort span'].style.transform, 'scaleX(0.000)');
  assert.doesNotThrow(() => J.tick(null, f));
});

test('tick lässt Elemente ohne Beginn unverändert', () => {
  const leer = el({ live: 'dauer', start: '' });
  leer.textContent = '–';
  J.tick({ querySelectorAll: (s) => (s === '[data-live]' ? [leer] : []) }, f, JETZT);
  assert.equal(leer.textContent, '–');
});

/* ---------------------------------------------------------------- Höhe des Live-Logs */

const speicher = (start = {}) => { const d = { ...start }; return { getItem: (k) => (k in d ? d[k] : null), setItem: (k, v) => { d[k] = String(v); }, d }; };

test('Live-Log: Höhe je Browser gemerkt, Vorgabe klein, gesperrter Speicher ohne Fehler', () => {
  assert.equal(J.SCHLUESSEL, 'runner-monitor.log-hoehe');
  const s = speicher();
  assert.equal(J.logHoeheLaden(s), 'klein');
  assert.equal(J.logHoeheSpeichern('gross', s), true);
  assert.equal(s.d['runner-monitor.log-hoehe'], 'gross');
  assert.equal(J.logHoeheLaden(s), 'gross');
  assert.equal(J.logHoeheSpeichern('riesig', s), false);
  assert.equal(J.logHoeheLaden(speicher({ 'runner-monitor.log-hoehe': 'riesig' })), 'klein');
  const gesperrt = { getItem: () => { throw new Error('gesperrt'); }, setItem: () => { throw new Error('gesperrt'); } };
  assert.equal(J.logHoeheLaden(gesperrt), 'klein');
  assert.equal(J.logHoeheSpeichern('gross', gesperrt), false);
  assert.equal(J.logHoeheLaden(null), 'klein');
});

/* ---------------------------------------------------------------- Übersetzung und Einbindung */

test('Englisch: Texte der Restzeit ergeben sich aus i18n.js', () => {
  const en = (text, w) => f.t(I18N.EN[text] ?? text, w);
  const fe = { ...f, t: en };
  const rest = J.restText(J.restzeit(vor(402), { median: 660, anzahl: 5 }, JETZT), fe);
  assert.equal(rest.haupt, 'about 4 Min. left');
  assert.equal(rest.sub, 'done around 17:04 · usually about 11 Min.');
  assert.equal(J.restText(J.restzeit(vor(900), { median: 600, anzahl: 5 }, JETZT), fe).haupt, 'longer than usual');
  assert.equal(J.restText(J.restzeit(vor(900), null, JETZT), fe).haupt, 'no estimate');
});

test('Dashboard bindet jobs.js vor dashboard.js ein und hat den Knopf für die Höhe des Live-Logs', () => {
  const html = readFileSync(new URL('../../web/dashboard.html', import.meta.url), 'utf8');
  assert.ok(html.indexOf('/static/jobs.js') > 0 && html.indexOf('/static/jobs.js') < html.indexOf('/static/dashboard.js'));
  assert.match(html, /id="k-log-hoehe"[^>]*aria-expanded="false"/);
  // Jobs je Repository und Live-Log teilen sich die Fläche unter der Auslastung
  assert.ok(html.indexOf('id="unten"') < html.indexOf('id="workflows"') && html.indexOf('id="workflows"') < html.indexOf('aria-label="Live-Log"'));
});

test('Repository-Namen wie toString, constructor und __proto__ legen nichts lahm', () => {
  for (const name of ['toString', 'constructor', '__proto__', 'hasOwnProperty', 'valueOf']) {
    const je = J.nachRepo({ laufende: [job({ repo: name })], wartende: [{ repo: name, workflow: 'ci', seit: vor(5), pos: 1 }] });
    assert.equal(je.laufende[name].length, 1, name);
    assert.equal(je.wartende[name].length, 1, name);
    const wahl = Object.create(null);
    assert.equal(J.istOffen(wahl, name, 0), false, name);
    wahl[name] = true;
    assert.equal(J.istOffen(wahl, name, 0), true, name);
    // ein gewöhnliches Objekt als Wahl: geerbte Eigenschaften zählen nicht
    assert.equal(J.istOffen({}, name, 0), false, name);
    const h = J.repoHtml({ name, privat: false, laeuft: 1, wartet: 1 }, je, wahl, f);
    assert.match(h, /class="lj"/, name);
    assert.match(h, /class="lw"/, name);
  }
  // Repository ohne eigene Einträge, aber mit Namen aus Object.prototype
  assert.doesNotThrow(() => J.repoHtml({ name: 'toString', privat: false, laeuft: 0, wartet: 0 }, J.nachRepo({}), {}, f));
});

test('Segmente: fremde Zahlen werden begrenzt', () => {
  const h = J.laufendHtml(job({ schritt: { nr: 100000, von: 100000, name: 'x', start: null } }), f);
  assert.equal((h.match(/class="seg /g) || []).length, 100);
  assert.match(h, /data-spalten="100"/);
  const g = J.laufendHtml(job({ schritt: { nr: 5000, von: null, name: '', start: null } }), f);
  assert.equal((g.match(/class="seg /g) || []).length, 100);
});

test('aria-controls: Log-Knopf und Repository-Knöpfe nennen, was sie steuern', () => {
  const html = readFileSync(new URL('../../web/dashboard.html', import.meta.url), 'utf8');
  assert.match(html, /id="k-log-hoehe" aria-controls="unten"/);
  const h = J.repoHtml({ name: 'a.b', privat: false, laeuft: 1, wartet: 0 }, J.nachRepo({ laufende: [job({ repo: 'a.b' })] }), {}, f);
  assert.match(h, /aria-controls="rd-a_b"/);
  assert.match(h, /<div class="repo-detail" id="rd-a_b">/);
});
