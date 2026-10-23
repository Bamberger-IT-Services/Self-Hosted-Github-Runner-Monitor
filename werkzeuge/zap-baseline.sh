#!/usr/bin/env bash
# OWASP-ZAP-Baseline (nur passive Regeln) gegen eine lokale Testinstanz – Issue #20.
# Nie gegen die produktive VM. Braucht Java und ZAP (Crossplatform-Paket von zaproxy/zaproxy).
#
#   werkzeuge/zap-baseline.sh <zap-ordner> <ziel> <bericht-ordner> [rm_sitzung=…]
#   z. B. werkzeuge/zap-baseline.sh ~/ZAP_2.17.0 http://127.0.0.1:8091 /tmp/zap
#
# Ohne Sitzung prüft ZAP Anmeldung und öffentliche Seiten, mit Sitzung (Cookie einer Testanmeldung)
# auch das Dashboard. Ergebnis: zap-baseline.md und .json im Bericht-Ordner.
set -euo pipefail

zap="${1:?ZAP-Ordner fehlt}"
ziel="${2:?Ziel fehlt, z. B. http://127.0.0.1:8091}"
bericht="${3:?Bericht-Ordner fehlt}"
sitzung="${4:-}"

case "$ziel" in
  http://127.0.0.1:*|http://localhost:*) ;;
  *) echo "Nur gegen eine lokale Testinstanz (127.0.0.1/localhost): $ziel" >&2; exit 2 ;;
esac

hier="$(cd "$(dirname "$0")" && pwd)"
arbeit="$(mktemp -d)"
trap 'rm -rf "$arbeit"' EXIT
mkdir -p "$bericht"

# ZAP setzt Umgebungsvariablen nicht überall ein – Werte hier eintragen.
ersetze() { printf '%s' "$1" | sed -e 's/[\/&|]/\\&/g'; }
sed -e "s|\${ZAP_ZIEL}|$(ersetze "$ziel")|g" \
    -e "s|\${ZAP_SITZUNG}|$(ersetze "$sitzung")|g" \
    -e "s|\${ZAP_BERICHT}|$(ersetze "$bericht")|g" \
    "$hier/zap-baseline.yaml" > "$arbeit/plan.yaml"
if [ -z "$sitzung" ]; then
  # ohne Sitzung keinen leeren Cookie-Kopf mitschicken
  sed -i '/- type: replacer/,/replacementString/d' "$arbeit/plan.yaml"
fi

"$zap/zap.sh" -cmd -dir "$arbeit/home" -autorun "$arbeit/plan.yaml"
echo "Bericht: $bericht/zap-baseline.md"
