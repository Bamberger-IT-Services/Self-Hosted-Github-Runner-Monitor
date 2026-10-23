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

echo "1/5 Pakete"
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

echo "2/5 Benutzer $NUTZER"
id "$NUTZER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$NUTZER"
usermod -aG docker "$NUTZER"
# Die Workflows installieren Werkzeuge mit sudo apt-get (wie auf den GitHub-Runnern).
echo "$NUTZER ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-$NUTZER"
chmod 440 "/etc/sudoers.d/90-$NUTZER"

echo "3/5 Runner-Programm"
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

echo "4/5 Registrierung"
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

echo "5/5 Platz sichern"
# Die Platte darf nie volllaufen (eine volle Platte legt Runner-VM und Hypervisor lahm).
# 1) Vor JEDEM Job: unter 25 GB frei → alte Container, Images, Volumes und Build-Cache weg.
# 2) Jede Nacht: gründlich aufräumen (Build-Cache auf 20 GB begrenzen) und freien Platz per
#    fstrim an Proxmox zurückgeben (VM-Platte mit „Discard“ einstellen).
rm -f /etc/cron.weekly/*runner-aufraeumen   # Vorgänger älterer Fassungen (wöchentlich, auch mit Präfix)
cat > /usr/local/bin/runner-aufraeumen <<'SKRIPT'
#!/bin/sh
# Aufruf: runner-aufraeumen [mindest-frei-in-GB]  (ohne Angabe: immer gründlich)
GRENZE="${1:-}"
FREI="$(df --output=avail -BG / | tail -n 1 | tr -dc 0-9)"
if [ -n "$GRENZE" ] && [ "$FREI" -ge "$GRENZE" ]; then exit 0; fi
echo "runner-aufraeumen: ${FREI} GB frei – räume auf"
docker container prune -f >/dev/null 2>&1 || true
docker image prune -af --filter "until=24h" >/dev/null 2>&1 || true
docker volume prune -af >/dev/null 2>&1 || true
docker builder prune -af --max-used-space 20gb >/dev/null 2>&1 \
  || docker builder prune -af --keep-storage 20GB >/dev/null 2>&1 || true
find /opt/actions-runner/_diag -name '*.log' -mtime +7 -delete 2>/dev/null || true
journalctl --vacuum-size=500M >/dev/null 2>&1 || true
echo "runner-aufraeumen: jetzt $(df --output=avail -BG / | tail -n 1 | tr -dc 0-9) GB frei"
SKRIPT
chmod 755 /usr/local/bin/runner-aufraeumen
cat > "$VERZ/vor-dem-job.sh" <<'HOOK'
#!/bin/sh
/usr/local/bin/runner-aufraeumen 25
HOOK
chmod 755 "$VERZ/vor-dem-job.sh"; chown "$NUTZER:$NUTZER" "$VERZ/vor-dem-job.sh"
if ! grep -q '^ACTIONS_RUNNER_HOOK_JOB_STARTED=' "$VERZ/.env" 2>/dev/null; then
  echo "ACTIONS_RUNNER_HOOK_JOB_STARTED=$VERZ/vor-dem-job.sh" >> "$VERZ/.env"
  # Der Dienst liest .env nur beim Start. Neu starten, aber nie mitten in einem Job.
  if pgrep -f Runner.Worker >/dev/null 2>&1; then
    # Neustart einmalig nachholen, sobald kein Job mehr läuft (überlebt das Abmelden von SSH).
    systemctl stop runner-neustart >/dev/null 2>&1 || true
    systemd-run --unit=runner-neustart --description="Runner neu starten, sobald frei" /bin/sh -c \
      'while pgrep -f "[R]unner.Worker" >/dev/null; do sleep 20; done; systemctl restart "actions.runner.*"' >/dev/null
    echo "    Runner arbeitet gerade – Neustart folgt automatisch, sobald der Job fertig ist"
    echo "    (prüfen: systemctl status runner-neustart)"
  else
    ( cd "$VERZ" || exit 0; ./svc.sh stop >/dev/null 2>&1; ./svc.sh start >/dev/null 2>&1 ) || true
  fi
fi
cat > /etc/cron.daily/runner-aufraeumen <<'CRON'
#!/bin/sh
/usr/local/bin/runner-aufraeumen >/dev/null 2>&1
fstrim -a >/dev/null 2>&1 || true
CRON
chmod 755 /etc/cron.daily/runner-aufraeumen
systemctl enable --now fstrim.timer >/dev/null 2>&1 || true

echo
echo "Fertig. Runner: $NAME ($ZIEL_URL), Labels: self-hosted, linux, x64${LABELS:+, ${LABELS//,/, }}"
echo "Workflows wählen ihn mit  runs-on: [self-hosted${LABELS:+, ${LABELS%%,*}}]  – Umschalten je Repository: docs/RUNNER.md."
