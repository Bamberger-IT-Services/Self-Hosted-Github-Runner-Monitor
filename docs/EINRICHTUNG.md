# Erstinstallation auf der VM

**Stand: 25.10.2026 · Version 0.7.0**

Dauer: etwa 5 Minuten. Alle Befehle auf der Runner-VM (per SSH), Platzhalter wie
`beispiel-org` durch die eigenen Werte ersetzen.

## Voraussetzungen

- Ubuntu 22.04 oder 24.04 (andere systemd-Linux mit Python ≥ 3.10 gehen meist auch)
- `sudo`-Rechte
- Netz: die VM erreicht `github.com` und `api.github.com` (HTTPS)
- Der GitHub-Runner ist installiert (`/opt/actions-runner`) – oder das Skript richtet ihn mit ein

## 1. Herunterladen und entpacken

```bash
V=0.7.0
curl -fsSLO https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/releases/download/v$V/runner-monitor-$V.tar.gz
curl -fsSLO https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/releases/download/v$V/runner-monitor-$V.tar.gz.sha256
sha256sum -c runner-monitor-$V.tar.gz.sha256     # muss „OK“ melden
tar xzf runner-monitor-$V.tar.gz && cd runner-monitor-$V
```

## 2. Einrichtungsskript

```bash
sudo ./einrichten.sh
```

Das Skript arbeitet in drei Abschnitten:

| Abschnitt | Was passiert |
|---|---|
| System prüfen | Betriebssystem, Python, Docker, Netz (Adresse, lokales Netz). Abschnitt **Runner auf dieser VM**: erkennt alle Runner – GitHub, Forgejo, Gitea, GitLab und unbekannte – über systemd-Units, Prozesse, `.runner`-Dateien und eine Abfrage beim Server ohne Zugangsdaten (Beispiel unten). Gefundene Runner bleiben unverändert. Ohne Fund fragt das Skript, ob es einen GitHub-Runner einrichten soll (siehe unten). |
| Monitor einrichten | Systembenutzer `runner-monitor` (kein root, keine Anmeldung, darf das Journal lesen), `/var/lib/runner-monitor`, `/etc/runner-monitor/konfig.env`, Programm nach `/opt/runner-monitor/versionen/0.7.0` mit Verweis `aktuell`, Dienste `runner-monitor`, `runner-monitor-sammler`, `runner-monitor-update.path`. Eine alte Terminalansicht (ttyd, `monitor-einrichten.sh`) wird ersetzt, ihr Token übernommen. |
| Firewall (ufw) | SSH bleibt erlaubt, Port 8090 nur aus dem lokalen Netz (z. B. `192.0.2.0/24`). Ist ufw aus, fragt das Skript, ob es ihn einschalten soll. |

Runner auf dieser VM, zum Beispiel mit drei Funden:

```
Runner auf dieser VM
  ✓ runner-vm-01   GitHub    github.com/beispiel-org   2.338.1   sicher
  ✓ runner-vm-02   Forgejo   git.example.org           13.0      sicher
  ? buildagent     unbekannt –                         –         unklar
      Hinweise: Dienst buildagent.service, Name enthält „agent“, startet
                Container
      → Im Browser zuordnen oder ignorieren (Schritt „Runner“)
    Die Runner bleiben unverändert, es wird nur der Monitor eingerichtet.
```

`sicher`: eindeutige Merkmale und der Server hat bestätigt. `wahrscheinlich` (`!`): Dienst erkannt,
aber der Server war nicht erreichbar – das Skript nennt den Grund. `unklar` (`?`): nur allgemeine
Hinweise; im Browser zuordnen oder ignorieren. Ohne Fund:

```
Runner auf dieser VM
  ! Kein Runner gefunden (geprüft: systemd-Units, Prozesse, .runner-Dateien).
    Der Monitor kann trotzdem die VM überwachen. Später Runner ergänzen:
      sudo /opt/runner-monitor/aktuell/einrichten.sh runner
    Jetzt einen Runner einrichten? [j/N] n
    → Im Browser: „Von Hand zuordnen“ oder „Ohne Runner fortfahren“
```

