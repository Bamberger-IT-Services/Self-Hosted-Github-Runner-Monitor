/* Info & Hilfe (Design 0.8.0, #97, #123): Runner-Liste, Verbindungen und die Anleitungen „Was tun, wenn …“,
   anbieterneutral und mit der Unit des gewählten Runners. Reine Logik ohne DOM, damit sie sich mit node
   prüfen lässt (tests/js/info.test.mjs). Im Browser als globales INFO. Die Texte kommen über die
   übergebene Übersetzungsfunktion t() (deutscher Text = Schlüssel in web/i18n.js); Werte sind schlichter
   Text, den dashboard.js beim Zeichnen maskiert. Zugangsdaten stehen hier nie: Server, Organisation und
   Token ändert man nur auf der VM (E-18, E-22) – die Oberfläche nennt den Befehl und die Token-Datei. */
'use strict';

const INFO = (() => {
  const SKRIPT = 'sudo /opt/runner-monitor/aktuell/einrichten.sh';
  const NAMEN = { github: 'GitHub', forgejo: 'Forgejo', gitea: 'Gitea', gitlab: 'GitLab' };
  const ID = /^[a-z0-9_]([a-z0-9._-]{0,62}[a-z0-9_])?$/;           // wie einrichten.sh (Runner-ID) und erkennung.als_id
  const EINHEIT = /^[A-Za-z0-9:_.@\\-]{1,200}$/;                  // wie erkennung.pruefe_unit (ohne Sonderfälle)
  const SERVER = /^(https?:\/\/[A-Za-z0-9.-]+(?::\d{1,5})?)(\/[A-Za-z0-9._~/-]*)?$/;
  const FEHLER_ABFRAGE = ['nicht-erreichbar', 'kontingent', 'fehler'];
  const KEIN_ZUGANG = ['kein-token', 'token-ungueltig', 'keine-rechte'];

  const dienstName = (d) => NAMEN[d] || null;
  const befehlZugang = (id) => `${SKRIPT} zugang ${ID.test(String(id || '')) ? id : 'RUNNER'}`;
  const tokenDatei = (id) => `/etc/runner-monitor/zugang/${ID.test(String(id || '')) ? id : 'RUNNER'}.token`;

  /* Adresse des Servers für Befehle: nur Schema, Host, Port und Pfad ohne Sonderzeichen, sonst null. */
  function serverBasis(server) {
    const m = SERVER.exec(String(server || ''));
    return m ? m[1] + (m[2] || '').replace(/\/+$/, '') : null;
  }
  const ohneSchema = (server) => String(server || '').replace(/^https?:\/\//, '');

  /* Unit für systemctl/journalctl in einfachen Anführungszeichen, null bei ungültigem Namen. */
  const einheit = (unit) => (typeof unit === 'string' && EINHEIT.test(unit) && !unit.startsWith('-') ? `'${unit}'` : null);

  /* ------------------------------------------------------------ Runner */

  /* Wie ein Fund in der Liste gilt (Pille neben dem Namen): ignoriert, neu gefunden, angebunden (der Dienst
     antwortet: runner[].stand), Grundüberwachung oder noch nicht angebunden (Zugangsdaten fehlen). */
  function einstufung(fund, r, neu) {
    if (fund.stand === 'ignoriert') return { art: 'ignoriert', cls: 'neutral' };
    if (neu) return { art: 'neu', cls: 'laeuft' };
    if (r && r.stand === 'angebunden') return { art: 'angebunden', cls: 'ok' };
    if (fund.stand === 'grund') return { art: 'grund', cls: 'neutral' };
    if (['github', 'angebunden', 'ohne-server'].includes(fund.anbindung)) return { art: 'noch', cls: 'warn' };
    return { art: 'grund', cls: 'neutral' };
  }

  /* Liste, wenn die Funde nicht geladen werden konnten: nur das, was runner[] kennt. */
  function fundeAusRunner(runner) {
    return (Array.isArray(runner) ? runner : []).map((r) => ({
      id: r.id, name: r.name, dienst: r.dienst, server: r.server || null, version: r.version || null, grad: null,
      einstufung: r.einstufung, stand: r.stand, unit: r.unit || null, anbindung: r.stand === 'angebunden' ? 'angebunden' : null, zuordnung: {},
    }));
  }

  /* IDs, die gegenüber der Liste vorher neu sind (nicht ignoriert). */
  function neueFunde(vorher, nachher) {
    const alt = new Set((vorher || []).map((f) => f.id));
    return (nachher || []).filter((f) => !alt.has(f.id) && f.stand !== 'ignoriert').map((f) => f.id);
  }

  const hatZugang = (f) => !!NAMEN[f.dienst];

  /* Eintrag für POST /api/einrichtung/runner/zuordnung aus dem Formular „Zuordnung ändern“: nur, was sich
     gegenüber dem Fund ändert; der Stand (grund/ignoriert) bleibt, wie er ist. Nur Felder der Oberfläche (E-22). */
  function formEintrag(f, w, dienstWahl) {
    const z = f.zuordnung || {};
    const e = { id: f.id, stand: z.stand === 'grund' || z.stand === 'ignoriert' ? z.stand : null };
    const leer = (x) => String(x || '').trim() || null;
    const neu = { dienst: dienstWahl.includes(w.dienst) ? w.dienst : 'unbekannt', name: leer(w.name), unit: leer(w.unit), log: leer(w.log) };
    const jetzt = { dienst: f.dienst, name: f.name, unit: f.unit || null, log: z.log || null };
    for (const k of ['dienst', 'name', 'unit', 'log']) if (neu[k] !== jetzt[k]) e[k] = neu[k];
    return e;
  }
  const geaendert = (e) => Object.keys(e).length > 2;

  /* Startwerte des Formulars. */
  function formStart(f) {
    const z = f.zuordnung || {};
    return { dienst: f.dienst || 'unbekannt', name: f.name || '', unit: f.unit || '', log: z.log || '' };
  }

  /* Statuszeile über der Liste. z = { erk: 'ruhe'|'laeuft'|'keine'|'zeit', zeit, erkZeit, anzahl, ignoriert }. */
  function erkennenText(z, f) {
    const { t, RM, jetzt } = f;
    if (z.erk === 'laeuft') return t('Suche Runner …');
    if (z.erk === 'zeit') return t('Die Erkennung antwortet nicht. Bitte später erneut versuchen.');
    if (z.erk === 'keine') return t('Keine Änderung · geprüft um {zeit}', { zeit: RM.hm(z.erkZeit || z.zeit || jetzt) });
    if (!z.zeit) return t('Noch keine Erkennung. Der Monitor sucht beim Start und alle 6 Stunden.');
    const tag = RM.tm(z.zeit) === RM.tm(jetzt) ? t('heute') : RM.tm(z.zeit), werte = { tag, z: RM.hm(z.zeit) };
    const basis = z.anzahl === 0 ? t('Kein Runner erkannt · zuletzt {tag} {z}, automatisch alle 6 Std.', werte)
      : z.anzahl === 1 ? t('1 Runner erkannt · zuletzt {tag} {z}, automatisch alle 6 Std.', werte)
        : t('{n} Runner erkannt · zuletzt {tag} {z}, automatisch alle 6 Std.', { ...werte, n: z.anzahl });
    return z.ignoriert ? `${basis} ${t('({n} ignoriert)', { n: z.ignoriert })}` : basis;
  }

  /* Zeilen der Liste: Punkt, Name, Plakette, Pille und kv. f = { t, RM, jetzt }, Daten = { funde, runner, neu, zeit }. */
  function runnerZeilen(daten, f) {
    const { t, RM } = f;
    const neu = new Set(daten.neu || []), grad = {
      sicher: t('sicher – eindeutige Merkmale, Server bestätigt'),
      wahrscheinlich: t('wahrscheinlich – Server nicht erreichbar'),
      unklar: t('unklar – nur allgemeine Hinweise'),
    };
    // „wahrscheinlich“ mit dem Grund aus der Erkennung (#145): z. B. „keine Registrierung gefunden“ statt pauschal „nicht erreichbar“
    const gradText = (fund) => (fund.grad === 'wahrscheinlich' && typeof fund.grund === 'string' && fund.grund
      ? t('wahrscheinlich – {grund}', { grund: t(fund.grund) }) : grad[fund.grad] || fund.grad);
    const pille = { angebunden: t('angebunden'), grund: t('Grundüberwachung'), noch: t('noch nicht angebunden'), neu: t('neu gefunden'), ignoriert: t('ignoriert') };
    const erkannt = daten.zeit ? (RM.tm(daten.zeit) === RM.tm(f.jetzt) ? t('heute') : RM.tm(daten.zeit)) + ' ' + RM.hm(daten.zeit) : '–';
    return (daten.funde || []).map((fund) => {
      const r = (daten.runner || []).find((x) => x.id === fund.id) || null;
      const istNeu = neu.has(fund.id) && fund.stand !== 'ignoriert';
      const st = einstufung(fund, r, istNeu);
      const server = fund.dienst === 'github' ? ohneSchema(fund.server) : String(fund.server || '');
      const kv = [[t('Server'), server || '–']];
      if (fund.grad) kv.push([t('Sicherheitsgrad'), gradText(fund), fund.grad === 'sicher' ? '' : 'warn']);
      kv.push([t('Unit'), fund.unit || '–'], [t('Letzte Erkennung'), istNeu ? t('gerade eben') : erkannt]);
      return {
        id: fund.id, name: fund.name, dienst: dienstName(fund.dienst) || t('unbekannt'), dienstId: fund.dienst,
        punkt: st.cls, pille: pille[st.art], pilleCls: st.cls, art: st.art, ignoriert: fund.stand === 'ignoriert', istNeu, kv,
        hatZugang: hatZugang(fund), befehl: befehlZugang(fund.id), fund,
      };
    });
  }

  /* ------------------------------------------------------------ Verbindungen */

  /* Eine Gruppe je angebundenem Dienst (Runner mit Fähigkeit „jobs“). Nur, was der Zustand hergibt – sonst „–“. */
  function verbindungen(runner, f) {
    const { t, RM, jetzt } = f;
    return (Array.isArray(runner) ? runner : []).filter((r) => r && r.faehig && r.faehig.jobs && r.jobsJeRepository).map((r) => {
      const j = r.jobsJeRepository, abf = j.abfrage, server = r.server ? String(r.server) : '';
      const kont = j.kontingent || {}, tage = j.tokenAblauf ? Math.ceil((RM.ms(j.tokenAblauf) - jetzt) / 86400000) : null;
      const fehl = KEIN_ZUGANG.includes(abf);
      const token = abf === 'ausstehend' ? '–' : abf === 'kein-token' ? t('nicht eingerichtet') : abf === 'token-ungueltig' ? t('ungültig oder abgelaufen') : abf === 'keine-rechte' ? t('ohne Zugriff') : t('hinterlegt');
      const rechte = r.dienst === 'github' ? t('Actions, Metadata, Self-hosted runners – je Read-only')
        : r.dienst === 'gitlab' ? 'read_api' : t('repository, organization – je Lesen');
      const letzte = abf === 'kein-token' ? t('aus') : abf === 'ausstehend' ? t('wird abgefragt') : abf === 'ok' ? t('{z} · erfolgreich', { z: RM.zeit(j.abgefragt) })
        : t('fehlgeschlagen · letzte erfolgreiche {z}', { z: j.abgefragt ? RM.zeit(j.abgefragt) : '–' });
      const kontingent = kont.limit ? t('{a} von {b} frei, Reset {z}', { a: RM.zahl(kont.frei), b: RM.zahl(kont.limit), z: RM.hm(kont.reset) })
        : (abf === 'ok' && r.dienst !== 'github' ? t('vom Server nicht gemeldet') : '–');
      const kv = [
        [t('Server'), server || '–'],
        [t('Organisation'), r.org || j.org || '–'],
        ['Token', token, fehl ? 'warn' : ''],
        [t('Rechte (nötig)'), rechte + (j.runnerGrund ? ` (${t(j.runnerGrund)})` : ''), j.runnerGrund ? 'warn' : ''],
        [t('Ablauf'), tage != null ? t('{d} (in {n} {tage})', { d: RM.datum(j.tokenAblauf), n: tage, tage: RM.mehrzahl(tage, t('Tag'), t('Tagen')) }) : '–', tage != null && tage <= 14 ? 'warn' : ''],
        [t('Letzte Abfrage'), letzte, !['ok', 'kein-token', 'ausstehend'].includes(abf) ? 'warn' : ''],
        [t('Nächste Abfrage'), '', '', 'naechste'],
        [t('API-Kontingent'), kontingent],
        [t('Token-Datei'), tokenDatei(r.id)],
      ];
      return { id: r.id, dienst: dienstName(r.dienst) || t('unbekannt'), titel: r.org || ohneSchema(server) || r.name, runner: r.name, kv };
    });
  }

  /* „Nächste Abfrage“ als Text (sekündlich neu gesetzt). */
  function naechste(r, f) {
    const { t, RM, jetzt } = f, j = r && r.jobsJeRepository;
    return j && j.naechste && j.abfrage !== 'kein-token' ? t('in {n} s (alle 30 s)', { n: Math.max(0, Math.round((RM.ms(j.naechste) - jetzt) / 1000)) }) : '–';
  }

  /* ------------------------------------------------------------ Was tun, wenn … */

  /* Anleitungen für den gewählten Runner. c: dienst, id, unit, server, org, grund (Stopp-Ursache) und die Flags der
     Lage (gestoppt, offline, fehlt, abfrage, tokenAblauf, knapp, getrennt, updNeu, updFehler). z (freiwillig): ein
     anderer Runner nur für „Zugangsdaten einrichten oder erneuern“ – der Link bei „Zugangsdaten ändern“. */
  function anleitungen(c, t, z) {
    const dienst = NAMEN[c.dienst] ? c.dienst : 'unbekannt', gh = dienst === 'github';
    const unit = einheit(c.unit);
    const u = unit || (gh ? "'actions.runner.*'" : "'UNIT.service'");
    const basis = serverBasis(c.server) || 'https://SERVER';
    /* Prüfbefehl für das Token eines Runners (der des Links „Anleitung: Zugangsdaten für …“, sonst der gewählte). */
    const pruefBefehl = (d) => {
      const art = NAMEN[d.dienst] ? d.dienst : 'unbekannt', datei = tokenDatei(d.id), server = serverBasis(d.server) || 'https://SERVER';
      const org = (re) => (re.test(d.org || '') ? d.org : 'ORGANISATION');  // sichtbarer Platzhalter statt eines erfundenen Namens
      if (art === 'github') return `curl -s -o /dev/null -w '%{http_code}\\n' \\\n  -H "Authorization: Bearer $(sudo cat ${datei})" \\\n  "https://api.github.com/orgs/${org(/^[A-Za-z0-9][A-Za-z0-9-]{0,38}$/)}/repos?per_page=1"`;
      if (art === 'gitlab') return `curl -s -o /dev/null -w '%{http_code}\\n' \\\n  -H "PRIVATE-TOKEN: $(sudo cat ${datei})" \\\n  "${server}/api/v4/personal_access_tokens/self"`;
      if (art === 'unbekannt') return null;
      return `curl -s -o /dev/null -w '%{http_code}\\n' \\\n  -H "Authorization: token $(sudo cat ${datei})" \\\n  "${server}/api/v1/orgs/${org(/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/)}"`;
    };
    const zd = z || c, pruefenToken = pruefBefehl(zd);

    const token = { id: 'token', titel: t('Zugangsdaten einrichten oder erneuern'), aktiv: KEIN_ZUGANG.includes(c.abfrage) || !!c.tokenAblauf,
      wann: t('Wenn „Kein Token“, „ohne Zugriff“ oder „Token läuft ab“ gemeldet wird. Je Dienst ein eigenes, nur lesendes Token. Es wird nur auf der VM eingetragen, nie in dieser Oberfläche.'), schritte: [
        [t('GitHub · Auf github.com: Profilbild › Settings › Developer settings › Personal access tokens › Fine-grained tokens › „Generate new token“.')],
        [t('Resource owner: die Organisation, nicht das eigene Konto. Repository access: All repositories. Ablauf zum Beispiel 1 Jahr.')],
        [t('Nur lesende Rechte: Repository › Actions „Read-only“ (Metadata kommt automatisch dazu). Für den Online-Status zusätzlich Organization › Self-hosted runners „Read-only“.')],
        [t('Verlangt die Organisation eine Freigabe: Organisation › Settings › Personal access tokens › Pending requests. Vorher meldet der Monitor „ohne Zugriff“.')],
        [t('Forgejo / Gitea · Auf dem Server: Einstellungen › Anwendungen › „Neues Token generieren“. Rechte repository und organization jeweils „Lesen“.')],
        [t('Forgejo / Gitea · Den Online-Status zeigt die Runner-Liste der Organisation nur ihren Besitzern. Ein Runner auf Instanz-Ebene (global) erscheint dort mit; ohne Besitzerrechte sieht ihn nur ein Administrator mit dem zusätzlichen Recht admin „Lesen“ (read:admin). Das ist freiwillig und weitreichend (Abwägung in docs/EINRICHTUNG.md) – ohne zeigt der Monitor „nicht sichtbar“, Dienst und Jobs bleiben sichtbar.')],
        [t('GitLab · Benutzer › Einstellungen › Zugriffstoken. Bereich read_api.')],
        [t('Auf der VM eintragen, die Eingabe bleibt unsichtbar. Das Skript fragt auch nach Server und Organisation, Enter behält die bisherigen:'), befehlZugang(zd.id)],
        ...(pruefenToken ? [[t('Prüfen, ob der Dienst das Token annimmt (200 = in Ordnung, 401 = ungültig, 403/404 = kein Zugriff):'), pruefenToken]] : []),
      ] };

    const sammler = [t('Keine Antwort: DNS, Firewall oder Proxy der VM prüfen. Letzte Meldungen des Sammlers:'), 'journalctl -u runner-monitor-sammler -n 30'];
    const erreichbar = { id: 'github', titel: t('Dienst nicht erreichbar (GitHub, Forgejo …)'), aktiv: FEHLER_ABFRAGE.includes(c.abfrage),
      wann: t('Wenn die Abfrage der Workflows fehlschlägt. Die Karte zeigt dann den letzten Stand.'),
      schritte: gh ? [
        [t('Zuerst den Status von GitHub prüfen: githubstatus.com.')],
        [t('Von der VM aus testen, ob die API antwortet:'), 'curl -sI https://api.github.com | head -1'],
        [t('Antwort 401: Token ungültig oder abgelaufen, siehe „Zugangsdaten einrichten oder erneuern“. Antwort 403: API-Kontingent erschöpft, die Abfrage setzt bis zum Reset aus.')],
        sammler,
      ] : dienst === 'unbekannt' ? [
        [t('Dieser Runner läuft in der Grundüberwachung: Der Monitor fragt keinen Dienst ab, deshalb gibt es hier nichts zu erreichen. Zuordnen lässt er sich unter „Runner“ › „Zuordnung ändern“.')],
        sammler,
      ] : [
        [t('Zuerst prüfen, ob der Server selbst läuft: {server} im Browser öffnen oder den Betreiber fragen.', { server: basis })],
        [t('Von der VM aus testen, ob der Server antwortet:'), dienst === 'gitlab' ? `curl -sI ${basis}/users/sign_in | head -1` : `curl -sI ${basis}/api/v1/version | head -1`],
        [t('Antwort 401: Token ungültig oder abgelaufen, siehe „Zugangsdaten einrichten oder erneuern“. Antwort 403 oder 404: kein Zugriff auf die Organisation. Antwort 429: zu viele Anfragen, die Abfrage setzt kurz aus.')],
        ...(String(c.server || '').startsWith('http://') ? [[t('Die Adresse beginnt mit http://. Der Monitor schickt ein Token nur dann unverschlüsselt, wenn in /etc/runner-monitor/runner.json für diesen Runner "http_erlaubt": true steht.')]] : []),
        sammler,
      ] };

    const start = unit ? `sudo systemctl start ${u}` : gh ? 'sudo systemctl start "$(cat /opt/actions-runner/.service)"' : `sudo systemctl start ${u}`;
    const gestoppt = { id: 'gestoppt', titel: t('Runner-Dienst gestoppt'), aktiv: !!c.gestoppt, cls: 'fehler', wann: t('Wenn der systemd-Dienst des Runners nicht läuft. Jobs bleiben dann in der Warteschlange.'), schritte: [
      [t('Status und letzte Meldungen ansehen:'), `systemctl status ${u}`],
      ...(c.grund === 'oom-kill' ? [
        [t('„oom-kill“: Ein Job hat den Arbeitsspeicher gesprengt. RAM und Swap ansehen – für Builds und Docker-Images mindestens 8 GB RAM plus Swap (docs/RUNNER.md):'), 'free -h; swapon --show'],
        ...(gh ? [[t('Dienst gegen Speichermangel einstellen (dann scheitert nur der Job) und fehlenden Swap anlegen:'), `${SKRIPT} runner`]] : []),
      ] : []),
      [t('Dienst starten:'), start],
      [t('Startet er nicht, das Protokoll prüfen:'), `journalctl -u ${u} -n 50`],
      [t('Wartende Jobs laufen danach von selbst an.')],
      [t('Woran es lag, steht in den Logs – siehe „Runner-Logs abrufen“.')],
    ] };

    const fehlt = { id: 'runner', titel: t('Kein Runner eingerichtet'), aktiv: !!c.fehlt, cls: 'warn', wann: t('Wenn auf dieser VM kein Runner gefunden wird.'), schritte: [
      [t('GitHub · Registrierungs-Token holen: GitHub › Organisation › Settings › Actions › Runners › „New self-hosted runner“ (1 Stunde gültig).')],
      [t('GitHub-Runner richtet das Skript auf der VM ein – es fragt Organisation, Token und Labels ab:'), `${SKRIPT} runner`],
      [t('Forgejo-, Gitea- und GitLab-Runner werden nach der Anleitung des Dienstes eingerichtet und als systemd-Dienst gestartet.')],
      [t('Der Monitor erkennt den Runner danach von selbst (alle 6 Stunden) oder sofort mit „Neu erkennen“ unter „Runner“.')],
    ] };

    const offline = { id: 'offline', titel: t('Runner offline beim Dienst'), aktiv: !!c.offline, cls: 'fehler',
      wann: t('Wenn der Dienst auf der VM läuft, der Server (GitHub, Forgejo …) den Runner aber nicht sieht.'), schritte: gh ? [
        [t('Netz der VM prüfen:'), 'curl -sI https://github.com | head -1'],
        [t('Dienst neu starten, damit er sich neu anmeldet:'), `sudo systemctl restart ${u}`],
        [t('Wurde der Runner in GitHub entfernt (Organisation › Settings › Actions › Runners), neu registrieren:'), `${SKRIPT} runner --umziehen`],
        [t('Warum die Verbindung fehlt, steht im Diagnoseprotokoll des Runners – siehe „Runner-Logs abrufen“.')],
      ] : [
        [t('Netz der VM prüfen:'), `curl -sI ${basis} | head -1`],
        [t('Dienst neu starten, damit er sich neu anmeldet:'), `sudo systemctl restart ${u}`],
        [t('Wurde der Runner auf dem Server entfernt (Organisation › Einstellungen › Actions › Runners, bei GitLab CI/CD › Runners), muss er dort nach der Anleitung des Dienstes neu registriert werden.')],
        [t('Warum die Verbindung fehlt, steht im Journal des Dienstes:'), `journalctl -u ${u} -n 50 --no-pager`],
      ] };

    const logs = { id: 'logs', titel: t('Runner-Logs abrufen (Diagnose)'), aktiv: !!c.gestoppt || !!c.offline, cls: c.gestoppt ? 'fehler' : 'warn',
      wann: t('Wenn der Runner-Dienst stoppt, abstürzt, offline ist oder Jobs nicht annimmt. Alle Befehle auf der VM ausführen.'), schritte: gh ? [
        [t('Dienst-Protokoll: Start, Stopp, Abstürze, Job-Start und -Ende. Die letzten 100 Zeilen:'), `journalctl -u ${u} -n 100 --no-pager`],
        [t('Dasselbe live mitlesen (Strg+C beendet):'), `journalctl -u ${u} -f`],
        [t('Diagnoseprotokoll des Runners: Anmeldung bei GitHub, Verbindungsfehler, Updates. Neueste Datei:'), 'sudo tail -n 100 "$(ls -t /opt/actions-runner/_diag/Runner_*.log | head -1)"'],
        [t('Protokoll des letzten Jobs (Worker), wenn ein Job abbricht oder hängt:'), 'sudo tail -n 100 "$(ls -t /opt/actions-runner/_diag/Worker_*.log | head -1)"'],
        [t('Ausgabe der einzelnen Schritte, eine Datei je Schritt:'), 'ls -lt /opt/actions-runner/_diag/pages/ | head'],
        [t('Logs abgeschlossener Jobs liegen bei GitHub: Repository › Actions › Lauf öffnen › Job › „Download log archive“.')],
        [t('Alles gebündelt zum Weitergeben, z. B. für eine Fehlersuche:'), `sudo tar czf ~/runner-diag.tgz -C /opt/actions-runner _diag\njournalctl -u ${u} --since today > ~/runner-journal.txt`],
      ] : [
        [t('Journal des Dienstes: Start, Stopp, Abstürze, Aufträge. Die letzten 100 Zeilen:'), `journalctl -u ${u} -n 100 --no-pager`],
        [t('Dasselbe live mitlesen (Strg+C beendet):'), `journalctl -u ${u} -f`],
        [t('Logs abgeschlossener Jobs liegen beim Dienst: Repository › Actions bzw. bei GitLab CI/CD › Pipelines › Job.')],
        [t('Alles gebündelt zum Weitergeben, z. B. für eine Fehlersuche:'), `journalctl -u ${u} --since today > ~/runner-journal.txt`],
      ] };

    const platte = { id: 'platte', titel: t('Platte knapp'), aktiv: !!c.knapp, wann: t('Wenn auf „/“ weniger als 25 GB frei sind.'), schritte: [
      [t('Der Runner räumt dann vor jedem Job selbst auf. Sofort aufräumen:'), 'sudo runner-aufraeumen'],
      [t('Wer belegt den Platz?'), 'docker system df'],
      [t('Freien Platz an Proxmox zurückgeben:'), 'sudo fstrim -av'],
      [t('Reicht das dauerhaft nicht, die Platte der VM in Proxmox vergrößern.')],
    ] };
    const monitor = { id: 'monitor', titel: t('Verbindung zum Monitor unterbrochen'), aktiv: !!c.getrennt, cls: 'fehler', wann: t('Wenn diese Seite keine Daten mehr von der VM bekommt. Sie zeigt dann den letzten Stand.'), schritte: [
      [t('Die Seite versucht es selbst weiter. Ist die VM im Netz erreichbar?'), `ping ${/^[A-Za-z0-9][A-Za-z0-9.-]{0,62}$/.test(c.vm || '') ? c.vm : 'runner-vm'}`],
      [t('Monitor-Dienst auf der VM neu starten:'), 'sudo systemctl restart runner-monitor'],
      [t('Letzte Meldungen des Monitors:'), 'journalctl -u runner-monitor -n 30'],
    ] };
    const update = { id: 'update', titel: t('Monitor aktualisieren'), aktiv: !!c.updNeu || !!c.updFehler, cls: c.updFehler ? 'fehler' : 'warn', wann: t('Wenn eine neue Version gemeldet wird oder ein Update fehlgeschlagen ist.'), schritte: [
      [t('Am einfachsten oben in „Updates“ auf „Jetzt aktualisieren“ klicken. Ein Hilfsdienst auf der VM lädt das offizielle Release, prüft die Prüfsumme, installiert es und startet den Monitor neu. Antwortet die neue Version nicht, stellt er die alte wieder her.')],
      [t('Oder per SSH auf der VM:'), `${SKRIPT} aktualisieren`],
      [t('Protokoll des letzten Updates:'), 'journalctl -u runner-monitor-update -n 50'],
      [t('Zur vorherigen Version zurück:'), `${SKRIPT} zurueck`],
    ] };
    return [token, erreichbar, gestoppt, fehlt, offline, logs, platte, monitor, update];
  }

  return { SKRIPT, NAMEN, dienstName, befehlZugang, tokenDatei, serverBasis, ohneSchema, einheit, einstufung, fundeAusRunner, neueFunde,
    hatZugang, formEintrag, geaendert, formStart, erkennenText, runnerZeilen, verbindungen, naechste, anleitungen };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = INFO;
