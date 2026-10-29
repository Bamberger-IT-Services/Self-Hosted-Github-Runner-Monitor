"""GitLab-Adapter (#99): Runner-Status und Jobs über die GitLab-REST-API (v4), nur lesend.

Token: persönliches, Projekt- oder Gruppen-Zugriffstoken mit dem Bereich ``read_api`` (nur lesen),
abgelegt in ``/etc/runner-monitor/zugang/<id>.token`` (nur der Sammler als root liest es). Der Server
kommt **nur aus der Konfiguration** (``RunnerKonfig.server``), nie aus dem Fund der Erkennung (E-18);
der Klient folgt keiner Weiterleitung, damit das Token nie an eine andere Adresse geht. Mit Token nur
``https://``; ``http://`` nur, wenn ``runner.json`` für diesen Runner ausdrücklich ``"http_erlaubt": true``
setzt (E-21); dann geht die Anfrage auch nie über einen Proxy aus der Umgebung.

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
import math
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .. import erkennung, github as gh
from . import Anbieter, RunnerKonfig, registriere
from . import token as zugangsdaten

TAKT = 30                        # Sekunden zwischen zwei Abfragen (Sammler)
ZEITLIMIT = 15.0                 # harte Gesamtfrist je Anfrage (DNS, Verbindung, Lesen – eigener Faden)
FRIST = 25.0                     # eine ganze Runde (wie Forgejo); danach bricht sie ab („nicht erreichbar“, #115)
TOKEN_PRUEFUNG = 3600            # Bereiche und Ablauf des Tokens höchstens stündlich neu holen
MAX_ANTWORT = 4 * 1024 * 1024    # größere Antworten gelten als Fehler
MAX_RUNNER_SEITEN = 5            # höchstens 500 Runner durchsuchen
LETZTE_JOBS = 5
GUELTIG = ("read_api", "api")    # Token-Bereiche, die lesen dürfen
STATUS_ONLINE = {"online"}
STATUS_OFFLINE = {"offline", "stale", "never_contacted", "not_connected"}
ERGEBNIS = {"success": "erfolg", "failed": "fehler", "canceled": "abgebrochen", "cancelled": "abgebrochen"}


class GitLabFehler(Exception):
    def __init__(self, art: str, text: str = "", ursache: str | None = None) -> None:
        super().__init__(text or art)
        self.art = art  # nicht-erreichbar | token-ungueltig | kontingent | keine-rechte | fehler
        # Warum die Adresse nicht passt (für „Server nicht gefunden“ in einrichten.sh zugang, #120):
        # kein-dienst (antwortet nicht wie GitLab) | weiterleitung (3xx) | None
        self.ursache = ursache


class _KeineWeiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *argumente, **schluessel):  # noqa: ANN002, ANN003
        return None  # 3xx wird zum HTTPError: das Token geht nie an eine andere Adresse


def _verwerfe_konstante(name: str):
    raise ValueError(f"unzulässiger JSON-Wert: {name}")  # NaN, Infinity, -Infinity


def _oeffner(url: str) -> urllib.request.OpenerDirector:
    """Ohne Weiterleitungen. Bei ``http://`` auch ohne Proxy aus der Umgebung (E-21): das Token ginge
    sonst unverschlüsselt über einen Proxy; bei ``https://`` bleibt der Proxy-Tunnel (CONNECT) möglich."""
    if url.startswith("http://"):
        return urllib.request.build_opener(_KeineWeiterleitung, urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(_KeineWeiterleitung)


class Klient:
    """GitLab-REST-Klient (nur ``GET``). ``server`` kommt aus der Konfiguration, nie aus einem Fund.

    ``https://`` ist Pflicht; ``http://`` nur mit ``http_erlaubt`` (``runner.json`` des Runners, E-21).
    Jede Anfrage hat eine **harte Gesamtfrist** (``zeitlimit``): Sie läuft in einem eigenen Daemon-Faden;
    ist er zur Frist nicht fertig (langsamer DNS, tröpfelnder Server), gilt der Server als nicht
    erreichbar und der Faden wird zurückgelassen (wie ``erkennung.Quelle.hole``). Dazu eine Frist für
    die ganze Runde (``frist``, ab Erzeugen des Klienten, #115): Keine Anfrage läuft über sie hinaus."""

    def __init__(self, server: str, token: str = "", zeitlimit: float = ZEITLIMIT, http_erlaubt: bool = False,
                 frist: float | None = None) -> None:
        adresse = erkennung.pruefe_url(server) or ""
        if adresse.startswith("http://") and http_erlaubt is not True:
            adresse = ""  # Token nur über https, außer runner.json erlaubt http ausdrücklich
        self.server = adresse
        self.token = token.strip()
        self.zeitlimit = zeitlimit
        self.zaehler = {"anfragen": 0}
        self.letzter_kopf: dict = {}
        self._ende = time.monotonic() + (FRIST if frist is None else frist)

    def hole(self, pfad: str, parameter: dict | None = None) -> gh.Antwort:
        if not self.server:
            raise GitLabFehler("fehler", "Server fehlt, ist keine gültige Adresse oder nicht https:// (http:// nur mit „http_erlaubt“ in runner.json)")
        rest = min(self.zeitlimit, self._ende - time.monotonic())
        if rest <= 0:
            raise GitLabFehler("nicht-erreichbar", "Frist für die Abfrage überschritten")
        url = f"{self.server}/api/v4{pfad}"
        if parameter:
            url += "?" + urllib.parse.urlencode(parameter)
        self.zaehler["anfragen"] += 1
        ergebnis: list = []
        ende = time.monotonic() + rest
        faden = threading.Thread(target=self._hole, args=(url, ende, ergebnis), name="gitlab-abfrage", daemon=True)
        faden.start()
        faden.join(rest)
        if faden.is_alive() or not ergebnis:
            raise GitLabFehler("nicht-erreichbar", "Zeitüberschreitung (keine vollständige Antwort innerhalb der Frist)")
        art, *wert = ergebnis[0]
        if art == "fehler":
            raise wert[0]
        code, kopf, roh = wert
        self.letzter_kopf = kopf
        if code is not None:
            self._pruefe_code(code, pfad)
        if len(roh) > MAX_ANTWORT:
            raise GitLabFehler("fehler", "Antwort zu groß")
        try:
            daten = json.loads(roh.decode("utf-8"), parse_constant=_verwerfe_konstante)
        except (UnicodeDecodeError, ValueError, RecursionError) as fehler:
            raise GitLabFehler("fehler", "GitLab antwortet nicht mit JSON (falsche Adresse oder Proxy?)", ursache="kein-dienst") from fehler
        return gh.Antwort(daten, kopf)

    @staticmethod
    def _pruefe_code(code: int, pfad: str) -> None:
        if code == 401:
            raise GitLabFehler("token-ungueltig", "Token ungültig, widerrufen oder abgelaufen (401)")
        if code == 429:
            raise GitLabFehler("kontingent", "API-Kontingent erschöpft (429)")
        if code in (403, 404):
            # GitLab antwortet 404, wenn die Ressource für dieses Token nicht sichtbar ist.
            raise GitLabFehler("keine-rechte", f"Keine Berechtigung für {pfad} ({code})")
        if 300 <= code < 400:
            raise GitLabFehler("fehler", f"GitLab leitet weiter ({code}) – Adresse des Servers prüfen", ursache="weiterleitung")
        raise GitLabFehler("fehler", f"GitLab antwortet mit {code}")

    def _hole(self, url: str, ende: float, ergebnis: list) -> None:
        anfrage = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "runner-monitor",
                                                       "PRIVATE-TOKEN": self.token})
        try:
            try:
                with _oeffner(url).open(anfrage, timeout=max(0.1, ende - time.monotonic())) as antwort:  # noqa: S310 – Adresse aus der Konfiguration
                    kopf = {k.lower(): v for k, v in antwort.headers.items()}
                    ergebnis.append(("ok", None, kopf, _lies_antwort(antwort, ende)))
            except urllib.error.HTTPError as fehler:
                try:
                    kopf = {k.lower(): v for k, v in (fehler.headers or {}).items()}
                    ergebnis.append(("ok", fehler.code, kopf, _lies_antwort(fehler, ende)))
                finally:
                    fehler.close()
        except GitLabFehler as fehler:
            ergebnis[:] = [("fehler", fehler)]
        except Exception as fehler:  # noqa: BLE001 – Netz, DNS, TLS, http.client (BadStatusLine, IncompleteRead …)
            ergebnis[:] = [("fehler", GitLabFehler("nicht-erreichbar", str(getattr(fehler, "reason", None) or fehler) or type(fehler).__name__))]

    def kontingent(self) -> dict:
        """``RateLimit-*`` gibt es nur, wenn der Server sie sendet (gitlab.com ja, viele eigene Server nein)."""
        k = self.letzter_kopf
        try:
            return {"frei": int(k["ratelimit-remaining"]), "limit": int(k["ratelimit-limit"]), "reset": int(k.get("ratelimit-reset", "0"))}
        except (KeyError, ValueError):
            return {}


