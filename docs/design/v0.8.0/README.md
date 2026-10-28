# Handoff: Runner-Monitor · Design 0.8.0 (anbieterunabhängig)

## Überblick
Der Runner-Monitor ist ein Live-Dashboard für selbst gehostete CI-Runner auf einer Linux-VM (Repo `Self-Hosted-Github-Runner-Monitor`: Python-Backend `runner_monitor/`, Oberfläche `web/` ohne Framework, Einrichtung `einrichten.sh`). Bisher kennt er nur GitHub Actions und genau einen Runner. Design 0.8.0 macht ihn **anbieterunabhängig**: Er erkennt auf der VM selbst, welche Runner laufen (GitHub, Forgejo, Gitea, GitLab, unbekannte), zeigt, wie sicher die Erkennung ist, und sagt je Fund, was zu tun ist. Auf einer VM können **mehrere Runner** laufen.

Dazu kommen: echter, zeitlich stabiler Verlauf mit Zeitraumwahl, Sprache Deutsch/Englisch, Fehler/Idee per E-Mail, breiteres Info-Blatt.

## Über die Design-Dateien
Die Dateien in diesem Ordner sind **Design-Referenzen in HTML**: Prototypen, die Aussehen und Verhalten zeigen, **kein Produktionscode**. Aufgabe ist, sie in der bestehenden Umgebung des Repos nachzubauen: `web/index.html`, `web/dashboard.js`, `web/*.css` (Vanilla JS, keine Inline-Styles nötig, keine Frameworks) und das Python-Backend. Die Demo-Daten (`web/demo.js`) sollen die neuen Zustände ebenfalls abbilden.

Öffnen: `Runner-Monitor 0.8.0.dc.html` im Browser (lokaler Webserver, z. B. `python3 -m http.server` im Ordner). Links alle Bildschirme, ‹ › oder Pfeiltasten blättern, unten links „Optionen“ (Zustand, Runner-Anzahl, gewählter Runner, Sprache, Thema …).

## Fidelity
**High-fidelity.** Farben, Typografie, Abstände, Texte und Interaktionen sind final. Pixelgenau nachbauen; alles, was 0.4.0 schon festlegt (Raster, Karten, Pillen, kv-Zeilen, Meldungen, Info-Blatt), bleibt unverändert.

## Feste Rahmen
- Dashboard: Desktop-Onepager ohne Scrollen bei 1440 × 900, wächst bis 1920 × 1080. Einrichtung und Anmeldung ab 390 px bedienbar.
- Kontrast AA hell und dunkel, `prefers-reduced-motion` beachten (Animationen → kurzes Einblenden oder aus).
- Dashboard neutral formulieren (nie „du“), Anmeldung und Einrichtung „Sie“.
- Keine Anbieter-Logos: Dienst als Text-Plakette im Label-Stil (`GitHub`, `Forgejo`, `Gitea`, `GitLab`, `unbekannt`).
- Nur neutrale Beispieldaten (VM `runner-vm`, `beispiel-org`, `git.example.org`, IPs aus 192.0.2.0/24).

---

## Bildschirme

### 1. Dashboard mit mehreren Runnern (Variante C: Reiter an der Runner-Spalte)
- **Was zur VM gehört** (für alle gleich): Auslastung (CPU, RAM, Netz, Last), Prozesse, Platten, Container.
- **Was zum gewählten Runner gehört:** Karte „Runner-Status“, Karte „Jobs je Repository“, Live-Log.
- **Reiter** direkt über „Runner-Status“ in der linken Spalte (400 px breit): Grid mit gleich breiten Spalten, `gap: 2px`, Höhe 48 px, Radius `4px 4px 0 0`, `margin-bottom: -12px` (stößt an die Karte, deren obere Ecken dann 0 Radius haben).
  - Zeile 1: Zustandspunkt 7 px + Name (13 px / 600, Ellipse). Zeile 2: Zustandstext (11,5 px / 550) in Zustandsfarbe.
  - Gewählt: Hintergrund `--surface-alt` (wie die Karte). Nicht gewählt: transparent, `box-shadow: inset 0 -1px 0 var(--border)`, Hover `color-mix(--surface-alt 55%, transparent)`.
  - Zustände und Farben: Job läuft `--brand`, Bereit `--success`, Gestoppt `--danger`, Offline `--warning`, Grundüberwachung „Dienst aktiv“ `--success`.
  - **Ab 4 Runnern:** drei Reiter (Index 0, 1 und der gewählte bzw. 2) + Reiter „+N“ (64 px) mit Zustandspunkten der übrigen. Klick öffnet eine Liste (320 px, rechtsbündig unter den Reitern, Schatten `0 8px 28px rgba(19,33,43,.16)`): je Zeile Punkt, Name, Plakette, Zustand. Klick wählt und schließt.
