/* Runner-Monitor – Ersteinrichtung im Browser (Design 0.3.0: Setup-Web).
   Schritte: 1 Code · 2 Zugang · 3 GitHub (optional) · 4 Fertig → Anmeldung. Ansprache „Sie“
   (E-10; Design 0.3.0 hat in Schritt 1 noch „Gib …“). */
'use strict';

(() => {
  const { $, IC, esc } = RM;
  const TITEL = ['Code', 'Zugang', 'GitHub', 'Fertig'];
  const SKRIPT = 'sudo /opt/runner-monitor/aktuell/einrichten.sh';
  const E = { codeOk: false, schritt: 1, pruefung: {}, nutzer: 'admin', zugang: false, org: '', github: null, ablauf: null, ergebnisse: null, laeuft: false, fertig: false };

  const ICO = {
    ok: '<svg class="ok" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="8" r="6.5"/><path d="M5.2 8.2l1.9 1.9 3.7-4"/></svg>',
    warn: '<svg class="warn" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 1.9l6.4 11.3H1.6z"/><path d="M8 6.3v3.2M8 11.4v.1"/></svg>',
    x: '<svg class="fehler" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="6.5"/><path d="M5.8 5.8l4.4 4.4M10.2 5.8l-4.4 4.4"/></svg>',
    aus: '<svg class="mut" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="6.5"/><path d="M5 8h6"/></svg>',
    haken: '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-label="erledigt" role="img"><path d="M3.5 8.4l3 3 6-6.6"/></svg>',
    fertig: '<svg class="fertig-ic" viewBox="0 0 16 16" width="44" height="44" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="8" r="6.6"/><path d="M5.2 8.2l1.9 1.9 3.7-4"/></svg>',
  };
  const zeile = (art, html) => `<div class="zeile">${ICO[art]}<span>${html}</span></div>`;
  const listenZeile = (art, titel, text) => `<div class="zeile">${ICO[art]}<b>${titel}</b><span class="mut">${text}</span></div>`;
  const meldung = (text) => `<div class="meldung-box fehler" role="alert">${ICO.x}<span>${esc(text)}</span></div>`;
  const datum = (t) => new Date(t * 1000).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });

  function kopf() {
    const p = E.pruefung || {};
    $('kopf-icon').innerHTML = IC.server();
    $('kopf-host').textContent = p.vm ? `${p.vm} · ${location.host}` : location.host;
  }

  function stepper() {
    $('stepper').innerHTML = TITEL.map((t, i) => {
      const nr = i + 1, cls = nr < E.schritt ? 'fertig' : nr === E.schritt ? 'aktiv' : '';
      return `${i ? '<span class="st-linie"></span>' : ''}<span class="st ${cls}"${nr === E.schritt ? ' aria-current="step"' : ''}><span class="st-nr">${nr < E.schritt ? ICO.haken : nr}</span>${t}</span>`;
    }).join('');
  }

  function zeichne(fehler) {
    stepper();
    const k = $('karte'), p = E.pruefung || {}, r = p.runner || {}, fw = p.firewall || {}, port = esc(p.port || 8090);
    let html = '';
    if (E.schritt === 1) {
      const erledigt = p.zeit ? `<div class="erkannt"><div class="erkannt-titel">Vom Skript erledigt</div>
          ${r.gefunden ? zeile('ok', `Runner <b>&#160;${esc(r.name || '')}&#160;</b> gefunden${r.aktiv === false ? ', Dienst nicht aktiv' : ', Dienst aktiv'}`) : zeile('warn', `Kein GitHub-Runner gefunden, der Monitor zeigt dann nur die VM. Später einrichten: <code>${SKRIPT} runner</code>`)}
          ${zeile('ok', 'Monitor-Dienst läuft als eigener Benutzer, nicht als root')}
          ${fw.aktiv ? zeile('ok', `Firewall aktiv: Port ${port} nur aus dem lokalen Netz${fw.netz ? ' ' + esc(fw.netz) : ''}, SSH bleibt erlaubt`) : zeile('warn', `Firewall (ufw) nicht aktiv: Port ${port} ist für alle erreichbar, die die VM erreichen`)}
        </div>` : '';
      html = `<section aria-label="Schritt 1: Einrichtungscode" class="karte-inhalt">
        <div class="eyebrow">Schritt 1 von 4</div>
        <h1>Einrichtung abschließen</h1>
        <p class="einl">Das Skript auf der VM ist durchgelaufen. Geben Sie den Einrichtungscode ein, den es am Ende angezeigt hat. So kann niemand sonst im Netz diesen Monitor übernehmen.</p>
        ${erledigt}${fehler || ''}
        <div class="feld">
          <label for="code">Einrichtungscode</label>
          <input id="code" class="gross" placeholder="XXXX-XXXX" autocomplete="one-time-code" autocapitalize="characters" spellcheck="false" maxlength="9" required>
          <span class="feld-hinweis">Code verloren oder abgelaufen? Neuen Code auf der VM anzeigen: <code>${SKRIPT} code</code></span>
        </div>
        <div class="fuss"><span class="mut fuss-text">Der Code gilt 60 Minuten.</span><span class="luecke"></span><button type="submit" class="knopf primaer">Weiter</button></div>
      </section>`;
    } else if (E.schritt === 2) {
      html = `<section aria-label="Schritt 2: Zugang schützen" class="karte-inhalt">
        <div class="eyebrow">Schritt 2 von 4</div>
        <h1>Zugang schützen</h1>
        <p class="einl">Der Monitor ist nur mit Benutzername und Passwort erreichbar. Damit melden Sie sich gleich nach der Einrichtung an. Auf Wunsch bleibt der Browser 30 Tage angemeldet.</p>
        ${fehler || ''}
        ${E.zugang ? `<div class="erkannt">${zeile('ok', `Zugang <b>&#160;${esc(E.nutzer)}&#160;</b> ist angelegt. Ändern später mit <code>${SKRIPT} passwort</code>.`)}</div>` : `<div class="breit-420">
          <div class="feld"><label for="nutzer">Benutzername</label><input id="nutzer" autocomplete="username" autocapitalize="none" spellcheck="false" maxlength="64" value="${esc(E.nutzer)}" required></div>
          <div class="feld"><label for="pw">Passwort</label><input id="pw" type="password" autocomplete="new-password" maxlength="128" required>
            <div class="staerke" id="staerke" aria-hidden="true"><span></span><span></span><span></span><span></span></div>
            <span class="feld-hinweis" id="pw-hinweis">Mindestens 12 Zeichen.</span>
          </div>
          <div class="feld"><label for="pw2">Passwort wiederholen</label><input id="pw2" type="password" autocomplete="new-password" maxlength="128" required>
            <span class="feld-hinweis" id="pw2-hinweis">&#160;</span>
          </div>
        </div>`}
        <p class="feld-hinweis hinweis-hash">Auf der VM wird nur ein Hash gespeichert, nur für root lesbar. Ändern später mit <code>${SKRIPT} passwort</code>.</p>
        <div class="fuss"><button type="button" class="knopf" id="zurueck">Zurück</button><span class="luecke"></span><button type="submit" class="knopf primaer">Weiter</button></div>
      </section>`;
    } else if (E.schritt === 3) {
      const erg = E.ergebnisse ? `<div class="pruef" role="status">${E.ergebnisse.map(x => zeile(x.ok ? 'ok' : x.warn ? 'warn' : 'x', esc(x.text))).join('')}</div>` : '';
      const erkanntOrg = r.dienst && E.org && /^actions\.runner\./.test(r.dienst);
      html = `<section aria-label="Schritt 3: GitHub anbinden" class="karte-inhalt">
        <div class="eyebrow">Schritt 3 von 4</div>
        <h1>GitHub anbinden<span class="optional">optional</span></h1>
        <p class="einl">Mit einem nur lesenden Token zeigt der Monitor, welche Workflows je Repository laufen und warten, und ob GitHub den Runner sieht. Ohne Token funktioniert alles andere trotzdem.</p>
        ${fehler || ''}
        <div class="zwei">
          <div>
            <div class="feld"><label for="org">Organisation</label><input id="org" autocapitalize="none" spellcheck="false" maxlength="39" value="${esc(E.org)}" placeholder="beispiel-org">${erkanntOrg ? '<span class="feld-hinweis">Aus der Runner-Konfiguration erkannt.</span>' : ''}</div>
            <div class="feld"><label for="token">Token</label><input id="token" class="mono" type="password" placeholder="github_pat_…" autocomplete="off" spellcheck="false"></div>
            <button type="button" class="knopf klein" id="pruefen">${E.laeuft ? 'Prüfe …' : E.ergebnisse ? 'Erneut prüfen' : 'Verbindung prüfen'}</button>
            ${erg}
          </div>
          <div class="anl">
            <div class="anl-titel">So erstellen Sie das Token</div>
            <ol>
              <li>Auf GitHub ein „Fine-grained token“ anlegen (Link unten).</li>
              <li>Resource owner: die Organisation. Repository access: <b>All repositories</b>.</li>
              <li>Repository-Rechte: <b>Actions</b> und <b>Metadata</b> jeweils „Read-only“.</li>
              <li>Organisations-Recht: <b>Self-hosted runners</b> „Read-only“, damit der Online-Status angezeigt wird.</li>
              <li>Ablauf z. B. 90 Tage. Der Monitor warnt 14 Tage vorher.</li>
              <li>Token kopieren und links einfügen.</li>
            </ol>
            <a href="https://github.com/settings/personal-access-tokens/new" rel="noopener" target="_blank">Token-Seite auf GitHub öffnen ↗</a>
          </div>
        </div>
        <div class="fuss"><button type="button" class="knopf" id="zurueck">Zurück</button><span class="luecke"></span><button type="button" class="knopf" id="ueberspringen">Ohne GitHub fortfahren</button><button type="submit" class="knopf primaer">Weiter</button></div>
        <p class="feld-hinweis hinweis-nachholen">Später auf der VM nachholen: <code>${SKRIPT} token</code></p>
      </section>`;
    } else {
      html = `<section aria-label="Schritt 4: Fertig" class="karte-inhalt">
        ${ICO.fertig}
        <h1>Alles eingerichtet</h1>
        <p class="einl">Der Monitor läuft. Legen Sie die Adresse als Lesezeichen an. Auf einem zweiten Bildschirm kann die Seite dauerhaft offen bleiben.</p>
        ${fehler || ''}
        <div class="liste">
          ${listenZeile('ok', 'Zugang geschützt', `Benutzer ${esc(E.nutzer)}`)}
          ${E.github ? listenZeile('ok', 'GitHub verbunden', `${esc(E.github)}${E.ablauf ? ' · Token bis ' + datum(E.ablauf) : ''}`) : listenZeile('aus', 'GitHub nicht verbunden', 'später nachholen, Anleitung unter „Info &amp; Hilfe“')}
          ${fw.aktiv ? listenZeile('ok', 'Firewall aktiv', `Port ${port} nur aus ${esc(fw.netz || 'dem lokalen Netz')}`) : listenZeile('warn', 'Firewall nicht aktiv', `Port ${port} ist für alle erreichbar, die die VM erreichen`)}
          ${r.gefunden ? listenZeile('ok', 'Runner wird überwacht', esc(r.name || '')) : listenZeile('warn', 'Kein Runner gefunden', 'der Monitor zeigt nur die VM')}
        </div>
        <p class="feld-hinweis hinweis-ende">Diese Einrichtung lässt sich nicht erneut im Browser aufrufen. Ändern auf der VM mit <code>${SKRIPT}</code>. Hilfe finden Sie später im Monitor unter „Info &amp; Hilfe“.</p>
        <div class="fuss"><button type="button" class="knopf" id="zurueck">Zurück</button><span class="luecke"></span><button type="submit" class="knopf primaer" id="zum-monitor">Zum Monitor anmelden</button></div>
      </section>`;
    }
    k.innerHTML = html;
    verdrahte();
  }

  /* Passwortstärke wie im Design: Länge, Groß/klein, Ziffer oder Sonderzeichen; unter 12 Zeichen höchstens 1 Punkt. */
  function staerke(pw) {
    const n = pw.length;
    let pkt = 0;
    if (n >= 8) pkt++; if (n >= 12) pkt++;
    if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) pkt++;
    if (/[0-9]/.test(pw) || /[^A-Za-z0-9]/.test(pw)) pkt++;
    if (n < 12) pkt = Math.min(pkt, 1);
    const text = n === 0 ? 'Mindestens 12 Zeichen.' : n < 12 ? `Noch ${12 - n} Zeichen bis zur Mindestlänge.` : `${['', 'Schwach', 'In Ordnung', 'Gut', 'Stark'][pkt]} · ${n} Zeichen`;
    return { pkt, text, warn: n > 0 && n < 12 };
  }

  let sendet = false;
  function verdrahte() {
    const f = $('karte');
    f.onsubmit = null;
    const zurueck = $('zurueck');
    if (zurueck) zurueck.addEventListener('click', () => { E.schritt = Math.max(1, E.schritt - 1); zeichne(); });
    if (E.schritt === 1) {
      const c = $('code');
      c.addEventListener('input', () => {
        let v = c.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 8);
        if (v.length > 4) v = v.slice(0, 4) + '-' + v.slice(4);
        c.value = v; c.classList.remove('falsch');
      });
      c.focus();
      f.onsubmit = async (e) => {
        e.preventDefault();
        // Schon angenommen (z. B. nach „Zurück“): ohne neue Eingabe weiter
        if (E.codeOk && !c.value) { E.schritt = 2; zeichne(); return; }
        if (c.value.replace('-', '').length !== 8) { c.classList.add('falsch'); return; }
        const r = await RM.sende('/api/einrichtung/code', { code: c.value });
        if (r.ok) { E.codeOk = true; E.schritt = 2; zeichne(); } else zeichne(meldung(r.daten.fehler || 'Code nicht angenommen.'));
      };
    } else if (E.schritt === 2) {
      if (E.zugang) { f.onsubmit = (e) => { e.preventDefault(); E.schritt = 3; zeichne(); }; return; }
      const pw = $('pw'), pw2 = $('pw2');
      const pruefe = () => {
        const s = staerke(pw.value);
        [...$('staerke').children].forEach((x, i) => x.classList.toggle('an', i < s.pkt));
        const h = $('pw-hinweis'); h.textContent = s.text; h.classList.toggle('warn', s.warn);
        const h2 = $('pw2-hinweis'), gleich = pw2.value.length > 0 && pw.value === pw2.value;
        h2.textContent = pw2.value.length === 0 ? ' ' : gleich ? '✓ Stimmt überein' : 'Stimmt noch nicht überein';
        h2.classList.toggle('ok', gleich); h2.classList.toggle('warn', pw2.value.length > 0 && !gleich);
      };
      pw.addEventListener('input', pruefe); pw2.addEventListener('input', pruefe);
      $('nutzer').focus();
      f.onsubmit = async (e) => {
        e.preventDefault();
        E.nutzer = $('nutzer').value.trim();
        if (!E.nutzer) { zeichne(meldung('Bitte einen Benutzernamen eingeben.')); return; }
        if (pw.value.length < 12) { pw.classList.add('falsch'); pw.focus(); return; }
        if (pw.value !== pw2.value) { pw2.classList.add('falsch'); pw2.focus(); return; }
        if (sendet) return; sendet = true;
        const r = await RM.sende('/api/einrichtung/zugang', { nutzer: E.nutzer, passwort: pw.value });
        sendet = false;
        if (r.ok) { E.zugang = true; E.schritt = 3; zeichne(); } else zeichne(meldung(r.daten.fehler || 'Zugang nicht angelegt.'));
      };
    } else if (E.schritt === 3) {
      const daten = () => ({ org: $('org').value.trim(), token: $('token').value.trim() });
      $('org').addEventListener('input', () => { E.org = $('org').value.trim(); });
      $('org').focus();
      const pruefen = async (d) => {
        E.laeuft = true; $('pruefen').textContent = 'Prüfe …'; $('pruefen').disabled = true;
        const r = await RM.sende('/api/einrichtung/github/pruefen', d);
        E.laeuft = false; E.ergebnisse = (r.daten && r.daten.ergebnisse) || [{ fehler: true, text: 'Prüfung fehlgeschlagen.' }];
        const ok = !!(r.daten && r.daten.ok);
        zeichne(); $('token').value = d.token; // Token nur im Feld halten, nie im Zustand
        return ok;
      };
      $('pruefen').addEventListener('click', async () => {
        const d = daten(); E.org = d.org;
        if (!d.org || !d.token) { zeichne(meldung('Bitte Organisation und Token eingeben.')); return; }
        await pruefen(d);
      });
      f.onsubmit = async (e) => {
        e.preventDefault();
        const d = daten(); E.org = d.org;
        if (!d.org || !d.token) { zeichne(meldung('Bitte Organisation und Token eingeben – oder „Ohne GitHub fortfahren“.')); return; }
        if (!(await pruefen(d))) return;
        const r = await RM.sende('/api/einrichtung/github/speichern', d);
        if (!r.ok) { zeichne(meldung(r.daten.fehler || 'Nicht gespeichert.')); return; }
        const erst = (E.ergebnisse || [])[0] || {};
        E.github = d.org; E.ablauf = erst.ablauf || null; E.schritt = 4; zeichne();
      };
      // Ein schon gespeichertes Token (Weiter, dann Zurück) bleibt gültig – Schritt 4 zeigt es weiter an.
      $('ueberspringen').addEventListener('click', () => { E.schritt = 4; zeichne(); });
    } else {
      // Erst hier ist die Einrichtung abgeschlossen; bis dahin geht „Zurück“ noch.
      f.onsubmit = async (e) => {
        e.preventDefault();
        if (!E.fertig) { await RM.sende('/api/einrichtung/fertig'); E.fertig = true; }
        location.href = '/anmelden';
      };
    }
  }

  fetch('/api/einrichtung/status', { credentials: 'same-origin' }).then(r => (r.ok ? r.json() : {})).then((d) => {
    E.pruefung = d.pruefung || {};
    if (d.codeGueltig) { E.codeOk = true; E.schritt = 2; }
    const dienst = (E.pruefung.runner || {}).dienst || '';
    const m = dienst.match(/^actions\.runner\.([A-Za-z0-9-]+)\./);
    if (m) E.org = m[1];
    kopf(); zeichne();
  }).catch(() => { kopf(); zeichne(); });
})();
