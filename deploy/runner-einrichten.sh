#!/usr/bin/env bash
# Selbst gehosteter GitHub-Actions-Runner auf einer Ubuntu-VM.
# Übernommen aus https://github.com/Bamberger-IT-Services/Public/tree/main/anweisungen/vorlagen
# (runner-einrichten.sh) – hier mit frei wählbarer Organisation (RUNNER_ZIEL, Pflicht).
# Wird normalerweise über „sudo ./einrichten.sh runner“ aufgerufen.
#
#   sudo bash runner-einrichten.sh <REGISTRIERUNGS-TOKEN>              # neu einrichten
#   sudo bash runner-einrichten.sh --umziehen <REGISTRIERUNGS-TOKEN>   # vorhandenen Runner
#                                    (z. B. bisher nur bei einem Repo angemeldet) auf die Organisation umstellen
#
# Das Token kommt aus GitHub › Ihre Organisation › Settings › Actions ›
# Runners › „New runner“ › „New self-hosted runner“ (gilt eine Stunde). NICHT auf einer
# Produktiv-VM ausführen: Die Tests starten eigene Datenbanken und Container.
#
# Idempotent: Ein zweiter Aufruf (ohne Token) aktualisiert Pakete und Aufräumen und lässt
# einen schon registrierten Runner stehen (außer mit --umziehen). Ein laufender Job wird nie
# unterbrochen.
# shellcheck disable=SC1091  # /etc/os-release gibt es nur auf dem Zielsystem
set -euo pipefail

UMZIEHEN=0
if [ "${1:-}" = "--umziehen" ]; then UMZIEHEN=1; shift; fi
TOKEN="${1:-}"
ZIEL_URL="${RUNNER_ZIEL:-}"
[ -n "$ZIEL_URL" ] || { echo "RUNNER_ZIEL fehlt, z. B. RUNNER_ZIEL=https://github.com/beispiel-org" >&2; exit 1; }
NUTZER="${RUNNER_NUTZER:-github-runner}"
NAME="${RUNNER_NAME:-runner-$(hostname -s)}"
# Zusätzliche Labels (self-hosted, linux, x64 setzt GitHub selbst), z. B. RUNNER_LABELS=bits
LABELS="${RUNNER_LABELS:-}"
VERZ="/opt/actions-runner"

[ "$(id -u)" = 0 ] || { echo "Bitte mit sudo ausführen." >&2; exit 1; }
# os-release in einer Subshell lesen: Die Datei setzt u. a. NAME und würde sonst den
# Runner-Namen überschreiben (der erste Runner hieß deshalb „Ubuntu“).
OS_ID="$(. /etc/os-release && echo "${ID:-}")"
OS_CODENAME="$(. /etc/os-release && echo "${VERSION_CODENAME:-}")"
[ "$OS_ID" = ubuntu ] || echo "Hinweis: getestet für Ubuntu, gefunden: $(. /etc/os-release && echo "${PRETTY_NAME:-unbekannt}")."

echo "1/6 Pakete"
apt-get update -q
apt-get install -y -q ca-certificates curl git jq unzip zip python3 python3-venv build-essential \
  postgresql-common gnupg lsb-release
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${OS_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker

echo "2/6 Benutzer $NUTZER"
id "$NUTZER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$NUTZER"
usermod -aG docker "$NUTZER"
# Die Workflows installieren Werkzeuge mit sudo apt-get (wie auf den GitHub-Runnern).
echo "$NUTZER ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-$NUTZER"
chmod 440 "/etc/sudoers.d/90-$NUTZER"

echo "3/6 Runner-Programm"
install -d -o "$NUTZER" -g "$NUTZER" "$VERZ"
if [ ! -x "$VERZ/config.sh" ]; then
  version="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest | jq -r .tag_name | sed 's/^v//')"
  arch="$(uname -m)"; case "$arch" in x86_64) arch=x64 ;; aarch64) arch=arm64 ;; esac
  datei="actions-runner-linux-${arch}-${version}.tar.gz"
  curl -fsSL -o "/tmp/$datei" "https://github.com/actions/runner/releases/download/v${version}/${datei}"
  tar -xzf "/tmp/$datei" -C "$VERZ" && rm -f "/tmp/$datei"
  chown -R "$NUTZER:$NUTZER" "$VERZ"
  "$VERZ/bin/installdependencies.sh" >/dev/null
fi

echo "4/6 Registrierung"
if [ "$UMZIEHEN" = 1 ] && [ -f "$VERZ/.runner" ]; then
  [ -n "$TOKEN" ] || { echo "Registrierungs-Token fehlt: sudo bash $0 --umziehen <TOKEN>" >&2; exit 1; }
  echo "    bisherige Registrierung ($(jq -r .gitHubUrl "$VERZ/.runner" 2>/dev/null || echo ?)) wird ersetzt"
  ( cd "$VERZ" || exit 0; ./svc.sh stop >/dev/null 2>&1 || true; ./svc.sh uninstall >/dev/null 2>&1 || true )
  # Nur die lokale Anmeldung entfernen; den alten Eintrag in GitHub (dann „Offline“)
  # unter Settings › Actions › Runners entfernen.
  rm -f "$VERZ/.runner" "$VERZ/.credentials" "$VERZ/.credentials_rsaparams"
