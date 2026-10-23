#!/usr/bin/env bash
# Runner-Monitor einrichten, warten und entfernen (Ubuntu 22.04/24.04, als root).
#
#   sudo ./einrichten.sh                 # installieren oder auf diese Version aktualisieren
#   sudo ./einrichten.sh code            # neuen Einrichtungscode anzeigen (60 Min. gültig)
#   sudo ./einrichten.sh passwort        # Zugang zurücksetzen – danach neu im Browser anlegen
#   sudo ./einrichten.sh token           # GitHub-Token eintragen oder erneuern
#   sudo ./einrichten.sh runner          # GitHub-Runner auf dieser VM einrichten (--umziehen: neu anmelden)
#   sudo ./einrichten.sh aktualisieren   # neueste Version von GitHub installieren
#   sudo ./einrichten.sh zurueck         # zur vorherigen Version zurück
#   sudo ./einrichten.sh status          # Dienste und Version anzeigen
#   sudo ./einrichten.sh entfernen       # Dienste entfernen (Daten bleiben, außer mit --alles)
#
# Ablauf beim ersten Mal: Dateien nach /opt/runner-monitor, Benutzer runner-monitor, Firewall
# (SSH bleibt offen, Port 8090 nur aus dem lokalen Netz), Dienste starten, Runner suchen.
# Am Ende stehen Adresse und Einrichtungscode da – der Rest passiert im Browser.
# Doku: docs/EINRICHTUNG.md · Keine echten IPs/Namen in Issues posten (öffentliches Repo).
# shellcheck disable=SC1091  # /etc/os-release gibt es nur auf dem Zielsystem
set -euo pipefail

QUELLE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="$(tr -d '[:space:]' < "$QUELLE/VERSION")"
BASIS=/opt/runner-monitor
DATEN=/var/lib/runner-monitor
ETC=/etc/runner-monitor
NUTZER=runner-monitor
SYSTEMD=/etc/systemd/system
RUNNER_VERZ="${RUNNER_VERZ:-/opt/actions-runner}"
PYTHON=/usr/bin/python3

fett() { printf '\033[1m%s\033[0m\n' "$*"; }
ok() { printf '  \033[32m✓\033[0m %s\n' "$*"; }
hinweis() { printf '  \033[33m!\033[0m %s\n' "$*"; }
fehler() { printf '\033[31mFehler:\033[0m %s\n' "$*" >&2; exit 1; }
frage() { local a; read -r -p "  $1 [j/N] " a </dev/tty || true; [[ "${a,,}" == j* ]]; }

[ "$(id -u)" = 0 ] || fehler "Bitte mit sudo ausführen: sudo $0 ${*}"

port() { grep -E '^MONITOR_PORT=' "$ETC/konfig.env" 2>/dev/null | cut -d= -f2 | tr -dc 0-9 || true; }
PORT="$(port)"; PORT="${PORT:-8090}"
eigene_ip() { ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}'; }
lan_netz() {
  local dev; dev="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')"
  ip -4 -o addr show dev "$dev" 2>/dev/null | awk '{print $4; exit}' | "$PYTHON" -c 'import ipaddress,sys; print(ipaddress.ip_interface(sys.stdin.read().strip()).network)' 2>/dev/null || true
}

runner_name() { "$PYTHON" -c 'import json,sys; print(json.loads(open(sys.argv[1],encoding="utf-8-sig").read()).get("agentName",""))' "$RUNNER_VERZ/.runner" 2>/dev/null || true; }
runner_unit() { systemctl list-units --all --type=service --no-legend --plain 'actions.runner.*' 2>/dev/null | awk '{print $1; exit}'; }

neuer_code() {
  [ -s "$DATEN/zugang.json" ] && { hinweis "Zugang ist schon angelegt – kein Code nötig. Passwort vergessen? sudo $0 passwort"; return; }
  local code
  code="$(cd "$BASIS/aktuell" && "$PYTHON" -c '
import pathlib, sys
from runner_monitor import zugang
c = zugang.neuer_code()
zugang.schreibe_code(pathlib.Path(sys.argv[1]), c)
print(c)' "$DATEN/einrichtungscode.json")"
  chown "$NUTZER:$NUTZER" "$DATEN/einrichtungscode.json"
  echo
  fett "Weiter im Browser:  http://$(eigene_ip):$PORT"
  echo "  Einrichtungscode:   $code   (60 Minuten gültig, neuer Code: sudo $0 code)"
  echo
}

