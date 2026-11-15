/* Laufende und wartende Jobs je Repository (Design 0.9.0, #171): aufklappbare Repositories, laufende Jobs mit
   Schritt „n von m“, Laufzeit und geschätzter Restzeit, wartende Läufe mit Position, dazu die gemerkte Höhe des
   Live-Logs. Reine Logik und HTML-Texte ohne DOM-Zugriff außer in tick(), damit sie sich mit node prüfen lässt
   (tests/js/jobs.test.mjs). Im Browser als globales JOBS. Die Hilfen (t, esc, dauer, …) kommen als Parameter
   `f` aus dashboard.js, damit hier nichts von RM oder I18N abhängt.

   Die Restzeit rechnet das Dashboard selbst, damit sie live herunterzählt: Der Server liefert je Job nur
   `vergleich = {median, anzahl}` – den Median der Dauern der letzten erfolgreichen Läufe desselben Workflows und
   Jobs (Sekunden). Ohne Vergleichswerte: „keine Schätzung“; über dem Median: „länger als üblich“, nie eine
   negative Zeit. Alles Veränderliche (Laufzeit, Restzeit, „wartet seit …“) steht als Zahl in data-Attributen und
   wird einmal je Sekunde mit tick() gesetzt, damit die Elemente nicht neu aufgebaut werden (Fokus, Klicks). */
'use strict';

