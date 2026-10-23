"""Systemwerte aus ``/proc``: CPU je Kern, RAM, Swap, Last, Netz, Prozesse und Platten.

Alles hier läuft ohne besondere Rechte. Die Funktionen nehmen den Inhalt der Dateien als
Text entgegen, damit sie sich mit Beispieldaten testen lassen (``tests/fixtures``).
"""

from __future__ import annotations

import os
import pwd
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PROC = Path("/proc")
KIB = 1024


# ---------------------------------------------------------------- CPU


@dataclass(frozen=True)
class CpuZeiten:
    gesamt: int
    leer: int


def lies_cpu_zeiten(stat_text: str) -> list[CpuZeiten]:
    """Zeilen ``cpu0 …`` bis ``cpuN …`` aus /proc/stat (ohne die Summenzeile ``cpu``)."""
    kerne: list[CpuZeiten] = []
    for zeile in stat_text.splitlines():
        if not zeile.startswith("cpu") or zeile.startswith("cpu "):
            continue
        teile = zeile.split()
        werte = [int(x) for x in teile[1:]]
        # user nice system idle iowait irq softirq steal guest guest_nice
        leer = werte[3] + (werte[4] if len(werte) > 4 else 0)
        gesamt = sum(werte[:8])  # guest ist in user schon enthalten
        kerne.append(CpuZeiten(gesamt=gesamt, leer=leer))
    return kerne


def cpu_auslastung(vorher: list[CpuZeiten], jetzt: list[CpuZeiten]) -> list[float]:
    """Prozent je Kern zwischen zwei Messungen (0–100)."""
    ergebnis = []
    for a, b in zip(vorher, jetzt):
        d_gesamt = b.gesamt - a.gesamt
        d_leer = b.leer - a.leer
        if d_gesamt <= 0:
            ergebnis.append(0.0)
            continue
        ergebnis.append(round(max(0.0, min(100.0, 100.0 * (d_gesamt - d_leer) / d_gesamt)), 1))
    return ergebnis


# ---------------------------------------------------------------- Speicher, Last


def lies_meminfo(text: str) -> dict[str, int]:
    """Werte aus /proc/meminfo in Byte."""
    werte: dict[str, int] = {}
    for zeile in text.splitlines():
        if ":" not in zeile:
            continue
        name, rest = zeile.split(":", 1)
        teile = rest.split()
        if not teile:
            continue
        zahl = int(teile[0])
        werte[name] = zahl * KIB if len(teile) > 1 and teile[1] == "kB" else zahl
    return werte


def speicher(meminfo: dict[str, int]) -> dict:
    gesamt = meminfo.get("MemTotal", 0)
    verfuegbar = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
    swap_gesamt = meminfo.get("SwapTotal", 0)
    swap_frei = meminfo.get("SwapFree", 0)
    return {
        "ram": {"belegt": max(0, gesamt - verfuegbar), "gesamt": gesamt},
        "swap": {"belegt": max(0, swap_gesamt - swap_frei), "gesamt": swap_gesamt},
    }


def lies_last(text: str) -> list[float]:
    teile = text.split()
    return [float(teile[0]), float(teile[1]), float(teile[2])]


def startzeit(uptime_text: str, jetzt: float | None = None) -> float:
    """Zeitpunkt des Systemstarts (Unix-Zeit) aus /proc/uptime."""
    sekunden = float(uptime_text.split()[0])
    return (time.time() if jetzt is None else jetzt) - sekunden


# ---------------------------------------------------------------- Prozesse


@dataclass
class ProzessRoh:
    pid: int
    uid: int
    ticks: int
    rss: int
    befehl: str


def _lies(pfad: Path) -> str | None:
    try:
        return pfad.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def lies_prozess(verz: Path, seitengroesse: int) -> ProzessRoh | None:
    stat = _lies(verz / "stat")
    status = _lies(verz / "status")
    if stat is None or status is None:
        return None
    # Der Programmname in Klammern kann Leerzeichen und Klammern enthalten.
    rechts = stat[stat.rfind(")") + 2:].split()
    try:
        utime, stime = int(rechts[11]), int(rechts[12])
        rss_seiten = int(rechts[21])
    except (IndexError, ValueError):
        return None
    uid = 0
    for zeile in status.splitlines():
        if zeile.startswith("Uid:"):
            uid = int(zeile.split()[1])
            break
    try:
        roh = (verz / "cmdline").read_bytes()
    except OSError:
        roh = b""
    befehl = roh.replace(b"\0", b" ").decode("utf-8", "replace").strip()
    if not befehl:
        befehl = "[" + stat[stat.find("(") + 1:stat.rfind(")")] + "]"
    return ProzessRoh(pid=int(verz.name), uid=uid, ticks=utime + stime, rss=rss_seiten * seitengroesse, befehl=befehl)


