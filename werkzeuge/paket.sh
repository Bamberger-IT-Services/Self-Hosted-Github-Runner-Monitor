#!/usr/bin/env bash
# Baut das Release-Paket dist/runner-monitor-X.Y.Z.tar.gz und dessen SHA-256-Prüfsumme.
# Inhalt: nur, was auf der VM gebraucht wird (Programm, Oberfläche, Dienste, Skripte, Doku-Kern).
set -euo pipefail
cd "$(dirname "$0")/.."
v="$(tr -d '[:space:]' < VERSION)"
name="runner-monitor-$v"
rm -rf dist && mkdir -p "dist/$name"
cp -r runner_monitor web deploy VERSION einrichten.sh README.md CHANGELOG.md "dist/$name/"
[ -f LICENSE ] && cp LICENSE "dist/$name/"
find "dist/$name" -name '__pycache__' -prune -exec rm -rf {} +
# Reproduzierbar: feste Zeit, feste Reihenfolge, keine Besitzer
tar --sort=name --mtime='2000-01-01 00:00Z' --owner=0 --group=0 --numeric-owner \
  -C dist -czf "dist/$name.tar.gz" "$name"
(cd dist && sha256sum "$name.tar.gz" > "$name.tar.gz.sha256")
rm -rf "dist/$name"
cat "dist/$name.tar.gz.sha256"