const JOBS = (() => {
  const SCHLUESSEL = 'runner-monitor.log-hoehe';  // localStorage: 'klein' | 'gross'
  const HOEHEN = ['klein', 'gross'];
  const MAX_SEGMENTE = 100;                        // mehr Segmente zeichnet der Balken nicht (fremde Zahlen)
  const speicherStandard = () => { try { return typeof localStorage === 'undefined' ? null : localStorage; } catch (e) { return null; } };

  /* Gemerkte Höhe des Live-Logs; ohne Wahl oder bei gesperrtem Speicher: klein (der Platz gehört den Jobs). */
  function logHoeheLaden(speicher = speicherStandard()) {
    try { const w = speicher.getItem(SCHLUESSEL); return HOEHEN.includes(w) ? w : 'klein'; } catch (e) { return 'klein'; }
  }
  /* true, wenn gespeichert; gesperrt → false, die Wahl gilt dann nur für diese Seite. */
  function logHoeheSpeichern(w, speicher = speicherStandard()) {
    if (!HOEHEN.includes(w)) return false;
    try { speicher.setItem(SCHLUESSEL, w); return true; } catch (e) { return false; }
  }

  const ms = (z) => (z == null ? NaN : (typeof z === 'number' ? (z < 1e12 ? z * 1000 : z) : Date.parse(z)));
  const zahl = (x) => (typeof x === 'number' && Number.isFinite(x) ? x : null);

  /* Restzeit eines laufenden Jobs. start: Beginn (Unix-Sekunden, ms oder ISO), vergleich: {median, anzahl} oder null,
     jetzt in ms. art: 'rest' (noch n Sekunden), 'laenger' (Median überschritten) oder 'keine' (nichts zu vergleichen). */
  function restzeit(start, vergleich, jetzt) {
    const s = ms(start), m = vergleich ? zahl(vergleich.median) : null;
    if (!Number.isFinite(s) || m === null || m <= 0) return { art: 'keine', anteil: 0 };
    const lauf = Math.max(0, (jetzt - s) / 1000);
    const anzahl = Math.max(1, Math.round(zahl(vergleich.anzahl) || 1));
    if (lauf >= m) return { art: 'laenger', median: m, anzahl, anteil: 1 };
    return { art: 'rest', rest: m - lauf, fertig: jetzt + (m - lauf) * 1000, median: m, anzahl, anteil: lauf / m };
  }

  /* Sekunden → „12 Min.“ / „1 Std. 5 Min.“, auf ganze Minuten, mindestens 1 (f.seit setzt die Einheit). */
  const minuten = (sek, f) => f.seit(Math.max(1, Math.round(sek / 60)) * 60);

  /* Texte zur Restzeit: haupt („noch ca. 12 Min.“), sub, cls ('' | 'lang' | 'keine'), titel, aria, anteil (0…1). */
  function restText(r, f) {
    const { t } = f;
    if (r.art === 'rest') {
      const quelle = r.anzahl === 1 ? t('Dauer des letzten erfolgreichen Laufs desselben Workflows und Jobs') : t('Median der letzten {n} erfolgreichen Läufe desselben Workflows und Jobs', { n: r.anzahl });
      return { haupt: t('noch ca. {d}', { d: minuten(r.rest, f) }), sub: `${t('ca. {z} fertig', { z: f.hm(r.fertig) })} · ${t('üblich ca. {d}', { d: minuten(r.median, f) })}`,
        cls: '', titel: quelle, aria: t('{p} % der üblichen Laufzeit', { p: Math.round(r.anteil * 100) }), anteil: r.anteil, pct: `${Math.round(r.anteil * 100)} %` };
    }
    if (r.art === 'laenger') {
      return { haupt: t('länger als üblich'), sub: t('üblich ca. {d}', { d: minuten(r.median, f) }), cls: 'lang', titel: '', aria: t('Länger als üblich'), anteil: 1, pct: '' };
    }
    return { haupt: t('keine Schätzung'), sub: t('Keine Vergleichsläufe'), cls: 'keine', titel: '', aria: t('Keine Schätzung möglich'), anteil: 0, pct: '' };
  }

  /* Läufe und wartende Läufe nach Repository: {laufende: {repo: […]}, wartende: {repo: […]}}. Fehlende oder
     fehlerhafte Felder (älterer Server, anderer Dienst) ergeben leere Listen. */
  function nachRepo(w) {
    const gruppe = (liste) => {
      const je = Object.create(null);  // Repo-Namen wie „toString“ oder „__proto__“ sind gewöhnliche Schlüssel
      for (const e of Array.isArray(liste) ? liste : []) if (e && typeof e.repo === 'string') (je[e.repo] = je[e.repo] || []).push(e);
      return je;
    };
    return { laufende: gruppe(w && w.laufende), wartende: gruppe(w && w.wartende) };
  }

  /* Ist ein Repository aufgeklappt? Eine Wahl des Benutzers gilt; sonst offen, wenn dort etwas läuft. */
  const istOffen = (wahl, repo, laeuft) => (wahl && Object.hasOwn(wahl, repo) && typeof wahl[repo] === 'boolean' ? wahl[repo] : laeuft > 0);

  /* ---------------------------------------------------------------- HTML */
  const live = (art, start) => `data-live="${art}" data-start="${Number.isFinite(ms(start)) ? Math.round(ms(start)) : ''}"`;

  /* Block „Geschätzte Restzeit“: im Runner-Status ausführlich (gross), in der Repository-Liste ohne Kopfzeile und Balken.
     Die Texte setzt tick() – das HTML enthält nur Zahlen in data-Attributen und bleibt so zwischen zwei Daten gleich. */
  function restHtml(job, f, gross) {
    const v = job.vergleich ? `data-median="${zahl(job.vergleich.median) || ''}" data-anzahl="${zahl(job.vergleich.anzahl) || ''}"` : '';
    const kopf = gross ? `<div class="zeile-k"><span>${f.t('Geschätzte Restzeit')}</span><span class="rest-pct"></span></div>` : '';
    const balken = gross ? '<div class="fort" role="img"><span></span></div>' : '';
    return `<div class="${gross ? 'rest-karte' : 'rest-block'}" data-live="rest" data-start="${Number.isFinite(ms(job.start)) ? Math.round(ms(job.start)) : ''}" ${v}>${kopf}`
      + `<div class="rest"></div><div class="rest-sub"></div>${balken}</div>`;
  }

  function segmenteHtml(nr, von) {
    nr = Math.min(Math.max(nr, 1), MAX_SEGMENTE); von = von ? Math.min(von, MAX_SEGMENTE) : null;
    const n = von || Math.min(nr + 1, MAX_SEGMENTE);
    return `<div class="segmente" data-spalten="${n}">${Array.from({ length: n }, (_, i) => `<span class="seg ${i < nr - 1 ? 'fertig' : i === nr - 1 ? 'aktiv' : von ? '' : 'unbekannt'}"></span>`).join('')}</div>`;
  }

  /* Ein laufender Job: Workflow und Job, Branch/PR, Runner · Schritt n von m mit Dauer · läuft seit und Restzeit. */
  function laufendHtml(j, f) {
    const { t, esc } = f, s = j.schritt && Number(j.schritt.nr) > 0 ? j.schritt : null;
    const pfad = j.name ? `${t('Workflow')} <b>${esc(j.workflow)}</b><span class="sep"> › </span>${t('Job')} <b>${esc(j.name)}</b>` : `${t('Workflow')} <b>${esc(j.workflow || '–')}</b>`;
    const ref = j.ref ? `<div class="lj-ref"><span>${esc(j.ref.art)}</span><span class="ref">${esc(j.ref.name)}</span><span class="ref-titel">${esc(j.ref.titel || '')}</span></div>` : '';
    const runner = j.runner ? `<div class="lj-runner">${t('Runner {name}', { name: esc(j.runner) })}</div>` : j.eigener === false ? `<div class="lj-runner">${t('anderer Runner')}</div>` : '';
    const nr = s ? Math.floor(Number(s.nr)) : 0, von = s && Number(s.von) > 0 ? Math.floor(Number(s.von)) : null;
    const schritt = s ? `<div class="zeile-k"><span>${t('Aktueller Schritt')}</span><span>${t('{nr} von {von}', { nr, von: von || '–' })}</span></div>`
      + `<div class="lj-schritt${s.name ? '' : ' mut'}">${esc(s.name || t('Schritt {nr}', { nr }))}${Number.isFinite(ms(s.start)) ? ` <span class="dauer">${t('seit {d}', { d: `<span ${live('dauer', s.start)}></span>` })}</span>` : ''}</div>${segmenteHtml(nr, von)}`
      : `<div class="zeile-k"><span>${t('Aktueller Schritt')}</span></div><div class="lj-schritt mut">${t('Schritte nicht verfügbar')}</div>`;
    const start = Number.isFinite(ms(j.start)) ? `<div class="zeile-k"><span>${t('Läuft seit')}</span><span>${t('gestartet {z}', { z: f.zeit(j.start) })}</span></div><div class="lj-zahl" ${live('dauer', j.start)}></div>`
      : `<div class="zeile-k"><span>${t('Läuft seit')}</span></div><div class="lj-zahl">–</div>`;
    return `<div class="lj"><div><div class="lj-pfad">${pfad}</div>${ref}${runner}</div><div>${schritt}</div><div>${start}${restHtml(j, f, false)}</div></div>`;
  }

  /* Ein wartender Lauf: Position (nur wenn ableitbar), Workflow, Branch/PR, seit wann. */
  function wartendHtml(w, f) {
    const { t, esc } = f;
    const pos = w.blockiert ? `<span class="lw-pos" title="${esc(t('Wartet auf eine Freigabe oder einen anderen Job, nicht auf einen Runner'))}">${t('blockiert')}</span>`
      : `<span class="lw-pos">${Number(w.pos) > 0 ? t('Pos. {n}', { n: Math.floor(Number(w.pos)) }) : '–'}</span>`;
    const ref = w.ref ? `<span class="mut">${esc(w.ref.art)} ${esc(w.ref.name)}</span>` : '';
    const seit = Number.isFinite(ms(w.seit)) ? `${t('wartet seit {d}', { d: `<span ${live('seit', w.seit)}></span>` })}` : '';
    return `<div class="lw">${pos}<span class="lw-name">${t('Workflow')} <b>${esc(w.workflow || '–')}</b>${ref}</span><span class="lw-seit">${seit}</span></div>`;
  }

  const detailId = (name) => `rd-${String(name).replace(/[^A-Za-z0-9_-]/g, '_')}`;

  /* Eine Zeile „Repository“ mit Pillen („1 läuft“, „2 warten“) als Knopf zum Aufklappen und, wenn offen, den Einzelheiten.
     r: {name, privat, laeuft, wartet}, je: Ergebnis von nachRepo(), wahl: {repo: bool} des Benutzers. */
  function repoHtml(r, je, wahl, f) {
    const { t, esc, IC, mehrzahl } = f, offen = istOffen(wahl, r.name, r.laeuft);
    const laufende = je.laufende[r.name] || [], wartende = je.wartende[r.name] || [];
    const pillen = `${r.laeuft ? `<span class="pill laeuft">${IC.dreieck()}${r.laeuft} ${mehrzahl(r.laeuft, t('läuft'), t('laufen'))}</span>` : ''}${r.wartet ? `<span class="pill wartet">${IC.uhr(12, 1.7)}${r.wartet} ${mehrzahl(r.wartet, t('wartet'), t('warten'))}</span>` : ''}`;
    let detail = '';
    if (offen) {
      const ohne = r.laeuft > 0 && !laufende.length ? `<div class="lj-leer">${t('Einzelheiten zum laufenden Job liegen nicht vor.')}</div>` : '';
      const wart = wartende.length ? `<div class="lw-titel">${t('Wartet auf einen Runner')}</div>${wartende.map((w) => wartendHtml(w, f)).join('')}` : '';
      detail = `<div class="repo-detail" id="${detailId(r.name)}">${laufende.map((j) => laufendHtml(j, f)).join('')}${ohne}${wart}</div>`;
    }
    return `<div class="repo-block"><button type="button" class="repo repo-kopf" data-aktion="repo-offen" data-repo="${esc(r.name)}" aria-expanded="${offen}" aria-controls="${detailId(r.name)}">${IC.chev(offen)}`
      + `<span class="repo-name">${esc(r.name)}${r.privat ? IC.schloss(12) : ''}</span><span class="repo-pillen">${pillen}</span></button>${detail}</div>`;
  }

  /* ---------------------------------------------------------------- Takt */
  /* Setzt Laufzeiten, „wartet seit“ und Restzeiten in `wurzel` (einmal je Sekunde). Nur textContent, className und
     style per CSSOM (die CSP erlaubt keine style-Attribute). f: Hilfen wie oben, dazu f.dauer, f.seit. */
  function tick(wurzel, f, jetzt = Date.now()) {
    if (!wurzel) return;
    const setze = (el, text) => { if (el && el.textContent !== text) el.textContent = text; };
    for (const el of wurzel.querySelectorAll('[data-live]')) {
      const start = Number(el.dataset.start), art = el.dataset.live;
      if (!Number.isFinite(start) || !el.dataset.start) continue;
      if (art === 'dauer') setze(el, f.dauer((jetzt - start) / 1000));
      else if (art === 'seit') setze(el, f.seit((jetzt - start) / 1000));
      else if (art === 'rest') {
        const vergleich = el.dataset.median ? { median: Number(el.dataset.median), anzahl: Number(el.dataset.anzahl) } : null;
        const r = restText(restzeit(start, vergleich, jetzt), f);
        setze(el.querySelector('.rest'), r.haupt); setze(el.querySelector('.rest-sub'), r.sub); setze(el.querySelector('.rest-pct'), r.pct);
        const hauptEl = el.querySelector('.rest');
        if (hauptEl && hauptEl.title !== r.titel) hauptEl.title = r.titel;
        for (const k of el.querySelectorAll('.rest, .fort')) { k.classList.toggle('lang', r.cls === 'lang'); k.classList.toggle('keine', r.cls === 'keine'); }
        const balken = el.querySelector('.fort span');
        if (balken) balken.style.transform = `scaleX(${r.anteil.toFixed(3)})`;
        const fort = el.querySelector('.fort');
        if (fort && fort.getAttribute('aria-label') !== r.aria) fort.setAttribute('aria-label', r.aria);
      }
    }
    for (const seg of wurzel.querySelectorAll('.segmente[data-spalten]')) seg.style.gridTemplateColumns = `repeat(${seg.dataset.spalten}, minmax(0, 1fr))`;
  }

  return { SCHLUESSEL, HOEHEN, logHoeheLaden, logHoeheSpeichern, restzeit, restText, nachRepo, istOffen, restHtml, laufendHtml, wartendHtml, repoHtml, tick };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = JOBS;
