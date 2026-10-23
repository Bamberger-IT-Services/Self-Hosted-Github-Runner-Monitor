# Änderungen

Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionen nach SemVer.

## [Unveröffentlicht]

## [0.3.0] – 23.10.2026

Umsetzung von **Design v0.3.0** (`docs/design/v0.3.0/`, Abgleich in `docs/design/README.md`).

### Neu
- Auslastung: **Netzwerk** als eigener Block in der RAM-Spalte mit Verlauf der letzten 10 Minuten
  (empfangen als Fläche, gesendet als Linie, Skala nach der Spitze, mindestens 64 KB/s).
- Live-Log: eigene Pille „Mitlaufen angehalten · n neue Zeilen“ mit **Zum Ende ↓** beim
  Hochscrollen, dünne Scrollleiste; „Anhalten“ behält seine Pille.
- Befehle in Info & Hilfe mit Knopf **Kopieren** (auch über http im LAN).
- „Fehler gefunden oder Idee?“ zeigt Version, System, Runner und Browser.

### Geändert
- „Jetzt prüfen“ nach Design: eigene Zustände, Fehler als Hinweis mit Befehl, gesperrt während
  eines Updates.
- GitHub-Verbindung ist reine Übersicht; Token ändern steht in der Anleitung (sechs Schritte,
  mehrzeiliger `curl`-Befehl).
- Kopfzeile: Knopf „Info & Hilfe“; mit Meldung entfällt „aktualisiert …“ immer.
- Einrichtung im Browser neu nach Design (volle Kartenhöhe, Zurück/Weiter, „Alles eingerichtet“),
  Anmeldung mit VM-Name und Version im Fuß, Ausgabe von `einrichten.sh` in Abschnitten.
- Entwickler-Dashboard nach dem Aufbau des Helios-Dashboards.
- Design v1 aus dem Repository entfernt (liegt im Tag v0.1.2).

### Behoben
- `einrichten.sh` bricht nicht mehr still ab, wenn Docker fehlt oder die VM keine Standardroute hat.
- Knöpfe in den Karten Runner-Status und Workflows verlieren Klicks und Fokus nicht mehr durch die
  sekündliche Aktualisierung.
- „Jetzt prüfen“ meldet bei abweichender Uhr von Browser und VM nicht mehr „Keine Antwort vom Sammler“.
- Meldung „Kein Runner eingerichtet“ hat eine eigene Anleitung unter „Was tun, wenn …“.

## [0.1.2] – 23.10.2026

### Neu
- Info › Updates: Knopf **„Jetzt prüfen“** fragt GitHub sofort nach einer neuen Version statt erst
  nach bis zu 6 Stunden (über den root-Sammler, höchstens einmal je Minute).

## [0.1.1] – 23.10.2026

Erstes veröffentlichtes Release, enthält 0.1.0.

### Neu
- Auslastung: Zeile **Netz** mit Empfangen und Senden je Sekunde und der Spitze der letzten
  10 Minuten (aus `/proc/net/dev`, ohne virtuelle Schnittstellen).

### Geändert
- Info & Hilfe baut sich nicht mehr jede Sekunde neu auf: Das Blatt blendet nur beim Öffnen ein,
  danach aktualisieren sich nur die Werte. Position, Auswahl und aufgeklappte Anleitung bleiben.
- Live-Log: Hochscrollen hält das Mitlaufen an (neue Zeilen werden gezählt), ganz unten läuft es
  wieder mit.
- Info › GitHub-Verbindung nennt den Befehl zum Ändern auf der VM, die Token-Anleitung die
  Freigabe in der Organisation und eine Prüfung mit `curl`.
- Alle Befehle in der Oberfläche nutzen den festen Pfad `/opt/runner-monitor/aktuell/einrichten.sh`
  (`./einrichten.sh` gibt es nur im entpackten Ordner).

### Behoben
- `einrichten.sh token` fragt immer nach der Organisation (Enter behält die bisherige) und trägt
  sie in `konfig.env` und den Einstellungen ein. Vorher fehlte sie, wenn GitHub in der Einrichtung
  übersprungen wurde.

## [0.1.0] – nicht als Release veröffentlicht (in 0.1.1 enthalten)

Erste Version nach Design v1.

### Neu
- Dashboard: Runner-Status mit laufendem Job und Schritten, letzte Jobs, Workflows je Repository,
  Auslastung (CPU je Kern, RAM, Swap, Last, 10-Minuten-Verlauf), Top-6-Prozesse, alle Platten mit
  Aufräumschwelle, Live-Log mit ANSI-Farben und Schritt-Trennern, Anhalten, Umbrechen.
- Meldungen in der Kopfzeile mit „Was tun?“ und Anleitungen in Info & Hilfe (inkl. Runner-Logs abrufen).
- Hell, dunkel, automatisch – Umschalter in der Kopfzeile und in Info.
- Anmeldung (scrypt, Sperre, „Angemeldet bleiben“) und Ersteinrichtung im Browser mit Einrichtungscode.
- Root-Sammler für GitHub-API und Docker; GitHub-Token nur für root lesbar.
- Updates aus GitHub-Releases per Knopf oder nachts automatisch, mit Prüfsumme und Rückweg.
- `einrichten.sh`: Installation, Firewall, Runner-Erkennung und -Einrichtung, Code, Passwort, Token,
  Aktualisieren, Zurück, Entfernen. Ersetzt die alte ttyd-Terminalansicht.
- Fehler melden / Idee vorschlagen als vorbereitetes GitHub-Issue.