systempruefung() {
  local name unit ver fw=false
  name="$(runner_name)"; unit="$(runner_unit)"
  ver="$( [ -x "$RUNNER_VERZ/bin/Runner.Listener" ] && "$RUNNER_VERZ/bin/Runner.Listener" --version 2>/dev/null || true)"
  command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active" && fw=true
  "$PYTHON" - "$DATEN/systempruefung.json" "$VERSION" "$PORT" "$name" "$unit" "$ver" "$fw" <<'PY'
import json, sys, time, socket
ziel, version, port, name, unit, ver, fw = sys.argv[1:]
json.dump({"zeit": time.time(), "vm": socket.gethostname(), "port": int(port), "monitorVersion": version,
           "runner": {"gefunden": bool(name), "name": name, "dienst": unit, "version": ver},
           "firewall": {"aktiv": fw == "true"}}, open(ziel, "w", encoding="utf-8"))
PY
  chown "$NUTZER:$NUTZER" "$DATEN/systempruefung.json"; chmod 640 "$DATEN/systempruefung.json"
}

alte_ansicht_entfernen() {
  # Vorgänger (ttyd-Terminalansicht aus monitor-einrichten.sh) nutzte denselben Dienstnamen.
  if [ -f "$SYSTEMD/runner-monitor.service" ] && grep -q ttyd "$SYSTEMD/runner-monitor.service"; then
    hinweis "alte Terminalansicht (ttyd) gefunden – wird ersetzt"
    systemctl disable --now runner-monitor.service runner-monitor-repos.timer >/dev/null 2>&1 || true
    rm -f "$SYSTEMD/runner-monitor-repos.service" "$SYSTEMD/runner-monitor-repos.timer" \
          /usr/local/bin/runner-monitor /usr/local/bin/runner-logs /usr/local/bin/runner-status /usr/local/bin/runner-repos
    if [ -s /etc/runner-monitor-github-token ] && [ ! -s "$ETC/github-token" ]; then
      install -m 600 /etc/runner-monitor-github-token "$ETC/github-token"; ok "GitHub-Token übernommen"
    fi
    hinweis "/etc/runner-monitor.env (alter ttyd-Zugang) wird nicht mehr gebraucht und kann gelöscht werden"
  fi
}

installiere_dateien() {
  local ziel="$BASIS/versionen/$VERSION"
  install -d -m 755 "$BASIS/versionen"
  if [ "$QUELLE" != "$ziel" ]; then
    rm -rf "$ziel.neu"; install -d -m 755 "$ziel.neu"
    cp -r "$QUELLE/runner_monitor" "$QUELLE/web" "$QUELLE/deploy" "$QUELLE/VERSION" "$QUELLE/einrichten.sh" "$ziel.neu/"
    [ -f "$QUELLE/LICENSE" ] && cp "$QUELLE/LICENSE" "$ziel.neu/"
    chown -R root:root "$ziel.neu"; chmod -R a+rX,go-w "$ziel.neu"
    rm -rf "$ziel"; mv "$ziel.neu" "$ziel"
  fi
  ln -sfn "versionen/$VERSION" "$BASIS/aktuell.neu" && mv -T "$BASIS/aktuell.neu" "$BASIS/aktuell"
  ok "Version $VERSION in $ziel"
}

