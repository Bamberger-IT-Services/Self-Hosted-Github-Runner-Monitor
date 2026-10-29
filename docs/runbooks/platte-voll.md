# Runbook: Platte voll

**Wann:** Meldung „Platte knapp: n GB frei“; Jobs scheitern mit „No space left on device“; Runner-Dienst stoppt.
**Dauer:** ca. 5–20 Minuten · **Zuletzt geprüft:** 2026-10-29 (#144, vor 0.9.0)

Eine volle Platte kann Runner-VM **und** Hypervisor lahmlegen. Deshalb räumt die VM – eingerichtet mit
`einrichten.sh aufraeumen` – jede Nacht gründlich und alle 15 Minuten unter 25 GB frei auf, der GitHub-Runner
zusätzlich vor jedem Job (`vor-dem-job.sh`). Für jeden Runner: GitHub, Forgejo, Gitea, GitLab
([RUNNER.md](../RUNNER.md), Abschnitt 6a).

## Voraussetzungen
- SSH auf die Runner-VM mit sudo

## Schritte
1. Lage:
   ```bash
   df -h /
   docker system df
   sudo du -xh --max-depth=1 /opt/actions-runner/_work | sort -h | tail   # GitHub-Runner
   sudo du -xh --max-depth=2 /var/lib/forgejo-runner /home 2>/dev/null | sort -h | tail   # andere Runner (Pfad je nach Einrichtung)
   ```
2. Ist das Aufräumen eingerichtet? Info › Was tun, wenn … › „Platte knapp“ zeigt es; auf der VM:
   ```bash
   ls -l /usr/local/bin/runner-aufraeumen /etc/cron.daily/runner-aufraeumen
   systemctl status runner-aufraeumen.timer
   ```
   Fehlt etwas (z. B. „No such file“ oder „Unit … could not be found“) – einrichten, idempotent, ein laufender
   Job wird nicht gestört:
   ```bash
   sudo /opt/runner-monitor/aktuell/einrichten.sh aufraeumen
   ```
3. Sofort aufräumen (Container, Images, Volumes, Build-Cache; läuft gerade ein Job, nur schonend):
   ```bash
   sudo /usr/local/bin/runner-aufraeumen
   ```
   Erwartet: „runner-aufraeumen: jetzt nn GB frei (gruendlich)“ bzw. „(schonend)“. „Schonend“ entfernt auch
   während eines Jobs unbenutzte Images, die seit mindestens 30 Minuten auf der VM liegen. Reicht das nicht,
   nach dem Job erneut ausführen. Protokoll der Läufe alle 15 Minuten: `journalctl -u runner-aufraeumen -n 20`.
4. Freien Platz an den Hypervisor zurückgeben (VM-Platte mit „Discard“):
   ```bash
   sudo fstrim -av
   ```
5. Reicht es dauerhaft nicht: VM-Platte im Hypervisor vergrößern, dann in der VM das
   Dateisystem wachsen lassen (z. B. `sudo growpart /dev/sda 1 && sudo resize2fs /dev/sda1` –
   Gerät vorher mit `lsblk` prüfen).
6. War der Runner-Dienst deshalb gestoppt: [runner-dienst-gestoppt](runner-dienst-gestoppt.md).

## Prüfen, ob es geklappt hat
- Monitor: Balken von „/“ wieder links der Marke, Meldung verschwindet nach spätestens 10 s.

## Rückweg
- Aufräumen löscht nur Wegwerfdaten (Caches, gestoppte Container). Nichts zurückzuholen.

## Aufhören und Hilfe holen, wenn
- `du` zeigt große Dateien außerhalb von Docker und `_work`, deren Herkunft unklar ist – nicht blind löschen.