_namen: dict[int, str] = {}


def benutzername(uid: int) -> str:
    if uid not in _namen:
        try:
            _namen[uid] = pwd.getpwuid(uid).pw_name
        except KeyError:
            _namen[uid] = str(uid)
    return _namen[uid]


class ProzessMesser:
    """Hält die Werte der letzten Messung, um CPU-Prozente wie ``top`` zu berechnen."""

    def __init__(self, proc: Path = PROC) -> None:
        self.proc = proc
        self.takt = os.sysconf("SC_CLK_TCK")
        self.seite = os.sysconf("SC_PAGE_SIZE")
        self._vorher: dict[int, int] = {}
        self._zeit = time.monotonic()

    def messen(self, ram_gesamt: int, anzahl: int = 6) -> list[dict]:
        jetzt = time.monotonic()
        dauer = max(0.001, jetzt - self._zeit)
        neu: dict[int, int] = {}
        liste = []
        for verz in self.proc.iterdir():
            if not verz.name.isdigit():
                continue
            p = lies_prozess(verz, self.seite)
            if p is None:
                continue
            neu[p.pid] = p.ticks
            if p.pid not in self._vorher:
                continue
            cpu = (p.ticks - self._vorher[p.pid]) / self.takt / dauer * 100.0
            liste.append({
                "pid": p.pid,
                "benutzer": benutzername(p.uid),
                "cpu": round(max(0.0, cpu), 1),
                "ram": round(100.0 * p.rss / ram_gesamt, 1) if ram_gesamt else 0.0,
                "befehl": p.befehl[:500],
            })
        self._vorher, self._zeit = neu, jetzt
        liste.sort(key=lambda x: (x["cpu"], x["ram"]), reverse=True)
        return liste[:anzahl]


# ---------------------------------------------------------------- Platten

ECHTE_DATEISYSTEME = {"ext4", "ext3", "xfs", "btrfs", "zfs", "f2fs", "vfat", "exfat", "nfs", "nfs4", "cifs"}


MIN_GROESSE = 1024 ** 3  # Laufwerke unter 1 GiB werden nicht angezeigt


def einhaengepunkte(mounts_text: str) -> list[str]:
    """Echte Laufwerke aus /proc/mounts – ohne Snap-, Docker-Overlay- und Pseudo-Dateisysteme."""
    gesehen: set[str] = set()
    punkte = []
    for zeile in mounts_text.splitlines():
        teile = zeile.split()
        if len(teile) < 3:
            continue
        geraet, punkt, art = teile[0], teile[1].replace("\\040", " "), teile[2]
        if art not in ECHTE_DATEISYSTEME:
            continue
        if punkt.startswith(("/snap/", "/var/lib/docker/", "/run/", "/boot/efi")):
            continue
        if geraet in gesehen:  # Bind-Mounts desselben Geräts nur einmal
            continue
        gesehen.add(geraet)
        punkte.append(punkt)
    punkte.sort(key=lambda p: (p != "/", p))
    return punkte


def platten(mounts_text: str, schwelle_frei_gb: int) -> list[dict]:
    ergebnis = []
    for punkt in einhaengepunkte(mounts_text):
        try:
            s = os.statvfs(punkt)
        except OSError:
            continue
        gesamt = s.f_blocks * s.f_frsize
        frei = s.f_bavail * s.f_frsize
        if gesamt < MIN_GROESSE and punkt != "/":  # Kleinst-Images (z. B. squashfs, Werkzeug-Mounts) zählen nicht
            continue
        if gesamt <= 0:
            continue
        ergebnis.append({
            "pfad": punkt,
            "gesamt": gesamt,
            "frei": frei,
            "belegt": gesamt - s.f_bfree * s.f_frsize,
            # Die Aufräumschwelle des Runners gilt nur für das Wurzel-Dateisystem.
            "schwelleFrei": schwelle_frei_gb * 10**9 if punkt == "/" else 0,
        })
    return ergebnis


