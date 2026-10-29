/*
 * Inhalt des Runner-Monitor-Entwicklerdashboards (gemeinsamer Aufbau der Entwicklerdashboards).
 *
 * Diese Datei pflegt Claude am Ende jeder Arbeitsrunde (CLAUDE.md, Anweisung 00):
 * neuer Stand, offene Entscheidungen, wichtige Hinweise. index.html nicht für Inhalte ändern.
 * `stand` aus: TZ=Europe/Berlin date +"%d.%m.%Y %H:%M"
 * Pfade relativ zur Wurzel des Repositorys; "datei:" = lokale Datei, sonst normale Adresse.
 *
 * ÖFFENTLICHES REPOSITORY: keine echten IP-Adressen, Rechnernamen, Tokens oder Passwörter.
 * Platzhalter: runner-vm, runner-vm-01, beispiel-org, <ip-der-runner-vm>, Adressen aus 192.0.2.0/24.
 *
 * Statuswerte – Aufgaben: "offen", "läuft" (= in Bearbeitung), "erledigt".
 *               Entscheidungen: "entschieden", "zurückgestellt", sonst offen.
 */
window.RUNNER_MONITOR = {
  stand: "29.10.2026 01:51",

  dienste: [
    { name: "Runner-Monitor lokal (Demo)", url: "http://127.0.0.1:8090/?demo", pruefen: "http://127.0.0.1:8090/api/health", gruppe: "Runner-Monitor" },
    { name: "Runner-Monitor lokal (echte Werte)", url: "http://127.0.0.1:8090/", pruefen: "http://127.0.0.1:8090/api/health", gruppe: "Runner-Monitor" },
    { name: "Monitor auf der Runner-VM", url: "http://<ip-der-runner-vm>:8090", pruefen: null, hinweis: "Platzhalter – Adresse der Runner-VM selbst einsetzen (nie ins Repository schreiben). Zustand auf der VM: curl -s http://127.0.0.1:8090/api/health", gruppe: "Runner-VM" },
  ],

  befehle: [
    {
      titel: "Monitor lokal starten",
      wann: "Im Klon auf dem Mac. Bindet nur an 127.0.0.1 und schaltet die Anmeldung ab. Demo unter 127.0.0.1:8090/?demo (Leiste zum Umschalten der Zustände). Strg+C beendet.",
      code: "cd ~/Desktop/git/DEV/proj-self-hosted-github-runner-monitor/Self-Hosted-Github-Runner-Monitor\nMONITOR_ENTWICKLUNG=1 MONITOR_DATEN_VERZ=./daten MONITOR_LAUF_VERZ=./lauf python3 -m runner_monitor",
    },
    {
      titel: "Tests",
      wann: "Vor jedem Commit. Nur Python-Standardbibliothek (unittest), keine Pakete nötig.",
      code: "cd ~/Desktop/git/DEV/proj-self-hosted-github-runner-monitor/Self-Hosted-Github-Runner-Monitor\npython3 -m unittest discover -s tests -t .",
    },
    {
      titel: "Shell-Skripte prüfen (shellcheck)",
      wann: "Wenn ein Skript geändert wurde. Die CI prüft dasselbe auf ubuntu-latest.",
      code: "cd ~/Desktop/git/DEV/proj-self-hosted-github-runner-monitor/Self-Hosted-Github-Runner-Monitor\nshellcheck einrichten.sh deploy/runner-einrichten.sh werkzeuge/paket.sh",
    },
    {
      titel: "Bildschirmfotos fürs Handbuch",
      wann: "Nach Änderungen an der Oberfläche. Nicht als root ausführen. Die erste Zeile nur einmal (Playwright). Bilder landen in docs/handbuch/bilder/ – nur Demo-Daten.",
      code: "cd ~/Desktop/git/DEV/proj-self-hosted-github-runner-monitor/Self-Hosted-Github-Runner-Monitor\nnpm i --no-save playwright@1 && npx playwright install chromium\nnode werkzeuge/bilder.mjs",
    },
    {
      titel: "Release-Paket bauen",
      wann: "Baut dist/runner-monitor-X.Y.Z.tar.gz und die .sha256 (Version aus VERSION). Veröffentlichen macht der Release-Workflow am GitHub-Release – nur nach OK von Tobias.",
      code: "cd ~/Desktop/git/DEV/proj-self-hosted-github-runner-monitor/Self-Hosted-Github-Runner-Monitor\nwerkzeuge/paket.sh",
    },
    {
      titel: "Zeitstempel für das Dashboard",
      wann: "Für „stand“ in daten.js und den Verlauf.",
      code: "TZ=Europe/Berlin date +\"%d.%m.%Y %H:%M\"",
    },
    {
      titel: "VM: installieren mit einem Befehl",
      wann: "Auf der Runner-VM (per SSH, im Home-Ordner). Holt den Stand von main, richtet Benutzer, Dienste, Firewall (Port 8090 nur aus dem LAN) und Runner-Erkennung ein und zeigt Adresse und Einrichtungscode. Für eine veröffentlichte Version mit Prüfsumme: docs/EINRICHTUNG.md.",
      code: "cd ~ && curl -fsSL https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/archive/refs/heads/main.tar.gz | tar xz && sudo ./Self-Hosted-Github-Runner-Monitor-main/einrichten.sh",
    },
    {
      titel: "VM: Status",
      wann: "Dienste, Version und Antwort des Monitors. /api/health meldet {\"ok\": true, \"version\": \"…\"}.",
      code: "sudo /opt/runner-monitor/aktuell/einrichten.sh status\ncurl -s http://127.0.0.1:8090/api/health; echo",
    },
    {
      titel: "VM: GitHub-Token eintragen oder erneuern",
      wann: "Fragt das Token verdeckt, danach die Organisation (Enter behält die bisherige), startet die Dienste neu. Token nie in Chat, Issue oder Notizen.",
      code: "sudo /opt/runner-monitor/aktuell/einrichten.sh token",
    },
    {
      titel: "VM: Update sofort prüfen",
      wann: "Statt bis zu 6 Stunden zu warten – wie Info › Updates › „Jetzt prüfen“. Danach erscheint „Version X.Y.Z verfügbar“, wenn es eine neuere gibt.",
      code: "sudo systemctl restart runner-monitor-sammler",
    },
    {
      titel: "VM: aktualisieren",
      wann: "Neueste Version installieren (wie der Knopf in Info › Updates). Zugang, Token und Einstellungen bleiben. Vorher die Release-Notiz lesen.",
      code: "sudo /opt/runner-monitor/aktuell/einrichten.sh aktualisieren",
    },
    {
      titel: "VM: zurück zur vorigen Version",
      wann: "Wenn sich eine neue Version falsch verhält. Die drei zuletzt installierten Versionen liegen unter /opt/runner-monitor/versionen/.",
      code: "sudo /opt/runner-monitor/aktuell/einrichten.sh zurueck",
    },
    {
      titel: "VM: entfernen",
      wann: "Dienste und Firewall-Regel entfernen, Daten bleiben. Mit --alles werden auch Daten, Zugang und Token gelöscht.",
      code: "sudo /opt/runner-monitor/aktuell/einrichten.sh entfernen\n# alles löschen: sudo /opt/runner-monitor/aktuell/einrichten.sh entfernen --alles",
    },
    {
      titel: "VM: Protokolle (journalctl)",
      wann: "Webserver und Sammler bzw. Update-Hilfsdienst. Mit -f statt -n 50 läuft es live mit (Strg+C beendet).",
      code: "sudo journalctl -u runner-monitor -u runner-monitor-sammler -n 50 --no-pager\nsudo journalctl -u runner-monitor-update -n 50 --no-pager",
    },
    {
      titel: "VM: Dienste neu starten",
      wann: "Nach Änderungen an /etc/runner-monitor/konfig.env oder wenn die Seite hängt. Der Runner läuft davon unberührt weiter.",
      code: "sudo systemctl restart runner-monitor runner-monitor-sammler",
    },
    {
      titel: "VM: Einrichtungscode oder Zugang neu",
      wann: "Code abgelaufen (60 Minuten) – nur solange kein Zugang besteht. „passwort“ löscht Zugang, Sitzungen und Sperren und zeigt einen neuen Code; Token und Einstellungen bleiben.",
      code: "sudo /opt/runner-monitor/aktuell/einrichten.sh code\n# Passwort vergessen:\nsudo /opt/runner-monitor/aktuell/einrichten.sh passwort",
    },
    {
      titel: "VM: GitHub-Runner einrichten oder umziehen",
      wann: "Registrierungs-Token aus GitHub › Organisation › Settings › Actions › Runners › „New self-hosted runner“ (gilt eine Stunde). --umziehen, wenn der Runner bisher an einem Repository hing oder in GitHub gelöscht wurde.",
      code: "sudo RUNNER_LABELS=bits /opt/runner-monitor/aktuell/einrichten.sh runner\n# Umzug: sudo RUNNER_LABELS=bits /opt/runner-monitor/aktuell/einrichten.sh runner --umziehen",
    },
  ],

  branch: "main",

  /*
   * Protokolle: Der Monitor schreibt keine Logdateien, sondern ins systemd-Journal der Runner-VM.
   * Einträge mit "code" werden als Befehl kopiert ("einheit" steht klein darunter).
   * Einträge mit "datei" würden eine Datei unter protokollordner öffnen (hier nicht genutzt).
   */
  protokollordner: "",
  protokolle: [
    { titel: "Monitor (Webserver, Port 8090)", einheit: "runner-monitor", code: "sudo journalctl -u runner-monitor -n 100 --no-pager", wann: "Seite lädt nicht, bleibt auf „Getrennt“, Anmeldung hakt" },
    { titel: "Sammler (GitHub, Docker, Releases)", einheit: "runner-monitor-sammler", code: "sudo journalctl -u runner-monitor-sammler -n 50 --no-pager", wann: "Workflows leer oder alt, Token-Fehler, neue Version wird nicht erkannt" },
    { titel: "Update-Hilfsdienst", einheit: "runner-monitor-update", code: "sudo journalctl -u runner-monitor-update -n 50 --no-pager\nsudo cat /var/lib/runner-monitor/update-status.json", wann: "„Update fehlgeschlagen“ – Grund und letzter Schritt" },
    { titel: "Monitor und Sammler live", einheit: "runner-monitor, runner-monitor-sammler", code: "sudo journalctl -u runner-monitor -u runner-monitor-sammler -f", wann: "Beim Testen mitlesen (Strg+C beendet)" },
    { titel: "Runner-Dienst live", einheit: "actions.runner.*", code: "sudo journalctl -u 'actions.runner.*' -f", wann: "Welche Jobs der Runner annimmt und wie sie enden (Strg+C beendet)" },
    { titel: "Runner-Diagnose (Runner_*.log)", einheit: "/opt/actions-runner/_diag", code: "sudo tail -n 100 \"$(ls -t /opt/actions-runner/_diag/Runner_*.log | head -1)\"", wann: "Runner offline bei GitHub, 401, „registration has been deleted“" },
    { titel: "Laufender Job (Worker_*.log)", einheit: "/opt/actions-runner/_diag", code: "sudo tail -f \"$(ls -t /opt/actions-runner/_diag/Worker_*.log | head -1)\"", wann: "Ein einzelner Job hängt" },
  ],

  /* Wenn etwas nicht geht: Anzeichen → was tun. Aus docs/runbooks/, docs/RUNNER.md und dem Chat. */
  fehlerhilfe: [
    { anzeichen: "Meldung „GitHub-Token ungültig“ (401), Karte Workflows leer", tun: "Token abgelaufen, widerrufen oder falsch kopiert. Neues Fine-grained Token anlegen (Resource owner = Organisation; Actions: Read-only, Metadata: Read-only, optional Self-hosted runners: Read-only) und mit „VM: GitHub-Token eintragen“ hinterlegen.", datei: "docs/runbooks/github-nicht-erreichbar.md" },
    { anzeichen: "„Keine Berechtigung“ / Token ohne Zugriff (403 oder 404)", tun: "Resource owner des Tokens ist nicht die Organisation, Rechte fehlen, oder die Organisation verlangt eine Freigabe: Organisation › Settings › Personal access tokens › Pending requests. 403 kann auch das Kontingent sein – Reset-Zeit unter Info › GitHub-Verbindung (reicht im 30-s-Takt für etwa 35 Repositories, A-07).", datei: "docs/EINRICHTUNG.md" },
    { anzeichen: "Workflows bleiben leer, im Sammler-Protokoll „MONITOR_ORG ist nicht gesetzt“", tun: "Organisation fehlt (z. B. GitHub in der Einrichtung übersprungen). „VM: GitHub-Token eintragen“ fragt seit 0.1.1 auch die Organisation ab. Alternativ MONITOR_ORG in /etc/runner-monitor/konfig.env setzen und „VM: Dienste neu starten“." },
    { anzeichen: "Meldung „Kein GitHub-Token“ (grau)", tun: "GitHub wurde bei der Einrichtung übersprungen – alles andere läuft. Token nachtragen mit „VM: GitHub-Token eintragen“." },
    { anzeichen: "„GitHub nicht erreichbar“, Workflows zeigen einen alten Stand", tun: "githubstatus.com prüfen. Auf der VM: curl -sI https://api.github.com | head -1 (HTTP/2 200). Sonst DNS, Proxy und Firewall nach außen prüfen.", datei: "docs/runbooks/github-nicht-erreichbar.md" },
    { anzeichen: "Meldung „Update fehlgeschlagen – Version X wurde wiederhergestellt“", tun: "Die alte Version läuft schon wieder. Grund im Protokoll „Update-Hilfsdienst“. Prüfsumme stimmt nicht → nicht von Hand installieren, Sicherheitsmeldung über GitHub. Sonst erneut versuchen (Info › Updates oder „VM: aktualisieren“); verhält sich die neue Version falsch → „VM: zurück zur vorigen Version“.", datei: "docs/runbooks/update-fehlgeschlagen.md" },
    { anzeichen: "„Version X verfügbar“ erscheint nicht, obwohl das Release da ist", tun: "Der Sammler fragt nur alle 6 Stunden. Info › Updates › „Jetzt prüfen“ oder „VM: Update sofort prüfen“. Das Release muss veröffentlicht sein (kein Entwurf) und runner-monitor-X.Y.Z.tar.gz samt .sha256 tragen (Release-Workflow).", datei: "docs/UPDATE.md" },
    { anzeichen: "Meldung „Runner-Dienst gestoppt“ (rot), Jobs bleiben in der Warteschlange", tun: "Erst Platz prüfen (df -h /, unter 5 GB → Platte knapp). Dann sudo systemctl start 'actions.runner.*'. Den Grund zeigt das Protokoll „Runner-Dienst live“ bzw. journalctl -u 'actions.runner.*' -n 100.", datei: "docs/runbooks/runner-dienst-gestoppt.md" },
    { anzeichen: "„Runner offline bei GitHub“, obwohl der Dienst läuft", tun: "Netz prüfen (curl -sI https://github.com | head -1). Im Protokoll „Runner-Diagnose“ nach 401 oder „runner registration has been deleted“ suchen → neu registrieren mit „VM: GitHub-Runner einrichten oder umziehen“ (--umziehen).", datei: "docs/runbooks/runner-dienst-gestoppt.md" },
    { anzeichen: "Job hängt auf „Queued“", tun: "Kein passender Runner frei: Labels im runs-on passen nicht (z. B. bits fehlt am Runner), Variable EIGENER_RUNNER falsch geschrieben, Runner offline oder belegt (Jobs laufen nacheinander). Labels: GitHub › Organisation › Settings › Actions › Runners.", datei: "docs/RUNNER.md" },
    { anzeichen: "„Platte knapp: n GB frei“ oder Jobs scheitern mit „No space left on device“", tun: "sudo runner-aufraeumen (Container, Images, Volumes, Build-Cache), danach sudo fstrim -av. Reicht es dauerhaft nicht: VM-Platte im Hypervisor vergrößern. Große Dateien außerhalb von Docker und _work nicht blind löschen.", datei: "docs/runbooks/platte-voll.md" },
    { anzeichen: "Monitor-Seite lädt nicht oder bleibt auf „Getrennt“", tun: "„VM: Status“ und Protokoll „Monitor“ ansehen. Antwortet /api/health lokal, aber nicht im Browser: Firewall (sudo ufw status | grep 8090). Sonst „VM: Dienste neu starten“. „Konfiguration ungültig“ → konfig.env mit deploy/konfig.env.example vergleichen.", datei: "docs/runbooks/monitor-startet-nicht.md" },
    { anzeichen: "Anmeldung: „Zu viele Fehlversuche“ oder Passwort vergessen", tun: "Gesperrt: 5 Minuten warten (5 Fehlversuche je Konto oder 30 je Adresse in 15 Minuten). Vergessen: „VM: Einrichtungscode oder Zugang neu“ (passwort) – neuen Code im Browser eingeben, Zugang neu anlegen, GitHub-Schritt überspringen.", datei: "docs/runbooks/zugang-gesperrt.md" },
    { anzeichen: "Einrichtung im Browser: Code abgelaufen oder falsch", tun: "Der Code gilt 60 Minuten und 10 Versuche. Neuer Code mit „VM: Einrichtungscode oder Zugang neu“ (code) – geht nur, solange noch kein Zugang besteht." },
    { anzeichen: "„./einrichten.sh: No such file or directory“", tun: "./einrichten.sh gibt es nur im entpackten Ordner. Nach der Installation immer den vollen Pfad sudo /opt/runner-monitor/aktuell/einrichten.sh … nutzen." },
    { anzeichen: "CI auf dem eigenen Runner: „Instanz ci existiert schon“", tun: "Reste eines abgebrochenen Laufs: docker ps -a, die Container des Projekts mit docker rm -f <name> entfernen; gründlich: sudo runner-aufraeumen. Der nächste Lauf legt sie neu an.", datei: "docs/RUNNER.md" },
    { anzeichen: "CI auf dem eigenen Runner: Node fehlt", tun: "Auf dem eigenen Runner ist Node nicht vorinstalliert: actions/setup-node mit node-version-file: .nvmrc." },
    { anzeichen: "Lokal: 127.0.0.1:8090 – „This site can't be reached“", tun: "Der Entwicklungsserver läuft nicht: „Monitor lokal starten“. Unter macOS zeigt 127.0.0.1:8090/ ohne /proc nur die Oberfläche – für Inhalte ?demo nutzen, z. B. ?demo&zustand=gestoppt&github=kein-token." },
    { anzeichen: "Dashboard per file:// → ERR_BLOCKED_BY_CLIENT", tun: "Der Browser in der Claude-App blockiert lokale Dateien. In Chrome öffnen: ~/Desktop/git/DEV/proj-self-hosted-github-runner-monitor/Self-Hosted-Github-Runner-Monitor/entwickler-dashboard/index.html (am besten als Lesezeichen)." },
    { anzeichen: "Befehl mit <Platzhalter> eingefügt → „syntax error near unexpected token“", tun: "Platzhalter in spitzen Klammern immer durch den echten Wert ersetzen; im Zweifel Claude nach dem fertigen Befehl fragen – echte Werte aber nie ins Repository." },
  ],

  hinweise: [
    { titel: "Version", text: "0.3.1 ist veröffentlicht (Live-Verbindung bleibt bei viel Log-Ausgabe stabil), davor v0.3.0 mit Design 0.3.0, v0.1.2 und v0.1.1. 0.4.0 setzt Design 0.4.0 um (Verlauf über die ganze Breite und über Neustarts, Job-Schritte aus einer Quelle); Release v0.4.0 veröffentlicht. Der Abnahmetest auf der Runner-VM läuft (#14).", datei: "CHANGELOG.md" },
    { titel: "Nächste Schritte", text: "1) v0.4.0 auf der VM einspielen („Jetzt prüfen“), Dashboard neu laden. 2) Im Betrieb prüfen, ob Verlauf und Schritte wie im Entwurf aussehen (#13). 3) Reihenfolge in „Ready“ festlegen. 4) Abnahme mit Rückweg (#14). Offen: wohin die frühere A-14 gehört (anderes Projekt-Repo)." },
    { titel: "Öffentliches Repository", text: "Keine echten IP-Adressen, Rechner-, Organisations- oder Personennamen und keine Tokens – auch nicht in Tests, Bildern, Logs oder diesem Dashboard. Platzhalter: runner-vm, runner-vm-01, beispiel-org, <ip-der-runner-vm>, Adressen aus 192.0.2.0/24 (RFC 5737)." },
    { titel: "Kein Docker (E-02, E-12)", text: "Der Monitor läuft nur als systemd-Dienst, auch nicht zusätzlich als Container – gilt auch dann, wenn eine Projektanweisung etwas anderes sagt („Als Docker sollte es dennoch funktionieren“ gilt nicht).", datei: "docs/adr/0002-systemd-statt-docker.md" },
    { titel: "Keine Lizenz (E-11)", text: "Keine LICENSE-Datei anlegen. Alle Rechte bei Bamberger IT Services, der Code ist nur zum Lesen öffentlich." },
    { titel: "Releases über den Browser", text: "Die Sitzung darf über die API keine Releases anlegen. Claude legt Releases deshalb über den Browser (GitHub angemeldet) an – und nur nach OK von Tobias. Der Release-Workflow hängt Paket und Prüfsumme an." },
    { titel: "Design-Grundlage", text: "Jetzt Design v0.3.0 in docs/design/ (Entwürfe neben dem Klon unter ../Runner-Monitor-Design-v0.3.0/). Design v1 bleibt eingefroren in docs/design/v1/. Bei Widerspruch gelten die Anweisungen; den Abgleich in docs/design/README.md pflegen.", datei: "docs/design/README.md" },
    { titel: "Abweichungen von den Anweisungen", text: "02 Stack (Next.js, Postgres) → Python-Standardbibliothek, JSON-Dateien (ADR-0001) · 01 Release (GHCR-Images, Trivy, Abnahme mit Compose) → tar.gz + SHA-256 am Release, kein Docker (ADR-0002) · 03 Zwei-Faktor → nur Passwort (ADR-0003, E-01) · 04 CSP mit Nonce → script-src 'self' ohne Inline-Skripte (Sicherheitsbericht S-CSP-01) · 04 Rate-Limit in Postgres → dateibasiert, sperren.json (ADR-0001) · 01 CI auf eigenem Runner → öffentliches Repo, immer ubuntu-latest (Anweisung 01 selbst).", datei: "CLAUDE.md" },
    { titel: "CI", text: "Läuft bei jedem PR auf ubuntu-latest, nie auf dem eigenen Runner – sonst könnte jeder per Pull Request Code auf der VM ausführen. In der Runner-Gruppe „Default“ bleibt „Allow public repositories“ aus." },
    { titel: "Nur Standardbibliothek", text: "Python-Standardbibliothek und Vanilla-JS, keine Pakete ohne ADR. Playwright nur als Werkzeug für Bildschirmfotos (npm i --no-save)." },
    { titel: "Oberfläche", text: "Ansprache „Sie“ in Anmeldung und Einrichtung, neutral im Dashboard, nie „du“ (E-10). CSP: keine Inline-Skripte, keine style=\"…\"-Attribute – Werte per element.style setzen." },
    { titel: "Produktive Schritte nur nach OK", text: "Release veröffentlichen, die VM umstellen und Einstellungen bei GitHub (z. B. #21) nur nach OK von Tobias." },
    { titel: "Doku im selben PR", text: "Jede Änderung an Bedienung, Einrichtung oder Betrieb passt im selben PR Handbuch, README, docs/EINRICHTUNG.md, docs/UPDATE.md, Runbooks und Sicherheitsbericht an. Nach jeder Arbeitsrunde dieses Dashboard (daten.js) pflegen." },
    { titel: "Ein Ort für die Runner-VM", text: "Einrichtung, Umzug, Pflege und Fehlerhilfe des Runners stehen hier in docs/RUNNER.md; das Public-Repo (Anweisung 01) verweist hierher; Projekt-Repos mit eigenem Runner-Abschnitt sollen ebenfalls hierher verweisen.", datei: "docs/RUNNER.md" },
    { titel: "GitHub-Kontingent", text: "Je Abfrage eine Anfrage je Repository plus drei, aber bedingt (ETag): unveränderte Antworten (304) kosten kein Kontingent; ruhige Repositories (über 1 Std. kein Push, nichts läuft/wartet) nur alle 5 Min. (#15)." },
  ],

  /*
   * Entscheidungen – feste Nummern (E-01 …), damit Tobias im Chat darauf verweisen kann („E-13: Variante A“).
   * Erledigte nicht löschen, sondern status: "entschieden" + antwort setzen. Quelle: DECISIONS.md.
   */
  entscheidungen: [
    { id: "E-01", thema: "Anmeldung", frage: "Zwei-Faktor-Anmeldung nach Anweisung 03 auch für den Monitor? Es gibt einen Zugang, nur im LAN, nur lesend.", optionen: ["Nur Passwort (Abweichung)", "Passwort + TOTP", "Gar keine Anmeldung"], datei: "docs/adr/0003-nur-passwort.md", status: "entschieden", antwort: "Nur Passwort, keine 2FA – Abweichung von Anweisung 03, ADR-0003 (Tobias, Auswahlfrage, 23.10.2026)" },
    { id: "E-02", thema: "Betrieb", frage: "Monitor als Docker-Container oder als normaler Dienst? Er braucht den Host (/proc, Journal, systemd, Dateien des Runners).", optionen: ["systemd-Dienst", "Docker-Container"], datei: "docs/adr/0002-systemd-statt-docker.md", status: "entschieden", antwort: "Normaler systemd-Dienst statt Docker, ADR-0002 (Tobias, 23.10.2026)" },
    { id: "E-03", thema: "Update", frage: "Wie kommen Updates aus den GitHub-Releases auf die VM?", optionen: ["1: nur Hinweis, Update per SSH", "2: Knopf über root-Hilfsdienst", "3: Webserver mit sudo-Regel"], datei: "docs/adr/0004-update-hilfsdienst.md", status: "entschieden", antwort: "Variante 2: per Knopf über den root-Hilfsdienst – Komfort ohne Rechte im Webserver, ADR-0004 (Tobias, 23.10.2026)" },
    { id: "E-04", thema: "Design", frage: "Design v1 (Canvas „Runner-Monitor · Design v1“) als Grundlage für 0.1.0 einfrieren?", optionen: ["Einfrieren", "Weiter abstimmen"], datei: "docs/design/README.md", status: "entschieden", antwort: "Eingefroren als Grundlage für 0.1.0, Kopie in docs/design/v1 (Tobias, 23.10.2026)" },
    { id: "E-05", thema: "Oberfläche", frage: "Docker-Container in Version 0.1 im Dashboard anzeigen?", optionen: ["Anzeigen", "Nicht anzeigen"], status: "entschieden", antwort: "Nicht anzeigen, die Daten werden aber gesammelt – Platz für Prozesse, Platten und ein größeres Log (Tobias, Kommentar im Design, 23.10.2026)" },
    { id: "E-06", thema: "Oberfläche", frage: "Wie werden Prozesse, Platten und Live-Log angeordnet?", optionen: ["Prozesse und Platten in einer Karte", "Getrennte Karten"], status: "entschieden", antwort: "Platten- und Prozessinfos in einer Karte, Log breiter und höher, Top 6 Prozesse (Tobias, Kommentare im Design, 23.10.2026)" },
    { id: "E-07", thema: "Oberfläche", frage: "Wo erscheinen Fehler und Warnungen?", optionen: ["Zentral in der Kopfzeile", "In den einzelnen Karten"], status: "entschieden", antwort: "Zentral oben in der Kopfzeile, jede mit „Was tun?“ zur Anleitung in Info & Hilfe – „muss sichtbarer sein“ (Tobias, 23.10.2026)" },
    { id: "E-08", thema: "Einrichtung", frage: "Wie läuft die Ersteinrichtung ab?", optionen: ["Skript → Code im Browser → Zugang → GitHub → Anmeldung", "Standardpasswort"], status: "entschieden", antwort: "Skript auf der VM (Dienste, Firewall, Runner-Erkennung, Code) → Browser (Code, Zugang, GitHub) → Anmeldung; Besitznachweis über die VM, kein Standardpasswort (Tobias, 23.10.2026)" },
    { id: "E-09", thema: "Stack", frage: "Stack nach Anweisung 02 (Next.js, Postgres) oder Python-Standardbibliothek?", optionen: ["Python-Standardbibliothek", "Next.js + TypeScript"], datei: "docs/adr/0001-python-standardbibliothek.md", status: "entschieden", antwort: "Python-Standardbibliothek, JSON-Dateien statt Postgres, ADR-0001 (Tobias, Vorgabe im Brief, 23.10.2026)" },
    { id: "E-10", thema: "Sprache", frage: "Ansprache: Design v1 nutzte teils „du“, die Anweisungen verlangen in Anmeldung und Einrichtung „Sie“.", optionen: ["„Sie“, Dashboard neutral", "„du“ wie im Entwurf"], status: "entschieden", antwort: "„Sie“ in Anmeldung und Einrichtung, im Dashboard neutral – die Anweisungen gehen dem Entwurf vor (Claude im Rahmen der Anweisungen, 23.10.2026)" },
    { id: "E-11", thema: "Repository", frage: "Lizenz für das öffentliche Repository (#31)? Ohne Lizenz sind alle Rechte vorbehalten.", optionen: ["MIT", "Keine Lizenz", "Apache-2.0"], status: "entschieden", antwort: "Keine Lizenz: alle Rechte bei Bamberger IT Services, der Code ist nur zum Lesen öffentlich (Tobias, Auswahlfrage, 23.10.2026)" },
    { id: "E-12", thema: "Betrieb", frage: "Die Projektanweisung sagt „Als Docker sollte es dennoch funktionieren“ – zusätzlich einen Container (privilegiert, --pid=host, Journal- und Runner-Mounts) anbieten (A-17)?", optionen: ["Zusätzlich Docker", "Kein Docker"], datei: "docs/adr/0002-systemd-statt-docker.md", status: "entschieden", antwort: "Kein Docker-Container, auch nicht zusätzlich – nur systemd; der Satz in der Projektanweisung gilt nicht, bestätigt E-02 (Tobias, 23.10.2026)" },
    { id: "E-13", thema: "Design", frage: "Netzwerk-Variante im Design 0.3.0: Wo steht die Netzauslastung?", optionen: ["Variante A: eigener Block in der RAM-Spalte", "Andere Variante"], datei: "docs/design/README.md", status: "entschieden", antwort: "Variante A: eigener Block in der RAM-Spalte – Vorgabe im Design (Claude nach Design-Vorgabe, 23.10.2026)" },
    { id: "E-14", thema: "Oberfläche", frage: "Sprache (#90): Texte auf echte Schlüssel mit de.json/en.json umbauen (Design 0.8.0) oder den deutschen Text als Schlüssel in web/i18n.js behalten?", optionen: ["Deutscher Text bleibt Schlüssel in web/i18n.js", "Umbau auf Schlüssel mit de.json/en.json"], datei: "web/i18n.js", status: "entschieden", antwort: "Deutscher Text bleibt Schlüssel in web/i18n.js: läuft seit 0.7.0, tests/test_i18n.py sichert die Vollständigkeit, der Umbau brächte Risiko ohne Nutzen. Umgesetzt in #90: Segment Automatisch | Deutsch | English, Wahl in localStorage „runner-monitor.sprache“ (auto|de|en, alter Schlüssel rm-sprache wird übernommen), Automatisch folgt navigator.languages[0] (Entscheidung von Claude im Auftrag von Tobias – Auftrag 29.10.2026: offene Themen selbstständig erledigen; jederzeit widerrufbar)" },
    { id: "E-15", thema: "Fehlermeldung", frage: "Was geschieht mit den GitHub-Issue-Vorlagen fehler.yml und idee.yml, nachdem Fehler und Ideen per E-Mail kommen (#98)?", optionen: ["Entfernen, config.yml mit E-Mail-Kontaktlink (a)", "Vorlagen behalten"], datei: ".github/ISSUE_TEMPLATE/config.yml", status: "entschieden", antwort: "Option (a): fehler.yml und idee.yml entfernt, config.yml verweist per mailto auf info@bamberger-it-services.de; aufgabe.yml bleibt (Claude im Auftrag von Tobias, 29.10.2026)" },
    { id: "E-16", thema: "Runner-Erkennung", frage: "Einstufung und Fähigkeiten von Forgejo, Gitea und GitLab, solange es keinen Adapter gibt (#91): wie heute lieferbar oder wie im Design-Ziel?", optionen: ["Wie heute lieferbar: „teil“, nur Dienst und Journal", "Wie im Design-Ziel: Forgejo/Gitea „voll“ schon jetzt"], datei: "runner_monitor/erkennung.py", status: "entschieden", antwort: "„teil“ bis zum Adapter, GitHub „voll“, updates überall false – die Oberfläche zeigt nur, was geliefert wird; ändert sich je Adapter nur in FAEHIG (Claude im Auftrag von Tobias (Review #107, 29.10.2026); jederzeit widerrufbar)" },
    { id: "E-17", thema: "Runner-Erkennung", frage: "Server-Probe auch für Funde ohne systemd-Unit (nur .runner in /home, nur ein Prozess)?", optionen: ["Nur für Funde mit Unit, sonst „Server nicht geprüft“", "Für alle Funde"], datei: "docs/sicherheit/bericht.md", status: "entschieden", antwort: "Nur für Funde mit Unit: eine Datei in /home kann jeder Benutzer anlegen und den root-Sammler sonst Adressen seiner Wahl abfragen lassen (S-ERK-01) (Claude im Auftrag von Tobias (Review #107, 29.10.2026); jederzeit widerrufbar)" },
    { id: "E-18", thema: "Runner-Erkennung", frage: "Wie wird verhindert, dass ein nachgemachter Fund die ID und Zuordnung eines echten Runners übernimmt?", optionen: ["IDs an die Unit binden, Funde ohne Unit nie angebunden, Adapter nehmen Server/Log nur aus runner.json bzw. Zugangsdaten", "Keine Einschränkung"], datei: "runner_monitor/erkennung.py", status: "entschieden", antwort: "IDs zuerst an Funde mit Unit, Funde ohne Unit nie „angebunden“ und ohne Log-Pfad; Adapter (#92, #93, #99) nehmen Server und Log-Pfad nur aus runner.json bzw. zugang/, nie aus dem Fund (Claude im Auftrag von Tobias (Review #107, 29.10.2026); jederzeit widerrufbar)" },
    { id: "E-19", thema: "Anbieter-Adapter", frage: "Wie ändert sich das Format von /api/zustand mit den Anbieter-Adaptern (#92), und was geschieht mit dem bestehenden GitHub-Token?", optionen: ["Additiv: bisherige Bereiche bleiben, dazu vm, runner[], meldungen[]; Token nach zugang/<runner>.token kopieren, alter Ort bleibt als Rückfall", "Sofort umstellen und Token verschieben"], datei: "docs/adr/0006-anbieter-adapter-und-zustand.md", status: "entschieden", antwort: "Additiv: GET /api/zustand (neu, nur angemeldet, ohne Live-Log) liefert die bisherigen Bereiche unverändert plus vm, runner[] (id, name, dienst, stand, einstufung, faehig, status, job mit schritt {nr, von|null, name}, letzteJobs, jobsJeRepository, log) und meldungen[] mit runner-ID; /events zusätzlich runner und meldungen. Die Oberfläche stellt mit #94 um, danach entfällt das Altformat in einem eigenen Issue. Das GitHub-Token wird beim ersten Start nach dem Update nach /etc/runner-monitor/zugang/<runner-id>.token kopiert (root 0700/0600), github-token bleibt Rückfall bis #94/#96 (Claude im Auftrag von Tobias, 29.10.2026; jederzeit widerrufbar)" },
    { id: "E-20", thema: "GitLab-Fähigkeiten", frage: "Soll die ausgelieferte Fähigkeiten-Tabelle für GitLab schon Jobs versprechen, wenn der Adapter da ist, der Sammler ihn aber noch nicht aufruft?", optionen: ["Nein: Grundüberwachung bis zur Anbindung (#94/#96); Adapter-Klasse darf mehr können als die Tabelle", "Ja, sofort jobs true"], datei: "DECISIONS.md", status: "entschieden", antwort: "FAEHIG[gitlab] bleibt Grundüberwachung bis zur Anbindung; Test: Tabelle verspricht nie mehr als der Adapter kann (Claude im Auftrag von Tobias, Review #113, 29.10.2026; jederzeit widerrufbar)" },
    { id: "E-21", thema: "Token nur über https", frage: "Darf der Monitor ein Token an einen Server mit http:// schicken?", optionen: ["Nur https://; http:// nur mit \"http_erlaubt\": true für diesen Runner in runner.json, dann ohne Proxy aus der Umgebung", "http:// immer erlauben"], datei: "DECISIONS.md", status: "entschieden", antwort: "Nur https://; http:// nur mit ausdrücklichem http_erlaubt in runner.json (Claude im Auftrag von Tobias, Review #113, 29.10.2026; jederzeit widerrufbar)" },
    { id: "E-20", thema: "Forgejo-/Gitea-Adapter", frage: "Wie werden Forgejo und Gitea nach der API-Prüfung (#93) eingestuft und angebunden?", optionen: ["„voll“ (Status, Jobs, Schritte, Logs), angebunden mit server/org in runner.json und Token in zugang/; Gitea nach OpenAPI", "Gitea „teil“, bis es an einer echten Instanz geprüft ist", "Beide „teil“, bis die Einrichtung im Browser (#96/#97) da ist"], datei: "docs/FUNKTIONSWEISE.md", status: "entschieden", antwort: "„voll“ für Forgejo und Gitea; Schritte bei Forgejo vor 17 je Runner false; angebunden nur mit Unit, server und org in runner.json und Token in zugang/<id>.token, sonst Grundüberwachung; Live-Log weiter aus dem Journal (Claude im Auftrag von Tobias, Auftrag zu #93, 29.10.2026; jederzeit widerrufbar – Alternative Gitea „teil“ ist eine Zeile in erkennung.py)" },
  ],

  /* Aufgaben stehen seit 23.10.2026 als Issues im GitHub-Project (Anweisung 08), nicht mehr hier.
   * Die alte Liste A-01 … A-24 liegt in der Git-Historie; jedes Issue nennt seine alte Nummer („früher A-nn“). */
  board: {
    url: "https://github.com/orgs/Bamberger-IT-Services/projects/5",
    titel: "Self-Hosted-Github-Runner-Monitor Roadmap",
    issues: "https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/issues",
    neu: "mailto:info@bamberger-it-services.de",
  },

  /* Wo finde ich was: lokal, im Repository, auf der VM, im Monitor. Keine echten Adressen oder Rechnernamen. */
  orte: [
    { gruppe: "Lokal auf dem Mac", titel: "Lokaler Klon", wo: "~/Desktop/git/DEV/proj-self-hosted-github-runner-monitor/Self-Hosted-Github-Runner-Monitor", was: "Arbeitskopie des Repositorys; dieses Dashboard liegt darin unter entwickler-dashboard/." },
    { gruppe: "Lokal auf dem Mac", titel: "Design 0.4.0 (Entwürfe)", wo: "../Runner-Monitor-Design-v0.4.0/", was: "Entpackte Fassung neben dem Klon (mit Bildschirmfotos aus dem Betrieb); die Entwürfe ohne Fotos liegen im Repository unter docs/design/v0.4.0/.", datei: "../Runner-Monitor-Design-v0.4.0/" },
    { gruppe: "Lokal auf dem Mac", titel: "Entwicklungsdaten", wo: "daten/ und lauf/", was: "Entstehen beim lokalen Start (MONITOR_DATEN_VERZ, MONITOR_LAUF_VERZ): Zugang, Sitzungen, Einstellungen bzw. Ergebnisse des Sammlers. Stehen in .gitignore – nie committen.", datei: "daten/" },
    { gruppe: "Lokal auf dem Mac", titel: "Release-Paket", wo: "dist/", was: "runner-monitor-X.Y.Z.tar.gz und .sha256 nach werkzeuge/paket.sh. Steht in .gitignore.", datei: "dist/" },
    { gruppe: "Im Repository", titel: "Programm und Oberfläche", wo: "runner_monitor/ · web/", was: "Server, Sammler, Update-Hilfsdienst (Python) und die Oberfläche (HTML, CSS, Vanilla-JS, demo.js). Übersicht der Dateien in docs/FUNKTIONSWEISE.md.", datei: "docs/FUNKTIONSWEISE.md" },
    { gruppe: "Im Repository", titel: "Einrichtungsskripte", wo: "einrichten.sh · deploy/runner-einrichten.sh", was: "Installation, Wartung und Entfernen des Monitors bzw. projektneutrale Einrichtung der Runner-VM.", datei: "einrichten.sh" },
    { gruppe: "Im Repository", titel: "systemd-Einheiten und Vorlage konfig.env", wo: "deploy/systemd/ · deploy/konfig.env.example", was: "runner-monitor.service, runner-monitor-sammler.service, runner-monitor-update.service und .path; Vorlage für /etc/runner-monitor/konfig.env.", datei: "deploy/systemd/" },
    { gruppe: "Im Repository", titel: "Design", wo: "docs/design/", was: "Design v0.3.0 und das eingefrorene Design v1 (v1/), Abgleich Design ↔ Code in README.md, Farben und Maße in TOKENS.md.", datei: "docs/design/README.md" },
    { gruppe: "Im Repository", titel: "Bildschirmfotos und Release-Notizen", wo: "docs/handbuch/bilder/ · docs/releases/", was: "Bilder entstehen mit werkzeuge/bilder.mjs (nur Demo-Daten); je Version eine Release-Notiz vX.Y.Z.md.", datei: "docs/releases/" },
    { gruppe: "Im Repository", titel: "Workflows", wo: ".github/workflows/ci.yml · release.yml", was: "CI bei jedem PR auf ubuntu-latest; der Release-Workflow hängt Paket und Prüfsumme an ein veröffentlichtes Release.", url: "https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/actions" },
    { gruppe: "Auf der VM", titel: "Programm", wo: "/opt/runner-monitor", was: "versionen/X.Y.Z/ (die drei letzten Versionen), Verweis aktuell auf die laufende, darin einrichten.sh.", code: "sudo /opt/runner-monitor/aktuell/einrichten.sh status" },
    { gruppe: "Auf der VM", titel: "Konfiguration und Token", wo: "/etc/runner-monitor", was: "konfig.env (root:runner-monitor, 0640) und github-token (nur root, 0600 – nur der Sammler liest es). Token nie anzeigen oder kopieren; ändern mit „VM: GitHub-Token eintragen“.", code: "sudo nano /etc/runner-monitor/konfig.env" },
    { gruppe: "Auf der VM", titel: "Daten des Monitors", wo: "/var/lib/runner-monitor", was: "zugang.json (scrypt-Hash), sitzungen.json, sperren.json, einstellungen.json, einrichtungscode.json, systempruefung.json, update-status.json, auftraege/.", code: "sudo ls -l /var/lib/runner-monitor" },
    { gruppe: "Auf der VM", titel: "Ergebnisse des Sammlers", wo: "/run/runner-monitor", was: "github.json, docker.json, release.json (root schreibt, alle lesen). Liegt im Arbeitsspeicher, nach einem Neustart frisch.", code: "ls -l /run/runner-monitor" },
    { gruppe: "Auf der VM", titel: "systemd-Einheiten", wo: "/etc/systemd/system/runner-monitor*", was: "runner-monitor (Webserver, Benutzer runner-monitor), runner-monitor-sammler (root), runner-monitor-update.service + .path (root, nur bei Bedarf).", code: "systemctl status runner-monitor runner-monitor-sammler runner-monitor-update.path --no-pager" },
    { gruppe: "Auf der VM", titel: "GitHub-Runner", wo: "/opt/actions-runner", was: "Registrierung .runner, Diagnose _diag/ (Runner_*.log, Worker_*.log, pages/ für das Live-Log), Arbeitsordner _work/. Dienst actions.runner.<organisation>.<name>.service.", code: "systemctl status 'actions.runner.*' --no-pager" },
    { gruppe: "Auf der VM", titel: "Monitor im Browser", wo: "http://<ip-der-runner-vm>:8090", was: "Port 8090 nur aus dem eigenen Netz (ufw-Regel des Einrichtungsskripts). Adresse selbst einsetzen." },
    { gruppe: "Im Monitor", titel: "Updates", wo: "Info › Updates", was: "Installierte und neueste Version, „Jetzt prüfen“, „Jetzt auf X.Y.Z aktualisieren“, Schalter „Automatisch aktualisieren“ (nachts 3 Uhr, nur ohne laufenden Job)." },
    { gruppe: "Im Monitor", titel: "GitHub-Verbindung", wo: "Info › GitHub-Verbindung", was: "Organisation, Token-Ablauf, Rechte, Kontingent und Reset-Zeit; nennt den Befehl zum Ändern auf der VM." },
    { gruppe: "Im Monitor", titel: "Runner-Logs abrufen und „Was tun, wenn …“", wo: "Info & Hilfe", was: "Kurzfassungen der Runbooks; „Was tun?“ an jeder Meldung springt direkt zur passenden Anleitung." },
    { gruppe: "Im Monitor", titel: "Demo-Zustände (lokal)", wo: "?demo&zustand=…&github=…", was: "Zustände per Adresse wählen, z. B. gestoppt und kein Token. Nur im lokalen Entwicklungsmodus.", url: "http://127.0.0.1:8090/?demo&zustand=gestoppt&github=kein-token" },
  ],

  links: [
    { titel: "README", datei: "README.md" },
    { titel: "Projektregeln (CLAUDE.md)", datei: "CLAUDE.md" },
    { titel: "Entscheidungen (DECISIONS.md)", datei: "DECISIONS.md" },
    { titel: "Änderungen (CHANGELOG.md)", datei: "CHANGELOG.md" },
    { titel: "Funktionsweise", datei: "docs/FUNKTIONSWEISE.md" },
    { titel: "Handbuch", datei: "docs/handbuch/README.md" },
    { titel: "Erstinstallation", datei: "docs/EINRICHTUNG.md" },
    { titel: "Update und Rückweg", datei: "docs/UPDATE.md" },
    { titel: "Runner-VM", datei: "docs/RUNNER.md" },
    { titel: "Runbooks", datei: "docs/runbooks/README.md" },
    { titel: "Sicherheitsbericht", datei: "docs/sicherheit/bericht.md" },
    { titel: "Datenschutz", datei: "docs/DATENSCHUTZ.md" },
    { titel: "Design-Abgleich", datei: "docs/design/README.md" },
    { titel: "Architekturentscheidungen (ADRs)", datei: "docs/adr/" },
    { titel: "Release-Notizen", datei: "docs/releases/" },
    { titel: "GitHub: Repository", url: "https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor" },
    { titel: "GitHub: Pull Requests", url: "https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/pulls" },
    { titel: "GitHub: Releases", url: "https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/releases" },
    { titel: "GitHub: Actions", url: "https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/actions" },
    { titel: "GitHub: Issues", url: "https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/issues" },
    { titel: "Gemeinsame Anweisungen (Public)", url: "https://github.com/Bamberger-IT-Services/Public/tree/main/anweisungen" },
  ],

  verlauf: [
    { datum: "29.10.2026 01:43", text: "Review #113 (GitLab-Adapter) eingearbeitet: FAEHIG[gitlab] wieder Grundüberwachung bis zur Anbindung (E-20); Token nur über https, http nur mit http_erlaubt in runner.json und ohne Proxy (E-21); Antworten Feld für Feld geprüft (Typen, NaN/Infinity, expires_at, id/tag_list/duration), unerwartete Antwort = Fehler; http.client-Fehler als nicht erreichbar; harte Gesamtfrist je Anfrage (Daemon-Faden, Test mit tröpfelndem Server); pausierte Runner gelten als offline; Doku zu Rollen, Instanz-Runnern, Version in /managers." },
    { datum: "29.10.2026 01:31", text: "#99 umgesetzt (PR offen): GitLab-Adapter runner_monitor/anbieter/gitlab.py (Token read_api, nur lesend, keine Weiterleitungen, Server nur aus der Konfiguration): Runner-Status, aktueller Job, letzte Jobs, laufende Jobs je Projekt über die GitLab-REST-API v4; ehrlich nicht verfügbar: Schritte und wartende Jobs. Fähigkeiten gitlab: jobs true, schritte false (erkennung.FAEHIG, Test mitgezogen); Einstufung bleibt teil. Fehlerfälle (nicht erreichbar, Token ungültig, keine Rechte, Kontingent, HTML statt JSON, Weiterleitung) mit tests/test_gitlab.py gegen einen lokalen Testserver mit neutralisierten Antworten. Doku: FUNKTIONSWEISE (Fähigkeiten-Tabelle, Abschnitt GitLab-Adapter mit Unsicherheiten), EINRICHTUNG › GitLab anbinden, Runbook gitlab-nicht-erreichbar, Sicherheitsbericht S-GITLAB-01, Design-Abgleich. Offen: Aufruf im Sammler (#94) und Eingabe im Browser (#96); Bestätigung gegen einen echten GitLab-Server." },
    { datum: "29.10.2026 01:33", text: "#94 umgesetzt (PR offen): Dashboard für mehrere Runner nach Design 0.8.0 Variante C – Reiter über „Runner-Status“, ab 4 Runnern „+N“ mit Liste, Wahl in localStorage runner-monitor.runner (Runner-ID), Dienst-Plakette und Runner-Name im Live-Log, Meldungen mit Runner und „Anzeigen“, Kartentitel „Jobs je Repository“. Die Oberfläche nutzt runner[] und meldungen[] (Rückfall aufs Altformat ohne runner); Logik in web/runner.js mit Node-Tests; Demo mit ?runner=1 bis 5. Runner ohne Jobs und das Journal je Runner bleiben #95." },
    { datum: "29.10.2026 01:53", text: "#93 umgesetzt (PR offen): API-Prüfung an Forgejo 17.0.1 (nur lesend) und nach OpenAPI (Forgejo 16, Gitea), Tabelle „Fähigkeiten je Anbieter“ in FUNKTIONSWEISE.md und in der Notiz des Spielplatzes. runner_monitor/anbieter/forgejo.py für Forgejo und Gitea: Online beim Dienst, Jobs je Repository, aktueller Job mit Schritten (Forgejo ab 17; Runner-Zuordnung über die erste Log-Zeile), letzte Jobs; eigener Klient nur GET, ohne Weiterleitungen, mit Grenzen. Sammler fragt angebundene Runner (server/org in runner.json, Token in zugang/) alle 30 s ab → /run/runner-monitor/anbieter.json; runner[] nutzt den Adapter. Einstufung Forgejo/Gitea „voll“ (E-20), Token-Rechte read:repository + read:organization in EINRICHTUNG.md, Sicherheitsbericht S-FORGEJO-01, tests/test_forgejo.py mit neutralisierten Antworten (tests/daten/)." },
    { datum: "29.10.2026 01:06", text: "#92 umgesetzt (PR offen): Paket runner_monitor/anbieter/ mit Basisklasse, Grundüberwachung, Registry und Fähigkeiten (status/jobs/schritte/logs/updates); GitHub als erster Adapter (Verhalten unverändert, alte Namen in github.py leiten weiter). GET /api/zustand neu (additiv: bisherige Bereiche + vm, runner[], meldungen[] mit Runner-ID), /events zusätzlich runner und meldungen; demo.js liefert die neuen Felder (?runner=2|3). Zugangsdaten je Runner in /etc/runner-monitor/zugang/<runner>.token (root 0700/0600), einrichten.sh zugang <runner>; altes GitHub-Token wird einmal kopiert, github-token bleibt Rückfall. E-19, ADR-0006, Sicherheitsbericht S-ADAPTER-01, tests/test_anbieter.py, tests/js/demo.test.mjs. Nebenbei behoben: Syntaxfehler in web/dashboard.js (seit Review #90, Dashboard lud nicht; als Hotfix #112 in develop). Review #111 eingearbeitet: veraltete Token-Kopie wird ersetzt, Schreibfehler entfernen sie und werden ohne Token gemeldet, stand „angebunden“ nur bei gültigem Token, runner[].log ohne Pfade, einrichten.sh zugang kennzeichnet den GitHub-Runner." },
    { datum: "29.10.2026 00:47", text: "#109 umgesetzt (PR offen): Review-Reste aus #107 – Sammler-Takt und -Frist mit time.monotonic(), stderr der Erkennung begrenzt ins Journal, einrichten.sh timeout --foreground, github.com auch ohne Netz sicher, Dienst aus der ersten Registrierung der Gruppe statt dienste[-1]. Offen: Version aus Runner.Listener.deps.json auf einer echten VM prüfen (Claude im Auftrag von Tobias)." },
    { datum: "29.10.2026 00:37", text: "#91 umgesetzt (PR offen): runner_monitor/erkennung.py erkennt GitHub-, Forgejo-, Gitea-, GitLab- und unbekannte Runner über systemd-Units, Prozesse, .runner/config.toml und eine Server-Probe ohne Zugangsdaten (Grad sicher/wahrscheinlich/unklar, Merkmale). einrichten.sh zeigt den Abschnitt „Runner auf dieser VM“ wie im Design; der Sammler sucht beim Start und alle 6 Std. (/run/runner-monitor/erkennung.json). runner.json nur gelesen. Review #107 eingearbeitet: Erkennung im Sammler als eigener Prozess mit 60 s Grenze, Server-Probe mit harter Frist (auch DNS), keine Symlinks außer Unit-Dateien, E-16 bis E-18 (Claude im Auftrag von Tobias)." },
    { datum: "29.10.2026 00:00", text: "#90 Sprache: Segment Automatisch | Deutsch | English in Info › Darstellung, Wahl in localStorage „runner-monitor.sprache“ (auto|de|en, alter Schlüssel rm-sprache einmalig übernommen), Automatisch folgt navigator.languages[0] (de* → Deutsch, sonst Englisch), Hinweistext nach Design 0.8.0; englische Texte der vorhandenen Oberfläche an das Wörterbuch des Designs angeglichen; Tests in tests/test_i18n.py und tests/js/i18n.test.mjs. E-14: deutscher Text bleibt Schlüssel in web/i18n.js, kein Umbau auf de.json/en.json." },
    { datum: "29.10.2026 00:00", text: "#98 umgesetzt: Fehler und Ideen per E-Mail statt GitHub-Issues (mailto: mit Vorlage und technischen Angaben, auch beim fehlgeschlagenen Update; Logik in web/mail.js, Test tests/js/mail.test.mjs). Handbuch, Datenschutz, README, CHANGELOG und Designabgleich angepasst. Review nachgezogen: Update-Fehler als Knopf neben „Erneut versuchen“, Briefumschlag-Symbol, Mailtext nach Main 0.8.0, Tokenfilter auch für 40-Hex. E-15: Issue-Vorlagen fehler.yml/idee.yml entfernt, config.yml mit E-Mail-Kontaktlink." },
    { datum: "28.10.2026 23:45", text: "Design 0.8.0: Epic #100 mit Teil-Issues #89–#99 und #101 angelegt (Labels, Meilenstein v0.8.0), Design in PR #102 abgelegt. #89 umgesetzt: Verlauf mit festen Zeitfenstern (Eimer am absoluten Zeitpunkt) und Zeitraum-Umschalter 30 s/2/5/10 Min.; Node-Tests in der CI. Offen: Entscheidungen zu #90 (feste Schlüssel) und #92 (Format /api/zustand), prio-Labels durch Tobias." },
    { datum: "25.10.2026 10:04", text: "0.7.0: #77 Nacht-Update wartet auf freien Runner (bis 7 Uhr, ein Versuch je Nacht), #78 Änderungen seit der installierten Version, Epic #79 Deutsch/Englisch (#80 Dashboard, #81 Anmeldung, Einrichtung, Server-Meldungen). #21 Branch-Schutz und private Sicherheitsmeldungen eingerichtet (OK Projektinhaber), #22–#24 auf Wunsch geschlossen." },
    { datum: "25.10.2026 00:55", text: "0.6.1: Runner nach OOM-Kill gestoppt (Rückmeldung aus dem Betrieb, VM auf 4 GB RAM ohne Swap). #70 RAM-Empfehlung in docs/RUNNER.md, #67 Runner-Einrichtung mit OOMPolicy=continue, Restart=on-failure und Swap, #68 Grund für gestoppten Dienst im Dashboard, #69 Runner-Version aus deps.json. Backlog geprüft: #21 (blocked, GitHub-Einstellungen), #22–#24 (brauchen Design) sind nicht erledigt." },
    { datum: "24.10.2026 00:03", text: "0.6.0: #63 Update gleich nach dem Release (Paket noch nicht angehängt → „wird bereitgestellt“, neue Prüfung nach 2 Min.; Rückmeldung aus dem Betrieb beim Update auf 0.5.0), #18 Herkunft per GitHub-Attestierung (ADR-0005), #20 ZAP-Baseline mit zwei behobenen Befunden (S-ZAP-01, S-HTTP-01). Offen: #21 (blocked), #22–#24 brauchen ein Design." },
    { datum: "23.10.2026 23:41", text: "0.5.0: Backlog abgearbeitet – #26 Netzlaufwerke, #15 Kontingent (ETag), #27 interne Namen, #19 Verbindungsgrenze, #57 Live-Log-Leser robust (Rückmeldung aus dem Betrieb), #16 Passwortliste, #17 HTTPS-Anleitung. #11–#14 nach Prüfung auf der VM geschlossen. #18 (Attestierung, E: GitHub-Attestierung) auf eigenem Branch, noch nicht im Release." },
    { datum: "23.10.2026 23:11", text: "Review der 0.4.0-Änderungen eingearbeitet (PR #51: gleichnamiger Folgejob, robuste verlauf.json, Schrittblock ohne Neuaufbau). Epic #42 geschlossen, Release v0.4.0 veröffentlicht (Workflow grün, Prüfsumme geprüft)." },
    { datum: "23.10.2026 23:04", text: "0.4.0 nach Design 0.4.0: #43 Verlauf (PR #47), #44 Job-Schritte (PR #48), #25 Demo-Version (PR #49), #45 Version, Doku und Handbuch-Bilder (neues Bild dashboard-neustart.png)." },
    { datum: "23.10.2026 22:50", text: "Design 0.4.0 übernommen (docs/design/v0.4.0, Design 0.3.0 nur noch im Tag v0.3.1). Epic #42 mit #43 Verlauf, #44 Job-Schritte, #45 Version und Doku, Milestone v0.4.0." },
    { datum: "23.10.2026 22:43", text: "Umstellung nach Anweisung 08: Aufgaben als Issues im Project „Self-Hosted-Github-Runner-Monitor Roadmap“ (17 offen im Backlog, 13 erledigt übernommen und geschlossen, Epic #11 „Design v0.3.0 vollständig umsetzen“ mit Sub-Issues #12 und #13). Labels, Milestone v0.4.0, Issue-Vorlagen, AGENTS.md. Aufgabenliste im Dashboard durch den Board-Link ersetzt." },
    { datum: "23.10.2026 22:18", text: "Release v0.3.1 veröffentlicht (Workflow grün, Prüfsumme geprüft)." },
    { datum: "23.10.2026 22:04", text: "0.3.1: Ursache für „Getrennt“ gefunden (Meldung Tobias von der VM): Jede Log-Zeile war eine eigene Nachricht, ein Build füllte die Warteschlange (2000), der Strom blieb danach stumm offen, der Browser verband nicht neu. Zeilen gebündelt, Strom endet bei Überlauf, Browser verbindet nach 10 s ohne Daten selbst neu, write() mit 60-s-Frist. Nachgestellt mit langsam lesendem Client." },
    { datum: "23.10.2026 21:31", text: "0.3.0: Design 0.3.0 pixelgenau umgesetzt (Dashboard mit Netz-Block, Info & Hilfe mit „Jetzt prüfen“ und Kopieren-Knöpfen, Live-Log mit Mitlaufen-Hinweis, Einrichtung und Anmeldung neu, einrichten.sh-Ausgabe). Design v1 entfernt, Design 0.3.0 unter docs/design/v0.3.0. Bildschirmfotos neu. Review: einrichten.sh ohne Docker, Klicks in sekündlich aktualisierten Karten, „Jetzt prüfen“ bei Uhrversatz, Anleitung „Kein Runner“." },
    { datum: "23.10.2026 21:06", text: "Entwickler-Dashboard auf den gemeinsamen Aufbau der Entwicklerdashboards umgestellt." },
    { datum: "23.10.2026 18:16", text: "0.1.2: Knopf „Jetzt prüfen“ in Info › Updates (Auftrag release-pruefen an den Sammler, höchstens einmal je Minute). Release v0.1.1 veröffentlicht (Workflow grün, Prüfsumme geprüft)." },
    { datum: "23.10.2026 18:04", text: "Release v0.1.1 (OK Tobias): CHANGELOG, Release-Notiz, Doku-Stand, Bildschirmfotos neu. Public-Repo: Anweisung 01 verweist zur Runner-Einrichtung hierher (PR #15)." },
    { datum: "23.10.2026 17:56", text: "Netzwerkauslastung ergänzt (Zeile „Netz“ in der Auslastung, /proc/net/dev ohne virtuelle Schnittstellen). PR #4 und Dependabot #2/#3 gemergt." },
    { datum: "23.10.2026 17:49", text: "0.1.1: Info-Blatt bleibt ruhig stehen, Live-Log lässt sich hochscrollen, Token-Befehl im Info-Menü, einrichten.sh token fragt die Organisation. Entscheidungen E-11 (keine Lizenz) und E-12 (kein Docker) nachgetragen." },
    { datum: "23.10.2026 16:29", text: "Version 0.1.0 programmiert: Server, Sammler, Update-Hilfsdienst, Oberfläche nach Design v1, einrichten.sh (inkl. Runner-Einrichtung und Ablösung der ttyd-Ansicht), Doku (Funktionsweise, Handbuch mit Bildern, Einrichtung, Update, Runner, Runbooks, Sicherheit), CI und Release-Workflow. Tests und Browser-Rauchtest grün." },
    { datum: "23.10.2026", text: "Design v1 abgestimmt und eingefroren (21 Bildschirme inkl. Einrichtung, Anmeldung, Updates). Entscheidungen E-01 bis E-08." },
  ],
};
