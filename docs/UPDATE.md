# Update und Rückweg

**Stand: 25.10.2026 · Version 0.6.1**

Der Monitor prüft alle 6 Stunden, ob es auf GitHub ein neueres Release gibt – sofort geht es mit
**Info › Updates › „Jetzt prüfen“** (höchstens einmal je Minute, auf der VM alternativ
`sudo systemctl restart runner-monitor-sammler`). Gibt es eins, erscheint
oben die Meldung **„Version X.Y.Z verfügbar“**. Vorher die Release-Notiz lesen
(`docs/releases/vX.Y.Z.md` oder „Was ist neu?“). Steht dort ein einmaliger Schritt, kommt er
nach dem Update dran.

## Im Browser (empfohlen)

1. Meldung „Was ist neu?“ oder **Info › Updates** öffnen.
2. **„Jetzt auf X.Y.Z aktualisieren“**. Die Schritte erscheinen live:
   herunterladen → Prüfsumme prüfen → installieren → neu starten → Funktion prüfen.
3. Nach etwa einer Minute meldet der Monitor „Aktualisiert auf X.Y.Z“.

Der Runner und laufende Jobs arbeiten währenddessen weiter, nur der Monitor ist kurz nicht
erreichbar.

![Update verfügbar](handbuch/bilder/update-verfuegbar.png)

**Automatisch:** In Info › Updates „Automatisch aktualisieren“ einschalten – dann nachts um
3 Uhr, aber nur, wenn gerade kein Job läuft.

## Per SSH

```bash
sudo /opt/runner-monitor/aktuell/einrichten.sh aktualisieren
```

Ohne Internet: das neue Paket wie bei der [Einrichtung](EINRICHTUNG.md) herunterladen, prüfen,
entpacken und darin `sudo ./einrichten.sh` aufrufen. Zugang, Token und Einstellungen bleiben.

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
eine Warnung ins Journal.

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
