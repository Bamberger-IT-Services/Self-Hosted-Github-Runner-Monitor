# Runbook: GitLab nicht erreichbar, Token ungültig oder ohne Rechte

**Wann:** Bei einem GitLab-Runner meldet der Monitor „GitLab nicht erreichbar“, „Token ungültig“ oder „keine Rechte“, oder der Runner steht bei „Online bei GitLab“ auf „unbekannt“.
**Dauer:** 5–10 Minuten · **Zuletzt geprüft:** nicht gegen einen echten Server (Stand der GitLab-Dokumentation, Version 0.8.0)

## Voraussetzungen
- SSH auf die Runner-VM mit sudo; für ein neues Token: Konto mit Rolle Maintainer in der Gruppe bzw. im Projekt

## Schritte
1. Von der VM (Adresse Ihres GitLab, hier `gitlab.example.org`):
   ```bash
   curl -sI https://gitlab.example.org/users/sign_in | head -1      # HTTP/2 200
   journalctl -u runner-monitor-sammler -n 30 --no-pager
   ```
2. **Nicht erreichbar:** DNS, Proxy, Firewall und Zertifikat prüfen. Antwortet der Server mit einer
   Weiterleitung (301/302, z. B. von `http` auf `https`), die endgültige Adresse eintragen – der Monitor
   folgt keiner Weiterleitung, damit das Token nie an eine andere Adresse geht. Fehlt nur `https://`: ein
   Server mit `http://` wird nur abgefragt, wenn in `/etc/runner-monitor/runner.json` bei diesem Runner
   `"http_erlaubt": true` steht (siehe [Einrichtung](../EINRICHTUNG.md#gitlab-anbinden)).
3. **401 / Token ungültig:** Token abgelaufen, widerrufen oder falsch kopiert. Neues Token mit dem Bereich
   `read_api` erstellen (siehe [Einrichtung](../EINRICHTUNG.md#gitlab-anbinden)) und eintragen:
   ```bash
   sudo /opt/runner-monitor/aktuell/einrichten.sh zugang <runner-id>
   ```
4. **Keine Rechte (403/404):** Das Token hat nicht den Bereich `read_api`, oder sein Konto darf den Runner
   nicht sehen (Rolle unter Maintainer, bei Gruppen-Runnern ggf. Owner; Instanz-Runner sind per Token nicht abfragbar). Bei GitLab unter Settings › Access tokens den Bereich
   und die Rolle prüfen.
5. **Runner „unbekannt“, Abfrage ok:** Der Runner wird über seinen Namen gefunden. `name` in
   `/etc/gitlab-runner/config.toml` und die Beschreibung bei GitLab (Settings › CI/CD › Runners) müssen gleich
   sein und dürfen nur einmal vorkommen.
6. **Runner „offline“, obwohl der Dienst läuft:** Bei GitLab pausiert (Settings › CI/CD › Runners › „Resume“).
7. **429 / Kontingent:** Die Abfrage setzt aus und läuft später weiter. Auf eigenen Servern lässt sich die
   Rate-Limit-Einstellung der Instanz prüfen.

## Prüfen, ob es geklappt hat
- Die Karte „Jobs je Repository“ zeigt „Abgefragt hh:mm:ss“ ohne Warnung, der Runner steht auf „online“.

## Rückweg
- Das alte Token liegt weiter in `/etc/runner-monitor/zugang/<runner-id>.token` (nur root), bis ein neues eingetragen ist; bei Bedarf bei GitLab ein neues ausstellen.

## Aufhören und Hilfe holen, wenn
- das Token in Logs, Issues oder Chats aufgetaucht ist → sofort bei GitLab widerrufen (Settings › Access tokens › Revoke).
