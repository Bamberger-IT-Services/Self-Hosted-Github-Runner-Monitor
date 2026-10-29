# Sicherheitsbericht

**Stand: 29.10.2026 · Version 0.7.0 (0.8.0 in Arbeit)** · gegliedert nach OWASP ASVS 4.0 (Anweisung 04)

Einsatzrahmen: ein Monitor im **lokalen Netz** einer Runner-VM, ein Zugang, nur lesend.
Erreichbar über HTTP auf Port 8090, die Firewall-Regel des Einrichtungsskripts lässt nur das
eigene Netz zu.

## Befundliste

| ID | Befund | Schwere | Status | Datum |
|---|---|---|---|---|
| S-NET-01 | Kein HTTPS: Passwort und Sitzungs-Cookie gehen im LAN unverschlüsselt; Cookie ohne `Secure`, kein HSTS | mittel | akzeptiert für den LAN-Betrieb. Für Zugriff von außen: Reverse-Proxy mit TLS nach [HTTPS.md](../HTTPS.md), dazu `MONITOR_HTTPS=1` (Cookies mit `Secure`, HSTS) – Issue #17 | 23.10.2026 |
| S-AUTH-01 | Keine Zwei-Faktor-Anmeldung (Abweichung von Anweisung 03) | mittel | akzeptiert, [ADR-0003](../adr/0003-nur-passwort.md) / E-01 | 23.10.2026 |
| S-AUTH-02 | Liste gesperrter Passwörter war kurz (20 Einträge statt der 10 000 häufigsten) | niedrig | behoben: 10 000 häufigste aus SecLists (MIT) plus eigene Ergänzungen, auch mit angehängten Ziffern/Zeichen (Issue #16) | 23.10.2026 |
| S-HOST-01 | Jobs laufen als `github-runner` mit `sudo` ohne Passwort und in der Gruppe `docker` – faktisch root. Ein bösartiger Workflow kann das GitHub-Token des Monitors lesen und den Monitor verändern | hoch (Eigenschaft der Runner-VM, nicht des Monitors) | akzeptiert: Token nur lesend und kurzlebig; Runner nur für eigene, private Repositories, nie für Pull Requests aus Forks | 23.10.2026 |
| S-CSP-01 | CSP ohne Nonce/`strict-dynamic` (Anweisung 04 verlangt sie); stattdessen streng `script-src 'self'` ohne Inline-Skripte | niedrig | akzeptiert – gleich streng, da keine Inline-Skripte und keine fremden Quellen | 23.10.2026 |
| S-UPD-01 | Updates wurden nur per SHA-256 aus demselben Release geprüft. Wer das Repository oder den Release-Prozess übernimmt, kann ein Update ausliefern | mittel | behoben ab 0.6: GitHub-Attestierung des Pakets, Prüfung mit `gh attestation verify` gegen Repository und Release-Workflow ([ADR-0005](../adr/0005-herkunft-per-github-attestierung.md), Issue #18); ohne GitHub-CLI auf der VM weiter nur Prüfsumme, mit `MONITOR_UPDATE_HERKUNFT=pflicht` dann kein Update | 23.10.2026 |
| S-ZAP-01 | Ohne JavaScript schickte das Anmeldeformular Benutzername und Passwort per GET in der Adresse (ZAP-Regel 10024) – landet in Verlauf und Proxy-Logs | niedrig | behoben: Formular mit `method="post"` (Issue #20) | 23.10.2026 |
| S-HTTP-01 | Wurde ein POST vor dem Lesen des Körpers abgelehnt (Herkunft, Inhaltstyp, Größe), blieb der Körper in der Verbindung und wurde als nächste Anfrage gelesen; Fehlerseiten der Standardbibliothek (kaputte Anfragezeile, unbekannte Methode) kamen ohne Sicherheits-Kopfzeilen | niedrig | behoben: Verbindung wird dann geschlossen (`Connection: close`), alle Fehler als JSON mit CSP und den übrigen Kopfzeilen (Issue #20) | 23.10.2026 |
| S-DOS-01 | Ein angemeldeter Browser konnte beliebig viele SSE-Verbindungen öffnen (Threads) | niedrig | behoben: höchstens 6 Live-Verbindungen je Sitzung, weitere bekommen 429 (Issue #19); hängende Verbindungen enden nach 60 s, übergelaufene Warteschlangen beenden den Strom (seit 0.3.1) | 23.10.2026 |
| S-ERK-01 | Runner-Erkennung (#91) läuft als root und wertet Unit-Dateien, `/proc` und `.runner`-Dateien aus – auch solche, die ein Benutzer der VM anlegen kann (`/home/*`). Ohne Schutz könnte er so eine Server-Abfrage des Sammlers an eine Adresse seiner Wahl auslösen, den Sammler mit einem langsamen Server oder DNS aufhalten, über Symlinks root-Dateien lesen lassen oder mit einem nachgemachten Fund die ID und Zuordnung eines echten Runners übernehmen | niedrig | behandelt (Review #107): nichts aus einem Fund wird ausgeführt; keinem Symlink gefolgt außer bei Unit-Dateien, `lstat` vor dem Öffnen, `O_NOFOLLOW`/`O_NONBLOCK`/`O_NOCTTY`, Größengrenzen; Tokens nie übernommen; Namen, Units, Pfade, Adressen nach festen Mustern; Bei Funden mit Unit-Datei zählen für Name, Server und Dienst nur Registrierungen aus der Unit (ein Job-Prozess mit `exec -a` oder eigener `--config` ist nur Merkmal, #109); Server-Probe nur für Funde mit systemd-Unit (E-17), GET auf feste Pfade ohne Zugangsdaten und Weiterleitungen, harte Fristen 3 s/10 s in eigenem Faden (auch DNS), höchstens 8 Server; Erkennung im Sammler als eigener Prozess mit 60 s Grenze, Ergebnis geprüft; IDs zuerst an Funde mit Unit, Funde ohne Unit nie „angebunden“, Adapter nehmen Server und Log-Pfad nie aus dem Fund (E-18); Steuerzeichen in der Textausgabe ersetzt. Offen: `PrivateDevices=yes` für den Sammler (möglich, noch nicht auf der VM erprobt) | 29.10.2026 |
| S-ADAPTER-01 | Anbieter-Adapter und Zugangsdaten je Runner (#92): neue Angriffsfläche durch mehrere Tokens (`/etc/runner-monitor/zugang/<runner>.token`), die Übernahme des alten Tokens, Adapter-Eingaben aus `erkennung.json` und `runner.json` und den neuen Endpunkt `GET /api/zustand`. Risiken: ein Fund lenkt einen Adapter mit Token an einen fremden Server oder auf eine fremde Datei; eine Runner-ID wird zum Pfad (`../`); ein Symlink in `zugang/` lässt root eine fremde Datei als Token lesen; die Übernahme überschreibt ein neueres Token; Tokens gelangen in die Momentaufnahme; viele Funde lösen viele `systemctl`-Aufrufe aus | niedrig | behandelt: Server, Organisation, Log-Pfad und Token-Datei nur aus der Konfiguration (`konfig.env`, `einstellungen.json`, `runner.json`, `zugang/`), nie aus dem Fund (E-18); GitHub-Server fest; IDs nur `a-z 0-9 . _ -` ohne Punkt/Minus am Anfang, höchstens 64 Zeichen; `zugang/` root 0700 (Besitzer und Art geprüft, kein Symlink), Dateien 0600, atomar geschrieben, gelesen nur regulär ohne Symlink bis 4 KB; Übernahme als Kopie über `os.link`, eine vorhandene Kopie wird nur ersetzt, wenn der alte Ort neuer und anders ist (atomar), alter Ort bleibt; nach einem Schreibfehler wird die veraltete Kopie entfernt und das ohne Token gemeldet (Review #111); `runner[].log` ohne Pfade der VM; `erkennung.json` wird im Monitor erneut geprüft, Unit-Namen vor jedem `systemctl` erneut geprüft, höchstens 20 Runner, Dienststatus der Grundüberwachung höchstens alle 10 s; `/api/zustand` nur angemeldet und `no-store`, enthält dieselben Daten wie `/events` und nie Tokens; Kommandozeile für `einrichten.sh` gibt nur die ID aus, das Token nie (auch nicht als Argument). Restrisiko: Der Dateiname des GitHub-Tokens folgt dem `agentName` in `.runner`, den der Runner-Benutzer (also jeder Workflow, S-HOST-01) ändern kann – dann liest der GitHub-Adapter eine andere vorhandene Token-Datei oder fällt auf den alten Ort zurück und schickt sie an `api.github.com`; ein fremder Server ist dabei nie möglich. Offen bis #94/#96: zwei Orte für das GitHub-Token (Rückfall) | 29.10.2026 |
| S-GITLAB-01 | GitLab-Adapter (#99): Der Sammler (root) schickt ein Token an einen Server aus der Konfiguration und liest Antworten eines fremden Dienstes. Risiken: Weiterleitung des Servers lenkt das Token an eine fremde Adresse; unverschlüsseltes `http://`; riesige, falsche oder tröpfelnde Antworten; Token im Ergebnis, Journal oder in der Adresse; Token mit zu vielen Rechten | niedrig | behandelt: Server nur aus der Konfiguration (nie aus dem Fund, E-18), Adresse über `erkennung.pruefe_url` bereinigt (ohne Zugangsdaten, Abfrage, Anker); Token nur in der Kopfzeile `PRIVATE-TOKEN`, nie in der Adresse; Klient folgt keiner Weiterleitung (3xx = Fehler); nur `GET`; Token nur über `https://`, `http://` nur mit ausdrücklichem `"http_erlaubt": true` in `runner.json` (E-21) und dann ohne Proxy aus der Umgebung; Antwort höchstens 4 MB, harte Gesamtfrist 15 s je Anfrage (Daemon-Faden), `NaN`/`Infinity`, falsche Typen und Wertebereiche werden abgelehnt (Runde = Fehler „unerwartete Antwort“); Token aus `zugang/<id>.token`, nie aus dem alten GitHub-Ort; Fehlertexte, Ergebnis und `runner[]` enthalten nie das Token (Test); ein Token ohne `read_api`/`api` wird als „keine Rechte“ gemeldet, empfohlen ist `read_api`. Restrisiko: Wer `http_erlaubt` setzt, schickt das Token unverschlüsselt durchs Netz; Antworten eines kompromittierten GitLab-Servers erscheinen als Anzeigetext (Namen von Projekten und Jobs; die Oberfläche maskiert sie) | 29.10.2026 |
| S-JOURNAL-01 | Journal je Unit im Live-Log (#95): Der Monitor startet `journalctl` für Units anderer Runner und schickt deren Ausgabe an den Browser. Risiken: eine Unit aus der Anfrage oder aus einem Fund wird zum Argument (`--help`, Pfade); die Ausgabe eines fremden Dienstes enthält Geheimnisse (Tokens, Kopfzeilen); viele Fenster oder Units erzeugen viele Prozesse; eine Flut von Zeilen oder riesige Zeilen legen Browser oder Server lahm; ein Programm gibt sich im Journal als systemd aus; `journalctl`-Prozesse bleiben liegen | niedrig | behandelt: nur angemeldet (wie `/events`); die Anfrage nennt nur die Runner-ID, die Unit kommt aus `runner[]` des Servers (Fähigkeit `logs`, Quelle `journal`, Name nach `erkennung.pruefe_unit`, Units nur aus root-eigenen systemd-Verzeichnissen, E-17/E-18) und wird als `--unit=<name>` ohne Shell übergeben; je Unit ein `journalctl`, geteilt von allen Fenstern, höchstens 4 Units gleichzeitig, Prozess endet mit dem letzten Fenster (`terminate`, nach 2 s `kill`), Neustart nach 5 s ab dem letzten Cursor; je Zeile 4000 Zeichen, je Rohzeile 64 KiB, je Nachricht 200 Zeilen (Rest als Lücke gezählt), 500 Zeilen Stand; Steuerzeichen außer Farben entfernt, Ausgabe im Browser über `esc()`; bekannte Token-Muster (GitHub, GitLab, 40 Hex-Zeichen, `Authorization: …`) werden durch `***` ersetzt; „Dienst gestartet/gestoppt“ nur aus Meldungen mit `_COMM=systemd` und `_PID=1` (von journald gesetzt). Restrisiko: Der Token-Filter erkennt nur bekannte Muster – Passwörter oder eigene Geheimnisse eines Dienstes, die er ins Journal schreibt, sieht jeder angemeldete Benutzer (wie auf der VM jedes Mitglied der Gruppe `systemd-journal`) | 29.10.2026 |
| S-FORGEJO-01 | Forgejo-/Gitea-Adapter (#93): der root-Sammler schickt ein weiteres Token an einen selbst betriebenen Server und wertet dessen Antworten aus. Risiken: das Token geht an eine fremde Adresse (Adresse aus einem Fund, Weiterleitung des Servers, Zugangsdaten oder Abfrage in der Adresse); das Token geht mit `http://` unverschlüsselt durchs Netz; ein übernommener oder fehlerhafter Server hält den Sammler auf, schickt riesige Antworten oder Namen mit `../`, die als Pfad der nächsten Anfrage dienen; ein Workflow oder ein zweiter Runner mit gleichem Namen gibt sich als dieser Runner aus | niedrig | behandelt: Server und Organisation nur aus `runner.json` (root, 0640), nie aus dem Fund (E-18); Adressen mit Zugangsdaten, Abfrage oder Anker werden verworfen; nur GET, **keiner Weiterleitung gefolgt** (urllib würde den `Authorization`-Kopf sonst mitnehmen; Test mit zweitem Server); Token nur über `https://`, `http://` nur mit ausdrücklichem `"http_erlaubt": true` in `runner.json` und dann ohne Proxy aus der Umgebung (E-21); harte Frist 10 s je Anfrage in einem Daemon-Faden (auch DNS, tröpfelnde Antworten; stückweises Lesen), 25 s je Runde, die ganze Abfrage in einem eigenen Faden neben dem Takt des Sammlers (Test: tröpfelnder Server, `ein_takt` unter 1 s); Antworten höchstens 4 MB, `NaN`/`Infinity` abgelehnt, Werte nach Typ geprüft, unerwartete Form = „unerwartete Antwort“ mit letztem gutem Stand; vom Job-Log nur die ersten 4 KB (`Range`), ausgewertet nur per festem Muster; Repository-Namen nach Muster geprüft und jeder Pfadteil vollständig kodiert, IDs nur als Zahl; Fehlertexte ohne Token; Ergebnis `anbieter.json` 0644 ohne Token; ein Fehler bei einem Dienst hält GitHub, Docker und Updates nicht auf; höchstens 20 Runner. Die Zuordnung eines Jobs zum Runner (UUID bzw. Name in der ersten Log-Zeile, die der Runner vor jedem Schritt schreibt) beeinflusst nur die Anzeige. Akzeptiert: `http://` nur mit `http_erlaubt` (Token im Klartext im LAN); Zertifikate nur über die Systemablage. Die Runner-Liste zeigen Forgejo und Gitea nur Besitzern der Organisation: Das empfohlene eigene Konto im Team „Owners“ hat damit **volle Rechte** an der Organisation (wer sein Passwort hat, kann alles ändern) – das Token selbst bekommt nur Leserechte (`read:repository`, `read:organization`), deshalb das Konto mit starkem Passwort und ohne weitere Nutzung führen. **Offen für #96/#97:** Wer `runner.json` über die Oberfläche schreiben lässt, darf den Server eines Runners mit vorhandenem Token nicht ohne neues Token ändern können – sonst ginge das Token an eine Adresse nach Wahl der Oberfläche | 29.10.2026 |

Lücken melden: vertraulich über GitHub (Security › Report a vulnerability), siehe
[SECURITY.md](../../SECURITY.md).

## V1 Architektur

- Trennung nach Rechten: Webserver unprivilegiert (`runner-monitor`, systemd-Härtung
  `ProtectSystem=strict`, `NoNewPrivileges`, keine Capabilities); GitHub-Token, Docker und
  Installation nur in root-Diensten, die eng umrissene Aufträge annehmen ([FUNKTIONSWEISE](../FUNKTIONSWEISE.md)).
- Keine Fremdabhängigkeiten (Python-Standardbibliothek, Vanilla-JS) → keine Lieferkette außer Python/Ubuntu.

## V2 Anmeldung

- scrypt (N = 2¹⁵, r = 8, p = 1, 16 Byte Salz), Vergleich in konstanter Zeit.
- 12–128 Zeichen, keine Zusammensetzungsregeln, Sperrliste und Benutzername gesperrt (NIST 800-63B).
- Sperre: 5 Fehlversuche je Konto bzw. 30 je IP in 15 Minuten → 5 Minuten.
- Fehlermeldung verrät nicht, ob der Benutzer existiert.
- Ersteinrichtung nur mit Einrichtungscode von der VM (Besitznachweis), 60 min, 10 Versuche,
  als SHA-256 gespeichert, nach Abschluss gelöscht; danach ist die Einrichtung gesperrt.

## V3 Sitzungen

- 256-Bit-Zufallstoken, gespeichert nur als SHA-256. Cookie `HttpOnly`, `SameSite=Strict`, `Path=/`.
- 12 h, mit „Angemeldet bleiben“ 30 Tage; 7 Tage Inaktivität beenden jede Sitzung.
- Abmelden löscht die Sitzung serverseitig; Passwort zurücksetzen beendet alle Sitzungen.

## V4 Zugriff

- Ein Zugang, alles nur lesend. Ändernde Aktionen: Update starten, Auto-Update schalten, abmelden.
- `GET /api/zustand` (seit #92) und das Journal je Unit (`/events?journal=<runner-id>`, seit #95, S-JOURNAL-01)
  nur angemeldet, wie `/events`; Zugangsdaten je Runner lassen sich im
  Dashboard weder ansehen noch ändern, nur auf der VM mit `sudo einrichten.sh zugang <runner>` (S-ADAPTER-01).
- Ohne Anmeldung erreichbar: Anmeldung, Einrichtung (nur mit Code), statische Dateien und `/api/health`. Seit 0.3.0 nennt `/api/health` neben der Version auch den Namen der VM (die Anmeldeseite zeigt ihn, Design 0.3.0) – im LAN hinter ufw unkritisch.

## V5 Eingaben

- POST nur JSON, höchstens 16 KB. Organisation und Token mit festen Mustern geprüft.
- Alle Ausgaben im Browser über `esc()`; ANSI-Log wird in Textknoten zerlegt, kein HTML aus Logs.
- Runner-Erkennung: Funde (Unit-Dateien, Befehlszeilen, `.runner`, `config.toml`) gelten als
  feindliche Eingabe – nur gelesen und geprüft, nie ausgeführt; `systemctl`/`journalctl` nur mit
  geprüftem Unit-Namen als eigenem Argument (S-ERK-01, [FUNKTIONSWEISE](../FUNKTIONSWEISE.md)).
- Anbieter-Adapter: `erkennung.json` und `runner.json` gelten im Monitor erneut als Eingabe (Form,
  Größe, Muster); Ziele von Anfragen und Log-Pfade kommen nie aus einem Fund (S-ADAPTER-01).
- Journal je Unit: Runner-ID aus der Anfrage nur nach Muster, die Unit nur aus `runner[]` des Servers,
  Ausgabe begrenzt und um bekannte Token-Muster bereinigt (S-JOURNAL-01).

## V7 Fehler und Protokoll

- Fehlerantworten enthalten nur Text und eine Fehler-ID, keine Stacktraces oder Pfade.
- Tokens und Passwörter werden nie protokolliert.

## V8 Daten

- `/var/lib/runner-monitor` 0750, Dateien 0600; Token-Datei root 0600; `/etc/runner-monitor/zugang/`
  root 0700 mit `<runner>.token` 0600 (seit #92, der alte Ort `github-token` bleibt bis #94/#96).

## V9 Kommunikation

- Zu GitHub nur HTTPS mit Zertifikatsprüfung der Standardbibliothek. Zum Browser HTTP (S-NET-01).
- Zu Forgejo/Gitea (#93) HTTPS mit Zertifikatsprüfung oder – wenn `runner.json` es so nennt – HTTP im
  lokalen Netz; keine Weiterleitungen, nur GET (S-FORGEJO-01).

## V10 Schadcode / Updates

- Update-Hilfsdienst lädt nur von `https://github.com/<release-repo>/releases/download/`,
  Adresse aus root-eigener Datei, prüft SHA-256, entpackt nur reguläre Dateien und Ordner
  (keine Links, kein `..`), automatischer Rückweg (S-UPD-01).

## V13/V14 HTTP und Konfiguration

- Header: CSP `default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none';
  object-src 'none'; base-uri 'self'; form-action 'self'`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`, `X-Frame-Options: DENY`,
  `Cache-Control: no-store`.
- CSRF: `Origin` muss zum `Host` passen, dazu `SameSite=Strict`.
- Nicht benötigte HTTP-Methoden → 405.
- Entwicklungsmodus (ohne Anmeldung) nur auf 127.0.0.1 erlaubt; der Dienst verweigert sonst den Start.

## Prüfungen

| Wann | Was | Ergebnis |
|---|---|---|
| jeder PR | Unit-Tests inkl. Header, CSRF, Weiterleitungen, Einrichtung, Anmeldung, Entpacken; gitleaks | CI; seit 25.10.2026 Pflicht für `main` (Branch-Schutz: nur per PR, Checks `pruefen (3.10)`, `pruefen (3.12)`, `geheimnisse`; Issue #21) |
| 23.10.2026 | Abnahme auf der Test-VM (Issue #14) | erledigt |
| 23.10.2026 · 0.6.0 | OWASP ZAP 2.17.0 Baseline (nur passive Regeln) gegen eine lokale Testinstanz, ohne und mit Anmeldung (Issue #20) | S-ZAP-01 und S-HTTP-01 behoben; danach nur noch die zwei unten bewerteten Hinweise |

### ZAP-Baseline wiederholen

Nur gegen eine lokale Testinstanz, nie gegen die produktive VM:

```bash
# Testinstanz (eigener Datenordner, nicht als root), Zugang anlegen, dann starten
export MONITOR_DATEN_VERZ=./zap/daten MONITOR_LAUF_VERZ=./zap/lauf MONITOR_RUNNER_VERZ=./zap/runner MONITOR_ADRESSE=127.0.0.1 MONITOR_PORT=8091
python3 -c "from runner_monitor import konfig, zugang; k=konfig.lade(); zugang.Zugang(k.zugang_datei, k.sitzungen_datei, k.sperren_datei).lege_an('pruefer', '<testpasswort>')"
python3 -m runner_monitor &
werkzeuge/zap-baseline.sh <zap-ordner> http://127.0.0.1:8091 ./zap/ohne
werkzeuge/zap-baseline.sh <zap-ordner> http://127.0.0.1:8091 ./zap/mit "rm_sitzung=<cookie einer Testanmeldung>"
```

Bewertete Hinweise (Stand 0.6.0):

| ZAP-Regel | Fundstelle | Bewertung |
|---|---|---|
| 10202 Absence of Anti-CSRF Tokens (mittel, Konfidenz niedrig) | Anmeldeformular | akzeptiert: CSRF-Schutz über `Origin`-Prüfung, `SameSite=Strict` und nur JSON-Körper; ein fremdes Formular bekommt 403/415. Ein Token im Formular brächte nichts dazu |
| 10109 Modern Web Application (Info) | Dashboard | nur ein Hinweis für den Spider, kein Befund |