installieren() {
  fett "Runner-Monitor $VERSION einrichten"
  "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || fehler "Python 3.10 oder neuer nötig (Ubuntu 22.04+)."
  grep -qi ubuntu /etc/os-release || hinweis "getestet für Ubuntu – hier: $(. /etc/os-release && echo "${PRETTY_NAME:-unbekannt}")"

  echo "1/6 Benutzer und Ordner"
  id "$NUTZER" >/dev/null 2>&1 || useradd --system --no-create-home --home-dir "$DATEN" --shell /usr/sbin/nologin "$NUTZER"
  usermod -aG systemd-journal "$NUTZER"
  install -d -o "$NUTZER" -g "$NUTZER" -m 750 "$DATEN" "$DATEN/auftraege"
  install -d -o root -g "$NUTZER" -m 750 "$ETC"
  [ -f "$ETC/konfig.env" ] || install -o root -g "$NUTZER" -m 640 "$QUELLE/deploy/konfig.env.example" "$ETC/konfig.env"
  sed -i 's/^MONITOR_ORG=beispiel-org$/MONITOR_ORG=/' "$ETC/konfig.env"
  ok "Benutzer $NUTZER (ohne Anmeldung), Daten in $DATEN, Einstellungen in $ETC/konfig.env"

  echo "2/6 Programm"
  alte_ansicht_entfernen
  installiere_dateien

  echo "3/6 Runner"
  if [ -f "$RUNNER_VERZ/.runner" ]; then
    ok "Runner $(runner_name) gefunden ($(runner_unit || true))"
  else
    hinweis "kein GitHub-Runner in $RUNNER_VERZ gefunden"
    if frage "Runner jetzt einrichten? (braucht einen Registrierungs-Token von GitHub)"; then runner_einrichten; else
      echo "    Später: sudo $0 runner – bis dahin zeigt der Monitor nur die VM."; fi
  fi

  echo "4/6 Firewall"
  if command -v ufw >/dev/null; then
    local netz; netz="$(lan_netz)"
    ufw allow OpenSSH >/dev/null 2>&1 || ufw allow 22/tcp >/dev/null
    if [ -n "$netz" ]; then
      ufw allow from "$netz" to any port "$PORT" proto tcp comment 'runner-monitor' >/dev/null
      ok "Port $PORT nur aus $netz erlaubt, SSH bleibt offen"
    else
      hinweis "lokales Netz nicht erkannt – Port $PORT bitte von Hand freigeben: sudo ufw allow from <netz> to any port $PORT proto tcp"
    fi
    if ! ufw status | grep -q "Status: active"; then
      if frage "Firewall (ufw) ist aus. Jetzt einschalten? SSH bleibt erreichbar."; then ufw --force enable >/dev/null; ok "ufw eingeschaltet"; else hinweis "ufw bleibt aus – Port $PORT ist für alle erreichbar, die die VM erreichen"; fi
    fi
  else
    hinweis "ufw nicht installiert (sudo apt install ufw) – Port $PORT ist offen"
  fi

  echo "5/6 Dienste"
  install -m 644 "$QUELLE"/deploy/systemd/runner-monitor*.service "$QUELLE"/deploy/systemd/runner-monitor-update.path "$SYSTEMD/"
  systemctl daemon-reload
  systemctl enable runner-monitor-sammler.service runner-monitor.service runner-monitor-update.path >/dev/null
  systemctl restart runner-monitor-sammler.service runner-monitor.service runner-monitor-update.path
  local _; for _ in $(seq 1 20); do curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && break; sleep 0.5; done
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then ok "Dienste laufen"; else fehler "Monitor antwortet nicht: journalctl -u runner-monitor -n 30"; fi
  systempruefung

  echo "6/6 Einrichtung im Browser"
  if [ -s "$DATEN/zugang.json" ]; then
    ok "Zugang besteht schon – Aktualisierung fertig: http://$(eigene_ip):$PORT"
  else
    neuer_code
  fi
}

token() {
  local t org
  echo "Fine-grained Token mit Read-only für Actions und Metadata (optional: Self-hosted runners)."
  echo "Erstellen: github.com › Settings › Developer settings › Fine-grained tokens"
  read -r -s -p "  Token (Eingabe bleibt unsichtbar): " t </dev/tty; echo
  [[ "$t" =~ ^[A-Za-z0-9_]{20,255}$ ]] || fehler "Das sieht nicht wie ein GitHub-Token aus."
  install -d -o root -g "$NUTZER" -m 750 "$ETC"
  (umask 077; printf '%s\n' "$t" > "$ETC/github-token.neu"); mv "$ETC/github-token.neu" "$ETC/github-token"
  ok "gespeichert in $ETC/github-token (nur root)"
  org="$(grep -E '^MONITOR_ORG=' "$ETC/konfig.env" 2>/dev/null | cut -d= -f2)"
  if [ -z "$org" ] && [ ! -s "$DATEN/einstellungen.json" ]; then
    read -r -p "  GitHub-Organisation: " org </dev/tty
    [[ "$org" =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}$ ]] || fehler "Ungültiger Name."
    sed -i "s/^MONITOR_ORG=.*/MONITOR_ORG=$org/" "$ETC/konfig.env"
  fi
  systemctl restart runner-monitor-sammler.service runner-monitor.service
  ok "übernommen – die Workflows erscheinen in spätestens 30 s"
}

runner_einrichten() {
  local ziel tok labels umziehen=()
  [ "${1:-}" = "--umziehen" ] && umziehen=(--umziehen)
  echo "  Registrierungs-Token: GitHub › Organisation › Settings › Actions › Runners › "New self-hosted runner" (1 Stunde gültig)."
  read -r -p "  Organisation (z. B. beispiel-org): " ziel </dev/tty
  [[ "$ziel" =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}$ ]] || fehler "Ungültiger Name."
  labels="${RUNNER_LABELS:-}"
  [ -n "$labels" ] || read -r -p "  Zusätzliche Labels, mit Komma getrennt (leer: keine): " labels </dev/tty
  [[ -z "$labels" || "$labels" =~ ^[A-Za-z0-9._,-]+$ ]] || fehler "Labels nur aus Buchstaben, Ziffern, Punkt, Minus, Komma."
  read -r -s -p "  Registrierungs-Token: " tok </dev/tty; echo
  RUNNER_ZIEL="https://github.com/$ziel" RUNNER_LABELS="$labels" bash "$QUELLE/deploy/runner-einrichten.sh" "${umziehen[@]}" "$tok"
  grep -q '^MONITOR_ORG=.\+' "$ETC/konfig.env" 2>/dev/null || sed -i "s/^MONITOR_ORG=.*/MONITOR_ORG=$ziel/" "$ETC/konfig.env" 2>/dev/null || true
  [ -d "$DATEN" ] && systempruefung || true
}

