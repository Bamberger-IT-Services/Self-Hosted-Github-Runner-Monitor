"""Erkennung der Runner auf dieser VM (Design 0.8.0, #91).

Der Monitor findet selbst, welche CI-Runner auf der VM laufen, zu welchem Dienst sie gehören
(GitHub, Forgejo, Gitea, GitLab oder unbekannt) und wie sicher das ist. Quellen:

* **systemd-Units** – Unit-Dateien in ``/etc/systemd/system``, ``/run/systemd/system``,
  ``/usr/lib/systemd/system``, ``/lib/systemd/system`` (mit Drop-ins ``*.d/*.conf``); aktiv oder
  nicht über ``systemctl is-active``.
* **Prozesse** – ``/proc/<pid>/cmdline``, ``cgroup`` (zu welcher Unit gehört der Prozess?) und ``cwd``.
* **Registrierungen** – ``.runner`` (GitHub, Forgejo, Gitea) und ``config.toml`` (GitLab) neben den
  Units und Prozessen sowie an den üblichen Orten.
* **Server-API-Probe** ohne Zugangsdaten – ``/api/forgejo/v1/version``, ``/api/v1/version``,
  GitLab-Anmeldeseite, ``/api/v3/meta`` (GitHub Enterprise). Ohne Netz bleibt der Grad „wahrscheinlich“.

Regeln (Sicherheitsbericht): Die Erkennung führt **nie** etwas aus, das in einem Fund steht (kein
``ExecStart``, kein Runner-Programm, keine Shell). Aufgerufen werden nur ``systemctl is-active`` und
``journalctl`` mit geprüftem Unit-Namen als eigenem Argument. Dateien werden nur gelesen, wenn sie
reguläre Dateien unter einer Größengrenze sind, ohne Symlinks zu folgen (Ausnahme: Unit-Dateien in
den root-eigenen systemd-Verzeichnissen), Registrierungen nur mit festen Dateinamen. Tokens
(``token`` in ``.runner``/``config.toml``) werden nie übernommen, ``.credentials`` wird nie gelesen.
Namen, Pfade und Adressen werden streng geprüft; die Textausgabe ersetzt Steuerzeichen, damit ein
Fund das Terminal nicht verändern kann. Die Server-Probe gilt nur für Funde mit systemd-Unit (E-17)
und hat harte Fristen. IDs werden zuerst an Funde mit Unit vergeben, Funde ohne Unit sind nie
„angebunden“ (E-18). Adapter nehmen Server und Log-Pfad nur aus ``runner.json`` bzw. den
Zugangsdaten, nie aus einem Fund – der Fund ist nur ein Vorschlag. Ein Fehler in einer Quelle
beendet die Erkennung nie.

Aufruf (z. B. aus ``einrichten.sh``)::

    python3 -m runner_monitor.erkennung --text [--farbe] [--einrichtung] [--ohne-netz]
    python3 -m runner_monitor.erkennung --json

``--text`` endet mit 3, wenn kein Runner gefunden wurde. Format eines Funds: ``docs/FUNKTIONSWEISE.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import textwrap
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

DIENSTE = ("github", "forgejo", "gitea", "gitlab", "unbekannt")
ANZEIGE = {"github": "GitHub", "forgejo": "Forgejo", "gitea": "Gitea", "gitlab": "GitLab", "unbekannt": "unbekannt"}
GRADE = ("sicher", "wahrscheinlich", "unklar")
STAENDE = ("angebunden", "grund", "ignoriert", "offen")
GEPRUEFT = ["systemd-Units", "Prozesse", ".runner-Dateien", "Server-API"]

# Was der Monitor in dieser Version je Dienst liefern kann (README › „Nicht verfügbar“ ehrlich zeigen).
# Forgejo, Gitea und GitLab sind erkannt, ausgeliefert aber als Grundüberwachung (Dienst und Journal).
# Ihre Adapter können mehr (Forgejo/Gitea #93: Jobs und Schritte; GitLab #99: Jobs ohne Schritte); die
# Tabelle hebt erst an, wenn die Einrichtung sie anbindet (#96) und der Sammler sie regulär aufruft
# (#115), Gitea zusätzlich erst nach Prüfung an einem echten Server (E-20, E-23). Ein von Hand in
# runner.json angebundener Forgejo-/Gitea-Runner meldet in runner[] die Fähigkeiten seines Adapters.
FAEHIG = {
    "github": {"status": True, "jobs": True, "schritte": True, "logs": True, "updates": False},
    "forgejo": {"status": True, "jobs": False, "schritte": False, "logs": True, "updates": False},
    "gitea": {"status": True, "jobs": False, "schritte": False, "logs": True, "updates": False},
    "gitlab": {"status": True, "jobs": False, "schritte": False, "logs": True, "updates": False},
    "unbekannt": {"status": True, "jobs": False, "schritte": False, "logs": True, "updates": False},
}
EINSTUFUNG = {"github": "voll", "forgejo": "teil", "gitea": "teil", "gitlab": "teil", "unbekannt": "unbekannt"}

UNIT_VERZEICHNISSE = ("/etc/systemd/system", "/run/systemd/system", "/usr/local/lib/systemd/system",
                      "/usr/lib/systemd/system", "/lib/systemd/system")
UNIT_NAME = re.compile(r"(?:[A-Za-z0-9:_.@-]|\\x[0-9a-fA-F]{2}){1,200}\.service")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@+-]{0,63}")
ORG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}")
HOST = re.compile(r"(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?)*")
URL_PFAD = re.compile(r"(?:/[A-Za-z0-9._~%_-]{1,80}){0,8}/?")
VERSION = re.compile(r"v?(\d{1,5}(?:\.\d{1,6}){0,3})(?:[+-][A-Za-z0-9.+-]{0,60})?")

# Bekannte Runner: Unit-Name bzw. Programmname → Dienst.
BEKANNT_UNIT = (
    ("github", re.compile(r"actions\.runner\..+\.service")),
    ("forgejo", re.compile(r"forgejo-runner(?:[-_.@].*)?\.service")),
    ("gitea", re.compile(r"(?:act_runner|act-runner|gitea-runner|gitea-act-runner)(?:[-_.@].*)?\.service")),
    ("gitlab", re.compile(r"gitlab-(?:ci-multi-)?runner(?:[-_.@].*)?\.service")),
)
BEKANNT_PROGRAMM = (
    ("github", re.compile(r"Runner\.Listener")),
    ("forgejo", re.compile(r"forgejo-runner(?:[-_.].*)?")),
    ("gitea", re.compile(r"(?:act_runner|act-runner|gitea-runner)(?:[-_.].*)?")),
    ("gitlab", re.compile(r"gitlab-(?:ci-multi-)?runner(?:[-_.].*)?")),
)
# Allgemeine Hinweise für unbekannte Runner (nur im Unit-Namen) – das erste passende Wort zählt.
STICHWORTE = ("runner", "agent", "build", "woodpecker", "drone", "buildkite", "jenkins", "teamcity", "bamboo")
# Bekannte Dienste mit solchen Wörtern, die keine CI-Runner sind.
AUSNAHMEN = re.compile(
    r"(?:runner-monitor.*|qemu-guest-agent|ssh-agent|gpg-agent.*|walinuxagent|amazon-ssm-agent|"
    r"snap\..*|google-.*|zabbix-agent2?|datadog-agent.*|wazuh-agent|elastic-agent|fluent-bit|"
    r"spice-vdagentd?|vgauth.*|open-vm-tools|vmtoolsd|buildkit.*|docker.*|containerd.*|"
    r"systemd-.*|user@.*|user-runtime-dir@.*|polkit.*|pcscd|xrdp.*)\.service"
)
CONTAINER = re.compile(r"(?:^|[\s/])(?:docker|podman|nerdctl|ctr)(?:\s|$)")

MAX_UNIT = 64 * 1024
MAX_REGISTRIERUNG = 64 * 1024
MAX_CMDLINE = 8 * 1024
MAX_PROZESSE = 20000
MAX_ANTWORT = 256 * 1024
MAX_SERVER = 8


# ---------------------------------------------------------------- Prüfen und Entschärfen


def pruefe_unit(name: object) -> str | None:
    """Unit-Name nach systemd-Regeln (nur ``.service``), sonst None. Beginnt nie mit „-“."""
    if isinstance(name, str) and UNIT_NAME.fullmatch(name) and not name.startswith("-"):
        return name
    return None


def pruefe_name(name: object) -> str | None:
    if isinstance(name, str) and NAME.fullmatch(name.strip()):
        return name.strip()
    return None


def pruefe_org(org: object) -> str | None:
    """Organisation oder Benutzer beim Dienst (Forgejo/Gitea: ``A-Z a-z 0-9 . _ -``), höchstens 64 Zeichen."""
    if isinstance(org, str) and ORG.fullmatch(org.strip()) and org.strip() not in (".", ".."):
        return org.strip()
    return None


def pruefe_pfad(pfad: object) -> str | None:
    """Absoluter, normalisierter Pfad ohne Steuerzeichen und ohne „..“, höchstens 1024 Zeichen."""
    if not isinstance(pfad, str) or not pfad.startswith("/") or len(pfad) > 1024:
        return None
    if any(unicodedata.category(z).startswith("C") for z in pfad):
        return None
    teile = pfad.split("/")
    if ".." in teile:
        return None
    sauber = os.path.normpath(pfad)
    return sauber if sauber.startswith("/") else None


def pruefe_url(url: object) -> str | None:
    """``https://host[:port][/pfad]`` – ohne Zugangsdaten, Abfrage und Anker; sonst None."""
    if not isinstance(url, str) or len(url) > 512 or any(unicodedata.category(z).startswith("C") for z in url):
        return None
    try:
        teile = urllib.parse.urlsplit(url.strip())
        port = teile.port
    except ValueError:
        return None
    host = teile.hostname or ""
    if teile.scheme not in ("http", "https") or not HOST.fullmatch(host):
        return None
    pfad = teile.path or ""
    if not URL_PFAD.fullmatch(pfad):
        return None
    ergebnis = f"{teile.scheme}://{host.lower()}"
    if port is not None:
        ergebnis += f":{port}"
    return ergebnis + pfad.rstrip("/")