- **Kopfzeile** bleibt wie 0.4.0: VM-Name | Name des gewählten Runners + Labels; bei mehreren Runnern steht die Dienst-Plakette als erstes Label.
- **Live-Log**: neben dem Titel der Runner-Name (mono, 12 px, `--ink-muted`).
- **Ein Runner:** keine Reiter, keine zusätzlichen Bedienelemente – identisch mit 0.4.0.
- **Meldungen** in der Kopfzeile nennen bei mehreren Runnern den Runner: „runner-vm-02: Dienst gestoppt“. Betrifft die Meldung einen nicht gewählten Runner, heißt der Knopf „Anzeigen“ und wechselt zu ihm.
- **Wahl merken:** `localStorage["runner-monitor.runner"]` (Index bzw. besser Runner-ID).

### 2. „Nicht verfügbar“ ehrlich zeigen
Fähigkeiten je Anbieter: **Status, Jobs, Schritte, Logs, Updates**. Die Oberfläche richtet sich nach diesen Fähigkeiten, nicht nach dem Anbieternamen.
- **Grundüberwachung** (unbekannt oder noch nicht unterstützt): Runner-Status zeigt Zustand „Dienst aktiv“/„Dienst gestoppt“, Text „Nur Grundüberwachung: Dienst, Neustarts und Log. Jobs und Schritte sind ohne Anbindung an den Dienst nicht verfügbar.“, kv: Dienst (Unit · aktiv seit …), Neustarts, Letzter Stopp. Pille „Online bei …“ entfällt; „Letzte Jobs“ entfällt. „Jobs je Repository“ zeigt den ruhigen Leerzustand „Jobs nicht verfügbar“ mit Link „Runner zuordnen ›“. Live-Log zeigt das Journal der Unit (Chip „Journal · buildagent.service“), **ohne** Schritt-Trenner.
- **Teilweise** (Jobs ja, Schritte nein): Statt Schrittbalken „Aktueller Schritt / Schritte nicht verfügbar“ (gedämpft) + „Der Dienst meldet keine Schritte – Job und Laufzeit bleiben sichtbar.“; im Log keine Trenner, kein Schritt-Chip.
- Kartentitel einheitlich **„Jobs je Repository“** (statt „Workflows“).

### 3. Verlauf (CPU, RAM, Netz, Last) – wichtig
- **Zeitraum-Umschalter** im Kopf der Karte „Auslastung“ rechts neben der Meta-Zeile: Segment `30 s | 2 Min. | 5 Min. | 10 Min.` (Höhe 22 px, 12 px). Gilt für alle Verläufe der Karte. Gemerkt in `localStorage["runner-monitor.zeitraum"]` (Sekunden). Standard 10 Min.
- **Feste Zeitfenster:** Die Werte werden in Eimer fester Größe gruppiert, deren Grenzen am **absoluten** Messzeitpunkt hängen (Eimer = `floor(t / bs)`), nicht am Ende der Liste. Eimergröße: 30 s → 1 s, 2 Min. → 1 s, 5 Min. → 3 s, 10 Min. → 5 s. CPU/RAM/Last: Mittelwert je Eimer, Netz: Maximum je Eimer (Spitzen bleiben sichtbar).
- x-Position = Zeit: der letzte Wert liegt bei x = 100 % („jetzt“), der älteste bei 0. Jede Sekunde wandert die Kurve um eine Messung nach links, **nur der rechte Rand ändert sich** – so entsteht ein echter Verlauf statt eines „zuckenden“ Diagramms (bisheriger Fehler: Gruppierung vom Listenende aus verschob jede Sekunde alle Eimergrenzen).
- Weniger Messwerte als der Zeitraum (z. B. nach Neustart): vorhandene Werte über die ganze Breite, linke Achse „seit hh:mm“; sonst „vor 30 s“ / „vor 2 Min.“ / ….
- Netz-Skala: Spitze im gewählten Zeitraum, Untergrenze 64 KB/s; Achsenmitte „Spitze …“.
- Verlauf wird alle 10 s nach `/var/lib/runner-monitor/verlauf.json` gesichert und übersteht Neustarts (aus 0.4.0).
- aria-label der Diagramme mit Zeitraum: „CPU-Verlauf der letzten 2 Minuten“.

