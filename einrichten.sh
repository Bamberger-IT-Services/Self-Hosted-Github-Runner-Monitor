#!/usr/bin/env bash
# shellcheck disable=SC1111  # „…“ in den Texten sind gewollte deutsche Anführungszeichen, keine Shell-Quotes (#133)
# Runner-Monitor einrichten, warten und entfernen (Ubuntu 22.04/24.04, als root).
#
#   sudo ./einrichten.sh                 # installieren oder auf diese Version aktualisieren
#   sudo ./einrichten.sh code            # neuen Einrichtungscode anzeigen (60 Min. gültig)
#   sudo ./einrichten.sh passwort        # Zugang zurücksetzen – danach neu im Browser anlegen
#   sudo ./einrichten.sh token           # GitHub-Token eintragen oder erneuern
#   sudo ./einrichten.sh zugang <runner> # Zugangsdaten eines Runners (Forgejo/Gitea/GitLab: mit Server) eintragen (ohne: Liste)
#   sudo ./einrichten.sh runner          # GitHub-Runner auf dieser VM einrichten (--umziehen: neu anmelden)
#   sudo ./einrichten.sh aktualisieren   # neueste Version aus der Update-Quelle installieren
#   sudo ./einrichten.sh quelle          # Update-Quelle wählen: GitHub (Vorgabe) oder Forgejo
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
frage() { local a; read -r -p "    $1 [j/N] " a </dev/tty || true; [[ "${a,,}" == j* ]]; }
frage_ja() { local a; read -r -p "    $1 [J/n] " a </dev/tty || true; [[ "${a,,}" != n* ]]; }
# Ausgabe wie im Design 0.3.0 (Setup-Skript): Abschnitte, Trennlinien, graue Hinweise
abschnitt() { printf '\033[1;94m%s\033[0m\n' "$*"; }
regel() { printf '\033[90m%s\033[0m\n' '──────────────────────────────────────────────────────────'; }
hin() { printf '\033[90m    %s\033[0m\n' "$*"; }

[ "$(id -u)" = 0 ] || fehler "Bitte mit sudo ausführen: sudo $0 ${*}"

port() { grep -E '^MONITOR_PORT=' "$ETC/konfig.env" 2>/dev/null | cut -d= -f2 | tr -dc 0-9 || true; }
PORT="$(port)"; PORT="${PORT:-8090}"
eigene_ip() { ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}' || true; }
lan_netz() {
  local dev; dev="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')" || true
  ip -4 -o addr show dev "$dev" 2>/dev/null | awk '{print $4; exit}' | "$PYTHON" -c 'import ipaddress,sys; print(ipaddress.ip_interface(sys.stdin.read().strip()).network)' 2>/dev/null || true
}

runner_name() { "$PYTHON" -c 'import json,sys; print(json.loads(open(sys.argv[1],encoding="utf-8-sig").read()).get("agentName",""))' "$RUNNER_VERZ/.runner" 2>/dev/null || true; }
runner_unit() { systemctl list-units --all --type=service --no-legend --plain 'actions.runner.*' 2>/dev/null | awk '{print $1; exit}' || true; }

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
  regel
  fett "Fast geschafft. Schließen Sie die Einrichtung im Browser ab:"
  echo
  printf '    \033[1;4;94m%s\033[0m\n' "http://$(eigene_ip):$PORT"
  echo
  printf '    Einrichtungscode: \033[1;30;43m %s \033[0m\033[90m   (gilt 60 Minuten, danach: sudo %s code)\033[0m\n' "$code" "$BASIS/aktuell/einrichten.sh"
  echo
}

systempruefung() {
  local name unit ver fw=false netz aktiv=false
  name="$(runner_name)"; unit="$(runner_unit)"; netz="$(lan_netz)"
  [ -n "$unit" ] && systemctl is-active --quiet "$unit" && aktiv=true
  ver=""
  if [ -x "$RUNNER_VERZ/bin/Runner.Listener" ]; then ver="$("$RUNNER_VERZ/bin/Runner.Listener" --version 2>/dev/null || true)"; fi
  command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active" && fw=true
  "$PYTHON" - "$DATEN/systempruefung.json" "$VERSION" "$PORT" "$name" "$unit" "$ver" "$fw" "$netz" "$aktiv" <<'PY'
import json, sys, time, socket
ziel, version, port, name, unit, ver, fw, netz, aktiv = sys.argv[1:]
json.dump({"zeit": time.time(), "vm": socket.gethostname(), "port": int(port), "monitorVersion": version,
           "runner": {"gefunden": bool(name), "name": name, "dienst": unit, "version": ver, "aktiv": aktiv == "true"},
           "firewall": {"aktiv": fw == "true", "netz": netz}}, open(ziel, "w", encoding="utf-8"))
PY
  chown "$NUTZER:$NUTZER" "$DATEN/systempruefung.json"; chmod 640 "$DATEN/systempruefung.json"
}

