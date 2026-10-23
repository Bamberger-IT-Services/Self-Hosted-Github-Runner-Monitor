# CLAUDE.md – Runner-Monitor

Es gelten die gemeinsamen Anweisungen:
https://github.com/Bamberger-IT-Services/Public/tree/main/anweisungen (00–07, Vorlagen).
Kurz: mit Tobias auf Deutsch und per „du“; Entscheidungen per Auswahlfrage, eine je Nachricht;
CI bei jedem PR; Doku im selben PR; `entwickler-dashboard/daten.js` nach jeder Arbeitsrunde
(`stand` aus `TZ=Europe/Berlin date +"%d.%m.%Y %H:%M"`).

## Projektregeln

- **Öffentliches Repository:** keine echten IPs, Rechner-, Organisations- oder Personennamen,
  keine Tokens – auch nicht in Tests, Bildern, Logs. Platzhalter: `runner-vm`, `runner-vm-01`,
  `beispiel-org`, Adressen aus `192.0.2.0/24` (RFC 5737).
- CI läuft auf `ubuntu-latest`, **nie** auf dem eigenen Runner (fremde PRs).
- Nur Python-Standardbibliothek und Vanilla-JS. Keine Pakete ohne ADR.
- Oberfläche: Ansprache „Sie“ in Anmeldung und Einrichtung, neutral im Dashboard, nie „du“.
- CSP: keine Inline-Skripte, keine `style="…"`-Attribute; Werte per `element.style` setzen.
- Design-Grundlage: Design v1 (`docs/design/`). Bei Widerspruch gelten die Anweisungen; Abgleich
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

**Kein Docker** für den Monitor, auch nicht als Zusatz (E-02, E-12) – gilt auch dann, wenn eine
Projektanweisung etwas anderes sagt. **Keine Lizenz** (E-11): keine LICENSE-Datei anlegen.

## Arbeiten

```bash
MONITOR_ENTWICKLUNG=1 MONITOR_DATEN_VERZ=./daten MONITOR_LAUF_VERZ=./lauf python3 -m runner_monitor   # → :8090/?demo
python3 -m unittest discover -s tests -t .
shellcheck einrichten.sh deploy/runner-einrichten.sh werkzeuge/paket.sh
node werkzeuge/bilder.mjs     # Bildschirmfotos fürs Handbuch (nicht als root)
werkzeuge/paket.sh            # Release-Paket nach dist/
```

Aufbau und Datenformate: `docs/FUNKTIONSWEISE.md`.
