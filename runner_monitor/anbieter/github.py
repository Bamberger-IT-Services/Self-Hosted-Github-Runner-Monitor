"""GitHub-Adapter (#92): Runner-Status, Jobs je Repository, aktueller Job mit Schritten, Log-Quelle.

Bis 0.7 lag diese Auswertung in ``runner_monitor/github.py`` und ``runner_monitor/zustand.py``; das
Verhalten für genau einen GitHub-Runner ist unverändert (gleiche Anfragen, gleiche ``github.json``,
gleiche Bereiche ``status`` und ``workflows``). ``runner_monitor/github.py`` bleibt der REST-Klient
(auch für Releases und die Prüfung in der Einrichtung) und reicht die alten Namen weiter.

Quellen: Sammler (root) fragt mit dem Token die GitHub-API ab (alle 30 s, ETag, ruhige Repositories
seltener – Issue #15); der Monitor liest ``github.json`` und ergänzt Journal und ``_diag/pages``.
Server ist fest ``https://github.com`` (API ``api.github.com``), die Organisation kommt aus
``einstellungen.json`` bzw. ``MONITOR_ORG``, das Token aus ``zugang/<id>.token`` (Rückfall: alter Ort).
"""

from __future__ import annotations

import re
import time

from .. import github as gh
from . import Anbieter, RunnerKonfig, registriere
from . import token as zugangsdaten

SERVER = "https://github.com"
# Kontingent schonen (Issue #15): ruhige Repositories seltener abfragen.
RUHIG_AB = 3600              # Repository gilt als ruhig, wenn der letzte Push länger her ist …
RUHIG_TAKT = 300             # … und nichts läuft oder wartet: Läufe dann nur alle 5 Minuten abfragen
LAEUFT = {"in_progress"}
WARTET = {"queued", "waiting", "pending", "requested"}
TAKT = 30                    # Sekunden zwischen zwei Abfragen (Sammler)


# ---------------------------------------------------------------- Auswertung (testbar ohne Netz)


def zaehle_laeufe(runs: list[dict]) -> tuple[int, int]:
    laeuft = sum(1 for r in runs if r.get("status") in LAEUFT)
    wartet = sum(1 for r in runs if r.get("status") in WARTET)
    return laeuft, wartet


def ref_aus_lauf(lauf: dict) -> dict:
    prs = lauf.get("pull_requests") or []
    titel = lauf.get("display_title", "") or ""
    if lauf.get("event") == "pull_request" and prs:
        return {"art": "PR", "name": f"#{prs[0].get('number')}", "titel": titel}
    zweig = lauf.get("head_branch") or ""
    if lauf.get("event") in ("release", "push") and re.fullmatch(r"v\d+\.\d+\.\d+.*", zweig):
        return {"art": "Tag", "name": zweig, "titel": titel}
    return {"art": "Branch", "name": zweig, "titel": titel}


def job_fuer_runner(lauf: dict, jobs: list[dict], runner_name: str) -> dict | None:
    for job in jobs:
        if job.get("status") != "in_progress":
            continue
        if runner_name and job.get("runner_name") != runner_name:
            continue
        schritte = [s.get("name", "") for s in job.get("steps") or []]
        aktuell = 0
        for i, schritt in enumerate(job.get("steps") or []):
            if schritt.get("status") == "in_progress":
                aktuell = i
                break
            if schritt.get("status") == "completed":
                aktuell = i + 1
        return {
            "repo": lauf.get("repository", {}).get("name", ""),
            "privat": bool(lauf.get("repository", {}).get("private")),
            "workflow": lauf.get("name", ""),
            "name": job.get("name", ""),
            "ref": ref_aus_lauf(lauf),
            "schritte": schritte,
            "schritt": min(aktuell + 1, max(1, len(schritte))),
            "start": gh.iso_zu_unix(job.get("started_at")),
            "url": job.get("html_url", ""),
        }
    return None


