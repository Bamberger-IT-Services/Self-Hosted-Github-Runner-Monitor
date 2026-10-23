# ADR-0001: Python-Standardbibliothek statt Next.js/TypeScript

**Status:** angenommen
**Datum:** 2026-10-23 · **Entschieden von:** Tobias (Vorgabe im Design-Brief), Claude (Ausarbeitung)

## Ausgangslage
Anweisung 02 sieht für Web-Apps Next.js mit TypeScript und Postgres vor. Der Runner-Monitor
ist aber ein kleines Werkzeug auf genau einer VM: ein Benutzer, keine Datenbank, Daten aus
`/proc`, dem Journal und Dateien des Runners. Er soll ohne Paketinstallation laufen und die VM
kaum belasten.

## Entscheidung
Server in Python 3.10+ nur mit der Standardbibliothek (`http.server`, `json`, `hashlib.scrypt`,
`urllib`), Oberfläche als statisches HTML/CSS/Vanilla-JS, Live-Daten per Server-Sent Events.
Speicher: kleine JSON-Dateien statt Postgres.

## Betrachtete Möglichkeiten

### A: Python-Standardbibliothek
| Gesichtspunkt | Einschätzung |
|---|---|
| Aufwand | niedrig |
| Betrieb (eine Person) | sehr einfach: Python ist auf Ubuntu vorhanden, keine Updates von Paketen |
| Sicherheit | keine Lieferkette; HTTP-Server selbst gehärtet |
| Vertrautheit | hoch |

**Für:** null Abhängigkeiten, wenige MB RAM · **Gegen:** weniger Komfort (kein Router, keine Typprüfung)

### B: Next.js + TypeScript (Standard der Anweisungen)
**Für:** einheitlich mit anderen Projekten · **Gegen:** Node-Laufzeit, Hunderte Pakete, Build,
deutlich mehr RAM – für ein Monitoring-Werkzeug auf der Runner-VM unverhältnismäßig.

## Folgen
- leichter: Installation in einer Minute, Updates als ein Archiv.
- schwerer: Rate-Limits/Sperren dateibasiert statt in Postgres; Tests mit `unittest`.
- neu prüfen, wenn: mehrere Benutzer, Rollen oder mehrere VMs in einer Oberfläche gebraucht werden.
