/* E-Mail-Vorlagen für „Fehler melden“ und „Idee vorschlagen“ (Design 0.8.0, #98). Reine Logik ohne
   DOM, damit sie sich mit node prüfen lässt (tests/js/mail.test.mjs). Im Browser als globales MAIL.
   Die Texte kommen über die übergebene Übersetzungsfunktion t() (deutscher Text = Schlüssel in
   web/i18n.js), die technischen Angaben als schlichte Werte. Es gibt keine Anfrage an GitHub. */
'use strict';

const MAIL = (() => {
  const ADRESSE = 'info@bamberger-it-services.de';
  const BROWSER_MAX = 160;                 // userAgent kürzen, damit die Adresse handlich bleibt
  const JOURNAL = 'journalctl -u runner-monitor-update -n 50';

  /* Tokens gehören nie in die Mail: Muster gängiger Tokens entfernen. */
  const TOKEN = /\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|glpat-[A-Za-z0-9_-]{16,})/g;
  const bereinige = (s) => String(s == null ? '' : s).replace(TOKEN, '[entfernt]').replace(/[\r\n]+/g, ' ').trim();

  const kurz = (s, n) => (s.length > n ? s.slice(0, n - 1) + '…' : s);

  /* Technische Angaben als Zeilen: Version, System, Runner, Gewählt, Browser. */
  function angaben(a, t) {
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
    return adresse(t('Runner-Monitor {v} – Idee', { v: bereinige(a.version) || '–' }), [
      t('Hallo Bamberger IT Services,'), '',
      t('ich habe eine Idee für den Runner-Monitor.'), '',
      t('Worum geht es?'), '…', '',
      t('Warum wäre das hilfreich?'), '…', '',
      `${t('Version:')} Runner-Monitor ${bereinige(a.version) || '–'}`, '',
      t('Bitte keine Tokens oder Passwörter mitschicken.'),
    ]);
  }

  /* Fehlgeschlagenes Update: a wie oben, dazu neu (Zielversion) und meldung (Text des Aktualisierers). */
  function updateFehler(a, t) {
    const neu = bereinige(a.neu) || '–';
    const zeilen = [
      t('Hallo Bamberger IT Services,'), '',
      t('das Update des Runner-Monitors auf {v} ist fehlgeschlagen.', { v: neu }), '',
    ];
    if (a.meldung) zeilen.push(`${t('Meldung:')} ${bereinige(a.meldung)}`, '');
    zeilen.push(
      t('Ausgabe von {befehl} (gekürzt, ohne Tokens):', { befehl: JOURNAL }), '…', '',
      t('Technische Angaben (automatisch ergänzt):'), ...angaben(a, t), '',
      t('Bitte keine Tokens oder Passwörter mitschicken.'),
    );
    return adresse(t('Runner-Monitor – Update auf {v} fehlgeschlagen', { v: neu }), zeilen);
  }

  return { ADRESSE, JOURNAL, fehler, idee, updateFehler };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = MAIL;