# Abschnitt „Runner auf dieser VM“ (Design 0.8.0, #91): runner_monitor.erkennung sucht GitHub-,
# Forgejo-, Gitea-, GitLab- und unbekannte Runner (systemd-Units, Prozesse, .runner-Dateien,
# Server-API ohne Zugangsdaten) und gibt die Zeilen aus. Rückgabe 0 = gefunden, 3 = keiner.
# Vorhandene Runner bleiben unverändert; ohne Fund bietet das Skript die Einrichtung an.
runner_suchen() {
  local rc=0 farbe=""
  abschnitt "Runner auf dieser VM"
  if [ -t 1 ]; then farbe=--farbe; fi
  # timeout: harte Grenze, falls DNS oder ein Server hängt (--foreground: Strg+C wirkt sofort)
  (cd "$QUELLE" && PYTHONDONTWRITEBYTECODE=1 timeout --foreground 60 \
      "$PYTHON" -m runner_monitor.erkennung --text --einrichtung \
      ${farbe:+"$farbe"} \
      --runner-verz "$RUNNER_VERZ" --zuordnung "$ETC/runner.json" \
      --token-datei "$ETC/github-token") || rc=$?
  case "$rc" in
    0) ;;
    3)
      hinweis "Kein Runner gefunden (geprüft: systemd-Units, Prozesse, .runner-Dateien)."
      hin "Der Monitor kann trotzdem die VM überwachen. Später Runner ergänzen:"
      hin "  sudo $BASIS/aktuell/einrichten.sh runner"
      if frage "Jetzt einen Runner einrichten?"; then runner_einrichten
      else hin "→ Im Browser: „Von Hand zuordnen“ oder „Ohne Runner fortfahren“"; fi
      ;;
    *) hinweis "Runner-Erkennung nicht möglich – der Monitor sucht später selbst." ;;
  esac
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
  local os py docker_v dev ip netz
  echo
  fett "Runner-Monitor $VERSION – Einrichtung"
  regel
  abschnitt "System prüfen"
  "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || fehler "Python 3.10 oder neuer nötig (Ubuntu 22.04+)."
  os="$(. /etc/os-release && echo "${PRETTY_NAME:-unbekannt}")"
  py="$("$PYTHON" -c 'import sys; print(f"Python {sys.version_info.major}.{sys.version_info.minor}")')"
  docker_v="$(docker --version 2>/dev/null | sed -n 's/^Docker version \([0-9]*\.[0-9]*\).*/Docker \1/p')" || true
  ok "$os, $py${docker_v:+, $docker_v}"
  grep -qi ubuntu /etc/os-release || hinweis "getestet für Ubuntu – hier: $os"
  dev="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')" || true
  ip="$(eigene_ip)"; netz="$(lan_netz)"
  ok "Netz: ${ip:-unbekannt}${dev:+ ($dev)}${netz:+, lokales Netz $netz}"
  runner_suchen

  abschnitt "Monitor einrichten"
  id "$NUTZER" >/dev/null 2>&1 || useradd --system --no-create-home --home-dir "$DATEN" --shell /usr/sbin/nologin "$NUTZER"
  ok "Benutzer $NUTZER angelegt (kein root, keine Anmeldung)"
  usermod -aG systemd-journal "$NUTZER"
  install -d -o "$NUTZER" -g "$NUTZER" -m 750 "$DATEN" "$DATEN/auftraege"
  install -d -o root -g "$NUTZER" -m 750 "$ETC"
  [ -f "$ETC/konfig.env" ] || install -o root -g "$NUTZER" -m 640 "$QUELLE/deploy/konfig.env.example" "$ETC/konfig.env"
  sed -i 's/^MONITOR_ORG=beispiel-org$/MONITOR_ORG=/' "$ETC/konfig.env"
  ok "Leserechte: Systemprotokoll, Docker-Status, Runner-Logs"
  alte_ansicht_entfernen
  installiere_dateien
  token_uebernehmen
  install -m 644 "$QUELLE"/deploy/systemd/runner-monitor*.service "$QUELLE"/deploy/systemd/runner-monitor-update.path "$SYSTEMD/"
  systemctl daemon-reload
  systemctl enable runner-monitor-sammler.service runner-monitor.service runner-monitor-update.path >/dev/null
  systemctl restart runner-monitor-sammler.service runner-monitor.service runner-monitor-update.path
  local _; for _ in $(seq 1 20); do curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && break; sleep 0.5; done
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then ok "Dienst runner-monitor gestartet, Port $PORT"; else fehler "Monitor antwortet nicht: journalctl -u runner-monitor -n 30"; fi

  abschnitt "Firewall (ufw)"
  if command -v ufw >/dev/null; then
    ufw allow OpenSSH >/dev/null 2>&1 || ufw allow 22/tcp >/dev/null
    ok "SSH (22) bleibt erlaubt"
    if [ -n "$netz" ]; then
      ufw allow from "$netz" to any port "$PORT" proto tcp comment 'runner-monitor' >/dev/null
      ok "Port $PORT nur aus dem lokalen Netz $netz"
    else
      hinweis "lokales Netz nicht erkannt – Port $PORT bitte von Hand freigeben: sudo ufw allow from <netz> to any port $PORT proto tcp"
    fi
    if ufw status | grep -q "Status: active"; then ok "ufw aktiv"
    elif frage "Firewall (ufw) ist aus. Jetzt einschalten? SSH bleibt erreichbar."; then ufw --force enable >/dev/null; ok "ufw aktiviert"
    else hinweis "ufw bleibt aus – Port $PORT ist für alle erreichbar, die die VM erreichen"; fi
  else
    hinweis "ufw nicht installiert (sudo apt install ufw) – Port $PORT ist offen"
  fi
  systempruefung

  if [ -s "$DATEN/zugang.json" ]; then
    regel
    fett "Fertig. Der Zugang besteht schon, der Monitor ist auf $VERSION:"
    echo
    printf '    \033[1;4;94m%s\033[0m\n\n' "http://${ip:-$(eigene_ip)}:$PORT"
  else
    neuer_code
  fi
}