# ---------------------------------------------------------------- Netz

# Virtuelle Schnittstellen zählen nicht: Was ein Container über veth/docker0 schickt, läuft
# ohnehin über die echte Schnittstelle und würde sonst doppelt gezählt.
VIRTUELL = ("lo", "docker", "br-", "veth", "virbr", "vnet", "cni", "flannel", "kube", "dummy", "ifb", "tap",
            "tun", "wg", "tailscale", "zt")  # VPN-Tunnel laufen ebenfalls über die echte Schnittstelle


def lies_netz(text: str) -> dict[str, tuple[int, int]]:
    """``/proc/net/dev`` → {Schnittstelle: (empfangen, gesendet)} in Bytes, ohne virtuelle."""
    ergebnis: dict[str, tuple[int, int]] = {}
    for zeile in text.splitlines()[2:]:
        if ":" not in zeile:
            continue
        name, werte = zeile.split(":", 1)
        name = name.strip()
        felder = werte.split()
        if not name or name.startswith(VIRTUELL) or len(felder) < 9:
            continue
        try:
            ergebnis[name] = (int(felder[0]), int(felder[8]))
        except ValueError:
            continue
    return ergebnis


def netz_rate(vorher: dict[str, tuple[int, int]], jetzt: dict[str, tuple[int, int]], sekunden: float) -> dict:
    """Bytes je Sekunde, summiert über alle echten Schnittstellen. Zähler-Neustart zählt als 0."""
    empfangen = gesendet = 0
    if sekunden > 0:
        for name, (rx, tx) in jetzt.items():
            if name in vorher:
                empfangen += max(0, rx - vorher[name][0])
                gesendet += max(0, tx - vorher[name][1])
        empfangen = round(empfangen / sekunden)
        gesendet = round(gesendet / sekunden)
    return {"empfangen": empfangen, "gesendet": gesendet, "schnittstellen": sorted(jetzt)}


# ---------------------------------------------------------------- Betriebssystem


def beschreibung(os_release: Path = Path("/etc/os-release")) -> str:
    """Kurz für Fehlermeldungen: „Ubuntu 24.04.1 LTS, Python 3.12“."""
    name = ""
    text = _lies(os_release) or ""
    for zeile in text.splitlines():
        if zeile.startswith("PRETTY_NAME="):
            name = zeile.split("=", 1)[1].strip().strip('"')
            break
    py = f"Python {sys.version_info.major}.{sys.version_info.minor}"
    return f"{name}, {py}" if name else py


# ---------------------------------------------------------------- Zusammenfassung


class SystemMesser:
    def __init__(self, proc: Path = PROC, schwelle_frei_gb: int = 25) -> None:
        self.proc = proc
        self.schwelle = schwelle_frei_gb
        self._cpu_vorher = lies_cpu_zeiten((proc / "stat").read_text())
        self._netz_vorher = self._netz()
        self._netz_zeit = time.monotonic()
        self.prozesse = ProzessMesser(proc)

    def _netz(self) -> dict[str, tuple[int, int]]:
        text = _lies(self.proc / "net" / "dev")
        return lies_netz(text) if text else {}

    def system(self) -> dict:
        jetzt = lies_cpu_zeiten((self.proc / "stat").read_text())
        kerne = cpu_auslastung(self._cpu_vorher, jetzt)
        self._cpu_vorher = jetzt
        sp = speicher(lies_meminfo((self.proc / "meminfo").read_text()))
        netz_jetzt, zeit_jetzt = self._netz(), time.monotonic()
        netz = netz_rate(self._netz_vorher, netz_jetzt, zeit_jetzt - self._netz_zeit)
        self._netz_vorher, self._netz_zeit = netz_jetzt, zeit_jetzt
        return {
            "zeit": time.time(),
            "kerne": kerne,
            "cpu": round(sum(kerne) / len(kerne), 1) if kerne else 0.0,
            "last": lies_last((self.proc / "loadavg").read_text()),
            "ram": sp["ram"],
            "swap": sp["swap"],
            "netz": netz,
            "start": startzeit((self.proc / "uptime").read_text()),
        }

    def platten(self) -> list[dict]:
        return platten((self.proc / "mounts").read_text(), self.schwelle)
