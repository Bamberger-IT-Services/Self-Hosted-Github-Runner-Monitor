# Design

**Stand: 23.10.2026 · Version 0.1.0**

**Design v1 (eingefroren 23.10.2026)** – Canvas „Runner-Monitor · Design v1“ in Claude Design
(privat). Eine Kopie aller Bildschirme liegt in [`v1/`](v1/) (`*.dc.html`, Design-Canvas-Format).
Neue Entwürfe bekommen einen eigenen Ordner `v2/`; `v1/` bleibt unverändert.

Grundlage: Designsystem „Bamberger IT Services“ (Farben, Radien), Schrift = Systemschrift,
Bewegung nach Apple-Prinzipien (kritisch gedämpfte Federn, `prefers-reduced-motion`).
Farben und Maße: [TOKENS.md](TOKENS.md).

## Abgleich Design ↔ Code

| Bildschirm (v1) | Code | Stand | Bemerkung |
|---|---|---|---|
| Main (Job läuft) | `web/dashboard.*` | umgesetzt | |
| Leerlauf | dashboard | umgesetzt | |
| Volllast-dunkel | dashboard | umgesetzt | 16 Kerne: Balken in zwei Spalten |
| Gestoppt | dashboard | umgesetzt | Link heißt „Runner-Logs abrufen“ statt „So rufst du die Runner-Logs ab“ (neutral) |
| Offline | dashboard | umgesetzt | wie Gestoppt |
| Platte-knapp | dashboard | umgesetzt | mehrere Laufwerke dynamisch, Schwelle nur für „/“ |
| Getrennt | dashboard | umgesetzt | |
| Kein-Token | dashboard | umgesetzt | |
| GitHub-nicht-erreichbar | dashboard | umgesetzt | |
| Token-Ablauf | dashboard | umgesetzt | |
| Info & Hilfe (Blatt) | dashboard | umgesetzt | Abschnitte wie v1; „Abmelden“ ergänzt |
| Update-verfuegbar / -laeuft / -fehlgeschlagen | dashboard | umgesetzt | |
| Docker-Container | – | entfällt in 0.1 | in v1 entfernt (E-05), Daten werden gesammelt |
| Setup-Skript, Setup-Skript-ohne-Runner | `einrichten.sh` | umgesetzt | Terminalausgabe leicht gekürzt |
| Setup-Web (1 Code) | `web/einrichtung.*` | umgesetzt | **„Sie“** statt „du“ (Anweisung 03/06) |
| Setup-Web-Zugang | einrichtung | umgesetzt | „Sie“; Stärkebalken zeigt nur die Länge (keine Zusammensetzungsregeln) |
| Setup-Web-GitHub | einrichtung | umgesetzt | „Sie“ |
| Setup-Web-Fertig | einrichtung | umgesetzt | „Zum Monitor“ führt zur Anmeldung |
| Login, Login-Fehler | `web/anmelden.*` | umgesetzt | „Sie“; Sperre zählt herunter |

## Vermerke für Design v2

- Ansprache: Anmeldung und Einrichtung durchgehend „Sie“, Dashboard neutral (v1 hatte stellenweise „du“).
- Kopfzeile bei 1440 px: Mit Meldung wird „aktualisiert hh:mm:ss“ ausgeblendet, damit der Meldungstext Platz hat.
- Bei vielen Laufwerken scrollt die Plattenliste innerhalb der Karte.
- **Netz** (ab 0.1.1, Wunsch Tobias): Zeile „Netz“ in der Auslastung zwischen Swap und Last – ↓ empfangen, ↑ gesendet, Spitze 10 Min. Nicht in Design v1, im Stil der Zeile „Last“ ergänzt. Der RAM-Verlauf wird dadurch etwas flacher.
