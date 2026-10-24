"""Runner-Monitor: Live-Dashboard für einen selbst gehosteten GitHub-Actions-Runner.

Nur Python-Standardbibliothek (ADR-0001). Zwei Dienste:

* ``runner_monitor.server``  – Weboberfläche + Server-Sent Events, läuft als eigener,
  unprivilegierter Benutzer ``runner-monitor``.
* ``runner_monitor.sammler`` – läuft als root: Docker-Status, GitHub-Abfrage, Update-Prüfung.
  Schreibt nur JSON-Dateien nach ``/run/runner-monitor/``.
"""

VERSION = "0.6.1"
