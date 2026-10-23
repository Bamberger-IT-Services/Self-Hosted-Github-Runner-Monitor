# Sicherheitsbericht

**Stand: 23.10.2026 · Version 0.3.0** · gegliedert nach OWASP ASVS 4.0 (Anweisung 04)

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
| S-UPD-01 | Updates werden nur per SHA-256 aus demselben Release geprüft, nicht signiert. Wer das Repository oder den Release-Prozess übernimmt, kann ein Update ausliefern | mittel | offen (Issue #18: Signatur mit Sigstore/minisign) | 23.10.2026 |
| S-DOS-01 | Ein angemeldeter Browser konnte beliebig viele SSE-Verbindungen öffnen (Threads) | niedrig | behoben: höchstens 6 Live-Verbindungen je Sitzung, weitere bekommen 429 (Issue #19); hängende Verbindungen enden nach 60 s, übergelaufene Warteschlangen beenden den Strom (seit 0.3.1) | 23.10.2026 |

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
| jeder PR | Unit-Tests inkl. Header, CSRF, Weiterleitungen, Einrichtung, Anmeldung, Entpacken; gitleaks | CI |
| vor 0.1.0 | Abnahme auf einer Test-VM (Issue #14), OWASP ZAP Baseline (Issue #20) | offen |
