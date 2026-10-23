# Runbook: GitHub nicht erreichbar, Token ungültig

**Wann:** „GitHub nicht erreichbar“, „GitHub-Token ungültig“, „Token läuft ab“, Workflows zeigen einen alten Stand.
**Dauer:** 5–10 Minuten · **Zuletzt geprüft:** 2026-10-23 (Version 0.1.0)

## Voraussetzungen
- SSH auf die Runner-VM mit sudo; für ein neues Token: Konto mit Rechten in der Organisation

## Schritte
1. GitHub selbst gestört? githubstatus.com
2. Von der VM:
   ```bash
   curl -sI https://api.github.com | head -1        # HTTP/2 200
   journalctl -u runner-monitor-sammler -n 30 --no-pager
   ```
3. **401 / Token ungültig oder abgelaufen:** neues Fine-grained Token (Rechte siehe
   [Einrichtung](../EINRICHTUNG.md#github-token-erstellen)) und eintragen:
   ```bash
   sudo /opt/runner-monitor/aktuell/einrichten.sh token
   ```
4. **403 / Kontingent:** die Abfrage setzt bis zum Reset aus (Uhrzeit unter Info ›
   GitHub-Verbindung). Viele Repositories? Je Abfrage braucht der Monitor etwa eine Anfrage je Repository plus drei; 5000 Anfragen je Stunde reichen im 30-s-Takt für etwa 35 Repositories (Issue #15).
5. **Keine Antwort:** DNS, Proxy, Firewall der VM nach außen prüfen.

## Prüfen, ob es geklappt hat
- Karte „Workflows“ zeigt „Abgefragt hh:mm:ss“ ohne Warnung.

## Rückweg
- Das alte Token liegt nicht mehr vor; bei Bedarf in GitHub ein neues ausstellen.

## Aufhören und Hilfe holen, wenn
- das Token in Logs, Issues oder Chats aufgetaucht ist → sofort in GitHub widerrufen.
