"""Anbieter-Adapter (Design 0.8.0, #92): eine Schnittstelle für Status, Jobs, Schritte und Logs.

Die Oberfläche richtet sich nach den **Fähigkeiten** eines Runners, nicht nach dem Namen des
Dienstes (README › „Nicht verfügbar“ ehrlich zeigen). Jeder Dienst hat einen Adapter:

* ``github``     – :class:`runner_monitor.anbieter.github.GitHub` (voll: Status, Jobs, Schritte, Logs)
* alle anderen   – :class:`Grundueberwachung` (nur Dienst und Journal), bis ihr Adapter kommt
  (Forgejo/Gitea #93, GitLab #99)

Schnittstelle (je Runner eine Instanz, gebaut aus :class:`RunnerKonfig`):

* ``faehig()``                 – ``{status, jobs, schritte, logs, updates}`` (bool)
* ``abfrage(speicher, …)``     – nur im Sammler (root): Abfrage beim Dienst mit dem Token,
  Ergebnis ohne Geheimnisse (wird 0644 nach ``/run/runner-monitor`` geschrieben); Basis: ``None``
* ``dienst_status()``          – systemd-Zustand der Unit (Monitor, ohne root)
* ``beim_dienst(ergebnis)``    – Runner beim Dienst online/offline (aus der Abfrage)
* ``jobs_je_repository(erg.)`` – Karte „Jobs je Repository“ (aus der Abfrage) oder ``None``
* ``api_job(ergebnis)``        – aktueller Job laut Dienst (mit Schrittliste) oder ``None``
* ``log_quelle()``             – woher das Live-Log kommt (Seiten, Journal, Datei) oder ``None``
* ``eintrag(…)``               – ein Eintrag in ``runner[]`` von ``/api/zustand``

Sicherheit (E-18, S-ADAPTER-01): Server, Organisation, Log-Pfad und Token-Datei kommen **nur** aus
der Konfiguration (``konfig.env``, ``einstellungen.json``, ``/etc/runner-monitor/runner.json``,
``/etc/runner-monitor/zugang/<runner>.token``), nie aus einem Fund der Erkennung. Vom Fund werden nur
ID, Anzeigename, Unit (aus den root-eigenen systemd-Verzeichnissen), Version, Einstufung und Stand
übernommen – zum Anzeigen, nie als Ziel einer Anfrage.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from .. import erkennung, runner

FAEHIGKEITEN = ("status", "jobs", "schritte", "logs", "updates")
DIENSTE = erkennung.DIENSTE

# Zustand eines Runners für Reiter und Karte (Design 0.8.0 › Bildschirme 1 und 2):
# job · bereit · offline · gestoppt · fehlt (kein Dienst) · aktiv (Grundüberwachung: Dienst läuft) · unbekannt
ZUSTAENDE = ("job", "bereit", "offline", "gestoppt", "fehlt", "aktiv", "unbekannt")


@dataclass(frozen=True)
class RunnerKonfig:
    """Was ein Adapter über seinen Runner wissen darf – nur aus der Konfiguration (E-18)."""

    id: str
    name: str
    dienst: str = "unbekannt"
    unit: str | None = None                # systemd-Unit (geprüfter Name)
    log: str | None = None                 # Log-Datei nur aus runner.json; None = Journal der Unit
    server: str | None = None              # Adresse des Dienstes aus der Konfiguration
    org: str = ""                          # Organisation aus konfig.env bzw. einstellungen.json
    token_datei: Path | None = None        # /etc/runner-monitor/zugang/<id>.token
    token_rueckfall: Path | None = None    # alter Ort (/etc/runner-monitor/github-token) bis #94/#96
    runner_verz: Path | None = None        # GitHub: Verzeichnis des Runners (MONITOR_RUNNER_VERZ)


class Anbieter:
    """Basisklasse und Grundüberwachung: Dienst (systemd) und Journal, ohne Anbindung an den Dienst."""

    dienst: ClassVar[str] = "unbekannt"
    FAEHIG: ClassVar[dict[str, bool]] = {"status": True, "jobs": False, "schritte": False, "logs": True, "updates": False}

    def __init__(self, konfig: RunnerKonfig) -> None:
        self.k = konfig

    # ------------------------------------------------------------ Fähigkeiten

    def faehig(self) -> dict[str, bool]:
        """Was dieser Runner wirklich liefert. Ohne Unit gibt es weder Dienststatus noch Journal."""
        f = dict(self.FAEHIG)
        if not self.k.unit:
            f["status"] = f["logs"] = False
        return f

    # ------------------------------------------------------------ Sammler (root)

    def abfrage(self, speicher: dict, letzter_erfolg: float | None = None) -> dict | None:  # noqa: ARG002
        """Abfrage beim Dienst (nur im Sammler). Grundüberwachung: keine."""
        return None

    # ------------------------------------------------------------ Monitor (ohne root)

    def dienst_status(self) -> dict:
        unit = erkennung.pruefe_unit(self.k.unit)
        if not unit:
            return {"zustand": "fehlt", "seit": None, "grund": None}
        d = runner.dienst_status(unit)
        return {"zustand": d["zustand"], "seit": d.get("seit"), "grund": d.get("grund")}

    def beim_dienst(self, ergebnis: dict | None) -> dict | None:  # noqa: ARG002
        """Runner beim Dienst online/offline – ohne Anbindung nicht verfügbar."""
        return None

    def jobs_je_repository(self, ergebnis: dict | None) -> dict | None:  # noqa: ARG002
        return None

    def api_job(self, ergebnis: dict | None) -> dict | None:  # noqa: ARG002
        return None

    def log_quelle(self) -> dict | None:
        """``{"art": "datei", "pfad"}`` (nur aus runner.json), ``{"art": "journal", "unit"}`` oder None."""
        if self.k.log:
            return {"art": "datei", "pfad": self.k.log}
        if self.k.unit:
            return {"art": "journal", "unit": self.k.unit}
        return None

    # ------------------------------------------------------------ runner[] in /api/zustand

    @staticmethod
    def zustand_aus(dienst: dict, job: object, online: dict | None, faehig: dict) -> str:
        if not faehig.get("status"):
            return "unbekannt"
        if dienst.get("zustand") == "fehlt":
            return "fehlt"
        if dienst.get("zustand") == "gestoppt":
            return "gestoppt"
        if not faehig.get("jobs"):
            return "aktiv"  # Grundüberwachung: „Dienst aktiv“
        if job:
            return "job"
        if online and online.get("zustand") == "offline":
            return "offline"
        return "bereit"

    def eintrag(self, *, dienst: dict | None = None, job: dict | None = None, letzte_jobs: list | None = None,
                ergebnis: dict | None = None, online: dict | None = None, fund: dict | None = None,
                stand: str | None = None, labels: list | None = None, version: str | None = None) -> dict:
        """Ein Eintrag in ``runner[]`` (Format: docs/FUNKTIONSWEISE.md › „Anbieter-Adapter“, E-19)."""
        faehig = self.faehig()
        fund = fund or {}
        dienst = dienst if dienst is not None else (self.dienst_status() if faehig["status"] else
                                                    {"zustand": "fehlt", "seit": None, "grund": None})
        online = online if online is not None else self.beim_dienst(ergebnis)
        if not faehig["jobs"]:
            job, letzte_jobs = None, None
        elif job and not faehig["schritte"]:
            job = {**job, "schritt": None, "schritte": []}  # „Schritte nicht verfügbar“
        return {
            "id": self.k.id,
            "name": self.k.name,
            "dienst": self.k.dienst,
            "server": self.k.server,
            "org": self.k.org or None,
            "unit": self.k.unit,
            "stand": stand or fund.get("stand") or "offen",
            "einstufung": fund.get("einstufung") or erkennung.EINSTUFUNG.get(self.k.dienst, "unbekannt"),
            "version": version if version is not None else fund.get("version"),
            "labels": labels or [],
            "faehig": faehig,
            "status": {"zustand": self.zustand_aus(dienst, job, online, faehig), "dienst": dienst, "beimDienst": online},
            "job": job,
            "letzteJobs": letzte_jobs,
            "jobsJeRepository": self.jobs_je_repository(ergebnis) if faehig["jobs"] else None,
            "log": self.log_oeffentlich() if faehig["logs"] else None,
        }

    def log_oeffentlich(self) -> dict | None:
        """Log-Quelle für ``/api/zustand``: nur Art und Unit, keine Pfade der VM (Review #111)."""
        quelle = self.log_quelle()
        if not quelle:
            return None
        return {"art": quelle["art"], "unit": quelle.get("unit") or self.k.unit or None}


class Grundueberwachung(Anbieter):
    """Für Dienste ohne eigenen Adapter (Forgejo, Gitea, GitLab bis #93/#99, unbekannte Runner)."""

    dienst = "unbekannt"


# ---------------------------------------------------------------- Registry

_REGISTRY: dict[str, type[Anbieter]] = {}


def registriere(klasse: type[Anbieter]) -> type[Anbieter]:
    """Adapter eintragen (als Dekorator). Ein Dienst hat genau einen Adapter."""
    if klasse.dienst not in DIENSTE:
        raise ValueError(f"unbekannter Dienst: {klasse.dienst!r}")
    if set(klasse.FAEHIG) != set(FAEHIGKEITEN):
        raise ValueError(f"Fähigkeiten von {klasse.__name__} unvollständig")
    _REGISTRY[klasse.dienst] = klasse
    return klasse


def klasse_fuer(dienst: str) -> type[Anbieter]:
    """Adapter für einen Dienst; ohne eigenen Adapter die Grundüberwachung."""
    return _REGISTRY.get(dienst, Grundueberwachung)


def adapter(konfig: RunnerKonfig) -> Anbieter:
    return klasse_fuer(konfig.dienst)(konfig)


def faehigkeiten_tabelle() -> dict[str, dict[str, bool]]:
    """Fähigkeiten je Dienst in dieser Version – muss zu ``erkennung.FAEHIG`` passen (Test)."""
    return {d: dict(klasse_fuer(d).FAEHIG) for d in DIENSTE}


registriere(Grundueberwachung)

from . import github as _github  # noqa: E402,F401 – registriert den GitHub-Adapter
