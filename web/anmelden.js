/* Runner-Monitor – Anmeldung. Ansprache „Sie“ (Anweisungen 03). */
'use strict';

(() => {
  const { $, IC, esc, hm } = RM;
  $('marke-icon').innerHTML = IC.server(28);
  $('marke-host').textContent = location.host;
  const form = $('formular'), knopf = $('absenden'), box = $('meldung');
  let sperreBis = 0, uhr = 0;

  function zeige(titel, text) {
    box.innerHTML = `${IC.x(16)}<span><b>${esc(titel)}</b>${text ? ' ' + esc(text) : ''}</span>`;
    box.hidden = false;
  }

  function sperre() {
    const rest = Math.ceil(sperreBis - Date.now() / 1000);
    if (rest <= 0) { clearInterval(uhr); knopf.disabled = false; knopf.textContent = 'Anmelden'; box.hidden = true; return; }
    knopf.disabled = true;
    knopf.textContent = `Gesperrt – noch ${Math.floor(rest / 60)}:${String(rest % 60).padStart(2, '0')}`;
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const nutzer = $('nutzer').value.trim(), passwort = $('passwort').value;
    $('nutzer').classList.toggle('falsch', !nutzer); $('passwort').classList.toggle('falsch', !passwort);
    if (!nutzer || !passwort) { zeige('Bitte Benutzername und Passwort eingeben.'); return; }
    knopf.disabled = true; knopf.textContent = 'Wird geprüft …';
    const r = await RM.sende('/api/anmelden', { nutzer, passwort, merken: $('merken').checked });
    if (r.ok) { location.href = '/'; return; }
    knopf.disabled = false; knopf.textContent = 'Anmelden';
    $('passwort').value = ''; $('passwort').classList.add('falsch'); $('passwort').focus();
    const d = r.daten || {};
    if (d.gesperrtBis) {
      sperreBis = d.gesperrtBis;
      zeige('Zu viele Fehlversuche.', `Die Anmeldung ist bis ${hm(sperreBis)} Uhr gesperrt. Danach können Sie es erneut versuchen.`);
      clearInterval(uhr); uhr = setInterval(sperre, 1000); sperre();
      return;
    }
    const rest = d.verbleibend;
    zeige(d.fehler || 'Anmeldung fehlgeschlagen.', rest != null && rest <= 3 ? `Noch ${rest} ${rest === 1 ? 'Versuch' : 'Versuche'}, dann wird die Anmeldung 5 Minuten gesperrt.` : '');
  });
  $('nutzer').focus();
})();
