# Wie der Runner-Monitor funktioniert

**Stand: 29.10.2026 · Version 0.7.0 (Runner-Erkennung und Anbieter-Adapter aus 0.8.0 in Arbeit)**

Diese Seite erklärt den Aufbau: welche Teile es gibt, woher jede Zahl im Dashboard kommt,
welche Dateien wo liegen und wer was lesen und schreiben darf. Bedienung: [Handbuch](handbuch/README.md).

## Überblick

```mermaid
flowchart LR
  subgraph VM["Runner-VM (Ubuntu)"]
    direction LR
    R["GitHub-Runner<br/>actions.runner.*.service<br/>/opt/actions-runner"]
    J[("systemd-Journal")]
    P[("/proc")]
    S["runner-monitor-sammler<br/>(root)"]
    M["runner-monitor<br/>(Benutzer runner-monitor)<br/>HTTP + SSE :8090"]
    U["runner-monitor-update<br/>(root, bei Bedarf)"]
    RUN[("/run/runner-monitor<br/>github.json · docker.json · release.json")]
    VAR[("/var/lib/runner-monitor<br/>zugang · sitzungen · einstellungen<br/>auftraege/ · update-status.json")]
    TOK[("/etc/runner-monitor/zugang/&lt;runner&gt;.token<br/>(Rückfall github-token) · nur root")]
    R -- "Job-Start/-Ende" --> J
    R -- "_diag/pages/*.log<br/>Ausgabe je Schritt" --> M
    J --> M
    P --> M
    S -- "liest" --> TOK
    S -- "schreibt 0644" --> RUN
    RUN -- "liest" --> M
    M -- "Aufträge" --> VAR
    VAR -- "Token-/Update-Auftrag" --> S
    VAR -- "update (systemd .path)" --> U
  end
  GH["GitHub-API<br/>api.github.com"]
  B["Browser"]
  S -- "alle 30 s / 6 h" --> GH
  U -- "Release-Archiv + SHA-256" --> GH
  M -- "Server-Sent Events" --> B
  B -- "Anmelden, Update starten" --> M
```

Drei systemd-Dienste, alle in Python 3 nur mit der Standardbibliothek ([ADR-0001](adr/0001-python-standardbibliothek.md)):

| Dienst | Läuft als | Aufgabe |
|---|---|---|
| `runner-monitor` | `runner-monitor` (ohne Anmeldung, Gruppe `systemd-journal`) | Webserver auf Port 8090: Seiten, Anmeldung, Server-Sent Events. Misst die VM, liest Journal und Schritt-Logs des Runners. |
| `runner-monitor-sammler` | root | Fragt GitHub (mit dem Token, das nur root lesen kann) und Docker ab, prüft auf neue Releases, erkennt die Runner auf der VM (beim Start und alle 6 h), übernimmt Aufträge der Oberfläche. |
| `runner-monitor-update` | root, nur bei Bedarf | Installiert ein Update ([ADR-0004](adr/0004-update-hilfsdienst.md)). Startet über `runner-monitor-update.path`, sobald ein Auftrag liegt. |

**Warum zwei Benutzer?** Der Webserver ist das, was aus dem Netz erreichbar ist. Er läuft
ohne Rechte und kann weder das GitHub-Token lesen noch Software installieren. Was root-Rechte
braucht, erledigen die beiden root-Dienste – sie nehmen von der Oberfläche nur eng umrissene
Aufträge an (ein Token zum Ablegen, eine Versionsnummer zum Aktualisieren, `release-pruefen` für
„Jetzt prüfen“ – der Sammler fragt dann sofort, höchstens einmal je Minute) und prüfen sie selbst.

## Woher die Daten kommen

| Bereich im Dashboard | Quelle | Takt |
|---|---|---|
| CPU gesamt, je Kern | `/proc/stat` (Differenz zweier Messungen, iowait zählt als frei) | 1 s |
| RAM, Swap | `/proc/meminfo` (belegt = gesamt − verfügbar) | 1 s |
| Last | `/proc/loadavg` | 1 s |
| Netz | `/proc/net/dev`, Bytes je Sekunde summiert über alle echten Schnittstellen (ohne `lo`, Docker-Brücken, `veth`, VPN-Tunnel – deren Verkehr läuft ohnehin über die echte Schnittstelle) | 1 s |
| Laufzeit der VM | `/proc/uptime` | 1 s |
| Verlauf 10 Minuten | die letzten 600 Sekundenwerte im Speicher des Dienstes | 1 s |
| Prozesse (Top 6) | `/proc/<pid>/stat`, `status`, `cmdline` | 2 s |
| Platten | `/proc/mounts` + `statvfs`; nur echte Dateisysteme ab 1 GiB, ohne Snap/Docker-Overlays. Netzlaufwerke (NFS, CIFS) mit 2 s Frist in eigenem Thread; antwortet eines nicht, fehlt es, bis es wieder antwortet (Journal: „Netzlaufwerk … antwortet nicht“) | 10 s |
| Runner-Dienst aktiv/gestoppt | `systemctl show actions.runner.*` | 2 s |
| Runner-Name, Version | `/opt/actions-runner/.runner`, `bin/Runner.Listener.deps.json` (Eintrag `Runner.Listener/x.y.z`; Rückfall `bin/Runner.Listener --version`) | gefunden: 10 min, nicht gefunden: nach 30 s erneut |
| Job gestartet/beendet, Ergebnis | Journal des Runner-Dienstes: „Running job: …“, „Job … completed with result: …“ | sofort |
| Live-Log | `/opt/actions-runner/_diag/pages/*.log` – der Runner schreibt je Schritt eine neue Datei; der Monitor liest sie wie `tail -f` | sofort |
| Repository, Workflow, Schritte des Jobs | GitHub-API: Läufe der Repositories, Jobs mit `runner_name` dieses Runners | 30 s |
| Online bei GitHub | GitHub-API `orgs/{org}/actions/runners` (Recht „Self-hosted runners: Read“, optional) | 30 s |
| Workflows je Repository | GitHub-API `orgs/{org}/repos`, dann je Repository `actions/runs?per_page=30`; bedingt mit ETag (304 kostet kein Kontingent), ruhige Repositories (über 1 Std. kein Push, nichts läuft oder wartet) nur alle 5 Min. | 30 s |
| Token-Ablauf, API-Kontingent | Antwort-Header `github-authentication-token-expiration`, `x-ratelimit-*` | 30 s |
| Neue Version | GitHub-API `repos/<release-repo>/releases/latest` | 6 h |
| Docker-Container | `docker ps --format json` (wird gesammelt, in Version 0.1 nicht angezeigt) | 10 s |