def _lies_antwort(antwort, ende: float) -> bytes:
    """Antwort stückweise lesen, höchstens ``MAX_ANTWORT`` + 1 Byte, und zur Frist abbrechen."""
    lese = getattr(antwort, "read1", None) or antwort.read
    teile, gelesen = [], 0
    while gelesen <= MAX_ANTWORT:
        if time.monotonic() > ende:
            raise GitLabFehler("nicht-erreichbar", "Antwort zu langsam")
        stueck = lese(min(65536, MAX_ANTWORT + 1 - gelesen))
        if not stueck:
            break
        teile.append(stueck)
        gelesen += len(stueck)
    return b"".join(teile)


# ---------------------------------------------------------------- Auswertung (testbar ohne Netz)


def _dict(wert: object) -> dict:
    """Fremde Antworten: ein Objekt oder ``{}``."""
    return wert if isinstance(wert, dict) else {}


def _liste(wert: object) -> list[dict]:
    return [x for x in wert if isinstance(x, dict)] if isinstance(wert, list) else []


def _text(wert: object, grenze: int = 200) -> str:
    return str(wert)[:grenze] if isinstance(wert, (str, int, float)) and not isinstance(wert, bool) else ""


def _zeit(wert: object) -> float | None:
    if not isinstance(wert, str):
        return None
    try:
        ergebnis = gh.iso_zu_unix(wert)
    except (ValueError, OverflowError, OSError):
        return None
    return ergebnis if ergebnis is not None and math.isfinite(ergebnis) else None