token() {
  local t org neu
  echo "Fine-grained Token mit Read-only für Actions und Metadata (optional: Self-hosted runners)."
  echo "Erstellen: github.com › Settings › Developer settings › Fine-grained tokens (Resource owner: die Organisation)"
  read -r -s -p "  Token (Eingabe bleibt unsichtbar): " t </dev/tty; echo
  [[ "$t" =~ ^[A-Za-z0-9_]{20,255}$ ]] || fehler "Das sieht nicht wie ein GitHub-Token aus."
  install -d -o root -g "$NUTZER" -m 750 "$ETC"
  (umask 077; printf '%s\n' "$t" > "$ETC/github-token.neu"); mv "$ETC/github-token.neu" "$ETC/github-token"
  ok "gespeichert in $ETC/github-token (nur root)"
  # Auch je Runner ablegen (#92, E-19), sonst gälte eine ältere Kopie in zugang/ weiter.
  token_kopieren "auch in" --ueberschreiben
  # Organisation immer anbieten. Die Einstellung aus dem Browser hat Vorrang vor konfig.env,
  # deshalb beide Stellen lesen und beide schreiben (sonst fehlt sie nach „Überspringen“).
  org="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("org",""))' "$DATEN/einstellungen.json" 2>/dev/null || true)"
  [ -n "$org" ] || org="$(grep -E '^MONITOR_ORG=' "$ETC/konfig.env" 2>/dev/null | cut -d= -f2 || true)"
  read -r -p "  GitHub-Organisation${org:+ [Enter: $org]}: " neu </dev/tty || true
  neu="${neu:-$org}"
  [[ "$neu" =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}$ ]] || fehler "Ungültiger Name der Organisation: ${neu:-leer}"
  if grep -q '^MONITOR_ORG=' "$ETC/konfig.env" 2>/dev/null; then sed -i "s/^MONITOR_ORG=.*/MONITOR_ORG=$neu/" "$ETC/konfig.env"
  else echo "MONITOR_ORG=$neu" >> "$ETC/konfig.env"; fi
  if [ -f "$DATEN/einstellungen.json" ]; then
    "$PYTHON" -c '
import json, os, sys
pfad, org = sys.argv[1], sys.argv[2]
try:
    daten = json.load(open(pfad, encoding="utf-8"))
except (OSError, ValueError):
    daten = {}
daten["org"] = org
info = os.stat(pfad)
with open(pfad + ".neu", "w", encoding="utf-8") as datei:
    json.dump(daten, datei)
os.chown(pfad + ".neu", info.st_uid, info.st_gid)
os.chmod(pfad + ".neu", info.st_mode & 0o777)
os.replace(pfad + ".neu", pfad)' "$DATEN/einstellungen.json" "$neu"
  fi
  ok "Organisation: $neu"
  systemctl restart runner-monitor-sammler.service runner-monitor.service
  ok "übernommen – die Workflows erscheinen in spätestens 30 s"
}