### 4. Info & Hilfe
- Blatt rechts, **890 px** breit (Goldener Schnitt von 1440 px: 61,8 %), innen zwei Spalten `minmax(0,1.618fr) minmax(0,1fr)`, Abstand 32 px.
  - Links: **Runner**, **Verbindungen**, **Was tun, wenn …**
  - Rechts: **Updates**, **Darstellung** (Modus + Sprache), **Über diesen Monitor**, **Fehler gefunden oder Idee?**
- **Runner:** Kopf „Runner“ + Knopf „Neu erkennen“ (Drehsymbol während der Suche, gesperrt). Statuszeile: „3 Runner erkannt · zuletzt heute 14:02, automatisch alle 6 Std.“ / „Suche Runner …“ / „Keine Änderung · geprüft um …“.
  - Je Runner: Punkt, Name, Plakette, Pille Einstufung (angebunden `ok`, Grundüberwachung neutral, noch nicht angebunden `warn`, neu gefunden `brand`, ignoriert neutral); kv: Server, Sicherheitsgrad (mit Erklärung), Unit, Letzte Erkennung; Links „Zuordnung ändern“, „Ignorieren“/„Wieder anzeigen“, „Zugangsdaten ändern“.
  - „Zuordnung ändern“: kleines Formular (Dienst-Auswahl GitHub/Forgejo/Gitea/GitLab/anderer, Anzeigename, systemd-Unit, Log-Pfad; leer = Journal). „Speichern“ übernimmt die Auswahl (Plakette/Einstufung ändern sich), „Abbrechen“ verwirft.
  - „Zugangsdaten ändern“: nur auf der VM – Text + Codeblock `sudo /opt/runner-monitor/aktuell/einrichten.sh zugang <runner>` mit „Kopieren“ + Link zur Anleitung.
  - Neuer Fund nach „Neu erkennen“: Hinweisleiste „1 neuer Runner gefunden: runner-vm-03 Gitea“ mit „Übernehmen“/„Ignorieren“; der Runner steht **sofort** in der Liste („neu gefunden“).
- **Verbindungen** (ersetzt „GitHub-Verbindung“): je angebundenem Dienst Titel (Plakette, Server/Organisation, Runner) + kv: Server, Organisation, Token, Rechte, Ablauf, Letzte/Nächste Abfrage, API-Kontingent, Token-Datei (`/etc/runner-monitor/zugang/<runner>.token`).
- **Was tun, wenn …** anbieterneutral: „Zugangsdaten einrichten oder erneuern“ (Unterpunkte GitHub · Forgejo/Gitea · GitLab), „Dienst nicht erreichbar (GitHub, Forgejo …)“, „Runner offline beim Dienst“, „Runner-Dienst gestoppt“ (Befehle mit der Unit des gewählten Runners).
- **Darstellung › Sprache:** Segment `Automatisch | Deutsch | English`. Automatisch = Systemsprache (`navigator.languages[0]`): beginnt mit `de` → Deutsch, **alles andere → Englisch**. Gemerkt in `localStorage["runner-monitor.sprache"]` (`auto|de|en`). Hinweis darunter: „„Automatisch“ folgt der Sprache des Systems. Andere Sprachen als Deutsch zeigen Englisch. Die Wahl gilt nur für diesen Browser.“
- **Fehler gefunden oder Idee?:** keine GitHub-Issues mehr. Text „Fehler und Wünsche gehen per E-Mail an info@bamberger-it-services.de …“. Knöpfe „Fehler melden“ und „Idee vorschlagen“ sind `mailto:`-Links mit Betreff und Vorlage (siehe unten). Hinweis: „Vor dem Absenden prüfen: Keine Tokens oder Passwörter mitschicken. Log-Ausschnitte nur gekürzt einfügen.“ Auch „Fehler melden“ beim fehlgeschlagenen Update ist ein `mailto:`.

