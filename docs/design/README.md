# Design

**Stand: 23.10.2026 · Design v0.4.0**

**Design v0.4.0** – aus Claude Design, Grundlage für Version 0.4.0. Die Dateien liegen in
[`v0.4.0/`](v0.4.0/) (`*.dc.html`, Design-Canvas-Format, mit `support.js`), die Umsetzungshinweise
in [`v0.4.0/Umsetzung 0.4.0.md`](v0.4.0/Umsetzung%200.4.0.md):

| Datei | Inhalt |
|---|---|
| `Runner-Monitor 0.4.0.dc.html` | Übersicht aller Bildschirme mit Notiz „Was ist neu“ und Optionen (Zustand, GitHub, Netzwerk-Variante, Kerne, Log, Update, Info-Blatt, **Schrittliste**, **Verlaufslänge**) |
| `Main 0.4.0.dc.html` | Dashboard als Live-Prototyp inkl. Info & Hilfe |
| `Setup-Skript 0.4.0.dc.html` | Ausgabe von `einrichten.sh` |
| `Setup-Web 0.4.0.dc.html` | Einrichtung im Browser, Schritte 1–4 |
| `Login 0.4.0.dc.html` | Anmeldung |
| `ds/bamberger-it-services/tokens.json` | Designsystem „Bamberger IT Services“ |

Öffnen: die `.dc.html` im Browser (lädt React von unpkg.com). Ältere Fassungen liegen nur noch in
den Tags: Design v0.3.0 in [`v0.3.1`](https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/tree/v0.3.1/docs/design/v0.3.0),
Design v1 in [`v0.1.2`](https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/tree/v0.1.2/docs/design/v1).
Bildschirmfotos aus dem Betrieb, die zum Entwurf gehörten, liegen bewusst nicht im Repository
(öffentlich, echte Daten).

Grundlage: Designsystem „Bamberger IT Services“ (Farben, Radien), Schrift = Systemschrift,
Bewegung nach Apple-Prinzipien (kritisch gedämpfte Federn, `prefers-reduced-motion`).
Farben und Maße: [TOKENS.md](TOKENS.md).

