# CLAUDE.md – Runner-Monitor

Es gelten die gemeinsamen Anweisungen im Repo `Public` auf Forgejo, Ordner `anweisungen/`
(lokal `~/_Forgejo/Bamberger-IT-Services/Public/anweisungen`, 00–08, Vorlagen).
**Seit 28.10.2026 nur noch Forgejo** (README der Anweisungen › Forgejo statt GitHub): GitHub ist
eingefroren, Branches `develop` (Standard) / `main` / `feature/*` / `fix/*` / `release/*`, Merge
nach `develop` per PR selbst, nach `main` nur mit Freigabe. Lokaler Ordner:
`~/_Forgejo/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor`. Was das Programm selbst
mit GitHub macht (Runner überwachen, Updates aus GitHub-Releases), bleibt vorerst so. Deshalb
legt Claude jedes Release zusätzlich per `gh release create` auf GitHub an (Tag und `main` kommen
über die Forgejo-Spiegelung, Filter `main,develop,release/*`; `release.yml` baut dort Paket und
Attestierung, dasselbe Paket hängt byte-gleich am Forgejo-Release; E-29).
Kurz: mit Tobias auf Deutsch und per „du“; Entscheidungen per Auswahlfrage, eine je Nachricht;
volle CI vor dem Release, je PR nach `develop` nur gitleaks und vor dem Merge die Tests lokal (E-30); Doku im selben PR; `entwickler-dashboard/daten.js` (Entscheidungen, Verlauf)
nach jeder Arbeitsrunde (`stand` aus `TZ=Europe/Berlin date +"%d.%m.%Y %H:%M"`).

## Modellwahl (Anweisung 09, seit 28.10.2026)
Sitzungen, die Issues abarbeiten, laufen auf **Sonnet**. Vor jedem Issue nennt Claude im Chat die Stufe
(„Stufe Umsetzung, weil …“) und gibt die Arbeit an den passenden Subagenten in `.claude/agents/` ab:
- `routine` (Haiku, wenig Aufwand): Labels, Issues, CI-Protokolle, Tippfehler, Versionsnummern, Dashboard.
- `umsetzer` (Sonnet, mittel): Issues mit klaren Akzeptanzkriterien, Oberfläche nach Entwurf, Tests.
- `architekt` (Opus, hoch): Aktualisierer und Herkunftsprüfung, `einrichten.sh` und Runner-Einrichtung, Anmeldung, Tokens, Sicherheitsbericht, Release – dazu Fehler mit unklarer Ursache und das Review größerer PRs vor dem Merge.
Im Zweifel die höhere Stufe; nach dem zweiten Fehlversuch hochstufen, nie stillschweigend herunter.

**Aufgaben** stehen als Issues in diesem Repo auf Forgejo (Anweisung 08) und alle im Projekt-Board
„Roadmap“, gepflegt vom Board-Bot (Anweisung 08 › Projekt-Board): Backlog, „To review“ (über
`Closes #<nr>`) und Geschlossen setzt er selbst; `forgejo-board.js` aus den Anweisungen nur optional für
„In progress“ oder wenn der Bot ausfällt. Nächstes Issue = offen, ohne `agent:`-Label und ohne `blocked`, höchste Priorität
zuerst; vor dem Start `agent:claude`; Branch `feature/<nr>-<kurzname>` bzw. `fix/<nr>-<kurzname>`
von `develop`, PR nach `develop` mit `Closes #<nr>`.
Bereichslabels: `area:monitor`, `area:einrichtung`, `area:runner`, `area:docs`.

## Projektregeln

- **Öffentliches Repository:** keine echten IPs, Rechner-, Organisations- oder Personennamen,
  keine Tokens – auch nicht in Tests, Bildern, Logs. Platzhalter: `runner-vm`, `runner-vm-01`,
  `beispiel-org`, Adressen aus `192.0.2.0/24` (RFC 5737).
- CI läuft auf `ubuntu-latest`, **nie** auf dem eigenen Runner (fremde PRs).
- Nur Python-Standardbibliothek und Vanilla-JS. Keine Pakete ohne ADR.
- Oberfläche: Ansprache „Sie“ in Anmeldung und Einrichtung, neutral im Dashboard, nie „du“.
- CSP: keine Inline-Skripte, keine `style="…"`-Attribute; Werte per `element.style` setzen.
- Design-Grundlage: Design v0.8.0 (`docs/design/v0.8.0/`, pixelgenau umsetzen). Bei Widerspruch gelten die Anweisungen; Abgleich
  in `docs/design/README.md` pflegen.
- Produktive Schritte (Release veröffentlichen, VM umstellen, Einstellungen bei Forgejo oder GitHub) nur nach OK von Tobias.

## Abweichungen von den Anweisungen

| Anweisung | Abweichung | Beleg |
|---|---|---|
| 02 Stack (Next.js, Postgres) | Python-Standardbibliothek, JSON-Dateien | ADR-0001 |
| 01 Release (GHCR-Images, Trivy, Abnahme mit Compose) | tar.gz + SHA-256 am Release, kein Docker | ADR-0002 |
| 03 Zwei-Faktor | nur Passwort | ADR-0003, E-01 |
| 04 CSP mit Nonce | `script-src 'self'` ohne Inline-Skripte | Sicherheitsbericht S-CSP-01 |
| 04 Rate-Limit in Postgres | dateibasiert (`sperren.json`) | ADR-0001 |
| 06/08 Design-Übergabe unter `handoff/` | Entwürfe unter `docs/design/vX/` (z. B. `docs/design/v0.4.0/`), Abgleich in `docs/design/README.md` | Projektstand seit Design v1 |
| 01/06 CI bei jedem PR | volle Prüfung nur bei PRs nach `main`, Push auf `main` und von Hand; PRs nach `develop`: gitleaks in der CI, Tests lokal vor dem Merge | E-30 |
| README Forgejo statt GitHub (GitHub eingefroren) | Releases zusätzlich auf GitHub (Aktualisierer und Attestierung) | E-29, ADR-0007 |

**Kein Docker** für den Monitor, auch nicht als Zusatz (E-02, E-12) – gilt auch dann, wenn eine
Projektanweisung etwas anderes sagt. **Keine Lizenz** (E-11): keine LICENSE-Datei anlegen.

## Arbeiten

```bash
MONITOR_ENTWICKLUNG=1 MONITOR_DATEN_VERZ=./daten MONITOR_LAUF_VERZ=./lauf python3 -m runner_monitor   # → :8090/?demo
python3 -m unittest discover -s tests -t .
node --test tests/js/*.test.mjs   # Glob nötig, nur das Verzeichnis scheitert
shellcheck einrichten.sh deploy/runner-einrichten.sh deploy/aufraeumen-einrichten.sh deploy/runner-aufraeumen werkzeuge/paket.sh werkzeuge/zap-baseline.sh
node werkzeuge/bilder.mjs     # Bildschirmfotos fürs Handbuch (nicht als root)
werkzeuge/paket.sh            # Release-Paket nach dist/
werkzeuge/zap-baseline.sh     # OWASP-ZAP-Baseline gegen eine lokale Testinstanz (Sicherheitsbericht › Prüfungen)
```

Aufbau und Datenformate: `docs/FUNKTIONSWEISE.md`.