def abfrage(klient: gh.Klient, org: str, runner_name: str, letzter_erfolg: float | None = None) -> dict:
    """Ein Durchlauf: Repos der Organisation, Läufe je Repo, Runner-Status, aktueller Job."""
    jetzt = time.time()
    ergebnis: dict = {
        "org": org, "abfrage": "ok", "abgefragt": jetzt, "letzterErfolg": letzter_erfolg,
        "tokenAblauf": None, "kontingent": {}, "repos": [], "runner": {"zustand": "unbekannt"},
        "job": None, "fehler": "",
    }
    if not klient.token:
        ergebnis["abfrage"] = "kein-token"
        return ergebnis
    if not org:
        ergebnis.update(abfrage="fehler", fehler="MONITOR_ORG ist nicht gesetzt")
        return ergebnis
    try:
        repos: list[dict] = []
        seite = 1
        while seite <= 10:  # höchstens 1000 Repos
            antwort = klient.hole(f"/orgs/{org}/repos", {"per_page": 100, "page": seite, "sort": "pushed"})
            if seite == 1:
                ergebnis["tokenAblauf"] = gh.token_ablauf(antwort.kopf.get("github-authentication-token-expiration"))
            daten = antwort.daten if isinstance(antwort.daten, list) else []
            repos.extend(r for r in daten if not r.get("archived"))
            if len(daten) < 100:
                break
            seite += 1

        ruhige = klient.speicher.setdefault("ruhig", {})  # Repo → {"zeit", "laeuft", "wartet"} der letzten Abfrage
        for repo in repos:
            name = repo.get("name", "")
            alt = ruhige.get(name)
            gepusht = gh.iso_zu_unix(repo.get("pushed_at")) or 0
            if alt and not alt["laeuft"] and not alt["wartet"] and jetzt - gepusht > RUHIG_AB and jetzt - alt["zeit"] < RUHIG_TAKT:
                # ruhig: letzten Stand übernehmen, erst nach RUHIG_TAKT wieder fragen
                ergebnis["repos"].append({"name": name, "privat": bool(repo.get("private")), "laeuft": 0, "wartet": 0})
                continue
            laeufe = klient.hole(f"/repos/{org}/{name}/actions/runs", {"per_page": 30}).daten
            runs = laeufe.get("workflow_runs", []) if isinstance(laeufe, dict) else []
            laeuft, wartet = zaehle_laeufe(runs)
            ruhige[name] = {"zeit": jetzt, "laeuft": laeuft, "wartet": wartet}
            ergebnis["repos"].append({"name": name, "privat": bool(repo.get("private")), "laeuft": laeuft, "wartet": wartet})
            if ergebnis["job"] is None and laeuft:
                for lauf in runs:
                    if lauf.get("status") not in LAEUFT:
                        continue
                    jobs = klient.hole(f"/repos/{org}/{name}/actions/runs/{lauf['id']}/jobs", {"filter": "latest"}).daten
                    gefunden = job_fuer_runner(lauf, jobs.get("jobs", []) if isinstance(jobs, dict) else [], runner_name)
                    if gefunden:
                        ergebnis["job"] = gefunden
                        break

        # Online-Status des Runners: braucht das Recht „Self-hosted runners: read“ (optional).
        try:
            runners = klient.hole(f"/orgs/{org}/actions/runners", {"per_page": 100}).daten
            for r in runners.get("runners", []) if isinstance(runners, dict) else []:
                if not runner_name or r.get("name") == runner_name:
                    ergebnis["runner"] = {
                        "zustand": "online" if r.get("status") == "online" else "offline",
                        "beschaeftigt": bool(r.get("busy")),
                        "labels": [l.get("name") for l in r.get("labels", []) if l.get("name")],
                    }
                    break
        except gh.GitHubFehler as fehler:
            if fehler.art not in ("keine-rechte",):
                raise
            ergebnis["runner"] = {"zustand": "unbekannt", "grund": "Recht „Self-hosted runners: read“ fehlt"}

        ergebnis["letzterErfolg"] = jetzt
        for name in set(ruhige) - {r.get("name", "") for r in repos}:
            del ruhige[name]  # gelöschte oder archivierte Repositories vergessen
    except gh.GitHubFehler as fehler:
        ergebnis["abfrage"] = "nicht-erreichbar" if fehler.art in ("nicht-erreichbar", "fehler") else fehler.art
        ergebnis["fehler"] = str(fehler)
    ergebnis["kontingent"] = klient.kontingent()
    ergebnis["anfragen"] = dict(klient.zaehler)  # davon „unveraendert“ = 304, ohne Kontingent
    return ergebnis


def workflows_aus(ergebnis: dict | None) -> dict:
    """Bereich ``workflows`` bzw. ``jobsJeRepository`` aus ``github.json`` (Format seit 0.1 unverändert)."""
    erg = ergebnis or {}
    abgefragt = erg.get("abgefragt") or 0
    return {
        "org": erg.get("org", ""),
        "abfrage": erg.get("abfrage", "kein-token"),
        "abgefragt": erg.get("letzterErfolg") or abgefragt,
        "versucht": abgefragt,
        "naechste": abgefragt + TAKT if abgefragt else None,
        "tokenAblauf": erg.get("tokenAblauf"),
        "kontingent": erg.get("kontingent") or {},
        "repos": erg.get("repos") or [],
        "fehler": erg.get("fehler", ""),
        "runnerGrund": (erg.get("runner") or {}).get("grund", ""),
    }


# ---------------------------------------------------------------- Adapter


@registriere
class GitHub(Anbieter):
    dienst = "github"
    FAEHIG = {"status": True, "jobs": True, "schritte": True, "logs": True, "updates": False}
    ANBINDUNG = True

    def faehig(self) -> dict[str, bool]:
        # Wie bis 0.7: Status (Dienst „fehlt“ bzw. Online bei GitHub) und Live-Log aus _diag/pages
        # gibt es auch ohne gefundene Unit.
        return dict(self.FAEHIG)

    # ------------------------------------------------------------ Sammler (root)

    def token(self) -> str:
        """``zugang/<id>.token``, sonst der alte Ort (Rückfall bis #94/#96)."""
        return zugangsdaten.lies(self.k.token_datei) or zugangsdaten.lies_rueckfall(self.k.token_rueckfall)

    def abfrage(self, speicher: dict, letzter_erfolg: float | None = None, token: str | None = None) -> dict:
        tok = self.token() if token is None else token
        return abfrage(gh.Klient(tok, speicher=speicher), self.k.org, self.k.name, letzter_erfolg)

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

    def log_quelle(self) -> dict | None:
        """Ausgabe je Schritt in ``<runner>/_diag/pages`` (Schritt-Trenner), Pfad aus der Konfiguration."""
        if not self.k.runner_verz:
            return None
        return {"art": "seiten", "pfad": str(self.k.runner_verz / "_diag" / "pages"), "unit": self.k.unit}


def konfig_fuer(name: str, rid: str, unit: str | None, org: str, runner_verz, zugang_verz, rueckfall) -> RunnerKonfig:
    """Konfiguration des GitHub-Runners aus ``MONITOR_RUNNER_VERZ`` – nie aus einem Fund (E-18)."""
    return RunnerKonfig(id=rid, name=name, dienst="github", unit=unit or None, server=SERVER, org=org,
                        token_datei=zugangsdaten.token_pfad(zugang_verz, rid) if zugangsdaten.pruefe_id(rid) else None,
                        token_rueckfall=rueckfall, runner_verz=runner_verz)
