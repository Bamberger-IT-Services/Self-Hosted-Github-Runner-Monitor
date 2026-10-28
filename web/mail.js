/* E-Mail-Vorlagen für „Fehler melden“ und „Idee vorschlagen“ (Design 0.8.0, #98). Reine Logik ohne
   DOM, damit sie sich mit node prüfen lässt (tests/js/mail.test.mjs). Im Browser als globales MAIL.
   Die Texte kommen über die übergebene Übersetzungsfunktion t() (deutscher Text = Schlüssel in
   web/i18n.js), die technischen Angaben als schlichte Werte. Es gibt keine Anfrage an GitHub. */
'use strict';

const MAIL = (() => {
  const ADRESSE = 'info@bamberger-it-services.de';
  const BROWSER_MAX = 160;                 // userAgent kürzen, damit die Adresse handlich bleibt
  const JOURNAL = 'journalctl -u runner-monitor-update -n 50';

  /* Tokens gehören nie in die Mail: Muster gängiger Tokens (auch 40 Hex-Zeichen ohne Präfix) entfernen.
     Die Ersatzmarke kommt übersetzt aus t(). */
  const TOKEN = /\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|glpat-[A-Za-z0-9_-]{16,})|\b[0-9a-fA-F]{40}\b/g;
  const bereiniger = (t) => (s) => String(s == null ? '' : s).replace(TOKEN, t('[entfernt]')).replace(/[\r\n]+/g, ' ').trim();

  const kurz = (s, n) => (s.length > n ? s.slice(0, n - 1) + '…' : s);

  /* Technische Angaben als Zeilen: Version, System, Runner, Gewählt, Browser. */
  function angaben(a, t) {
    const bereinige = bereiniger(t);
    const runner = (a.runner || []).map((r) => {
      const dv = [r.dienst, r.version].filter(Boolean).join(' ');
      return bereinige(r.name) + (dv ? ` (${bereinige(dv)})` : '');
    }).join(', ');
    const zeilen = [
      `${t('Version:')} Runner-Monitor ${bereinige(a.version) || '–'}`,
      `${t('System:')} ${bereinige(a.system) || '–'}`,
      `${t('Runner:')} ${runner || '–'}`,
    ];
    if (a.gewaehlt) zeilen.push(`${t('Gewählt:')} ${bereinige(a.gewaehlt.name) || '–'}${a.gewaehlt.zustand ? ' · ' + bereinige(a.gewaehlt.zustand) : ''}`);
    zeilen.push(`${t('Browser:')} ${kurz(bereinige(a.browser) || '–', BROWSER_MAX)}`);
    return zeilen;
  }

  function adresse(betreff, zeilen) {
    const text = zeilen.join('\r\n');
    return `mailto:${ADRESSE}?subject=${encodeURIComponent(betreff)}&body=${encodeURIComponent(text)}`;
  }

  /* a: { version, system, runner: [{ name, dienst, version }], gewaehlt: { name, zustand }, browser } */
  function fehler(a, t) {
    const bereinige = bereiniger(t);
    return adresse(t('Runner-Monitor {v} – Fehler', { v: bereinige(a.version) || '–' }), [
      t('Hallo Bamberger IT Services,'), '',
      t('im Runner-Monitor ist mir ein Fehler aufgefallen.'), '',
      t('Was ist passiert?'), '…', '',
      t('Was hätte passieren sollen?'), '…', '',
      t('So lässt es sich nachstellen:'), '1. …', '2. …', '',
      t('Technische Angaben (automatisch ergänzt):'), ...angaben(a, t), '',
      t('Bitte keine Tokens oder Passwörter mitschicken.'),
    ]);
  }

  function idee(a, t) {
    const bereinige = bereiniger(t);
    return adresse(t('Runner-Monitor {v} – Idee', { v: bereinige(a.version) || '–' }), [
      t('Hallo Bamberger IT Services,'), '',
      t('ich habe eine Idee für den Runner-Monitor.'), '',
      t('Worum geht es?'), '…', '',
      t('Warum wäre das hilfreich?'), '…', '',
      `${t('Version:')} Runner-Monitor ${bereinige(a.version) || '–'}`,
    ]);
  }

  /* Fehlgeschlagenes Update: a wie oben, dazu alt (wiederhergestellte Version), neu (Zielversion)
     und meldung (Text des Aktualisierers). */
  function updateFehler(a, t) {
    const bereinige = bereiniger(t);
    const neu = bereinige(a.neu) || '–', alt = bereinige(a.alt) || bereinige(a.version) || '–';
    const zeilen = [
      t('Hallo Bamberger IT Services,'), '',
      t('das Update von {alt} auf {neu} ist fehlgeschlagen, {alt} wurde wiederhergestellt.', { alt, neu }), '',
    ];
    if (a.meldung) zeilen.push(`${t('Meldung:')} ${bereinige(a.meldung)}`, '');
    zeilen.push(
      t('Ausgabe von {befehl} (gekürzt):', { befehl: JOURNAL }), '…', '',
      t('Technische Angaben (automatisch ergänzt):'), ...angaben(a, t),
    );
    return adresse(t('Runner-Monitor – Update auf {v} fehlgeschlagen', { v: neu }), zeilen);
  }

  return { ADRESSE, JOURNAL, fehler, idee, updateFehler };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = MAIL;