Nach der Installation sucht der Monitor beim Start und alle 6 Stunden erneut. Die Erkennung von Hand:
`sudo python3 -m runner_monitor.erkennung --text` im Ordner `/opt/runner-monitor/aktuell`
(`--json` für alle Merkmale).

Am Ende stehen Adresse und **Einrichtungscode** (60 Minuten gültig), zum Beispiel:

```
──────────────────────────────────────────────────────────
Fast geschafft. Schließen Sie die Einrichtung im Browser ab:

    http://192.0.2.25:8090

    Einrichtungscode:  K7QF-2M9D    (gilt 60 Minuten, danach: sudo /opt/runner-monitor/aktuell/einrichten.sh code)
```

## 3. Im Browser abschließen

![Schritt 1: Einrichtungscode](handbuch/bilder/einrichtung-1-code.png)

1. **Code:** den angezeigten Code eingeben. Oben steht, was das Skript erledigt hat und wie viele
   Runner es gefunden hat.
2. **Zugang schützen:** Benutzername und Passwort (mindestens 12 Zeichen; ein Satz aus mehreren
   Wörtern ist gut). Es gibt genau einen Zugang.
3. **Runner:** die Funde der Runner-Erkennung, je Fund mit Dienst (`GitHub`, `Forgejo`, `Gitea`,
   `GitLab`, `unbekannt`), Sicherheitsgrad (sicher, wahrscheinlich, unklar), Server, Version, Einstufung und
   aufklappbarer Begründung. Je nach Einstufung:
   - *vollständig unterstützt* (heute GitHub): Schalter „Übernehmen“ – die Zugangsdaten folgen im nächsten
     Schritt; aus = ignoriert.
   - *erkannt, noch nicht unterstützt*: „Grundüberwachung“ (Dienst, Auslastung, Log, Neustarts) oder „Ignorieren“.
   - *unbekannt*: „Zuordnen“ (Dienst, Anzeigename, systemd-Unit, Log-Pfad; leer = Journal der Unit) oder
     „Ignorieren“. Als Log-Pfad ist nur eine `*.log`-Datei unter `/var/log`, `/opt` oder `/srv` erlaubt.

   „Neu erkennen“ lässt den Sammler sofort neu suchen (höchstens alle 10 s). Ohne Fund gibt es drei Wege:
   Runner einrichten (`sudo /opt/runner-monitor/aktuell/einrichten.sh runner`, danach „Neu erkennen“), von
   Hand zuordnen oder „Nur VM überwachen“. Mit „Weiter“ landet die Wahl in `/etc/runner-monitor/runner.json`
   (der Sammler schreibt sie, der Webserver darf das nicht).
