"""GitLab-Adapter (#99): Runner-Status und Jobs über die GitLab-REST-API (v4), nur lesend.

Token: persönliches, Projekt- oder Gruppen-Zugriffstoken mit dem Bereich ``read_api`` (nur lesen),
abgelegt in ``/etc/runner-monitor/zugang/<id>.token`` (nur der Sammler als root liest es). Der Server
kommt **nur aus der Konfiguration** (``RunnerKonfig.server``), nie aus dem Fund der Erkennung (E-18);
der Klient folgt keiner Weiterleitung, damit das Token nie an eine andere Adresse geht.

Fragen je Runde (alle ``GET``, Kopfzeile ``PRIVATE-TOKEN``), Stand der GitLab-Dokumentation
(Runners API, Jobs API, Personal access tokens API) – ohne Test gegen einen echten Server geschrieben,
siehe docs/FUNKTIONSWEISE.md › „Anbieter-Adapter“ › GitLab, Abschnitt „Unsicherheiten“:

* ``/personal_access_tokens/self`` (höchstens stündlich) – Bereiche und Ablaufdatum des Tokens; fehlt
  die Route (ältere GitLab-Versionen), wird der Schritt übersprungen,
* ``/runners/:id`` bzw. beim ersten Mal ``/runners`` – Status (``online``, ``offline``, ``stale``,
  ``never_contacted``), Labels (``tag_list``) und Version; der Runner wird über seinen **Namen**
  (``description`` bei GitLab = ``name`` in ``config.toml``) gefunden, nie über das Runner-Token,
* ``/runners/:id/jobs?status=running`` – aktueller Job und „Jobs je Repository“ (laufend),
* ``/runners/:id/jobs?order_by=id&sort=desc`` – die letzten Jobs.

Nicht verfügbar, weil die API es nicht hergibt: **Schritte** (GitLab kennt Jobs in Stages, aber keine
Schrittliste eines laufenden Jobs; das Protokoll eines Jobs ist nur Rohtext) und **wartende** Jobs je
Repository (die Runner-API kennt nur ``running``, ``success``, ``failed``, ``canceled``). Das Live-Log
kommt wie bei der Grundüberwachung aus dem Journal der Unit.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import erkennung, github as gh
from . import Anbieter, RunnerKonfig, registriere
from . import token as zugangsdaten

TAKT = 30                        # Sekunden zwischen zwei Abfragen (Sammler)
TOKEN_PRUEFUNG = 3600            # Bereiche und Ablauf des Tokens höchstens stündlich neu holen
MAX_ANTWORT = 4 * 1024 * 1024    # größere Antworten gelten als Fehler
MAX_RUNNER_SEITEN = 5            # höchstens 500 Runner durchsuchen
LETZTE_JOBS = 5
GUELTIG = ("read_api", "api")    # Token-Bereiche, die lesen dürfen
STATUS_ONLINE = {"online"}
STATUS_OFFLINE = {"offline", "stale", "never_contacted", "not_connected"}
ERGEBNIS = {"success": "erfolg", "failed": "fehler", "canceled": "abgebrochen", "cancelled": "abgebrochen"}


class GitLabFehler(Exception):
    def __init__(self, art: str, text: str = "") -> None:
        super().__init__(text or art)
        self.art = art  # nicht-erreichbar | token-ungueltig | kontingent | keine-rechte | fehler


class _KeineWeiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *argumente, **schluessel):  # noqa: ANN002, ANN003
        return None  # 3xx wird zum HTTPError: das Token geht nie an eine andere Adresse


_OEFFNER = urllib.request.build_opener(_KeineWeiterleitung)


class Klient:
    """GitLab-REST-Klient (nur ``GET``). ``server`` kommt aus der Konfiguration, nie aus einem Fund."""

    def __init__(self, server: str, token: str = "", zeitlimit: float = 15.0) -> None:
        self.server = erkennung.pruefe_url(server) or ""
        self.token = token.strip()
        self.zeitlimit = zeitlimit
        self.zaehler = {"anfragen": 0}
        self.letzter_kopf: dict = {}

    def hole(self, pfad: str, parameter: dict | None = None) -> gh.Antwort:
        if not self.server:
            raise GitLabFehler("fehler", "Server fehlt oder ist keine gültige Adresse")
        url = f"{self.server}/api/v4{pfad}"
        if parameter:
            url += "?" + urllib.parse.urlencode(parameter)
        anfrage = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "runner-monitor",
                                                       "PRIVATE-TOKEN": self.token})
        self.zaehler["anfragen"] += 1
        try:
            with _OEFFNER.open(anfrage, timeout=self.zeitlimit) as antwort:  # noqa: S310 – Adresse aus der Konfiguration
                kopf = {k.lower(): v for k, v in antwort.headers.items()}
                roh = antwort.read(MAX_ANTWORT + 1)
        except urllib.error.HTTPError as fehler:
            kopf = {k.lower(): v for k, v in (fehler.headers or {}).items()}
            self.letzter_kopf = kopf
            code = fehler.code
            if code == 401:
                raise GitLabFehler("token-ungueltig", "Token ungültig, widerrufen oder abgelaufen (401)") from fehler
            if code == 429:
                raise GitLabFehler("kontingent", "API-Kontingent erschöpft (429)") from fehler
            if code in (403, 404):
                # GitLab antwortet 404, wenn die Ressource für dieses Token nicht sichtbar ist.
                raise GitLabFehler("keine-rechte", f"Keine Berechtigung für {pfad} ({code})") from fehler
            if 300 <= code < 400:
                raise GitLabFehler("fehler", f"GitLab leitet weiter ({code}) – Adresse des Servers prüfen") from fehler
            raise GitLabFehler("fehler", f"GitLab antwortet mit {code}") from fehler
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as fehler:
            raise GitLabFehler("nicht-erreichbar", str(getattr(fehler, "reason", None) or fehler)) from fehler
        self.letzter_kopf = kopf
        if len(roh) > MAX_ANTWORT:
            raise GitLabFehler("fehler", "Antwort zu groß")
        try:
            daten = json.loads(roh.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as fehler:
            raise GitLabFehler("fehler", "GitLab antwortet nicht mit JSON (falsche Adresse oder Proxy?)") from fehler
        return gh.Antwort(daten, kopf)

    def kontingent(self) -> dict:
        """``RateLimit-*`` gibt es nur, wenn der Server sie sendet (gitlab.com ja, viele eigene Server nein)."""
        k = self.letzter_kopf
        try:
            return {"frei": int(k["ratelimit-remaining"]), "limit": int(k["ratelimit-limit"]), "reset": int(k.get("ratelimit-reset", "0"))}
        except (KeyError, ValueError):
            return {}


# ---------------------------------------------------------------- Auswertung (testbar ohne Netz)


def ref_aus_job(job: dict) -> dict:
    ref = str(job.get("ref") or "")
    titel = str((job.get("commit") or {}).get("title") or "")
    merge = re.fullmatch(r"refs/merge-requests/(\d+)/(?:head|merge)", ref)
    if merge:
        return {"art": "PR", "name": f"!{merge.group(1)}", "titel": titel}  # GitLab schreibt Merge Requests „!12“
    if job.get("tag"):
        return {"art": "Tag", "name": ref, "titel": titel}
    return {"art": "Branch", "name": ref, "titel": titel}


def projekt_aus(job: dict) -> str:
    """Name des Projekts: ``project.name`` (Runner-API), sonst die Nummer der Pipeline-Projekts."""
    projekt = job.get("project")
    if isinstance(projekt, dict) and projekt.get("name"):
        return str(projekt["name"])
    pid = (job.get("pipeline") or {}).get("project_id")
    return f"Projekt {pid}" if pid else ""


def job_aus(job: dict) -> dict:
    """Aktueller Job im Format des Adapters (Schritte gibt die API nicht her)."""
    pipeline = job.get("pipeline") or {}
    return {
        "repo": projekt_aus(job),
        "privat": False,  # Sichtbarkeit steht nicht in der Antwort
        "workflow": f"Pipeline #{pipeline['id']}" if pipeline.get("id") else "",
        "name": str(job.get("name") or ""),
        "stage": str(job.get("stage") or ""),
        "ref": ref_aus_job(job),
        "schritte": [],
        "schritt": None,
        "start": gh.iso_zu_unix(job.get("started_at")),
        "url": str(job.get("web_url") or ""),
    }


def letzter_job_aus(job: dict) -> dict:
    dauer = job.get("duration")
    return {
        "name": str(job.get("name") or ""),
        "ergebnis": ERGEBNIS.get(str(job.get("status")), "abgebrochen"),
        "dauer": int(dauer) if isinstance(dauer, (int, float)) else None,
        "ende": gh.iso_zu_unix(job.get("finished_at")),
        "repo": projekt_aus(job),
        "workflow": f"Pipeline #{(job.get('pipeline') or {}).get('id')}" if (job.get("pipeline") or {}).get("id") else "",
    }


def zaehle_laufende(jobs: list[dict]) -> list[dict]:
    """Laufende Jobs je Projekt: ``[{name, privat, laeuft, wartet}]`` (wartend ist per API nicht zu erfahren)."""
    je: dict[str, int] = {}
    for job in jobs:
        name = projekt_aus(job)
        if name:
            je[name] = je.get(name, 0) + 1
    return [{"name": n, "privat": False, "laeuft": c, "wartet": 0} for n, c in sorted(je.items())]


def zustand_aus_runner(r: dict) -> str:
    status = str(r.get("status") or "")
    if status in STATUS_ONLINE:
        return "online"
    if status in STATUS_OFFLINE:
        return "offline"
    if "online" in r:  # ältere Versionen kennen nur das Feld online (bool)
        return "online" if r.get("online") else "offline"
    return "unbekannt"


def finde_runner(runner: list[dict], name: str) -> dict | None:
    """Runner über die Beschreibung (= ``name`` in ``config.toml``) finden. Mehrdeutig → ``None``."""
    treffer = [r for r in runner if isinstance(r, dict) and r.get("description") == name]
    return treffer[0] if len(treffer) == 1 else None


def abfrage(klient: Klient, name: str, letzter_erfolg: float | None = None, speicher: dict | None = None) -> dict:
    """Ein Durchlauf: Token prüfen, Runner finden, Status, laufende und letzte Jobs."""
    speicher = speicher if speicher is not None else {}
    jetzt = time.time()
    ergebnis: dict = {
        "org": "", "abfrage": "ok", "abgefragt": jetzt, "letzterErfolg": letzter_erfolg,
        "tokenAblauf": None, "kontingent": {}, "repos": [], "runner": {"zustand": "unbekannt"},
        "job": None, "letzteJobs": [], "fehler": "", "wartetUnbekannt": True,
    }
    if not klient.token:
        ergebnis["abfrage"] = "kein-token"
        return ergebnis
    if not klient.server:
        ergebnis.update(abfrage="fehler", fehler="Server fehlt oder ist keine gültige Adresse")
        return ergebnis
    try:
        _pruefe_token(klient, speicher, jetzt, ergebnis)
        r = _runner(klient, name, speicher)
        if r is None:
            ergebnis["runner"] = {"zustand": "unbekannt", "grund": "Runner mit diesem Namen nicht gefunden oder nicht eindeutig"}
        else:
            ergebnis["runner"] = {"zustand": zustand_aus_runner(r), "beschaeftigt": False,
                                  "labels": [t for t in r.get("tag_list") or [] if isinstance(t, str)],
                                  "version": str(r.get("version") or "") or None, "id": r.get("id")}
            laeuft = klient.hole(f"/runners/{int(r['id'])}/jobs", {"status": "running", "per_page": 100}).daten
            laeuft = [j for j in laeuft if isinstance(j, dict)] if isinstance(laeuft, list) else []
            ergebnis["runner"]["beschaeftigt"] = bool(laeuft)
            ergebnis["repos"] = zaehle_laufende(laeuft)
            ergebnis["job"] = job_aus(laeuft[0]) if laeuft else None
            letzte = klient.hole(f"/runners/{int(r['id'])}/jobs", {"order_by": "id", "sort": "desc", "per_page": 20}).daten
            fertig = [j for j in letzte if isinstance(j, dict) and j.get("status") in ERGEBNIS] if isinstance(letzte, list) else []
            ergebnis["letzteJobs"] = [letzter_job_aus(j) for j in fertig[:LETZTE_JOBS]]
        ergebnis["letzterErfolg"] = jetzt
    except GitLabFehler as fehler:
        ergebnis["abfrage"] = "nicht-erreichbar" if fehler.art in ("nicht-erreichbar", "fehler") else fehler.art
        ergebnis["fehler"] = str(fehler)
        if fehler.art == "token-ungueltig":
            speicher.pop("token_geprueft", None)
    ergebnis["kontingent"] = klient.kontingent()
    ergebnis["anfragen"] = dict(klient.zaehler)
    if ergebnis["abfrage"] == "ok":
        ergebnis["tokenAblauf"] = speicher.get("token_ablauf")
    return ergebnis


def _pruefe_token(klient: Klient, speicher: dict, jetzt: float, ergebnis: dict) -> None:
    """Bereiche und Ablauf des Tokens (``GET /personal_access_tokens/self``, ab GitLab 15.5), höchstens stündlich.

    Fehlt der Bereich ``read_api``, ist das Token zwar gültig, der Monitor aber ohne Rechte. Antwortet der
    Server mit 403/404 (ältere Version, Token-Art ohne diese Route), wird der Schritt übersprungen."""
    if jetzt - speicher.get("token_geprueft", 0) < TOKEN_PRUEFUNG:
        return
    try:
        daten = klient.hole("/personal_access_tokens/self").daten
    except GitLabFehler as fehler:
        if fehler.art != "keine-rechte":
            raise
        speicher["token_geprueft"] = jetzt
        speicher["token_ablauf"] = None
        return
    speicher["token_geprueft"] = jetzt
    if not isinstance(daten, dict):
        return
    bereiche = daten.get("scopes")
    if isinstance(bereiche, list) and bereiche and not any(b in GUELTIG for b in bereiche):
        speicher.pop("token_geprueft", None)
        raise GitLabFehler("keine-rechte", "Token ohne Bereich read_api")
    ablauf = daten.get("expires_at")
    try:
        speicher["token_ablauf"] = time.mktime(time.strptime(str(ablauf), "%Y-%m-%d")) + 86399 if ablauf else None
    except ValueError:
        speicher["token_ablauf"] = None


def _runner(klient: Klient, name: str, speicher: dict) -> dict | None:
    """Den Runner des Monitors finden. Die gefundene Nummer wird gemerkt und danach direkt abgefragt."""
    rid = speicher.get("runner_id")
    if isinstance(rid, int):
        try:
            r = klient.hole(f"/runners/{rid}").daten
            if isinstance(r, dict) and r.get("description") == name and r.get("id") == rid:
                return r
        except GitLabFehler as fehler:
            if fehler.art != "keine-rechte":
                raise
        speicher.pop("runner_id", None)  # gelöscht, umbenannt oder Rechte entzogen: neu suchen
    alle: list[dict] = []
    seite = 1
    while seite <= MAX_RUNNER_SEITEN:
        daten = klient.hole("/runners", {"per_page": 100, "page": seite}).daten
        daten = daten if isinstance(daten, list) else []
        alle.extend(d for d in daten if isinstance(d, dict))
        if len(daten) < 100:
            break
        seite += 1
    treffer = finde_runner(alle, name)
    if treffer is None or not isinstance(treffer.get("id"), int):
        return None
    speicher["runner_id"] = treffer["id"]
    try:  # Einzelheiten (Labels, Version) sind freiwillig
        einzel = klient.hole(f"/runners/{treffer['id']}").daten
        if isinstance(einzel, dict):
            return {**treffer, **einzel}
    except GitLabFehler as fehler:
        if fehler.art != "keine-rechte":
            raise
    return treffer


def workflows_aus(ergebnis: dict | None) -> dict:
    """Karte „Jobs je Repository“ im selben Format wie bei GitHub; ``wartetUnbekannt`` kennzeichnet,
    dass wartende Jobs nicht abgefragt werden können."""
    erg = ergebnis or {}
    abgefragt = erg.get("abgefragt") or 0
    return {
        "org": "",
        "abfrage": erg.get("abfrage", "kein-token"),
        "abgefragt": erg.get("letzterErfolg") or abgefragt,
        "versucht": abgefragt,
        "naechste": abgefragt + TAKT if abgefragt else None,
        "tokenAblauf": erg.get("tokenAblauf"),
        "kontingent": erg.get("kontingent") or {},
        "repos": erg.get("repos") or [],
        "fehler": erg.get("fehler", ""),
        "runnerGrund": (erg.get("runner") or {}).get("grund", ""),
        "wartetUnbekannt": True,
    }


# ---------------------------------------------------------------- Adapter


@registriere
class GitLab(Anbieter):
    dienst = "gitlab"
    # Schritte: GitLab liefert keine Schrittliste (nur Jobs in Stages) – nicht als verfügbar zeigen.
    FAEHIG = {"status": True, "jobs": True, "schritte": False, "logs": True, "updates": False}

    # ------------------------------------------------------------ Sammler (root)

    def token(self) -> str:
        return zugangsdaten.lies(self.k.token_datei)

    def abfrage(self, speicher: dict, letzter_erfolg: float | None = None, token: str | None = None) -> dict:
        tok = self.token() if token is None else token
        return abfrage(Klient(self.k.server or "", tok), self.k.name, letzter_erfolg, speicher)

    # ------------------------------------------------------------ Monitor

    def beim_dienst(self, ergebnis: dict | None) -> dict | None:
        erg = ergebnis or {}
        zustand = (erg.get("runner") or {}).get("zustand", "unbekannt") if erg.get("abfrage") == "ok" else "unbekannt"
        return {"zustand": zustand, "seit": None}

    def jobs_je_repository(self, ergebnis: dict | None) -> dict | None:
        return workflows_aus(ergebnis)

    def api_job(self, ergebnis: dict | None) -> dict | None:
        job = (ergebnis or {}).get("job")
        return job if isinstance(job, dict) else None

    def letzte_jobs(self, ergebnis: dict | None) -> list[dict]:
        liste = (ergebnis or {}).get("letzteJobs")
        return [j for j in liste if isinstance(j, dict)] if isinstance(liste, list) else []


def konfig_fuer(name: str, rid: str, unit: str | None, server: str | None, zugang_verz, log: str | None = None) -> RunnerKonfig:
    """Konfiguration eines GitLab-Runners – Server und Log-Pfad nur aus ``runner.json`` bzw. der
    Einrichtung, nie aus einem Fund (E-18)."""
    return RunnerKonfig(id=rid, name=name, dienst="gitlab", unit=erkennung.pruefe_unit(unit), log=log,
                        server=erkennung.pruefe_url(server),
                        token_datei=zugangsdaten.token_pfad(zugang_verz, rid) if zugangsdaten.pruefe_id(rid) else None)