# Zugangsdaten je Runner (#92, E-19): $ETC/zugang/<runner>.token, Verzeichnis root 0700, Datei 0600 –
# nur der Sammler (root) liest sie, nie über die Weboberfläche. Beim GitHub-Runner wird auch der alte
# Ort $ETC/github-token geschrieben (Rückfall für ältere Versionen und den Update-Hilfsdienst, bis #94/#96).
token_helfer() { (cd "$QUELLE" && PYTHONDONTWRITEBYTECODE=1 "$PYTHON" -m runner_monitor.anbieter.token "$@" 2>/dev/null); }

# $ETC/github-token nach $ETC/zugang/<id>.token kopieren. Rückgabe des Helfers: 0 geschrieben, 3 nichts zu
# tun (kein Runner, kein Token, Kopie aktuell), 2 Schreibfehler – dann hat er die veraltete Kopie
# entfernt, und es gilt der alte Ort. Das Token erscheint nie in der Ausgabe.
token_kopieren() {
  local text="$1" rid rc=0; shift
  rid="$(token_helfer kopiere "$@" --alt "$ETC/github-token" --verz "$ETC/zugang" --runner-verz "$RUNNER_VERZ")" || rc=$?
  case "$rc" in
    0) ok "$text $ETC/zugang/$rid.token (je Runner, nur root)" ;;
    3) ;;
    2) hinweis "Token je Runner nicht geschrieben${rid:+ ($ETC/zugang/$rid.token)} – veraltete Kopie entfernt, es gilt $ETC/github-token. Rechte prüfen: sudo ls -ld $ETC/zugang" ;;
    *) hinweis "Token je Runner nicht geprüft (Rückgabe $rc) – der Sammler übernimmt es beim Start" ;;
  esac
}

# Bisheriges GitHub-Token je Runner ablegen – Kopie, der alte Ort bleibt (der Sammler tut das beim
# Start ebenso; hier steht es sichtbar in der Ausgabe). Ist der alte Ort neuer, wird die Kopie ersetzt.
token_uebernehmen() {
  [ -s "$ETC/github-token" ] || return 0
  token_kopieren "GitHub-Token übernommen nach"
}

# Forgejo, Gitea, GitLab (#120, E-22, E-26): Server, Organisation und Token auf der VM. Prüfen und
# Schreiben macht runner_monitor.anbieter.anbindung mit den Regeln von Erkennung und Sammler – das
# Skript fragt nur ab. Das Token geht über die Standardeingabe (printf ist eingebaut, also nie als
# Argument eines Prozesses) und erscheint nie in der Ausgabe.
anbindung_helfer() { (cd "$QUELLE" && PYTHONDONTWRITEBYTECODE=1 "$PYTHON" -m runner_monitor.anbieter.anbindung "$@" 2>/dev/null); }

# Wert zu einem Schlüssel aus der Ausgabe von „anbindung info“ (Zeilen schluessel=wert)
wert_aus() {
  local zeile
  while IFS= read -r zeile; do
    if [[ "$zeile" == "$2="* ]]; then printf '%s\n' "${zeile#"$2="}"; return 0; fi
  done <<< "$1"
  return 0
}

# Zeilen „art|text“ des Helfers ausgeben (ok, warn, fehler, hin)
zeilen_ausgeben() {
  local art text
  while IFS='|' read -r art text; do
    case "$art" in
      ok) ok "$text" ;;
      warn) hinweis "$text" ;;
      fehler) printf '  \033[31m✗\033[0m %s\n' "$text" ;;
      hin) hin "$text" ;;
    esac
  done <<< "$1"
}

