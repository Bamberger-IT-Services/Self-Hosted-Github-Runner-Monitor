# Runbook: Platte voll

**Wann:** Meldung „Platte knapp: n GB frei“; Jobs scheitern mit „No space left on device“; Runner-Dienst stoppt.
**Dauer:** ca. 5–20 Minuten · **Zuletzt geprüft:** 2026-10-23 (Version 0.1.0)

Eine volle Platte kann Runner-VM **und** Hypervisor lahmlegen. Deshalb räumt der Runner unter
25 GB frei vor jedem Job selbst auf (`vor-dem-job.sh`) und jede Nacht gründlich.

## Voraussetzungen
- SSH auf die Runner-VM mit sudo

## Schritte
1. Lage:
   ```bash
   df -h /
   docker system df
   sudo du -xh --max-depth=1 /opt/actions-runner/_work | sort -h | tail
   ```
2. Sofort aufräumen (Container, Images, Volumes, Build-Cache):
   ```bash
   sudo runner-aufraeumen
   ```
   Erwartet: „runner-aufraeumen: jetzt nn GB frei“.
3. Freien Platz an den Hypervisor zurückgeben (VM-Platte mit „Discard“):
   ```bash
   sudo fstrim -av
   ```
4. Reicht es dauerhaft nicht: VM-Platte im Hypervisor vergrößern, dann in der VM das
   Dateisystem wachsen lassen (z. B. `sudo growpart /dev/sda 1 && sudo resize2fs /dev/sda1` –
   Gerät vorher mit `lsblk` prüfen).
5. War der Runner-Dienst deshalb gestoppt: [runner-dienst-gestoppt](runner-dienst-gestoppt.md).

## Prüfen, ob es geklappt hat
- Monitor: Balken von „/“ wieder links der Marke, Meldung verschwindet nach spätestens 10 s.

## Rückweg
- Aufräumen löscht nur Wegwerfdaten (Caches, gestoppte Container). Nichts zurückzuholen.

## Aufhören und Hilfe holen, wenn
- `du` zeigt große Dateien außerhalb von Docker und `_work`, deren Herkunft unklar ist – nicht blind löschen.
