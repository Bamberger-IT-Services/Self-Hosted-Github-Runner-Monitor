#!/usr/bin/env bash
# shellcheck disable=SC1111  # „…“ in den Texten sind gewollte deutsche Anführungszeichen
# Aufräumen der Platte einrichten – für jeden Runner auf dieser VM: GitHub, Forgejo, Gitea, GitLab … (#144).
# Eine volle Platte legt Runner-VM und Hypervisor lahm.
#
#   sudo /opt/runner-monitor/aktuell/einrichten.sh aufraeumen     # üblicher Weg
#   sudo bash deploy/aufraeumen-einrichten.sh                      # direkt (so ruft es runner-einrichten.sh auf)
#
# Richtet ein:
#   1. /usr/local/bin/runner-aufraeumen (aus deploy/runner-aufraeumen)
#   2. jede Nacht gründlich: /etc/cron.daily/runner-aufraeumen, dazu fstrim (gibt freien Platz an den
#      Hypervisor zurück, VM-Platte mit „Discard“) und fstrim.timer
#   3. alle 15 Minuten: runner-aufraeumen.timer räumt auf, wenn auf „/“ weniger als 25 GB frei sind
#   4. GitHub-Runner (/opt/actions-runner, RUNNER_VERZ): zusätzlich vor jedem Job
#      (Hook ACTIONS_RUNNER_HOOK_JOB_STARTED → vor-dem-job.sh)
# Forgejo-, Gitea- und GitLab-Runner kennen keinen Hook, der vor jedem Job auf dem Rechner läuft – für sie
# wirkt der Timer (Schritt 3).
#
# Idempotent: ein zweiter Aufruf bringt alles auf den Stand dieses Pakets. Ein laufender Job wird nie
# gestört: das Skript räumt dann nur schonend auf, und der GitHub-Runner wird erst neu gestartet, wenn
# er frei ist (nur nötig, wenn der Hook neu eingetragen wird).
set -euo pipefail

HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GH_VERZ="${RUNNER_VERZ:-/opt/actions-runner}"
W="${AUFRAEUMEN_WURZEL:-}"   # nur für Tests (tests/test_aufraeumen.py): alles unter diesem Ordner statt unter /
SKRIPT="$W/usr/local/bin/runner-aufraeumen"
NACHT="$W/etc/cron.daily/runner-aufraeumen"
SYSTEMD="$W/etc/systemd/system"
SCHWELLE=25   # wie runner-aufraeumen.service und der Hook

ok() { printf '  \033[32m✓\033[0m %s\n' "$*"; }
hinweis() { printf '  \033[33m!\033[0m %s\n' "$*"; }

[ "$(id -u)" = 0 ] || { echo "Bitte mit sudo ausführen." >&2; exit 1; }
for f in "$HIER/runner-aufraeumen" "$HIER/systemd/runner-aufraeumen.service" "$HIER/systemd/runner-aufraeumen.timer"; do
  [ -f "$f" ] || { echo "Fehlt: $f (bitte aus dem vollständigen Paket aufrufen)" >&2; exit 1; }
done
install -d -m 755 "$(dirname "$SKRIPT")" "$(dirname "$NACHT")" "$SYSTEMD"   # fehlt cron, fehlt auch /etc/cron.daily

# Datei als root atomar ersetzen: neue Datei im selben Ordner, dann umbenennen. Ein Symlink am Ziel wird
# ersetzt, nicht verfolgt. Der Name der Zwischendatei beginnt mit „.“, run-parts (cron.daily) überspringt ihn.
ersetze() {
  local quelle="$1" ziel="$2" modus="$3" tmp
  tmp="$(mktemp "$(dirname "$ziel")/.$(basename "$ziel").XXXXXX")"
  cat "$quelle" > "$tmp"
  chown root:root "$tmp"; chmod "$modus" "$tmp"
  mv -f "$tmp" "$ziel"
}

# 1. Skript
ersetze "$HIER/runner-aufraeumen" "$SKRIPT" 755
ok "Skript $SKRIPT (gründlich; läuft ein Job, nur schonend)"

