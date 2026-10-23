# Runbook: Live-Log bleibt leer

**Wann:** Ein Job läuft (Karte „Job läuft“), aber das Live-Log zeigt keine neuen Zeilen – oder nur
alte Zeilen eines früheren Jobs.
**Dauer:** ca. 5 Minuten · **Zuletzt geprüft:** 2026-10-23 (Version 0.5.0)

## Voraussetzungen
- SSH auf die Runner-VM mit sudo
- Ein laufender Job (sonst gibt es nichts zu sehen)

## Schritte
1. Schreibt der Runner gerade Seitendateien? Der Monitor liest die jüngste Datei in `_diag/pages`.
   ```bash
   sudo ls -la --time-style=+%H:%M:%S /opt/actions-runner/_diag/pages | tail -5
   sudo find /opt/actions-runner/_diag -type f -newermt '-5 minutes' -printf '%TT %s %p\n' | sort | tail -15
   ```
   Erwartet: während des Jobs eine Datei mit aktueller Uhrzeit, die wächst. Liegen nur alte Dateien
   dort, schreibt der Runner seine Ausgabe woanders hin – Ausgabe und Runner-Version
   (`/opt/actions-runner/bin/Runner.Listener --version`) in einem Fehler-Issue melden.
2. Darf der Monitor die Dateien lesen?
   ```bash
   sudo -u runner-monitor ls /opt/actions-runner/_diag/pages | tail -3
   ```
   Erwartet: dieselben Dateinamen wie in Schritt 1, keine Fehlermeldung.
3. Hat der Log-Leser einen Fehler gemeldet?
   ```bash
   journalctl -u runner-monitor -n 200 --no-pager | grep -iE "live-log|exception|traceback" | tail -20
   ```
   Seit 0.5.0 läuft der Leser nach einem Fehler weiter und schreibt ihn hier hinein.
4. Monitor neu starten (liest dann die jüngste Datei neu ein):
   ```bash
   sudo systemctl restart runner-monitor
   ```

## Prüfen, ob es geklappt hat
- Neue Zeilen erscheinen im Live-Log, die Pille zeigt den aktuellen Schritt.

## Rückweg
- Nichts zu tun – die Schritte ändern nichts außer einem Neustart des Monitors.

## Aufhören und Hilfe holen, wenn
- in Schritt 1 während eines Jobs keine aktuelle Datei erscheint – dann hat sich der Ablageort
  des Runners geändert und der Monitor muss angepasst werden.
