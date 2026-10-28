// Runner-Monitor 0.8.0 · Übersetzung Deutsch → Englisch
// Standard: Sprache des Systems (de* → Deutsch, alles andere → Englisch). Wahl je Browser in localStorage „runner-monitor.sprache“ (auto | de | en).
// Im Design übersetzt dieses Skript die gerenderte Seite; in der Umsetzung dienen EXAKT/TEILE/MUSTER als Wörterbuch.
(function () {
  if (window.RM_I18N) return;
  const EXAKT = {
    // Kopf, allgemein
    "Info & Hilfe": "Info & Help", "Info und Hilfe": "Info and help", "Verbunden": "Connected", "Getrennt": "Disconnected",
    "Automatisch": "Automatic", "Hell": "Light", "Dunkel": "Dark", "Sprache": "Language", "Deutsch": "Deutsch", "English": "English",
    "Abmelden": "Sign out", "Schließen": "Close", "Weiter": "Continue", "Zurück": "Back", "Anhalten": "Pause", "Details": "Details",
    "Was tun?": "What to do?", "Was ist neu?": "What’s new?", "Anzeigen": "Show", "Ansehen ›": "View ›",
    "Name der VM (Hostname), nicht der Titel des Dienstes": "VM name (hostname), not the service title",
    "Darstellung: Automatisch, Hell oder Dunkel": "Display: automatic, light or dark", "Hell oder dunkel": "Light or dark",
    "Verbindung zum Monitor unterbrochen.": "Connection to the monitor lost.", "Angezeigt wird der Stand von": "Showing data from",
    "). Neuer Versuch läuft automatisch.": "). Retrying automatically.",
    "Runner wählen": "Select runner", "Auslastung, Prozesse und Platten gelten für die ganze VM": "Load, processes and disks apply to the whole VM",
    // Runner-Status
    "Runner-Status": "Runner status", "Aktueller Schritt": "Current step", "Schritte nicht verfügbar": "Steps not available", "von": "of",
    "Laufzeit": "Duration", "Gestartet": "Started", "Runner-Logs abrufen ›": "Get runner logs ›", "Letzte Jobs": "Recent jobs",
    "Job läuft": "Job running", "Bereit": "Ready", "Gestoppt": "Stopped", "Dienst gestoppt": "Service stopped", "Dienst aktiv": "Service active",
    "Offline bei GitHub": "Offline at GitHub", "Online bei GitHub": "Online at GitHub", "Online bei Forgejo": "Online at Forgejo",
    "Keine Anbindung": "Not connected", "keine Anbindung": "not connected", "GitHub: unbekannt": "GitHub: unknown", "GitHub: keine Antwort": "GitHub: no response",
    "Wartet auf den nächsten Job. Neue Jobs starten automatisch.": "Waiting for the next job. New jobs start automatically.",
    "Der Runner-Dienst läuft nicht. Neue Jobs bleiben bei GitHub in der Warteschlange, bis er wieder startet.": "The runner service is not running. New jobs stay queued at GitHub until it starts again.",
    "Der Dienst läuft, aber GitHub sieht den Runner nicht. Jobs werden ihm gerade nicht zugestellt.": "The service is running, but GitHub does not see the runner. Jobs are not being delivered to it.",
    "Nur Grundüberwachung: Dienst, Neustarts und Log. Jobs und Schritte sind ohne Anbindung an den Dienst nicht verfügbar.": "Basic monitoring only: service, restarts and log. Jobs and steps are not available without a connection to the service.",
    "Der Dienst meldet keine Schritte – Job und Laufzeit bleiben sichtbar.": "The service reports no steps – job and duration stay visible.",
    "Dienst": "Service", "Wartende Jobs": "Queued jobs", "Letzter Job": "Last job", "Bei GitHub": "At GitHub", "Runner-Version": "Runner version",
    "Neustarts": "Restarts", "keine in den letzten 7 Tagen": "none in the last 7 days", "Letzter Stopp": "Last stop",
    "Erfolg": "Success", "Fehler": "Failed", "Abgebrochen": "Cancelled", "wartet auf Jobs": "waiting for jobs", "meldet sich nicht bei GitHub": "not reporting to GitHub",
    "Node einrichten": "Set up Node", "Abhängigkeiten installieren": "Install dependencies",
    "Suche im Kundenbereich": "Search in customer area", "Abhängigkeiten aktualisiert": "Dependencies updated", "Kapitel Einrichtung ergänzt": "Added setup chapter",
    // Jobs je Repository
    "Jobs je Repository": "Jobs per repository", "Nichts läuft, nichts wartet": "Nothing running, nothing queued", "läuft": "running", "laufen": "running", "wartet": "queued", "warten": "queued",
    "GitHub nicht erreichbar": "GitHub unreachable", "– angezeigt wird der Stand von": "– showing data from", ". Neuer Versuch in": ". Retrying in",
    "Token läuft in 14 Tagen ab": "Token expires in 14 days", "). Danach bleibt dieser Bereich leer.": "). After that this area stays empty.",
    "Kein GitHub-Token eingerichtet": "No GitHub token set up", "Ohne Token bleibt dieser Bereich leer. Runner-Status, Auslastung und Log laufen normal weiter.": "Without a token this area stays empty. Runner status, load and log keep working.",
    "Anleitung: Token einrichten ›": "Guide: set up token ›", "Jobs nicht verfügbar": "Jobs not available",
    "Für diesen Runner gibt es keine Anbindung an den Dienst. Dienst, Auslastung und Log laufen normal weiter.": "This runner is not connected to its service. Service, load and log keep working.",
    "Runner zuordnen ›": "Assign runner ›", "Abfrage aus": "Polling off",
    // Auslastung
    "Auslastung": "Load", "CPU gesamt": "CPU total", "jetzt": "now", "Arbeitsspeicher": "Memory", "Netzwerk": "Network", "Netz": "Net", "Spitze": "Peak",
    "Last": "Load avg", "Kerne": "Cores", "empfangen": "received", "gesendet": "sent",
    "Zeitraum des Verlaufs": "History range", "Zeitraum für CPU-, RAM- und Netzwerk-Verlauf": "Range for CPU, RAM and network history",
    // Log
    "Live-Log": "Live log", "Umbrechen": "Wrap", "Abschneiden": "Truncate", "Lange Zeilen": "Long lines", "Ereignisse": "Events",
    "Ausgabe des laufenden Schritts": "Output of the running step", "Zum Ende ↓": "Jump to end ↓",
    "Job gestartet": "Job started", "Job beendet": "Job finished", "Runner meldet sich nicht mehr bei GitHub": "Runner no longer reports to GitHub",
    "Der Runner-Dienst ist gestoppt – es kommt keine Ausgabe.": "The runner service is stopped – no output.",
    "Kein Schritt läuft. GitHub stellt dem Runner gerade keine Jobs zu.": "No step running. GitHub is not delivering jobs to the runner.",
    "Kein Schritt läuft. Die Ausgabe erscheint hier, sobald ein Job startet.": "No step running. Output appears here as soon as a job starts.",
    "1 neue Zeile": "1 new line",
    // Prozesse, Platten, Container
    "Prozesse": "Processes", "Top 6 nach CPU": "Top 6 by CPU", "Benutzer": "User", "Befehl": "Command", "Platten": "Disks", "Platte": "Disk",
    "Prozesse, Platte und Container": "Processes, disk and containers", "Container": "Containers", "1 Laufwerk": "1 drive",
    "Aufräumen unter 25 GB frei": "Cleanup below 25 GB free", "Unter 25 GB frei": "Below 25 GB free", "– der Runner räumt vor jedem Job auf.": "– the runner cleans up before each job.",
    "Supabase · Instanz ci": "Supabase · instance ci",
    // Info › Runner
    "Runner": "Runners", "Neu erkennen": "Detect again", "1 neuer Runner gefunden:": "1 new runner found:", "Übernehmen": "Add", "Ignorieren": "Ignore",
    "Zuordnung ändern": "Change assignment", "Zugangsdaten ändern": "Change credentials", "anderer": "other", "Anzeigename": "Display name",
    "systemd-Unit": "systemd unit", "Log-Pfad": "Log path", "Speichern": "Save", "Abbrechen": "Cancel", "leer = Journal der Unit": "empty = unit journal",
    "Zugangsdaten werden aus Sicherheitsgründen nur auf der VM geändert. Der Befehl fragt Server, Organisation und Token ab und prüft die Verbindung:": "For security reasons, credentials are only changed on the VM. The command asks for server, organization and token and tests the connection:",
    "Anleitung:": "Guide:", "angebunden": "connected", "noch nicht angebunden": "not yet connected", "Grundüberwachung": "Basic monitoring", "ignoriert": "ignored",
    "Server": "Server", "Sicherheitsgrad": "Confidence", "Unit": "Unit", "Letzte Erkennung": "Last detection", "gerade eben": "just now", "Wieder anzeigen": "Show again",
    "sicher – eindeutige Merkmale, Server bestätigt": "certain – clear signs, server confirmed", "wahrscheinlich – Server nicht erreichbar": "likely – server unreachable",
    "unklar – nur allgemeine Hinweise": "unclear – only general hints", "Suche Runner …": "Searching for runners …", "unbekannt": "unknown",
    "Zugangsdaten für GitHub": "credentials for GitHub", "Zugangsdaten für Forgejo": "credentials for Forgejo", "Zugangsdaten für Gitea": "credentials for Gitea",
    // Verbindungen
    "Verbindungen": "Connections", "Organisation": "Organization", "Token": "Token", "nicht eingerichtet": "not set up", "hinterlegt, nur lesend": "stored, read-only",
    "Rechte": "Permissions", "Actions, Metadata, Self-hosted runners – je Read-only": "Actions, Metadata, Self-hosted runners – each read-only", "Ablauf": "Expires",
    "Letzte Abfrage": "Last poll", "Nächste Abfrage": "Next poll", "API-Kontingent": "API quota", "Token-Datei": "Token file",
    "vom Server nicht begrenzt": "not limited by the server", "repository, organization – je Lesen": "repository, organization – each read",
    // Updates
    "Updates": "Updates", "Installiert": "Installed", "Neueste": "Latest", "Geprüft": "Checked", "Jetzt prüfen": "Check now",
    "GitHub sofort nach einer neuen Version fragen (sonst alle 6 Std.)": "Ask GitHub for a new version now (otherwise every 6 h)",
    "Frage GitHub nach neuen Versionen …": "Asking GitHub for new versions …", "Auf dem neuesten Stand.": "Up to date.", "Version 0.8.1 ist verfügbar.": "Version 0.8.1 is available.",
    "Gerade erst geprüft – Stand siehe oben.": "Just checked – see status above.", "Gesperrt, solange das Update läuft.": "Locked while the update is running.",
    "GitHub nicht erreichbar:": "GitHub unreachable:", "keine Antwort von api.github.com nach 10 s. Der nächste automatische Versuch folgt in 6 Std.": "no response from api.github.com after 10 s. The next automatic attempt follows in 6 h.",
    "Keine Antwort vom Sammler.": "No response from the collector.", "Auf der VM prüfen:": "Check on the VM:", "Alle Änderungen auf GitHub ↗": "All changes on GitHub ↗",
    "Jetzt auf 0.8.1 aktualisieren": "Update to 0.8.1 now", "Dauert etwa eine Minute. Der Monitor ist dabei kurz nicht erreichbar, der Runner und laufende Jobs arbeiten weiter.": "Takes about a minute. The monitor is briefly unavailable; the runner and running jobs keep working.",
    "Aktualisiert auf 0.8.1": "Updated to 0.8.1", "– um": "– at", ". Dienst läuft, alle Daten kommen an.": ". Service running, all data arriving.", "Update fehlgeschlagen": "Update failed",
    "– Version 0.8.1 hat nach dem Neustart nicht geantwortet. Version 0.8.0 wurde automatisch wiederhergestellt und läuft wieder. Details:": "– version 0.8.1 did not respond after restarting. Version 0.8.0 was restored automatically and is running again. Details:",
    "Erneut versuchen": "Try again", "Fehler melden ↗": "Report a bug ↗", "Automatisch aktualisieren – nachts um 3 Uhr, nur wenn kein Job läuft": "Update automatically – at 3 am, only when no job is running",
    "Release 0.8.1 herunterladen": "Download release 0.8.1", "Prüfsumme prüfen": "Verify checksum", "SHA-256 stimmt": "SHA-256 matches", "alte Version gesichert": "old version backed up",
    "Monitor neu starten": "Restart monitor", "kurz nicht erreichbar": "briefly unavailable", "Funktion prüfen": "Check function", "Daten kommen an": "data arriving",
    "Neu seit dem Update": "New since the update", "Neu in 0.8.1": "New in 0.8.1", "Log-Suche im Live-Log": "Log search in the live log", "Kleinere Korrekturen in der Einrichtung": "Minor fixes in setup",
    "keine Antwort nach 30 s": "no response after 30 s", "Version 0.8.0 wiederhergestellt": "Version 0.8.0 restored", "läuft wieder": "running again", "läuft …": "running …",
    "actions-runner 2.329.0 · aktualisiert sich selbst": "actions-runner 2.329.0 · updates itself",
    // Darstellung
    "Darstellung": "Display", "Modus": "Mode", "„Automatisch“ folgt der Einstellung des Systems. Die Wahl gilt nur für diesen Browser.": "“Automatic” follows the system setting. The choice applies to this browser only.",
    "„Automatisch“ folgt der Sprache des Systems. Andere Sprachen als Deutsch zeigen Englisch. Die Wahl gilt nur für diesen Browser.": "“Automatic” follows the system language. Languages other than German show English. The choice applies to this browser only.",
    // Was tun, wenn …
    "Was tun, wenn …": "What to do if …", "jetzt aktiv": "active now",
    "Zugangsdaten einrichten oder erneuern": "Set up or renew credentials",
    "Wenn „Keine Anbindung“, „ohne Zugriff“ oder „Token läuft ab“ gemeldet wird. Je Dienst ein eigenes, nur lesendes Token.": "When “Not connected”, “no access” or “Token expires” is shown. One separate read-only token per service.",
    "Auf github.com: Profilbild › Settings › Developer settings › Personal access tokens › Fine-grained tokens › „Generate new token“.": "On github.com: profile picture › Settings › Developer settings › Personal access tokens › Fine-grained tokens › “Generate new token”.",
    "Resource owner: die Organisation, nicht das eigene Konto. Repository access: All repositories. Ablauf zum Beispiel 1 Jahr.": "Resource owner: the organization, not your own account. Repository access: All repositories. Expiry for example 1 year.",
    "Nur lesende Rechte: Repository › Actions „Read-only“ (Metadata kommt automatisch dazu). Für den Online-Status zusätzlich Organization › Self-hosted runners „Read-only“.": "Read-only permissions: Repository › Actions “Read-only” (Metadata is added automatically). For the online status also Organization › Self-hosted runners “Read-only”.",
    "Verlangt die Organisation eine Freigabe: Organisation › Settings › Personal access tokens › Pending requests. Vorher meldet der Monitor „ohne Zugriff“.": "If the organization requires approval: Organization › Settings › Personal access tokens › Pending requests. Until then the monitor shows “no access”.",
    "Auf der VM eintragen, die Eingabe bleibt unsichtbar. Das Skript fragt auch nach der Organisation, Enter behält die bisherige:": "Enter it on the VM; the input stays hidden. The script also asks for the organization; Enter keeps the current one:",
    "Prüfen, ob GitHub das Token annimmt (200 = in Ordnung, 401 = ungültig, 403/404 = kein Zugriff):": "Check whether GitHub accepts the token (200 = OK, 401 = invalid, 403/404 = no access):",
    "Forgejo / Gitea · Auf dem Server: Einstellungen › Anwendungen › „Neues Token generieren“. Rechte repository und organization jeweils „Lesen“.": "Forgejo / Gitea · On the server: Settings › Applications › “Generate new token”. Permissions repository and organization each “Read”.",
    "GitLab · Benutzer › Einstellungen › Zugriffstoken. Bereich read_api.": "GitLab · User › Preferences › Access tokens. Scope read_api.",
    "Dienst nicht erreichbar (GitHub, Forgejo …)": "Service unreachable (GitHub, Forgejo …)",
    "Wenn die Abfrage der Workflows fehlschlägt. Die Karte zeigt dann den letzten Stand.": "When polling jobs fails. The card then shows the last known data.",
    "Zuerst den Status von GitHub prüfen: githubstatus.com.": "First check GitHub’s status: githubstatus.com.", "Von der VM aus testen, ob die API antwortet:": "Test from the VM whether the API responds:",
    "Antwort 401: Token ungültig oder abgelaufen, siehe „GitHub-Token einrichten oder erneuern“. Antwort 403: API-Kontingent erschöpft, die Abfrage setzt bis zum Reset aus.": "Response 401: token invalid or expired, see “Set up or renew credentials”. Response 403: API quota used up, polling pauses until the reset.",
    "Keine Antwort: DNS, Firewall oder Proxy der VM prüfen. Letzte Meldungen der Abfrage:": "No response: check the VM’s DNS, firewall or proxy. Latest messages from the poller:",
    "Runner-Dienst gestoppt": "Runner service stopped", "Wenn der systemd-Dienst des Runners nicht läuft. Jobs bleiben dann in der Warteschlange.": "When the runner’s systemd service is not running. Jobs then stay queued.",
    "Status und letzte Meldungen ansehen:": "View status and latest messages:", "Dienst starten:": "Start the service:", "Startet er nicht, das Protokoll prüfen:": "If it does not start, check the log:",
    "Wartende Jobs laufen danach von selbst an.": "Queued jobs then start on their own.", "Woran es lag, steht in den Logs – siehe „Runner-Logs abrufen“.": "The cause is in the logs – see “Get runner logs”.",
    "Runner offline beim Dienst": "Runner offline at the service", "Wenn der Dienst auf der VM läuft, der Server (GitHub, Forgejo …) den Runner aber nicht sieht.": "When the service runs on the VM but the server (GitHub, Forgejo …) does not see the runner.",
    "Netz der VM prüfen:": "Check the VM’s network:", "Dienst neu starten, damit er sich neu anmeldet:": "Restart the service so it registers again:",
    "Wurde der Runner in GitHub entfernt (Organisation › Settings › Actions › Runners), neu registrieren:": "If the runner was removed in GitHub (Organization › Settings › Actions › Runners), register it again:",
    "Warum die Verbindung fehlt, steht im Diagnoseprotokoll des Runners – siehe „Runner-Logs abrufen“.": "Why the connection is missing is in the runner’s diagnostic log – see “Get runner logs”.",
    "Platte knapp": "Disk low", "Wenn auf „/“ weniger als 25 GB frei sind.": "When less than 25 GB are free on “/”.",
    "Der Runner räumt dann vor jedem Job selbst auf. Sofort aufräumen:": "The runner then cleans up before each job. Clean up now:", "Wer belegt den Platz?": "What uses the space?",
    "Freien Platz an Proxmox zurückgeben:": "Return free space to Proxmox:", "Reicht das dauerhaft nicht, die Platte der VM in Proxmox vergrößern.": "If that is not enough in the long run, enlarge the VM’s disk in Proxmox.",
    "Verbindung zum Monitor unterbrochen": "Connection to the monitor lost", "Wenn diese Seite keine Daten mehr von der VM bekommt. Sie zeigt dann den letzten Stand.": "When this page no longer receives data from the VM. It then shows the last known data.",
    "Die Seite versucht es selbst weiter. Ist die VM im Netz erreichbar?": "The page keeps retrying. Is the VM reachable on the network?", "Monitor-Dienst auf der VM neu starten:": "Restart the monitor service on the VM:",
    "Letzte Meldungen des Monitors:": "Latest messages from the monitor:", "Runner-Logs abrufen (Diagnose)": "Get runner logs (diagnostics)",
    "Wenn der Runner-Dienst stoppt, abstürzt, offline ist oder Jobs nicht annimmt. Alle Befehle auf der VM ausführen.": "When the runner service stops, crashes, is offline or does not accept jobs. Run all commands on the VM.",
    "Dienst-Protokoll: Start, Stopp, Abstürze, Job-Start und -Ende. Die letzten 100 Zeilen:": "Service log: start, stop, crashes, job start and end. The last 100 lines:",
    "Dasselbe live mitlesen (Strg+C beendet):": "Follow the same live (Ctrl+C stops):", "Diagnoseprotokoll des Runners: Anmeldung bei GitHub, Verbindungsfehler, Updates. Neueste Datei:": "Runner diagnostic log: GitHub sign-in, connection errors, updates. Newest file:",
    "Protokoll des letzten Jobs (Worker), wenn ein Job abbricht oder hängt:": "Log of the last job (worker) when a job aborts or hangs:", "Ausgabe der einzelnen Schritte, eine Datei je Schritt:": "Output of the individual steps, one file per step:",
    "Logs abgeschlossener Jobs liegen bei GitHub: Repository › Actions › Lauf öffnen › Job › „Download log archive“.": "Logs of finished jobs are on GitHub: Repository › Actions › open run › Job › “Download log archive”.",
    "Alles gebündelt zum Weitergeben, z. B. für eine Fehlersuche:": "Everything bundled for sharing, e.g. for troubleshooting:", "Monitor aktualisieren": "Update the monitor",
    "Wenn eine neue Version gemeldet wird oder ein Update fehlgeschlagen ist.": "When a new version is reported or an update failed.",
    "Am einfachsten oben in „Updates“ auf „Jetzt aktualisieren“ klicken. Ein Hilfsdienst auf der VM lädt das offizielle Release, prüft die Prüfsumme, installiert es und startet den Monitor neu. Antwortet die neue Version nicht, stellt er die alte wieder her.": "Easiest: click “Update now” under “Updates” above. A helper service on the VM downloads the official release, verifies the checksum, installs it and restarts the monitor. If the new version does not respond, it restores the old one.",
    "Oder per SSH auf der VM:": "Or via SSH on the VM:", "Protokoll des letzten Updates:": "Log of the last update:", "Zur vorherigen Version zurück:": "Back to the previous version:",
    // Über, Fehler
    "Über diesen Monitor": "About this monitor",
    "Live-Dashboard für selbst gehostete CI-Runner auf einer VM – GitHub Actions, Forgejo, Gitea, GitLab, andere mit Grundüberwachung: Runner-Status, Auslastung mit Netzwerk, Prozesse, Platten, Jobs je Repository und Live-Log. Fehler und Hinweise erscheinen als Meldung in der Mitte der Kopfzeile, „Was tun?“ führt zur passenden Anleitung.": "Live dashboard for self-hosted CI runners on a VM – GitHub Actions, Forgejo, Gitea, GitLab, others with basic monitoring: runner status, load with network, processes, disks, jobs per repository and live log. Errors and hints appear as a message in the middle of the header; “What to do?” leads to the matching guide.",
    "Ersteller: Bamberger IT Services ·": "Made by: Bamberger IT Services ·", "Quellcode und Doku:": "Source code and docs:", "Version": "Version", "Adresse": "Address",
    "runner-monitor (systemd, eigener Benutzer)": "runner-monitor (systemd, own user)", "Aktualisierung": "Refresh", "Systemwerte jede Sekunde, Dienste (GitHub, Forgejo) alle 30 s": "System values every second, services (GitHub, Forgejo) every 30 s",
    "Fehler gefunden oder Idee?": "Found a bug or have an idea?",
    "Der Monitor ist ein offenes Projekt. Fehler und Wünsche landen als Issue im GitHub-Repository. Der Knopf öffnet GitHub mit einer vorbereiteten Vorlage, in der die technischen Angaben schon stehen:": "The monitor is an open project. Bugs and wishes go into the GitHub repository as issues. The button opens GitHub with a prepared template that already contains the technical details:",
    "Idee vorschlagen ↗": "Suggest an idea ↗", "wird automatisch ergänzt": "added automatically",
    "Vor dem Absenden prüfen: Keine IP-Adressen, Rechnernamen, Tokens oder Passwörter in das Issue schreiben, das Repository ist öffentlich. Log-Ausschnitte nur gekürzt einfügen.": "Check before sending: no IP addresses, host names, tokens or passwords in the issue – the repository is public. Only paste shortened log excerpts.",
    "Fehler und Wünsche gehen per E-Mail an": "Bugs and wishes go by email to", ". Der Knopf öffnet das E-Mail-Programm mit Betreff und einer Vorlage, in der die technischen Angaben schon stehen:": ". The button opens your email app with a subject and a template that already contains the technical details:",
    "Fehler melden": "Report a bug", "Idee vorschlagen": "Suggest an idea", "Vor dem Absenden prüfen: Keine Tokens oder Passwörter mitschicken. Log-Ausschnitte nur gekürzt einfügen.": "Check before sending: no tokens or passwords. Only paste shortened log excerpts.",
    "neu gefunden": "newly found", "Offline beim Server": "Offline at the server", "Offline bei GitLab": "Offline at GitLab", "Online bei Gitea": "Online at Gitea", "Online bei GitLab": "Online at GitLab", "Bei GitLab": "At GitLab",
    "Der Dienst läuft, aber gitlab.example.org sieht den Runner nicht. Jobs werden ihm gerade nicht zugestellt.": "The service is running, but gitlab.example.org does not see the runner. Jobs are not being delivered to it.",
    "meldet sich nicht beim Server": "not reporting to the server", "Weitere Runner": "More runners", "Zugangsdaten für GitLab": "credentials for GitLab",
    // Meldungen
    "Jobs bleiben in der Warteschlange": "Jobs stay queued", "Jobs werden nicht zugestellt": "Jobs are not delivered", "Kein GitHub-Token": "No GitHub token",
    "Workflows und GitHub-Status sind aus": "Jobs and GitHub status are off", "unter 25 GB räumt der Runner vor jedem Job auf": "below 25 GB the runner cleans up before each job",
    "GitHub-Token läuft in 14 Tagen ab": "GitHub token expires in 14 days", "Version 0.8.1 verfügbar": "Version 0.8.1 available", "installiert ist 0.8.0": "installed: 0.8.0",
    "Update auf 0.8.1 läuft": "Update to 0.8.1 running", "Version 0.8.0 wurde wiederhergestellt und läuft": "Version 0.8.0 was restored and is running",
    // Einrichtung im Browser
    "Einrichtung": "Setup", "Schritte der Einrichtung": "Setup steps", "Code": "Code", "Zugang": "Access", "Anbinden": "Connect", "Fertig": "Done",
    "Schritt 1 von 5": "Step 1 of 5", "Schritt 2 von 5": "Step 2 of 5", "Schritt 4 von 5": "Step 4 of 5",
    "Einrichtung abschließen": "Finish setup", "Das Skript auf der VM ist durchgelaufen. Geben Sie den Einrichtungscode ein, den es am Ende angezeigt hat. So kann niemand sonst im Netz diesen Monitor übernehmen.": "The script on the VM has finished. Enter the setup code it showed at the end. This way nobody else on the network can take over this monitor.",
    "Vom Skript erledigt": "Done by the script", "Monitor-Dienst läuft als eigener Benutzer, nicht als root": "Monitor service runs as its own user, not as root",
    "Firewall aktiv: Port 8090 nur aus dem lokalen Netz 192.0.2.0/24, SSH bleibt erlaubt": "Firewall active: port 8090 only from the local network 192.0.2.0/24, SSH stays allowed",
    "Einrichtungscode": "Setup code", "Code verloren oder abgelaufen? Neuen Code auf der VM anzeigen:": "Code lost or expired? Show a new code on the VM:", "Der Code gilt 60 Minuten.": "The code is valid for 60 minutes.",
    "Zugang schützen": "Protect access", "Der Monitor ist nur mit Benutzername und Passwort erreichbar. Damit melden Sie sich gleich nach der Einrichtung an. Auf Wunsch bleibt der Browser 30 Tage angemeldet.": "The monitor is only reachable with a user name and password. You sign in with them right after setup. Optionally the browser stays signed in for 30 days.",
    "Benutzername": "User name", "Passwort": "Password", "Passwort wiederholen": "Repeat password", "Mindestens 12 Zeichen.": "At least 12 characters.",
    "Schwach": "Weak", "In Ordnung": "OK", "Gut": "Good", "Stark": "Strong", "✓ Stimmt überein": "✓ Matches", "Stimmt noch nicht überein": "Does not match yet",
    "Auf der VM wird nur ein Hash gespeichert, nur für root lesbar. Ändern später mit": "Only a hash is stored on the VM, readable by root only. Change it later with",
    "optional": "optional", "Runner anbinden": "Connect runners",
    "Je Runner ein nur lesendes Token für den jeweiligen Dienst. Damit zeigt der Monitor Jobs, Schritte und den Online-Status. Jeder Runner lässt sich einzeln überspringen.": "One read-only token per runner for its service. With it the monitor shows jobs, steps and the online status. Each runner can be skipped individually.",
    "Ohne Anbindung: nur Grundüberwachung": "Without connection: basic monitoring only", "Doch anbinden": "Connect after all", "Überspringen – nur Grundüberwachung": "Skip – basic monitoring only",
    "Verbindung prüfen": "Test connection", "Erneut prüfen": "Test again", "Prüfe …": "Testing …", "Fine-grained Token": "Fine-grained token", "Organisation oder Benutzer": "Organization or user",
    "Zugriffstoken": "Access token", "Aus der Runner-Konfiguration erkannt.": "Detected from the runner configuration.", "Aus der Erkennung übernommen.": "Taken from detection.",
    "So erstellen Sie das Token": "How to create the token", "Token-Seite auf GitHub öffnen ↗": "Open token page on GitHub ↗", "Token-Seite auf git.example.org öffnen ↗": "Open token page on git.example.org ↗",
    "Auf GitHub ein „Fine-grained token“ anlegen (Link unten).": "Create a “Fine-grained token” on GitHub (link below).", "Resource owner: die Organisation. Repository access: All repositories.": "Resource owner: the organization. Repository access: All repositories.",
    "Repository-Rechte: Actions und Metadata jeweils „Read-only“.": "Repository permissions: Actions and Metadata each “Read-only”.", "Optional Organisations-Recht Self-hosted runners „Read-only“ für den Online-Status.": "Optional organization permission Self-hosted runners “Read-only” for the online status.",
    "Ablauf z. B. 90 Tage. Der Monitor warnt 14 Tage vorher. Token links einfügen.": "Expiry e.g. 90 days. The monitor warns 14 days ahead. Paste the token on the left.",
    "Auf git.example.org anmelden: Einstellungen › Anwendungen › „Neues Token generieren“.": "Sign in to git.example.org: Settings › Applications › “Generate new token”.", "Name z. B. runner-monitor, Ablaufdatum setzen.": "Name e.g. runner-monitor, set an expiry date.",
    "Rechte: repository und organization jeweils „Lesen“ (genaue Liste folgt aus der API-Prüfung).": "Permissions: repository and organization each “Read” (exact list follows from the API check).",
    "Optional: Zugriff auf Actions-Runner der Organisation „Lesen“ für den Online-Status.": "Optional: read access to the organization’s Actions runners for the online status.", "Token kopieren und links einfügen.": "Copy the token and paste it on the left.",
    "Token gültig, läuft ab am 21.01.2027": "Token valid, expires on 2027-01-21", "Organisation beispiel-org gefunden, 15 Repositories": "Organization beispiel-org found, 15 repositories", "Actions und Metadata: lesen": "Actions and Metadata: read",
    "Self-hosted runners fehlt: Online-Status bleibt „unbekannt“ (optional)": "Self-hosted runners missing: online status stays “unknown” (optional)", "Server erreichbar · Forgejo 13.0": "Server reachable · Forgejo 13.0",
    "Token gültig, Benutzer monitor-lesen": "Token valid, user monitor-lesen", "Organisation beispiel-org gefunden, 6 Repositories": "Organization beispiel-org found, 6 repositories",
    "Runner-Status nur mit Organisations-Recht: Online-Status bleibt „unbekannt“": "Runner status needs an organization permission: online status stays “unknown”",
    "Ohne Anbindung fortfahren": "Continue without connection", "Später auf der VM nachholen oder ändern:": "Do it later or change it on the VM:",
    "Alles eingerichtet": "All set up", "Der Monitor läuft. Legen Sie die Adresse als Lesezeichen an. Auf einem zweiten Bildschirm kann die Seite dauerhaft offen bleiben.": "The monitor is running. Bookmark the address. The page can stay open permanently on a second screen.",
    "Zugang geschützt": "Access protected", "Firewall aktiv": "Firewall active", "Port 8090 nur aus 192.0.2.0/24": "Port 8090 only from 192.0.2.0/24", "Runner auf runner-vm": "Runners on runner-vm",
    "Dienst, Auslastung, Log": "Service, load, log", "beispiel-org · Token bis 21.01.2027": "beispiel-org · token until 2027-01-21",
    "Diese Einrichtung lässt sich nicht erneut im Browser aufrufen. Runner und Zugangsdaten ändern Sie später unter „Info & Hilfe › Runner“ oder auf der VM mit": "This setup cannot be opened in the browser again. Change runners and credentials later under “Info & Help › Runners” or on the VM with",
    "Zum Monitor anmelden": "Sign in to the monitor",
    // Anmeldung
    "Anmelden": "Sign in", "Benutzername oder Passwort stimmt nicht.": "User name or password is incorrect.", "Angemeldet bleiben (30 Tage)": "Stay signed in (30 days)",
    "Passwort vergessen? Auf der VM neu setzen:": "Forgot your password? Reset it on the VM:", "Die Anmeldung ist für 5 Minuten gesperrt.": "Sign-in is locked for 5 minutes."
  };
  // Teile in zusammengesetzten Texten (längste zuerst angewendet)
  const TEILE = [
    [" Kerne · 32 GB RAM · läuft seit ", " cores · 32 GB RAM · up "], ["Dienst gestoppt seit ", "Service stopped since "], ["wartet auf Jobs · letzter ", "waiting for jobs · last "],
    ["Grundüberwachung · keine Jobs", "Basic monitoring · no jobs"], ["Letzte erfolgreiche Abfrage ", "Last successful poll "], ["fehlgeschlagen · letzte erfolgreiche ", "failed · last successful "],
    ["Keine Änderung · geprüft um ", "No change · checked at "], [" Runner erkannt · zuletzt heute ", " runners detected · last today "], [", automatisch alle 6 Std.", ", automatically every 6 h"],
    ["Jobs bleiben in der Warteschlange (", "Jobs stay queued ("], ["Workflows zeigen den Stand von ", "Jobs show data from "], [" – danach bleiben die Workflows leer", " – after that jobs stay empty"],
    [" – Jobs werden nicht zugestellt", " – jobs are not delivered"], [") · neuer Versuch läuft", ") · retrying"], [") · Runner arbeitet weiter", ") · runner keeps working"],
    [" bei GitHub · alle 6 Std.", " at GitHub · every 6 h"], [" – auf dem neuesten Stand", " – up to date"], [" · erschienen am ", " · released on "],
    [", Aufräumschwelle 25 GB frei", ", cleanup threshold 25 GB free"], ["4.812 von 5.000 frei, Reset ", "4,812 of 5,000 left, reset "], [" (alle 30 s)", " (every 30 s)"],
    ["Dienst gestoppt", "service stopped"], ["offline bei GitHub", "offline at GitHub"], ["CPU-Verlauf ", "CPU history "], ["RAM-Verlauf ", "RAM history "], ["Netzwerk-Verlauf ", "Network history "],
    ["der letzten 30 Sekunden", "for the last 30 seconds"], ["der letzten 2 Minuten", "for the last 2 minutes"], ["der letzten 5 Minuten", "for the last 5 minutes"], ["der letzten 10 Minuten", "for the last 10 minutes"],
    [", empfangen und gesendet", ", received and sent"], [" weitere ruhig", " more idle"], [" · nächste in ", " · next in "], [" · neuer Versuch in ", " · retrying in "],
    [" · alles läuft", " · all running"], [" · erfolgreich", " · successful"], [" in der Warteschlange", " in queue"], [" GB belegt, ", " GB used, "], [" GB frei", " GB free"],
    [" Laufwerke", " drives"], [" neue Zeilen", " new lines"], [" weitere", " more"], [" warten)", " queued)"], [" Repositories", " repositories"], [" Container", " containers"],
    ["gestoppt seit ", "stopped since "], ["offline seit ", "offline since "], ["aktiv seit ", "active for "], ["Abgefragt ", "Polled "], ["Platte knapp: ", "Disk low: "],
    ["Darstellung ", "Display "], [", umschalten auf ", ", switch to "], ["Angehalten · ", "Paused · "], ["Mitlaufen angehalten · ", "Auto-scroll paused · "],
    ["Journal · ", "Journal · "], ["Zugeordnet: ", "Assigned: "], ["Schritt ", "Step "], ["(unbekannt)", "(unknown)"], ["Noch ", ""]
  ];
  const MUSTER = [
    [/^Alle (\d+) Repositories ruhig$/, "All $1 repositories idle"], [/^(\d+) läuft$/, "$1 running"], [/^(\d+) laufen$/, "$1 running"], [/^1 wartet$/, "1 queued"],
    [/^Stand /, "As of "], [/^aktualisiert /, "updated "], [/^heute /, "today "], [/^am /, "on "], [/^um /, "at "], [/^in (\d+) s/, "in $1 s"],
    [/vor (\d+) s\b/g, "$1 s ago"], [/vor (\d+) Min\./g, "$1 min ago"], [/vor (\d+) Std\./g, "$1 h ago"], [/vor (\d+) T\b/g, "$1 d ago"],
    [/\bseit (\d\d:\d\d)/g, "since $1"], [/\(in (\d+) Tagen\)/g, "(in $1 days)"], [/(\d+) T (\d+) Std\./g, "$1 d $2 h"], [/(\d+) Std\. (\d+) Min\./g, "$1 h $2 min"],
    [/(\d+) Min\./g, "$1 min"], [/(\d+) Std\./g, "$1 h"], [/(\d+) Zeichen bis zur Mindestlänge\./, "$1 more characters to the minimum length."], [/ · (\d+) Zeichen$/, " · $1 characters"],
    [/^(\d+) Versuche?, danach ist die Anmeldung 5 Minuten gesperrt\.$/, "$1 attempt(s) left, then sign-in is locked for 5 minutes."],
    [/(\d+) Runner gefunden – Auswahl im Schritt „Runner“/, "$1 runners found – choose them in the “Runners” step"], [/Kein Runner gefunden – Wege im Schritt „Runner“/, "No runner found – options in the “Runners” step"],
    [/^(\w[\w-]*) anbinden$/, "Connect $1"], [/^Mit einem nur lesenden Token zeigt der Monitor, welche Jobs je Repository laufen und warten, und ob (\w+) den Runner sieht\. Ohne Token funktioniert alles andere trotzdem\.$/, "With a read-only token the monitor shows which jobs are running and queued per repository, and whether $1 sees the runner. Everything else works without a token."],
    [/^(So|Mo|Di|Mi|Do|Fr|Sa)(,?) (\d\d)\.(\d\d)\.$/, (x, w, k, d, mo) => ({ So: "Sun", Mo: "Mon", Di: "Tue", Mi: "Wed", Do: "Thu", Fr: "Fri", Sa: "Sat" }[w]) + k + " " + d + " " + ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][parseInt(mo, 10) - 1]],
    [/(\d),(\d)/g, "$1.$2"]
  ];
  const TS = TEILE.slice().sort((a, b) => b[0].length - a[0].length);
  const cache = new Map();
  function en(t) {
    if (cache.has(t)) return cache.get(t);
    const m = t.match(/^(\s*)([\s\S]*?)(\s*)$/), kern = m[2];
    let r;
    if (!kern || !/[A-Za-zÄÖÜäöüß]/.test(kern)) r = t;
    else if (EXAKT[kern] != null) r = m[1] + EXAKT[kern] + m[3];
    else {
      let x = kern;
      for (const [a, b] of TS) if (x.indexOf(a) >= 0) x = x.split(a).join(b);
      for (const [re, b] of MUSTER) x = x.replace(re, b);
      if (EXAKT[x] != null) x = EXAKT[x];
      r = m[1] + x + m[3];
    }
    if (cache.size > 5000) cache.clear();
    cache.set(t, r); return r;
  }
  const ATTR = ['aria-label', 'title', 'placeholder'];
  const SKIP = 'pre, code, .term, .codeblock, .leer-pfad, .code-box, [data-noi18n], script, style';
  function wahl() { try { const v = localStorage.getItem('runner-monitor.sprache'); if (v === 'de' || v === 'en') return v; } catch (e) {} return 'auto'; }
  function system() { const n = (navigator.languages && navigator.languages[0]) || navigator.language || 'en'; return /^de\b/i.test(n) ? 'de' : 'en'; }
  function sprache(ov) { if (ov === 'de' || ov === 'en') return ov; const w = wahl(); return w === 'auto' ? system() : w; }
  function textKnoten(n, ziel) {
    if (n.__en !== undefined && n.nodeValue === n.__en && ziel === 'en') return;
    if (n.__en !== undefined && n.nodeValue === n.__en && ziel === 'de') { n.nodeValue = n.__de; n.__en = undefined; return; }
    if (ziel === 'de') return;
    const de = n.nodeValue, e = en(de);
    n.__de = de; n.__en = e; if (e !== de) n.nodeValue = e;
  }
  function attrs(el, ziel) {
    el.__i18n = el.__i18n || {};
    for (const a of ATTR) {
      const v = el.getAttribute(a); if (v == null) continue;
      const st = el.__i18n[a];
      if (st && v === st.en) { if (ziel === 'de') { el.setAttribute(a, st.de); delete el.__i18n[a]; } continue; }
      if (ziel === 'de') continue;
      const e = en(v); el.__i18n[a] = { de: v, en: e }; if (e !== v) el.setAttribute(a, e);
    }
  }
  function lauf(root, ziel, start) {
    const w = document.createTreeWalker(start || root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    let n = start || root;
    while (n) {
      if (n.nodeType === 1) {
        if (n.matches && n.matches(SKIP)) { n = naechster(w, n); continue; }
        attrs(n, ziel);
      } else if (n.nodeType === 3) {
        const p = n.parentElement; if (!p || !p.closest(SKIP)) textKnoten(n, ziel);
      }
      n = w.nextNode();
    }
  }
  function naechster(w, n) { let x = w.nextSibling(); while (!x && w.parentNode()) x = w.nextSibling(); return x; }
  const gebunden = new Set();
  function binde(root, getOv) {
    if (!root || root.__rmI18n) return;
    const b = { root: root, ov: getOv, obs: null };
    root.__rmI18n = b; gebunden.add(b);
    const anwenden = () => { const z = sprache(b.ov && b.ov()); b.obs.disconnect(); lauf(root, z); root.setAttribute('lang', z); b.obs.observe(root, OPT); };
    const OPT = { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTR };
    b.obs = new MutationObserver(anwenden); b.anwenden = anwenden;
    b.obs.observe(root, OPT); anwenden();
  }
  function loese(root) { const b = root && root.__rmI18n; if (!b) return; b.obs.disconnect(); gebunden.delete(b); root.__rmI18n = null; }
  function setze(v) { try { localStorage.setItem('runner-monitor.sprache', v); } catch (e) {} alle(); window.dispatchEvent(new Event('rm-sprache')); }
  function alle() { gebunden.forEach((b) => { if (!document.contains(b.root)) { b.obs.disconnect(); gebunden.delete(b); } else b.anwenden(); }); }
  window.RM_I18N = { EXAKT: EXAKT, TEILE: TEILE, MUSTER: MUSTER, en: en, sprache: sprache, wahl: wahl, system: system, setze: setze, binde: binde, loese: loese, alle: alle };
})();
