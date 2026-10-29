# Update und Rückweg

**Stand: 29.10.2026 · Version 0.8.1**

Der Monitor prüft alle 6 Stunden, ob es in der Update-Quelle (Vorgabe GitHub, wählbar Forgejo –
siehe [Quelle](#quelle-github-oder-forgejo)) ein neueres Release gibt – sofort geht es mit
**Info › Updates › „Jetzt prüfen“** (höchstens einmal je Minute, auf der VM alternativ
`sudo systemctl restart runner-monitor-sammler`). Gibt es eins, erscheint
oben die Meldung **„Version X.Y.Z verfügbar“**. Vorher die Release-Notiz lesen
(`docs/releases/vX.Y.Z.md` oder „Was ist neu?“). Info › Updates zeigt alle Versionen seit der
installierten – je Version „Was ist neu“ und, hervorgehoben, „Einmalig nach dem Update“. Ein
einmaliger Schritt kommt nach dem Update dran.

## Im Browser (empfohlen)

1. Meldung „Was ist neu?“ oder **Info › Updates** öffnen.
2. **„Jetzt auf X.Y.Z aktualisieren“**. Die Schritte erscheinen live:
   herunterladen → Prüfsumme prüfen → installieren → neu starten → Funktion prüfen.
3. Nach etwa einer Minute meldet der Monitor „Aktualisiert auf X.Y.Z“.

Der Runner und laufende Jobs arbeiten währenddessen weiter, nur der Monitor ist kurz nicht
erreichbar.

![Update verfügbar](handbuch/bilder/update-verfuegbar.png)

**Automatisch:** In Info › Updates „Automatisch aktualisieren“ einschalten. Ab 3 Uhr nachts wird
ein neues Update vorgemerkt und startet, sobald der Runner keinen Job hat, spätestens bis 7 Uhr.
Läuft bis dahin durchgehend ein Job, kommt es in der nächsten Nacht dran. Info › Updates zeigt den
Stand („vorgemerkt“ oder „nächster Versuch in der kommenden Nacht“). Neu gestartet werden nur die
Monitor-Dienste, der Runner und laufende Jobs merken davon nichts.

## Per SSH

```bash
sudo /opt/runner-monitor/aktuell/einrichten.sh aktualisieren
```

Ohne Internet: das neue Paket wie bei der [Einrichtung](EINRICHTUNG.md) herunterladen, prüfen,
entpacken und darin `sudo ./einrichten.sh` aufrufen. Zugang, Token und Einstellungen bleiben.

## Quelle: GitHub oder Forgejo

Vorgabe ist GitHub; bestehende VMs bleiben dabei, bis jemand die Quelle ändert. Wahlweise kommen
Updates von einem Forgejo-Server ([ADR-0007](adr/0007-update-quelle-forgejo.md)):

```bash
sudo /opt/runner-monitor/aktuell/einrichten.sh quelle
```

Das Skript fragt GitHub oder Forgejo ab, bei Forgejo die Adresse (z. B. `https://git.example.org`,
ohne `/api/v1`), fragt dort das neueste Release ab und schreibt `/etc/runner-monitor/konfig.env`:

```ini
MONITOR_UPDATE_QUELLE=forgejo
MONITOR_UPDATE_FORGEJO=https://git.example.org
#MONITOR_UPDATE_HTTP_ERLAUBT=1   # nur für http:// im LAN, setzt das Skript nach Rückfrage
```

Info › Updates zeigt die Quelle in der Zeile „Quelle“ (bei `http://` gelb mit „unverschlüsselt“),
`einrichten.sh status` ebenso.

- **Ohne Anmeldung:** Das Repository muss auf Forgejo ohne Anmeldung lesbar sein (öffentlich, bei
  Forgejo `REQUIRE_SIGNIN_VIEW` aus). Ein Token wird nicht hinterlegt. Sonst meldet der Monitor
  „Forgejo verlangt eine Anmeldung“ bzw. „Quelle verlangt Anmeldung“.
- **Nur diese Adresse:** Der Monitor folgt keiner Weiterleitung und lädt nur
  `<adresse>/<repo>/releases/download/vX.Y.Z/runner-monitor-X.Y.Z.tar.gz` und `….sha256`. Das
  Repository ist dasselbe wie auf GitHub (`MONITOR_RELEASE_REPO`), der Tag muss `vX.Y.Z` heißen.
- **`http://`** nur mit ausdrücklicher Freigabe. Dann kann jemand im Netz Version, Archiv und
  Prüfsumme gemeinsam austauschen – es schützt nur noch die Herkunftsprüfung. Für `http://` deshalb
  GitHub-CLI und Token einrichten und `MONITOR_UPDATE_HERKUNFT=pflicht` setzen.
- **Herkunft:** auch bei Forgejo gegen die GitHub-Attestierung (nächster Abschnitt) – sie hängt an der
  Prüfsumme des Pakets, nicht am Ort. Das trägt nur, wenn das Release auch über GitHub gebaut wurde
  und das Paket auf Forgejo byte-gleich ist. Gibt es eine Version nur auf Forgejo, lehnt eine VM mit
  GitHub-CLI und Token das Update ab („Herkunft nicht bestätigt“).

Zurück zu GitHub: `einrichten.sh quelle`, „1“ – Adresse und http-Freigabe werden entfernt.

**Erst ab der Version, die Forgejo kennt:** Das Update installiert immer der Hilfsdienst der gerade
laufenden Version. Eine VM mit 0.8.1 oder älter holt die erste Version mit Forgejo-Quelle deshalb noch
von GitHub (oder per Paket von Hand wie bei der [Einrichtung](EINRICHTUNG.md)); danach
`einrichten.sh quelle`.

## Prüfen

```bash
curl -s http://127.0.0.1:8090/api/health                 # neue Versionsnummer
journalctl -u runner-monitor-update -n 50               # Protokoll des Updates
sudo /opt/runner-monitor/aktuell/einrichten.sh status
```

Danach im Browser einmal durchklicken: Anmeldung, Dashboard füllt sich, Live-Log.

## Was bei einem Fehler passiert

Antwortet die neue Version nach dem Neustart nicht binnen 30 Sekunden, stellt der
Hilfsdienst die alte Version **automatisch** wieder her. Oben steht dann „Update fehlgeschlagen
– Version X wurde wiederhergestellt“ mit dem Grund. Stimmt die Prüfsumme nicht, wird das
Archiv verworfen und nichts installiert. Runbook: [update-fehlgeschlagen](runbooks/update-fehlgeschlagen.md).

## Herkunft prüfen (empfohlen)

Seit Version 0.6 bestätigt der Release-Workflow jedes Paket per GitHub-Attestierung
([ADR-0005](adr/0005-herkunft-per-github-attestierung.md)). Ist die GitHub-CLI auf der VM
installiert, prüft der Update-Hilfsdienst damit, dass das Archiv aus diesem Repository und dessen
Release-Workflow stammt – sonst verwirft er es. Ohne CLI prüft er nur die Prüfsumme und schreibt
eine Warnung ins Journal. Das gilt für beide Quellen; bei Forgejo wird ebenfalls gegen das
GitHub-Repository geprüft. Vor der Prüfsumme verwirft er eine Anmeldeseite oder einen Download, der
kein tar.gz ist; nach dem Entpacken muss die Datei `VERSION` im Paket die Zielversion nennen.

GitHub-CLI einmal installieren (offizielles Paket-Repository, siehe cli.github.com):

```bash
sudo mkdir -p -m 755 /etc/apt/keyrings
wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
sudo apt update && sudo apt install -y gh
gh --version    # 2.49 oder neuer
```

Die Prüfung nutzt das GitHub-Token des Monitors (`/etc/runner-monitor/github-token`), eine
Anmeldung mit `gh auth login` ist nicht nötig. Nur mit bestätigter Herkunft aktualisieren:
`MONITOR_UPDATE_HERKUNFT=pflicht` in `/etc/runner-monitor/konfig.env`.

Von Hand prüfen:

```bash
gh attestation verify runner-monitor-X.Y.Z.tar.gz --repo Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor
```

## Zurück auf die vorige Version

```bash
sudo /opt/runner-monitor/aktuell/einrichten.sh zurueck
```

Die drei zuletzt installierten Versionen liegen unter `/opt/runner-monitor/versionen/`.
Ältere: das Paket der gewünschten Version herunterladen und darin `sudo ./einrichten.sh` aufrufen.
Die Daten in `/var/lib/runner-monitor` sind zwischen den Versionen verträglich; wo nicht, sagt
es die Release-Notiz.
