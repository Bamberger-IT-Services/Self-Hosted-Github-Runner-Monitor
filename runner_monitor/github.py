"""GitHub-REST-Klient (nur lesend) und Releases – läuft im Sammler als root.

Runner-Status, Jobs je Repository und Schritte wertet seit #92 der Adapter
``runner_monitor/anbieter/github.py`` aus; hier bleiben Klient, Fehlerarten, Releases und Versionen.
Das Token (Fine-grained, nur lesend: Actions + Metadata, optional Self-hosted runners) liegt
in ``/etc/runner-monitor/zugang/<runner>.token`` (Rückfall ``/etc/runner-monitor/github-token``,
siehe ``anbieter/token.py``) und verlässt den Sammler nie. Die Oberfläche bekommt nur das
Ergebnis als JSON-Datei.
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
# Kontingent schonen (Issue #15): bedingte Anfragen mit ETag (304 zählt nicht gegen das Kontingent);
# ruhige Repositories fragt der Adapter seltener ab (anbieter/github.py).
SPEICHER_MAX = 2000          # höchstens so viele ETags merken


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


# ---------------------------------------------------------------- Runner-Auswertung (seit #92 im Adapter)

# Die Auswertung für den Runner (Läufe zählen, Job und Schritte, eine Abfrage-Runde) liegt seit #92
# im GitHub-Adapter ``runner_monitor/anbieter/github.py``. Die alten Namen bleiben hier erreichbar,
# bis das Altformat von /api/zustand entfällt (E-19).
_IM_ADAPTER = ("zaehle_laeufe", "ref_aus_lauf", "job_fuer_runner", "abfrage", "LAEUFT", "WARTET", "RUHIG_AB", "RUHIG_TAKT")


def __getattr__(name: str):
    if name in _IM_ADAPTER:
        from .anbieter import github as adapter  # spät importiert: der Adapter nutzt diesen Klienten
        return getattr(adapter, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
        # Gleich nach dem Veröffentlichen hängt der Release-Workflow das Paket erst noch an (#63).
        "bereit": bool(archiv and pruefsumme),
        "notizen": notizen[:6],
        "fehler": "",
    }


AENDERUNGEN_MAX_VERSIONEN = 10
AENDERUNGEN_MAX_PUNKTE = 12
EINMALIG_MAX = 600


def abschnitte(text: str) -> dict[str, list[str]]:
    """Release-Notiz (docs/releases/vX.md) in Abschnitte „## Überschrift“ → Zeilen zerlegen."""
    teile: dict[str, list[str]] = {}
    aktuell = ""
    for zeile in (text or "").splitlines():
        if zeile.startswith("## "):
            aktuell = zeile[3:].strip().lower()
            teile.setdefault(aktuell, [])
        elif aktuell:
            teile[aktuell].append(zeile.rstrip())
    return teile


def deute_notiz(text: str) -> dict:
    """„Was ist neu“ als Punkte, „Einmalig nach dem Update“ als Text (ohne „Keine Schritte nötig.“)."""
    teile = abschnitte(text)
    punkte = lambda zeilen: [z.strip()[1:].strip() for z in zeilen if z.strip().startswith(("-", "*"))]
    neu = punkte(teile.get("was ist neu", []))
    if not neu:  # ältere Notizen ohne Abschnitt: alle Aufzählungspunkte
        neu = punkte((text or "").splitlines())
    einmalig = " ".join(z.strip() for z in teile.get("einmalig nach dem update", []) if z.strip())
    einmalig = re.sub(r"^Keine Schritte nötig\.?\s*", "", einmalig).strip()
    return {"neu": neu[:AENDERUNGEN_MAX_PUNKTE], "einmalig": einmalig[:EINMALIG_MAX]}


def aenderungen(klient: Klient, repo: str, installiert: str, neueste: str) -> list[dict]:
    """Alle veröffentlichten Releases nach ``installiert`` bis einschließlich ``neueste``, neueste
    zuerst – damit Info › Updates zeigt, was sich gegenüber dem installierten Stand ändert (#78)."""
    try:
        daten = klient.hole(f"/repos/{repo}/releases", {"per_page": 30}).daten
    except GitHubFehler:
        return []
    liste = []
    for rel in daten if isinstance(daten, list) else []:
        if not isinstance(rel, dict) or rel.get("draft") or rel.get("prerelease"):
            continue
        tag = rel.get("tag_name", "")
        version = tag[1:] if tag.startswith("v") else tag
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            continue
        if vergleiche(version, installiert) <= 0 or vergleiche(version, neueste) > 0:
            continue
        liste.append({"version": version, "url": rel.get("html_url", ""),
                      "veroeffentlicht": iso_zu_unix(rel.get("published_at")), **deute_notiz(rel.get("body") or "")})
    liste.sort(key=lambda r: tuple(int(x) for x in r["version"].split(".")), reverse=True)
    return liste[:AENDERUNGEN_MAX_VERSIONEN]


def vergleiche(a: str, b: str) -> int:
    """SemVer ohne Vorab-Teil vergleichen: -1, 0, 1."""
    def teile(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in re.findall(r"\d+", v.split("-")[0])[:3]) or (0,)
    ta, tb = teile(a), teile(b)
    return (ta > tb) - (ta < tb)