zugang_server() {
  local id="$1" info="$2" dienst name server_alt org_alt http_alt token_da stand braucht_org vor
  local s eingabe neu rc org="" t="" behalten=false aktiv=false ausgabe
  local -a http=() org_arg=() stand_arg=() token_arg=()
  dienst="$(wert_aus "$info" dienst)"; server_alt="$(wert_aus "$info" server)"; org_alt="$(wert_aus "$info" org)"
  http_alt="$(wert_aus "$info" http)"
  token_da="$(wert_aus "$info" token)"; stand="$(wert_aus "$info" stand)"; braucht_org="$(wert_aus "$info" braucht_org)"
  case "$dienst" in forgejo) name=Forgejo ;; gitea) name=Gitea ;; *) name=GitLab ;; esac
  vor="${server_alt:-$(wert_aus "$info" vorschlag)}"

  abschnitt "Zugang für $id ($name)"
  if [ "$dienst" = gitlab ]; then
    hin "Token: GitLab › Access tokens, Bereich read_api (nur lesen). Server ohne /api/v4."
  else
    hin "Token: $name › Einstellungen › Anwendungen, repository und organization „Lesen“. Server ohne /api/v1."
  fi
  if [ -n "$server_alt" ]; then hin "Bisher in $ETC/runner.json: $server_alt"
  elif [ -n "$vor" ]; then hin "Vorschlag aus der Erkennung: $vor (bitte prüfen)"; fi

  # 1. Server – https://; http:// nur nach ausdrücklicher Rückfrage (E-21)
  while true; do
    read -r -p "  Server${vor:+ [Enter: $vor]}: " eingabe </dev/tty || fehler "Abgebrochen – nichts geändert."
    s="${eingabe:-$vor}"
    rc=0; neu="$(anbindung_helfer pruefe-server -- "$s")" || rc=$?
    if [ "$rc" = 0 ]; then http=(); break; fi
    if [ "$rc" = 4 ] && [ "$neu" = "$server_alt" ] && [ "$http_alt" = 1 ]; then
      hin "http_erlaubt bleibt (für diese Adresse schon ausdrücklich erlaubt)."; http=(--http-erlaubt); break
    fi
    if [ "$rc" = 4 ]; then
      hinweis "Mit http:// geht das Token unverschlüsselt durchs Netz – nur in einem vertrauenswürdigen lokalen Netz."
      if frage "Trotzdem http:// erlauben (\"http_erlaubt\": true in runner.json)?"; then http=(--http-erlaubt); break; fi
      hin "Dann bitte die https://-Adresse angeben."
    else
      hinweis "${neu:-Keine gültige Adresse.}"
    fi
  done
  s="$neu"

  # 2. Organisation (Forgejo, Gitea – GitLab braucht keine)
  if [ "$braucht_org" = 1 ]; then
    while true; do
      read -r -p "  Organisation (oder Benutzer)${org_alt:+ [Enter: $org_alt]}: " eingabe </dev/tty || fehler "Abgebrochen – nichts geändert."
      org="${eingabe:-$org_alt}"
      rc=0; neu="$(anbindung_helfer pruefe-org -- "$org")" || rc=$?
      if [ "$rc" = 0 ]; then org="$neu"; org_arg=(--org "$org"); break; fi
      hinweis "${neu:-Ungültige Organisation.}"
    done
  fi

  # 3. Token – bei neuer Adresse Pflicht: das bisherige geht nie an eine andere Adresse (E-22)
  if [ "$token_da" = 1 ] && [ "$s" = "$server_alt" ]; then
    behalten=true
  elif [ "$token_da" = 1 ]; then
    hinweis "Die Adresse ändert sich – das bisherige Token wird gelöscht und nicht an $s geschickt."
  fi
  while true; do
    if $behalten; then read -r -s -p "  Token für $id (Enter: bisheriges behalten, Eingabe bleibt unsichtbar): " t </dev/tty || fehler "Abgebrochen – nichts geändert."
    else read -r -s -p "  Token für $id (Eingabe bleibt unsichtbar): " t </dev/tty || fehler "Abgebrochen – nichts geändert."; fi
    echo
    if [ -z "$t" ] && $behalten; then break; fi
    [ -n "$t" ] || fehler "Ohne Token – nichts geändert."
    # Länge getrennt: {16,512} überschreitet RE_DUP_MAX mancher regex-Bibliotheken (255)
    if [[ "$t" =~ ^[A-Za-z0-9._~+/=-]+$ ]] && [ "${#t}" -ge 16 ] && [ "${#t}" -le 512 ]; then token_arg=(--token-stdin); break; fi
    hinweis "Das Token ist zu kurz oder enthält ungültige Zeichen."
  done

  # 4. Stand aus der Einrichtung: „Grundüberwachung“ verhindert die Abfrage beim Dienst
  if [ "$stand" = grund ]; then
    hinweis "In der Einrichtung steht dieser Runner auf „Grundüberwachung“ – so fragt der Monitor $name nicht ab."
    if frage_ja "Stand aufheben, damit der Runner angebunden wird?"; then stand_arg=(--stand-aufheben); fi
    # Ein noch nicht abgeholter Auftrag der Einrichtung im Browser setzt „grund“ sonst gleich wieder
    if [ "${#stand_arg[@]}" -gt 0 ] && [ -e "$DATEN/auftraege/runner-zuordnung" ]; then
      hinweis "Im Browser wartet noch eine gespeicherte Auswahl („Weiter“ in Schritt Runner) – sie kann „Grundüberwachung“ wieder setzen."
      hin "Danach diesen Befehl erneut ausführen oder im Browser den Runner nicht auf „Grundüberwachung“ lassen."
    fi
  elif [ "$stand" = ignoriert ]; then
    hinweis "Der Runner ist in der Einrichtung „ignoriert“ – angebunden wird er erst, wenn Sie das dort zurücknehmen."
  fi

  # 5. Schreiben – der Sammler ruht so lange, damit keine Runde Adresse und Token verschieden liest
  install -d -o root -g "$NUTZER" -m 750 "$ETC"
  if systemctl is-active --quiet runner-monitor-sammler.service 2>/dev/null; then
    aktiv=true
    # auch bei Strg+C oder Fehler wieder starten
    trap 'systemctl start runner-monitor-sammler.service 2>/dev/null || true' EXIT
    trap 'exit 130' INT TERM
    systemctl stop runner-monitor-sammler.service 2>/dev/null || true
  fi
  rc=0
  if [ "${#token_arg[@]}" -gt 0 ]; then
    ausgabe="$(printf '%s\n' "$t" | anbindung_helfer setze --runner "$id" --zuordnung "$ETC/runner.json" \
      --zugang-verz "$ETC/zugang" --server "$s" "${org_arg[@]}" "${http[@]}" "${stand_arg[@]}" "${token_arg[@]}")" || rc=$?
  else
    ausgabe="$(anbindung_helfer setze --runner "$id" --zuordnung "$ETC/runner.json" --zugang-verz "$ETC/zugang" \
      --server "$s" "${org_arg[@]}" "${http[@]}" "${stand_arg[@]}" </dev/null)" || rc=$?
  fi
  t=""
  if $aktiv; then trap - EXIT INT TERM; systemctl start runner-monitor-sammler.service 2>/dev/null || true; fi
  zeilen_ausgeben "$ausgabe"
  [ "$rc" = 0 ] || fehler "Nicht gespeichert (Rückgabe $rc) – siehe oben."

  # 6. Verbindung prüfen – nur lesend, über den Adapter, mit harter Frist
  abschnitt "Verbindung prüfen"
  rc=0
  ausgabe="$(cd "$QUELLE" && PYTHONDONTWRITEBYTECODE=1 timeout --foreground 60 "$PYTHON" -m runner_monitor.anbieter.anbindung \
    pruefe-verbindung --runner "$id" --erkennung /run/runner-monitor/erkennung.json --zuordnung "$ETC/runner.json" \
    --zugang-verz "$ETC/zugang" 2>/dev/null)" || rc=$?
  zeilen_ausgeben "$ausgabe"
  case "$rc" in
    0) ok "übernommen – der Sammler fragt in spätestens 30 s ab (Info zeigt den Stand)" ;;
    124) hinweis "Prüfung abgebrochen (keine Antwort innerhalb von 60 s) – gespeichert ist trotzdem alles." ;;
    *) hin "Gespeichert ist alles; nach einer Korrektur erneut: sudo $0 zugang $id" ;;
  esac
}

