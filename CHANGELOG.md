# Änderungen

Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionen nach SemVer.

## [Unveröffentlicht]

### Behoben
- CI auf Forgejo (#133): Der Test „Live-Strom endet bei Überlauf“ sendete feste 2100 Nachrichten; auf einem
  langsamen Runner las der Server schnell genug mit, die Schlange lief nie über, und der Test lief in eine
  Zeitüberschreitung. Er sendet jetzt, bis die Schlange überläuft. Das Programm ist unverändert.

## [0.8.1] – 29.10.2026

### Behoben
- Release-Paket auf GitHub: Der Release-Workflow brach bei 0.8.0 vor dem Paketbau ab, weil
  `test_platte_ohne_runner` die echte Platte des Build-Rechners maß. Für 0.8.0 gibt es deshalb kein
  Paket auf GitHub; 0.8.1 ist inhaltlich 0.8.0 plus diese Korrekturen.
- gitleaks über die ganze Historie: Fehlalarm für ein erfundenes Test-Token (`.gitleaksignore`,
  Testwert ohne `glpat-`-Präfix).
- CI „pruefen“ für den Forgejo-Runner angepasst (#133; auf GitHub grün, auf Forgejo noch offen). Der Forgejo-Runner (act-Image) unterscheidet sich von GitHubs
  Rechnern: Schritte laufen als root, bash mit `pipefail`, ohne shellcheck und ohne UTF-8-Locale.
  `test_platte_ohne_runner` maß die echte Platte des Testrechners (grün nur, wenn dort < 25 GB frei
  sind) und misst jetzt nicht mehr; der Flut-Test des Journal-Folgers las `_neu` ohne Sperre und sah
  sporadisch 201 statt höchstens 200 Zeilen (Grenze im Programm unverändert); shellcheck wird als
  root ohne sudo aus dem Ubuntu-Archiv installiert, läuft mit `C.UTF-8`, und die gewollten deutschen
  Anführungszeichen in `einrichten.sh` sind von SC1111 ausgenommen; „Paket baut“ bricht nicht mehr
  an `tar … | head` (SIGPIPE unter `pipefail`) ab und prüft zusätzlich die SHA-256-Prüfsumme.

## [0.8.0] – 29.10.2026

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
- Anbieter-Adapter: Status, Jobs je Repository, aktueller Job mit Schritten und Log-Quelle kommen
  über eine gemeinsame Schnittstelle mit Fähigkeiten (`status`, `jobs`, `schritte`, `logs`, `updates`);
  GitHub ist der erste Adapter, unverändert im Verhalten, andere Dienste laufen in der Grundüberwachung.
  `GET /api/zustand` liefert die Momentaufnahme mit den bisherigen Bereichen und zusätzlich `vm`,
  `runner[]` und `meldungen[]` (mit Runner-ID); `/events` schickt zusätzlich `runner` und `meldungen`.
  Die Oberfläche nutzt die neuen Felder ab #94 (#92, E-19, ADR-0006).
- Dashboard für mehrere Runner: Über „Runner-Status“ stehen Reiter (Name, Zustandspunkt und Zustand als
  Text), ab vier Runnern drei Reiter und „+N“ mit einer Liste der übrigen, per Tastatur bedienbar. Runner-Status,
  Jobs je Repository und Live-Log gehören zum gewählten Runner, Auslastung, Prozesse und Platten zur VM. Die Kopfzeile
  zeigt Name und Dienst-Plakette des gewählten Runners, das Live-Log seinen Namen; Meldungen nennen den
  Runner („runner-vm-02: Dienst gestoppt“) und führen mit „Anzeigen“ zu einem anderen Runner. Die Wahl wird
  je Browser unter `runner-monitor.runner` (Runner-ID) gemerkt. Mit einem Runner bleibt die Ansicht wie
  bisher. Die Karte „Workflows“ heißt jetzt „Jobs je Repository“. Runner ohne Jobs (Grundüberwachung) zeigen
  vorerst nur den Dienst; die ausführliche Darstellung folgt mit #95. Demo: `?demo&runner=1` bis `5` (#94).
- Zugangsdaten je Runner in `/etc/runner-monitor/zugang/<runner>.token` (nur root), gesetzt mit
  `sudo /opt/runner-monitor/aktuell/einrichten.sh zugang <runner>` (#92).
- GitLab-Adapter: Status, aktueller Job, letzte Jobs und laufende Jobs je Projekt eines GitLab-Runners
  über die GitLab-REST-API (Token mit Bereich `read_api`, nur lesend, ohne Weiterleitungen). Ehrlich
  „nicht verfügbar“: Schritte und wartende Jobs (die API liefert sie nicht). Anleitung unter
  Einrichtung › „GitLab anbinden“ und im Runbook `gitlab-nicht-erreichbar`; der Sammler ruft den Adapter
  seit #115 auf (von Hand angebunden), ausgeliefert bleibt GitLab bis #96 „teil“. Das Token geht nur über `https://`
  (`http://` nur mit `"http_erlaubt": true` in `runner.json`) (#99, E-20, E-21).
- Grundüberwachung und „teilweise“ ehrlich zeigen: Runner ohne Anbindung zeigen „Dienst aktiv“ bzw.
  „Dienst gestoppt“, den Hinweis „Nur Grundüberwachung“, Dienst (Unit · aktiv seit …), Neustarts
  (automatische Neustarts laut systemd) und den letzten Stopp; „Jobs je Repository“ zeigt ruhig „Jobs nicht
  verfügbar“ mit „Runner zuordnen ›“. Das Live-Log zeigt für diese Runner das Journal ihrer Unit (Chip
  „Journal · <unit>“, ohne Schritt-Trenner), nur für angemeldete Benutzer, bekannte Token-Muster werden
  ersetzt. Liefert ein Dienst Jobs, aber keine Schritte, steht „Schritte nicht verfügbar“; Job, Laufzeit und
  „Letzte Jobs“ bleiben. Die Oberfläche richtet sich dabei nur nach den Fähigkeiten, nie nach dem Namen des
  Dienstes. Demo: `?demo&runner=3&gewaehlt=3` und `?demo&faehig=teilweise` (#95).
- Forgejo-/Gitea-Adapter nach API-Prüfung: Wer einen Forgejo- oder Gitea-Runner von Hand anbindet
  (Server und Organisation in `/etc/runner-monitor/runner.json`, Token mit `read:repository` und
  `read:organization`), sieht, ob der Runner beim Server online ist, Jobs je Repository, den laufenden
  Job mit Schritten (Forgejo ab 17, Gitea) und die letzten Jobs; ohne Anbindung bleibt es bei Dienst
  und Journal, ausgeliefert gelten Forgejo und Gitea weiter als Grundüberwachung, bis Einrichtung (#96)
  und Sammler (#115) sie anbinden (E-23). Token nur über `https://` (`http://` nur mit
  `"http_erlaubt": true`, E-21). Der Sammler fragt in einem eigenen Faden, nur lesend, ohne
  Weiterleitungen und mit harter Frist je Anfrage; Ergebnis ohne Token in
  `/run/runner-monitor/anbieter.json`. Die API-Prüfung steht als Tabelle „Fähigkeiten je Anbieter“ in
  `docs/FUNKTIONSWEISE.md`, die Anleitung in `docs/EINRICHTUNG.md`. Gitea ist nach der
  OpenAPI-Beschreibung umgesetzt und noch nicht an einer laufenden Instanz geprüft (#93).
- Einrichtung im Browser in fünf Schritten (Design 0.8.0): **Code → Zugang → Runner → Anbinden → Fertig**.
  Im Schritt „Runner“ stehen alle gefundenen Runner mit Dienst, Sicherheitsgrad, Begründung und Stand; je
  Fund übernehmen, Grundüberwachung, zuordnen (Dienst, Anzeigename, Unit, Log-Pfad) oder ignorieren, dazu
  „Neu erkennen“ und ohne Fund drei Wege (Runner einrichten, von Hand zuordnen, nur die VM überwachen). Die
  Wahl speichert der Sammler in `/etc/runner-monitor/runner.json`. „Anbinden“ zeigt je übernommenem Runner
  einen Block; der GitHub-Runner wie bisher mit Organisation und Token (mit nur einem Runner sieht der Schritt
  aus wie in 0.7), alle anderen mit dem Befehl `einrichten.sh zugang <runner>` (E-22). „Fertig“ fasst den
  Stand je Runner zusammen. Ab 390 px bedienbar (#96).
- „Verbindung prüfen“ ohne eingegebenes Token prüft das auf der VM hinterlegte GitHub-Token über den
  Sammler; bei einem angebundenen Forgejo-/Gitea-Runner (Server und Organisation in `runner.json`) ebenso (#96).
- Sammler fragt alle angebundenen Runner ab: Forgejo, Gitea und jetzt auch GitLab (Server in
  `/etc/runner-monitor/runner.json`, keine Organisation nötig) – je Runner ein eigener Faden, höchstens
  vier zugleich, mit Frist je Runde (Adapter 25 s, Sicherheitsnetz 35 s). Ein hängender oder tröpfelnder
  Server verzögert weder GitHub, Docker und Updates noch die anderen Runner; je Runner läuft höchstens
  eine Runde. Fehler (nicht erreichbar, Token ungültig, keine Rechte) erscheinen als Meldung mit Runner
  und Dienst („GitLab nicht erreichbar“, „Forgejo-Token ungültig oder abgelaufen“, „Pausiert bei GitLab“); ein neu
  angebundener Runner zeigt bis zur ersten Abfrage „Wird abgefragt …“ statt „Kein Token“ (E-25). Bei einem Fehler
  bleibt der letzte gute Stand nur für denselben Server und dasselbe Token stehen. Ausgeliefert bleiben
  Forgejo, Gitea und GitLab als „teil“, bis die Einrichtung im Browser sie anbindet (#96, E-20, E-23) (#115).
- `sudo /opt/runner-monitor/aktuell/einrichten.sh zugang <runner>` bindet Forgejo-, Gitea- und GitLab-Runner
  ohne Handarbeit an. Das Skript fragt Server (`https://`; `http://` nur nach ausdrücklicher Rückfrage, dann
  `"http_erlaubt": true`), Organisation (nicht bei GitLab) und Token ab. Es prüft streng mit denselben
  Regeln wie der Monitor, schreibt `runner.json` atomar (andere Felder bleiben) und das Token nach
  `zugang/<runner>.token`. Danach prüft es die Verbindung nur lesend, mit klarer Antwort (Verbindung in
  Ordnung, Token ungültig, keine Rechte, Server nicht erreichbar, Server nicht gefunden). Ändert sich die
  Adresse eines Runners mit Token, verlangt es ein neues Token; das bisherige geht nie an die neue
  Adresse. Ein Stand „Grundüberwachung“ aus der Einrichtung lässt sich dabei aufheben. Von Hand geht
  es weiterhin (#120, E-26).
  Hinweis: Ein Token, das bisher ohne Server in `zugang/` lag, wird beim ersten Lauf mit Server neu
  abgefragt und das alte verworfen. Eine im Browser noch nicht übernommene Auswahl „Grundüberwachung“ kann
  den aufgehobenen Stand wieder setzen.
- Info & Hilfe nach Design 0.8.0: Blatt 890 px mit zwei Spalten (links Runner, Verbindungen, Was tun, wenn …; rechts
  Updates, Darstellung, Über diesen Monitor, Fehler oder Idee). „Runner“ listet alle Runner mit Dienst, Einstufung,
  Server, Sicherheitsgrad, Unit und letzter Erkennung, mit „Neu erkennen“, „Zuordnung ändern“, „Ignorieren“ / „Wieder
  anzeigen“ und der Hinweisleiste bei einem neuen Fund (über die vorhandenen Endpunkte, nur angemeldet); „Zugangsdaten
  ändern“ zeigt nur den Befehl `einrichten.sh zugang <runner>`, nie ein Token-Feld (E-18, E-22). „Verbindungen“ ersetzt
  „GitHub-Verbindung“ und zeigt je angebundenem Dienst nur, was der Zustand hergibt. „Was tun, wenn …“ ist
  anbieterneutral (Zugangsdaten für GitHub, Forgejo/Gitea und GitLab, Dienst nicht erreichbar, Runner offline beim
  Dienst, gestoppt, Logs) und nennt die Unit des gewählten Runners (#97).
- „Was tun?“, Kartenfuß und leerer Zustand gelten für den Dienst des Runners (Forgejo, Gitea, GitLab statt GitHub). Bei
  einem Ausfall zeigt die Karte das Alter des letzten guten Stands; nach 10 Minuten steht „Zustand unbekannt“ statt eines
  Jobs, der stundenlang „läuft“ (#123).

### Behoben
- Sicherheitsbericht S-JOURNAL-01: Restrisiko dokumentiert, dass ein Job „Running job“, „completed with result“ und
  Verbindungsmeldungen im Runner-Journal vortäuschen kann (nur Anzeige); `_PID` kommt aus Kernel-Absenderdaten,
  `_COMM` allein ist nicht vertrauenswürdig. Kein geändertes Verhalten (#130).
- Dienst gestartet/gestoppt zählt im GitHub-Journal nur noch, wenn das Feld `UNIT` der Unit des überwachten
  Runners entspricht; stoppt systemd einen zweiten Runner auf der VM, erscheint es nicht mehr beim ersten (#131).
- Dienst gestartet/gestoppt erkennt der Monitor im Journal des GitHub-Runners nur noch an Meldungen von
  systemd selbst (`_COMM=systemd` und `_PID=1`), nicht mehr am `SYSLOG_IDENTIFIER`, den ein Job setzen
  kann; ein Job kann so keinen „Dienst gestoppt“ mehr vortäuschen (#119, S-JOURNAL-01).
- Reiter und Karte zeigen für einen Runner ohne systemd-Dienst beide „Kein Dienst“ (der Reiter zeigte
  „Unbekannt“) (#95, Review #114).
- GitLab: Ein Job mit `status` als Liste oder Objekt ließ die ganze Runde als „unerwartete Antwort“
  ausfallen; jetzt fehlt nur dieser Job (#115).
- Dashboard lud nicht (Syntaxfehler in `web/dashboard.js` seit dem Review zu #90: ein Zeilenkommentar
  schluckte eine schließende Klammer; Hotfix #112). Ein neuer Test prüft alle Skripte in `web/` (`tests/js/demo.test.mjs`).

### Einmalig nach dem Update
- Nichts zu tun: Das bestehende GitHub-Token wird beim Start nach dem Update nach
  `/etc/runner-monitor/zugang/<runner>.token` kopiert; `/etc/runner-monitor/github-token` bleibt als
  Rückfall bestehen (#92).

### Geändert
- Forgejo und GitLab gelten als vollständig unterstützt (Einstufung „voll“): Forgejo mit Status, Jobs, Schritten
  und Logs, GitLab mit Status, Jobs und Logs (die GitLab-API hat keine Schrittliste). In der Einrichtung lassen
  sich solche Runner übernehmen und über `einrichten.sh zugang` anbinden; Gitea bleibt „teil“
  (Grundüberwachung), bis der Adapter an einem echten Server geprüft ist. „Verbindung prüfen“ nennt bei
  GitLab den Dienst und keine Organisation; der Hinweis im Schritt „Anbinden“ beschreibt, dass der Befehl
  Server, Organisation (nicht bei GitLab) und Token abfragt; fehlt bei GitLab der Server, meldet die Prüfung
  nur „Server fehlt“ statt „Server und Organisation fehlen“. Ein weiterer GitHub-Runner (nicht der des
  Monitors) bekommt im Schritt „Anbinden“ wieder den allgemeinen Hinweis statt des GitLab-Texts
  (#126, E-20, E-23, E-27).
- Handbuch, Funktionsweise und Bildschirmfotos auf Design 0.8.0: Kapitel zu mehreren Runnern (Reiter, „+N“,
  Grundüberwachung), Zeitraum der Auslastung, Sprache, Info › Runner und Verbindungen, Fehler/Idee per E-Mail
  und `einrichten.sh zugang <runner>`; neue Bilder (`dashboard-mehrere-runner`, `dashboard-grundueberwachung`,
  `info-runner`, `dashboard-englisch`), alle übrigen neu aufgenommen (`node werkzeuge/bilder.mjs`, nur Demo-Daten);
  `docs/design/README.md` vollständig auf 0.8.0 abgeglichen (#101).
- CI: Prüfungen laufen auch bei Pull Requests nach `develop` und bei Push auf `develop`/`main`;
  shellcheck wird bei Bedarf nachinstalliert, davor `bash -n` (#108).
- Ein Token nimmt die Weboberfläche nur noch in der Einrichtung an (gültiger Einrichtungscode), nicht mehr
  mit einer Anmeldung; danach nur auf der VM mit `einrichten.sh zugang <runner>` bzw. `einrichten.sh token`.
  Aufträge der Oberfläche (auch `github-token`) liest der Sammler nur noch als reguläre Datei ohne Symlink
  (#96, E-22, Sicherheitsbericht S-EINR-01).
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
