/* Gemeinsame Hilfen für alle Seiten: Formatierung (Deutsch oder Englisch, i18n.js), Symbole,
   Thema, Anfragen. Kein Framework, keine externen Quellen. */
'use strict';

const RM = (() => {
  const EN = typeof I18N !== 'undefined' && I18N.sprache() === 'en';
  const t = (text, werte) => (typeof I18N !== 'undefined' ? I18N.t(text, werte) : text);
  const p2 = v => String(v).padStart(2, '0');
  const ms = t => (t == null ? NaN : (typeof t === 'number' ? (t < 1e12 ? t * 1000 : t) : Date.parse(t)));
  const zahl = (x, d = 0) => Number(x).toLocaleString(EN ? 'en-US' : 'de-DE', { minimumFractionDigits: d, maximumFractionDigits: d });
  const zeit = t => { const d = new Date(ms(t)); return `${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}`; };
  const hm = t => { const d = new Date(ms(t)); return `${p2(d.getHours())}:${p2(d.getMinutes())}`; };
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const tm = z => { const d = new Date(ms(z)); return EN ? `${d.getDate()} ${MON[d.getMonth()]}` : `${p2(d.getDate())}.${p2(d.getMonth() + 1)}.`; };
  const datum = z => { const d = new Date(ms(z)); return EN ? `${tm(z)} ${d.getFullYear()}` : `${tm(z)}${d.getFullYear()}`; };
  const WT = EN ? ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] : ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'];
  const wt = z => WT[new Date(ms(z)).getDay()];
  const dauer = s => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60; return h ? `${h}:${p2(m)}:${p2(x)}` : `${m}:${p2(x)}`; };
  const E = EN ? { min: 'min', std: 'h', tag: 'd' } : { min: 'Min.', std: 'Std.', tag: 'T' };
  const vorText = x => (EN ? `${x} ago` : `vor ${x}`);
  const vor = s => { s = Math.max(0, Math.round(s)); if (s < 60) return vorText(`${s} s`); const m = Math.floor(s / 60); if (m < 60) return vorText(`${m} ${E.min}`); const h = Math.floor(m / 60); return vorText(h < 24 ? `${h} ${E.std}` : `${Math.floor(h / 24)} ${E.tag}`); };
  const seit = s => { s = Math.max(0, Math.round(s)); if (s < 60) return `${s} s`; const m = Math.floor(s / 60); if (m < 60) return `${m} ${E.min}`; const h = Math.floor(m / 60); return h < 24 ? `${h} ${E.std} ${m % 60} ${E.min}` : `${Math.floor(h / 24)} ${E.tag} ${h % 24} ${E.std}`; };
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const mehrzahl = (n, eins, viele) => (n === 1 ? eins : viele);
  const $ = id => document.getElementById(id);

  /* Symbole: Strichzeichnungen 16×16, Farbe über currentColor */
  const svg = (s, inhalt, extra = '') => `<svg viewBox="0 0 16 16" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${inhalt}</svg>`;
  const IC = {
    ok: (s = 14, w = 1.6) => svg(s, `<circle cx="8" cy="8" r="6.5"/><path d="M5.2 8.2l1.9 1.9 3.7-4"/>`, `stroke-width="${w}"`),
    x: (s = 14, w = 1.6) => svg(s, `<circle cx="8" cy="8" r="6.5"/><path d="M5.8 5.8l4.4 4.4M10.2 5.8l-4.4 4.4"/>`, `stroke-width="${w}"`),
    abbr: (s = 14) => svg(s, `<circle cx="8" cy="8" r="6.5"/><path d="M3.6 12.4l8.8-8.8"/>`, 'stroke-width="1.6"'),
    unklar: (s = 13) => svg(s, `<circle cx="8" cy="8" r="6.5"/><path d="M5 8h6"/>`, 'stroke-width="1.7"'),
    play: (s = 14, w = 1.5) => svg(s, `<circle cx="8" cy="8" r="6.5"/><path d="M6.6 5.4v5.2L10.6 8z" fill="currentColor" stroke="none"/>`, `stroke-width="${w}"`),
    stop: (s = 28) => svg(s, `<circle cx="8" cy="8" r="6.6"/><rect x="5.6" y="5.6" width="4.8" height="4.8" rx=".6" fill="currentColor" stroke="none"/>`, 'stroke-width="1.3"'),
    warn: (s = 15, w = 1.6) => svg(s, `<path d="M8 1.9l6.4 11.3H1.6z"/><path d="M8 6.3v3.2M8 11.4v.1"/>`, `stroke-width="${w}"`),
    uhr: (s = 16, w = 1.5) => svg(s, `<circle cx="8" cy="8" r="6.5"/><path d="M8 4.6V8l2.3 1.5"/>`, `stroke-width="${w}"`),
    dreieck: (s = 11) => `<svg viewBox="0 0 16 16" width="${s}" height="${s}" aria-hidden="true"><path d="M4.5 3v10l8-5z" fill="currentColor"/></svg>`,
    pause: (s = 12) => `<svg viewBox="0 0 16 16" width="${s}" height="${s}" aria-hidden="true"><rect x="4" y="3" width="2.6" height="10" rx=".6" fill="currentColor"/><rect x="9.4" y="3" width="2.6" height="10" rx=".6" fill="currentColor"/></svg>`,
    schloss: (s = 13) => `<svg viewBox="0 0 16 16" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="1.5" role="img" aria-label="${t('privat')}"><rect x="3" y="7" width="10" height="7" rx="1.5"/><path d="M5.5 7V5a2.5 2.5 0 015 0v2"/></svg>`,
    chev: (offen, s = 12) => `<svg class="chev${offen ? ' offen' : ''}" viewBox="0 0 16 16" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 3.5L10.5 8 6 12.5"/></svg>`,
    schluessel: (s = 15, w = 1.5) => svg(s, `<circle cx="5" cy="11" r="2.6"/><path d="M6.9 9.1L13 3M11 5l1.6 1.6M9.4 6.6l1.4 1.4"/>`, `stroke-width="${w}"`),
    getrennt: (s = 14) => svg(s, `<path d="M2.5 2.5l11 11M6 4.6A8.6 8.6 0 0114.5 6.6M1.5 6.6a8.7 8.7 0 012.2-1.4M4 9.4a5 5 0 014.6-1.2M8 12.6h.01"/>`, 'stroke-width="1.6"'),
    update: (s = 18) => svg(s, `<circle cx="8" cy="8" r="6.5"/><path d="M8 4.8v6M5.4 8.6L8 11.2l2.6-2.6"/>`, 'stroke-width="1.6"'),
    herunter: (s = 14) => svg(s, `<path d="M8 2.5v8M4.8 7.6L8 10.8l3.2-3.2M3 13.5h10"/>`, 'stroke-width="1.7"'),
    dreh: (s = 16) => `<svg class="laeuft upd-dreh" viewBox="0 0 16 16" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" role="img" aria-label="${t('läuft')}"><path d="M8 1.5a6.5 6.5 0 106.5 6.5"/></svg>`,
    offen: (s = 16) => `<svg class="mut" viewBox="0 0 16 16" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="1.4" role="img" aria-label="${t('ausstehend')}"><circle cx="8" cy="8" r="6.5" stroke-dasharray="2 2.4"/></svg>`,
    info: (s = 14) => svg(s, `<circle cx="8" cy="8" r="6.5"/><path d="M8 7.2v4M8 4.9v.1"/>`, 'stroke-width="1.6"'),
    datei: (s = 14) => svg(s, `<path d="M4 2.5h5.5L12 5v8.5H4z"/><path d="M6 7.5h4M6 10h4"/>`, 'stroke-width="1.5"'),
    sonne: (s = 14) => svg(s, `<circle cx="8" cy="8" r="3"/><path d="M8 1.5v1.6M8 12.9v1.6M1.5 8h1.6M12.9 8h1.6M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M3.4 12.6l1.1-1.1M11.5 4.5l1.1-1.1"/>`, 'stroke-width="1.5"'),
    mond: (s = 14) => svg(s, `<path d="M13.5 9.6A5.8 5.8 0 016.4 2.5a5.8 5.8 0 107.1 7.1z"/>`, 'stroke-width="1.5"'),
    auto: (s = 14) => svg(s, `<circle cx="8" cy="8" r="6"/><path d="M8 2a6 6 0 010 12z" fill="currentColor" stroke="none"/>`, 'stroke-width="1.5"'),
    kaefer: (s = 14) => svg(s, `<ellipse cx="8" cy="9" rx="3.6" ry="4.4"/><path d="M8 4.6V13.4M4.4 9H1.8M14.2 9h-2.6M4.9 6.2L2.8 4.6M11.1 6.2l2.1-1.6M4.9 11.8l-2.1 1.6M11.1 11.8l2.1 1.6M6 4.8a2 2 0 014 0"/>`, 'stroke-width="1.5"'),
    server: (s = 18) => svg(s, `<rect x="2" y="2.5" width="12" height="4.5" rx="1"/><rect x="2" y="9" width="12" height="4.5" rx="1"/><path d="M4.5 4.75h.01M4.5 11.25h.01M8 4.75h3.5M8 11.25h3.5"/>`, 'stroke-width="1.5"'),
  };

  /* Darstellung: system | hell | dunkel – je Browser gemerkt (localStorage kann fehlen) */
  const THEMEN = ['system', 'hell', 'dunkel'];
  function thema() {
    try { const t = localStorage.getItem('rm-thema'); return THEMEN.includes(t) ? t : 'system'; } catch (e) { return 'system'; }
  }
  function setzeThema(t) {
    if (!THEMEN.includes(t)) t = 'system';
    try { localStorage.setItem('rm-thema', t); } catch (e) { /* privat: dann nur für diese Seite */ }
    if (t === 'system') document.documentElement.removeAttribute('data-thema');
    else document.documentElement.setAttribute('data-thema', t);
  }
  setzeThema(thema());

  /* POST mit JSON. Gibt {ok, status, daten} zurück, wirft nie. */
  async function sende(pfad, daten) {
    try {
      const antwort = await fetch(pfad, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(daten || {}),
      });
      let inhalt = {};
      try { inhalt = await antwort.json(); } catch (e) { /* leer */ }
      return { ok: antwort.ok, status: antwort.status, daten: inhalt };
    } catch (e) {
      return { ok: false, status: 0, daten: { fehler: t('Der Monitor ist nicht erreichbar.') } };
    }
  }

  /* Text aus einer Server-Antwort übersetzen: mit Vorlage und Werten (z. B. „Version {v} …“) oder
     als fester deutscher Text – der deutsche Text ist der Schlüssel in i18n.js (#81). */
  const serverText = (d, feld = 'fehler') => (d && d.vorlage ? t(d.vorlage, d.werte) : t(String((d && d[feld]) || '')));

  /* Knopf zum Umschalten der Sprache (Anmeldung, Einrichtung): zeigt die jeweils andere Sprache. */
  function sprachKnopf(el) {
    if (!el || typeof I18N === 'undefined') return;
    const andere = I18N.sprache() === 'de' ? 'en' : 'de';
    el.textContent = andere === 'en' ? 'English' : 'Deutsch';
    el.lang = andere;
    el.addEventListener('click', () => { I18N.setzeSprache(andere); location.reload(); });
  }

  return { p2, ms, zahl, zeit, hm, tm, datum, wt, dauer, vor, seit, esc, mehrzahl, $, IC, thema, setzeThema, sende, t, serverText, sprachKnopf };
})();
