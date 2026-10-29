"""Alles über den Runner selbst: Dienst, Registrierung, Version, Job-Ereignisse und Log.

Quellen (alle ohne root lesbar, der Monitor-Benutzer ist in der Gruppe ``systemd-journal``):

* ``systemctl show``                   – läuft der Dienst ``actions.runner.*``?
* ``journalctl -u 'actions.runner.*'`` – „Running job: X“ und „Job X completed with result: Y“
* ``/opt/actions-runner/.runner``       – Name und Organisation der Registrierung
* ``/opt/actions-runner/_diag/pages/``  – je Schritt eine neue Datei mit der Ausgabe
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

LOG = logging.getLogger("runner_monitor")

UNIT_MUSTER = "actions.runner.*"

# ---------------------------------------------------------------- Registrierung, Dienst


def lies_registrierung(runner_verz: Path) -> dict:
    """Inhalt von ``.runner`` (JSON, oft mit BOM). Leer, wenn kein Runner eingerichtet ist."""
    datei = runner_verz / ".runner"
    try:
        daten = json.loads(datei.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return {
        "name": daten.get("agentName", ""),
        "url": daten.get("gitHubUrl", ""),
        "pool": daten.get("poolName", ""),
    }


_version_cache: tuple[float, str] = (0.0, "")
VERSION_GEFUNDEN_TAKT = 600   # gefundene Version 10 Minuten merken
VERSION_LEER_TAKT = 30        # nichts gefunden (Runner aktualisiert sich gerade …): bald erneut versuchen
DEPS_MAX = 4 * 1024 * 1024
_VERSION = re.compile(r"\d+\.\d+\.\d+")


def version_aus_deps(runner_verz: Path) -> str:
    """Version aus ``bin/Runner.Listener.deps.json`` (Eintrag „Runner.Listener/2.338.1“) – ohne
    das Programm zu starten. Folgt dem Verweis ``bin`` → ``bin.<version>`` nach einem Selbst-Update."""
    datei = runner_verz / "bin" / "Runner.Listener.deps.json"
    try:
        if datei.stat().st_size > DEPS_MAX:
            return ""
        daten = json.loads(datei.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ""
    bibliotheken = daten.get("libraries") if isinstance(daten, dict) else None
    for name in bibliotheken if isinstance(bibliotheken, dict) else ():
        teil = name.partition("/")
        if teil[0] == "Runner.Listener" and _VERSION.fullmatch(teil[2]):
            return teil[2]
    return ""


def version_aus_programm(runner_verz: Path) -> str:
    """Rückfall: ``Runner.Listener --version``. Scheitert unter der systemd-Härtung des Monitors
    leicht (.NET braucht ein beschreibbares Verzeichnis), deshalb nur, wenn deps.json nichts liefert."""
    programm = runner_verz / "bin" / "Runner.Listener"
    try:
        lauf = subprocess.run([str(programm), "--version"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    kandidat = lauf.stdout.strip().splitlines()[-1] if lauf.stdout.strip() else ""
    return kandidat if _VERSION.fullmatch(kandidat) else ""


def runner_version(runner_verz: Path, jetzt: float | None = None) -> str:
    global _version_cache
    jetzt = time.monotonic() if jetzt is None else jetzt
    alter, gemerkt = _version_cache
    if jetzt - alter < (VERSION_GEFUNDEN_TAKT if gemerkt else VERSION_LEER_TAKT):
        return gemerkt
    version = version_aus_deps(runner_verz) or version_aus_programm(runner_verz)
    _version_cache = (jetzt, version)
    return version


def finde_unit() -> str:
    try:
        lauf = subprocess.run(
            ["systemctl", "list-units", UNIT_MUSTER, "--all", "--no-legend", "--plain", "--type=service"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    for zeile in lauf.stdout.splitlines():
        teile = zeile.split()
        if teile and teile[0].startswith("actions.runner."):
            return teile[0]
    return ""


def _systemd_zeit(wert: str) -> float | None:
    # „Thu 2026-10-23 12:02:11 UTC“ oder „n/a“
    treffer = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", wert or "")
    if not treffer:
        return None
    return datetime.strptime(treffer.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()


MAX_NEUSTARTS = 10**6


def _neustarts(wert: str) -> int | None:
    """``NRestarts`` von systemd: automatische Neustarts (Restart=) seit dem letzten Start von Hand."""
    wert = (wert or "").strip()
    return int(wert) if wert.isdigit() and int(wert) <= MAX_NEUSTARTS else None


def dienst_status(unit: str) -> dict:
    """``{"zustand": "aktiv"|"gestoppt"|"fehlt", "seit": unix|None, "grund": str|None,
    "neustarts": int|None, "letzterStopp": unix|None}``

    ``grund`` ist bei gestopptem Dienst das ``Result`` von systemd, wenn es kein normales Ende war
    (z. B. ``oom-kill``, ``exit-code``, ``signal``) – die Oberfläche nennt dann die Ursache (#68).
    ``neustarts`` ist ``NRestarts`` (automatische Neustarts seit dem letzten Start von Hand),
    ``letzterStopp`` ``InactiveEnterTimestamp`` (zuletzt beendet; None, wenn seit dem Booten nie) – beides
    für die Grundüberwachung (#95)."""
    if not unit:
        return {"zustand": "fehlt", "seit": None, "unit": ""}
    try:
        lauf = subprocess.run(
            ["systemctl", "show", unit, "-p", "ActiveState,ActiveEnterTimestamp,InactiveEnterTimestamp,Result,NRestarts",
             "--timestamp=utc"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {"zustand": "fehlt", "seit": None, "unit": unit}
    werte = dict(z.split("=", 1) for z in lauf.stdout.splitlines() if "=" in z)
    aktiv = werte.get("ActiveState") == "active"
    stopp = _systemd_zeit(werte.get("InactiveEnterTimestamp", ""))
    seit = _systemd_zeit(werte.get("ActiveEnterTimestamp", "")) if aktiv else stopp
    ergebnis = werte.get("Result", "").strip()
    grund = None if aktiv or ergebnis in ("", "success") or not re.fullmatch(r"[a-z-]{1,32}", ergebnis) else ergebnis
    return {"zustand": "aktiv" if aktiv else "gestoppt", "seit": seit, "unit": unit, "grund": grund,
            "neustarts": _neustarts(werte.get("NRestarts", "")), "letzterStopp": stopp}


# ---------------------------------------------------------------- Journal: Job-Ereignisse

LAUF_START = re.compile(r"Running job: (?P<name>.+?)\s*$")
LAUF_ENDE = re.compile(r"Job (?P<name>.+?) completed with result: (?P<ergebnis>\w+)")
ERGEBNIS = {"succeeded": "erfolg", "failed": "fehler", "canceled": "abgebrochen", "cancelled": "abgebrochen"}


@dataclass
class JobEreignis:
    zeit: float
    art: str  # start | ende | dienst-gestartet | dienst-gestoppt | bereit | verbindung
    name: str = ""
    ergebnis: str = ""


def deute_journalzeile(eintrag: dict) -> JobEreignis | None:
    """Eine Zeile aus ``journalctl -o json`` in ein Ereignis übersetzen (oder None)."""
    nachricht = eintrag.get("MESSAGE", "")
    if isinstance(nachricht, list):  # Nicht-UTF-8 kommt als Byte-Liste
        nachricht = bytes(nachricht).decode("utf-8", "replace")
    zeit = int(eintrag.get("__REALTIME_TIMESTAMP", "0")) / 1_000_000 or time.time()
    if (t := LAUF_START.search(nachricht)):
        return JobEreignis(zeit, "start", t.group("name"))
    if (t := LAUF_ENDE.search(nachricht)):
        return JobEreignis(zeit, "ende", t.group("name"), ERGEBNIS.get(t.group("ergebnis").lower(), "abgebrochen"))
    if eintrag.get("_COMM") == "systemd" or eintrag.get("SYSLOG_IDENTIFIER") == "systemd":
        if nachricht.startswith("Started"):
            return JobEreignis(zeit, "dienst-gestartet")
        if nachricht.startswith(("Stopped", "Stopping")):
            return JobEreignis(zeit, "dienst-gestoppt")
    if "Listening for Jobs" in nachricht:
        return JobEreignis(zeit, "bereit")
    if re.search(r"(?i)(failed to connect|connection.*(lost|refused)|unable to connect|retry)", nachricht):
        return JobEreignis(zeit, "verbindung", nachricht[:200])
    return None


class JournalFolger(threading.Thread):
    """Liest ``journalctl -f`` des Runners und meldet Ereignisse über ``melde``."""

    def __init__(self, melde: Callable[[JobEreignis], None], rueckblick: int = 400) -> None:
        super().__init__(name="journal", daemon=True)
        self.melde = melde
        self.rueckblick = rueckblick

    def run(self) -> None:  # pragma: no cover – braucht systemd
        while True:
            try:
                prozess = subprocess.Popen(
                    ["journalctl", "-u", UNIT_MUSTER, "-f", "-o", "json", "-n", str(self.rueckblick), "--no-pager"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1,
                )
                assert prozess.stdout is not None
                for zeile in prozess.stdout:
                    try:
                        ereignis = deute_journalzeile(json.loads(zeile))
                        if ereignis:
                            self.melde(ereignis)
                    except ValueError:
                        continue
                    except Exception:  # noqa: BLE001 – ein Fehler darf das Mitlesen nie beenden (Issue #57)
                        LOG.exception("Fehler beim Verarbeiten einer Journalzeile")
            except OSError:
                pass
            except Exception:  # noqa: BLE001
                LOG.exception("Journal-Leser: unerwarteter Fehler, starte neu")
            time.sleep(5)


# ---------------------------------------------------------------- Ausgabe der Schritte (_diag/pages)

ZEITSTEMPEL = re.compile(r"^(?P<zeit>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?Z\s?")


def deute_seitenzeile(zeile: str, ersatzzeit: float) -> tuple[float, str]:
    """Zeitstempel am Zeilenanfang abtrennen. Ohne Zeitstempel gilt ``ersatzzeit``."""
    t = ZEITSTEMPEL.match(zeile)
    if not t:
        return ersatzzeit, zeile
    try:
        zeit = datetime.strptime(t.group("zeit"), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:  # z. B. „2026-13-40T…“ – dann gilt die Ersatzzeit
        return ersatzzeit, zeile[t.end():]
    return zeit, zeile[t.end():]


class SeitenFolger(threading.Thread):
    """Verfolgt die jeweils neueste Datei in ``_diag/pages`` wie ``tail -f``.

    Jede neue Datei ist ein neuer Schritt. Gemeldet wird ``("schritt", datei)`` und danach
    ``("zeilen", [(zeit, text), …])`` je gelesenem Stück – nicht je Zeile, damit eine Flut von
    Ausgabe (npm, docker build) nicht tausende Einzelnachrichten an jedes Browserfenster erzeugt.
    """

    def __init__(self, seiten_verz: Path, melde: Callable[[str, object], None], takt: float = 0.3) -> None:
        super().__init__(name="seiten", daemon=True)
        self.verz = seiten_verz
        self.melde = melde
        self.takt = takt
        self.datei: Path | None = None
        self.position = 0
        self.rest = ""

    def neueste(self) -> Path | None:
        """Jüngste Seitendatei. Der Runner lädt Seiten hoch und löscht sie – eine Datei kann zwischen
        Auflisten und stat() verschwinden; das darf den Leser nicht beenden (Issue #57)."""
        try:
            dateien = [p for p in self.verz.iterdir() if p.suffix == ".log"]
        except OSError:
            return None
        beste, beste_zeit = None, -1.0
        for p in dateien:
            try:
                zeit = p.stat().st_mtime
            except OSError:
                continue
            if zeit > beste_zeit:
                beste, beste_zeit = p, zeit
        return beste

    def schritt(self) -> None:
        neu = self.neueste()
        if neu is not None and neu != self.datei:
            # Beim Start nicht die ganze alte Datei melden, nur die letzten 200 Zeilen.
            erster_lauf = self.datei is None
            self.datei, self.position, self.rest = neu, 0, ""
            self.melde("schritt", neu)
            if erster_lauf:
                try:
                    groesse = neu.stat().st_size
                    self.position = max(0, groesse - 64_000)
                except OSError:
                    pass
        if self.datei is None:
            return
        try:
            with self.datei.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(self.position)
                neu_text = f.read(512_000)
                self.position = f.tell()
        except OSError:
            return
        if not neu_text:
            return
        text = self.rest + neu_text
        zeilen = text.split("\n")
        self.rest = zeilen.pop()
        if zeilen:
            jetzt = time.time()
            self.melde("zeilen", [deute_seitenzeile(z.rstrip("\r"), jetzt) for z in zeilen])

    def run(self) -> None:  # pragma: no cover – Endlosschleife
        while True:
            try:
                self.schritt()
            except Exception:  # noqa: BLE001 – ein Fehler darf das Live-Log nie dauerhaft anhalten (Issue #57)
                LOG.exception("Live-Log: Fehler beim Lesen von %s", self.datei or self.verz)
                time.sleep(5)
            time.sleep(self.takt)
