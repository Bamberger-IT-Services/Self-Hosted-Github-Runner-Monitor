# ADR-0002: systemd-Dienst statt Docker

**Status:** angenommen
**Datum:** 2026-10-23 · **Entschieden von:** Tobias („ok, dann kein Docker.. normaler Dienst“)

## Ausgangslage
Gefragt war, ob der Monitor als kleine Docker-Instanz laufen kann. Er braucht aber den Blick
auf den **Host**: `/proc` aller Prozesse, das systemd-Journal, `systemctl` für den Runner-Dienst,
die Dateien des Runners, Docker selbst.

## Entscheidung
Normale systemd-Dienste auf der VM, kein Container, kein Image in GHCR.

## Betrachtete Möglichkeiten
- **A: systemd-Dienste** – direkter Zugriff, Härtung über systemd, keine Image-Pflege.
- **B: Docker-Container** – bräuchte `--pid=host`, Journal- und Docker-Socket-Mounts, `/opt/actions-runner`
  als Volume; der Container wäre damit faktisch privilegiert. Zudem räumt `runner-aufraeumen`
  regelmäßig Docker auf – der Monitor würde sich selbst gefährden.

## Folgen
- Release ist ein `tar.gz` mit Prüfsumme statt eines Images; Anweisung 01 (GHCR, Trivy, Image-Probe) entfällt.
- Update über einen root-Hilfsdienst ([ADR-0004](0004-update-hilfsdienst.md)).
