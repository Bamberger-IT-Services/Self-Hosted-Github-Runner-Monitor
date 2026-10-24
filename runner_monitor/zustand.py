"""Der Gesamtzustand des Monitors und die Verteilung an alle offenen Browserfenster.

Ein Hintergrund-Thread misst die Systemwerte (jede Sekunde), liest die Dateien des
Sammlers und baut daraus die Bereiche ``status``, ``system``, ``prozesse``, ``platten``,
``container``, ``workflows``, ``update`` und ``log``. Jeder Bereich geht als
Server-Sent Event an alle verbundenen Fenster (Format: ``docs/FUNKTIONSWEISE.md``).
"""

from __future__ import annotations

import json
import logging
import math
import os
import queue
import socket
import tempfile
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
VERLAUF_SICHERN = 10  # Sekunden zwischen zwei Sicherungen nach verlauf.json
VERLAUF_LUECKE = 60  # größere Lücke (Monitor länger aus) → gesicherten Verlauf verwerfen
GH_START_TOLERANZ = 120  # Sekunden: so viel früher darf GitHubs started_at vor dem lokalen Jobstart liegen


def lies_json(pfad: Path, vorgabe=None):
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return vorgabe


ENDE = ("_ende", "")  # letzte Nachricht einer rausgeworfenen Schlange: der Strom endet, der Browser verbindet neu


