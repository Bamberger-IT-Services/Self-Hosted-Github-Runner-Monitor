# Runner-Monitor

**Stand: 23.10.2026 · Version 0.5.0** (Design v0.4.0, auf der Runner-VM abgenommen)

Live-Dashboard für einen **selbst gehosteten GitHub-Actions-Runner** auf einer Linux-VM.
Ein Blick zeigt, ob der Runner bereit ist, welcher Job gerade läuft, wie ausgelastet die VM
ist und was in den Repositories der Organisation läuft oder wartet – mit der Ausgabe des
laufenden Schritts als Live-Log.

![Dashboard mit laufendem Job](docs/handbuch/bilder/dashboard-job.png)

- **Runner-Status:** Dienst aktiv/gestoppt, online/offline bei GitHub, laufender Job mit
  Repository, Workflow, Schritt und Laufzeit, die letzten fünf Jobs.
- **Auslastung:** CPU gesamt und je Kern, RAM, Swap, Netzwerk (empfangen/gesendet mit Verlauf), Last, Verlauf der letzten 10 Minuten.
- **Prozesse und Platten:** die sechs größten Prozesse, alle Laufwerke mit Aufräumschwelle.
- **Workflows je Repository:** was läuft, was wartet (über ein nur lesendes GitHub-Token).
- **Live-Log:** Ausgabe des laufenden Schritts mit ANSI-Farben und Schritt-Trennern.
- **Meldungen** oben in der Mitte (Dienst gestoppt, Platte knapp, Token läuft ab …), jede mit
  „Was tun?“ und einer Schritt-für-Schritt-Anleitung.
- **Updates per Knopfdruck** aus den GitHub-Releases, mit Prüfsumme und automatischem Rückweg.
- Hell und dunkel, deutsch, nur zum Anschauen. Anmeldung mit Benutzer und Passwort.

Nur Python-Standardbibliothek, keine Pakete, kein Docker: zwei kleine systemd-Dienste.
Dazu ist das Repository der eine Ort für die **Runner-VM selbst**: Einrichtung, Umzug, Pflege
und Fehlerhilfe stehen in [docs/RUNNER.md](docs/RUNNER.md).

## Schnellstart auf der VM (3 Schritte)

Voraussetzung: Ubuntu 22.04 oder 24.04 mit Python 3.10+ (vorinstalliert). Der Runner darf
schon laufen – oder das Skript richtet ihn mit ein.

```bash
# 1. Neueste Version holen und entpacken (Release-Seite: Assets › runner-monitor-X.Y.Z.tar.gz)
curl -fsSLO https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/releases/latest/download/runner-monitor-0.5.0.tar.gz
tar xzf runner-monitor-0.5.0.tar.gz && cd runner-monitor-0.5.0

# 2. Einrichtungsskript: Dienste, Firewall (Port 8090 nur aus dem LAN), Runner-Suche
sudo ./einrichten.sh

# 3. Die angezeigte Adresse im Browser öffnen, Einrichtungscode eingeben,
#    Zugang anlegen, optional GitHub-Token hinterlegen – fertig.
```

Ausführlich: [docs/EINRICHTUNG.md](docs/EINRICHTUNG.md) · Updates: [docs/UPDATE.md](docs/UPDATE.md)

## Lokal entwickeln (unter 5 Minuten)

Auf dem Mac oder unter Linux, ohne Runner und ohne Anmeldung:

```bash
git clone https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor.git
cd Self-Hosted-Github-Runner-Monitor
MONITOR_ENTWICKLUNG=1 MONITOR_DATEN_VERZ=./daten MONITOR_LAUF_VERZ=./lauf python3 -m runner_monitor
# → http://127.0.0.1:8090/?demo   (Demo-Daten mit Leiste zum Umschalten der Zustände)
# → http://127.0.0.1:8090/        (echte Werte – unter macOS ohne /proc nur die Oberfläche)
python3 -m unittest discover -s tests -t .   # Tests
```

`MONITOR_ENTWICKLUNG=1` bindet nur an 127.0.0.1 und schaltet die Anmeldung ab. Die
Demo-Zustände lassen sich auch per Adresse wählen, z. B. `?demo&zustand=gestoppt&github=kein-token`.

## Dokumentation