def pruefe_version(text: object) -> str | None:
    if isinstance(text, str):
        treffer = VERSION.fullmatch(text.strip())
        if treffer:
            return treffer.group(1)
    return None


def kurz_version(version: str) -> str:
    """„13.0.1“ → „13.0“ (Server- und Runner-Version wie im Design)."""
    return ".".join(version.split(".")[:2])


def fuer_terminal(text: object) -> str:
    """Steuer- und Formatzeichen ersetzen – ein Fund darf das Terminal nicht steuern."""
    return "".join("?" if unicodedata.category(z).startswith("C") else z for z in str(text))


def als_id(text: str) -> str:
    sauber = re.sub(r"[^a-z0-9._-]+", "-", text.lower()).strip("-.")
    return sauber[:64] or "runner"


# ---------------------------------------------------------------- Zugriff auf das System


@dataclass
class Prozess:
    pid: int
    programm: str          # Name des Programms (Basisname von argv[0])
    argv: list[str]
    unit: str | None       # Unit laut cgroup
    container: bool
    cwd: str | None


class Quelle:
    """Zugriff auf Dateien, /proc, systemctl, journalctl und Netz.

    ``wurzel`` verschiebt alle Pfade (Tests bauen eine VM im Temp-Ordner nach). Tests ersetzen
    ``aktiv``, ``journal`` und ``hole`` durch Attrappen."""

    def __init__(self, wurzel: Path | str = "/", netz: bool = True, frist: float = 10.0, zeitlimit: float = 3.0) -> None:
        self.wurzel = Path(wurzel)
        self.netz = netz
        self.ende = time.monotonic() + frist
        self.zeitlimit = zeitlimit

    def pfad(self, vm_pfad: str) -> Path:
        return self.wurzel / vm_pfad.lstrip("/")

    def lies(self, vm_pfad: str, grenze: int, folgen: bool = False) -> bytes | None:
        """Reguläre Datei bis ``grenze`` Bytes lesen, sonst None.

        Symlinks nur mit ``folgen=True`` – das gilt allein für Unit-Dateien in den root-eigenen
        systemd-Verzeichnissen. Vor dem Öffnen prüft ``lstat``, dass es eine reguläre Datei ist
        (keine FIFO, kein Gerät); geöffnet wird nicht blockierend, ohne Steuerterminal, und nach dem
        Öffnen muss es dieselbe Datei sein."""
        ziel = self.pfad(vm_pfad)
        try:
            vorab = os.stat(ziel) if folgen else os.lstat(ziel)
        except (OSError, ValueError):
            return None
        if not stat.S_ISREG(vorab.st_mode) or vorab.st_size > grenze:
            return None
        flags = (os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0)
                 | getattr(os, "O_CLOEXEC", 0) | (0 if folgen else getattr(os, "O_NOFOLLOW", 0)))
        try:
            fd = os.open(ziel, flags)
        except OSError:
            return None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != (vorab.st_dev, vorab.st_ino):
                return None
            teile, gelesen = [], 0
            while gelesen <= grenze:
                stueck = os.read(fd, min(65536, grenze + 1 - gelesen))
                if not stueck:
                    break
                teile.append(stueck)
                gelesen += len(stueck)
            return None if gelesen > grenze else b"".join(teile)
        except OSError:
            return None
        finally:
            os.close(fd)

    def eintraege(self, vm_verz: str, grenze: int = 2000) -> list[str]:
        try:
            with os.scandir(self.pfad(vm_verz)) as it:
                namen = []
                for eintrag in it:
                    namen.append(eintrag.name)
                    if len(namen) >= grenze:
                        break
                return sorted(namen)
        except OSError:
            return []

    def ist_verz(self, vm_pfad: str) -> bool:
        try:
            return stat.S_ISDIR(os.lstat(self.pfad(vm_pfad)).st_mode)
        except OSError:
            return False

    def gibt_es(self, vm_pfad: str) -> bool:
        return os.path.lexists(self.pfad(vm_pfad))

    def link_ziel(self, vm_pfad: str) -> str | None:
        try:
            return os.readlink(self.pfad(vm_pfad))
        except OSError:
            return None

    def aktiv(self, unit: str) -> bool | None:
        """``systemctl is-active`` – True, False oder None (unbekannt)."""
        if not pruefe_unit(unit):
            return None
        try:
            lauf = subprocess.run(["systemctl", "is-active", "--", unit], capture_output=True, text=True,
                                  timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        antwort = lauf.stdout.strip()
        if antwort in ("active", "activating", "reloading"):
            return True
        if antwort in ("inactive", "failed", "deactivating"):
            return False
        return None

    def journal(self, unit: str) -> list[str]:
        """Die letzten 300 Zeilen des Journals der Unit (nur für die Runner-Version)."""
        if not pruefe_unit(unit):
            return []
        try:
            lauf = subprocess.run(["journalctl", "-u", unit, "-n", "300", "-o", "cat", "--no-pager", "-q"],
                                  capture_output=True, text=True, errors="replace", timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            return []
        return lauf.stdout.splitlines()[-300:]

    def hole(self, url: str) -> tuple[int, bytes] | None:
        """GET ohne Zugangsdaten und ohne Weiterleitungen: höchstens 3 s je Anfrage und 10 s für alle
        zusammen – **harte** Grenzen, auch für die Namensauflösung (DNS) und einen Server, der die
        Antwort tröpfeln lässt. Die Anfrage läuft dafür in einem eigenen Faden; ist er zur Frist nicht
        fertig, gilt der Server als nicht erreichbar und der Faden wird zurückgelassen (daemon)."""
        rest = self.ende - time.monotonic()
        if not self.netz or rest <= 0.2 or not pruefe_url(url):
            return None
        frist = min(self.zeitlimit, rest)
        ergebnis: list = []
        faden = threading.Thread(target=self._hole, args=(url, time.monotonic() + frist, ergebnis),
                                 name="erkennung-probe", daemon=True)
        faden.start()
        faden.join(frist)
        return ergebnis[0] if ergebnis and not faden.is_alive() else None

    @staticmethod
    def _hole(url: str, ende: float, ergebnis: list) -> None:
        anfrage = urllib.request.Request(url, headers={"User-Agent": "runner-monitor-erkennung",
                                                       "Accept": "application/json, text/html"})
        oeffner = urllib.request.build_opener(_KeineWeiterleitung)
        try:
            try:
                with oeffner.open(anfrage, timeout=max(0.1, ende - time.monotonic())) as antwort:
                    ergebnis.append((antwort.status, _lies_antwort(antwort, ende)))
            except urllib.error.HTTPError as fehler:
                try:
                    ergebnis.append((fehler.code, _lies_antwort(fehler, ende)))
                finally:
                    fehler.close()
        except Exception:  # noqa: BLE001 – Netz, DNS, TLS, http.client: alles heißt „nicht erreichbar“
            ergebnis.clear()


def _lies_antwort(antwort, ende: float) -> bytes:
    """Antwort stückweise lesen, bis ``MAX_ANTWORT`` oder zur Frist (dann TimeoutError)."""
    lese = getattr(antwort, "read1", None) or antwort.read
    teile, gelesen = [], 0
    while gelesen < MAX_ANTWORT:
        if time.monotonic() > ende:
            raise TimeoutError("Antwort zu langsam")
        stueck = lese(min(8192, MAX_ANTWORT - gelesen))
        if not stueck:
            break
        teile.append(stueck)
        gelesen += len(stueck)
    return b"".join(teile)


class _KeineWeiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401, ANN001
        return None  # 3xx bleibt eine Antwort; einer Adresse aus einem Fund wird nicht weiter gefolgt


# ---------------------------------------------------------------- Units


@dataclass
class Unit:
    name: str
    datei: str
    argv: list[str] = field(default_factory=list)
    arbeitsverz: str | None = None
    beschreibung: str = ""
    container: bool = False
    aktiviert: bool = False


def deute_unit(text: str, unit: Unit) -> None:
    """``[Service]``-Werte aus einer Unit-Datei oder einem Drop-in übernehmen (ohne auszuführen)."""
    abschnitt = ""
    zeilen = text.replace("\\\n", " ").splitlines()
    for zeile in zeilen[:2000]:
        zeile = zeile.strip()
        if not zeile or zeile[0] in "#;":
            continue
        if zeile.startswith("[") and zeile.endswith("]"):
            abschnitt = zeile[1:-1]
            continue
        schluessel, _, wert = zeile.partition("=")
        schluessel, wert = schluessel.strip(), wert.strip()
        if abschnitt == "Unit" and schluessel == "Description":
            unit.beschreibung = wert[:200]
        elif abschnitt == "Service" and schluessel == "ExecStart":
            if not wert:
                unit.argv = []  # „ExecStart=“ leert die Liste (Drop-in)
            elif not unit.argv:
                unit.argv = zerlege_befehl(wert.lstrip("@-:+!"))
                unit.container = unit.container or bool(CONTAINER.search(" ".join(unit.argv)))
        elif abschnitt == "Service" and schluessel == "WorkingDirectory":
            unit.arbeitsverz = pruefe_pfad(wert.lstrip("-")) if wert and wert != "~" else None


def zerlege_befehl(text: str) -> list[str]:
    """Befehlszeile nur zerlegen (shlex), nie ausführen."""
    text = text[:4096]
    try:
        return shlex.split(text)[:64]
    except ValueError:
        return text.split()[:64]


def lies_units(q: Quelle) -> dict[str, Unit]:
    units: dict[str, Unit] = {}
    for verz in UNIT_VERZEICHNISSE:
        for name in q.eintraege(verz, grenze=5000):
            if name in units or not pruefe_unit(name):
                continue
            daten = q.lies(f"{verz}/{name}", MAX_UNIT, folgen=True)  # oft Symlinks (systemctl link)
            if daten is None:
                continue
            unit = Unit(name=name, datei=f"{verz}/{name}")
            deute_unit(daten.decode("utf-8", "replace"), unit)
            for drop in (f"/etc/systemd/system/{name}.d", f"/run/systemd/system/{name}.d"):
                for konf in q.eintraege(drop, grenze=50):
                    if konf.endswith(".conf"):
                        extra = q.lies(f"{drop}/{konf}", MAX_UNIT, folgen=True)
                        if extra is not None:
                            deute_unit(extra.decode("utf-8", "replace"), unit)
            units[name] = unit
    for wants in q.eintraege("/etc/systemd/system", grenze=5000):
        if wants.endswith(".wants"):
            for name in q.eintraege(f"/etc/systemd/system/{wants}", grenze=2000):
                if name in units:
                    units[name].aktiviert = True
                elif "@" in name and (vorlage := name.partition("@")[0] + "@.service") in units:
                    # Instanz einer Vorlage, z. B. act_runner@1.service
                    kopie = Unit(**{**units[vorlage].__dict__, "name": name, "aktiviert": True})
                    units[name] = kopie
    return units


# ---------------------------------------------------------------- Prozesse


def lies_prozesse(q: Quelle) -> list[Prozess]:
    ergebnis = []
    pids = [n for n in q.eintraege("/proc", grenze=MAX_PROZESSE + 200) if n.isdigit()][:MAX_PROZESSE]
    for pid in pids:
        roh = q.lies(f"/proc/{pid}/cmdline", MAX_CMDLINE)
        if not roh:
            continue
        argv = [t.decode("utf-8", "replace") for t in roh.split(b"\0") if t][:64]
        if not argv:
            continue
        programm = PurePosixPath(argv[0]).name
        if not any(muster.fullmatch(programm) for _, muster in BEKANNT_PROGRAMM):
            continue  # nur bekannte Runner-Programme; unbekannte Runner kommen über ihre Unit
        unit, container = None, False
        cgroup = (q.lies(f"/proc/{pid}/cgroup", 8192) or b"").decode("utf-8", "replace")
        for zeile in cgroup.splitlines():
            pfad = zeile.split(":", 2)[-1]
            if re.search(r"docker|libpod|containerd|kubepods|lxc", pfad):
                container = True
            if "user@" in pfad or "/user.slice/" in pfad:
                continue  # Dienste eines angemeldeten Benutzers sind keine System-Units
            for teil in reversed(pfad.split("/")):
                if pruefe_unit(teil) and not teil.startswith("user@"):
                    unit = teil
                    break
        cwd = q.link_ziel(f"/proc/{pid}/cwd")
        ergebnis.append(Prozess(int(pid), programm, argv, unit, container, pruefe_pfad(cwd) if cwd else None))
    return ergebnis


# ---------------------------------------------------------------- Registrierungen


@dataclass
class Registrierung:
    pfad: str
    art: str                 # github | act | gitlab | kaputt
    name: str | None = None
    server: str | None = None
    hinweis: str | None = None   # „forgejo“, wenn die Datei es selbst nennt
    anzahl: int = 1
    nur_prozess: bool = False    # stammt nur aus einem Prozess der Unit-Gruppe, nicht aus der Unit selbst (#109)


def deute_runner_datei(pfad: str, daten: bytes) -> Registrierung:
    """``.runner`` von GitHub (``agentName``, ``gitHubUrl``) oder act_runner/Forgejo (``name``,
    ``address``). ``token`` und alle anderen Felder werden nicht übernommen."""
    try:
        inhalt = json.loads(daten.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return Registrierung(pfad, "kaputt")
    if not isinstance(inhalt, dict):
        return Registrierung(pfad, "kaputt")
    if "agentName" in inhalt or "gitHubUrl" in inhalt:
        return Registrierung(pfad, "github", pruefe_name(inhalt.get("agentName")), pruefe_url(inhalt.get("gitHubUrl")))
    if "address" in inhalt and ("uuid" in inhalt or "token" in inhalt or "name" in inhalt):
        warnung = inhalt.get("WARNING")
        hinweis = "forgejo" if isinstance(warnung, str) and "forgejo" in warnung.lower() else None
        return Registrierung(pfad, "act", pruefe_name(inhalt.get("name")), pruefe_url(inhalt.get("address")), hinweis)
    return Registrierung(pfad, "kaputt")


TOML_WERT = re.compile(r'^\s*(name|url)\s*=\s*"([^"\\]{0,512})"\s*(?:#.*)?$')


def deute_gitlab_konfig(pfad: str, daten: bytes) -> Registrierung:
    """``config.toml`` von gitlab-runner: nur ``name`` und ``url`` je ``[[runners]]``, nie ``token``.
    Eigener kleiner Leser, weil ``tomllib`` erst ab Python 3.11 da ist (Ubuntu 22.04: 3.10)."""
    try:
        text = daten.decode("utf-8")
    except UnicodeDecodeError:
        return Registrierung(pfad, "kaputt")
    runner: list[dict] = []
    for zeile in text.splitlines()[:5000]:
        if zeile.strip() == "[[runners]]":
            runner.append({})
            continue
        treffer = TOML_WERT.match(zeile)
        if treffer and runner and treffer.group(1) not in runner[-1]:
            runner[-1][treffer.group(1)] = treffer.group(2)
    if not runner:
        return Registrierung(pfad, "kaputt")
    erster = runner[0]
    return Registrierung(pfad, "gitlab", pruefe_name(erster.get("name")), pruefe_url(erster.get("url")), anzahl=len(runner))


def lies_registrierung(q: Quelle, pfad: str) -> Registrierung | None:
    pfad = pruefe_pfad(pfad) or ""
    name = PurePosixPath(pfad).name
    if name not in (".runner", "config.toml"):
        return None  # nur feste Dateinamen – nie beliebige Dateien aus einer Befehlszeile
    daten = q.lies(pfad, MAX_REGISTRIERUNG)
    if daten is None:
        return Registrierung(pfad, "kaputt") if q.gibt_es(pfad) else None
    return deute_runner_datei(pfad, daten) if name == ".runner" else deute_gitlab_konfig(pfad, daten)


def konfig_runner_datei(q: Quelle, konfig: str, basis: str | None) -> str | None:
    """``runner: file: .runner`` aus der ``config.yml`` von act_runner/forgejo-runner."""
    if PurePosixPath(konfig).name not in ("config.yml", "config.yaml"):
        return None
    daten = q.lies(konfig, MAX_REGISTRIERUNG)
    if daten is None:
        return None
    for zeile in daten.decode("utf-8", "replace").splitlines()[:2000]:
        treffer = re.match(r"^\s+file:\s*[\"']?([^\"'\s#]{1,512})[\"']?\s*(?:#.*)?$", zeile)
        if treffer:
            wert = treffer.group(1)
            if not wert.startswith("/"):
                if not basis:
                    return None
                wert = f"{basis}/{wert}"
            return pruefe_pfad(wert)
    return None


def standard_orte(q: Quelle, runner_verz: str | None) -> list[str]:
    """Übliche Orte für ``.runner``/``config.toml`` – flach, ohne tiefe Suche."""
    verz = [runner_verz] if runner_verz else []
    verz += ["/opt/actions-runner", "/etc/forgejo-runner", "/var/lib/forgejo-runner", "/etc/act_runner",
             "/var/lib/act_runner", "/var/lib/gitea-runner", "/root"]
    for oben in ("/opt", "/srv", "/var/lib", "/home", "/root"):
        for name in q.eintraege(oben, grenze=500):
            unter = f"{oben}/{name}"
            if q.ist_verz(unter):
                verz.append(unter)
                if oben in ("/home", "/root"):
                    verz += [f"{unter}/{n}" for n in q.eintraege(unter, grenze=200)
                             if "runner" in n.lower() and q.ist_verz(f"{unter}/{n}")]
    dateien = [f"{v}/.runner" for v in verz if pruefe_pfad(v)]
    dateien += ["/etc/gitlab-runner/config.toml"]
    return list(dict.fromkeys(dateien))


# ---------------------------------------------------------------- Zusammenführen


@dataclass
class Gruppe:
    unit: Unit | None = None
    unit_name: str | None = None
    prozesse: list[Prozess] = field(default_factory=list)
    registrierungen: list[Registrierung] = field(default_factory=list)
    stichwort: str | None = None


def dienst_aus(muster: tuple, text: str) -> str | None:
    for dienst, regel in muster:
        if regel.fullmatch(text):
            return dienst
    return None


def stichwort(unit_name: str) -> str | None:
    stamm = unit_name.rsplit(".service", 1)[0].lower()
    for wort in STICHWORTE:
        if wort in stamm:
            return wort
    return None


def orte_der_gruppe(q: Quelle, g: Gruppe, aus_unit: bool | None = None) -> list[str]:
    """Wo neben Unit und Prozess eine Registrierung liegen kann.

    ``aus_unit=True``: nur was die Unit-Datei vorgibt (``--config`` im ExecStart, Programmordner,
    WorkingDirectory); ``False``: nur was Prozesse vorgeben (argv[0], ``--config``, cwd) – die kann
    jeder Prozess in der cgroup der Unit frei wählen (``exec -a``). ``None``: beides."""
    verz: list[str] = []
    programmverz: list[str] = []   # Ordner des Programms: verlässlicher als das Arbeitsverzeichnis (#109)
    konfig: list[tuple[str, str | None]] = []
    befehle = []
    if g.unit and aus_unit is not False:
        if g.unit.arbeitsverz:
            verz.append(g.unit.arbeitsverz)
        befehle.append((g.unit.argv, g.unit.arbeitsverz))
    for p in g.prozesse if aus_unit is not True else []:
        if p.cwd and not p.container:
            verz.append(p.cwd)
        befehle.append((p.argv, p.cwd))
    for argv, basis in befehle:
        if not argv:
            continue
        programm = pruefe_pfad(argv[0])
        if programm:
            eltern = PurePosixPath(programm).parent
            programmverz.append(str(eltern.parent if eltern.name.startswith("bin") else eltern))  # GitHub: bin/Runner.Listener
        for i, arg in enumerate(argv[1:], start=1):
            wert = None
            if arg in ("-c", "--config") and i + 1 < len(argv):
                wert = argv[i + 1]
            elif arg.startswith("--config="):
                wert = arg.split("=", 1)[1]
            elif arg == "--working-directory" and i + 1 < len(argv):
                verz.append(argv[i + 1])
            if wert:
                if not wert.startswith("/") and basis:
                    wert = f"{basis}/{wert}"
                konfig.append((wert, basis))
    dateien = []
    for pfad, basis in konfig:
        pfad = pruefe_pfad(pfad)
        if not pfad:
            continue
        if PurePosixPath(pfad).name == "config.toml":
            dateien.append(pfad)
        elif (datei := konfig_runner_datei(q, pfad, basis)):
            dateien.append(datei)
    dateien += [f"{v}/.runner" for v in programmverz + verz if pruefe_pfad(v)]
    if g.unit_name and aus_unit is not False and dienst_aus(BEKANNT_UNIT, g.unit_name) == "gitlab" or (
            aus_unit is not True and any(dienst_aus(BEKANNT_PROGRAMM, p.programm) == "gitlab" for p in g.prozesse)):
        dateien.append("/etc/gitlab-runner/config.toml")
    return list(dict.fromkeys(d for d in (pruefe_pfad(x) for x in dateien) if d))


def sammle(q: Quelle, runner_verz: str | None = None) -> list[Gruppe]:
    gruppen: dict[str, Gruppe] = {}
    try:
        units = lies_units(q)
    except Exception:  # noqa: BLE001 – eine kaputte Quelle darf die Erkennung nicht beenden
        units = {}
    for name, unit in units.items():
        if name.endswith("@.service"):
            continue  # Vorlage – Instanzen kommen über *.wants oder die cgroup der Prozesse
        programm = PurePosixPath(unit.argv[0]).name if unit.argv else ""
        bekannt = dienst_aus(BEKANNT_UNIT, name) or dienst_aus(BEKANNT_PROGRAMM, programm)
        wort = None if bekannt or AUSNAHMEN.fullmatch(name) else stichwort(name)
        if bekannt or (wort and (unit.aktiviert or q.aktiv(name))):
            gruppen[f"unit:{name}"] = Gruppe(unit=unit, unit_name=name, stichwort=wort)
    try:
        prozesse = lies_prozesse(q)
    except Exception:  # noqa: BLE001
        prozesse = []
    for p in prozesse:
        if p.unit and not p.container:
            schluessel = f"unit:{p.unit}"
            if schluessel not in gruppen:
                gruppen[schluessel] = Gruppe(unit=units.get(p.unit), unit_name=p.unit)
        else:
            schluessel = f"prozess:{p.cwd or p.pid}"
            gruppen.setdefault(schluessel, Gruppe())
        gruppen[schluessel].prozesse.append(p)

    vergeben: set[str] = set()
    # Erst alles, was die Unit-Datei vorgibt, dann was nur Prozesse vorgeben (#109): bei Gruppen mit
    # Unit-Datei zählt Letzteres nicht für Name, Server und Dienst.
    for aus_unit in (True, False):
        for g in gruppen.values():
            if aus_unit and not g.unit:
                continue
            try:
                orte = orte_der_gruppe(q, g, aus_unit if g.unit else None)
            except Exception:  # noqa: BLE001
                orte = []
            for pfad in orte:
                if pfad in vergeben:
                    continue
                reg = lies_registrierung(q, pfad)
                if reg:
                    vergeben.add(pfad)
                    reg.nur_prozess = bool(g.unit) and not aus_unit
                    g.registrierungen.append(reg)
    try:
        orte = standard_orte(q, runner_verz)
    except Exception:  # noqa: BLE001
        orte = []
    for pfad in orte:
        if pfad in vergeben:
            continue
        reg = lies_registrierung(q, pfad)
        if reg and reg.art != "kaputt":
            vergeben.add(pfad)
            gruppen[f"datei:{pfad}"] = Gruppe(registrierungen=[reg])
    return list(gruppen.values())


# ---------------------------------------------------------------- Server-Probe


def probe(q: Quelle, dienst: str, server: str, speicher: dict) -> tuple[str | None, str | None, str]:
    """→ (bestätigter Dienst oder None, Server-Version oder None, Merkmal)."""
    schluessel = (dienst in ("forgejo", "gitea") and "act" or dienst, server)
    if schluessel in speicher:
        return speicher[schluessel]
    if dienst == "github" and (urllib.parse.urlsplit(server).hostname or "") == "github.com":
        ergebnis = ("github", None, "")  # braucht keine Abfrage, also auch ohne Netz „sicher“
    elif not q.netz:
        ergebnis = (None, None, "Server nicht geprüft (ohne Netz)")
    elif len(speicher) >= MAX_SERVER:
        ergebnis = (None, None, "Server nicht geprüft (zu viele Server)")
    else:
        ergebnis = _probe(q, dienst, server)
    speicher[schluessel] = ergebnis
    return ergebnis


def _json_version(antwort: tuple[int, bytes] | None) -> str | None:
    if not antwort or antwort[0] != 200:
        return None
    try:
        daten = json.loads(antwort[1].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return daten.get("version") if isinstance(daten, dict) and isinstance(daten.get("version"), str) else None


def _probe(q: Quelle, dienst: str, server: str) -> tuple[str | None, str | None, str]:
    nicht = (None, None, "Server nicht erreichbar")
    if dienst == "github":
        host = urllib.parse.urlsplit(server).hostname or ""
        if host == "github.com":
            return "github", None, ""
        antwort = q.hole(f"{urllib.parse.urlsplit(server).scheme}://{host}/api/v3/meta")
        if antwort and antwort[0] == 200:
            try:
                daten = json.loads(antwort[1].decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                daten = None
            if isinstance(daten, dict) and "installed_version" in daten:
                version = pruefe_version(daten.get("installed_version"))
                return "github", version, f"/api/v3/meta antwortet: GitHub Enterprise {version or ''}".rstrip()
        return nicht
    if dienst in ("forgejo", "gitea"):
        roh = _json_version(q.hole(f"{server}/api/forgejo/v1/version"))
        if roh and (version := pruefe_version(roh)):
            return "forgejo", kurz_version(version), f"/api/forgejo/v1/version antwortet: {kurz_version(version)}"
        roh = _json_version(q.hole(f"{server}/api/v1/version"))
        if roh and (version := pruefe_version(roh)):
            echt = "forgejo" if "+gitea-" in roh or "forgejo" in roh.lower() else "gitea"
            return echt, kurz_version(version), f"/api/v1/version antwortet: {kurz_version(version)} ({ANZEIGE[echt]})"
        return nicht
    if dienst == "gitlab":
        antwort = q.hole(f"{server}/users/sign_in")
        if antwort and antwort[0] == 200 and b'content="GitLab"' in antwort[1]:
            return "gitlab", None, "Anmeldeseite meldet GitLab"
        return nicht
    return nicht


# ---------------------------------------------------------------- Runner-Version (ohne auszuführen)


def github_version(q: Quelle, verz: str) -> str | None:
    daten = q.lies(f"{verz}/bin/Runner.Listener.deps.json", 4 * 1024 * 1024)
    if daten is None:
        return None
    try:
        inhalt = json.loads(daten.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return None
    bibliotheken = inhalt.get("libraries") if isinstance(inhalt, dict) else None
    for name in bibliotheken if isinstance(bibliotheken, dict) else ():
        teil = name.partition("/")
        if teil[0] == "Runner.Listener" and re.fullmatch(r"\d+\.\d+\.\d+", teil[2]):
            return teil[2]
    return None


JOURNAL_VERSION = (
    re.compile(r"with version: v?(\d{1,4}\.\d{1,4}(?:\.\d{1,6})?)"),    # act_runner, forgejo-runner
    re.compile(r"\bversion=v?(\d{1,4}\.\d{1,4}\.\d{1,6})"),            # gitlab-runner
)


def journal_version(q: Quelle, unit: str) -> str | None:
    for zeile in reversed(q.journal(unit)):
        for muster in JOURNAL_VERSION:
            treffer = muster.search(zeile)
            if treffer:
                return treffer.group(1)
    return None


# ---------------------------------------------------------------- Zuordnung (/etc/runner-monitor/runner.json)


def lies_zuordnung(pfad: Path | str | None) -> dict[str, dict]:
    """Zuordnung und Ignorieren aus ``/etc/runner-monitor/runner.json`` (Format: FUNKTIONSWEISE.md).

    ``{"version": 1, "runner": {"<id>": {"stand": "angebunden|grund|ignoriert|offen",
    "dienst": "github|forgejo|gitea|gitlab|unbekannt", "name": "…", "unit": "….service",
    "log": "/pfad" | null, "http_erlaubt": true, "server": "https://…", "org": "…"}}}`` – jedes Feld
    außer der ID ist freiwillig. ``server`` und ``org`` sind die **einzige** Quelle, wohin ein Adapter
    (Forgejo, Gitea, #93) mit Token fragt (E-18); ``http://`` nur mit ``http_erlaubt`` (E-21).
    Ungültige Einträge oder Felder werden verworfen; fehlt die Datei oder ist sie kaputt, gilt „keine
    Zuordnung“."""
    if not pfad or not str(pfad).startswith("/"):
        return {}
    roh = Quelle("/").lies(str(pfad), MAX_REGISTRIERUNG)  # wie alle Dateien: ohne Symlink, regulär, begrenzt
    if roh is None:
        return {}
    try:
        daten = json.loads(roh.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}
    eintraege = daten.get("runner") if isinstance(daten, dict) else None
    if not isinstance(eintraege, dict):
        return {}
    ergebnis: dict[str, dict] = {}
    for rid, eintrag in list(eintraege.items())[:100]:
        if not isinstance(rid, str) or als_id(rid) != rid or not isinstance(eintrag, dict):
            continue
        sauber: dict = {}
        if eintrag.get("stand") in STAENDE:
            sauber["stand"] = eintrag["stand"]
        if eintrag.get("dienst") in DIENSTE:
            sauber["dienst"] = eintrag["dienst"]
        if (name := pruefe_name(eintrag.get("name"))):
            sauber["name"] = name
        if (unit := pruefe_unit(eintrag.get("unit"))):
            sauber["unit"] = unit
        if eintrag.get("http_erlaubt") is True:
            sauber["http_erlaubt"] = True  # nur für Adapter, die ein Token an einen Server schicken (E-21)
        if "log" in eintrag and (eintrag["log"] is None or pruefe_pfad(eintrag["log"])):
            sauber["log"] = pruefe_pfad(eintrag["log"]) if eintrag["log"] else None
        if (server := pruefe_url(eintrag.get("server"))) and not any(z in eintrag["server"] for z in "@?#"):
            sauber["server"] = server  # Zugangsdaten, Abfrage oder Anker in der Adresse: verworfen statt still gekürzt
        if (org := pruefe_org(eintrag.get("org"))):
            sauber["org"] = org
        ergebnis[rid] = sauber
    return ergebnis


# ---------------------------------------------------------------- Ergebnis je Fund


def baue_fund(q: Quelle, g: Gruppe, speicher: dict, token_da: bool) -> dict:
    merkmale: list[str] = []
    dienste: list[str] = []   # aus starken Merkmalen, wichtigstes zuletzt
    aus_registrierung: list[str] = []   # Teilmenge von ``dienste``, in Reihenfolge der Registrierungen
    unit = g.unit_name
    aktiv = q.aktiv(unit) if unit else None
    if g.prozesse and unit and aktiv is None:
        aktiv = True

    if unit:
        bekannt = dienst_aus(BEKANNT_UNIT, unit)
        if bekannt:
            dienste.append(bekannt)
            merkmale.append(f"systemd-Unit {unit}" + (" (gestoppt)" if aktiv is False else ""))
        else:
            merkmale.append(f"Dienst {unit}" + (" (gestoppt)" if aktiv is False else ""))
        if g.unit and g.unit.argv:
            programm = dienst_aus(BEKANNT_PROGRAMM, PurePosixPath(g.unit.argv[0]).name)
            if programm and not bekannt:
                dienste.append(programm)
                merkmale.append(f"startet {PurePosixPath(g.unit.argv[0]).name}")
    if g.stichwort:
        merkmale.append(f"Name enthält „{g.stichwort}“")
    if g.unit and g.unit.container or any(CONTAINER.search(" ".join(p.argv)) for p in g.prozesse):
        merkmale.append("startet Container")
    for p in g.prozesse[:1]:
        dienst = dienst_aus(BEKANNT_PROGRAMM, p.programm)
        if dienst:
            dienste.append(dienst)
        unterbefehl = p.argv[1] if len(p.argv) > 1 and re.fullmatch(r"[a-z]{2,16}", p.argv[1]) else ""
        text = f"Prozess {fuer_terminal(p.programm)[:40]}"
        text += f" {unterbefehl}" if unterbefehl and dienst != "github" else " läuft"
        merkmale.append(text + (" in einem Container" if p.container else ""))

    name = server = None
    runner_verz = None
    fremd: list[str] = []   # Dienste aus Registrierungen, die nur ein Prozess der Unit nennt
    for reg in g.registrierungen:
        if reg.nur_prozess:
            merkmale.append(f"{reg.pfad} nur von einem Prozess genannt (nicht übernommen)")
            if reg.art != "kaputt":
                fremd.append("gitlab" if reg.art == "gitlab" else "github" if reg.art == "github" else reg.hinweis or "forgejo")
            continue
        if reg.art == "kaputt":
            merkmale.append(f"{reg.pfad} nicht lesbar oder ungültig")
            continue
        name = name or reg.name
        server = server or reg.server
        if reg.art == "github":
            dienste.append("github")
            aus_registrierung.append("github")
            runner_verz = runner_verz or str(PurePosixPath(reg.pfad).parent)
            merkmale.append(f"{reg.pfad} mit gitHubUrl" if reg.server else f"{reg.pfad} ohne gültige gitHubUrl")
        elif reg.art == "act":
            vorher = [d for d in dienste if d in ("forgejo", "gitea")]
            dienste.append(reg.hinweis or (vorher[-1] if vorher else "forgejo"))
            aus_registrierung.append(dienste[-1])
            merkmale.append(f"{reg.pfad} mit address {reg.server}" if reg.server else f"{reg.pfad} ohne gültige address")
        elif reg.art == "gitlab":
            dienste.append("gitlab")
            aus_registrierung.append("gitlab")
            merkmale.append(f"{reg.pfad} mit url {reg.server}" if reg.server else f"{reg.pfad} ohne gültige url")
            if reg.anzahl > 1:
                merkmale.append(f"{reg.anzahl} Runner in {PurePosixPath(reg.pfad).name}")
        if reg.name is None:
            merkmale.append("Name in der Registrierung fehlt oder enthält ungültige Zeichen")
    if not runner_verz:
        for p in g.prozesse:
            if p.programm == "Runner.Listener" and (pfad := pruefe_pfad(p.argv[0])):
                eltern = PurePosixPath(pfad).parent
                runner_verz = str(eltern.parent if eltern.name.startswith("bin") else eltern)

    # Die erste Registrierung der Gruppe entscheidet (Reihenfolge: --config, Programmordner, Arbeitsordner);
    # eine fremde .runner im Arbeitsordner kippt die Anzeige so nicht (#109).
    dienst = aus_registrierung[0] if aus_registrierung else dienste[-1] if dienste else "unbekannt"
    widerspruch = len(set(d if d not in ("forgejo", "gitea") else "act" for d in dienste + fremd)) > 1
    if widerspruch:
        merkmale.append("widersprüchliche Merkmale: " + ", ".join(ANZEIGE[d] for d in dict.fromkeys(dienste + fremd)))

    bestaetigt = False
    server_version = None
    grund = None
    if dienst != "unbekannt" and server and not unit:
        grund = "Server nicht geprüft (kein systemd-Dienst)"  # E-17: keine Abfrage für Funde ohne Unit
        merkmale.append(grund)
    elif dienst != "unbekannt" and server:
        echt, server_version, text = probe(q, dienst, server, speicher)
        if text:
            merkmale.append(text)
        if echt:
            bestaetigt = True
            if echt != dienst and {echt, dienst} <= {"forgejo", "gitea"}:
                dienst = echt  # der Server entscheidet zwischen Forgejo und Gitea
        else:
            grund = text
    elif dienst != "unbekannt":
        grund = "keine Registrierung gefunden"

    if dienst == "unbekannt":
        grad = "unklar"
    elif bestaetigt and not widerspruch and (unit or g.prozesse):
        grad = "sicher"
    else:
        grad = "wahrscheinlich"
        if not grund:
            grund = "widersprüchliche Merkmale" if widerspruch else "kein Dienst und kein Prozess"

    runner_version = None
    if dienst == "github" and runner_verz:
        runner_version = github_version(q, runner_verz)
    elif dienst != "unbekannt" and unit:
        runner_version = journal_version(q, unit)
    if dienst == "github":
        version = runner_version
    else:
        teile = [server_version] if server_version else []
        if runner_version:
            teile.append(f"Runner {kurz_version(runner_version)}")
        version = " / ".join(teile) or None

    if not name:
        if unit:
            stamm = unit.rsplit(".service", 1)[0]
            name = pruefe_name(stamm.split(".")[-1] if dienst == "github" else stamm) or pruefe_name(stamm[:64])
        name = name or (pruefe_name(g.prozesse[0].programm) if g.prozesse else None) or "runner"

    faehig = dict(FAEHIG[dienst])
    if not unit:
        faehig["status"] = faehig["logs"] = False  # ohne Unit weder Dienst noch Journal
    return {
        "id": als_id(name),
        "name": name,
        "dienst": dienst,
        "server": server,
        "version": version,
        "grad": grad,
        "merkmale": merkmale,
        "einstufung": EINSTUFUNG[dienst],
        "stand": "angebunden" if dienst == "github" and token_da and unit else "offen",  # E-18
        "unit": unit,
        "log": f"{runner_verz}/_diag" if dienst == "github" and runner_verz and unit else None,
        "faehig": faehig,
        "aktiv": aktiv,
        "_grund": grund,
    }


def wende_zuordnung_an(funde: list[dict], zuordnung: dict[str, dict], q: Quelle | None = None) -> list[dict]:
    """Zuordnung und Ignorieren aus ``runner.json`` übernehmen; von Hand angelegte Runner ergänzen.

    Ein Fund ohne Unit (nur ``.runner`` in ``/home``, nur ein Prozess) wird nie „angebunden“ (E-18)."""
    gesehen = set()
    for fund in funde:
        eintrag = zuordnung.get(fund["id"])
        if not eintrag:
            continue
        gesehen.add(fund["id"])
        if eintrag.get("unit") and eintrag["unit"] != fund["unit"]:
            fund["aktiv"] = q.aktiv(eintrag["unit"]) if q else None  # andere Unit → deren Zustand
        for schluessel in ("name", "unit", "log", "stand"):
            if schluessel in eintrag:
                fund[schluessel] = eintrag[schluessel]
        if fund["stand"] == "angebunden" and not fund["unit"]:
            fund["stand"] = "offen"
        if eintrag.get("dienst") and eintrag["dienst"] != fund["dienst"]:
            fund["dienst"] = eintrag["dienst"]
            fund["einstufung"] = EINSTUFUNG[fund["dienst"]]
            fund["faehig"] = dict(FAEHIG[fund["dienst"]])
            fund["merkmale"].append(f"von Hand zugeordnet: {ANZEIGE[fund['dienst']]}")
    for rid, eintrag in zuordnung.items():
        if rid in gesehen or not eintrag.get("unit"):
            continue
        dienst = eintrag.get("dienst", "unbekannt")
        funde.append({
            "id": rid, "name": eintrag.get("name", rid), "dienst": dienst, "server": None, "version": None,
            "grad": "unklar", "merkmale": ["von Hand zugeordnet"], "einstufung": EINSTUFUNG[dienst],
            "stand": eintrag.get("stand", "grund"), "unit": eintrag["unit"], "log": eintrag.get("log"),
            "faehig": dict(FAEHIG[dienst]), "aktiv": q.aktiv(eintrag["unit"]) if q else None, "_grund": None,
        })
    return funde


def erkenne(wurzel: Path | str = "/", runner_verz: Path | str | None = None, zuordnung_datei: Path | str | None = None,
            token_datei: Path | str | None = None, netz: bool = True, quelle: Quelle | None = None) -> dict:
    """Alle Funde: ``{"zeit", "geprueft", "runner": [...]}``. Wirft nie."""
    q = quelle or Quelle(wurzel, netz=netz)
    funde: list[dict] = []
    try:
        gruppen = sammle(q, str(runner_verz) if runner_verz else None)
    except Exception:  # noqa: BLE001
        gruppen = []
    try:
        token_da = bool(token_datei) and os.path.exists(token_datei)  # nur ob es eins gibt, nie lesen
    except (OSError, ValueError):
        token_da = False
    speicher: dict = {}
    for g in gruppen:
        try:
            funde.append(baue_fund(q, g, speicher, token_da))
        except Exception:  # noqa: BLE001 – ein seltsamer Fund darf die anderen nicht verdecken
            continue
    # E-18: IDs zuerst an Funde mit Unit vergeben – ein nachgemachter Fund (z. B. ``.runner`` in
    # ``/home``) bekommt so nie die ID eines echten Runners und damit nie dessen Zuordnung.
    vergeben: dict[str, int] = {}
    reihe = sorted(funde, key=lambda f: (f["unit"] is None, f["unit"] or "", DIENSTE.index(f["dienst"]), f["name"], f["server"] or ""))
    for f in reihe:
        n = vergeben.get(f["id"], 0) + 1
        vergeben[f["id"]] = n
        if n > 1:
            f["id"] = f"{f['id'][:60]}-{n}"
    funde.sort(key=lambda f: (DIENSTE.index(f["dienst"]), f["name"], f["unit"] is None, f["unit"] or "", f["id"]))
    funde = wende_zuordnung_an(funde, lies_zuordnung(zuordnung_datei), q)
    return {"zeit": time.time(), "geprueft": GEPRUEFT, "runner": [{k: v for k, v in f.items() if not k.startswith("_")} | {"grund": f.get("_grund")} for f in funde]}


MAX_ERGEBNIS = 2 * 1024 * 1024
FUND_SCHLUESSEL = ("id", "name", "dienst", "server", "version", "grad", "merkmale", "einstufung", "stand",
                   "unit", "log", "faehig", "aktiv", "grund")


def pruefe_ergebnis(roh: bytes | None) -> dict | None:
    """Ausgabe von ``--json`` prüfen, bevor der Sammler sie schreibt (Form, Werte, Größe), sonst None."""
    if not roh or len(roh) > MAX_ERGEBNIS:
        return None
    try:
        daten = json.loads(roh.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    funde = daten.get("runner") if isinstance(daten, dict) else None
    if not isinstance(funde, list) or len(funde) > 200 or not isinstance(daten.get("zeit"), (int, float)):
        return None
    sauber = []
    for f in funde:
        if not isinstance(f, dict) or not isinstance(f.get("id"), str) or als_id(f["id"]) != f["id"]:
            return None
        if f.get("dienst") not in DIENSTE or f.get("grad") not in GRADE or f.get("stand") not in STAENDE:
            return None
        if not isinstance(f.get("merkmale"), list) or not isinstance(f.get("faehig"), dict):
            return None
        sauber.append({k: f.get(k) for k in FUND_SCHLUESSEL})
    return {"zeit": daten["zeit"], "geprueft": GEPRUEFT, "runner": sauber}


# ---------------------------------------------------------------- Textausgabe für einrichten.sh

BREITE = 80


def _spalte(text: object, breite: int) -> str:
    text = fuer_terminal(text if text else "–")
    if len(text) > breite - 1:
        text = text[: breite - 2] + "…"
    return text.ljust(breite)


def server_kurz(server: str | None) -> str:
    return re.sub(r"^https?://", "", server) if server else "–"


def als_text(ergebnis: dict, farbe: bool = False, einrichtung: bool = False) -> str:
    """Abschnitt „Runner auf dieser VM“ ohne Überschrift, 80 Zeichen breit, ohne Farben lesbar."""
    def f(code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if farbe else text

    zeilen: list[str] = []
    funde = ergebnis.get("runner") or []
    for fund in funde:
        grad = fund.get("grad")
        if fund.get("stand") == "ignoriert":
            zeichen, art, rechts = "–", "90", "ignoriert"
        else:
            zeichen, art = {"sicher": ("✓", "32"), "wahrscheinlich": ("!", "33")}.get(grad, ("?", "33"))
            rechts = grad or "unklar"
        # Spalte „Version“ wie im Design: bei GitHub die Runner-, sonst die Server-Version (ohne → „–“)
        version = (fund.get("version") or "").split(" / ")[0]
        version = None if version.startswith("Runner ") else version or None
        zeile = (f"  {f(art, zeichen)} " + f("1", _spalte(fund.get("name"), 15)) + _spalte(ANZEIGE.get(fund.get("dienst"), "unbekannt"), 10)
                 + _spalte(server_kurz(fund.get("server")), 26) + _spalte(version, 10) + f("32" if rechts == "sicher" else "33", rechts))
        zeilen.append(zeile)
        if fund.get("stand") == "ignoriert":
            continue
        if grad == "unklar":
            hinweise = textwrap.wrap("Hinweise: " + ", ".join(fuer_terminal(m) for m in fund.get("merkmale") or []),
                                     width=BREITE, initial_indent="      ", subsequent_indent="                ",
                                     break_on_hyphens=False)
            zeilen += [f("90", z) for z in hinweise[:4]]
            zeilen.append(f("90", "      → Im Browser zuordnen oder ignorieren (Schritt „Runner“)"))
        elif grad == "sicher" and fund.get("aktiv") is False:
            zeilen.append(f("90", "      Hinweis: Dienst gestoppt – der Monitor zeigt ihn als „Gestoppt“"))
        elif grad == "wahrscheinlich":
            grund = fuer_terminal(fund.get("grund") or "Server nicht bestätigt")
            zeilen += [f("90", z) for z in textwrap.wrap(f"Hinweis: {grund} – im Browser prüfen (Schritt „Runner“)", width=BREITE,
                                                       initial_indent="      ", subsequent_indent="      ")[:2]]
    if funde and einrichtung:
        text = ("Der Runner bleibt unverändert" if len(funde) == 1 else "Die Runner bleiben unverändert")
        zeilen.append(f("90", f"    {text}, es wird nur der Monitor eingerichtet."))
    return "\n".join(zeilen)


def main(argv: list[str] | None = None) -> int:
    teil = argparse.ArgumentParser(prog="python3 -m runner_monitor.erkennung", description="Runner auf dieser VM erkennen.")
    art = teil.add_mutually_exclusive_group()
    art.add_argument("--json", action="store_true", help="Ergebnis als JSON (Vorgabe)")
    art.add_argument("--text", action="store_true", help="Zeilen für einrichten.sh; Rückgabe 3 = kein Runner")
    teil.add_argument("--farbe", action="store_true", help="Textausgabe mit ANSI-Farben")
    teil.add_argument("--einrichtung", action="store_true", help="Schlusszeile für die Einrichtung")
    teil.add_argument("--ohne-netz", action="store_true", help="keine Server-API-Probe")
    teil.add_argument("--runner-verz", default="/opt/actions-runner")
    teil.add_argument("--zuordnung", default="/etc/runner-monitor/runner.json")
    teil.add_argument("--token-datei", default="/etc/runner-monitor/github-token")
    try:
        args = teil.parse_args(argv)
    except SystemExit as ende:
        return int(ende.code or 0)
    try:
        ergebnis = erkenne(runner_verz=args.runner_verz, zuordnung_datei=args.zuordnung,
                           token_datei=args.token_datei, netz=not args.ohne_netz)
        if args.text:
            text = als_text(ergebnis, farbe=args.farbe, einrichtung=args.einrichtung)
            if text:
                print(text)
            return 0 if ergebnis["runner"] else 3
        print(json.dumps(ergebnis, ensure_ascii=False, indent=2))
        return 0
    except Exception as fehler:  # noqa: BLE001 – nie mit Traceback enden
        print(f"Runner-Erkennung fehlgeschlagen: {type(fehler).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
