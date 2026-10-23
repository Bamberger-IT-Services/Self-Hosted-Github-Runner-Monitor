# Umsetzung 0.4.0 im Repo

## 1. Verlauf füllt die ganze Breite
Ursache: `zustand.py` hält CPU/RAM/Netz nur im Speicher (`deque(maxlen=600)`). Nach jedem Neustart des Monitors (Update, Reboot, `systemctl restart`) beginnt der Verlauf leer; `spark()` in `web/dashboard.js` legt ihn rechtsbündig in ein festes 600-s-Raster – links bleibt die Fläche leer.

- **Sichern:** alle 10 s `cpu_verlauf`, `ram_verlauf`, `netz_verlauf` + Zeitstempel nach `/var/lib/runner-monitor/verlauf.json` (atomar: temp + rename). Beim Start übernehmen, wenn jünger als 10 Min.; Lücke seit dem letzten Wert mit dem ersten neuen Messwert auffüllen oder verwerfen, wenn > 60 s.
- **Zeichnen:** `spark()` streckt den vorhandenen Verlauf über die volle Breite (Stützpunkte = min(120, Länge)), Fläche immer von x=0 bis x=300.
- **Achse:** links `vor 10 Min.` bei vollem Verlauf, sonst `seit hh:mm` (Startzeit des Verlaufs, neues Feld `verlauf.start` in der Momentaufnahme). Gilt für CPU, RAM und Netz.

## 2. Job-Schritte überall gleich
Ursache: zwei Quellen. `schritt_nr` zählt lokal die Dateien in `_diag/pages`, `schritte`/`schritt` kommen alle 30 s von GitHub. Karte zeigt mal „Nr. 3“ ohne Balken, mal „3 von 8“ mit Balken; Log-Trenner mischen lokale Nummer mit GitHub-Namen; Post-Schritte lassen die Zahl springen.

- **Eine Quelle:** Server rechnet `job.schritt = {nr, von, name}` und nutzt es für Status, Log-Chip und Trenner. `nr = max(lokal, github)`, nie kleiner als zuvor im selben Job. `von = max(len(schritte), nr)` oder `null`, wenn GitHub noch nichts geliefert hat.
- **Fester Aufbau:** Segmentbalken immer anzeigen. Ohne `von`: „3 von –“, Name „Schritt 3“ gedämpft, Balken mit `nr` Segmenten + einem gestrichelten Rest. Log: „Schritt 3/–“.
- Sobald GitHub liefert, Name und Anzahl nachtragen, ohne den Block neu aufzubauen.

Design: `Runner-Monitor 0.4.0.dc.html` › Dashboard › „Monitor gerade neu gestartet“ und „Job · Schrittliste von GitHub fehlt noch“.
