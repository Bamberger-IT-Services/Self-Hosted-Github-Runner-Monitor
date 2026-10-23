# Runbook: Zugang gesperrt oder Passwort vergessen

**Wann:** „Zu viele Fehlversuche“, Passwort unbekannt.
**Dauer:** 2–5 Minuten · **Zuletzt geprüft:** 2026-10-23 (Version 0.1.0)

## Voraussetzungen
- SSH auf die Runner-VM mit sudo

## Schritte
1. **Nur gesperrt:** 5 Minuten warten. Die Sperre greift nach 5 Fehlversuchen je Konto oder
   30 je Adresse in 15 Minuten.
2. **Passwort vergessen:**
   ```bash
   sudo /opt/runner-monitor/aktuell/einrichten.sh passwort
   ```
   Das löscht Zugang, Sitzungen und Sperren (Token und Einstellungen bleiben) und zeigt einen
   neuen Einrichtungscode. Im Browser die Adresse öffnen, Code eingeben, Zugang neu anlegen,
   den GitHub-Schritt überspringen.
3. Häufen sich Fehlversuche ohne eigenes Zutun: Wer kann Port 8090 erreichen?
   ```bash
   sudo ufw status | grep 8090
   journalctl -u runner-monitor --since today | grep -c anmelden
   ```

## Prüfen, ob es geklappt hat
- Anmeldung mit dem neuen Passwort geht.

## Rückweg
- Keiner nötig.

## Aufhören und Hilfe holen, wenn
- Fehlversuche von unbekannten Adressen kommen – Port schließen (`sudo ufw deny 8090/tcp`) und prüfen.
