# Design

**Stand: 23.10.2026 · Version 0.3.0**

**Design v0.3.0** – aus Claude Design, Grundlage für Version 0.3.0. Die Dateien liegen in
[`v0.3.0/`](v0.3.0/) (`*.dc.html`, Design-Canvas-Format, mit `support.js`):

| Datei | Inhalt |
|---|---|
| `Runner-Monitor 0.3.0.dc.html` | Übersicht aller Bildschirme mit Notiz „Was ist neu“ und Optionen (Zustand, GitHub, Netzwerk-Variante, Kerne, Log, Update, Info-Blatt) |
| `Main 0.3.0.dc.html` | Dashboard als Live-Prototyp inkl. Info & Hilfe |
| `Setup-Skript 0.3.0.dc.html` | Ausgabe von `einrichten.sh` |
| `Setup-Web 0.3.0.dc.html` | Einrichtung im Browser, Schritte 1–4 |
| `Login 0.3.0.dc.html` | Anmeldung |
| `ds/bamberger-it-services/tokens.json` | Designsystem „Bamberger IT Services“ |

Öffnen: die `.dc.html` im Browser (lädt React von unpkg.com). Design v1 ist mit Version 0.1.2
abgelöst und liegt nur noch im Tag [`v0.1.2`](https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/tree/v0.1.2/docs/design/v1).

Grundlage: Designsystem „Bamberger IT Services“ (Farben, Radien), Schrift = Systemschrift,
Bewegung nach Apple-Prinzipien (kritisch gedämpfte Federn, `prefers-reduced-motion`).
Farben und Maße: [TOKENS.md](TOKENS.md).

## Was 0.3.0 gegenüber v1 ändert

1. **Netzwerk in „Auslastung“:** Variante **A** (Vorgabe im Design, E-13) – eigener Block in der
   RAM-Spalte, Kopfzeile „Netzwerk ↓ … ↑ …“, Verlauf aus zwei Reihen (empfangen als Fläche in
   brand, gesendet als Linie in gold-ink), Achse „vor 10 Min. · Spitze … · jetzt“. Skala nach der
   Spitze der letzten 10 Minuten, mindestens 64 KB/s. Der RAM-Verlauf ist flacher (30 px) und hat
   keine eigene Achse.
2. **Updates › „Jetzt prüfen“:** sekundärer Knopf unter der Liste; Zustände läuft, „Auf dem
   neuesten Stand.“, „Version X ist verfügbar.“, „Gerade erst geprüft“, „Gesperrt, solange das
   Update läuft.“, Fehler „GitHub nicht erreichbar“ und „Keine Antwort vom Sammler“ (mit Befehl).
3. **GitHub-Verbindung** bleibt reine Übersicht; Token ändern steht nur in der Anleitung.
4. **Anleitung „GitHub-Token einrichten oder erneuern“** mit sechs Schritten, der `curl`-Befehl
   mehrzeilig.
5. **Befehlsblöcke mit „Kopieren“** in allen Anleitungen.
6. **Live-Log:** Hochscrollen hält das Mitlaufen an („Mitlaufen angehalten · n neue Zeilen“,
   „Zum Ende ↓“), dünne Scrollleiste; „Anhalten“ bleibt eigener Zustand mit eigener Pille.
7. **Info-Blatt bleibt beim Lesen ruhig** (keine Einblendung je Tick).
8. **Kleinkorrekturen:** „11,5 GB / 32 GB“, „Einstellung des Systems“, „Über diesen Monitor“
   ohne Docker mit Repo-Link, Kopfzeile ohne „aktualisiert …“ bei Meldung, Knopf „Info & Hilfe“,
   „Abmelden“ und „Schließen“ im Info-Blatt, „Fehler gefunden oder Idee?“ mit den technischen
   Angaben.
9. **Volle Befehlspfade** `sudo /opt/runner-monitor/aktuell/einrichten.sh …` überall.
10. **Einrichtung und Anmeldung** wie im Design (Karte über die volle Höhe, Fußleiste mit
    Zurück/Weiter, Schritt 4 „Alles eingerichtet“, Anmeldung mit Version im Fuß).

## Abgleich Design ↔ Code

Geprüft mit Bildschirmfotos bei 1440 × 900 (Design und App nebeneinander), hell und dunkel,
4, 8 und 16 Kerne.

| Bildschirm (0.3.0) | Code | Stand | Bemerkung |
|---|---|---|---|
| Main: Volllast, Job, Leerlauf, 16 Kerne dunkel | `web/dashboard.*` | umgesetzt | Netz Variante A |
| Live-Log hochgescrollt / angehalten | dashboard | umgesetzt | |
| Zustände: gestoppt, offline, Platte knapp, getrennt, kein Token, GitHub-Fehler, Token-Ablauf | dashboard | umgesetzt | |
| Info & Hilfe: Updates, Jetzt prüfen (alle Zustände), GitHub-Verbindung, Anleitungen | dashboard | umgesetzt | siehe Abweichungen |
| Updates: verfügbar, läuft, fehlgeschlagen | dashboard | umgesetzt | |
| Setup-Skript (mit/ohne Runner) | `einrichten.sh` | umgesetzt | Runner-Einrichtung zeigt zusätzlich die Ausgabe von `deploy/runner-einrichten.sh` |
| Setup-Web 1–4 | `web/einrichtung.*` | umgesetzt | siehe Abweichungen |
| Login, Login-Fehler | `web/anmelden.*` | umgesetzt | |

### Bewusste Abweichungen

- **Ansprache:** Setup-Web Schritt 1 sagt im Design „Gib den Einrichtungscode ein“; der Code sagt
  „Geben Sie …“ (Anweisung 03/06, E-10).
- **Token-Prüfung mit `curl`:** Das Design fragt `/orgs/<org>/actions/runners` ab. Das braucht das
  optionale Recht „Self-hosted runners“ und meldet ohne es 403, obwohl das Token in Ordnung ist.
  Der Code fragt `/orgs/<org>/repos?per_page=1` ab (reicht mit Metadata).
- **„GitHub nicht erreichbar“-Anleitung:** Das Design nennt `journalctl -u runner-monitor-repos`
  (Dienst des alten Prototyps). Der Code nennt `journalctl -u runner-monitor-sammler -n 30`.
- **Werte statt Beispieldaten:** Versionen, Adressen, Netz, System, Ablaufdatum kommen aus der VM.
- **Schmale Bildschirme:** Einrichtung und Anmeldung sind ab 390 px bedienbar (Anweisung 06), das
  Design zeigt nur 1440 × 900.
- **Zurück in der Einrichtung:** Ist der Zugang schon angelegt, zeigt Schritt 2 nach „Zurück“ nur
  den Hinweis „Zugang ist angelegt“ statt der leeren Felder.

## Vermerke für das nächste Design

- Bei vielen Laufwerken scrollt die Plattenliste innerhalb der Karte.
- Docker-Container werden gesammelt, aber nicht angezeigt (E-05, A-15).
