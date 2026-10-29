"""Forgejo- und Gitea-Adapter (#93): Runner-Status beim Dienst, Jobs je Repository, aktueller Job mit
Schritten, letzte Jobs. Nur lesend.

Ergebnis der API-Prüfung (docs/FUNKTIONSWEISE.md › „Fähigkeiten je Anbieter“): Forgejo und Gitea
liefern dieselben Pfade unter ``/api/v1``, aber verschieden geformte Antworten. Der Adapter richtet
sich deshalb nach der **Form der Antwort**, nicht nach dem Namen des Dienstes (die Erkennung kann
Forgejo und Gitea nur unterscheiden, wenn der Server ohne Anmeldung antwortet):

* Runner: Forgejo ``[{name, uuid, status: offline|idle|active, labels: ["…"]}]``,
  Gitea ``{runners: [{name, status: online|offline, busy, labels: [{name}]}]}``.
* Läufe: ``/repos/{o}/{r}/actions/runs`` – Forgejo ``status: running|waiting|blocked|success|…``,
  Gitea wie GitHub (``in_progress``, ``queued`` …).
* Jobs eines Laufs: Forgejo eine Liste ohne Runner und ohne Schritte – welcher Runner den Job hat,
  steht nur in der ersten Zeile seines Logs („Runner <uuid> (version:…) received task …“, Forgejo
  Runner; act_runner schreibt dort den Namen). Die Schritte kommen aus ``/actions/jobs/{id}``
  (Forgejo ab 17). Gitea liefert ``{jobs: [{runner_name, steps, started_at}]}`` wie GitHub.

Sicherheit (E-18, E-21, S-FORGEJO-01): Server und Organisation kommen **nur** aus ``runner.json``,
das Token nur aus ``/etc/runner-monitor/zugang/<id>.token`` (gelesen vom Sammler als root). Das Token
geht nur an ``https://``; ``http://`` nur mit ``"http_erlaubt": true`` in ``runner.json`` und dann ohne
Proxy aus der Umgebung (wie GitLab). Der Klient folgt keiner Weiterleitung (das Token geht nie an eine andere Adresse), begrenzt jede Antwort
(4 MB, Log-Anfang 4 KB) und jede Runde (25 s). Namen aus Antworten werden geprüft und als
Pfadteil kodiert, IDs müssen Zahlen sein. Das Ergebnis enthält keine Geheimnisse und keine URL mit
Zugangsdaten (es wird 0644 nach ``/run/runner-monitor/anbieter.json`` geschrieben).
"""

from __future__ import annotations

import http.client
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .. import erkennung
from .. import github as gh
from . import Anbieter, RunnerKonfig, registriere
from . import github as gh_adapter

TAKT = 30                     # Sekunden zwischen zwei Abfragen (Sammler), wie bei GitHub
ZEITLIMIT = 10.0              # je Anfrage (Verbindung und jedes Lesen)
FRIST = 25.0                  # eine ganze Runde; danach bricht sie ab („nicht erreichbar“)
MAX_ANTWORT = 4 * 1024 * 1024
MAX_LOGKOPF = 4096            # vom Job-Log nur der Anfang (wer hat den Job?)
SEITE = 50                    # Forgejo und Gitea liefern höchstens 50 Einträge je Seite (Vorgabe)
MAX_SEITEN = 20               # höchstens 1000 Repositories bzw. Runner
MAX_LETZTE = 5
LAEUFT = {"running", "in_progress"}
WARTET = {"waiting", "queued", "pending", "requested", "blocked"}
ERLEDIGT = {"success", "failure", "cancelled", "canceled", "skipped", "completed"}
ERGEBNIS = {"success": "erfolg", "failure": "fehler", "cancelled": "abgebrochen", "canceled": "abgebrochen",
            "skipped": "abgebrochen"}
REPO = re.compile(r"[A-Za-z0-9_.-]{1,100}")
# Erste Zeile eines Job-Logs (Zeitstempel davor optional):
#   Forgejo Runner: „Runner 0000…-0002 (version:v13.2.0) received task 83 of job build, triggered by …“
#   act_runner:     „runner-vm-03(version:v0.2.11) received task 12 of job build, be triggered by …“
LOG_KOPF = re.compile(r"^(?:\S+Z\s+)?(?:Runner\s+)?(?P<wer>[^\s(]{1,128})\s*\(version:[^)]{0,64}\)\s+received task (?P<task>\d+)")


