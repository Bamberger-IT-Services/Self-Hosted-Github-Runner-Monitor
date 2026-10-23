"""Abfrage der GitHub-API (nur lesend) – läuft im Sammler als root.

Das Token (Fine-grained, nur lesend: Actions + Metadata, optional Self-hosted runners) liegt
in ``/etc/runner-monitor/github-token`` und verlässt den Sammler nie. Die Oberfläche bekommt
nur das Ergebnis als JSON-Datei.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

API = "https://api.github.com"
# Kontingent schonen (Issue #15): bedingte Anfragen mit ETag (304 zählt nicht gegen das Kontingent)
# und ruhige Repositories seltener abfragen.
SPEICHER_MAX = 2000          # höchstens so viele ETags merken
RUHIG_AB = 3600              # Repository gilt als ruhig, wenn der letzte Push länger her ist …
RUHIG_TAKT = 300             # … und nichts läuft oder wartet: Läufe dann nur alle 5 Minuten abfragen
LAEUFT = {"in_progress"}
WARTET = {"queued", "waiting", "pending", "requested"}


class GitHubFehler(Exception):
    def __init__(self, art: str, text: str = "") -> None:
        super().__init__(text or art)
        self.art = art  # nicht-erreichbar | token-ungueltig | kontingent | keine-rechte | fehler


@dataclass
class Antwort:
    daten: object
    kopf: dict = field(default_factory=dict)


def iso_zu_unix(wert: str | None) -> float | None:
    if not wert:
        return None
    try:
        return datetime.fromisoformat(wert.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def token_ablauf(kopfzeile: str | None) -> float | None:
    """Kopfzeile ``github-authentication-token-expiration: 2026-11-06 12:00:00 UTC``."""
    if not kopfzeile:
        return None
    treffer = re.match(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})", kopfzeile.strip())
    if not treffer:
        return None
    return datetime.strptime(f"{treffer.group(1)} {treffer.group(2)}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()


class Klient:
    """GitHub-REST-Klient. ``speicher`` (vom Sammler über die Durchläufe gehalten) merkt sich ETags
    und Antworten; eine unveränderte Antwort kommt dann als 304 und kostet kein Kontingent."""

    def __init__(self, token: str = "", zeitlimit: float = 15.0, speicher: dict | None = None) -> None:
        self.token = token.strip()
        self.zeitlimit = zeitlimit
        self.letzter_kopf: dict = {}
        self.speicher = speicher if speicher is not None else {}
        self.etags = self.speicher.setdefault("etags", {})
        self.zaehler = {"anfragen": 0, "unveraendert": 0}

    def hole(self, pfad: str, parameter: dict | None = None) -> Antwort:
        url = API + pfad
        if parameter:
            url += "?" + urllib.parse.urlencode(parameter)
        anfrage = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "runner-monitor",
        })
        if self.token:
            anfrage.add_header("Authorization", f"Bearer {self.token}")
        gemerkt = self.etags.get(url)
        if gemerkt:
            anfrage.add_header("If-None-Match", gemerkt[0])
        self.zaehler["anfragen"] += 1
        try:
            with urllib.request.urlopen(anfrage, timeout=self.zeitlimit) as antwort:  # noqa: S310 – feste https-Adresse
                kopf = {k.lower(): v for k, v in antwort.headers.items()}
                daten = json.loads(antwort.read().decode("utf-8"))
        except urllib.error.HTTPError as fehler:
            kopf = {k.lower(): v for k, v in (fehler.headers or {}).items()}
            self.letzter_kopf = kopf
            if fehler.code == 304 and gemerkt:
                # unverändert: gemerkte Antwort, kostet kein Kontingent
                self.zaehler["unveraendert"] += 1
                return Antwort(gemerkt[1], {**gemerkt[2], **kopf})
            if fehler.code == 401:
                raise GitHubFehler("token-ungueltig", "Token ungültig oder abgelaufen (401)") from fehler
            if fehler.code in (403, 429) and kopf.get("x-ratelimit-remaining") == "0":
                raise GitHubFehler("kontingent", "API-Kontingent erschöpft") from fehler
            if fehler.code in (403, 404):
                raise GitHubFehler("keine-rechte", f"Keine Berechtigung für {pfad} ({fehler.code})") from fehler
            raise GitHubFehler("fehler", f"GitHub antwortet mit {fehler.code}") from fehler
        except (urllib.error.URLError, TimeoutError, OSError) as fehler:
            raise GitHubFehler("nicht-erreichbar", str(fehler)) from fehler
        self.letzter_kopf = kopf
        etag = kopf.get("etag")
        if etag:
            if len(self.etags) >= SPEICHER_MAX and url not in self.etags:
                self.etags.clear()
            self.etags[url] = (etag, daten, {k: v for k, v in kopf.items() if k.startswith("github-authentication")})
        return Antwort(daten, kopf)

    def kontingent(self) -> dict:
        k = self.letzter_kopf
        try:
            return {
                "frei": int(k.get("x-ratelimit-remaining", "0")),
                "limit": int(k.get("x-ratelimit-limit", "0")),
                "reset": int(k.get("x-ratelimit-reset", "0")),
            }
        except ValueError:
            return {}


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
            "start": iso_zu_unix(job.get("started_at")),
            "url": job.get("html_url", ""),
        }
    return None


def abfrage(klient: Klient, org: str, runner_name: str, letzter_erfolg: float | None = None) -> dict:
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
                ergebnis["tokenAblauf"] = token_ablauf(antwort.kopf.get("github-authentication-token-expiration"))
            daten = antwort.daten if isinstance(antwort.daten, list) else []
            repos.extend(r for r in daten if not r.get("archived"))
            if len(daten) < 100:
                break
            seite += 1

        ruhige = klient.speicher.setdefault("ruhig", {})  # Repo → {"zeit", "laeuft", "wartet"} der letzten Abfrage
        for repo in repos:
            name = repo.get("name", "")
            alt = ruhige.get(name)
            gepusht = iso_zu_unix(repo.get("pushed_at")) or 0
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
        except GitHubFehler as fehler:
            if fehler.art not in ("keine-rechte",):
                raise
            ergebnis["runner"] = {"zustand": "unbekannt", "grund": "Recht „Self-hosted runners: read“ fehlt"}

        ergebnis["letzterErfolg"] = jetzt
        for name in set(ruhige) - {r.get("name", "") for r in repos}:
            del ruhige[name]  # gelöschte oder archivierte Repositories vergessen
    except GitHubFehler as fehler:
        ergebnis["abfrage"] = "nicht-erreichbar" if fehler.art in ("nicht-erreichbar", "fehler") else fehler.art
        ergebnis["fehler"] = str(fehler)
    ergebnis["kontingent"] = klient.kontingent()
    ergebnis["anfragen"] = dict(klient.zaehler)  # davon „unveraendert“ = 304, ohne Kontingent
    return ergebnis


def neueste_version(klient: Klient, repo: str) -> dict:
    """Neuestes veröffentlichtes Release (keine Vorab-Versionen)."""
    try:
        daten = klient.hole(f"/repos/{repo}/releases/latest").daten
    except GitHubFehler as fehler:
        return {"geprueft": time.time(), "fehler": str(fehler), "version": ""}
    if not isinstance(daten, dict):
        return {"geprueft": time.time(), "fehler": "unerwartete Antwort", "version": ""}
    tag = daten.get("tag_name", "")
    version = tag[1:] if tag.startswith("v") else tag
    archiv = pruefsumme = ""
    for asset in daten.get("assets", []):
        name = asset.get("name", "")
        if name == f"runner-monitor-{version}.tar.gz":
            archiv = asset.get("browser_download_url", "")
        elif name == f"runner-monitor-{version}.tar.gz.sha256":
            pruefsumme = asset.get("browser_download_url", "")
    notizen = [z.strip("-* ").strip() for z in (daten.get("body") or "").splitlines() if z.strip().startswith(("-", "*"))]
    return {
        "geprueft": time.time(),
        "version": version,
        "veroeffentlicht": iso_zu_unix(daten.get("published_at")),
        "url": daten.get("html_url", ""),
        "archiv": archiv,
        "pruefsumme": pruefsumme,
        "notizen": notizen[:6],
        "fehler": "",
    }


def vergleiche(a: str, b: str) -> int:
    """SemVer ohne Vorab-Teil vergleichen: -1, 0, 1."""
    def teile(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in re.findall(r"\d+", v.split("-")[0])[:3]) or (0,)
    ta, tb = teile(a), teile(b)
    return (ta > tb) - (ta < tb)