Planung nach Anweisung 08: Epic [#42 „Design v0.4.0 umsetzen“](https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/issues/42).

## Was 0.4.0 gegenüber 0.3.0 ändert

1. **Verlauf füllt die ganze Breite** ([#43](https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/issues/43)):
   CPU, RAM und Netz strecken die vorhandenen Werte über die volle Fläche; links steht „vor 10 Min.“
   bei vollem Verlauf, sonst „seit hh:mm“. Der Server sichert den Verlauf alle 10 s, er übersteht
   Neustarts und Updates des Monitors.
2. **Job-Schritte überall gleich** ([#44](https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/issues/44)):
   Karte, Log-Kopf und Trenner zeigen denselben Schritt aus einer Quelle; der Segmentbalken steht
   immer. Fehlt die Liste von GitHub noch: „3 von –“, Name gedämpft, Rest gestrichelt; die Zahl
   springt nie zurück.
3. Versionsnummern in Anmeldung, Skript und Info-Blatt ([#45](https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/issues/45)).
   Sonst unverändert gegenüber 0.3.0 (Setup-Web identisch).

Was 0.3.0 gegenüber v1 geändert hat, steht unten und gilt weiter.

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

| Bildschirm (0.4.0) | Code | Stand | Bemerkung |
|---|---|---|---|
| Auslastung: Verlauf über die volle Breite, „seit hh:mm“, Sicherung | `runner_monitor/zustand.py`, `web/dashboard.js` | umgesetzt | #43 (PR #47) |
| Job: Schritt aus einer Quelle, „3 von –“, gestrichelter Rest, Log „Schritt 3/–“ | `runner_monitor/zustand.py`, `web/dashboard.js` | umgesetzt | #44 (PR #48) |
| Versionsnummern | Doku, Release | umgesetzt | #45 |

Abgleich mit Design 0.8.0 (Verlauf, Runner-Erkennung):

| Bildschirm (0.8.0) | Code | Stand | Bemerkung |
|---|---|---|---|
| Auslastung: Zeitraum-Umschalter 30 s / 2 / 5 / 10 Min., feste Eimergrenzen, Netz-Maximum, Skala nach Spitze im Zeitraum, aria-label mit Zeitraum | `web/verlauf.js`, `web/dashboard.*`, `web/stil.css`, `web/i18n.js`, `tests/js/verlauf.test.mjs` | umgesetzt | #89; Gruppierung nicht mehr vom Listenende; Wahl in `localStorage["runner-monitor.zeitraum"]` |
| Info › „Fehler gefunden oder Idee?“: keine GitHub-Issues mehr, `mailto:` an info@bamberger-it-services.de (Fehler melden, Idee vorschlagen) mit Betreff, Vorlage und automatischen Angaben, Hinweis ohne Tokens/Passwörter; „Fehler melden“ beim fehlgeschlagenen Update | `web/mail.js`, `web/dashboard.js`, `web/i18n.js`, `tests/js/mail.test.mjs` | umgesetzt | #98; Sprache der Vorlage folgt der Oberfläche; Abweichungen: „Runner“/„Gewählt“ zeigen nur den einen erkannten Runner (Zustand Job/Bereit/Gestoppt/Offline), bis die Mehrfach-Runner-Ansicht da ist; die Update-Mail enthält zusätzlich die Zeile „Meldung:“ des Aktualisierers und keinen Schlusssatz (wie im Entwurf); Token-Muster werden aus den Angaben entfernt; Knopf „Fehler melden“ beim Update-Fehler als `a.knopf` in der Zeile neben „Erneut versuchen“ (Zeilenklasse `.upd-aktion.zeile` statt Inline-Stil, wegen CSP); Issue-Vorlagen für Fehler/Ideen entfernt (E-15) |
| 6. Einrichtungsskript: Abschnitt „Runner auf dieser VM“ (mehrere Runner, kein Runner); Datenmodell › Erkennung | `runner_monitor/erkennung.py`, `runner_monitor/sammler.py`, `einrichten.sh`, `tests/test_erkennung.py` | umgesetzt | #91; Spalten wie im Design. Abweichung: die Hinweiszeile im Design ist 82 Zeichen lang und wird bei 80 umbrochen. Zusätzlich `!` für „wahrscheinlich“ mit Grund und „Dienst gestoppt“. Spalte „Version“: bei GitHub die Runner-, sonst die Server-Version, ohne Server-Version „–“. Fund-Format wie im README plus `aktiv`, `grund`. `runner.json` schreibt seit #96 der Sammler auf Auftrag der Einrichtung (Info › Runner: #97) |
| 2. „Nicht verfügbar“ ehrlich zeigen (Fähigkeiten); Datenmodell › Adapter, Momentaufnahme `/api/zustand`, Zugangsdaten je Runner | `runner_monitor/anbieter/` (`__init__.py`, `github.py`, `token.py`), `runner_monitor/zustand.py`, `runner_monitor/server.py`, `runner_monitor/sammler.py`, `einrichten.sh`, `web/demo.js`, `tests/test_anbieter.py` | Backend umgesetzt, Oberfläche folgt | #92, E-19, ADR-0006; Format additiv: `vm`, `runner[]` (mit `faehig`, `status`, `job.schritt {nr, von|null, name}`, `letzteJobs`, `jobsJeRepository`, `log {art, unit}` ohne Pfade) und `meldungen[]` (mit `runner`-ID) neben den bisherigen Bereichen, die Oberfläche stellt mit #94 um. Abweichungen: `/api/zustand` gab es vorher nicht (nur die Momentaufnahme in `/events`), jetzt als `GET` ohne Live-Log; Meldungen ohne Texte (Art und Werte, Texte im Browser), Meldungen zu Verbindung und Update bleiben im Browser; Token-Datei `zugang/<id>.token`, alter Ort `github-token` bleibt als Rückfall bis #94/#96; `einrichten.sh zugang <runner>` ohne Angabe zeigt die erkannten Runner |
| 5. Einrichtung › Schritt 4 „Anbinden“ (GitLab: Server, Token `read_api`); Datenmodell › Adapter `gitlab.py` | `runner_monitor/anbieter/gitlab.py`, `runner_monitor/erkennung.py` (Fähigkeiten), `docs/EINRICHTUNG.md`, `docs/runbooks/gitlab-nicht-erreichbar.md`, `tests/test_gitlab.py` | Backend umgesetzt, Oberfläche folgt | #99; Fähigkeiten `status`, `jobs`, `logs`, nicht `schritte` (die GitLab-API hat keine Schrittliste) und keine wartenden Jobs (`wartetUnbekannt`). Der Sammler ruft den Adapter mit #94/#96 auf; die Eingabe von Server und Token im Browser baut #96, bis dahin `einrichten.sh zugang`. Einstufung bleibt „teil“ und `FAEHIG[gitlab]` Grundüberwachung (E-20), bis die Anbindung da ist und die Unsicherheiten (Rollen für `/runners`, Feld `project.name`) gegen einen echten GitLab-Server bestätigt sind (FUNKTIONSWEISE › GitLab-Adapter) |
| 1. Dashboard mit mehreren Runnern (Variante C): Reiter an der Runner-Spalte, „+N“ ab 4 Runnern, Wahl in `localStorage["runner-monitor.runner"]`, Dienst-Plakette, Runner-Name im Live-Log, Meldungen mit Runner und „Anzeigen“; Kartentitel „Jobs je Repository“ | `web/runner.js`, `web/dashboard.*`, `web/stil.css`, `web/demo.js`, `web/i18n.js`, `tests/js/runner.test.mjs`, `tests/js/demo.test.mjs` | umgesetzt (Teil) | #94; im Browser gegen `Main 0.8.0.dc.html` geprüft (1440 × 900, hell und dunkel, 1, 3 und 5 Runner, Tastatur). Abweichungen: Tab-Muster mit Wahl bei Fokuswechsel (Pfeile), `+N` als eigener Knopf neben der Tab-Liste; Runner ohne Jobs und Journal je Runner seit #95 (nächste Zeile); Texte „Online/Offline bei {Dienst}“ nach dem Dienst des Runners |
| 2. „Nicht verfügbar“ ehrlich zeigen – Oberfläche: Grundüberwachung (Dienst aktiv/gestoppt, kv Dienst · aktiv seit, Neustarts, Letzter Stopp, ohne „Online bei …“ und „Letzte Jobs“; „Jobs nicht verfügbar“ mit „Runner zuordnen ›“; Live-Log = Journal der Unit mit Chip „Journal · <unit>“, ohne Trenner) und „teilweise“ („Schritte nicht verfügbar“, keine Trenner, kein Schritt-Chip) | `runner_monitor/journal.py`, `runner_monitor/runner.py` (`NRestarts`, `InactiveEnterTimestamp`), `runner_monitor/anbieter/__init__.py`, `runner_monitor/zustand.py`, `runner_monitor/server.py` (`/events?journal=<runner-id>`), `web/runner.js`, `web/dashboard.js`, `web/stil.css`, `web/demo.js`, `web/i18n.js`, `tests/test_journal.py`, `tests/js/runner.test.mjs`, `tests/js/demo.test.mjs` | umgesetzt | #95; im Browser gegen „buildagent · Grundüberwachung“, „Grundüberwachung · dunkel“ und „Teilweise · Job ohne Schritte“ geprüft (1440 × 900, hell und dunkel; Kartenmaße gleich dem Entwurf). Steuerung nur über `faehig{…}` (Test). Abweichungen: Neustarts aus `NRestarts` („keine“ / „{n} automatisch“ – zählt automatische Neustarts seit dem letzten Start von Hand, nicht „in den letzten 7 Tagen“ wie im Entwurf, E-24); Ereigniszeile im Journal-Modus zeigt nur „Dienst gestartet/gestoppt“ aus dem Journal (der Entwurf zeigt dort die Job-Ereignisse des GitHub-Runners); „Runner zuordnen ›“ öffnet vorerst Info & Hilfe (Zuordnung ändern: #97); ohne Unit „Kein Dienst“ auch im Reiter (statt „Unbekannt“, Review #114); Log-Datei aus `runner.json` noch nicht angezeigt (Hinweis) |
| Spielplatz › Notiz „Fähigkeiten je Anbieter“; 2. „Nicht verfügbar“ (teilweise); 5. Einrichtung › Schritt 4 (Forgejo/Gitea: Token-Rechte); Datenmodell › `forgejo.py` für Forgejo und Gitea | `runner_monitor/anbieter/forgejo.py`, `runner_monitor/anbieter/__init__.py`, `runner_monitor/erkennung.py`, `runner_monitor/sammler.py`, `runner_monitor/zustand.py`, `tests/test_forgejo.py`, `tests/daten/`, `docs/FUNKTIONSWEISE.md`, `docs/EINRICHTUNG.md` | Backend umgesetzt, Oberfläche: Zustände „Job nicht zuordenbar“ und „Zustand unbekannt“ | #93, E-21, E-23; ausgeliefert weiter „teil“/Grundüberwachung bis #96/#115; API-Prüfung an Forgejo 17.0.1 und nach OpenAPI (Forgejo 16, Gitea), Tabelle in FUNKTIONSWEISE.md › „Fähigkeiten je Anbieter“ und in der Notiz des Spielplatzes ausgefüllt. Abweichungen: Schritt 4 im Browser gibt es noch nicht (#96/#97) – Server und Organisation stehen bis dahin von Hand in `runner.json`, das Token kommt über `einrichten.sh zugang`; genaue Token-Rechte `read:repository` + `read:organization` (Runner-Liste nur für Besitzer der Organisation) statt „repository und organization Lesen“; Live-Log weiter aus dem Journal (ohne Schritt-Trenner), obwohl die API Logs je Schritt liefert (eigenes Issue); „Updates“ bleibt nicht verfügbar |
| 5. Einrichtung im Browser: Stepper Code → Zugang → Runner → Anbinden → Fertig (Kreise 24 px, Linien 32 px), Karte 880 px mit `.koerper`; Schritt 3 „Runner“ (Fundkarten, Begründung, Übernehmen / Grundüberwachung / Ignorieren / Zuordnen, Leerzustand mit drei Wegen, „Neu erkennen“, Fuß mit Zusammenfassung); Schritt 4 „Anbinden“ (Block je Runner, „Verbindung prüfen“ mit Ergebnisliste, Anleitung rechts, ein Runner ohne Rahmen); Schritt 5 „Fertig“ mit Stand je Runner; 390 px; Datenmodell › POST-Endpunkt für Zuordnung/Ignorieren | `web/einrichtung.*`, `web/einrichtung-runner.js`, `web/stil.css`, `web/i18n.js`, `runner_monitor/einrichtung.py`, `runner_monitor/server.py`, `runner_monitor/sammler.py`, `werkzeuge/bilder.mjs`, `tests/test_einrichtung_runner.py`, `tests/js/einrichtung.test.mjs` | umgesetzt | #96, E-22; im Browser gegen `Setup-Web 0.8.0.dc.html` geprüft (1440 × 900 und 390 px, hell und dunkel, Deutsch und Englisch). Abweichungen: Forgejo/Gitea/GitLab-Blöcke ohne Token- und Organisationsfeld – Server nur als Vorschlag (lesend) und Befehl `einrichten.sh zugang <runner>` (E-22); Token-Feld nur für den GitHub-Runner des Monitors; „Verbindung prüfen“ für einen angebundenen Forgejo-/Gitea-Runner (Server und Organisation in `runner.json`, #93) über den Sammler und `anbieter.json`, sonst ehrlich „Server und Organisation fehlen“ bzw. „noch nicht verfügbar“; `einrichten.sh zugang` legt bisher nur das Token ab (Server/Organisation: #120); Forgejo/Gitea/GitLab erscheinen bis zu ihrer Anbindung als „erkannt, noch nicht unterstützt“ (E-16, E-20), die Entwurfsansicht mit Forgejo-Block wurde mit einem nachgestellten Fund geprüft; Merkmale der Begründung kommen deutsch vom Server und werden (wie Log-Ausgabe) nicht übersetzt; Hinweis in „Fertig“ verweist auf die VM statt auf „Info & Hilfe › Runner“ (folgt mit #97); im Fuß bei 390 px steht die Zusammenfassung über den Knöpfen, damit „Weiter“ die Breite füllt; Codeblock mit den Log-Tokens (`--log-bg`) statt fester Farben; Server in der Fundkarte bei GitHub ohne `https://` wie im Entwurf, sonst vollständig; Link „Wie ein Anbieter ergänzt wird ↗“ führt zu `docs/FUNKTIONSWEISE.md` |
| 1. Dashboard mit mehreren Runnern › Meldungen mit Runner; 2. „Nicht verfügbar“ (GitLab ohne Schritte); Datenmodell › Sammler fragt alle Adapter ab | `runner_monitor/sammler.py`, `runner_monitor/anbieter/gitlab.py`, `runner_monitor/anbieter/__init__.py`, `runner_monitor/zustand.py`, `web/dashboard.js` (nur Meldungen), `web/i18n.js`, `einrichten.sh`, `tests/test_sammler_anbieter.py` | Backend umgesetzt, Oberfläche: Meldungstexte je Dienst | #115, E-20, E-23; je Runner ein Faden (höchstens 4 zugleich, Frist je Runde), GitLab im Sammler. Abweichung: das Design zeigt Meldungen nur für GitHub – für Forgejo, Gitea und GitLab steht der Dienst im Titel („GitLab nicht erreichbar“, „Forgejo-Token ungültig oder abgelaufen“), englisch analog, eigene Texte (nicht aus `i18n-0.8.0.js`). Ausgeliefert weiter „teil“/Grundüberwachung, bis #96 die Anbindung in der Einrichtung bringt (dann FAEHIG/EINSTUFUNG anheben, Gitea erst nach Prüfung an einem echten Server) |

Abgleich mit Design 0.3.0 (gilt weiter):

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

- Bei vielen Laufwerken scrollt die Plattenliste innerhalb der Karte – so belassen (Issue #24
  nicht geplant).
- Docker-Container werden gesammelt, aber nicht angezeigt; eine Anzeige ist nicht geplant (E-05,
  Issue #22 vom Projektinhaber geschlossen).
- **Sprachumschalter auf Anmeldung und Einrichtung** (#81, ohne Entwurf): ein Textknopf mit der
  jeweils anderen Sprache („English“/„Deutsch“) – auf der Anmeldeseite in der Fußzeile, in der
  Einrichtung rechts in der Kopfzeile.
- **Sprache** (#80, #90; Design 0.8.0): In Info › Darstellung steht unter „Modus“ samt Hinweis eine
  zweite Zeile „Sprache“ mit dem Segment „Automatisch | Deutsch | English“, darunter der Hinweis
  aus dem Design. Gemerkt in `localStorage["runner-monitor.sprache"]` (`auto|de|en`; der alte
  Schlüssel `rm-sprache` wird übernommen); „Automatisch“ folgt `navigator.languages[0]` (`de…` →
  Deutsch, sonst Englisch). Abweichung vom Design (Entscheidung E-14): Texte bleiben in
  `web/i18n.js` mit dem deutschen Text als Schlüssel statt `de.json`/`en.json`; die englischen
  Texte der vorhandenen Oberfläche folgen dem Wörterbuch `i18n-0.8.0.js`. Die Demo-Leiste bleibt
  deutsch.
- **Nacht-Update vorgemerkt** (#77, ohne Entwurf): Unter „Automatisch aktualisieren“ steht bei
  Bedarf eine Notiz im Stil `info-notiz` („Update auf X vorgemerkt …“ bzw. „nächster Versuch in der
  kommenden Nacht“).
- **Änderungen seit der installierten Version** (#78, Erweiterung von „Neu in X“): Bei mehreren
  Versionen heißt der Kasten „Neu seit X · n Versionen“, die neueste steht offen, ältere sind
  einklappbar (`details`). „Einmalig nach dem Update“ steht als Kasten mit gelbem Rand über den
  Punkten der Version.
- **Grund eines gestoppten Dienstes** (#68, ohne Entwurf): Die Status-Karte „Dienst gestoppt“ hat
  eine zusätzliche Zeile „Grund“ (z. B. „Speicher voll (OOM-Killer)“) im vorhandenen kv-Stil, die
  Meldung oben nennt die Ursache vor „Jobs bleiben in der Warteschlange“. Im nächsten Design
  bitte mit aufnehmen. Demo: `?demo&zustand=gestoppt&grund=oom-kill`.