E-Mail-Vorlagen (Sprache folgt der Oberfläche, Text URL-kodiert in `body`):
```
Betreff: Runner-Monitor 0.8.0 – Fehler
Hallo Bamberger IT Services,

im Runner-Monitor ist mir ein Fehler aufgefallen.

Was ist passiert?
…

Was hätte passieren sollen?
…

So lässt es sich nachstellen:
1. …
2. …

Technische Angaben (automatisch ergänzt):
Version: Runner-Monitor <version>
System: <os>, Python <py>
Runner: <name> (<dienst> <version>), …
Gewählt: <runner> · <zustand>
Browser: <navigator.userAgent>

Bitte keine Tokens oder Passwörter mitschicken.
```
„Idee“: Betreff „Runner-Monitor <version> – Idee“, Abschnitte „Worum geht es?“, „Warum wäre das hilfreich?“, Version. Update-Fehler: Betreff „Runner-Monitor – Update auf <neu> fehlgeschlagen“ mit Platz für `journalctl -u runner-monitor-update -n 50`.

### 5. Einrichtung im Browser (5 Schritte)
Stepper: **Code → Zugang → Runner → Anbinden → Fertig** (Kreise 24 px, Linien 32 px). Karte 880 px, Innenabstand 32/40/28, Inhalt scrollt in `.koerper`, Fuß unten.
- **Schritt 3 „Runner“:** Titel „Welche Runner laufen auf dieser VM?“, Einleitung, Werkzeugzeile „Neu erkennen“ + Status. Liste der Funde (Karte `--surface`, Rand `--border`, Radius 4, Innenabstand 14/16):
  - Kopf: Name (15/650), Plakette, Pille Sicherheitsgrad (sicher `ok`, wahrscheinlich `warn`, unklar neutral), rechts Stand (wird angebunden / Grundüberwachung / ignoriert / Entscheidung offen).
  - Meta: Server, Version, Einstufung. Aufklappbar „Begründung (n Merkmale)“ → Liste der Merkmale.
  - Handlung je Einstufung: *vollständig unterstützt* → Schalter „Übernehmen“ (an) + „Zugangsdaten im nächsten Schritt „Anbinden““. *erkannt, noch nicht unterstützt* → Hinweis „Nur Grundüberwachung: Dienst, CPU, RAM, Platte, Log, Neustarts. Jobs und Schritte fehlen.“ + Link „Wie ein Anbieter ergänzt wird ↗“ + Auswahl Grundüberwachung/Ignorieren. *unbekannt* → „Zuordnen“ (Formular: Dienst, Anzeigename, Unit, Log-Pfad) oder „Ignorieren“.
  - Leer: „Kein Runner gefunden“ mit drei Wegen: Runner einrichten (Befehl `sudo /opt/runner-monitor/aktuell/einrichten.sh runner` mit Kopieren), Von Hand zuordnen, Ohne Runner fortfahren (nur VM überwachen → direkt zu Schritt 5).
  - Fuß: Zusammenfassung „2 anbinden · 1 Grundüberwachung“.
- **Schritt 4 „Anbinden“:** je übernommenem, voll unterstütztem Runner ein Block (Plakette, Name, Server, „Überspringen – nur Grundüberwachung“). Links Felder + „Verbindung prüfen“ + Ergebnisliste (ok/warn/fehler), rechts Anleitung (3–5 Schritte + Link).
  - GitHub: Organisation, Fine-grained Token (Actions + Metadata read-only, optional Self-hosted runners).
  - Forgejo/Gitea: Server (aus Erkennung), Organisation oder Benutzer, Token (Lesen; genaue Rechte nach API-Prüfung).
  - GitLab: Server, Token (`read_api`).
  - **Nur ein Runner:** kein Block-Rahmen, Titel „GitHub anbinden“, Knopf „Ohne Anbindung fortfahren“ – wirkt wie 0.4.0.
