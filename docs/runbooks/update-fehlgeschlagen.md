# Runbook: Update fehlgeschlagen (Rückfall)

**Wann:** Meldung „Update fehlgeschlagen“, oder der Monitor verhält sich nach einem Update falsch.
**Dauer:** ca. 5 Minuten · **Zuletzt geprüft:** 2026-10-23 (Version 0.1.0, nur am Schreibtisch – Issue #14)

Bei „Update fehlgeschlagen“ hat der Hilfsdienst die alte Version **schon wiederhergestellt** –
es läuft nichts Kaputtes.

## Voraussetzungen
- SSH auf die Runner-VM mit sudo

## Schritte
1. Grund lesen:
   ```bash
   journalctl -u runner-monitor-update -n 50 --no-pager
   sudo cat /var/lib/runner-monitor/update-status.json
   ```
   | Grund | Bedeutung |
   |---|---|
   | Download fehlgeschlagen | Netz/GitHub – später erneut versuchen |
   | wird noch bereitgestellt / Release enthält kein Archiv mit Prüfsumme | Release gerade erst veröffentlicht, das Paket wird noch angehängt – Info › Updates › „Jetzt prüfen“, dann erneut versuchen (ab 0.6 von selbst nach 2 Minuten) |
   | Prüfsumme stimmt nicht | Archiv beschädigt oder manipuliert – **nicht** von Hand installieren, Issue melden |
   | neue Version hat nicht geantwortet | `journalctl -u runner-monitor -n 50` zeigt den Fehler der neuen Version |
2. Erneut versuchen: Info › Updates › „Erneut versuchen“ oder
   ```bash
   sudo /opt/runner-monitor/aktuell/einrichten.sh aktualisieren
   ```
3. Läuft eine neue Version, verhält sich aber falsch: zurück auf die vorige.
   ```bash
   sudo /opt/runner-monitor/aktuell/einrichten.sh zurueck
   ```

## Prüfen, ob es geklappt hat
- `curl -s http://127.0.0.1:8090/api/health` zeigt die erwartete Version; Info › Updates ebenso.

## Rückweg
- `ls /opt/runner-monitor/versionen/` – jede dort liegende Version lässt sich per `zurueck`
  (vorige) oder durch Aufruf ihres eigenen `einrichten.sh` wieder aktivieren.

## Aufhören und Hilfe holen, wenn
- die Prüfsumme wiederholt nicht stimmt (möglicher Angriff auf den Download) – Sicherheitsmeldung über GitHub.