4. **Anbinden (optional):** je übernommenem Runner ein Block. Für den GitHub-Runner des Monitors wie bisher
   Organisation und **Fine-grained Token** (siehe unten); „Verbindung prüfen“ zeigt, welche Rechte ankommen
   (ohne eingegebenes Token prüft der Sammler das auf der VM hinterlegte), „Weiter“ prüft und speichert. Für
   alle anderen Runner (Forgejo, Gitea, GitLab, weitere GitHub-Runner) tragen Sie Zugangsdaten **auf der VM**
   ein – der Block zeigt den Befehl `sudo /opt/runner-monitor/aktuell/einrichten.sh zugang <runner>` (E-22). Der Befehl
   legt bisher **nur das Token** ab; Server und Organisation eines Forgejo-/Gitea-Runners gehören in
   `/etc/runner-monitor/runner.json` (siehe „Forgejo- oder Gitea-Runner anbinden“; Abfrage im Skript folgt mit #120).
   „Verbindung prüfen“ fragt dann über den Sammler mit genau diesen Angaben.
   Jeder Runner lässt sich mit „Überspringen – nur Grundüberwachung“ auslassen; mit nur einem Runner heißt der
   Knopf „Ohne Anbindung fortfahren“. Ohne übernommenen Runner geht es von Schritt 3 direkt zu 5.
5. **Alles eingerichtet:** Zugang, Firewall und je Runner der Stand (angebunden, Grundüberwachung,
   ignoriert) → „Zum Monitor anmelden“. Erst dieser Knopf schließt die Einrichtung ab; bis dahin führt
   „Zurück“ noch in die vorigen Schritte. Danach nimmt die Oberfläche kein Token mehr an – auch nicht
   angemeldet; Zugangsdaten nur noch auf der VM.

Ab 390 px Breite (Telefon) zeigt der Stepper nur den aktiven Schritt, alles steht untereinander.

![Schritt 3: Runner](handbuch/bilder/einrichtung-3-runner.png)

![Schritt 4: Anbinden](handbuch/bilder/einrichtung-4-anbinden.png)

### GitHub-Token erstellen

github.com › Settings › Developer settings › Personal access tokens › **Fine-grained tokens** › „Generate new token“

| Feld | Wert |
|---|---|
| Resource owner | die Organisation |
| Expiration | z. B. 90 Tage (der Monitor warnt 14 Tage vorher) |
| Repository access | All repositories |
| Repository permissions | **Actions: Read-only**, **Metadata: Read-only** |
| Organization permissions | **Self-hosted runners: Read-only** (optional, für „Online bei GitHub“) |

Das Token wird auf der VM in `/etc/runner-monitor/zugang/<runner>.token` und – als Rückfall für
ältere Versionen und den Update-Hilfsdienst – in `/etc/runner-monitor/github-token` gespeichert (nur
root kann beide lesen, seit #92). Ein vorhandenes Token übernimmt das Update von selbst. Erneuern oder
nachholen, wenn GitHub übersprungen wurde:

```bash
sudo /opt/runner-monitor/aktuell/einrichten.sh token
```

Das Skript fragt das Token verdeckt und danach die Organisation ab (Enter behält die bisherige)
und startet die Dienste neu. Info › GitHub-Verbindung zeigt Ablauf und Rechte.

Kommt keine Verbindung zustande, auf GitHub prüfen: Resource owner des Tokens muss die
**Organisation** sein, und verlangt die Organisation eine Freigabe, steht das Token unter
Organisation › Settings › Personal access tokens › **Pending requests**.

### GitLab anbinden

Gilt für einen erkannten GitLab-Runner (`gitlab-runner.service`, `config.toml`); der Sammler fragt ihn
seit #115 ab ([Funktionsweise](FUNKTIONSWEISE.md#gitlab-adapter-99)), sobald Token und Server auf der VM
liegen. Zugangsdaten für GitLab (und Forgejo/Gitea) nimmt die Weboberfläche bewusst nicht an (E-22): Sie
gehören auf die VM. Ausgeliefert gilt er als „teil“ (E-20) und erscheint im Schritt „Runner“ als „erkannt,
noch nicht unterstützt“; von Hand angebunden zeigt er Jobs.

1. **Token erstellen:** GitLab › Gruppe (oder Projekt) › Settings › **Access tokens** › „Add new token“ –
   Rolle **Maintainer** (bei Gruppen-Runnern ggf. **Owner**), Bereich **`read_api`** (nur lesen), Ablaufdatum z. B. 90 Tage (der Monitor warnt
   14 Tage vorher). Ein persönliches Token (Profil › Access tokens) mit `read_api` geht ebenso, wenn das Konto
   Zugriff auf den Runner hat.
2. **Eintragen** (die ID zeigt `sudo ./einrichten.sh zugang` ohne Angabe):
   ```bash
   sudo /opt/runner-monitor/aktuell/einrichten.sh zugang <runner-id>
   ```
3. **Server:** die Adresse Ihres GitLab (z. B. `https://gitlab.example.org`) in `/etc/runner-monitor/runner.json`
   (wie unten bei Forgejo, aber **ohne** `org` – GitLab braucht keine Organisation):
   `{ "version": 1, "runner": { "runner-vm-03": { "server": "https://gitlab.example.org" } } }`.
   Die Adresse aus der Erkennung wird nie übernommen. Der Monitor folgt keiner Weiterleitung – die Adresse muss die endgültige sein. Mit Token
   nur **`https://`**; ein Server nur mit `http://` (z. B. im LAN) wird erst abgefragt, wenn in
   `/etc/runner-monitor/runner.json` bei diesem Runner `"http_erlaubt": true` steht – das Token läuft dann unverschlüsselt
   durchs Netz, und `HTTP_PROXY` wird dabei bewusst nicht benutzt.
4. **Name:** der Runner wird bei GitLab über seine Beschreibung gefunden. Sie muss mit `name` in
   `/etc/gitlab-runner/config.toml` übereinstimmen und darf bei GitLab nur einmal vorkommen.

Was der Monitor von GitLab zeigt: Runner online/offline, aktueller Job (Projekt, Pipeline, Job, Stage),
letzte Jobs, laufende Jobs je Projekt. **Nicht verfügbar:** Schritte eines Jobs und wartende Jobs (die
GitLab-API liefert beides nicht). Ein bei GitLab pausierter Runner gilt als offline. **Instanz-Runner** (von der
Instanz-Verwaltung angelegt) kann der Monitor nicht abfragen (dafür braucht GitLab Administratorrechte).

### Forgejo- oder Gitea-Runner anbinden (#93)

Erkennt der Monitor einen Forgejo- oder Gitea-Runner (System prüfen › „Runner auf dieser VM“),
überwacht er ihn zunächst nur über Dienst und Journal (ausgeliefert gilt er als „teil“, bis die
Einrichtung im Browser ihn anbindet, E-23). Von Hand angebunden zeigt er zusätzlich, ob der
Runner beim Server online ist, Jobs je Repository, den laufenden Job mit Schritten (Forgejo ab 17,
Gitea) und die letzten Jobs. Bis die Einrichtung im Browser das übernimmt (#96/#97), geht es so:

**1. Token erstellen** – auf dem Server (z. B. `https://git.example.org`) anmelden: Einstellungen ›
Anwendungen › „Zugriffstoken erstellen“ (Gitea: „Neues Token generieren“).

| Feld | Wert |
|---|---|
| Name | z. B. `runner-monitor` |
| Repository- und Organisationszugriff | alle (öffentliche und private) |
| `repository` | **Lesen** – Repositories, Läufe, Jobs, Schritte, Log-Anfang |
| `organization` | **Lesen** – Organisation und Runner-Liste („Online“) |
| `user` | **Lesen**, nur wenn die Runner einem Benutzer statt einer Organisation gehören |
| alles andere | keine Rechte |

Die Runner-Liste der Organisation zeigt Forgejo und Gitea nur ihren **Besitzern**. Gehört das Konto
des Tokens nicht zu den Besitzern, bleibt „beim Dienst“ unbekannt, und bei Forgejo lassen sich
Jobs keinem Runner zuordnen (Jobs je Repository gibt es trotzdem). Ein eigenes Konto nur für den
Monitor im Team „Owners“ ist die sauberste Lösung. Forgejo und Gitea melden einen Ablauf des Tokens
nicht über die API; der Monitor kann deshalb nicht vorher warnen, sondern meldet erst „Token ungültig“.

**2. Token auf der VM ablegen** (ID aus der Liste, z. B. `runner-vm-02`):

```bash
sudo /opt/runner-monitor/aktuell/einrichten.sh zugang                # erkannte Runner
sudo /opt/runner-monitor/aktuell/einrichten.sh zugang runner-vm-02   # Token verdeckt eingeben
```

**3. Server und Organisation eintragen** in `/etc/runner-monitor/runner.json` (root, Gruppe
`runner-monitor`, 0640). Nur diese Angaben bestimmen, wohin der Monitor mit dem Token fragt –
die Adresse aus der Erkennung ist nur ein Vorschlag:

```json
{ "version": 1,
  "runner": {
    "runner-vm-02": { "server": "https://git.example.org", "org": "beispiel-org" } } }
```

`server` ohne `/api/v1` und ohne Zugangsdaten; `org` ist die Organisation (oder der Benutzer), der
die Repositories gehören. Mit Token gilt nur **`https://`**; ein Server nur mit `http://` (z. B. im LAN)
wird erst abgefragt, wenn bei diesem Runner zusätzlich `"http_erlaubt": true` steht (E-21) – das
Token läuft dann unverschlüsselt durchs Netz, `HTTP_PROXY` wird dabei bewusst nicht benutzt. Der Sammler liest Datei und Token in jeder Runde (alle 30 s) neu – ein
Neustart ist nicht nötig. Ob es klappt, steht in `/run/runner-monitor/anbieter.json` (`"abfrage":
"ok"`) bzw. im Journal des Sammlers.

**Sicherheit:** `http_erlaubt` nur in einem vertrauenswürdigen Netz
([Sicherheitsbericht](sicherheit/bericht.md), S-FORGEJO-01). Der Monitor folgt keiner Weiterleitung –
leitet der Server z. B. von `http` auf `https` um, die `https`-Adresse eintragen. Ein Konto im Team
„Owners“ hat volle Rechte an der Organisation – das Token selbst bekommt trotzdem nur Leserechte.

## Prüfen

```bash
sudo ./einrichten.sh status                       # Dienste und Version
journalctl -u runner-monitor -u runner-monitor-sammler -n 30
curl -s http://127.0.0.1:8090/api/health          # {"ok": true, "version": "0.7.0", "vm": "runner-vm"}
```

## Einstellungen

In `/etc/runner-monitor/konfig.env` ([Vorlage](../deploy/konfig.env.example)), danach
`sudo systemctl restart runner-monitor runner-monitor-sammler`:

| Schlüssel | Vorgabe | Bedeutung |
|---|---|---|
| `MONITOR_PORT` | 8090 | Port der Oberfläche (Firewall-Regel anpassen!) |
| `MONITOR_ORG` | – | Organisation (die Einrichtung im Browser hat Vorrang) |
| `MONITOR_RUNNER_VERZ` | `/opt/actions-runner` | Ordner des Runners |
| `MONITOR_SCHWELLE_FREI_GB` | 25 | Warnschwelle für „/“ |
| `MONITOR_VM_NAME` | Hostname | Anzeigename |
| `MONITOR_HTTPS` | aus | `1` nur hinter einem Reverse-Proxy mit TLS: Cookies mit `Secure`, HSTS ([HTTPS.md](HTTPS.md)) |
| `MONITOR_ADRESSE` | `0.0.0.0` | `127.0.0.1`, wenn ein Proxy davor sitzt |
| `MONITOR_UPDATE_HERKUNFT` | – | `pflicht`: Update nur mit bestätigter GitHub-Attestierung ([UPDATE.md](UPDATE.md)) |
| `RUNNER_LABELS` | `self-hosted,linux,x64` | Labels, falls GitHub nicht abgefragt werden kann |
| `MONITOR_RELEASE_REPO` | dieses Repository | Quelle für Updates (nur für Forks ändern) |

## Weitere Befehle

| Befehl | Wirkung |
|---|---|
| `sudo ./einrichten.sh code` | neuer Einrichtungscode (nur solange kein Zugang besteht) |
| `sudo ./einrichten.sh passwort` | Zugang zurücksetzen, alle abmelden, neuer Code – Token und Einstellungen bleiben |
| `sudo ./einrichten.sh token` | GitHub-Token eintragen oder erneuern |
| `sudo ./einrichten.sh zugang <runner>` | Zugangsdaten eines Runners eintragen oder erneuern (`<runner>` = ID aus der Erkennung; ohne Angabe: Liste). Schreibt `/etc/runner-monitor/zugang/<runner>.token`, beim GitHub-Runner auch `github-token` |
| `sudo ./einrichten.sh runner` | GitHub-Runner einrichten |
| `sudo ./einrichten.sh aktualisieren` | neueste Version installieren ([UPDATE.md](UPDATE.md)) |
| `sudo ./einrichten.sh zurueck` | zur vorherigen Version |
| `sudo ./einrichten.sh entfernen` | Dienste und Firewall-Regel entfernen, Daten bleiben (`--alles` löscht auch Daten) |

Das Skript liegt nach der Installation auch unter `/opt/runner-monitor/aktuell/einrichten.sh`.
