/* Runner-Monitor – Anmeldung. Ansprache „Sie“ (Anweisungen 03). */
'use strict';

(() => {
  const { $, IC, esc, hm, t } = RM;
  I18N.wendeAn(); RM.sprachKnopf($('sprache'));
  document.title = `${t('Anmelden')} · Runner-Monitor`;
  $('marke-icon').innerHTML = IC.server(28);
  $('marke-host').textContent = location.hostname;
  fetch('/api/health').then(r => (r.ok ? r.json() : {})).then((d) => {
    if (d.vm) $('marke-host').textContent = d.vm;
    if (d.version) $('fuss-version').textContent = `Runner-Monitor ${d.version}`;
  }).catch(() => {});
  const form = $('formular'), knopf = $('absenden'), box = $('meldung');
  let sperreBis = 0, uhr = 0;

  function zeige(titel, text) {
    box.innerHTML = `${IC.x(16)}<span><b>${esc(titel)}</b>${text ? ' ' + esc(text) : ''}</span>`;
    box.hidden = false;
  }

  function sperre() {
    const rest = Math.ceil(sperreBis - Date.now() / 1000);
    if (rest <= 0) { clearInterval(uhr); knopf.disabled = false; knopf.textContent = t('Anmelden'); box.hidden = true; return; }
    knopf.disabled = true;
    knopf.textContent = t('Gesperrt – noch {z}', { z: `${Math.floor(rest / 60)}:${String(rest % 60).padStart(2, '0')}` });
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const nutzer = $('nutzer').value.trim(), passwort = $('passwort').value;
    $('nutzer').classList.toggle('falsch', !nutzer); $('passwort').classList.toggle('falsch', !passwort);
    if (!nutzer || !passwort) { zeige(t('Bitte Benutzername und Passwort eingeben.')); return; }
    knopf.disabled = true; knopf.textContent = t('Wird geprüft …');
    const r = await RM.sende('/api/anmelden', { nutzer, passwort, merken: $('merken').checked });
    if (r.ok) { location.href = '/'; return; }
    knopf.disabled = false; knopf.textContent = t('Anmelden');
    $('passwort').value = ''; $('passwort').classList.add('falsch'); $('passwort').focus();
    const d = r.daten || {};
    if (d.gesperrtBis) {
      sperreBis = d.gesperrtBis;
      zeige(t('Zu viele Fehlversuche.'), t('Die Anmeldung ist bis {z} Uhr gesperrt. Danach können Sie es erneut versuchen.', { z: hm(sperreBis) }));
      clearInterval(uhr); uhr = setInterval(sperre, 1000); sperre();
      return;
    }
    const rest = d.verbleibend;
    let text = '';
    if (rest != null) text = rest === 1 ? t('Noch {n} Versuch, danach ist die Anmeldung 5 Minuten gesperrt.', { n: rest }) : rest > 0 ? t('Noch {n} Versuche, danach ist die Anmeldung 5 Minuten gesperrt.', { n: rest }) : t('Die Anmeldung ist für 5 Minuten gesperrt.');
    zeige(d.fehler ? RM.serverText(d) : t('Anmeldung fehlgeschlagen.'), text);
  });
  $('nutzer').focus();
})();
