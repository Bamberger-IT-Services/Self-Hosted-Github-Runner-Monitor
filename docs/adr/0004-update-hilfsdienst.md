# ADR-0004: Updates über einen root-Hilfsdienst (Variante 2)

**Status:** angenommen
**Datum:** 2026-10-23 · **Entschieden von:** Tobias („variante 2 gefällt mir auch“)

## Ausgangslage
Updates sollen in der Oberfläche erkannt und per Knopf angestoßen werden. Der Webserver läuft
bewusst ohne Rechte und darf weder Dateien unter `/opt` ändern noch Dienste neu starten.

## Entscheidung
Ein eigener root-Dienst `runner-monitor-update.service`, ausgelöst von `runner-monitor-update.path`,
sobald der Webserver `auftraege/update` (nur eine Versionsnummer) ablegt. Der Dienst:
1. nimmt Archiv- und Prüfsummen-Adresse **nur** aus `/run/runner-monitor/release.json` (vom
   root-Sammler, nur root schreibbar) und nur von `https://github.com/<release-repo>/releases/download/`,
2. prüft SHA-256, entpackt sicher nach `/opt/runner-monitor/versionen/X.Y.Z`,
3. hängt den Verweis `aktuell` um, startet neu,
4. prüft `/api/health` 30 s lang und kehrt sonst zur alten Version zurück.
Fortschritt in `update-status.json`, das die Oberfläche anzeigt.

## Betrachtete Möglichkeiten
- **1: nur Hinweis**, Update per SSH – sicher, aber unbequem.
- **2: root-Hilfsdienst** (gewählt) – Knopf in der Oberfläche, Rechte bleiben getrennt.
- **3: Webserver mit sudo-Regel** – verworfen: ein Fehler im Webserver hätte root-Folgen.

## Folgen
- Release-Workflow muss `runner-monitor-X.Y.Z.tar.gz` und `.sha256` anhängen (`.github/workflows/release.yml`).
- Offen: Signatur statt nur Prüfsumme (S-UPD-01, A-10).