zugang() {
  local id="${1:-}" t gid info="" dienst=""
  if [ -z "$id" ]; then
    echo "Aufruf: sudo $0 zugang <runner>"
    echo "Erkannte Runner (ID, Dienst, Name):"
    token_helfer liste --erkennung /run/runner-monitor/erkennung.json --runner-verz "$RUNNER_VERZ" || hin "noch keine Erkennung – der Sammler sucht beim Start und alle 6 Stunden"
    exit 1
  fi
  [[ "$id" =~ ^[a-z0-9_]([a-z0-9._-]{0,62}[a-z0-9_])?$ ]] || fehler "Ungültige Runner-ID: $id (Liste: sudo $0 zugang)"
  gid="$(token_helfer github-id --runner-verz "$RUNNER_VERZ")" || true
  # Forgejo, Gitea, GitLab: auch Server und Organisation (#120); alle anderen wie bisher nur das Token
  if [ "$id" != "$gid" ]; then
    info="$(anbindung_helfer info --runner "$id" --erkennung /run/runner-monitor/erkennung.json \
      --zuordnung "$ETC/runner.json" --zugang-verz "$ETC/zugang")" || info=""
    dienst="$(wert_aus "$info" dienst)"
  fi
  case "$dienst" in
    forgejo|gitea|gitlab) zugang_server "$id" "$info"; return 0 ;;
  esac
  # Weder erkannt noch in runner.json: Dienst unbekannt – nicht still auf „nur Token“ zurückfallen
  if [ "$id" != "$gid" ] && [ "$(wert_aus "$info" gefunden)" != 1 ] && [ "$(wert_aus "$info" eingetragen)" != 1 ]; then
    hinweis "Runner $id ist (noch) nicht in der Erkennung – sein Dienst ist unbekannt."
    hin "Bei Forgejo, Gitea und GitLab fragt dieser Befehl auch Server und Organisation ab, sobald der Runner erkannt ist:"
    hin "  Liste: sudo $0 zugang   ·   neu suchen: im Browser „Neu erkennen“ oder sudo systemctl restart runner-monitor-sammler"
    frage "Trotzdem nur ein Token für $id ablegen?" || exit 1
  fi
  if [ "$id" = "$gid" ]; then
    echo "GitHub: Fine-grained Token mit Read-only für Actions und Metadata (optional: Self-hosted runners)."
  else
    echo "Token mit Leserechten beim Dienst dieses Runners (Forgejo/Gitea: read:repository und read:organization; GitLab: read_api)."
    hin "Genutzt, sobald $ETC/runner.json für diesen Runner den Server nennt – Forgejo/Gitea zusätzlich die Organisation (docs/EINRICHTUNG.md)."
  fi
  read -r -s -p "  Token für $id (Eingabe bleibt unsichtbar): " t </dev/tty; echo
  if [ "$id" = "$gid" ]; then
    [[ "$t" =~ ^[A-Za-z0-9_]{20,255}$ ]] || fehler "Das sieht nicht wie ein GitHub-Token aus."
  else
    [[ "$t" =~ ^[A-Za-z0-9._~+/=-]{16,512}$ ]] || fehler "Das Token ist zu kurz oder enthält ungültige Zeichen."
  fi
  install -d -o root -g "$NUTZER" -m 750 "$ETC"
  install -d -o root -g root -m 700 "$ETC/zugang"
  (umask 077; printf '%s\n' "$t" > "$ETC/zugang/$id.token.neu"); mv "$ETC/zugang/$id.token.neu" "$ETC/zugang/$id.token"
  ok "gespeichert in $ETC/zugang/$id.token (nur root)"
  if [ "$id" = "$gid" ]; then
    (umask 077; printf '%s\n' "$t" > "$ETC/github-token.neu"); mv "$ETC/github-token.neu" "$ETC/github-token"
    ok "auch in $ETC/github-token (Rückfall für ältere Versionen und Updates)"
  fi
  systemctl try-restart runner-monitor-sammler.service 2>/dev/null || true
  ok "übernommen – der Sammler fragt in spätestens 30 s neu ab"
}

