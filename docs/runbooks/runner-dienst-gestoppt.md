# Runbook: Runner-Dienst gestoppt oder offline

**Wann:** Meldung „Runner-Dienst gestoppt“ (rot) oder „Runner offline bei GitHub“; Jobs bleiben in der Warteschlange.
**Dauer:** ca. 5–15 Minuten · **Zuletzt geprüft:** 2026-10-23 (Version 0.1.0, nur am Schreibtisch – Issue #14)

## Voraussetzungen
- SSH auf die Runner-VM mit sudo

## Schritte
1. Zustand ansehen:
   ```bash
   systemctl status 'actions.runner.*'
   journalctl -u 'actions.runner.*' -n 100 --no-pager
   ```
   Erwartet: `active (running)`. Sonst zeigt das Journal den Grund (Absturz, „Runner update“, Platte voll …).
2. Platz prüfen – eine volle Platte ist die häufigste Ursache:
   ```bash
   df -h /
   ```
   Unter 5 GB frei → erst [platte-voll](platte-voll.md).
3. Steht im Status `Result: oom-kill`, hat ein Job den Arbeitsspeicher gesprengt. Dann vor dem
   Start RAM und Swap prüfen und den Dienst gegen Speichermangel einstellen:
   [RUNNER.md › Wie viel Arbeitsspeicher?](../RUNNER.md#wie-viel-arbeitsspeicher) und die Zeile
   „oom-kill“ in der Fehlerhilfe dort.
4. Dienst starten (mit dem vollen Namen der Unit; ein Muster wie `'actions.runner.*'` greift
   beim Start nur, wenn systemd die Unit gerade geladen hat):
   ```bash
   U=$(systemctl list-units --all --plain --no-legend 'actions.runner.*' | awk '{print $1}')
   sudo systemctl start "$U"
   ```
5. **Offline bei GitHub**, obwohl der Dienst läuft: Netz und Anmeldung prüfen.
   ```bash
   curl -sI https://github.com | head -1          # HTTP/2 200
   sudo tail -n 100 "$(ls -t /opt/actions-runner/_diag/Runner_*.log | head -1)"
   ```
   Steht dort „401“ oder „runner registration has been deleted“: Runner wurde in GitHub
   entfernt → neu registrieren (Registrierungs-Token aus GitHub › Organisation › Settings ›
   Actions › Runners › „New self-hosted runner“):
   ```bash
   sudo /opt/runner-monitor/aktuell/einrichten.sh runner --umziehen
   ```
6. Hängt ein einzelner Job, sein Worker-Protokoll:
   ```bash
   sudo tail -n 100 "$(ls -t /opt/actions-runner/_diag/Worker_*.log | head -1)"
   ```

## Prüfen, ob es geklappt hat
- Monitor zeigt „Bereit“ oder „Job läuft“, Plaketten „Dienst aktiv“ und „Online bei GitHub“.
- Wartende Jobs starten von selbst.

## Rückweg
- Nichts zu tun – Starten und Neustarten ändern keine Daten.

## Aufhören und Hilfe holen, wenn
- der Dienst sofort wieder stirbt und das Journal nichts Verständliches zeigt. Dann
  Diagnose bündeln (keine echten Namen weitergeben):
  ```bash
  sudo tar czf ~/runner-diag.tgz -C /opt/actions-runner _diag
  journalctl -u 'actions.runner.*' --since today > ~/runner-journal.txt
  ```
