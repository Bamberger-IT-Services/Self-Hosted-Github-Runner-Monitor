"""Der Gesamtzustand des Monitors und die Verteilung an alle offenen Browserfenster.

Ein Hintergrund-Thread misst die Systemwerte (jede Sekunde), liest die Dateien des
Sammlers und baut daraus die Bereiche ``status``, ``system``, ``prozesse``, ``platten``,
``container``, ``workflows``, ``update`` und ``log``. Jeder Bereich geht als
Server-Sent Event an alle verbundenen Fenster (Format: ``docs/FUNKTIONSWEISE.md``).
"""

from __future__ import annotations

import json
import logging
import queue
import socket
import threading
import time
from collections import deque
from pathlib import Path

from . import VERSION, runner, system
from .konfig import Konfig

LOG = logging.getLogger("runner_monitor")
MAX_ZEILEN = 1500
MAX_EREIGNISSE = 50
VERLAUF = 600  # 10 Minuten bei 1 Wert je Sekunde


def lies_json(pfad: Path, vorgabe=None):
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return vorgabe


class Verteiler:
    """Hält je Browserfenster eine Warteschlange. Volle Schlangen (hängende Fenster) fliegen raus."""

    def __init__(self) -> None:
        self._schlangen: set[queue.Queue] = set()
        self._sperre = threading.Lock()

    def anmelden(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=2000)
        with self._sperre:
            self._schlangen.add(q)
        return q

    def abmelden(self, q: queue.Queue) -> None:
        with self._sperre:
            self._schlangen.discard(q)

    def sende(self, bereich: str, daten: object) -> None:
        nachricht = (bereich, json.dumps(daten, ensure_ascii=False, separators=(",", ":")))
        with self._sperre:
            for q in list(self._schlangen):
                try:
                    q.put_nowait(nachricht)
                except queue.Full:
                    self._schlangen.discard(q)

    @property
    def anzahl(self) -> int:
        return len(self._schlangen)