- **Schritt 5 „Fertig“:** Zugang, Firewall, dann „Runner auf runner-vm“: je Runner Name, Plakette, Stand (angebunden / Grundüberwachung / ignoriert) + Detail.
- **390 px:** Stepper zeigt nur den aktiven Schritt mit Titel, Karte randlos, Formulare/Wege einspaltig, primärer Knopf füllt die Breite.

### 6. Einrichtungsskript (Terminal)
Abschnitt „Runner auf dieser VM“ in „System prüfen“, 80 Zeichen breit, ohne Farben lesbar:
```
Runner auf dieser VM
  ✓ runner-vm-01   GitHub    github.com/beispiel-org   2.338.1   sicher
  ✓ runner-vm-02   Forgejo   git.example.org           13.0      sicher
  ? buildagent     unbekannt –                         –         unklar
      Hinweise: Dienst buildagent.service, Name enthält „agent“, startet Container
      → Im Browser zuordnen oder ignorieren (Schritt „Runner“)
```
Ohne Fund: „! Kein Runner gefunden (geprüft: systemd-Units, Prozesse, .runner-Dateien).“ + Befehl für später + Frage „Jetzt einen Runner einrichten? [j/N]“ + Verweis auf den Browser.

---

## Datenmodell / Backend (Vorschlag)
Erkennung (`runner_monitor/erkennung.py`, neu): systemd-Units, Prozesse, `.runner`-Dateien, Server-API-Probe. Ergebnis je Fund:
```json
{ "id": "runner-vm-02", "name": "runner-vm-02", "dienst": "forgejo", "server": "https://git.example.org",
  "version": "13.0 / Runner 9.1", "grad": "sicher|wahrscheinlich|unklar", "merkmale": ["…"],
  "einstufung": "voll|teil|unbekannt", "stand": "angebunden|grund|ignoriert|offen",
  "unit": "forgejo-runner.service", "log": null,
  "faehig": { "status": true, "jobs": true, "schritte": true, "logs": true, "updates": false } }
```
- Anbieter als Adapter (`anbieter/github.py`, `forgejo.py` für Forgejo+Gitea, `gitlab.py`), gemeinsame Schnittstelle: Status, Jobs je Repository, aktueller Job + Schritte, Log-Quelle.
- Momentaufnahme `/api/zustand`: `vm` (Auslastung, Verlauf inkl. `verlauf.start`), `runner[]` (je Runner Status, Job mit `schritt: {nr, von|null, name}`, Letzte Jobs, Jobs je Repository, Log-Quelle), `meldungen[]` mit `runner`-ID.
- Zugangsdaten je Runner in `/etc/runner-monitor/zugang/<runner>.token` (nur root), gesetzt über `einrichten.sh zugang <runner>`.
- Zuordnung/Ignorieren aus der Oberfläche über einen POST-Endpunkt (nur angemeldet, CSRF-geschützt) in `/etc/runner-monitor/runner.json`.

## Übersetzung
`i18n-0.8.0.js` enthält das vollständige Wörterbuch Deutsch → Englisch (`EXAKT` für ganze Texte, `TEILE` für zusammengesetzte Texte, `MUSTER` für Zahlen/Zeiten, z. B. „vor 12 Min.“ → „12 min ago“, Dezimalkomma → Punkt, Wochentage). Im Design übersetzt das Skript die gerenderte Seite; **in der Umsetzung** bitte echte Schlüssel verwenden (z. B. `web/i18n/de.json`, `en.json`, `t('status.jobLaeuft')`) und die Texte aus dem Wörterbuch übernehmen. Code, Befehle und Log-Ausgabe werden nicht übersetzt.

