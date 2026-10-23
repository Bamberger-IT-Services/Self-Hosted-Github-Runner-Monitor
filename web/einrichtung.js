/* Runner-Monitor – Ersteinrichtung im Browser (Design v1: Setup-Web).
   Schritte: 1 Code · 2 Zugang · 3 GitHub (optional) · 4 Fertig → Anmeldung. Ansprache „Sie“. */
'use strict';

(() => {
  const { $, IC, esc } = RM;
  const SCHRITTE = ['Code', 'Zugang', 'GitHub', 'Fertig'];
  const E = { schritt: 1, pruefung: {}, nutzer: '', github: null, ergebnisse: null, org: '', laeuft: false };

  $('kopf-icon').innerHTML = IC.server(); $('kopf-host').textContent = location.host;

  function stepper() {
    $('stepper').innerHTML = SCHRITTE.map((n, i) => {
      const nr = i + 1, cls = nr < E.schritt ? 'fertig' : nr === E.schritt ? 'aktiv' : '';
      return `${i ? '<span class="st-linie"></span>' : ''}<span class="st ${cls}"${nr === E.schritt ? ' aria-current="step"' : ''}><span class="st-nr">${nr < E.schritt ? IC.ok(14, 2).replace('<circle cx="8" cy="8" r="6.5"/>', '') : nr}</span><span class="st-text">${n}</span></span>`;
    }).join('');
  }
  const meldung = (cls, titel, text) => `<div class="meldung-box ${cls}" role="alert">${cls === 'ok' ? IC.ok(16) : cls === 'warn' ? IC.warn(16) : IC.x(16)}<span><b>${esc(titel)}</b>${text ? ' ' + esc(text) : ''}</span></div>`;
  const zeile = (ok, text, warn) => `<div class="zeile"><span class="${ok ? 'ok' : warn ? 'warn' : 'fehler'}">${ok ? IC.ok(16) : warn ? IC.warn(16) : IC.x(16)}</span><span>${text}</span></div>`;

  function zeichne(fehler) {
    stepper();
    const k = $('karte'), p = E.pruefung || {}, r = p.runner || {};
    let html = '';
    if (E.schritt === 1) {
      const erkannt = p.zeit ? `<div class="erkannt"><div class="erkannt-titel">Vom Einrichtungsskript erkannt</div>
        ${zeile(true, `Monitor ${esc(p.monitorVersion || '')} läuft als Dienst <code class="inl">runner-monitor</code>`)}
        ${r.gefunden ? zeile(true, `Runner <b>${esc(r.name || '')}</b> gefunden${r.version ? ' · Version ' + esc(r.version) : ''}${r.dienst ? ' · Dienst ' + esc(r.dienst) : ''}`) : zeile(false, 'Kein GitHub-Runner gefunden – der Monitor zeigt dann nur die VM. Später einrichten: <code class="inl">sudo /opt/runner-monitor/aktuell/einrichten.sh runner</code>', true)}
        ${p.firewall && p.firewall.aktiv ? zeile(true, `Firewall aktiv · Port ${esc(p.port || 8090)} nur aus dem lokalen Netz`) : zeile(false, 'Firewall (ufw) nicht aktiv – der Port ist für alle erreichbar, die die VM erreichen', true)}
      </div>` : '';
      html = `<div class="eyebrow">SCHRITT 1 VON 4</div><h1>Einrichtungscode eingeben</h1>
        <p class="einl">Das Einrichtungsskript hat auf der VM einen achtstelligen Code angezeigt. Er beweist, dass Sie Zugriff auf die VM haben, und ist 60 Minuten gültig.</p>
        ${erkannt}${fehler || ''}
        <form id="f" novalidate class="breit-400">
          <div class="feld"><label for="code">Einrichtungscode</label><input id="code" class="gross" autocomplete="one-time-code" autocapitalize="characters" spellcheck="false" maxlength="9" placeholder="XXXX-XXXX" required>
          <span class="feld-hinweis">Code nicht mehr sichtbar oder abgelaufen? Neuen anzeigen: <code>sudo /opt/runner-monitor/aktuell/einrichten.sh code</code></span></div>
          <div class="form-fussleiste"><button type="submit" class="knopf primaer knopf-gross">Weiter</button></div>
        </form>`;
    } else if (E.schritt === 2) {
      html = `<div class="eyebrow">SCHRITT 2 VON 4</div><h1>Zugang anlegen</h1>
        <p class="einl">Mit diesem Benutzernamen und Passwort melden Sie sich künftig am Monitor an. Es gibt genau einen Zugang.</p>
        ${fehler || ''}
        <form id="f" novalidate class="breit-400">
          <div class="feld"><label for="nutzer">Benutzername</label><input id="nutzer" autocomplete="username" autocapitalize="none" spellcheck="false" maxlength="64" value="${esc(E.nutzer || 'admin')}" required></div>
          <div class="feld"><label for="pw">Passwort</label><input id="pw" type="password" autocomplete="new-password" maxlength="128" required>
            <div class="staerke" id="staerke" aria-hidden="true"><span></span><span></span><span></span><span></span></div>
            <span class="feld-hinweis" id="pw-hinweis">Mindestens 12 Zeichen. Ein Satz aus mehreren Wörtern ist leicht zu merken und sicher.</span></div>
          <div class="feld"><label for="pw2">Passwort wiederholen</label><input id="pw2" type="password" autocomplete="new-password" maxlength="128" required></div>
          <div class="form-fussleiste"><button type="submit" class="knopf primaer knopf-gross">Zugang anlegen</button></div>
        </form>`;
    } else if (E.schritt === 3) {
      const erg = E.ergebnisse ? `<div class="pruef" aria-live="polite">${E.ergebnisse.map(x => zeile(!!x.ok, esc(x.text), !!x.warn)).join('')}</div>` : '';
      const geprueft = E.ergebnisse && E.ergebnisse.length && !E.ergebnisse.some(x => x.fehler);
      html = `<div class="eyebrow">SCHRITT 3 VON 4</div><h1>Mit GitHub verbinden<span class="optional">optional</span></h1>
        <p class="einl">Mit einem nur lesenden Token zeigt der Monitor die Workflows aller Repositories und ob GitHub den Runner sieht. Ohne Token laufen Runner-Status, Auslastung und Log trotzdem.</p>
        ${fehler || ''}
        <div class="zwei">
          <form id="f" novalidate>
            <div class="feld"><label for="org">Organisation</label><input id="org" class="mono" autocapitalize="none" spellcheck="false" maxlength="39" value="${esc(E.org)}" placeholder="beispiel-org" required></div>
            <div class="feld"><label for="token">Fine-grained Token</label><input id="token" class="mono" type="password" autocomplete="off" spellcheck="false" placeholder="github_pat_…" required>
              <span class="feld-hinweis">Wird auf der VM in einer Datei gespeichert, die nur root lesen kann. Der Browser sieht es danach nicht mehr.</span></div>
            <div class="knopf-reihe"><button type="submit" class="knopf knopf-gross" id="pruefen">${E.laeuft ? 'Wird geprüft …' : 'Verbindung prüfen'}</button></div>
            ${erg}
          </form>
          <div class="anl-box">
            <div class="anl-box-titel">So erstellen Sie das Token</div>
            <ol>
              <li>github.com › Settings › Developer settings › Personal access tokens › <b>Fine-grained tokens</b> › „Generate new token“</li>
              <li>Resource owner: Ihre Organisation · Repository access: <b>All repositories</b> · Ablauf z. B. 90 Tage</li>
              <li>Repository permissions: <b>Actions</b> und <b>Metadata</b> – „Read-only“</li>
              <li>Organization permissions: <b>Self-hosted runners</b> – „Read-only“ (optional, für den Online-Status)</li>
              <li>Token kopieren und links einfügen</li>
            </ol>
            <a href="https://github.com/settings/personal-access-tokens/new" rel="noopener" target="_blank">Token auf GitHub erstellen ↗</a>
          </div>
        </div>
        <div class="form-fussleiste">
          <button type="button" class="knopf primaer knopf-gross" id="speichern"${geprueft ? '' : ' disabled'}>Speichern und weiter</button>
          <button type="button" class="knopf knopf-gross" id="ueberspringen">Überspringen</button>
          <span class="feld-hinweis">Später auf der VM nachholen: <code>sudo /opt/runner-monitor/aktuell/einrichten.sh token</code></span>
        </div>`;
    } else {
      html = `<div class="eyebrow">SCHRITT 4 VON 4</div><h1>Fertig eingerichtet</h1>
        <p class="einl">Der Monitor ist bereit. Melden Sie sich jetzt mit dem eben angelegten Zugang an.</p>
        <div class="liste breit-400">
          ${zeile(true, `Zugang <b>${esc(E.nutzer)}</b> angelegt`)}
          ${E.github ? zeile(true, `GitHub verbunden · Organisation <b>${esc(E.github)}</b>`) : zeile(false, 'GitHub nicht verbunden – später mit <code class="inl">sudo /opt/runner-monitor/aktuell/einrichten.sh token</code>', true)}
          ${E.pruefung.runner && E.pruefung.runner.gefunden ? zeile(true, `Runner <b>${esc(E.pruefung.runner.name || '')}</b> wird überwacht`) : zeile(false, 'Kein Runner gefunden – der Monitor zeigt nur die VM', true)}
          ${zeile(true, 'Updates: der Monitor prüft alle 6 Stunden auf GitHub, ob es eine neue Version gibt')}
        </div>
        <div class="form-fussleiste"><button type="button" class="knopf primaer knopf-gross" id="zum-monitor">Zum Monitor</button></div>`;
    }
    k.innerHTML = html;
    verdrahte();
  }

  function verdrahte() {
    const f = $('f');
    if (E.schritt === 1) {
      const c = $('code');
      c.addEventListener('input', () => {
        let v = c.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 8);
        if (v.length > 4) v = v.slice(0, 4) + '-' + v.slice(4);
        c.value = v;
      });
      c.focus();
      f.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (c.value.replace('-', '').length !== 8) { c.classList.add('falsch'); return; }
        const r = await RM.sende('/api/einrichtung/code', { code: c.value });
        if (r.ok) { E.schritt = 2; zeichne(); } else zeichne(meldung('fehler', 'Code nicht angenommen.', r.daten.fehler || ''));
      });
    } else if (E.schritt === 2) {
      const pw = $('pw'), pw2 = $('pw2');
      pw.addEventListener('input', () => {
        const n = pw.value.length, stufe = n === 0 ? 0 : n < 12 ? 1 : n < 16 ? 2 : n < 24 ? 3 : 4;
        [...$('staerke').children].forEach((s, i) => s.classList.toggle('an', i < stufe));
        $('pw-hinweis').textContent = n && n < 12 ? `Noch ${12 - n} Zeichen.` : 'Mindestens 12 Zeichen. Ein Satz aus mehreren Wörtern ist leicht zu merken und sicher.';
      });
      $('nutzer').focus();
      f.addEventListener('submit', async (e) => {
        e.preventDefault();
        E.nutzer = $('nutzer').value.trim();
        if (!E.nutzer) { zeichne(meldung('fehler', 'Bitte einen Benutzernamen eingeben.')); return; }
        if (pw.value.length < 12) { pw.classList.add('falsch'); pw.focus(); return; }
        if (pw.value !== pw2.value) { pw2.classList.add('falsch'); pw2.focus(); $('pw-hinweis').textContent = 'Die beiden Passwörter stimmen nicht überein.'; return; }
        const r = await RM.sende('/api/einrichtung/zugang', { nutzer: E.nutzer, passwort: pw.value });
        if (r.ok) { E.schritt = 3; zeichne(); } else zeichne(meldung('fehler', 'Zugang nicht angelegt.', r.daten.fehler || ''));
      });
    } else if (E.schritt === 3) {
      $('org').focus();
      const daten = () => ({ org: $('org').value.trim(), token: $('token').value.trim() });
      f.addEventListener('submit', async (e) => {
        e.preventDefault();
        const d = daten(); E.org = d.org;
        if (!d.org || !d.token) { zeichne(meldung('fehler', 'Bitte Organisation und Token eingeben.')); return; }
        E.laeuft = true; $('pruefen').textContent = 'Wird geprüft …'; $('pruefen').disabled = true;
        const r = await RM.sende('/api/einrichtung/github/pruefen', d);
        E.laeuft = false; E.ergebnisse = (r.daten && r.daten.ergebnisse) || [{ fehler: true, text: 'Prüfung fehlgeschlagen.' }];
        const token = d.token; zeichne(); $('token').value = token; // Token nur im Feld halten, nie im Zustand
      });
      $('speichern').addEventListener('click', async () => {
        const d = daten();
        const r = await RM.sende('/api/einrichtung/github/speichern', d);
        if (r.ok) { E.github = d.org; E.schritt = 4; await RM.sende('/api/einrichtung/fertig'); zeichne(); } else zeichne(meldung('fehler', 'Nicht gespeichert.', r.daten.fehler || ''));
      });
      $('ueberspringen').addEventListener('click', async () => { E.github = null; E.schritt = 4; await RM.sende('/api/einrichtung/fertig'); zeichne(); });
    } else {
      $('zum-monitor').addEventListener('click', () => { location.href = '/anmelden'; });
    }
  }

  fetch('/api/einrichtung/status', { credentials: 'same-origin' }).then(r => (r.ok ? r.json() : {})).then((d) => {
    E.pruefung = d.pruefung || {};
    if (d.codeGueltig) E.schritt = 2;
    zeichne();
  }).catch(() => zeichne());
})();