# 2. Jede Nacht gründlich, dazu fstrim
rm -f "$W"/etc/cron.weekly/*runner-aufraeumen   # Vorgänger älterer Fassungen (wöchentlich, auch mit Präfix)
ersetze /dev/stdin "$NACHT" 755 <<'CRON'
#!/bin/sh
# Runner-Monitor (#144): jede Nacht gründlich aufräumen und freien Platz an den Hypervisor zurückgeben.
# Eingerichtet von „einrichten.sh aufraeumen“ – Änderungen hier gehen beim nächsten Aufruf verloren.
/usr/local/bin/runner-aufraeumen >/dev/null 2>&1
fstrim -a >/dev/null 2>&1 || true
CRON
systemctl enable --now fstrim.timer >/dev/null 2>&1 || true
if systemctl is-active --quiet cron.service 2>/dev/null || command -v anacron >/dev/null 2>&1; then
  ok "jede Nacht gründlich: $NACHT, dazu fstrim"
else
  hinweis "$NACHT angelegt, aber cron läuft nicht – bitte einschalten: sudo apt install cron && sudo systemctl enable --now cron"
fi

# 3. Alle 15 Minuten unter $SCHWELLE GB frei (für alle Runner, auch ohne Hook)
install -m 644 -o root -g root "$HIER/systemd/runner-aufraeumen.service" "$HIER/systemd/runner-aufraeumen.timer" "$SYSTEMD/"
systemctl daemon-reload
systemctl enable --now runner-aufraeumen.timer >/dev/null 2>&1 || true
if systemctl is-active --quiet runner-aufraeumen.timer; then
  ok "alle 15 Minuten: unter $SCHWELLE GB frei wird aufgeräumt (runner-aufraeumen.timer)"
else
  hinweis "runner-aufraeumen.timer läuft nicht – prüfen: systemctl status runner-aufraeumen.timer"
fi

# 4. GitHub-Runner: zusätzlich vor jedem Job. Hook und .env gehören dem Runner-Benutzer und liegen in seinem
# Ordner – deshalb schreibt sie dieser Benutzer selbst (runuser), nie root: ein Symlink dort führt dann nur
# zu Dateien, die der Runner-Benutzer ohnehin ändern darf.
if [ -f "$GH_VERZ/.runner" ] && [ ! -L "$GH_VERZ" ]; then
  NUTZER="${RUNNER_NUTZER:-$(stat -c %U "$GH_VERZ")}"
  # shellcheck disable=SC2016  # $1, $v … wertet die innere Shell aus
  ergebnis="$(runuser -u "$NUTZER" -- sh -c '
    set -e
    v="$1"; schwelle="$2"
    tmp="$(mktemp "$v/.vor-dem-job.XXXXXX")"
    printf "#!/bin/sh\n# Aufräumen vor jedem Job (#144), eingerichtet von „einrichten.sh aufraeumen“\nexec /usr/local/bin/runner-aufraeumen --vor-dem-job %s\n" "$schwelle" > "$tmp"
    chmod 755 "$tmp"
    mv -f "$tmp" "$v/vor-dem-job.sh"
    zeile="$(grep "^ACTIONS_RUNNER_HOOK_JOB_STARTED=" "$v/.env" 2>/dev/null | tail -n 1 || true)"
    if [ -z "$zeile" ]; then
      echo "ACTIONS_RUNNER_HOOK_JOB_STARTED=$v/vor-dem-job.sh" >> "$v/.env"
      echo neu
    elif [ "$zeile" != "ACTIONS_RUNNER_HOOK_JOB_STARTED=$v/vor-dem-job.sh" ]; then
      echo fremd
    else
      echo da
    fi' sh "$GH_VERZ" "$SCHWELLE")" || ergebnis=fehler
  case "$ergebnis" in
    da) ok "GitHub-Runner: vor jedem Job unter $SCHWELLE GB frei (Hook vor-dem-job.sh)" ;;
    fremd) hinweis "GitHub-Runner: $GH_VERZ/.env nennt einen anderen Hook vor dem Job – bleibt unverändert; dort selbst /usr/local/bin/runner-aufraeumen --vor-dem-job $SCHWELLE aufrufen" ;;
    neu)
      # Der Dienst liest .env nur beim Start. Neu starten, aber nie mitten in einem Job.
      if pgrep -f 'Runner\.Worker' >/dev/null 2>&1; then
        # Neustart einmalig nachholen, sobald kein Job mehr läuft (überlebt das Abmelden von SSH).
        systemctl stop runner-neustart >/dev/null 2>&1 || true
        systemd-run --unit=runner-neustart --description="Runner neu starten, sobald frei" /bin/sh -c \
          'while pgrep -f "[R]unner\.Worker" >/dev/null; do sleep 20; done; systemctl try-restart "actions.runner.*"' >/dev/null
        ok "GitHub-Runner: vor jedem Job unter $SCHWELLE GB frei – der Runner arbeitet gerade, Neustart folgt automatisch nach dem Job"
        echo "    (prüfen: systemctl status runner-neustart)"
      else
        systemctl try-restart 'actions.runner.*' >/dev/null 2>&1 || true
        ok "GitHub-Runner: vor jedem Job unter $SCHWELLE GB frei (Hook eingetragen, Dienst neu gestartet)"
      fi ;;
    *) hinweis "GitHub-Runner: Hook vor dem Job nicht eingerichtet (Benutzer $NUTZER, Ordner $GH_VERZ) – der Timer räumt trotzdem alle 15 Minuten auf" ;;
  esac
fi