runner_einrichten() {
  local ziel tok labels umziehen=()
  [ "${1:-}" = "--umziehen" ] && umziehen=(--umziehen)
  echo '  Registrierungs-Token: GitHub › Organisation › Settings › Actions › Runners › „New self-hosted runner“ (1 Stunde gültig).'
  read -r -p "  Organisation (z. B. beispiel-org): " ziel </dev/tty
  [[ "$ziel" =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}$ ]] || fehler "Ungültiger Name."
  labels="${RUNNER_LABELS:-}"
  [ -n "$labels" ] || read -r -p "  Zusätzliche Labels, mit Komma getrennt (leer: keine): " labels </dev/tty
  [[ -z "$labels" || "$labels" =~ ^[A-Za-z0-9._,-]+$ ]] || fehler "Labels nur aus Buchstaben, Ziffern, Punkt, Minus, Komma."
  read -r -s -p "  Registrierungs-Token: " tok </dev/tty; echo
  RUNNER_ZIEL="https://github.com/$ziel" RUNNER_LABELS="$labels" bash "$QUELLE/deploy/runner-einrichten.sh" "${umziehen[@]}" "$tok"
  grep -q '^MONITOR_ORG=.\+' "$ETC/konfig.env" 2>/dev/null || sed -i "s/^MONITOR_ORG=.*/MONITOR_ORG=$ziel/" "$ETC/konfig.env" 2>/dev/null || true
  if [ -d "$DATEN" ]; then systempruefung; fi
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

# Update-Quelle (#138, ADR-0007): GitHub (Vorgabe) oder ein Forgejo-Server ohne Anmeldung. Prüfen und
# Schreiben macht runner_monitor.quelle mit den Regeln der Konfiguration – das Skript fragt nur ab.
quelle_helfer() { (cd "$QUELLE" && PYTHONDONTWRITEBYTECODE=1 "$PYTHON" -m runner_monitor.quelle "$@" 2>/dev/null); }

quelle_anzeigen() {
  local info q b
  info="$(quelle_helfer zeige --konfig "$ETC/konfig.env")" || info=""
  q="$(wert_aus "$info" quelle)"; b="$(wert_aus "$info" basis)"
  if [ "$q" = forgejo ]; then printf 'Forgejo (%s)\n' "$b"; else echo "GitHub"; fi
}

