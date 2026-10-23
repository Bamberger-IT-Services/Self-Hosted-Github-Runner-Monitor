# HTTPS über einen Reverse-Proxy

**Stand: 23.10.2026 · Version 0.4.0**

Der Monitor spricht selbst nur HTTP und ist für das lokale Netz gedacht (Sicherheitsbericht
S-NET-01). Soll er von außerhalb des LAN erreichbar sein – etwa über ein VPN mit Gästen oder eine
Freigabe im Router –, gehört ein Reverse-Proxy mit TLS davor. Diese Anleitung nutzt
[Caddy](https://caddyserver.com) als systemd-Dienst auf derselben VM (kein Docker).

## Ziel

```
Browser ──HTTPS:443──► Caddy (TLS) ──HTTP:8090 (nur 127.0.0.1)──► runner-monitor
```

- Der Monitor hört nur noch auf `127.0.0.1`, niemand kommt am Proxy vorbei.
- Cookies tragen `Secure`, der Monitor schickt `Strict-Transport-Security` (HSTS).
- Die Live-Verbindung (Server-Sent Events, `/events`) läuft ungepuffert durch.

## Schritte

1. **Caddy installieren** (offizielles Paket-Repository, siehe caddyserver.com › Install › Debian/Ubuntu):
   ```bash
   sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
   sudo apt update && sudo apt install -y caddy
   ```

2. **Caddy einrichten** – `/etc/caddy/Caddyfile`, eine der beiden Varianten:

   Mit eigenem Namen, der öffentlich auf die VM zeigt (Zertifikat von Let's Encrypt):
   ```
   monitor.example.org {
       reverse_proxy 127.0.0.1:8090 {
           flush_interval -1
       }
   }
   ```

   Nur im eigenen Netz oder VPN (Caddy erzeugt ein eigenes Zertifikat; der Browser warnt, bis die
   Caddy-Wurzel auf dem Mac als vertrauenswürdig eingetragen ist – `sudo caddy trust` zeigt den Weg):
   ```
   https://runner-vm.local {
       tls internal
       reverse_proxy 127.0.0.1:8090 {
           flush_interval -1
       }
   }
   ```

   `flush_interval -1` reicht die Live-Daten sofort weiter. Den `Host`-Kopf lässt Caddy unverändert –
   das braucht der Monitor, weil er ändernde Anfragen gegen den `Origin`-Kopf prüft (CSRF).

3. **Monitor umstellen** – in `/etc/runner-monitor/konfig.env`:
   ```
   MONITOR_HTTPS=1
   MONITOR_ADRESSE=127.0.0.1
   ```
   ```bash
   sudo systemctl restart runner-monitor caddy
   ```

4. **Firewall anpassen** – 443 statt 8090 freigeben (Netz wie bisher einsetzen):
   ```bash
   sudo ufw allow from 192.0.2.0/24 to any port 443 proto tcp
   sudo ufw delete allow from 192.0.2.0/24 to any port 8090 proto tcp
   ```

## Prüfen, ob es geklappt hat

```bash
curl -sI https://monitor.example.org/api/health | grep -iE "^HTTP|strict-transport"   # 200 und HSTS
curl -s  http://127.0.0.1:8090/api/health                                           # Monitor lokal
curl -s  --max-time 3 http://<adresse-der-vm>:8090/api/health || echo "8090 von außen zu – gut"
```

Im Browser: Anmelden über `https://…`, oben „Verbunden“, das Live-Log läuft mit.

## Rückweg

- In `konfig.env` `MONITOR_HTTPS` und `MONITOR_ADRESSE` wieder entfernen, `sudo systemctl restart runner-monitor`.
- Firewall-Regel für 8090 wieder anlegen, Caddy stoppen: `sudo systemctl disable --now caddy`.

## Wichtig

- `MONITOR_HTTPS=1` nur hinter TLS setzen: Über reines HTTP nimmt der Browser `Secure`-Cookies
  nicht an, die Anmeldung scheitert dann still.
- HSTS merkt sich der Browser ein Jahr lang für diesen Namen. Wer später zurück auf HTTP will,
  nimmt einen anderen Namen oder löscht den HSTS-Eintrag im Browser.
- Auch hinter HTTPS gilt: nur ein Zugang, keine Zwei-Faktor-Anmeldung (ADR-0003). Für Zugriff aus
  dem Internet ist ein VPN die bessere Wahl als eine offene Portfreigabe.