**Ohne Token** laufen Runner-Status, Auslastung, Prozesse, Platten und Live-Log normal; Job-
Name und Ergebnis kommen dann allein aus dem Journal, Repository und Schrittnamen fehlen.

**Fällt GitHub aus**, behält der Sammler den letzten erfolgreichen Stand und markiert ihn; die
Oberfläche zeigt „Stand von hh:mm:ss“ und die Zeit bis zum nächsten Versuch.

## Runner erkennen (seit Design 0.8.0, #91)

`runner_monitor/erkennung.py` findet selbst, welche Runner auf der VM laufen – auch mehrere und
auch andere als GitHub. Der Sammler (root) startet sie **beim Start und alle 6 Stunden** als
**eigenen Prozess** (`python3 -m runner_monitor.erkennung --json`), schaut in seinen folgenden
Takten (2 s) nach und beendet ihn nach 60 s – ein hängender DNS-Server oder ein tröpfelnder Server
hält so weder GitHub- noch Docker-Abfrage auf. Die Ausgabe landet in einer temporären Datei, wird
geprüft (`erkennung.pruefe_ergebnis`: Form, Werte, höchstens 2 MB, nur bekannte Felder) und erst
dann nach `/run/runner-monitor/erkennung.json` geschrieben (0644, ohne Geheimnisse); Takt und Frist
laufen mit `time.monotonic()`, die Fehlerausgabe (höchstens 2000 Zeichen) geht ins Journal; ein
abgebrochener oder ungültiger Lauf lässt die alte Datei stehen. `einrichten.sh` zeigt dieselbe
Erkennung in „System prüfen“ › „Runner auf dieser VM“ (`timeout --foreground 60 python3 -m
runner_monitor.erkennung --text`, Rückgabe 3 = kein Runner). Seit den Anbieter-Adaptern (#92) stehen
alle nicht ignorierten Funde in `runner[]` (siehe „Anbieter-Adapter“); die Oberfläche zeigt bis #94
weiter nur den GitHub-Runner wie bisher.

| Quelle | Was gelesen wird | Merkmal (Beispiel) |
|---|---|---|
| systemd-Units | Unit-Dateien in `/etc/systemd/system`, `/run/systemd/system`, `/usr/local/lib/systemd/system`, `/usr/lib/systemd/system`, `/lib/systemd/system` samt Drop-ins; `ExecStart`, `WorkingDirectory`; aktiviert über `*.wants/`, aktiv über `systemctl is-active` | „systemd-Unit forgejo-runner.service“ |
| Prozesse | `/proc/<pid>/cmdline`, `cgroup` (welche Unit, Container?), `cwd` – nur bekannte Programme (`Runner.Listener`, `forgejo-runner`, `act_runner`, `gitlab-runner`) | „Prozess forgejo-runner daemon“ |
| Registrierungen | `.runner` (GitHub: `agentName`, `gitHubUrl`; Forgejo/Gitea: `name`, `address`) neben Unit und Prozess, laut `config.yml` (`runner.file`) und an üblichen Orten (`/opt/*`, `/srv/*`, `/var/lib/*`, `/home/*`, `/root`); GitLab: `config.toml` (`name`, `url`) | „/opt/actions-runner/.runner mit gitHubUrl“ |
| Server-API ohne Zugangsdaten | nur für Funde mit systemd-Unit (E-17): Forgejo `/api/forgejo/v1/version`, Gitea `/api/v1/version`, GitLab-Anmeldeseite, GitHub Enterprise `/api/v3/meta` (github.com gilt als bekannt) | „/api/forgejo/v1/version antwortet: 13.0“ |
| Runner-Version | GitHub aus `bin/Runner.Listener.deps.json`, sonst aus dem Journal der Unit („with version: v9.1.0“, „version=17.5.2“) | – |

**Grad:** `sicher` – eindeutige Merkmale (Registrierung und systemd-Unit) **und** Server
bestätigt; `wahrscheinlich` – Dienst erkannt, aber Server nicht erreichbar, ohne Netz, nicht geprüft
(Fund ohne Unit, E-17), ohne Registrierung oder mit widersprüchlichen Merkmalen; `unklar` – nur allgemeine Hinweise (Name der
Unit enthält „runner“, „agent“, „build“ …, startet Container). Bekannte Nicht-Runner
(`qemu-guest-agent`, `runner-monitor*` …) zählen nicht; unbekannte Units nur, wenn sie aktiviert
oder aktiv sind. Zwischen Forgejo und Gitea entscheidet die Antwort des Servers.

**Einstufung und Fähigkeiten** richten sich nach dem, was diese Version liefern kann (Tabelle
`FAEHIG` in `erkennung.py`): GitHub `voll` (Status, Jobs, Schritte, Logs); Forgejo, Gitea, GitLab
`teil` (erkannt, noch ohne Adapter: Dienst und Journal); unbekannt `unbekannt` (Grundüberwachung).
`updates` ist überall `false` (E-16). Ein Fund ohne Unit hat weder `status` noch `logs`.

Ergebnis je Fund (`erkennung.json` › `runner[]`, Format aus dem Design-README):

```json
{ "id": "runner-vm-02", "name": "runner-vm-02", "dienst": "forgejo", "server": "https://git.example.org",
  "version": "13.0 / Runner 9.1", "grad": "sicher", "merkmale": ["systemd-Unit forgejo-runner.service", "…"],
  "einstufung": "teil", "stand": "offen", "unit": "forgejo-runner.service", "log": null,
  "faehig": { "status": true, "jobs": false, "schritte": false, "logs": true, "updates": false },
  "aktiv": true, "grund": null }
```

`dienst`: `github|forgejo|gitea|gitlab|unbekannt`; `stand`: `angebunden|grund|ignoriert|offen`
(GitHub mit Unit und vorhandenem Token: `angebunden`, sonst `offen`, bis eine Zuordnung etwas
anderes sagt; ein Fund ohne Unit ist nie `angebunden`, E-18); `log`: Pfad oder `null` (= Journal der
Unit; GitHub mit Unit: `<runner>/_diag`, ohne Unit `null`). Zusätzlich zum Design: `aktiv` (Unit
läuft: `true`/`false`/`null` unbekannt; bei einer zugeordneten anderen Unit deren Zustand) und
`grund` (warum nur „wahrscheinlich“). Die Datei hat außerdem `zeit` und `geprueft`.

**IDs (E-18):** aus dem Namen, eindeutig (gleicher Name → `-2`, `-3`) und **zuerst an Funde mit
Unit** vergeben – ein nachgemachter Fund (z. B. eine `.runner` in `/home`) bekommt so nie die ID
eines echten Runners und damit nie dessen Zuordnung. Für die Adapter (#92, #93, #99) gilt: Server
und Log-Pfad kommen nur aus `runner.json` bzw. den Zugangsdaten (`zugang/`), nie aus dem Fund – der
Fund ist nur ein Vorschlag für die Einrichtung.

**Spalte „Version“** in `einrichten.sh` wie im Design: bei GitHub die Runner-Version, sonst die
Server-Version; ist nur die Runner-Version bekannt, steht dort „–“ (sie bleibt im JSON).

**Zuordnung und Ignorieren** stehen dauerhaft in `/etc/runner-monitor/runner.json`
(root:runner-monitor, 0640). Gelesen wird sie schon (`erkennung.lies_zuordnung`), schreiben wird
sie der Sammler auf Auftrag der Oberfläche (POST-Endpunkt mit #96/#97):

```json
{ "version": 1,
  "runner": {
    "buildagent":   { "stand": "grund", "dienst": "unbekannt", "name": "Build-Agent",
                      "unit": "buildagent.service", "log": "/var/log/buildagent/agent.log" },
    "runner-vm-03": { "stand": "ignoriert" } } }
```

Schlüssel ist die `id` des Funds; jedes Feld ist freiwillig. Ungültige Einträge oder Felder werden
verworfen. Ein Eintrag mit `unit`, der nicht gefunden wurde, erscheint als „von Hand zugeordnet“.

**Sicherheit (S-ERK-01):** Bei Funden mit Unit-Datei kommen Name, Server und Dienst nur aus Registrierungen, die die Unit vorgibt
(`--config` im ExecStart, Programmordner, WorkingDirectory); was nur ein Prozess in der cgroup nennt
(argv[0], `--config`, cwd – frei wählbar) ist nur Merkmal und Widerspruch und senkt den Grad (#109). Die Erkennung führt nichts aus, was in einem Fund steht (kein
`ExecStart`, kein Runner-Programm, keine Shell); aufgerufen werden nur `systemctl is-active -- <unit>`
und `journalctl -u <unit>` mit geprüftem Namen. **Keinem Symlink wird gefolgt** außer bei
Unit-Dateien in den root-eigenen systemd-Verzeichnissen – also nicht bei `.runner`, `config.toml`,
`config.yml`, `deps.json`, `runner.json` und `/proc`. Vor dem Öffnen prüft `lstat`, dass es eine
reguläre Datei ist (keine FIFO, kein Gerät); geöffnet wird mit `O_NOFOLLOW`, `O_NONBLOCK` und
`O_NOCTTY`, danach muss es dieselbe Datei sein; gelesen wird bis zu einer Grenze (64 KB, `deps.json`
4 MB). Registrierungen nur unter festen Dateinamen (`.runner`, `config.toml`). `token` aus
`.runner`/`config.toml` wird nie übernommen, `.credentials` nie gelesen, vom GitHub-Token wird nur
geprüft, ob die Datei da ist. Namen, Unit-Namen, Pfade und Adressen werden streng geprüft (Adressen
ohne Zugangsdaten, Abfrage und Anker); die Textausgabe ersetzt Steuerzeichen. Die Server-Probe
(nur Funde mit Unit) ist ein GET auf feste Pfade ohne Zugangsdaten und ohne Weiterleitungen, mit
**harten** Fristen von 3 s je Anfrage und 10 s insgesamt, höchstens 8 Server: Sie läuft in einem
eigenen Faden, der zur Frist zurückgelassen wird – das deckt auch DNS und tröpfelnde Antworten ab.
Darüber liegt die Grenze des Prozesses (Sammler 60 s, `einrichten.sh` `timeout --foreground 60`). Fehler in einer
Quelle beenden die Erkennung nie.

`PrivateDevices=yes` für den Sammler wäre nach Prüfung möglich (Docker über `/run/docker.sock`,
`systemctl` über D-Bus, `journalctl` über `/var/log/journal` brauchen keine Geräte) – ist aber nicht
gesetzt, weil es auf einer echten VM noch nicht erprobt ist; Vorschlag für ein eigenes Issue.

## Anbieter-Adapter (seit Design 0.8.0, #92)

Status, Jobs, Schritte und Logs kommen über eine gemeinsame Schnittstelle, egal welcher Dienst
dahintersteht ([ADR-0006](adr/0006-anbieter-adapter-und-zustand.md), E-19). Paket
`runner_monitor/anbieter/`:

| Datei | Inhalt |
|---|---|
| `__init__.py` | Basisklasse `Anbieter` (zugleich Grundüberwachung), `RunnerKonfig`, Registry (`registriere`, `klasse_fuer`, `faehigkeiten_tabelle`) |
| `github.py` | GitHub-Adapter: Abfrage einer Runde (bisher `github.abfrage`), Jobs je Repository, aktueller Job mit Schritten, Online-Status, Log-Quelle `_diag/pages` |
| `gitlab.py` | GitLab-Adapter (#99): REST-Klient (`/api/v4`, nur lesend, ohne Weiterleitungen), Runner-Status, aktueller Job, letzte Jobs, Jobs je Projekt; ohne Schritte |
| `token.py` | Zugangsdaten je Runner, Übernahme des alten Tokens, Kommandozeile für `einrichten.sh` |

Schnittstelle je Runner: `faehig()`, `abfrage(speicher, …)` (nur im Sammler, root, mit Token),
`dienst_status()`, `beim_dienst()`, `jobs_je_repository()`, `api_job()`, `log_quelle()` und
`eintrag()` (ein Eintrag in `runner[]`). Ein Dienst ohne eigenen Adapter bekommt die
**Grundüberwachung** (Dienst über systemd, Journal). `runner_monitor/github.py` bleibt der
REST-Klient (auch für Releases und die Prüfung in der Einrichtung) und reicht die alten Namen
(`github.abfrage`, `job_fuer_runner` …) an den Adapter weiter, bis das Altformat entfällt.

**Fähigkeiten je Dienst** (diese Version; Test: muss zu `erkennung.FAEHIG` passen):

| Dienst | Adapter | status | jobs | schritte | logs | updates |
|---|---|---|---|---|---|---|
| GitHub | `GitHub` | ✓ | ✓ | ✓ | ✓ | – |
| Forgejo, Gitea | Grundüberwachung (bis #93) | ✓ | – | – | ✓ | – |
| GitLab | `GitLab` (#99) | ✓ | ✓ | – | ✓ | – |
| unbekannt | Grundüberwachung | ✓ | – | – | ✓ | – |

Ohne Unit gibt es weder `status` noch `logs` (außer beim GitHub-Runner aus `MONITOR_RUNNER_VERZ`,
dessen Status wie bisher „fehlt“ zeigt und dessen Live-Log aus `_diag/pages` kommt). Weitere
GitHub-Runner neben dem aus `MONITOR_RUNNER_VERZ` laufen bis #94 in der Grundüberwachung.

**Woher ein Adapter seine Werte nimmt (E-18):** Server, Organisation, Log-Pfad und Token-Datei nur
aus der Konfiguration – GitHub: Server fest `https://github.com`, Organisation aus
`einstellungen.json` bzw. `MONITOR_ORG`, Token aus `zugang/<id>.token` (Rückfall `github-token`);
Log-Datei anderer Runner nur aus `/etc/runner-monitor/runner.json`, sonst Journal der Unit. Vom Fund
der Erkennung kommen nur ID, Anzeigename, Unit (geprüft), Version, Einstufung und Stand – zum
Anzeigen, nie als Ziel einer Anfrage. Der Monitor prüft `erkennung.json` beim Lesen noch einmal
(`erkennung.pruefe_ergebnis`), nimmt höchstens 20 Runner auf und fragt den Dienststatus von Runnern in
Grundüberwachung höchstens alle 10 s ab.

### GitLab-Adapter (#99)

Token mit dem Bereich **`read_api`** (persönliches, Projekt- oder Gruppen-Zugriffstoken), abgelegt
in `zugang/<id>.token`; der **Server** kommt nur aus der Konfiguration (nicht aus dem Fund, E-18) und
darf `http://` oder `https://` sein (mit `http://` läuft das Token unverschlüsselt durchs Netz – nur
im vertrauenswürdigen Netz, besser `https://`). Der Klient folgt **keiner Weiterleitung**, sendet das
Token nur in der Kopfzeile `PRIVATE-TOKEN` an `<Server>/api/v4/…`, liest höchstens 4 MB je Antwort
und fragt nur mit `GET`. Alle 30 s eine Runde:

| Anfrage | Zweck | wenn sie fehlschlägt |
|---|---|---|
| `GET /personal_access_tokens/self` (höchstens stündlich) | Bereiche (`read_api` oder `api` nötig) und Ablaufdatum → Meldung „Token läuft ab“ | 403/404 (ältere GitLab-Version, andere Token-Art): übersprungen |
| `GET /runners` (nur beim ersten Mal und wenn die gemerkte Nummer nicht mehr passt; 100 je Seite, höchstens 5 Seiten) | den Runner finden: `description` = `name` in `config.toml` (bzw. der Anzeigename); ist der Name nicht genau einmal vorhanden, bleibt der Status „unbekannt“ mit Grund | 401/403/404: Token ungültig bzw. keine Rechte |
| `GET /runners/:id` | Status (`online`, `offline`, `stale`, `never_contacted`; ältere Versionen nur das Feld `online`), Labels (`tag_list`), Version | 403/404: Labels und Version fehlen, der Status kommt aus der Liste |
| `GET /runners/:id/jobs?status=running` | aktueller Job (Projekt, Pipeline, Job, Stage, Ref, Start, Link) und „Jobs je Repository“ (laufend) | wie oben |
| `GET /runners/:id/jobs?order_by=id&sort=desc` | die letzten fünf beendeten Jobs (`erfolg`, `fehler`, `abgebrochen`, Dauer, Ende) | wie oben |

Ergebnis (öffentlich, ohne Token) im selben Format wie `github.json`, dazu `letzteJobs` und
`wartetUnbekannt: true`. Die Fehlerarten sind die von GitHub: `nicht-erreichbar` (Netz, Zeitlimit,
5xx, keine JSON-Antwort, Weiterleitung, zu große Antwort), `token-ungueltig` (401),
`keine-rechte` (403, 404 oder Token ohne `read_api`), `kontingent` (429; `RateLimit-*` werden gezeigt,
wenn der Server sie sendet), `kein-token`, `fehler` (Server fehlt oder ist keine Adresse).

**Was GitLab nicht hergibt (steht so in der Oberfläche als „nicht verfügbar“):**
- **Schritte:** Die REST-API kennt Pipelines → Stages → Jobs, aber keine Schrittliste innerhalb eines
  laufenden Jobs; das Job-Protokoll (`/trace`) ist Rohtext. Darum `schritte: false`, `job.schritt`
  ist `null`, der Job zeigt Pipeline, Stage und Name.
- **Wartende Jobs je Projekt:** Die Runner-API kennt nur `running`, `success`, `failed`, `canceled`.
  `wartet` ist immer 0 und `jobsJeRepository.wartetUnbekannt` ist `true` – die Oberfläche soll die Zahl
  dann nicht zeigen (Umsetzung #94). `privat` ist immer `false` (die Sichtbarkeit steht nicht in der Antwort).
- **Live-Log:** aus dem Journal der Unit (`gitlab-runner.service`) bzw. einer Datei aus `runner.json`.
- **Updates des Runners:** `updates: false` wie bei allen Diensten.

**Unsicherheiten (nach GitLab-Dokumentation, ohne Test gegen einen echten Server geschrieben):**
(1) Welche Rolle `GET /runners` und `GET /runners/:id/jobs` verlangen – laut Dokumentation reichen
`read_api` und Zugriff auf den Runner (Gruppe/Projekt, mindestens Maintainer); bei zu geringer Rolle
antwortet GitLab mit 403/404 und der Monitor zeigt „keine Rechte“. (2) Ob `project.name` in den Jobs der
Runner-API steht (bei fehlendem Namen steht „Projekt <Nummer>“). (3) `GET /personal_access_tokens/self` gibt es
ab GitLab 15.5. (4) Der Runner wird über den Namen gefunden, nicht über die Runner-Nummer, weil die
Nummer in `config.toml` nicht steht und das Runner-Token nie gelesen wird. Diese Punkte sind mit einem
echten GitLab-Server zu bestätigen, bevor GitLab als „vollständig unterstützt“ eingestuft wird
(`erkennung.EINSTUFUNG["gitlab"]` bleibt bis dahin und bis zur Anbindung im Sammler/in der Einrichtung
(#94, #96) auf „teil“).

**Anbindung im Sammler:** Der Sammler fragt bis #94 nur den GitHub-Runner ab. Der Adapter ist
vollständig (`GitLab.abfrage`, `beim_dienst`, `jobs_je_repository`, `api_job`, `letzte_jobs`,
`konfig_fuer`) und getestet, wird aber erst mit der Mehr-Runner-Verarbeitung (#94) und der
Server-Eingabe der Einrichtung (#96) aufgerufen.

### Momentaufnahme `GET /api/zustand` (E-19, additiv)

Nur angemeldet (sonst 401 bzw. Weiterleitung zur Einrichtung), `no-store`. Bis 0.7 gab es die
Momentaufnahme nur als ersten Schwall von `/events`; jetzt auch als ein JSON-Objekt:

```json
{ "format": 2,
  "status": { … wie bisher … }, "system": { …, "verlauf": {…} }, "prozesse": […], "platten": […],
  "container": […], "workflows": { … wie bisher … }, "update": { … },
  "vm": { "name": "runner-vm", "system": "Ubuntu 24.04.1 LTS, Python 3.12", "monitorVersion": "0.7.0",
          "auslastung": { …Bereich system… }, "verlauf": { "cpu": [], "ram": [], "netz": [], "start": 0 },
          "prozesse": […], "platten": […], "container": […] },
  "runner": [ …Einträge… ],
  "meldungen": [ …Meldungen… ] }
```

Die bisherigen Bereiche bleiben **unverändert**, die Oberfläche nutzt sie weiter, bis #94 sie auf
`vm`/`runner[]`/`meldungen[]` umstellt; danach kann das Altformat in einem eigenen Issue entfallen.
Das Live-Log bleibt allein in `/events`. Über `/events` kommen zusätzlich die Ereignisse `runner`
(die Liste) und `meldungen`, nur wenn sie sich ändern; `vm` gibt es nur in `/api/zustand`, weil
`system`, `prozesse`, `platten` und `container` schon einzeln kommen.

Ein Eintrag in `runner[]`:

```json
{ "id": "runner-vm-01", "name": "runner-vm-01", "dienst": "github", "server": "https://github.com",
  "org": "beispiel-org", "unit": "actions.runner.beispiel-org.runner-vm-01.service",
  "stand": "angebunden", "einstufung": "voll", "version": "2.338.1", "labels": ["self-hosted", "linux"],
  "faehig": { "status": true, "jobs": true, "schritte": true, "logs": true, "updates": false },
  "status": { "zustand": "job",
              "dienst": { "zustand": "aktiv", "seit": 1761700000, "grund": null },
              "beimDienst": { "zustand": "online", "seit": null } },
  "job": { "repo": "web-portal", "workflow": "CI", "name": "test", "start": 1761700100,
           "schritt": { "nr": 3, "von": 8, "name": "Abhängigkeiten" }, "schritte": ["…"] },
  "letzteJobs": [ { "name": "build", "ergebnis": "erfolg", "dauer": 274, "ende": 1761699000, "repo": "api-dienst", "workflow": "CI" } ],
  "jobsJeRepository": { …wie der Bereich workflows… },
  "log": { "art": "seiten", "unit": "actions.runner.beispiel-org.runner-vm-01.service" } }
```

- `status.zustand`: `job|bereit|offline|gestoppt|fehlt` (mit Jobs), `aktiv|gestoppt|fehlt`
  (Grundüberwachung: „Dienst aktiv“), `unbekannt` (ohne Fähigkeit `status`). `beimDienst` ist `null`
  ohne Anbindung.
- `job` und `letzteJobs` sind `null` ohne Fähigkeit `jobs`; `job.schritt` ist `{nr, von|null, name}`,
  `von` ist `null`, solange der Dienst keine Schrittliste geliefert hat, und `job.schritt` ist `null`
  ohne Fähigkeit `schritte` („Schritte nicht verfügbar“).
- `jobsJeRepository` ist `null` ohne Fähigkeit `jobs`; `log` ist `null` ohne Fähigkeit `logs`, sonst
  `{art, unit}` mit `art` = `seiten` (GitHub, `_diag/pages`, mit Schritt-Trennern), `journal` oder
  `datei` (Pfad nur aus `runner.json`). Pfade der VM stehen bewusst nicht in `/api/zustand` (Review #111);
  der Monitor kennt sie intern (`log_quelle()`).
- `stand`, `einstufung`, `version` kommen aus der Erkennung. Beim GitHub-Runner gilt `angebunden` nur,
  wenn die letzte Abfrage `ok`, `nicht-erreichbar` oder `kontingent` war (Token gültig, Dienst evtl.
  kurz weg); ohne Token, mit ungültigem Token, ohne Rechte, ohne Organisation oder vor der ersten
  Abfrage ist er `offen` – auch wenn die Erkennung „angebunden“ meldet (sie sieht nur, dass eine
  Token-Datei da ist). `grund` aus `runner.json` bleibt. Ignorierte Funde fehlen.

Eine Meldung in `meldungen[]` (Texte entstehen wie bisher im Browser, hier nur Art und Werte; nach
Schwere `fehler` → `warn` → `neutral` sortiert):

```json
{ "id": "gestoppt", "stufe": "fehler", "runner": "runner-vm-02", "dienst": "forgejo",
  "daten": { "seit": 1761700000, "grund": "oom-kill" } }
```

| `id` | Stufe | Wann | `daten` |
|---|---|---|---|
| `gestoppt` | fehler | Dienst des Runners gestoppt | `seit`, `grund` |
| `fehlt` | warn | kein Runner (`runner: null`) oder Dienst des Runners fehlt | – |
| `offline` | fehler | Dienst aktiv, beim Dienst offline | `seit` |
| `abfrage` | warn | Dienst nicht erreichbar, Kontingent erschöpft, Fehler | `abfrage`, `abgefragt`, `naechste` |
| `token` | fehler / neutral / warn | Token ungültig oder ohne Rechte / kein Token / läuft in ≤ 14 Tagen ab | `abfrage` bzw. `tokenAblauf` |
| `platte` | warn | `/` unter der Schwelle (`runner: null`) | `pfad`, `frei`, `schwelleFrei` |

Meldungen zur Verbindung und zu Updates des Monitors bleiben bis #94 allein im Browser.

### Zugangsdaten je Runner und Übernahme des Tokens (E-19)

| Pfad | Besitzer, Rechte | Inhalt |
|---|---|---|
| `/etc/runner-monitor/zugang/` | root:root, 0700 | ein Token je Runner, Dateiname `<id>.token` (ID aus der Erkennung: `a-z 0-9 . _ -`, höchstens 64 Zeichen) |
| `/etc/runner-monitor/zugang/<id>.token` | root, 0600 | Token; nur der Sammler liest es (regulär, ohne Symlink, höchstens 4 KB) |
| `/etc/runner-monitor/github-token` | root, 0600 | bisheriger Ort, bleibt als **Rückfall** bis #94/#96 |

- **Übernahme:** Bei jedem Start des Sammlers (und bei `einrichten.sh`) wird das bestehende
  GitHub-Token nach `zugang/<id>.token` **kopiert**, wenn es dort fehlt; `<id>` ist die ID des
  GitHub-Runners aus `MONITOR_RUNNER_VERZ/.runner` (`agentName`, wie die Erkennung sie bildet). Gibt
  es noch keinen registrierten Runner, versucht es der Sammler im nächsten Takt. Eine vorhandene
  Kopie bleibt – außer der alte Ort ist **neuer und anders** (z. B. Token mit einer älteren Version
  nach `einrichten.sh zurueck` erneuert): dann wird sie atomar ersetzt.
- **Schreibfehler** (Platte voll, Rechte): Die dann veraltete Kopie wird entfernt, es gilt der alte
  Ort. Der Sammler schreibt eine Warnung ins Journal, `einrichten.sh` einen Hinweis – beide ohne Token.
- **Lesen:** zuerst `zugang/<id>.token`, sonst der alte Ort.
- **Erneuern:** `sudo /opt/runner-monitor/aktuell/einrichten.sh zugang <runner>` (ohne Angabe: Liste
  der erkannten Runner); beim GitHub-Runner schreibt es auch den alten Ort. Die alten Wege
  (Einrichtung im Browser, `einrichten.sh token`) schreiben ebenfalls beide Orte – sonst gälte eine
  ältere Kopie weiter. Ältere Versionen (`einrichten.sh zurueck`) und der Update-Hilfsdienst
  (`gh attestation verify`) lesen nur den alten Ort.
- Im Dashboard lassen sich Zugangsdaten weder ansehen noch ändern (nur auf der VM, Design › Info ›
  „Zugangsdaten ändern“); nur die Ersteinrichtung im Browser legt wie bisher das GitHub-Token als
  Auftrag für den Sammler ab. Tokens landen nie in `/run/runner-monitor`, `/api/zustand` oder `/events`.

## Vom Server in den Browser

Der Browser öffnet nach der Anmeldung **eine** Verbindung `GET /events` (Server-Sent Events).
Zuerst kommt der komplette aktuelle Stand, danach nur noch Änderungen. Jeder Bereich hat ein
eigenes Ereignis und ein eigenes Datenobjekt:

| Ereignis | Inhalt (Auszug) |
|---|---|
| `status` | `vm`, `runner`, `labels`, `version` (Runner), `monitorVersion`, `system` (z. B. „Ubuntu 24.04.1 LTS, Python 3.12“, für Fehlermeldungen), `dienst{zustand: aktiv\|gestoppt\|fehlt, seit, grund}` (`grund`: systemd-`Result` bei gestopptem Dienst, z. B. `oom-kill`, sonst `null`), `github{zustand: online\|offline\|unbekannt, seit}`, `job{repo, workflow, name, ref, start, schritt{nr, von, name}, schritte[]}`, `letzteJobs[]` |
| `system` | `kerne[]` (%), `cpu`, `last[3]`, `ram{belegt, gesamt}`, `swap{…}`, `netz{empfangen, gesendet, schnittstellen[]}` (B/s), `start`; beim ersten Mal zusätzlich `verlauf{cpu[], ram[], netz[[empfangen, gesendet]], start}` (bis 600 Sekundenwerte, `start` = Zeit des ältesten Werts) |
| `prozesse` | `[{pid, benutzer, cpu, ram, befehl}]` |
| `platten` | `[{pfad, gesamt, frei, belegt, schwelleFrei}]` (Bytes; `schwelleFrei` nur für „/“) |
| `workflows` | `org`, `abfrage: ok\|kein-token\|token-ungueltig\|keine-rechte\|nicht-erreichbar\|kontingent\|fehler`, `abgefragt`, `naechste`, `tokenAblauf`, `kontingent{}`, `repos[{name, privat, laeuft, wartet}]` |
| `update` | `installiert`, `neueste{version, veroeffentlicht, notizen[], aenderungen[{version, url, neu[], einmalig}], …}` (`aenderungen`: alle Releases nach der installierten bis zur neuesten, aus den Abschnitten „Was ist neu“ und „Einmalig nach dem Update“ der Release-Notiz), `status{zustand: laeuft\|fehler\|erfolg, schritt, meldung}`, `auto` |
| `container` | `[{name, image, zustand, seit}]` |
| `log` | `neu` (Ansicht leeren), `ereignisse[{art, zeit, repo, workflow, name, ergebnis, dauer}]`, `zeilen[{art: zeile\|schritt, zeit, text \| nr, von, name}]` (gebündelt, bis 1500 je Nachricht) |
| `runner` | seit #92: Liste der Runner wie `runner[]` in `/api/zustand` (siehe „Anbieter-Adapter“), nur bei Änderung; die Oberfläche nutzt sie ab #94 |
| `meldungen` | seit #92: Liste wie `meldungen[]` in `/api/zustand`, nur bei Änderung |

Zeiten sind Unix-Sekunden. Alle 15 s kommt ein Kommentar `: lebt`, damit Proxys die Verbindung
offen lassen. Nach 5 s ohne Daten zeigt der Browser „Getrennt“ und den letzten Stand; nach 10 s
ohne Daten baut er die Verbindung selbst neu auf (Wartezeit wächst bis 30 s). Ist die Sitzung
abgelaufen (`GET /api/sitzung` → 401), geht es zur Anmeldung.

**Job-Schritt aus einer Quelle (seit 0.4.0):** Der Server rechnet `job.schritt = {nr, von, name}` und
nutzt es für die Karte, die Schritt-Pille im Log und die Trennzeilen. `nr` ist das Maximum aus der
lokalen Zahl der Seitendateien in `_diag/pages` und dem Schritt laut GitHub (alle 30 s) und wird im
selben Job nie kleiner. `von` ist `max(Zahl der Schritte, nr)` oder `null`, solange GitHub noch keine
Schrittliste geliefert hat; `name` kommt nur von GitHub. Ohne `von` zeigt die Oberfläche „3 von –“.
Der GitHub-Job zählt nur, wenn Name **und** Startzeit zum lokalen Job passen (GitHubs `started_at`
höchstens 120 s vor dem lokalen Start) – so übernimmt ein gleichnamiger Folgejob nicht die bis zu
30 s alte Abfrage des vorigen. Die Oberfläche baut den Schrittblock nur bei geänderter Segmentzahl
neu; Zahl, Name, Segmente und Laufzeit werden direkt gesetzt.

**Verlauf über Neustarts (seit 0.4.0):** Der Monitor sichert CPU-, RAM- und Netz-Verlauf alle 10 s
atomar nach `verlauf.json` (temp + rename). Beim Start übernimmt er ihn, wenn er jünger als 10 Minuten
ist und die Pause höchstens 60 s dauerte; die Lücke füllt der erste neue Messwert. Sonst beginnt der
Verlauf leer. Die Oberfläche streckt die vorhandenen Werte über die ganze Breite und schreibt links
„seit hh:mm“, bis der gewählte Zeitraum voll ist („vor 10 Min.“).

**Zeitfenster der Verläufe (seit Design 0.8.0, #89):** Die Karte „Auslastung“ hat im Kopf ein Segment
„30 s | 2 Min. | 5 Min. | 10 Min.“, das für CPU, RAM und Netz gemeinsam gilt. Die Wahl steht in
`localStorage["runner-monitor.zeitraum"]` (Sekunden; ungültig oder Speicher gesperrt → 10 Min.).
Die Rechenlogik liegt in `web/verlauf.js` (ohne DOM, mit `node --test tests/js/*.test.mjs` geprüft):
Die Werte werden in Eimer fester Größe gruppiert (30 s und 2 Min. → 1 s, 5 Min. → 3 s,
10 Min. → 5 s), deren Grenzen an der **absoluten** Sekunde hängen (Eimer = `floor(t / Eimergröße)`).
Die absolute Sekunde des letzten Werts ist `round(system.zeit)` der Momentaufnahme, jeder neue Wert
zählt eins weiter. `dashboard.js` gruppiert also nicht mehr vom Listenende aus: Der letzte Wert liegt bei
x = 100 % („jetzt“), die Kurve wandert je Sekunde um eine Messung nach links, und nur der rechte Rand
ändert sich. CPU und RAM zeigen den Mittelwert je Eimer, das Netz das Maximum (Spitzen bleiben
sichtbar). Die Netz-Skala richtet sich nach der Spitze im gewählten Zeitraum, mindestens 64 KB/s.
Der Server schickt weiter 600 Sekundenwerte; der Verlauf in der Momentaufnahme und `verlauf.json`
bleiben unverändert.

**Höchstens 6 Live-Verbindungen je Sitzung:** Ein weiteres Fenster derselben Anmeldung bekommt 429 und
versucht es mit wachsender Wartezeit erneut; sobald ein anderes Fenster zu ist, verbindet es sich.
Abgelehnt wird die neue Verbindung, nicht die älteste – sonst würden sich offene Fenster im Wechsel
verdrängen.

**Warteschlange je Browserfenster (seit 0.3.1):** Der Verteiler hält je Fenster eine Schlange mit
höchstens 2000 Nachrichten. Log-Zeilen gehen gebündelt raus: Der Log-Leser meldet je gelesenem Stück
(alle 0,3 s, bis 512 KB) **eine** Nachricht mit höchstens 1500 Zeilen. Läuft eine Schlange trotzdem
über, weil der Browser nicht hinterherkommt, wird sie geleert und der Server beendet den Strom
(Journal: „Live-Verbindung beendet …“). Der Browser verbindet sich dann neu und bekommt den
kompletten Stand. Ein `write()` an einen hängenden Browser bricht nach 60 s ab.
Bis 0.3.0 blieb ein übergelaufener Strom stumm offen, und das Dashboard stand bis zum Neustart des
Dienstes auf „Getrennt“.

Die Oberfläche (`web/`) ist statisches HTML, CSS und JavaScript ohne Framework. Federnde
Balken, ANSI-Farben im Log und alle Texte entstehen im Browser. Mit `?demo` erzeugt `demo.js`
dieselben Daten ohne Server (Entwicklung, Bildschirmfotos).

## Anmeldung und Sitzungen

- **Texte vom Server** (Fehler, Prüfergebnisse der Einrichtung) sind deutsch und zugleich der
  Schlüssel für die Übersetzung in `web/i18n.js`. Mit Platzhaltern schickt der Server zusätzlich
  `vorlage` und `werte`, z. B. `{"fehler": "Version 1.2.3 wird noch bereitgestellt …", "vorlage":
  "Version {v} wird noch bereitgestellt …", "werte": {"v": "1.2.3"}}`; `RM.serverText()` übersetzt.
- **Ohne Anmeldung** antwortet nur `/api/health` mit `{ok, version, vm}` – für Prüfungen und für
  die Anmeldeseite (VM-Name unter dem Titel, Version im Fuß).
- **Ersteinrichtung:** Das Skript legt einen Einrichtungscode `XXXX-XXXX` an (60 min gültig,
  10 Versuche, nur als SHA-256 gespeichert). Wer ihn im Browser eingibt, darf einmalig den
  Zugang anlegen. Abgeschlossen ist die Einrichtung erst mit „Zum Monitor anmelden“ in Schritt 4; danach ist `/einrichtung` gesperrt.
- **Passwort:** 12 bis 128 Zeichen, keine Zusammensetzungsregeln. Gesperrt sind die 10 000 häufigsten
  Passwörter (`runner_monitor/daten/haeufige-passwoerter.txt`, SecLists, MIT), dieselben mit
  angehängten Ziffern oder Zeichen und der Benutzername. Gespeichert als scrypt-Hash (N = 2¹⁵, r = 8, p = 1).
- **Sitzung:** Cookie `rm_sitzung` (HttpOnly, SameSite=Strict), 12 Stunden oder mit
  „Angemeldet bleiben“ 30 Tage; nach 7 Tagen ohne Nutzung beendet. Gespeichert wird nur der
  Hash des Tokens.
- **Sperre:** 5 Fehlversuche je Konto oder 30 je IP in 15 Minuten → 5 Minuten gesperrt.
- **Schutz der Anfragen:** Jede POST-Anfrage muss JSON sein und vom selben Host kommen
  (`Origin`). Strenge Content-Security-Policy ohne Inline-Skripte und -Styles, `X-Frame-Options: DENY`,
  `no-store`.
- Zwei-Faktor-Anmeldung gibt es bewusst nicht ([ADR-0003](adr/0003-nur-passwort.md)).

## Update

1. Der Sammler fragt alle 6 Stunden `releases/latest` ab und legt das Ergebnis in
   `/run/runner-monitor/release.json` (nur root kann es schreiben). Hängen Archiv und Prüfsumme
   noch nicht am Release (der Release-Workflow lädt sie erst nach dem Veröffentlichen hoch), steht
   dort `bereit: false`; der Sammler fragt dann nach 2 Minuten erneut, die Oberfläche zeigt
   „wird gerade bereitgestellt“ statt des Knopfs, und es gibt kein automatisches Update (#63).
2. Klick auf „Jetzt aktualisieren“ → der Webserver legt `auftraege/update` mit der Versionsnummer ab.
3. `runner-monitor-update.path` startet den root-Hilfsdienst. Er nimmt Archiv- und
   Prüfsummen-Adresse **nur** aus `release.json` und nur von
   `https://github.com/<release-repo>/releases/download/…`, prüft SHA-256 und – mit GitHub-CLI – die
   Herkunft per `gh attestation verify` (ADR-0005), entpackt nach
   `/opt/runner-monitor/versionen/X.Y.Z`, hängt `aktuell` um und startet beide Dienste neu.
4. Meldet `/api/health` binnen 30 s nicht die neue Version, hängt er zurück auf die alte und
   meldet „Update fehlgeschlagen“. Drei Versionen bleiben liegen (`./einrichten.sh zurueck`).

Automatisch aktualisieren (Schalter in „Info“): Ab 3 Uhr ist ein neues Update vorgemerkt. Der
Sammler startet es, sobald kein Job läuft (`pgrep Runner.Worker`), spätestens bis 7 Uhr, sonst in
der nächsten Nacht. Höchstens ein Versuch je Nacht. Der Stand (`vorgemerkt`, `verschoben`,
`gestartet`) liegt in `/run/runner-monitor/auto-update.json` und übersteht den Neustart durch das
Update selbst (#77). Das Update startet nur die Monitor-Dienste neu, der Runner bleibt unberührt.

## Dateien und Rechte

| Pfad | Besitzer, Rechte | Inhalt |
|---|---|---|
| `/opt/runner-monitor/versionen/X.Y.Z/` | root, 0755 | Programm je Version |
| `/opt/runner-monitor/aktuell` | root | Verweis auf die laufende Version |
| `/etc/runner-monitor/konfig.env` | root:runner-monitor, 0640 | Einstellungen ([Vorlage](../deploy/konfig.env.example)) |
| `/etc/runner-monitor/zugang/` | root:root, 0700 (Dateien `<runner>.token` 0600) | Zugangsdaten je Runner (#92, nur der Sammler liest sie; siehe „Anbieter-Adapter“) |
| `/etc/runner-monitor/github-token` | root, 0600 | bisheriger Ort des GitHub-Tokens, Rückfall bis #94/#96 (Update-Hilfsdienst und ältere Versionen lesen nur ihn) |
| `/etc/runner-monitor/runner.json` | root:runner-monitor, 0640 | Zuordnung und Ignorieren erkannter Runner (siehe „Runner erkennen“) |
| `/var/lib/runner-monitor/` | runner-monitor, 0750 | `zugang.json` (scrypt-Hash), `sitzungen.json`, `sperren.json`, `einstellungen.json` (Organisation, Auto-Update), `einrichtungscode.json`, `systempruefung.json`, `update-status.json`, `verlauf.json` (Verlauf der letzten 10 Min., alle 10 s gesichert), `auftraege/` |
| `/run/runner-monitor/` | root, 0755 (Dateien 0644) | `github.json`, `docker.json`, `release.json`, `erkennung.json` (erkannte Runner) – Ergebnisse des Sammlers |
| `/etc/systemd/system/runner-monitor*.{service,path}` | root | Dienste ([deploy/systemd](../deploy/systemd/)) |

## Was der Monitor nicht kann

- Nichts verändern: kein Neustart des Runners, kein Abbrechen von Jobs (nur anschauen).
- Kein HTTPS von sich aus – gedacht für das lokale Netz. Wer von außen zugreifen will, setzt
  einen Reverse-Proxy mit TLS davor ([Sicherheitsbericht](sicherheit/bericht.md), S-01).
- Ein Runner je VM im Dashboard (der erste gefundene `actions.runner.*`-Dienst). Die Erkennung findet
  schon alle Runner, `/api/zustand` liefert sie in `runner[]`; mehrere im Dashboard kommen mit #94.

## Quellcode

| Datei | Aufgabe |
|---|---|
| `runner_monitor/__main__.py` | Start der Oberfläche |
| `runner_monitor/konfig.py` | Einstellungen aus `konfig.env` und `MONITOR_*` |
| `runner_monitor/system.py` | Messungen aus `/proc` |
| `runner_monitor/runner.py` | Runner-Registrierung, Dienststatus, Journal- und Schritt-Logs |
| `runner_monitor/erkennung.py` | Erkennung aller Runner auf der VM (Units, Prozesse, Registrierungen, Server-Probe), Zuordnung aus `runner.json`, Ausgabe für `einrichten.sh` |
| `runner_monitor/github.py` | GitHub-REST-Klient (ETag, Fehlerarten), Releases, Versionen; alte Namen der Runner-Auswertung leiten an den Adapter weiter |
| `runner_monitor/anbieter/` | Anbieter-Adapter: Basisklasse, Grundüberwachung, Registry und Fähigkeiten (`__init__.py`), GitHub-Adapter (`github.py`), Zugangsdaten je Runner und Token-Übernahme (`token.py`) |
| `runner_monitor/zustand.py` | Gesamtstand, Verlauf, `runner[]` und `meldungen[]`, Momentaufnahme, Verteilung an alle Browserfenster |
| `runner_monitor/server.py` | HTTP, Anmeldung, Einrichtung, SSE, `GET /api/zustand` |
| `runner_monitor/zugang.py` | Passwörter, Sitzungen, Sperren, Einrichtungscode |
| `runner_monitor/sammler.py` | root-Sammler (GitHub, Docker, Releases, Aufträge) |
| `runner_monitor/aktualisierer.py` | root-Update-Hilfsdienst |
| `web/` | Oberfläche: `dashboard.*`, `anmelden.*`, `einrichtung.*`, `demo.js`, `stil.css`, `gemeinsam.js`, `verlauf.js` (Eimer und Pfade der Verläufe), `mail.js` (Vorlagen der `mailto:`-Links für Fehler, Idee und Update-Fehler), `i18n.js` (Sprache: deutscher Text als Schlüssel, englische Fassung in `EN`; Wahl `auto|de|en` je Browser in `localStorage["runner-monitor.sprache"]`, „auto“ folgt `navigator.languages[0]` (`de…` → Deutsch, sonst Englisch), der alte Schlüssel `rm-sprache` wird einmal übernommen; Entscheidung E-14: kein Umbau auf `de.json`/`en.json`). Anmeldung und Einrichtung setzen die Sprache über ihren Knopf fest auf `de` oder `en`; „Automatisch“ ist nur im Info-Blatt des Dashboards wählbar. Bei gesperrtem Speicher bleibt die Wahl wirkungslos |
| `einrichten.sh` | Installation, Wartung, Entfernen |