| Thema | Datei |
|---|---|
| Wie es funktioniert (Aufbau, Datenfluss, Dateien, Rechte) | [docs/FUNKTIONSWEISE.md](docs/FUNKTIONSWEISE.md) |
| Handbuch (Bedienung mit Bildern) | [docs/handbuch/](docs/handbuch/README.md) |
| Erstinstallation des Monitors | [docs/EINRICHTUNG.md](docs/EINRICHTUNG.md) |
| Runner-VM: einrichten, umschalten, Umzug, Pflege, Fehlerhilfe | [docs/RUNNER.md](docs/RUNNER.md) |
| Update und Rückweg | [docs/UPDATE.md](docs/UPDATE.md) |
| HTTPS über einen Reverse-Proxy (Zugriff außerhalb des LAN) | [docs/HTTPS.md](docs/HTTPS.md) |
| Runbooks für Störungen | [docs/runbooks/](docs/runbooks/README.md) |
| Sicherheit, Datenschutz | [docs/sicherheit/bericht.md](docs/sicherheit/bericht.md), [docs/DATENSCHUTZ.md](docs/DATENSCHUTZ.md) |
| Architekturentscheidungen | [docs/adr/](docs/adr/) · [DECISIONS.md](DECISIONS.md) |
| Design v0.3.0 und Abgleich mit dem Code | [docs/design/README.md](docs/design/README.md) |
| Änderungen | [CHANGELOG.md](CHANGELOG.md) · [docs/releases/](docs/releases/) |
| Aufgaben | [Project „Self-Hosted-Github-Runner-Monitor Roadmap“](https://github.com/orgs/Bamberger-IT-Services/projects/5) (Issues dieses Repos) |
| Entscheidungen, Verlauf | [entwickler-dashboard/index.html](entwickler-dashboard/index.html) |

### Dokumentation nach Version

| Version | Datum | Handbuch | Release-Notiz |
|---|---|---|---|
| 0.5 | 23.10.2026 (0.5.0) | [v0.5.0/docs/handbuch](https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/tree/v0.5.0/docs/handbuch) | [v0.5.0](docs/releases/v0.5.0.md) |
| 0.4 | 23.10.2026 (0.4.0) | [v0.4.0/docs/handbuch](https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/tree/v0.4.0/docs/handbuch) | [v0.4.0](docs/releases/v0.4.0.md) |
| 0.3 | 23.10.2026 (0.3.1) | [v0.3.1/docs/handbuch](https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/tree/v0.3.1/docs/handbuch) | [v0.3.1](docs/releases/v0.3.1.md), [v0.3.0](docs/releases/v0.3.0.md) |
| 0.1 | 23.10.2026 (0.1.2) | [v0.1.2/docs/handbuch](https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/tree/v0.1.2/docs/handbuch) | [v0.1.2](docs/releases/v0.1.2.md) |

## Nichtfunktionale Anforderungen

| Bereich | Ziel |
|---|---|
| Aktualität | Systemwerte jede Sekunde, Prozesse 2 s, Platten 10 s, GitHub alle 30 s, Releases alle 6 h |
| Last | Monitor unter 1 % CPU und unter 60 MB RAM im Leerlauf; keine Abfrage, wenn niemand zuschaut, außer GitHub (30 s) |
| Darstellung | Desktop ohne Scrollen ab 1440 × 900 bis 1920 × 1080; Anmeldung und Einrichtung ab 390 px |
| Verfügbarkeit | Dienste starten bei Fehlern neu (systemd); Browser verbindet sich selbst neu und zeigt den letzten Stand |
| Sicherheit | Anmeldung (scrypt), Sperre nach Fehlversuchen, CSP ohne Inline-Skripte, CSRF-Prüfung, Token nur für root lesbar, Port nur aus dem LAN |
| Abhängigkeiten | Keine – Python-Standardbibliothek und Vanilla-JavaScript |
| Barrierefreiheit | Kontrast AA in hell und dunkel, Tastaturbedienung, `prefers-reduced-motion` |
| Datenschutz | Keine Daten verlassen die VM außer Anfragen an die GitHub-API; keine Cookies außer der Sitzung |

## Mitmachen

Fehler und Ideen als [Issue](https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/issues/new/choose) –
**bitte ohne IP-Adressen, Rechnernamen, Tokens oder Passwörter**, das Repository ist öffentlich.
Sicherheitslücken vertraulich über *Security › Report a vulnerability*.

Ein Projekt von [Bamberger IT Services](https://bamberger-it-services.de). © 2026 Bamberger IT Services, alle Rechte vorbehalten –
der Code ist zum Lesen öffentlich, aber ohne Lizenz zur Weiterverwendung (E-11).