class Zustand:
    def __init__(self, konfig: Konfig) -> None:
        self.k = konfig
        self.verteiler = Verteiler()
        self._sperre = threading.RLock()
        self.bereiche: dict[str, object] = {}
        self.cpu_verlauf: deque[float] = deque(maxlen=VERLAUF)
        self.ram_verlauf: deque[float] = deque(maxlen=VERLAUF)
        self.zeilen: deque[dict] = deque(maxlen=MAX_ZEILEN)
        self.ereignisse: deque[dict] = deque(maxlen=MAX_EREIGNISSE)
        self.letzte_jobs: deque[dict] = deque(maxlen=5)
        self.job_lokal: dict | None = None      # aus dem Journal: {"name", "start"}
        self.schritt_nr = 0
        self.job_zuordnung: dict[str, dict] = {}  # Jobname → {repo, workflow} aus der GitHub-Abfrage
        self.offline_seit: float | None = None
        self._dateistand: dict[Path, float] = {}
        self.messer: system.SystemMesser | None = None
        try:
            self.messer = system.SystemMesser(schwelle_frei_gb=konfig.schwelle_frei_gb)
        except OSError:
            LOG.warning("Keine Systemwerte verfügbar (kein /proc) – nur Oberfläche, z. B. für ?demo")

    # ------------------------------------------------------------ Hilfen

    def _setze(self, bereich: str, daten: object) -> None:
        with self._sperre:
            self.bereiche[bereich] = daten
        self.verteiler.sende(bereich, daten)

    def momentaufnahme(self) -> list[tuple[str, object]]:
        """Alles, was ein neu verbundenes Fenster zuerst braucht."""
        with self._sperre:
            liste = [(k, v) for k, v in self.bereiche.items() if k != "system" and not k.startswith("_")]
            if "system" in self.bereiche:
                sys_daten = dict(self.bereiche["system"])  # type: ignore[arg-type]
                sys_daten["verlauf"] = {"cpu": list(self.cpu_verlauf), "ram": list(self.ram_verlauf)}
                liste.insert(0, ("system", sys_daten))
            liste.append(("log", {"neu": True, "ereignisse": list(self.ereignisse), "zeilen": list(self.zeilen)}))
        return liste

    def _geaendert(self, pfad: Path) -> bool:
        try:
            stand = pfad.stat().st_mtime
        except OSError:
            stand = 0.0
        if self._dateistand.get(pfad) == stand:
            return False
        self._dateistand[pfad] = stand
        return True

    # ------------------------------------------------------------ Runner-Ereignisse (Threads)

    def bei_journal(self, e: runner.JobEreignis) -> None:
        with self._sperre:
            if e.art == "start":
                self.job_lokal = {"name": e.name, "start": e.zeit}
                self.schritt_nr = 0
                info = self.job_zuordnung.get(e.name, {})
                eintrag = {"zeit": e.zeit, "art": "start", "name": e.name, **info}
            elif e.art == "ende":
                start = self.job_lokal["start"] if self.job_lokal and self.job_lokal["name"] == e.name else None
                info = self.job_zuordnung.get(e.name, {})
                dauer = e.zeit - start if start else None
                self.letzte_jobs.appendleft({"name": e.name, "ergebnis": e.ergebnis, "dauer": dauer, "ende": e.zeit,
                                             "repo": info.get("repo", ""), "workflow": info.get("workflow", "")})
                self.job_lokal = None
                eintrag = {"zeit": e.zeit, "art": "ende", "name": e.name, "ergebnis": e.ergebnis, "dauer": dauer, **info}
            elif e.art in ("dienst-gestartet", "dienst-gestoppt"):
                if e.art == "dienst-gestoppt":
                    self.job_lokal = None
                eintrag = {"zeit": e.zeit, "art": e.art}
            else:
                return
            self.ereignisse.append(eintrag)
        self.verteiler.sende("log", {"ereignisse": [eintrag], "zeilen": []})

    def bei_seite(self, art: str, wert: object) -> None:
        with self._sperre:
            if art == "schritt":
                self.schritt_nr += 1
                gh_job = (self.bereiche.get("_github") or {}).get("job") if isinstance(self.bereiche.get("_github"), dict) else None
                name = ""
                von = 0
                if gh_job and gh_job.get("schritte"):
                    von = len(gh_job["schritte"])
                    idx = min(int(gh_job.get("schritt", 1)), von) - 1
                    name = gh_job["schritte"][idx]
                zeile = {"zeit": time.time(), "art": "schritt", "nr": self.schritt_nr, "von": von, "name": name or f"Schritt {self.schritt_nr}"}
            else:
                zeit, text = wert  # type: ignore[misc]
                zeile = {"zeit": zeit, "text": text[:4000]}
            self.zeilen.append(zeile)
        self.verteiler.sende("log", {"ereignisse": [], "zeilen": [zeile]})

    # ------------------------------------------------------------ Bereiche bauen

    def _status(self) -> dict:
        reg = runner.lies_registrierung(self.k.runner_verz)
        dienst = runner.dienst_status(runner.finde_unit()) if reg else {"zustand": "fehlt", "seit": None}
        gh = lies_json(self.k.lauf_verz / "github.json", {}) or {}
        gh_runner = gh.get("runner") or {}
        gh_zustand = gh_runner.get("zustand", "unbekannt") if gh.get("abfrage") == "ok" else "unbekannt"
        if gh_zustand == "offline":
            self.offline_seit = self.offline_seit or time.time()
        else:
            self.offline_seit = None
        job = None
        with self._sperre:
            gh_job = gh.get("job")
            if self.job_lokal or (gh_job and dienst["zustand"] == "aktiv"):
                job = {
                    "name": (self.job_lokal or {}).get("name") or (gh_job or {}).get("name", ""),
                    "start": (self.job_lokal or {}).get("start") or (gh_job or {}).get("start"),
                    "repo": "", "workflow": "", "privat": False, "ref": None, "schritte": [], "schritt": self.schritt_nr or 1,
                }
                if gh_job and (not self.job_lokal or gh_job.get("name") == self.job_lokal.get("name")):
                    job.update({k: gh_job.get(k) for k in ("repo", "workflow", "privat", "ref", "schritte", "schritt", "url")})
            letzte = list(self.letzte_jobs)
        labels = gh_runner.get("labels") or self.k.weitere.get("RUNNER_LABELS", "self-hosted,linux,x64").split(",")
        return {
            "vm": self.k.vm_name or socket.gethostname(),
            "runner": reg.get("name", ""),
            "eingerichtet": bool(reg),
            "labels": labels,
            "version": runner.runner_version(self.k.runner_verz) if reg else "",
            "monitorVersion": VERSION,
            "dienst": {"zustand": dienst["zustand"], "seit": dienst.get("seit")},
            "github": {"zustand": gh_zustand, "seit": self.offline_seit},
            "job": job,
            "letzteJobs": letzte,
        }

    def _workflows(self, gh: dict) -> dict:
        abgefragt = gh.get("abgefragt") or 0
        return {
            "org": gh.get("org", ""),
            "abfrage": gh.get("abfrage", "kein-token"),
            "abgefragt": gh.get("letzterErfolg") or abgefragt,
            "versucht": abgefragt,
            "naechste": abgefragt + 30 if abgefragt else None,
            "tokenAblauf": gh.get("tokenAblauf"),
            "kontingent": gh.get("kontingent") or {},
            "repos": gh.get("repos") or [],
            "fehler": gh.get("fehler", ""),
            "runnerGrund": (gh.get("runner") or {}).get("grund", ""),
        }

    def _update(self) -> dict:
        release = lies_json(self.k.lauf_verz / "release.json", {}) or {}
        status = lies_json(self.k.update_status_datei, {}) or {}
        einstellungen = lies_json(self.k.einstellungen_datei, {}) or {}
        return {
            "installiert": VERSION,
            "neueste": release,
            "status": status,
            "auto": bool(einstellungen.get("autoUpdate")),
        }

    def _github_dateien(self) -> None:
        pfad = self.k.lauf_verz / "github.json"
        if self._geaendert(pfad):
            gh = lies_json(pfad, {}) or {}
            with self._sperre:
                self.bereiche["_github"] = gh
                if gh.get("job"):
                    j = gh["job"]
                    self.job_zuordnung[j.get("name", "")] = {"repo": j.get("repo", ""), "workflow": j.get("workflow", "")}
            self._setze("workflows", self._workflows(gh))
        pfad = self.k.lauf_verz / "docker.json"
        if self._geaendert(pfad):
            self._setze("container", (lies_json(pfad, {}) or {}).get("container", []))
        for pfad in (self.k.lauf_verz / "release.json", self.k.update_status_datei, self.k.einstellungen_datei):
            if self._geaendert(pfad):
                self._setze("update", self._update())
                break

    # ------------------------------------------------------------ Schleife

    def starte(self) -> None:
        if self.messer is not None:
            runner.JournalFolger(self.bei_journal).start()
            runner.SeitenFolger(self.k.runner_verz / "_diag" / "pages", self.bei_seite).start()
        threading.Thread(target=self._schleife, name="messen", daemon=True).start()

    def _schleife(self) -> None:  # pragma: no cover – Endlosschleife
        takt = 0
        self._setze("update", self._update())
        while True:
            beginn = time.monotonic()
            try:
                self.ein_takt(takt)
            except Exception:  # noqa: BLE001 – ein Fehler darf die Messung nie stoppen
                LOG.exception("Fehler beim Messen")
            takt += 1
            time.sleep(max(0.05, 1.0 - (time.monotonic() - beginn)))

    def ein_takt(self, takt: int) -> None:
        if self.messer is not None:
            daten = self.messer.system()
            self.cpu_verlauf.append(daten["cpu"])
            ram = daten["ram"]
            self.ram_verlauf.append(round(100.0 * ram["belegt"] / ram["gesamt"], 1) if ram["gesamt"] else 0.0)
            self._setze("system", daten)
            if takt % 2 == 0:
                self._setze("prozesse", self.messer.prozesse.messen(ram["gesamt"]))
            if takt % 10 == 0:
                self._setze("platten", self.messer.platten())
        self._github_dateien()
        if takt % 2 == 0:
            self._setze("status", self._status())