quelle() {
  local info q_alt b_alt eingabe s rc wahl ausgabe repo http=()
  [ -f "$ETC/konfig.env" ] || fehler "Der Monitor ist noch nicht eingerichtet ($ETC/konfig.env fehlt): sudo $0"
  info="$(quelle_helfer zeige --konfig "$ETC/konfig.env")" || info=""
  q_alt="$(wert_aus "$info" quelle)"; b_alt="$(wert_aus "$info" basis)"
  abschnitt "Update-Quelle"
  hin "Bisher: $(quelle_anzeigen)"
  [ -z "$(wert_aus "$info" fehler)" ] || hinweis "konfig.env: $(wert_aus "$info" fehler)"
  hin "GitHub ist die Vorgabe. Forgejo nur, wenn die Releases dort ohne Anmeldung lesbar sind."
  hin "Die Herkunft prüft der Monitor in beiden Fällen gegen die GitHub-Attestierung (docs/UPDATE.md)."
  read -r -p "  Quelle: 1 = GitHub, 2 = Forgejo [Enter: $([ "$q_alt" = forgejo ] && echo 2 || echo 1)]: " wahl </dev/tty || fehler "Abgebrochen – nichts geändert."
  wahl="${wahl:-$([ "$q_alt" = forgejo ] && echo 2 || echo 1)}"
  case "$wahl" in
    1)
      ausgabe="$(quelle_helfer setze --konfig "$ETC/konfig.env" --quelle github)" || fehler "Nicht gespeichert – siehe oben."
      zeilen_ausgeben "$ausgabe"
      ;;
    2)
      while true; do
        read -r -p "  Forgejo-Adresse (ohne /api/v1)${b_alt:+ [Enter: $b_alt]}: " eingabe </dev/tty || fehler "Abgebrochen – nichts geändert."
        s="${eingabe:-$b_alt}"
        rc=0; s="$(quelle_helfer pruefe-adresse -- "$s")" || rc=$?
        if [ "$rc" = 0 ]; then http=(); break; fi
        if [ "$rc" = 4 ]; then
          hinweis "Mit http:// kann jemand im Netz Versionsangabe, Archiv und Prüfsumme austauschen."
          hin "Schutz bleibt dann nur die GitHub-Attestierung (GitHub-CLI und Token auf der VM, besser MONITOR_UPDATE_HERKUNFT=pflicht)."
          if frage "Trotzdem http:// erlauben (MONITOR_UPDATE_HTTP_ERLAUBT=1)?"; then http=(--http-erlaubt); break; fi
          hin "Dann bitte die https://-Adresse angeben."
        else
          hinweis "${s:-Keine gültige Adresse.}"
        fi
      done
      abschnitt "Forgejo prüfen"
      repo="$(grep -E '^MONITOR_RELEASE_REPO=' "$ETC/konfig.env" 2>/dev/null | cut -d= -f2 | tr -d "\"'" || true)"
      repo="${repo:-Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor}"
      rc=0; ausgabe="$(cd "$QUELLE" && PYTHONDONTWRITEBYTECODE=1 timeout --foreground 60 "$PYTHON" -m runner_monitor.quelle \
        abfrage --basis "$s" "${http[@]}" --repo "$repo" 2>/dev/null)" || rc=$?
      zeilen_ausgeben "$ausgabe"
      if [ "$rc" != 0 ]; then frage "Forgejo antwortet nicht wie erwartet. Trotzdem speichern?" || fehler "Nichts geändert."; fi
      ausgabe="$(quelle_helfer setze --konfig "$ETC/konfig.env" --quelle forgejo --basis "$s" "${http[@]}")" || { zeilen_ausgeben "$ausgabe"; fehler "Nicht gespeichert."; }
      zeilen_ausgeben "$ausgabe"
      ;;
    *) fehler "Bitte 1 oder 2 – nichts geändert." ;;
  esac
  systemctl try-restart runner-monitor-sammler.service runner-monitor.service 2>/dev/null || true
  ok "übernommen – der Sammler fragt die neue Quelle beim Start, Info › Updates zeigt sie"
}

status() {
  echo "Version: $(readlink "$BASIS/aktuell" 2>/dev/null | xargs -r basename || echo 'nicht installiert')"
  echo "Update-Quelle: $(quelle_anzeigen)"
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
  zugang) zugang "${2:-}" ;;
  runner) runner_einrichten "${2:-}" ;;
  aktualisieren) aktualisieren ;;
  zurueck) zurueck ;;
  quelle) quelle ;;
  status) status ;;
  entfernen) entfernen "${2:-}" ;;
  -h|--help|hilfe) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) fehler "Unbekannter Befehl: $1 (Hilfe: $0 hilfe)" ;;
esac
