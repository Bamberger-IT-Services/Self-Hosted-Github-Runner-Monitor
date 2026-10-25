# Sicherheitsbericht

**Stand: 25.10.2026 · Version 0.7.0** · gegliedert nach OWASP ASVS 4.0 (Anweisung 04)

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
- Ohne Anmeldung erreichbar: Anmeldung, Einrichtung (nur mit Code), statische Dateien und `/api/health`. Seit 0.3.0 nennt `/api/health` neben der Version auch den Namen der VM (die Anmeldeseite zeigt ihn, Design 0.3.0) – im LAN hinter ufw unkritisch.

## V5 Eingaben

- POST nur JSON, höchstens 16 KB. Organisation und Token mit festen Mustern geprüft.
- Alle Ausgaben im Browser über `esc()`; ANSI-Log wird in Textknoten zerlegt, kein HTML aus Logs.

## V7 Fehler und Protokoll

- Fehlerantworten enthalten nur Text und eine Fehler-ID, keine Stacktraces oder Pfade.
- Tokens und Passwörter werden nie protokolliert.

## V8 Daten

- `/var/lib/runner-monitor` 0750, Dateien 0600; Token-Datei root 0600.

## V9 Kommunikation

- Zu GitHub nur HTTPS mit Zertifikatsprüfung der Standardbibliothek. Zum Browser HTTP (S-NET-01).

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
