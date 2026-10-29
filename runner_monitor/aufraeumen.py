"""Ist das Aufräumen der Platte eingerichtet? (#144)

Der Sammler (root) prüft jede Minute, was ``einrichten.sh aufraeumen`` (``deploy/aufraeumen-einrichten.sh``)
anlegt, und schreibt das Ergebnis nach ``/run/runner-monitor/aufraeumen.json`` (0644, ohne Inhalte der
Dateien). Der Monitor gibt es als Bereich ``aufraeumen`` weiter (``/events``, ``/api/zustand``); Info › Was
tun, wenn … › „Platte knapp“ zeigt den Befehl ``sudo /usr/local/bin/runner-aufraeumen`` nur, wenn es ihn gibt,
sonst den Befehl zum Einrichten.

Geprüft wird ohne Symlinks zu folgen: Skript und nächtlicher Lauf zählen nur als reguläre Dateien, die
root gehören, für Gruppe und andere nicht schreibbar und ausführbar sind (sonst könnte ein anderer
Benutzer ändern, was root jede Nacht ausführt). Gelesen wird nur mit ``O_NOFOLLOW``, begrenzt und ohne zu
blockieren (FIFO). Hook und ``.env`` des GitHub-Runners gehören dem Runner-Benutzer; sie zählen, wenn sie
reguläre Dateien sind und auf das Skript zeigen.
"""

from __future__ import annotations

import math
import os
import stat
import subprocess
from pathlib import Path

SKRIPT = Path("/usr/local/bin/runner-aufraeumen")
NACHT = Path("/etc/cron.daily/runner-aufraeumen")
TIMER = "runner-aufraeumen.timer"
HOOK_SCHLUESSEL = "ACTIONS_RUNNER_HOOK_JOB_STARTED"
MAX_LESEN = 64 * 1024
FELDER = ("skript", "nacht", "timer", "vorDemJob")


def _root_datei(pfad: Path, besitzer: int = 0) -> bool:
    """Reguläre Datei (kein Symlink), gehört root, für Gruppe/andere nicht schreibbar, ausführbar."""
    try:
        st = os.lstat(pfad)
    except OSError:
        return False
    return (stat.S_ISREG(st.st_mode) and st.st_uid == besitzer and not st.st_mode & 0o022
            and bool(st.st_mode & 0o100))


def lies(pfad: Path, grenze: int = MAX_LESEN) -> str | None:
    """Text einer regulären Datei, ohne einem Symlink zu folgen und ohne zu blockieren; sonst ``None``."""
    try:
        fd = os.open(pfad, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        daten = b""
        while len(daten) <= grenze:
            stueck = os.read(fd, grenze + 1 - len(daten))
            if not stueck:
                break
            daten += stueck
        if len(daten) > grenze:
            return None
        return daten.decode("utf-8", "replace")
    except OSError:
        return None
    finally:
        os.close(fd)


def _timer_aktiv(timer: str) -> bool:
    try:
        lauf = subprocess.run(["systemctl", "is-active", "--quiet", timer], stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return lauf.returncode == 0


def _hook(runner_verz: Path) -> bool | None:
    """GitHub-Runner: ``None`` ohne registrierten Runner, sonst ob ``.env`` den Hook vor dem Job auf
    ``vor-dem-job.sh`` setzt und dieser ``runner-aufraeumen`` aufruft."""
    if not os.path.lexists(runner_verz / ".runner"):
        return None
    hook = runner_verz / "vor-dem-job.sh"
    env = lies(runner_verz / ".env") or ""
    wert = None
    for zeile in env.splitlines():
        if zeile.startswith(HOOK_SCHLUESSEL + "="):
            wert = zeile.split("=", 1)[1].strip()  # wie der Runner: die letzte Zeile gilt
    if wert != str(hook):
        return False
    return str(SKRIPT) in (lies(hook, 4096) or "")


def pruefe(runner_verz: Path, skript: Path = SKRIPT, nacht: Path = NACHT, timer_aktiv=None, besitzer: int = 0) -> dict:
    """Stand des Aufräumens. ``timer_aktiv`` und ``besitzer`` nur für Tests (sonst ``systemctl is-active``, root)."""
    aktiv = timer_aktiv if timer_aktiv is not None else _timer_aktiv
    return {
        "skript": _root_datei(skript, besitzer),
        "nacht": _root_datei(nacht, besitzer) and str(SKRIPT) in (lies(nacht, 4096) or ""),
        "timer": bool(aktiv(TIMER)),
        "vorDemJob": _hook(runner_verz),
    }


def pruefe_stand(daten: object) -> dict | None:
    """Was der Monitor (ohne root) aus ``aufraeumen.json`` übernimmt: nur die bekannten Felder als
    Wahrheitswerte (``vorDemJob`` auch ``None``) und die Zeit der Prüfung. Sonst ``None``."""
    if not isinstance(daten, dict):
        return None
    stand: dict = {}
    for feld in FELDER:
        wert = daten.get(feld)
        if not (isinstance(wert, bool) or (feld == "vorDemJob" and wert is None)):
            return None
        stand[feld] = wert
    zeit = daten.get("geprueft")
    gueltig = isinstance(zeit, (int, float)) and not isinstance(zeit, bool) and math.isfinite(zeit)
    stand["geprueft"] = zeit if gueltig else None
    return stand