passwort() {
  frage "Zugang (Benutzer und Passwort) zurücksetzen? Alle Browser werden abgemeldet." || exit 0
  rm -f "$DATEN/zugang.json" "$DATEN/sitzungen.json" "$DATEN/sperren.json"
  systemctl restart runner-monitor.service
  ok "zurückgesetzt – GitHub-Token und Einstellungen bleiben"
  neuer_code
}

aktualisieren() {
  local installiert
  installiert="$(readlink "$BASIS/aktuell" 2>/dev/null | xargs -r basename || true)"
  if [ -n "$installiert" ] && [ "$installiert" != "$VERSION" ] && \
     "$PYTHON" -c 'import sys; a,b=[tuple(map(int,v.split("."))) for v in sys.argv[1:]]; sys.exit(a<=b)' "$VERSION" "$installiert"; then
    echo "Dieses Paket ($VERSION) ist neuer als die installierte Version ($installiert) – installiere es."
    installieren; return
  fi
  local neu; neu="$("$PYTHON" -c 'import json; print(json.load(open("/run/runner-monitor/release.json")).get("version",""))' 2>/dev/null || true)"
  [ -n "$neu" ] || fehler "Noch keine Release-Information. Gleich nochmal versuchen (der Sammler prüft beim Start)."
  [ "$neu" != "$installiert" ] || { ok "Version $installiert ist aktuell."; return; }
  printf '{"version": "%s", "zeit": %s}\n' "$neu" "$(date +%s)" > "$DATEN/auftraege/update"
  chown "$NUTZER:$NUTZER" "$DATEN/auftraege/update"
  echo "Update auf $neu läuft … (Protokoll: journalctl -u runner-monitor-update -f)"
  systemctl start runner-monitor-update.service || true
  "$PYTHON" -c 'import json; d=json.load(open("'"$DATEN"'/update-status.json")); print(d.get("zustand"), d.get("version"), d.get("meldung",""))' 2>/dev/null || true
}

zurueck() { (cd "$BASIS/aktuell" && "$PYTHON" -m runner_monitor.aktualisierer --zurueck); }

status() {
  echo "Version: $(readlink "$BASIS/aktuell" 2>/dev/null | xargs -r basename || echo 'nicht installiert')"
  systemctl --no-pager --lines=0 status runner-monitor.service runner-monitor-sammler.service runner-monitor-update.path 2>/dev/null | grep -E '●|Active:' || true
  echo "Adresse: http://$(eigene_ip):$PORT"
}

entfernen() {
  systemctl disable --now runner-monitor.service runner-monitor-sammler.service runner-monitor-update.path >/dev/null 2>&1 || true
  rm -f "$SYSTEMD"/runner-monitor.service "$SYSTEMD"/runner-monitor-sammler.service "$SYSTEMD"/runner-monitor-update.service "$SYSTEMD"/runner-monitor-update.path
  systemctl daemon-reload
  command -v ufw >/dev/null && ufw status numbered 2>/dev/null | grep -q runner-monitor && \
    while n="$(ufw status numbered | grep runner-monitor | head -1 | sed 's/^\[ *\([0-9]*\)\].*/\1/')"; [ -n "$n" ]; do ufw --force delete "$n" >/dev/null; done
  ok "Dienste und Firewall-Regel entfernt"
  if [ "${1:-}" = "--alles" ] && frage "Auch Programm, Zugang, Token und Einstellungen löschen? Das ist endgültig."; then
    rm -rf "$BASIS" "$DATEN" "$ETC"; userdel "$NUTZER" 2>/dev/null || true
    ok "alles entfernt"
  else
    echo "  Daten bleiben in $BASIS, $DATEN und $ETC (alles löschen: sudo $0 entfernen --alles)."
  fi
}

case "${1:-installieren}" in
  installieren) installieren ;;
  code) neuer_code ;;
  passwort) passwort ;;
  token) token ;;
  runner) runner_einrichten "${2:-}" ;;
  aktualisieren) aktualisieren ;;
  zurueck) zurueck ;;
  status) status ;;
  entfernen) entfernen "${2:-}" ;;
  -h|--help|hilfe) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) fehler "Unbekannter Befehl: $1 (Hilfe: $0 hilfe)" ;;
esac