class Verteiler:
    """Hält je Browserfenster eine Warteschlange.

    Eine volle Schlange (Fenster liest nicht schnell genug) wird geleert und bekommt nur noch ENDE:
    Der Server beendet dann den Strom, der Browser verbindet sich neu und bekommt den aktuellen Stand.
    Bis 0.3.0 blieb der Strom offen und lieferte nur noch Lebenszeichen – das Dashboard stand auf
    „Getrennt“, bis der Dienst neu gestartet wurde.
    """

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
                    with q.mutex:
                        q.queue.clear()
                    q.put_nowait(ENDE)

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
        self.netz_verlauf: deque[list[int]] = deque(maxlen=VERLAUF)  # [empfangen, gesendet] in B/s
        self.verlauf_start: float | None = None  # Zeit des ältesten Werts im Verlauf (Achse „seit hh:mm“)
        self._luecke = 0  # Sekunden seit dem letzten gesicherten Wert, beim ersten Messwert aufzufüllen
        self._sichern_fehler = False  # Warnung nur beim Wechsel, nicht alle 10 s
        self.zeilen: deque[dict] = deque(maxlen=MAX_ZEILEN)
        self.ereignisse: deque[dict] = deque(maxlen=MAX_EREIGNISSE)
        self.letzte_jobs: deque[dict] = deque(maxlen=5)
        self.job_lokal: dict | None = None      # aus dem Journal: {"name", "start"}
        self.schritt_nr = 0  # lokal: Zahl der Seitendateien in _diag/pages im laufenden Job
        self._schritt_hoch = 0  # höchster angezeigter Schritt im laufenden Job – die Zahl springt nie zurück
        self._schritt_job = ""  # Name des Jobs, zu dem _schritt_hoch gehört
        self._beendet: tuple[str, float] | None = None  # (Name, Ende) des letzten Jobs – GitHub meldet ihn bis zu 30 s weiter
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
                sys_daten["verlauf"] = {"cpu": list(self.cpu_verlauf), "ram": list(self.ram_verlauf), "netz": list(self.netz_verlauf),
                                        "start": self._start_des_verlaufs()}
                liste.insert(0, ("system", sys_daten))
            liste.append(("log", {"neu": True, "ereignisse": list(self.ereignisse), "zeilen": list(self.zeilen)}))
        return liste

    # ------------------------------------------------------------ Verlauf sichern (Design 0.4.0)

    @property
    def verlauf_datei(self) -> Path:
        return self.k.daten_verz / "verlauf.json"

    def _start_des_verlaufs(self) -> float:
        """Zeit des ältesten Werts: bei vollem Verlauf jetzt − 10 Min., sonst der erste Messwert."""
        jetzt = time.time()
        n = len(self.cpu_verlauf)
        if self.verlauf_start is None or n >= VERLAUF:
            return jetzt - n
        return max(self.verlauf_start, jetzt - n)

    def sichere_verlauf(self, jetzt: float | None = None) -> None:
        """Atomar nach verlauf.json (temp + rename), damit Neustarts und Updates den Verlauf nicht leeren."""
        jetzt = time.time() if jetzt is None else jetzt
        with self._sperre:
            daten = {"zeit": jetzt, "start": self._start_des_verlaufs(), "cpu": [round(w, 1) for w in self.cpu_verlauf],
                     "ram": [round(w, 1) for w in self.ram_verlauf], "netz": [list(w) for w in self.netz_verlauf]}
        pfad = self.verlauf_datei
        try:
            pfad.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=pfad.parent, prefix=".verlauf-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(daten, f, separators=(",", ":"))
                os.replace(tmp, pfad)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        except OSError as fehler:
            if not self._sichern_fehler:
                LOG.warning("Verlauf nicht gesichert (weitere Fehler werden nicht gemeldet): %s", fehler)
            self._sichern_fehler = True
        else:
            if self._sichern_fehler:
                LOG.info("Verlauf wird wieder gesichert")
            self._sichern_fehler = False

    def lade_verlauf(self, jetzt: float | None = None) -> None:
        """Übernimmt einen gesicherten Verlauf, wenn er jünger als 10 Min. ist und die Lücke höchstens 60 s."""
        jetzt = time.time() if jetzt is None else jetzt
        d = lies_json(self.verlauf_datei)
        if not isinstance(d, dict):
            return
        # Erst alles prüfen (Zahlen endlich, gleich lang), dann übernehmen – eine kaputte Datei
        # darf den Start nie verhindern und nie halbe Verläufe hinterlassen.
        try:
            zeit = float(d["zeit"])
            cpu = [float(w) for w in d["cpu"]][-VERLAUF:]
            ram = [float(w) for w in d["ram"]][-VERLAUF:]
            netz = [[int(w[0]), int(w[1])] for w in d["netz"]][-VERLAUF:]
            start = float(d.get("start", zeit - len(cpu)))
        except (KeyError, TypeError, ValueError, IndexError, OverflowError):
            return
        if not all(math.isfinite(w) for w in [zeit, start, *cpu, *ram]) or not len(cpu) == len(ram) == len(netz):
            return
        luecke = jetzt - zeit
        if not cpu or luecke < 0 or luecke > VERLAUF_LUECKE:
            return
        with self._sperre:
            self.cpu_verlauf.extend(cpu)
            self.ram_verlauf.extend(ram)
            self.netz_verlauf.extend(netz)
            self.verlauf_start = start
            self._luecke = int(luecke)

    def _haenge_an(self, cpu: float, ram: float, netz: list[int]) -> None:
        """Neuer Sekundenwert; nach einem Neustart füllt der erste Wert die Lücke seit der Sicherung."""
        anzahl = 1 + self._luecke
        self._luecke = 0
        if self.verlauf_start is None:
            self.verlauf_start = time.time()
        for _ in range(min(anzahl, VERLAUF)):
            self.cpu_verlauf.append(cpu)
            self.ram_verlauf.append(ram)
            self.netz_verlauf.append(list(netz))

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
                self._schritt_hoch, self._schritt_job = 0, e.name
                info = self.job_zuordnung.get(e.name, {})
                eintrag = {"zeit": e.zeit, "art": "start", "name": e.name, **info}
            elif e.art == "ende":
                start = self.job_lokal["start"] if self.job_lokal and self.job_lokal["name"] == e.name else None
                info = self.job_zuordnung.get(e.name, {})
                dauer = e.zeit - start if start else None
                self.letzte_jobs.appendleft({"name": e.name, "ergebnis": e.ergebnis, "dauer": dauer, "ende": e.zeit,
                                             "repo": info.get("repo", ""), "workflow": info.get("workflow", "")})
                self.job_lokal = None
                self._beendet = (e.name, e.zeit)
                eintrag = {"zeit": e.zeit, "art": "ende", "name": e.name, "ergebnis": e.ergebnis, "dauer": dauer, **info}
            elif e.art in ("dienst-gestartet", "dienst-gestoppt"):
                if e.art == "dienst-gestoppt":
                    self.job_lokal = None
                eintrag = {"zeit": e.zeit, "art": e.art}
            else:
                return
            self.ereignisse.append(eintrag)
        self.verteiler.sende("log", {"ereignisse": [eintrag], "zeilen": []})

    # ------------------------------------------------------------ Job-Schritt aus einer Quelle (Design 0.4.0)

    def _passt(self, gh_job: object) -> dict | None:
        """Der Job aus der GitHub-Abfrage, sofern er zum lokal laufenden Job gehört.

        Gleicher Name reicht nicht: Starten zwei Jobs „test“ kurz nacheinander, hält die bis zu 30 s
        alte Abfrage noch den vorigen. Deshalb muss GitHubs Startzeit zum lokalen Start passen.
        """
        if not isinstance(gh_job, dict):
            return None
        if not self.job_lokal and self._beendet:
            # Job gerade beendet: die Abfrage (bis zu 30 s alt) meldet ihn noch als laufend
            name, ende = self._beendet
            gh_start = gh_job.get("start")
            if gh_job.get("name") == name and (not isinstance(gh_start, (int, float)) or gh_start < ende):
                return None
        if self.job_lokal:
            if gh_job.get("name") != self.job_lokal.get("name"):
                return None
            gh_start, lokal_start = gh_job.get("start"), self.job_lokal.get("start")
            if isinstance(gh_start, (int, float)) and isinstance(lokal_start, (int, float)) and gh_start < lokal_start - GH_START_TOLERANZ:
                return None
        return gh_job

    def _gh_job(self) -> dict | None:
        gh = self.bereiche.get("_github")
        return self._passt(gh.get("job") if isinstance(gh, dict) else None)

    def _schritt(self, gh_job: dict | None) -> dict:
        """{nr, von, name} für Status, Log-Chip und Trenner.

        nr = max(lokal, GitHub), nie kleiner als zuvor im selben Job; von = max(Zahl der Schritte, nr)
        oder None, solange GitHub keine Schrittliste geliefert hat; name nur aus GitHub.
        """
        job_name = (self.job_lokal or {}).get("name") or (gh_job or {}).get("name", "")
        if job_name != self._schritt_job:
            self._schritt_hoch, self._schritt_job = 0, job_name
        schritte = [str(s) for s in ((gh_job or {}).get("schritte") or [])]
        try:
            gh_nr = int((gh_job or {}).get("schritt") or 0) if schritte else 0
        except (TypeError, ValueError):
            gh_nr = 0
        nr = max(self.schritt_nr, gh_nr, self._schritt_hoch, 1)
        self._schritt_hoch = nr
        von = max(len(schritte), nr) if schritte else None
        name = schritte[nr - 1] if nr <= len(schritte) else ""
        return {"nr": nr, "von": von, "name": name}

    def bei_seite(self, art: str, wert: object) -> None:
        with self._sperre:
            if art == "schritt":
                self.schritt_nr += 1
                s = self._schritt(self._gh_job())
                zeile = {"zeit": time.time(), "art": "schritt", **s}
                neu = [zeile]
            elif art == "zeilen":
                neu = [{"zeit": zeit, "text": text[:4000]} for zeit, text in list(wert)[-MAX_ZEILEN:]]  # type: ignore[call-overload]
            else:
                zeit, text = wert  # type: ignore[misc]
                neu = [{"zeit": zeit, "text": text[:4000]}]
            if not neu:
                return
            self.zeilen.extend(neu)
        self.verteiler.sende("log", {"ereignisse": [], "zeilen": neu})

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
            passend = self._passt(gh.get("job"))
            if self.job_lokal or (passend and dienst["zustand"] == "aktiv"):
                job = {
                    "name": (self.job_lokal or {}).get("name") or (passend or {}).get("name", ""),
                    "start": (self.job_lokal or {}).get("start") or (passend or {}).get("start"),
                    "repo": "", "workflow": "", "privat": False, "ref": None, "schritte": [],
                }
                if passend:
                    job.update({k: passend.get(k) for k in ("repo", "workflow", "privat", "ref", "schritte", "url")})
                job["schritt"] = self._schritt(passend)
            letzte = list(self.letzte_jobs)
        labels = gh_runner.get("labels") or self.k.weitere.get("RUNNER_LABELS", "self-hosted,linux,x64").split(",")
        return {
            "vm": self.k.vm_name or socket.gethostname(),
            "runner": reg.get("name", ""),
            "eingerichtet": bool(reg),
            "labels": labels,
            "version": runner.runner_version(self.k.runner_verz) if reg else "",
            "monitorVersion": VERSION,
            "system": system.beschreibung(),
            "dienst": {"zustand": dienst["zustand"], "seit": dienst.get("seit"), "grund": dienst.get("grund")},
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
            self.lade_verlauf()
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
            ram = daten["ram"]
            netz = daten.get("netz") or {}
            with self._sperre:
                self._haenge_an(daten["cpu"], round(100.0 * ram["belegt"] / ram["gesamt"], 1) if ram["gesamt"] else 0.0,
                                [netz.get("empfangen", 0), netz.get("gesendet", 0)])
            self._setze("system", daten)
            if takt % VERLAUF_SICHERN == VERLAUF_SICHERN - 1:
                self.sichere_verlauf()
            if takt % 2 == 0:
                self._setze("prozesse", self.messer.prozesse.messen(ram["gesamt"]))
            if takt % 10 == 0:
                self._setze("platten", self.messer.platten())
        self._github_dateien()
        if takt % 2 == 0:
            self._setze("status", self._status())
