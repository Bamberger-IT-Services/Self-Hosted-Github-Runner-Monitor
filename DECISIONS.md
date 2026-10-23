# Entscheidungen

Nummeriert, mit Datum und Begründung (Anweisung 06). Technische Entscheidungen mit ADR in `docs/adr/`.

| Nr. | Datum | Entscheidung | Begründung | Von |
|---|---|---|---|---|
| E-01 | 23.10.2026 | Anmeldung nur mit Passwort, keine 2FA – Abweichung von Anweisung 03 | ein Zugang, nur LAN, nur lesend ([ADR-0003](docs/adr/0003-nur-passwort.md)) | Tobias (Auswahlfrage) |
| E-02 | 23.10.2026 | Normaler systemd-Dienst statt Docker | Monitor braucht den Host (`/proc`, Journal, systemd) ([ADR-0002](docs/adr/0002-systemd-statt-docker.md)) | Tobias |
| E-03 | 23.10.2026 | Updates aus GitHub-Releases, per Knopf über root-Hilfsdienst (Variante 2) | Komfort ohne Rechte im Webserver ([ADR-0004](docs/adr/0004-update-hilfsdienst.md)) | Tobias |
| E-04 | 23.10.2026 | Design v1 eingefroren (Canvas „Runner-Monitor · Design v1“) als Grundlage für 0.1.0 | Stand der Abstimmung festhalten ([docs/design](docs/design/README.md)) | Tobias |
| E-05 | 23.10.2026 | Docker-Container werden in 0.1 nicht angezeigt (Daten werden gesammelt) | Platz für Prozesse, Platten und ein größeres Log | Tobias (Kommentar im Design) |
| E-06 | 23.10.2026 | Platten- und Prozessinfos in einer Karte, Log breiter und höher, Top 6 Prozesse | Kommentare im Design | Tobias |
| E-07 | 23.10.2026 | Fehler und Warnungen zentral oben in der Kopfzeile, jede mit „Was tun?“ zur Anleitung in Info & Hilfe | „muss sichtbarer sein“, Anleitung dahinter | Tobias |
| E-08 | 23.10.2026 | Erst-Einrichtung: Skript auf der VM (Dienste, Firewall, Runner-Erkennung, Code) → Browser (Code, Zugang, GitHub) → Anmeldung | Besitznachweis über die VM, kein Standardpasswort | Tobias |
| E-09 | 23.10.2026 | Python-Standardbibliothek statt Next.js | [ADR-0001](docs/adr/0001-python-standardbibliothek.md) | Tobias (Brief) |
| E-10 | 23.10.2026 | Ansprache in Anmeldung und Einrichtung „Sie“, im Dashboard neutral – Design v1 nutzte teils „du“ | Anweisungen gehen dem Entwurf vor (Anweisung 06) | Claude (im Rahmen der Anweisungen) |
