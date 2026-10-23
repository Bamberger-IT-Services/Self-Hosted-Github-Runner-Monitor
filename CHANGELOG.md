# Änderungen

Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionen nach SemVer.

## [Unveröffentlicht]

## [0.1.0] – noch nicht veröffentlicht

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
