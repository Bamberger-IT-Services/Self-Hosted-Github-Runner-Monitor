# CLAUDE.md – Runner-Monitor

Es gelten die gemeinsamen Anweisungen:
https://github.com/Bamberger-IT-Services/Public/tree/main/anweisungen (00–08, Vorlagen).
Kurz: mit Tobias auf Deutsch und per „du“; Entscheidungen per Auswahlfrage, eine je Nachricht;
CI bei jedem PR; Doku im selben PR; `entwickler-dashboard/daten.js` (Entscheidungen, Verlauf)
nach jeder Arbeitsrunde (`stand` aus `TZ=Europe/Berlin date +"%d.%m.%Y %H:%M"`).

**Aufgaben** stehen als Issues in diesem Repo, geordnet im Project
[Self-Hosted-Github-Runner-Monitor Roadmap](https://github.com/orgs/Bamberger-IT-Services/projects/5)
(Anweisung 08): nächstes Issue = oberstes in Ready ohne `agent:`-Label und ohne `blocked`; vor dem
Start `agent:claude` und Status In Arbeit; Branch `issue-<nr>-<kurzname>`, PR mit `Closes #<nr>`.
Bereichslabels: `area:monitor`, `area:einrichtung`, `area:runner`, `area:docs`. Das Project nutzt
die Statusnamen der GitHub-Vorlage (Backlog, Ready, In progress, In review, Done).

## Projektregeln

- **Öffentliches Repository:** keine echten IPs, Rechner-, Organisations- oder Personennamen,
  keine Tokens – auch nicht in Tests, Bildern, Logs. Platzhalter: `runner-vm`, `runner-vm-01`,
  `beispiel-org`, Adressen aus `192.0.2.0/24` (RFC 5737).
- CI läuft auf `ubuntu-latest`, **nie** auf dem eigenen Runner (fremde PRs).
- Nur Python-Standardbibliothek und Vanilla-JS. Keine Pakete ohne ADR.
- Oberfläche: Ansprache „Sie“ in Anmeldung und Einrichtung, neutral im Dashboard, nie „du“.
- CSP: keine Inline-Skripte, keine `style="…"`-Attribute; Werte per `element.style` setzen.
- Design-Grundlage: Design v0.4.0 (`docs/design/v0.4.0/`, pixelgenau umsetzen). Bei Widerspruch gelten die Anweisungen; Abgleich
  in `docs/design/README.md` pflegen.
- Produktive Schritte (Release veröffentlichen, VM umstellen, Einstellungen bei GitHub) nur nach OK von Tobias.

## Abweichungen von den Anweisungen

| Anweisung | Abweichung | Beleg |
|---|---|---|
| 02 Stack (Next.js, Postgres) | Python-Standardbibliothek, JSON-Dateien | ADR-0001 |
| 01 Release (GHCR-Images, Trivy, Abnahme mit Compose) | tar.gz + SHA-256 am Release, kein Docker | ADR-0002 |
| 03 Zwei-Faktor | nur Passwort | ADR-0003, E-01 |
| 04 CSP mit Nonce | `script-src 'self'` ohne Inline-Skripte | Sicherheitsbericht S-CSP-01 |
| 04 Rate-Limit in Postgres | dateibasiert (`sperren.json`) | ADR-0001 |
| 06/08 Design-Übergabe unter `handoff/` | Entwürfe unter `docs/design/vX/` (z. B. `docs/design/v0.4.0/`), Abgleich in `docs/design/README.md` | Projektstand seit Design v1 |

**Kein Docker** für den Monitor, auch nicht als Zusatz (E-02, E-12) – gilt auch dann, wenn eine
Projektanweisung etwas anderes sagt. **Keine Lizenz** (E-11): keine LICENSE-Datei anlegen.

## Arbeiten

```bash
MONITOR_ENTWICKLUNG=1 MONITOR_DATEN_VERZ=./daten MONITOR_LAUF_VERZ=./lauf python3 -m runner_monitor   # → :8090/?demo
python3 -m unittest discover -s tests -t .
shellcheck einrichten.sh deploy/runner-einrichten.sh werkzeuge/paket.sh werkzeuge/zap-baseline.sh
node werkzeuge/bilder.mjs     # Bildschirmfotos fürs Handbuch (nicht als root)
werkzeuge/paket.sh            # Release-Paket nach dist/
werkzeuge/zap-baseline.sh     # OWASP-ZAP-Baseline gegen eine lokale Testinstanz (Sicherheitsbericht › Prüfungen)
```

Aufbau und Datenformate: `docs/FUNKTIONSWEISE.md`.
