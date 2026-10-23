# Runbook: Monitor nicht erreichbar

**Wann:** Seite lädt nicht, oder sie bleibt auf „Getrennt“.
**Dauer:** ca. 5 Minuten · **Zuletzt geprüft:** 2026-10-23 (Version 0.1.0)

## Voraussetzungen
- SSH auf die Runner-VM mit sudo

## Schritte
1. Läuft der Dienst?
   ```bash
   sudo /opt/runner-monitor/aktuell/einrichten.sh status
   journalctl -u runner-monitor -n 50 --no-pager
   ```
2. Antwortet er lokal?
   ```bash
   curl -s http://127.0.0.1:8090/api/health
   ```
   Antwortet er lokal, aber nicht im Browser: Firewall.
   ```bash
   sudo ufw status | grep 8090        # Regel „ALLOW … from <lan>“?
   ```
   Fehlt sie: `sudo ufw allow from 192.0.2.0/24 to any port 8090 proto tcp` (eigenes Netz einsetzen).
3. Neu starten:
   ```bash
   sudo systemctl restart runner-monitor runner-monitor-sammler
   ```
4. Startet er nicht („Konfiguration ungültig“): `/etc/runner-monitor/konfig.env` mit der
   [Vorlage](../../deploy/konfig.env.example) vergleichen.
5. Nach einem Update kaputt: [update-fehlgeschlagen](update-fehlgeschlagen.md).

## Prüfen, ob es geklappt hat
- `/api/health` antwortet, im Browser „Verbunden“.

## Rückweg
- `sudo /opt/runner-monitor/aktuell/einrichten.sh zurueck` (vorige Version).

## Aufhören und Hilfe holen, wenn
- auch die vorige Version nicht startet – dann Fehler-Issue mit bereinigtem Journal.