## Design-Tokens
Hell:
`--surface #ffffff` · `--surface-alt #f6f6f6` · `--ink #13212b` · `--ink-muted #4f5d67` · `--border #d9dee2` · `--track #e2e6e9` · `--brand #0e628f` · `--on-brand #ffffff` · `--gold-ink #85602a` · `--success #1f7a4d` · `--danger #b3261e` · `--warning #9a4d00` · `--log-bg #0f1d27` · `--log-ink #dbe3e9` · `--log-muted #8796a2` · `--log-rule #2c3d4a` · `--mat rgba(255,255,255,.74)` · `--schatten 0 1px 2px rgba(19,33,43,.08), 0 8px 24px rgba(19,33,43,.10)`
Dunkel:
`--surface #0c1a24` · `--surface-alt #13283a` · `--ink #eef2f5` · `--ink-muted #a9b6c0` · `--border #2a3f50` · `--track #20384c` · `--brand #5aa9d6` · `--on-brand #0c1a24` · `--gold-ink #d6ad72` · `--success #5cc08a` · `--danger #f08a80` · `--warning #f0a35e` · `--log-bg #08131b` · `--log-rule #22333f` · `--schatten 0 8px 28px rgba(0,0,0,.45)`
Schrift: System-UI (`-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', system-ui, sans-serif`), Mono `ui-monospace, 'SF Mono', Menlo, Consolas`. Grundgröße 13/18, Kartentitel 13/650, Zustand 30/34/650, Zahlen tabellarisch. Radien: Karten 4 px, Knöpfe/Pillen/Plaketten 2 px. Plakette: Mono 11 px, Zeilenhöhe 16–18 px, Rand 1 px.
Bewegung: Einblenden 0,18–0,36 s `cubic-bezier(.22,1,.36,1)`; bei `prefers-reduced-motion` nur Opazität.

## Umsetzung als Forgejo-Issues (Reihenfolge)
1. Verlauf: feste Zeitfenster + Zeitraum-Umschalter (30 s/2/5/10 Min.), Netz-Maximum je Eimer.
2. i18n-Grundlage: Schlüssel, `de.json`/`en.json`, Sprache Automatisch/Deutsch/English.
3. Erkennung der Runner (Backend) + Ausgabe im Einrichtungsskript.
4. Anbieter-Adapter + Fähigkeiten; GitHub auf Adapter umbauen.
5. Forgejo/Gitea-Adapter (nach API-Prüfung; Tabelle „Fähigkeiten je Anbieter“ füllen).
6. Dashboard: mehrere Runner, Reiter, „+N“, Wahl merken, Meldungen mit Runner.
7. Grundüberwachung und „teilweise“ (Journal-Log, Leerzustände).
8. Einrichtung im Browser: Schritte „Runner“ und „Anbinden“, „Fertig“-Zusammenfassung, 390 px.
9. Info & Hilfe: 890 px zweispaltig, Abschnitte Runner und Verbindungen, neutrale Anleitungen.
10. Fehler/Idee per `mailto:` statt GitHub.
11. GitLab-Adapter.

## Dateien in diesem Ordner
- `Runner-Monitor 0.8.0.dc.html` – Spielplatz mit allen Bildschirmen und der Notiz „Design 0.8.0 · was ist neu“ (Einstieg).
- `Main 0.8.0.dc.html` – Dashboard inkl. Info & Hilfe (Live-Prototyp mit simulierten Daten).
- `Setup-Web 0.8.0.dc.html` – Einrichtung im Browser, 5 Schritte.
- `Setup-Skript 0.8.0.dc.html` – Terminal-Ausgabe von `einrichten.sh`.
- `Login 0.8.0.dc.html` – Anmeldung.
- `Dashboard-Varianten 0.8.0.dc.html` – Varianten A/B/C für mehrere Runner (gewählt: C).
- `i18n-0.8.0.js` – Wörterbuch Deutsch → Englisch.
- `support.js` – Laufzeit der Design-Dateien (nur zum Ansehen, nicht übernehmen).

Keine Bilder oder Logos; Symbole sind einfache Inline-SVGs (16er-Raster, Strich 1,5–1,7) und können wie in 0.4.0 übernommen werden.
