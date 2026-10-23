"""Start des Weboberflächen-Dienstes: ``python3 -m runner_monitor``.

Für die Entwicklung auf dem Mac (ohne /proc, ohne Anmeldung, nur 127.0.0.1)::

    MONITOR_ENTWICKLUNG=1 python3 -m runner_monitor
    # dann http://127.0.0.1:8090/?demo öffnen
"""

from __future__ import annotations

import logging
import os
import sys

from . import VERSION
from .konfig import KonfigFehler, lade
from .server import erstelle_server


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("runner_monitor")
    try:
        konfig = lade()
    except KonfigFehler as fehler:
        print(f"Konfiguration fehlerhaft: {fehler}", file=sys.stderr)
        raise SystemExit(2) from fehler
    if hasattr(os, "geteuid") and os.geteuid() == 0 and not konfig.entwicklung:
        raise SystemExit("Der Monitor läuft nicht als root. Start über systemd (runner-monitor.service).")
    server = erstelle_server(konfig)
    server.app.zustand.starte()  # type: ignore[attr-defined]
    log.info("Runner-Monitor %s auf http://%s:%s%s", VERSION, konfig.adresse, konfig.port,
             " (Entwicklung: ohne Anmeldung)" if konfig.entwicklung else "")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