class ForgejoFehler(Exception):
    def __init__(self, art: str, text: str = "") -> None:
        super().__init__(text or art)
        self.art = art  # nicht-erreichbar | token-ungueltig | keine-rechte | fehlt | kontingent | fehler


@dataclass
class Antwort:
    daten: object
    kopf: dict = field(default_factory=dict)


class _OhneWeiterleitung(urllib.request.HTTPRedirectHandler):
    """Keiner Weiterleitung folgen: urllib würde den Authorization-Kopf sonst mitnehmen – auch zu
    einer anderen Adresse. Eine 3xx-Antwort wird so zum HTTPError."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102, PLR0913
        return None


def q(teil: object) -> str:
    """Ein Pfadteil (Organisation, Repository), vollständig kodiert – nie ein ``/`` oder ``..``."""
    return urllib.parse.quote(str(teil), safe="")


class Klient:
    """REST-Klient für ``<server>/api/v1`` (nur GET). ``server`` kommt aus runner.json (E-18)."""

    def __init__(self, server: str, token: str = "", zeitlimit: float = ZEITLIMIT, frist: float = FRIST,
                 oeffner: urllib.request.OpenerDirector | None = None, http_erlaubt: bool = False) -> None:
        adresse = erkennung.pruefe_url(server) or ""
        if adresse.startswith("http://") and http_erlaubt is not True:
            adresse = ""  # E-21: Token nur über https, außer runner.json erlaubt http ausdrücklich
        self.server = adresse
        self.token = (token or "").strip()
        self.zeitlimit = zeitlimit
        self.zaehler = {"anfragen": 0}
        self._ende = time.monotonic() + frist
        if oeffner is None:
            # bei http:// ohne Proxy aus der Umgebung: das Token ginge sonst unverschlüsselt über ihn (E-21)
            oeffner = (urllib.request.build_opener(_OhneWeiterleitung, urllib.request.ProxyHandler({}))
                       if adresse.startswith("http://") else urllib.request.build_opener(_OhneWeiterleitung))
        self._oeffner = oeffner

    def hole(self, pfad: str, parameter: dict | None = None, *, text: bool = False) -> Antwort:
        if not self.server:
            raise ForgejoFehler("fehler", "Server fehlt, ist keine gültige Adresse oder nicht https:// (http:// nur mit „http_erlaubt“ in runner.json)")
        if time.monotonic() > self._ende:
            raise ForgejoFehler("nicht-erreichbar", "Frist für die Abfrage überschritten")
        url = f"{self.server}/api/v1{pfad}"
        if parameter:
            url += "?" + urllib.parse.urlencode(parameter)
        anfrage = urllib.request.Request(url, headers={"Accept": "text/plain" if text else "application/json",
                                                       "User-Agent": "runner-monitor"})
        if self.token:
            anfrage.add_header("Authorization", f"token {self.token}")
        if text:
            anfrage.add_header("Range", f"bytes=0-{MAX_LOGKOPF - 1}")
        grenze = MAX_LOGKOPF if text else MAX_ANTWORT
        self.zaehler["anfragen"] += 1
        try:
            with self._oeffner.open(anfrage, timeout=self.zeitlimit) as antwort:
                kopf = {k.lower(): v for k, v in antwort.headers.items()}
                roh = antwort.read(grenze + 1)
        except urllib.error.HTTPError as fehler:
            code = fehler.code
            fehler.close()
            if code == 401:
                raise ForgejoFehler("token-ungueltig", "Token ungültig oder abgelaufen (401)") from None
            if code == 403:
                raise ForgejoFehler("keine-rechte", f"Keine Berechtigung für {pfad} (403)") from None
            if code == 404:
                raise ForgejoFehler("fehlt", f"{pfad} nicht gefunden (404)") from None
            if code == 429:
                raise ForgejoFehler("kontingent", "Zu viele Anfragen (429)") from None
            if 300 <= code < 400:
                raise ForgejoFehler("fehler", f"Weiterleitung ({code}) – Adresse in runner.json prüfen") from None
            if code >= 500:  # Dienst startet neu, Proxy ohne Ziel: vorübergehend
                raise ForgejoFehler("nicht-erreichbar", f"Server antwortet mit {code}") from None
            raise ForgejoFehler("fehler", f"Server antwortet mit {code}") from None
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException, ValueError) as fehler:
            grund = getattr(fehler, "reason", None) or type(fehler).__name__
            raise ForgejoFehler("nicht-erreichbar", f"Server nicht erreichbar ({grund})") from None
        if text:
            return Antwort(roh[:grenze].decode("utf-8", "replace"), kopf)
        if len(roh) > grenze:
            raise ForgejoFehler("fehler", f"Antwort auf {pfad} zu groß")
        try:
            return Antwort(json.loads(roh.decode("utf-8")), kopf)
        except (UnicodeDecodeError, ValueError):
            raise ForgejoFehler("fehler", f"Keine gültige JSON-Antwort auf {pfad}") from None


# ---------------------------------------------------------------- Auswertung (testbar ohne Netz)


def art_aus_version(version: object) -> str | None:
    """``17.0.1+gitea-1.22.0`` → forgejo (Forgejo nennt die Gitea-Basis), ``1.24.0`` → gitea."""
    if not isinstance(version, str) or not erkennung.pruefe_version(version.split("+")[0]):
        return None
    return "forgejo" if "+gitea-" in version or "forgejo" in version.lower() else "gitea"


def liste_aus(daten: object, schluessel: str) -> list[dict]:
    """Forgejo antwortet mit einer Liste, Gitea mit ``{schluessel: [...]}``."""
    if isinstance(daten, dict):
        daten = daten.get(schluessel)
    return [e for e in daten if isinstance(e, dict)] if isinstance(daten, list) else []


def ganzzahl(wert: object) -> int | None:
    return wert if isinstance(wert, int) and not isinstance(wert, bool) and 0 < wert < 2**53 else None


def runner_eintrag(r: dict) -> dict:
    """Runner der Liste → ``{zustand: online|offline, beschaeftigt, labels}`` (beide Formen)."""
    status = str(r.get("status") or "").lower()
    labels = [lab.get("name") if isinstance(lab, dict) else lab for lab in r.get("labels") or []]
    return {
        "zustand": "offline" if status == "offline" or not status else "online",
        "beschaeftigt": bool(r.get("busy")) or status == "active",
        "labels": [str(lab)[:64] for lab in labels if isinstance(lab, str) and lab][:20],
    }


def zaehle(laeufe: list[dict]) -> tuple[int, int]:
    laeuft = sum(1 for lauf in laeufe if lauf.get("status") in LAEUFT)
    wartet = sum(1 for lauf in laeufe if lauf.get("status") in WARTET)
    return laeuft, wartet


def workflow_aus(lauf: dict) -> str:
    """Name des Workflows: Forgejo ``workflow_id`` („ci.yml“), Gitea ``path`` („.gitea/workflows/ci.yml@…“)."""
    datei = str(lauf.get("workflow_id") or lauf.get("path") or lauf.get("name") or "")
    datei = datei.split("@")[0].rsplit("/", 1)[-1]
    return re.sub(r"\.ya?ml$", "", datei)[:100]


def ref_aus(lauf: dict) -> dict:
    """Branch, Tag oder PR – Gitea wie GitHub, Forgejo aus ``prettyref`` und ``trigger_event``."""
    if "prettyref" not in lauf:
        return gh_adapter.ref_aus_lauf(lauf)
    ereignis = str(lauf.get("trigger_event") or lauf.get("event") or "")
    ref = str(lauf.get("prettyref") or "")
    nachgebaut = {"event": ereignis, "head_branch": ref, "display_title": lauf.get("title") or ""}
    pr = re.fullmatch(r"#?(\d{1,9})", ref)
    if ereignis.startswith("pull_request") and pr:
        nachgebaut.update(event="pull_request", pull_requests=[{"number": int(pr.group(1))}])
    return gh_adapter.ref_aus_lauf(nachgebaut)


def schritt_aus(schritte: list[dict]) -> tuple[list[str], dict | None]:
    """Namen und ``{nr, von, name}``: der laufende Schritt, sonst der nach dem letzten erledigten."""
    namen = [str(s.get("name") or "")[:200] for s in schritte]
    if not namen:
        return [], None
    nr = 0
    for i, s in enumerate(schritte):
        status = s.get("status")
        if status in LAEUFT:
            nr = i + 1
            break
        if status in ERLEDIGT or s.get("conclusion"):
            nr = i + 2
    nr = max(1, min(nr, len(namen)))
    return namen, {"nr": nr, "von": len(namen), "name": namen[nr - 1]}


def wer_aus_log(kopf: str) -> str | None:
    """UUID (Forgejo Runner) bzw. Name (act_runner) aus der ersten Zeile des Job-Logs."""
    treffer = LOG_KOPF.match((kopf or "").lstrip("﻿"))
    return treffer.group("wer") if treffer else None


def runner_beim_dienst(klient: Klient, org: str, besitzer: str, name: str) -> tuple[dict, dict | None]:
    """Online-Status (optional, braucht Besitzerrechte an der Organisation). ``(Ergebnis, Rohdaten)``."""
    pfad = f"/orgs/{q(org)}/actions/runners" if besitzer == "org" else "/user/actions/runners"
    gefunden: dict | None = None
    try:
        for seite in range(1, MAX_SEITEN + 1):
            daten = klient.hole(pfad, {"visible": "true", "page": seite, "limit": SEITE}).daten
            liste = liste_aus(daten, "runners")
            gefunden = next((r for r in liste if not name or r.get("name") == name), None)
            if gefunden or len(liste) < SEITE:
                break
    except ForgejoFehler as fehler:
        if fehler.art not in ("keine-rechte", "fehlt"):
            raise
        return {"zustand": "unbekannt", "grund": "Runner-Liste nicht lesbar (Besitzerrechte an der Organisation nötig)"}, None
    if not gefunden:
        return {"zustand": "unbekannt", "grund": "Runner nicht in der Liste der Organisation"}, None
    return runner_eintrag(gefunden), gefunden


def job_details(klient: Klient, org: str, repo: str, job: dict) -> tuple[list[dict] | None, dict]:
    """Schritte eines Jobs: Gitea liefert sie in der Liste, Forgejo (ab 17) über ``/actions/jobs/{id}``.
    ``None`` = der Server liefert keine Schritte (ältere Forgejo-Versionen)."""
    if isinstance(job.get("steps"), list):
        return [s for s in job["steps"] if isinstance(s, dict)], job
    jid = ganzzahl(job.get("id"))
    if jid is None:
        return None, job
    try:
        daten = klient.hole(f"/repos/{q(org)}/{q(repo)}/actions/jobs/{jid}").daten
    except ForgejoFehler as fehler:
        if fehler.art == "fehlt":
            return None, job
        raise
    if not isinstance(daten, dict) or not isinstance(daten.get("steps"), list):
        return None, job
    return [s for s in daten["steps"] if isinstance(s, dict)], {**job, **daten}


def job_fuer(lauf: dict, repo: dict, job: dict, schritte: list[dict] | None) -> dict:
    namen, schritt = schritt_aus(schritte or [])
    start = gh.iso_zu_unix(job.get("started_at")) or next(
        (gh.iso_zu_unix(s.get("started") or s.get("started_at")) for s in (schritte or []) if s.get("started") or s.get("started_at")),
        None) or gh.iso_zu_unix(lauf.get("started") or lauf.get("run_started_at") or lauf.get("created_at"))
    return {
        "repo": repo["name"], "privat": repo["privat"], "workflow": workflow_aus(lauf),
        "name": str(job.get("name") or "")[:200], "ref": ref_aus(lauf), "schritte": namen, "schritt": schritt,
        "start": start, "url": str(job.get("html_url") or "")[:500],
        "_id": ganzzahl(job.get("id")), "_lauf": ganzzahl(lauf.get("id")),
    }


def ende_aus(job: dict, schritte: list[dict] | None) -> tuple[str | None, float | None]:
    """Ergebnis und Ende eines beendeten Jobs (Forgejo: ``status``, Gitea: ``conclusion``)."""
    status = str(job.get("conclusion") or job.get("status") or "")
    if status in LAEUFT or status in WARTET:
        return None, None
    ende = gh.iso_zu_unix(job.get("completed_at"))
    for s in reversed(schritte or []):
        if ende:
            break
        ende = gh.iso_zu_unix(s.get("stopped") or s.get("completed_at"))
    return ERGEBNIS.get(status, "abgebrochen"), ende


def _repos(klient: Klient, org: str, besitzer: str) -> list[dict]:
    pfad = f"/orgs/{q(org)}/repos" if besitzer == "org" else f"/users/{q(org)}/repos"
    repos: list[dict] = []
    for seite in range(1, MAX_SEITEN + 1):
        daten = klient.hole(pfad, {"page": seite, "limit": SEITE}).daten
        liste = daten if isinstance(daten, list) else []
        for r in liste:
            name = r.get("name") if isinstance(r, dict) else None
            if not isinstance(name, str) or not REPO.fullmatch(name) or name in (".", ".."):
                continue
            if r.get("archived") or r.get("has_actions") is False:
                continue
            repos.append({"name": name, "privat": bool(r.get("private")), "geaendert": gh.iso_zu_unix(r.get("updated_at")) or 0})
        if len(liste) < SEITE:
            break
    return repos


def _besitzer(klient: Klient, org: str, speicher: dict) -> str:
    """Organisation oder Benutzer (einmal je Token gemerkt)."""
    if speicher.get("besitzer") in ("org", "user"):
        return speicher["besitzer"]
    try:
        klient.hole(f"/orgs/{q(org)}")
        besitzer = "org"
    except ForgejoFehler as fehler:
        if fehler.art != "fehlt":
            raise
        try:
            klient.hole(f"/users/{q(org)}")
        except ForgejoFehler as fehler2:
            if fehler2.art == "fehlt":
                raise ForgejoFehler("keine-rechte", f"Organisation oder Benutzer „{org}“ nicht gefunden") from None
            raise
        besitzer = "user"
    speicher["besitzer"] = besitzer
    return besitzer


def abfrage(klient: Klient, org: str, runner_name: str, speicher: dict, letzter_erfolg: float | None = None) -> dict:
    """Eine Runde: Version, Runner beim Dienst, Läufe je Repository, aktueller Job, letzte Jobs."""
    jetzt = time.time()
    ergebnis: dict = {
        "org": org, "abfrage": "ok", "abgefragt": jetzt, "letzterErfolg": letzter_erfolg, "tokenAblauf": None,
        "kontingent": {}, "art": None, "serverVersion": None, "repos": [], "runner": {"zustand": "unbekannt"},
        "job": None, "letzteJobs": list(speicher.get("letzte") or []), "schritte": speicher.get("schritte"), "fehler": "",
    }
    if not klient.token:
        ergebnis["abfrage"] = "kein-token"
        return ergebnis
    if not klient.server:
        ergebnis.update(abfrage="fehler", fehler="Server fehlt, ist keine gültige Adresse oder nicht https:// (http:// nur mit „http_erlaubt“ in runner.json)")
        return ergebnis
    if not org:
        ergebnis.update(abfrage="fehler", fehler="Organisation fehlt in runner.json")
        return ergebnis
    try:
        try:
            version = klient.hole("/version").daten
        except ForgejoFehler as fehler:
            if fehler.art != "fehlt":
                raise
            raise ForgejoFehler("fehler", "Server antwortet nicht wie Forgejo oder Gitea (/api/v1/version fehlt)") from None
        roh = version.get("version") if isinstance(version, dict) else None
        ergebnis["art"] = art_aus_version(roh)
        ergebnis["serverVersion"] = erkennung.pruefe_version(roh.split("+")[0]) if isinstance(roh, str) else None
        besitzer = _besitzer(klient, org, speicher)
        ergebnis["runner"], mein = runner_beim_dienst(klient, org, besitzer, runner_name)
        ich = {w for w in ((mein or {}).get("uuid"), runner_name) if isinstance(w, str) and w}

        repos = _repos(klient, org, besitzer)
        ruhige = speicher.setdefault("ruhig", {})
        laufend: list[tuple[dict, dict]] = []
        for repo in repos:
            alt = ruhige.get(repo["name"])
            if (alt and not alt["laeuft"] and not alt["wartet"] and jetzt - repo["geaendert"] > gh_adapter.RUHIG_AB
                    and jetzt - alt["zeit"] < gh_adapter.RUHIG_TAKT):
                ergebnis["repos"].append({"name": repo["name"], "privat": repo["privat"], "laeuft": 0, "wartet": 0})
                continue
            try:
                daten = klient.hole(f"/repos/{q(org)}/{q(repo['name'])}/actions/runs", {"limit": 30}).daten
            except ForgejoFehler as fehler:
                if fehler.art != "fehlt":  # Actions im Repository aus: 404
                    raise
                daten = {}
            laeufe = liste_aus(daten, "workflow_runs")
            laeuft, wartet = zaehle(laeufe)
            ruhige[repo["name"]] = {"zeit": jetzt, "laeuft": laeuft, "wartet": wartet}
            ergebnis["repos"].append({"name": repo["name"], "privat": repo["privat"], "laeuft": laeuft, "wartet": wartet})
            laufend.extend((repo, lauf) for lauf in laeufe if lauf.get("status") in LAEUFT and ganzzahl(lauf.get("id")))
        for name in set(ruhige) - {r["name"] for r in repos}:
            del ruhige[name]

        meine = _meine_jobs(klient, org, laufend, ich, speicher) if ich else []
        if meine:
            ergebnis["job"] = meine[0]
            if meine[0]["schritte"] or speicher.get("schritte") is None:
                ergebnis["schritte"] = speicher["schritte"] = bool(meine[0]["schritte"])
        _letzte_jobs(klient, org, meine, speicher, jetzt)
        ergebnis["letzteJobs"] = list(speicher.get("letzte") or [])
        ergebnis["letzterErfolg"] = jetzt
    except ForgejoFehler as fehler:
        ergebnis["abfrage"] = "keine-rechte" if fehler.art == "fehlt" else fehler.art
        ergebnis["fehler"] = str(fehler)
    ergebnis["anfragen"] = dict(klient.zaehler)
    if ergebnis["job"]:
        ergebnis["job"] = {k: v for k, v in ergebnis["job"].items() if not k.startswith("_")}
    return ergebnis


def _meine_jobs(klient: Klient, org: str, laufend: list[tuple[dict, dict]], ich: set[str], speicher: dict) -> list[dict]:
    """Laufende Jobs dieses Runners. Gitea nennt ``runner_name``; bei Forgejo steht der Runner nur in der
    ersten Log-Zeile – je Job (und Versuch) einmal gelesen und gemerkt."""
    wer_je_job = speicher.setdefault("wer", {})
    gesehen: set[str] = set()
    meine: list[dict] = []
    for repo, lauf in laufend[:20]:
        daten = klient.hole(f"/repos/{q(org)}/{q(repo['name'])}/actions/runs/{ganzzahl(lauf['id'])}/jobs").daten
        for job in liste_aus(daten, "jobs"):
            jid = ganzzahl(job.get("id"))
            if jid is None or job.get("status") not in LAEUFT:
                continue
            if "runner_name" in job:
                wer = job.get("runner_name")
            else:
                schluessel = f"{jid}:{ganzzahl(job.get('task_id')) or job.get('attempt') or 0}"
                gesehen.add(schluessel)
                wer = wer_je_job.get(schluessel)
                if wer is None:
                    kopf = klient.hole(f"/repos/{q(org)}/{q(repo['name'])}/actions/jobs/{jid}/logs", text=True).daten
                    wer = wer_aus_log(kopf if isinstance(kopf, str) else "") or ""
                    if wer:  # leer = Log noch nicht da: in der nächsten Runde erneut
                        wer_je_job[schluessel] = wer
            if wer not in ich:
                continue
            schritte, job = job_details(klient, org, repo["name"], job)
            meine.append(job_fuer(lauf, repo, job, schritte))
    for schluessel in set(wer_je_job) - gesehen:
        del wer_je_job[schluessel]
    return meine


def _job_am_ende(klient: Klient, org: str, jid: int, j: dict) -> tuple[str | None, float | None]:
    """Ergebnis und Ende eines Jobs: ``/actions/jobs/{id}`` (Forgejo ab 17, Gitea), sonst aus der
    Job-Liste des Laufs (ältere Forgejo-Versionen, ohne Zeiten). ``(None, None)`` = unbekannt/läuft."""
    pfad = f"/repos/{q(org)}/{q(j['repo'])}/actions"
    try:
        daten = klient.hole(f"{pfad}/jobs/{jid}").daten
        if isinstance(daten, dict):
            return ende_aus(daten, [s for s in daten.get("steps") or [] if isinstance(s, dict)])
    except ForgejoFehler as fehler:
        if fehler.art not in ("fehlt", "keine-rechte"):
            raise
    lauf = ganzzahl(j.get("lauf"))
    if lauf is None:
        return None, None
    try:
        liste = liste_aus(klient.hole(f"{pfad}/runs/{lauf}/jobs").daten, "jobs")
    except ForgejoFehler as fehler:
        if fehler.art not in ("fehlt", "keine-rechte"):
            raise
        return None, None
    job = next((e for e in liste if ganzzahl(e.get("id")) == jid), None)
    return ende_aus(job, None) if job else (None, None)


def _letzte_jobs(klient: Klient, org: str, meine: list[dict], speicher: dict, jetzt: float) -> None:
    """Jobs, die dieser Runner in der vorigen Runde hatte und jetzt nicht mehr: Ergebnis und Ende holen
    und vorn in ``letzte`` (höchstens 5) eintragen. Jobs, die zwischen zwei Runden (30 s) begannen und
    endeten, sieht der Monitor nicht. Ist das Ergebnis (noch) nicht zu bekommen, wird es bis zu einer
    Stunde lang erneut versucht und sonst nicht eingetragen – nie ein geratenes Ergebnis."""
    jetzt_ids = {j["_id"] for j in meine if j.get("_id")}
    vorher: dict = speicher.get("laufend") or {}
    letzte: list = speicher.setdefault("letzte", [])
    bleibt: dict = {}
    for jid, j in vorher.items():
        if not str(jid).isdigit() or int(jid) in jetzt_ids or not isinstance(j, dict):
            continue
        ergebnis, ende = _job_am_ende(klient, org, int(jid), j)
        if ergebnis is None:
            if jetzt - (j.get("gesehen") or jetzt) < 3600:
                bleibt[jid] = j
            continue
        ende = ende or jetzt
        start = j.get("start")
        letzte.insert(0, {"name": j["name"], "ergebnis": ergebnis, "dauer": ende - start if isinstance(start, (int, float)) else None,
                          "ende": ende, "repo": j["repo"], "workflow": j["workflow"]})
    del letzte[MAX_LETZTE:]
    bleibt.update({str(j["_id"]): {"name": j["name"], "repo": j["repo"], "workflow": j["workflow"], "start": j["start"],
                                   "lauf": j.get("_lauf"), "gesehen": jetzt}
                   for j in meine if j.get("_id")})
    speicher["laufend"] = dict(list(bleibt.items())[:20])


# ---------------------------------------------------------------- Adapter


@registriere
class Forgejo(Anbieter):
    dienst = "forgejo"
    FAEHIG = {"status": True, "jobs": True, "schritte": True, "logs": True, "updates": False}
    ANBINDUNG = True
    BRAUCHT_ORG = True

    def __init__(self, konfig: RunnerKonfig) -> None:
        super().__init__(konfig)
        self._schritte: bool | None = None  # liefert der Server Schritte? (aus der letzten Abfrage)

    def faehig(self) -> dict[str, bool]:
        f = super().faehig()
        if self._schritte is False:
            f["schritte"] = False  # z. B. Forgejo vor 17: Job und Laufzeit ja, Schritte nein („teilweise“)
        return f

    # ------------------------------------------------------------ Sammler (root)

    def abfrage(self, speicher: dict, letzter_erfolg: float | None = None, token: str | None = None,
                klient: Klient | None = None) -> dict:
        tok = self.token() if token is None else token
        return abfrage(klient or Klient(self.k.server or "", tok, http_erlaubt=self.k.http_erlaubt),
                       self.k.org, self.k.name, speicher, letzter_erfolg)

    # ------------------------------------------------------------ Monitor

    def beim_dienst(self, ergebnis: dict | None) -> dict | None:
        erg = ergebnis or {}
        zustand = (erg.get("runner") or {}).get("zustand", "unbekannt") if erg.get("abfrage") == "ok" else "unbekannt"
        return {"zustand": zustand if zustand in ("online", "offline") else "unbekannt", "seit": None}

    def jobs_je_repository(self, ergebnis: dict | None) -> dict | None:
        return gh_adapter.workflows_aus({"org": self.k.org, **(ergebnis or {})})

    def api_job(self, ergebnis: dict | None) -> dict | None:
        job = (ergebnis or {}).get("job")
        return job if isinstance(job, dict) else None

    def eintrag(self, *, ergebnis: dict | None = None, **rest) -> dict:
        erg = ergebnis if isinstance(ergebnis, dict) else {}
        self._schritte = erg.get("schritte") if isinstance(erg.get("schritte"), bool) else None
        rest.setdefault("job", self.api_job(erg))
        rest.setdefault("letzte_jobs", [j for j in erg.get("letzteJobs") or [] if isinstance(j, dict)])
        if not rest.get("labels"):
            rest["labels"] = list((erg.get("runner") or {}).get("labels") or [])
        return super().eintrag(ergebnis=erg, **rest)


@registriere
class Gitea(Forgejo):
    """Gitea: dieselben Pfade, Antworten wie GitHub geformt – der Adapter erkennt die Form selbst."""

    dienst = "gitea"