def _zahl_id(wert: object) -> int | None:
    return wert if isinstance(wert, int) and not isinstance(wert, bool) and 0 < wert < 2**53 else None


def _dauer(wert: object) -> int | None:
    if isinstance(wert, bool) or not isinstance(wert, (int, float)) or not math.isfinite(wert) or not 0 <= wert < 10**9:
        return None
    return int(wert)


def ref_aus_job(job: dict) -> dict:
    ref = _text(job.get("ref"))
    titel = _text(_dict(job.get("commit")).get("title"))
    merge = re.fullmatch(r"refs/merge-requests/(\d+)/(?:head|merge)", ref)
    if merge:
        return {"art": "PR", "name": f"!{merge.group(1)}", "titel": titel}  # GitLab schreibt Merge Requests „!12“
    if job.get("tag") is True:
        return {"art": "Tag", "name": ref, "titel": titel}
    return {"art": "Branch", "name": ref, "titel": titel}


def projekt_aus(job: dict) -> str:
    """Name des Projekts: ``project.name`` (Runner-API), sonst die Nummer des Pipeline-Projekts."""
    name = _text(_dict(job.get("project")).get("name"))
    if name:
        return name
    pid = _zahl_id(_dict(job.get("pipeline")).get("project_id"))
    return f"Projekt {pid}" if pid else ""