fi
if [ -f "$VERZ/.runner" ]; then
  echo "    bereits registriert ($(jq -r .agentName "$VERZ/.runner" 2>/dev/null || echo ?)) – übersprungen"
else
  [ -n "$TOKEN" ] || { echo "Registrierungs-Token fehlt: sudo bash $0 <TOKEN>" >&2; exit 1; }
  sudo -u "$NUTZER" "$VERZ/config.sh" --unattended --url "$ZIEL_URL" --token "$TOKEN" \
    --name "$NAME" ${LABELS:+--labels "$LABELS"} --work _work --replace
fi
( cd "$VERZ" || exit 0; ./svc.sh install "$NUTZER" >/dev/null 2>&1 || true; ./svc.sh start >/dev/null 2>&1 || true )

echo "5/6 Platz sichern"
# Die Platte darf nie volllaufen (eine volle Platte legt Runner-VM und Hypervisor lahm). Gemeinsam für alle
# Runner in aufraeumen-einrichten.sh (#144, auch „einrichten.sh aufraeumen“): /usr/local/bin/runner-aufraeumen,
# jede Nacht gründlich mit fstrim, alle 15 Minuten unter 25 GB frei – und hier zusätzlich vor JEDEM Job
# (Hook vor-dem-job.sh). Ein laufender Job wird nie gestört.
RUNNER_VERZ="$VERZ" RUNNER_NUTZER="$NUTZER" bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/aufraeumen-einrichten.sh" \
  || echo "    Aufräumen nicht vollständig eingerichtet – später erneut: sudo /opt/runner-monitor/aktuell/einrichten.sh aufraeumen"

echo
echo "Fertig. Runner: $NAME ($ZIEL_URL), Labels: self-hosted, linux, x64${LABELS:+, ${LABELS//,/, }}"
echo "Workflows wählen ihn mit  runs-on: [self-hosted${LABELS:+, ${LABELS%%,*}}]  – Umschalten je Repository: docs/RUNNER.md."

echo "6/6 Speicher"
# Sprengt ein Job den Arbeitsspeicher, beendet der Kernel einen Prozess (OOM-Killer). Ohne
# Vorkehrung stoppt systemd dann den GANZEN Runner-Dienst (OOMPolicy=stop), und runsvc.sh startet
# ihn nicht neu. So scheitert nur der Job, und ein abgestürzter Dienst startet wieder (Issue #67).
UNIT="$(cat "$VERZ/.service" 2>/dev/null || true)"
[ -n "$UNIT" ] || UNIT="$(systemctl list-units --all --plain --no-legend 'actions.runner.*' | awk 'NR==1{print $1}')"
if [ -n "$UNIT" ]; then
  dropin="/etc/systemd/system/$UNIT.d/speicher.conf"
  soll="$(printf '[Service]\nOOMPolicy=continue\nRestart=on-failure\nRestartSec=15\n')"
  if [ "$(cat "$dropin" 2>/dev/null || true)" != "$soll" ]; then
    install -d "/etc/systemd/system/$UNIT.d"
    printf '%s\n' "$soll" > "$dropin"
    systemctl daemon-reload   # greift ohne Neustart, ein laufender Job bleibt unberührt
    echo "    $UNIT: OOMPolicy=continue, Restart=on-failure"
  else
    echo "    $UNIT: Speicher-Einstellung schon gesetzt"
  fi
else
  echo "    Runner-Dienst nicht gefunden – Speicher-Einstellung übersprungen"
fi
# Swap als Puffer für Spitzen (Builds, Images). Nur anlegen, wenn es noch keinen gibt und genug
# Platz frei ist. Mehr RAM ersetzt er nicht (docs/RUNNER.md › Wie viel Arbeitsspeicher?).
RAM_MB="$(awk '/^MemTotal:/{print int($2/1024)}' /proc/meminfo)"
if [ -n "$(swapon --noheadings --show 2>/dev/null)" ]; then
  echo "    Swap vorhanden: $(swapon --noheadings --show=SIZE 2>/dev/null | paste -sd+ -)"
elif [ -e /swapfile ]; then
  echo "    /swapfile liegt da, ist aber nicht aktiv – bitte prüfen: swapon /swapfile"
else
  if [ "$RAM_MB" -ge 16000 ]; then SWAP_GB=2; else SWAP_GB=4; fi
  FREI_GB="$(df --output=avail -BG / | tail -n 1 | tr -dc 0-9)"
  if [ "$FREI_GB" -ge $((SWAP_GB + 10)) ]; then
    fallocate -l "${SWAP_GB}G" /swapfile
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    [ -e /etc/sysctl.d/99-swap.conf ] || [ -e /etc/sysctl.d/99-runner-swap.conf ] \
      || { echo 'vm.swappiness=10' > /etc/sysctl.d/99-runner-swap.conf; sysctl -q --system >/dev/null 2>&1 || true; }
    echo "    Swap angelegt: /swapfile, ${SWAP_GB} GB"
  else
    echo "    Kein Swap angelegt: nur ${FREI_GB} GB frei (nötig: $((SWAP_GB + 10)) GB)"
  fi
fi
if [ "$RAM_MB" -lt 7500 ]; then
  echo "    Hinweis: ${RAM_MB} MB RAM. Für Builds und Docker-Images mindestens 8 GB (docs/RUNNER.md)."
fi
