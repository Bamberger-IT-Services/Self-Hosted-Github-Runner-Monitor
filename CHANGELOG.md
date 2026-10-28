# Änderungen

Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionen nach SemVer.

## [Unveröffentlicht]

### Neu
- Verlauf mit festen Zeitfenstern: Auslastung hat einen Zeitraum-Umschalter (30 s, 2, 5 oder 10 Min.);
  die Werte werden in Eimer mit festen Grenzen gruppiert, die Kurve wandert ruhig nach links (#89).
- Info › Darstellung › Sprache: `Automatisch | Deutsch | English`. Automatisch folgt der ersten
  Sprache des Browsers (`de…` → Deutsch, alles andere → Englisch); die Wahl wird je Browser unter
  `runner-monitor.sprache` gemerkt, die bisherige Wahl übernommen (#90).
  Hinweis: Wer bisher nichts gewählt hat und einen nicht deutschen Browser nutzt, sieht jetzt Englisch.
- Runner-Erkennung: Der Monitor findet selbst alle Runner auf der VM (GitHub, Forgejo, Gitea,
  GitLab, unbekannte) über systemd-Units, Prozesse, `.runner`-Dateien und eine Abfrage beim Server
  ohne Zugangsdaten, mit Grad sicher/wahrscheinlich/unklar und Begründung. `einrichten.sh` zeigt
  sie in „System prüfen“ › „Runner auf dieser VM“; der Sammler sucht beim Start und alle 6 Stunden
  (`/run/runner-monitor/erkennung.json`). Das Dashboard bleibt vorerst beim GitHub-Runner (#91).

### Geändert
- Runner-Erkennung nachgeschärft (#109): Takt und Frist des Sammlers mit `time.monotonic()`; die
  Fehlerausgabe (stderr, höchstens 2000 Zeichen) der Erkennung landet im Journal statt in `/dev/null`;
  `einrichten.sh` ruft sie mit `timeout --foreground 60` auf (Strg+C wirkt sofort); github.com gilt
  auch mit `--ohne-netz` als „sicher“; eine fremde `.runner` im Arbeitsordner kippt die Anzeige des
  Dienstes nicht mehr (die erste Registrierung aus Konfiguration oder Programmordner entscheidet).
- Fehler und Ideen gehen per E-Mail an Bamberger IT Services statt als GitHub-Issue: Info › „Fehler
  gefunden oder Idee?“ und der fehlgeschlagene Update öffnen das Mailprogramm mit Betreff, Vorlage und
  den technischen Angaben (Version, System, Runner, Browser); Vorlage in Deutsch oder Englisch nach
  Oberfläche, Token-Muster werden entfernt. Die Issue-Vorlagen für Fehler und Ideen entfallen (#98).

## [0.7.0] – 25.10.2026

### Geändert
- Automatisches Update wartet, bis der Runner frei ist: ab 3 Uhr vorgemerkt, gestartet, sobald kein
  Job läuft (bis 7 Uhr, sonst nächste Nacht), höchstens ein Versuch je Nacht; Info › Updates zeigt
  den Stand (#77).

### Neu
- Dashboard auf Englisch umschaltbar: Info › Darstellung › Sprache (Vorgabe nach Browser, je
  Browser gemerkt); Texte über `web/i18n.js`, ein Test prüft, dass jeder Text übersetzt ist (#80).
- Anmeldung und Einrichtung ebenfalls auf Englisch, mit eigenem Umschalter; Fehlermeldungen und
  Prüfergebnisse des Servers werden übersetzt (Vorlage mit Platzhaltern, #81).
- Info › Updates zeigt alle Änderungen seit der installierten Version – je Version „Was ist neu“
  und hervorgehoben „Einmalig nach dem Update“, ältere Versionen zum Aufklappen (#78).

### Sicherheit
- `SECURITY.md`: Lücken vertraulich über GitHub melden („Private vulnerability reporting“);
  `main` nur noch per PR mit grüner CI (Branch-Schutz) (#21).

## [0.6.1] – 25.10.2026

### Geändert
- Gestoppter Runner-Dienst: Status-Karte und Meldung nennen die Ursache aus systemd (z. B. „Speicher
  voll (OOM-Killer)“); „Was tun“ zeigt dann Schritte zu RAM, Swap und Speicher-Einstellung und startet
  den Dienst mit vollem Unit-Namen (#68).
- Runner-Einrichtung sichert den Dienst gegen Speichermangel: `OOMPolicy=continue` und
  `Restart=on-failure` per Drop-in, Swap-Datei, wenn keine da ist, Hinweis unter 8 GB RAM (#67).

### Behoben
- Runner-Version wurde nicht angezeigt („–“): Der Monitor liest sie jetzt aus
  `bin/Runner.Listener.deps.json`, statt das Programm zu starten; ein leeres Ergebnis wird nur 30 s
  gemerkt (#69).

### Dokumentation
- `docs/RUNNER.md`: Wie viel Arbeitsspeicher die Runner-VM braucht (mindestens 8 GB plus 4 GB Swap
  für Builds und Image-Jobs), Fehlerhilfe für `oom-kill`; Runbook „Runner-Dienst gestoppt“ ergänzt (#70).

## [0.6.0] – 24.10.2026

### Sicherheit
- OWASP-ZAP-Baseline gegen eine Testinstanz (#20), Ergebnis im Sicherheitsbericht; Werkzeug
  `werkzeuge/zap-baseline.sh`. Behoben: Ohne JavaScript schickte das Anmeldeformular das Passwort in
  der Adresse (S-ZAP-01); ein vorzeitig abgelehnter POST ließ seinen Körper in der Verbindung, und
  Fehlerseiten der Standardbibliothek kamen ohne Sicherheits-Kopfzeilen (S-HTTP-01).

### Neu
- **Herkunft der Updates** (#18, ADR-0005): Der Release-Workflow bestätigt jedes Paket per
  GitHub-Attestierung (Sigstore); der Update-Hilfsdienst prüft sie mit `gh attestation verify` und
  verwirft ein Archiv ohne Bestätigung. Ohne GitHub-CLI auf der VM weiter nur Prüfsumme;
  `MONITOR_UPDATE_HERKUNFT=pflicht` erzwingt die Prüfung.

### Behoben
- Update gleich nach einem neuen Release scheiterte mit „Release enthält kein Archiv mit
  Prüfsumme“, wenn der Monitor das Release abfragte, bevor der Release-Workflow das Paket angehängt
  hatte – und fragte erst nach 6 Stunden wieder. Jetzt: „wird gerade bereitgestellt“, neue Abfrage
  nach 2 Minuten, kein Auto-Update in dieser Zeit (#63).

## [0.5.0] – 23.10.2026

### Neu
- **HTTPS über einen Reverse-Proxy** (#17): Anleitung `docs/HTTPS.md` mit Caddy; neue Einstellung
  `MONITOR_HTTPS=1` setzt `Secure` an den Cookies und schickt HSTS.

### Geändert
- Anmeldung und Einrichtung sperren die 10 000 häufigsten Passwörter (SecLists, MIT), auch mit
  angehängten Ziffern oder Zeichen (#16, S-AUTH-02).
- Keine internen Projektnamen mehr im Repository (#27); das Runner-Skript räumt alte wöchentliche
  Aufräum-Einträge jetzt per Muster ab.
- **GitHub-Kontingent schonen** (#15): bedingte Anfragen mit ETag – unveränderte Antworten (304)
  zählen nicht gegen das Kontingent; ruhige Repositories (über eine Stunde kein Push, nichts läuft
  oder wartet) fragt der Sammler nur alle 5 Minuten ab. `github.json` nennt die Zahl der Anfragen
  (`anfragen.anfragen`, davon `anfragen.unveraendert`).

### Behoben
- Live-Log: Verschwindet eine Seitendatei, während der Monitor sie sucht (der Runner räumt
  hochgeladene Seiten auf), oder enthält sie einen ungültigen Zeitstempel, läuft der Log-Leser weiter;
  Fehler stehen im Journal. Gleiches für den Journal-Leser. Neues Runbook „Live-Log bleibt leer“ (#57).
- Höchstens 6 Live-Verbindungen je Sitzung, weitere bekommen 429 (#19, S-DOS-01).
- Ein hängendes Netzlaufwerk (NFS, CIFS) hält die Messung nicht mehr an; es fehlt in der Plattenliste,
  bis es wieder antwortet (#26).

## [0.4.0] – 23.10.2026

Umsetzung von **Design v0.4.0** (`docs/design/v0.4.0/`, Epic #42).

### Neu
- **Verlauf füllt die ganze Breite** (Design 0.4.0, #43): CPU, RAM und Netz strecken die vorhandenen
  Werte über die volle Fläche; links steht „seit hh:mm“, bis 10 Minuten gemessen sind. Der Monitor
  sichert den Verlauf alle 10 s nach `verlauf.json` und übernimmt ihn nach einem Neustart (bis 60 s
  Pause). Demo: `?verlauf=120`.
- **Job-Schritte überall gleich** (Design 0.4.0, #44): Karte, Log-Pille und Trennzeilen zeigen
  denselben Schritt aus einer Quelle (`job.schritt = {nr, von, name}`), die Zahl springt nie zurück.
  Der Segmentbalken steht immer; ohne Schrittliste von GitHub „3 von –“ mit gestricheltem Rest.
  Demo: `?schritte=lokal`.

### Behoben
- Demo zeigt als installierte Version die Version des Servers statt fest „0.1.0“ (#25).

## [0.3.1] – 23.10.2026

### Behoben
- **Dashboard blieb auf „Getrennt“ stehen**, bis der Dienst neu gestartet wurde. Ursache: Jede Zeile des
  Job-Logs war eine eigene Nachricht. Ein Build mit viel Ausgabe füllte die Warteschlange eines
  Browserfensters (2000 Nachrichten). Der Server warf sie raus, ließ die Verbindung aber offen und schickte
  nur noch Lebenszeichen. Jetzt:
  - Log-Zeilen gehen gebündelt raus (eine Nachricht je gelesenem Stück).
  - Läuft eine Schlange trotzdem über, beendet der Server den Strom, und der Browser verbindet sich neu.
  - Der Browser baut die Verbindung selbst neu auf, wenn 10 s keine Daten kommen, auch nach einer
    Fehlantwort (mit wachsender Wartezeit bis 30 s).
  - Schreibversuche an einen hängenden Browser brechen nach 60 s ab, statt den Thread festzuhalten.
- `GET /api/sitzung` antwortet angemeldet mit 200 statt 404 (kein „Fehler … 404“ mehr im Journal).
- Angehaltenes oder hochgescrolltes Live-Log puffert höchstens 1500 Zeilen.

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
- Entwickler-Dashboard nach dem gemeinsamen Aufbau der Entwicklerdashboards.
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