def _pipeline(job: dict) -> str:
    pid = _zahl_id(_dict(job.get("pipeline")).get("id"))
    return f"Pipeline #{pid}" if pid else ""


def job_aus(job: dict) -> dict:
    """Aktueller Job im Format des Adapters (Schritte gibt die API nicht her)."""
    return {
        "repo": projekt_aus(job),
        "privat": False,  # Sichtbarkeit steht nicht in der Antwort
        "workflow": _pipeline(job),
        "name": _text(job.get("name")),
        "stage": _text(job.get("stage")),
        "ref": ref_aus_job(job),
        "schritte": [],
        "schritt": None,
        "start": _zeit(job.get("started_at")),
        "url": _text(job.get("web_url"), 500),
    }


def letzter_job_aus(job: dict) -> dict:
    return {
        "name": _text(job.get("name")),
        "ergebnis": ERGEBNIS.get(job.get("status") if isinstance(job.get("status"), str) else "", "abgebrochen"),
        "dauer": _dauer(job.get("duration")),
        "ende": _zeit(job.get("finished_at")),
        "repo": projekt_aus(job),
        "workflow": _pipeline(job),
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
    status = r.get("status") if isinstance(r.get("status"), str) else ""
    if status in STATUS_ONLINE:
        return "online"
    if status in STATUS_OFFLINE:
        return "offline"
    if isinstance(r.get("online"), bool):  # ältere Versionen kennen nur das Feld online (bool)
        return "online" if r["online"] else "offline"
    return "unbekannt"


def ist_pausiert(r: dict) -> bool:
    """Pausierter Runner nimmt keine Jobs an. ``paused`` (neu) bzw. ``active: false`` (veraltet)."""
    return r.get("paused") is True or r.get("active") is False


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
        ergebnis.update(abfrage="fehler", fehler="Server fehlt, ist keine gültige Adresse oder nicht https:// (http:// nur mit „http_erlaubt“ in runner.json)")
        return ergebnis
    try:
        _pruefe_token(klient, speicher, jetzt, ergebnis)
        r = _runner(klient, name, speicher)
        if r is None:
            ergebnis["runner"] = {"zustand": "unbekannt", "grund": "Runner mit diesem Namen nicht gefunden oder nicht eindeutig"}
        else:
            rid = r["id"]
            zustand = zustand_aus_runner(r)
            pausiert = ist_pausiert(r)
            ergebnis["runner"] = {"zustand": "offline" if pausiert and zustand == "online" else zustand, "pausiert": pausiert,
                                  "beschaeftigt": False,
                                  "labels": [t[:64] for t in r.get("tag_list", [])[:50] if isinstance(t, str)] if isinstance(r.get("tag_list"), list) else [],
                                  "version": _text(r.get("version"), 40) or None, "id": rid}
            laeuft = _liste(klient.hole(f"/runners/{rid}/jobs", {"status": "running", "per_page": 100}).daten)
            ergebnis["runner"]["beschaeftigt"] = bool(laeuft)
            ergebnis["repos"] = zaehle_laufende(laeuft)
            ergebnis["job"] = job_aus(laeuft[0]) if laeuft else None
            letzte = _liste(klient.hole(f"/runners/{rid}/jobs", {"order_by": "id", "sort": "desc", "per_page": 20}).daten)
            # nur ein Text zählt: ein nicht hashbarer status (Liste, Objekt) wäre bei „in“ ein TypeError und
            # ließe die ganze Runde ausfallen – so fehlt nur dieser eine Job (#115)
            ergebnis["letzteJobs"] = [letzter_job_aus(j) for j in letzte
                                      if isinstance(j.get("status"), str) and j["status"] in ERGEBNIS][:LETZTE_JOBS]
        ergebnis["letzterErfolg"] = jetzt
    except GitLabFehler as fehler:
        ergebnis["abfrage"] = "nicht-erreichbar" if fehler.art in ("nicht-erreichbar", "fehler") else fehler.art
        ergebnis["fehler"] = str(fehler)
        if fehler.ursache:
            ergebnis["ursache"] = fehler.ursache
        if fehler.art == "token-ungueltig":
            speicher.pop("token_geprueft", None)
    except (TypeError, ValueError, AttributeError, OverflowError, KeyError, IndexError, RecursionError):
        # Fremde Antwort in unerwarteter Form: Runde als Fehler melden, nie abstürzen oder Halbes zeigen
        ergebnis.update(abfrage="fehler", fehler="unerwartete Antwort von GitLab", repos=[], job=None, letzteJobs=[],
                        runner={"zustand": "unbekannt"})
    ergebnis["kontingent"] = klient.kontingent()
    ergebnis["anfragen"] = dict(klient.zaehler)
    if ergebnis["abfrage"] == "ok":
        ergebnis["tokenAblauf"] = speicher.get("token_ablauf")
    return ergebnis


def _ablauf(wert: object) -> float | None:
    """``expires_at`` (``2026-11-30``) → Ende des Tages (UTC) als Unix-Zeit; sonst ``None``."""
    if not isinstance(wert, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", wert):
        return None
    try:
        tag = datetime.strptime(wert, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        zeit = tag.timestamp() + 86399
    except (ValueError, OverflowError, OSError):
        return None
    return zeit if zeit > 0 else None


def _pruefe_token(klient: Klient, speicher: dict, jetzt: float, ergebnis: dict) -> None:
    """Bereiche und Ablauf des Tokens (``GET /personal_access_tokens/self``, ab GitLab 15.5), höchstens stündlich.

    Fehlt der Bereich ``read_api``, ist das Token zwar gültig, der Monitor aber ohne Rechte. Antwortet der
    Server mit 403/404 (ältere Version, Token-Art ohne diese Route), wird der Schritt übersprungen."""
    if jetzt - speicher.get("token_geprueft", 0) < TOKEN_PRUEFUNG:
        return
    try:
        daten = _dict(klient.hole("/personal_access_tokens/self").daten)
    except GitLabFehler as fehler:
        if fehler.art != "keine-rechte":
            raise
        speicher["token_geprueft"] = jetzt
        speicher["token_ablauf"] = None
        return
    speicher["token_geprueft"] = jetzt
    bereiche = daten.get("scopes")
    if isinstance(bereiche, list) and bereiche and not any(isinstance(b, str) and b in GUELTIG for b in bereiche):
        speicher.pop("token_geprueft", None)
        raise GitLabFehler("keine-rechte", "Token ohne Bereich read_api")
    speicher["token_ablauf"] = _ablauf(daten.get("expires_at"))


def _runner(klient: Klient, name: str, speicher: dict) -> dict | None:
    """Den Runner des Monitors finden. Die gefundene Nummer wird gemerkt und danach direkt abgefragt."""
    rid = speicher.get("runner_id")
    if _zahl_id(rid):
        try:
            r = _dict(klient.hole(f"/runners/{rid}").daten)
            if r.get("description") == name and r.get("id") == rid:
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
    if treffer is None or not _zahl_id(treffer.get("id")):
        return None
    speicher["runner_id"] = treffer["id"]
    try:  # Einzelheiten (Labels, Version) sind freiwillig
        einzel = _dict(klient.hole(f"/runners/{treffer['id']}").daten)
        # Nummer und Name bleiben die aus der Liste – eine abweichende Antwort ändert nicht, welcher Runner gemeint ist.
        return {**treffer, **einzel, "id": treffer["id"], "description": treffer.get("description")}
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
    # Was der Adapter kann. Seit #126 liefert ``erkennung.FAEHIG["gitlab"]`` dasselbe; die Tabelle darf nie
    # mehr versprechen als diese Klasse (E-20). Ein in runner.json angebundener Runner (Server, Unit)
    # meldet in runner[] die Fähigkeiten dieser Klasse.
    # Schritte: GitLab liefert keine Schrittliste (nur Jobs in Stages) – nicht als verfügbar zeigen.
    FAEHIG = {"status": True, "jobs": True, "schritte": False, "logs": True, "updates": False}
    ANBINDUNG = True   # der Sammler fragt ihn ab (#115), sobald runner.json den Server nennt
    BRAUCHT_ORG = False  # der Runner wird über seinen Namen gefunden, nicht über eine Organisation

    # ------------------------------------------------------------ Sammler (root)

    def token(self) -> str:
        return zugangsdaten.lies(self.k.token_datei)

    def abfrage(self, speicher: dict, letzter_erfolg: float | None = None, token: str | None = None) -> dict:
        tok = self.token() if token is None else token
        return abfrage(Klient(self.k.server or "", tok, http_erlaubt=self.k.http_erlaubt), self.k.name, letzter_erfolg, speicher)

    # ------------------------------------------------------------ Monitor

    def beim_dienst(self, ergebnis: dict | None) -> dict | None:
        erg = ergebnis or {}
        runner = erg.get("runner") if isinstance(erg.get("runner"), dict) else {}
        zustand = runner.get("zustand", "unbekannt") if erg.get("abfrage") == "ok" else "unbekannt"
        antwort = {"zustand": zustand, "seit": None}
        if zustand != "unbekannt" and runner.get("pausiert"):
            antwort["pausiert"] = True  # offline, weil der Runner bei GitLab pausiert ist
        return antwort

    def jobs_je_repository(self, ergebnis: dict | None) -> dict | None:
        return workflows_aus(ergebnis)

    def api_job(self, ergebnis: dict | None) -> dict | None:
        job = (ergebnis or {}).get("job")
        return job if isinstance(job, dict) else None

    def letzte_jobs(self, ergebnis: dict | None) -> list[dict]:
        liste = (ergebnis or {}).get("letzteJobs")
        return [j for j in liste if isinstance(j, dict)] if isinstance(liste, list) else []

    def eintrag(self, *, ergebnis: dict | None = None, **rest) -> dict:
        """Wie die Basis, dazu Job, letzte Jobs und Labels aus der Abfrage des Sammlers (#115). Ehrlich
        wie bei Forgejo (E-23): ist der Runner bei GitLab nicht zu finden oder schlug die Abfrage fehl,
        ist der Zustand ``unbekannt`` statt „bereit“."""
        erg = ergebnis if isinstance(ergebnis, dict) else {}
        rest.setdefault("job", self.api_job(erg))
        rest.setdefault("letzte_jobs", self.letzte_jobs(erg))
        runner_erg = erg.get("runner") if isinstance(erg.get("runner"), dict) else {}
        if not rest.get("labels"):
            labels = runner_erg.get("labels")
            rest["labels"] = [lab for lab in labels if isinstance(lab, str)] if isinstance(labels, list) else []
        e = super().eintrag(ergebnis=erg, **rest)
        st = e["status"]
        if e["faehig"]["jobs"] and st["zustand"] == "bereit" and (st.get("beimDienst") or {}).get("zustand") == "unbekannt":
            st["zustand"] = "unbekannt"
        return e


def konfig_fuer(name: str, rid: str, unit: str | None, server: str | None, zugang_verz, log: str | None = None,
                http_erlaubt: bool = False) -> RunnerKonfig:
    """Konfiguration eines GitLab-Runners – Server, Log-Pfad und ``http_erlaubt`` nur aus ``runner.json``
    bzw. der Einrichtung, nie aus einem Fund (E-18). ``http://`` nur bei ``http_erlaubt is True`` (E-21)."""
    adresse = erkennung.pruefe_url(server)
    if adresse and adresse.startswith("http://") and http_erlaubt is not True:
        adresse = None
    return RunnerKonfig(id=rid, name=name, dienst="gitlab", unit=erkennung.pruefe_unit(unit), log=log, server=adresse,
                        token_datei=zugangsdaten.token_pfad(zugang_verz, rid) if zugangsdaten.pruefe_id(rid) else None,
                        http_erlaubt=http_erlaubt is True)
