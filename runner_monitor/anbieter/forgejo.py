"""Forgejo- und Gitea-Adapter (#93): Runner-Status beim Dienst, Jobs je Repository, aktueller Job mit
Schritten, letzte Jobs. Nur lesend.

Ergebnis der API-Prüfung (docs/FUNKTIONSWEISE.md › „Fähigkeiten je Anbieter“): Forgejo und Gitea
liefern dieselben Pfade unter ``/api/v1``, aber verschieden geformte Antworten. Der Adapter richtet
sich deshalb nach der **Form der Antwort**, nicht nach dem Namen des Dienstes (die Erkennung kann
Forgejo und Gitea nur unterscheiden, wenn der Server ohne Anmeldung antwortet):

* Runner: Forgejo ``[{name, uuid, status: offline|idle|active, labels: ["…"]}]``,
  Gitea ``{runners: [{name, status: online|offline, busy, labels: [{name}]}]}``. Gesucht wird in der Liste
  der Organisation bzw. des Benutzers (mit ``visible=true`` auch globale Runner, braucht Besitzerrechte),
  sonst – höchstens alle 10 Minuten – in ``/admin/actions/runners`` (nur mit ``read:admin`` eines
  Administrators; 403/404 = „darf nicht“, dann erst nach einer Stunde wieder) und in den Listen der
  Repositories (#145). Zugeordnet wird über UUID bzw. Name aus der ``.runner``-Datei (Fund der Erkennung),
  sonst über den Namen aus der Konfiguration bzw. der Unit – nie über die Monitor-ID allein.
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

import json
import math
import re
import threading
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
ZEITLIMIT = 10.0              # harte Gesamtfrist je Anfrage (DNS, Verbindung, Lesen – eigener Faden)
FRIST = 25.0                  # eine ganze Runde; danach bricht sie ab („nicht erreichbar“)
MAX_ANTWORT = 4 * 1024 * 1024
MAX_LOGKOPF = 4096            # vom Job-Log nur der Anfang (wer hat den Job?)
SEITE = 50                    # Forgejo und Gitea liefern höchstens 50 Einträge je Seite (Vorgabe)
MAX_SEITEN = 20               # höchstens 1000 Repositories bzw. Runner
MAX_LETZTE = 5
SUCHE_TAKT = 600              # Runner nicht in der eigenen Liste: Admin- und Repository-Listen höchstens alle 10 Min.
ADMIN_ERNEUT = 3600           # /admin/actions/runners nach 403/404 erst nach einer Stunde wieder versuchen
MAX_REPO_SUCHE = 10           # so viele Repositories (zuletzt geändert zuerst) je Suche
SUCHE_MIN_REST = 12.0         # die erweiterte Suche nur, wenn von der Runde noch so viele Sekunden übrig sind
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
    def __init__(self, art: str, text: str = "", ursache: str | None = None) -> None:
        super().__init__(text or art)
        self.art = art  # nicht-erreichbar | token-ungueltig | keine-rechte | fehlt | kontingent | fehler
        # Warum die Adresse nicht passt (für „Server nicht gefunden“ in einrichten.sh zugang, #120):
        # kein-dienst (antwortet nicht wie Forgejo/Gitea) | weiterleitung (3xx) | None
        self.ursache = ursache


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

    def rest(self) -> float:
        """Sekunden, die von der Runde noch übrig sind."""
        return self._ende - time.monotonic()

    def hole(self, pfad: str, parameter: dict | None = None, *, text: bool = False) -> Antwort:
        """Eine GET-Anfrage mit **harter Frist**: Sie läuft in einem eigenen Daemon-Faden; ist er nach
        ``min(zeitlimit, Rest der Runde)`` nicht fertig (hängender DNS, tröpfelnder Server), gilt der
        Server als nicht erreichbar und der Faden wird zurückgelassen (wie ``gitlab.Klient``)."""
        if not self.server:
            raise ForgejoFehler("fehler", "Server fehlt, ist keine gültige Adresse oder nicht https:// (http:// nur mit „http_erlaubt“ in runner.json)")
        rest = min(self.zeitlimit, self._ende - time.monotonic())
        if rest <= 0:
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
        ergebnis: list = []
        frist = time.monotonic() + rest
        faden = threading.Thread(target=self._hole, args=(anfrage, frist, grenze, text, ergebnis), name="forgejo-abfrage", daemon=True)
        faden.start()
        faden.join(rest)
        if faden.is_alive() or not ergebnis:
            raise ForgejoFehler("nicht-erreichbar", "Zeitüberschreitung (keine vollständige Antwort innerhalb der Frist)")
        art, *wert = ergebnis[0]
        if art == "fehler":
            raise wert[0]
        code, kopf, roh = wert
        if code is not None:
            self._pruefe_code(code, pfad)
        if text:
            return Antwort(roh[:grenze].decode("utf-8", "replace"), kopf)
        if len(roh) > grenze:
            raise ForgejoFehler("fehler", f"Antwort auf {pfad} zu groß")
        try:
            return Antwort(json.loads(roh.decode("utf-8"), parse_constant=_verwerfe_konstante), kopf)
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise ForgejoFehler("fehler", f"Keine gültige JSON-Antwort auf {pfad}", ursache="kein-dienst") from None

    @staticmethod
    def _pruefe_code(code: int, pfad: str) -> None:
        if code == 401:
            raise ForgejoFehler("token-ungueltig", "Token ungültig oder abgelaufen (401)")
        if code == 403:
            raise ForgejoFehler("keine-rechte", f"Keine Berechtigung für {pfad} (403)")
        if code == 404:
            raise ForgejoFehler("fehlt", f"{pfad} nicht gefunden (404)")
        if code == 429:
            raise ForgejoFehler("kontingent", "Zu viele Anfragen (429)")
        if 300 <= code < 400:
            raise ForgejoFehler("fehler", f"Weiterleitung ({code}) – Adresse in runner.json prüfen", ursache="weiterleitung")
        if code >= 500:  # Dienst startet neu, Proxy ohne Ziel: vorübergehend
            raise ForgejoFehler("nicht-erreichbar", f"Server antwortet mit {code}")
        raise ForgejoFehler("fehler", f"Server antwortet mit {code}")

    def _hole(self, anfrage: urllib.request.Request, frist: float, grenze: int, text: bool, ergebnis: list) -> None:
        try:
            try:
                with self._oeffner.open(anfrage, timeout=max(0.1, frist - time.monotonic())) as antwort:
                    kopf = {k.lower(): v for k, v in antwort.headers.items()}
                    ergebnis.append(("ok", None, kopf, _lies_antwort(antwort, frist, grenze, ganz=not text)))
            except urllib.error.HTTPError as fehler:
                try:
                    ergebnis.append(("ok", fehler.code, {}, b""))
                finally:
                    fehler.close()
        except ForgejoFehler as fehler:
            ergebnis[:] = [("fehler", fehler)]
        except Exception as fehler:  # noqa: BLE001 – Netz, DNS, TLS, http.client (BadStatusLine, IncompleteRead …)
            grund = getattr(fehler, "reason", None) or type(fehler).__name__
            ergebnis[:] = [("fehler", ForgejoFehler("nicht-erreichbar", f"Server nicht erreichbar ({grund})"))]


def _verwerfe_konstante(name: str):
    raise ValueError(f"unzulässiger JSON-Wert: {name}")  # NaN, Infinity, -Infinity


def _lies_antwort(antwort, frist: float, grenze: int, ganz: bool = True) -> bytes:
    """Stückweise lesen, höchstens ``grenze`` + 1 Byte, zur Frist abbrechen. ``ganz=False`` (Log-Anfang):
    nach ``grenze`` Byte aufhören, statt den Rest abzuwarten."""
    lese = getattr(antwort, "read1", None) or antwort.read
    teile, gelesen = [], 0
    while gelesen <= grenze if ganz else gelesen < grenze:
        if time.monotonic() > frist:
            raise ForgejoFehler("nicht-erreichbar", "Antwort zu langsam")
        stueck = lese(min(65536, grenze + 1 - gelesen))
        if not stueck:
            break
        teile.append(stueck)
        gelesen += len(stueck)
    return b"".join(teile)


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


def status(d: dict, feld: str = "status") -> str:
    """Status aus einer fremden Antwort – nur ein String zählt (sonst wäre ``in {…}`` ein TypeError)."""
    wert = d.get(feld) if isinstance(d, dict) else None
    return wert[:40] if isinstance(wert, str) else ""


def text(wert: object, grenze: int = 200) -> str:
    return str(wert)[:grenze] if isinstance(wert, (str, int)) and not isinstance(wert, bool) else ""


def zeit(wert: object) -> float | None:
    if not isinstance(wert, str):
        return None
    try:
        ergebnis = gh.iso_zu_unix(wert)
    except (ValueError, OverflowError, OSError):
        return None
    return ergebnis if ergebnis is not None and math.isfinite(ergebnis) else None


def runner_eintrag(r: dict) -> dict:
    """Runner der Liste → ``{zustand: online|offline, beschaeftigt, labels}`` (beide Formen)."""
    zustand = status(r).lower()
    roh = r.get("labels") if isinstance(r.get("labels"), list) else []
    labels = [lab.get("name") if isinstance(lab, dict) else lab for lab in roh]
    return {
        "zustand": "offline" if zustand == "offline" or not zustand else "online",
        "beschaeftigt": r.get("busy") is True or zustand == "active",
        "labels": [str(lab)[:64] for lab in labels if isinstance(lab, str) and lab][:20],
    }


def zaehle(laeufe: list[dict]) -> tuple[int, int]:
    laeuft = sum(1 for lauf in laeufe if status(lauf) in LAEUFT)
    wartet = sum(1 for lauf in laeufe if status(lauf) in WARTET)
    return laeuft, wartet


def workflow_aus(lauf: dict) -> str:
    """Name des Workflows: Forgejo ``workflow_id`` („ci.yml“), Gitea ``path`` („.gitea/workflows/ci.yml@…“)."""
    datei = text(lauf.get("workflow_id")) or text(lauf.get("path"), 500) or text(lauf.get("name"))
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
    namen = [text(s.get("name")) for s in schritte]
    if not namen:
        return [], None
    nr = 0
    for i, s in enumerate(schritte):
        zustand = status(s)
        if zustand in LAEUFT:
            nr = i + 1
            break
        if zustand in ERLEDIGT or status(s, "conclusion"):
            nr = i + 2
    nr = max(1, min(nr, len(namen)))
    return namen, {"nr": nr, "von": len(namen), "name": namen[nr - 1]}


def wer_aus_log(kopf: str) -> str | None:
    """UUID (Forgejo Runner) bzw. Name (act_runner) aus der ersten Zeile des Job-Logs."""
    treffer = LOG_KOPF.match((kopf or "").lstrip("﻿"))
    return treffer.group("wer") if treffer else None


@dataclass(frozen=True)
class Kennung:
    """Wer „dieser Runner“ beim Dienst ist (#145): ``uuid`` und ``name_aus_datei`` aus der ``.runner``-Datei
    (Fund der Erkennung), ``namen`` = dieser Name und Ersatznamen (Name aus der Konfiguration, Unit ohne
    ``.service``) in dieser Reihenfolge."""

    namen: tuple[str, ...] = ()
    uuid: str | None = None
    name_aus_datei: str | None = None

    @classmethod
    def aus(cls, wert: "Kennung | str | None") -> "Kennung":
        if isinstance(wert, Kennung):
            return wert
        return cls(namen=(wert,) if isinstance(wert, str) and wert else ())


GRUND_NICHT_LESBAR = "Runner-Liste nicht lesbar (Besitzerrechte an der Organisation nötig)"
GRUND_NICHT_SICHTBAR = "Runner beim Dienst nicht sichtbar (globaler Runner? Token-Rechte)"


def passt(r: dict, kennung: Kennung) -> int | None:
    """Rang eines Eintrags der Runner-Liste (0 = UUID, 1 … = Name in der Reihenfolge der Kennung) oder None.
    Kennt der Monitor die UUID und nennt der Dienst eine, zählt nur sie – ein gleichnamiger, neu
    registrierter Runner ist ein anderer."""
    ruuid = erkennung.pruefe_uuid(r.get("uuid"))
    if kennung.uuid and ruuid:
        return 0 if ruuid == kennung.uuid else None
    name = r.get("name")
    return 1 + kennung.namen.index(name) if isinstance(name, str) and name in kennung.namen else None


def bester(liste: list[dict], kennung: Kennung) -> dict | None:
    raenge = [(rang, i) for i, r in enumerate(liste) if (rang := passt(r, kennung)) is not None]
    return liste[min(raenge)[1]] if raenge else None


def _durchsuche(klient: Klient, pfad: str, kennung: Kennung) -> dict | None:
    for seite in range(1, MAX_SEITEN + 1):
        liste = liste_aus(klient.hole(pfad, {"visible": "true", "page": seite, "limit": SEITE}).daten, "runners")
        treffer = bester(liste, kennung)
        if treffer or len(liste) < SEITE:
            return treffer
    return None


def _rest(klient: object) -> float:
    rest = getattr(klient, "rest", None)
    return rest() if callable(rest) else math.inf


def runner_beim_dienst(klient: Klient, org: str, besitzer: str, kennung: "Kennung | str", speicher: dict | None = None,
                       repos: list[dict] | None = None, jetzt: float | None = None) -> tuple[dict, dict | None]:
    """Online-Status beim Dienst (optional). ``(Ergebnis, Rohdaten)``; nicht gefunden → ``zustand: unbekannt``
    mit ``grund`` und ``ursache`` (``nicht-lesbar``: keine Liste lesbar, ``nicht-gefunden``: in keiner
    lesbaren Liste). Nur lesend; 403/404 einer Liste heißt „darf nicht“ und ist kein Fehler der Runde.

    Reihenfolge: der Ort des letzten Funds, die eigene Liste (Organisation bzw. Benutzer), dann – fehlt der
    Runner dort, höchstens alle ``SUCHE_TAKT`` Sekunden und nur mit genug Zeit in der Runde – die Liste der
    Instanz (``/admin``, nach 403/404 erst nach ``ADMIN_ERNEUT`` wieder) und die der zuletzt geänderten
    Repositories."""
    kennung = Kennung.aus(kennung)
    speicher = {} if speicher is None else speicher
    jetzt = time.time() if jetzt is None else jetzt
    eigen = f"/orgs/{q(org)}/actions/runners" if besitzer == "org" else "/user/actions/runners"
    repo_namen = [r["name"] for r in sorted(repos or [], key=lambda r: -(r.get("geaendert") or 0))]

    def pfad_fuer(ort: str) -> str | None:
        if ort == "eigen":
            return eigen
        if ort == "admin":
            return "/admin/actions/runners"
        name = ort[5:] if ort.startswith("repo:") else ""
        return f"/repos/{q(org)}/{q(name)}/actions/runners" if name in repo_namen else None

    gelesen = False

    def versuche(ort: str) -> dict | None:
        nonlocal gelesen
        pfad = pfad_fuer(ort)
        if not pfad:
            return None
        try:
            treffer = _durchsuche(klient, pfad, kennung)
        except ForgejoFehler as fehler:
            # die eigene Liste wie bisher; die zusätzlichen Listen sind freiwillig – ein älterer Server ohne
            # den Pfad (400/405) kostet dort nicht die ganze Runde, „nicht erreichbar“ aber schon
            if fehler.art not in ("keine-rechte", "fehlt") and (ort == "eigen" or fehler.art != "fehler"):
                raise
            if ort == "admin":
                speicher["adminAb"] = jetzt + ADMIN_ERNEUT  # Token ohne read:admin oder kein Administrator
            return None
        gelesen = True
        if treffer:
            speicher["runnerOrt"] = ort
        return treffer

    orte = list(dict.fromkeys([speicher.get("runnerOrt") or "eigen", "eigen"]))
    gefunden = next((t for ort in orte if (t := versuche(ort))), None)
    if not gefunden and jetzt >= (speicher.get("sucheAb") or 0) and _rest(klient) >= SUCHE_MIN_REST:
        speicher["sucheAb"] = jetzt + SUCHE_TAKT
        weitere = (["admin"] if jetzt >= (speicher.get("adminAb") or 0) else []) \
            + [f"repo:{n}" for n in repo_namen[:MAX_REPO_SUCHE]]
        for ort in weitere:
            if ort in orte:
                continue
            if _rest(klient) < SUCHE_MIN_REST / 2:
                break  # Läufe und Jobs der Runde gehen vor
            if (gefunden := versuche(ort)):
                break
        speicher["gelesen"] = gelesen
    if gefunden:
        return runner_eintrag(gefunden), gefunden
    speicher.pop("runnerOrt", None)
    if gelesen or speicher.get("gelesen"):
        return {"zustand": "unbekannt", "grund": GRUND_NICHT_SICHTBAR, "ursache": "nicht-gefunden"}, None
    return {"zustand": "unbekannt", "grund": GRUND_NICHT_LESBAR, "ursache": "nicht-lesbar"}, None


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
    start = zeit(job.get("started_at")) or next(
        (z for s in (schritte or []) if (z := zeit(s.get("started")) or zeit(s.get("started_at")))), None) \
        or zeit(lauf.get("started")) or zeit(lauf.get("run_started_at")) or zeit(lauf.get("created_at"))
    return {
        "repo": repo["name"], "privat": repo["privat"], "workflow": workflow_aus(lauf),
        "name": text(job.get("name")), "ref": ref_aus(lauf), "schritte": namen, "schritt": schritt,
        "start": start, "url": text(job.get("html_url"), 500), "zuordenbar": True,
        "_id": ganzzahl(job.get("id")), "_lauf": ganzzahl(lauf.get("id")),
    }


def ende_aus(job: dict, schritte: list[dict] | None) -> tuple[str | None, float | None]:
    """Ergebnis und Ende eines beendeten Jobs (Forgejo: ``status``, Gitea: ``conclusion``)."""
    zustand = status(job, "conclusion") or status(job)
    if not zustand or zustand in LAEUFT or zustand in WARTET:
        return None, None
    ende = zeit(job.get("completed_at"))
    for s in reversed(schritte or []):
        if ende:
            break
        ende = zeit(s.get("stopped")) or zeit(s.get("completed_at"))
    return ERGEBNIS.get(zustand, "abgebrochen"), ende


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
            repos.append({"name": name, "privat": r.get("private") is not False, "geaendert": zeit(r.get("updated_at")) or 0})
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


def abfrage(klient: Klient, org: str, runner_name: "Kennung | str", speicher: dict, letzter_erfolg: float | None = None) -> dict:
    """Eine Runde: Version, Repositories, Runner beim Dienst, Läufe je Repository, aktueller Job, letzte Jobs.
    ``runner_name``: :class:`Kennung` (UUID und Namen) oder nur ein Name."""
    jetzt = time.time()
    kennung = Kennung.aus(runner_name)
    ergebnis: dict = {
        "org": org, "abfrage": "ok", "abgefragt": jetzt, "letzterErfolg": letzter_erfolg, "tokenAblauf": None,
        "kontingent": {}, "art": None, "serverVersion": None, "repos": [], "runner": {"zustand": "unbekannt"},
        "job": None, "letzteJobs": list(speicher.get("letzte") or []), "schritte": speicher.get("schritte"), "fehler": "",
        "laeufeNichtLesbar": 0,
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
            raise ForgejoFehler("fehler", "Server antwortet nicht wie Forgejo oder Gitea (/api/v1/version fehlt)", ursache="kein-dienst") from None
        roh = version.get("version") if isinstance(version, dict) else None
        ergebnis["art"] = art_aus_version(roh)
        ergebnis["serverVersion"] = erkennung.pruefe_version(roh.split("+")[0]) if isinstance(roh, str) else None
        besitzer = _besitzer(klient, org, speicher)
        repos = _repos(klient, org, besitzer)
        ergebnis["runner"], mein = runner_beim_dienst(klient, org, besitzer, kennung, speicher, repos, jetzt)
        # Wer hat einen Job? Forgejo Runner schreibt die UUID ins Log, act_runner/Gitea den Namen. Ist der Runner
        # in einer Liste gefunden, zählt sein Name dort; sonst der aus .runner bzw. die Ersatznamen (#145).
        namen = [mein.get("name")] if mein else [kennung.name_aus_datei] if kennung.name_aus_datei else list(kennung.namen)
        ich = {_wer(w) for w in ((mein or {}).get("uuid"), kennung.uuid, *namen) if isinstance(w, str) and w}

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
                if fehler.art != "fehlt":
                    raise
                # 404 trotz has_actions (z. B. Gitea vor 1.24 ohne /actions/runs): Läufe nicht lesbar –
                # das Repository fehlt in der Liste, und „bereit“ wird nicht behauptet
                ergebnis["laeufeNichtLesbar"] += 1
                continue
            laeufe = liste_aus(daten, "workflow_runs")
            laeuft, wartet = zaehle(laeufe)
            ruhige[repo["name"]] = {"zeit": jetzt, "laeuft": laeuft, "wartet": wartet}
            ergebnis["repos"].append({"name": repo["name"], "privat": repo["privat"], "laeuft": laeuft, "wartet": wartet})
            laufend.extend((repo, lauf) for lauf in laeufe if status(lauf) in LAEUFT and ganzzahl(lauf.get("id")))
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
        if fehler.ursache:
            ergebnis["ursache"] = fehler.ursache
    except (TypeError, ValueError, AttributeError, OverflowError, KeyError, IndexError, RecursionError):
        # Fremde Antwort in unerwarteter Form: Runde als Fehler, nie abstürzen oder Halbes zeigen –
        # der Sammler behält den letzten guten Stand
        ergebnis.update(abfrage="fehler", fehler="unerwartete Antwort des Servers", repos=[], job=None,
                        runner={"zustand": "unbekannt"}, letzteJobs=list(speicher.get("letzte") or []))
    ergebnis["anfragen"] = dict(klient.zaehler)
    if ergebnis["job"]:
        ergebnis["job"] = {k: v for k, v in ergebnis["job"].items() if not k.startswith("_")}
    return ergebnis


def _wer(wert: str) -> str:
    """UUIDs ohne Rücksicht auf Groß-/Kleinschreibung vergleichen, Namen genau."""
    return erkennung.pruefe_uuid(wert) or wert


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
            if jid is None or status(job) not in LAEUFT:
                continue
            if "runner_name" in job:
                wer = text(job.get("runner_name"), 128)
            else:
                schluessel = f"{jid}:{ganzzahl(job.get('task_id')) or job.get('attempt') or 0}"
                gesehen.add(schluessel)
                wer = wer_je_job.get(schluessel)
                if wer is None:
                    kopf = klient.hole(f"/repos/{q(org)}/{q(repo['name'])}/actions/jobs/{jid}/logs", text=True).daten
                    wer = wer_aus_log(kopf if isinstance(kopf, str) else "") or ""
                    if wer:  # leer = Log noch nicht da: in der nächsten Runde erneut
                        wer_je_job[schluessel] = wer
            if _wer(wer) not in ich:
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

VERALTET = 600  # so alt darf eine erfolgreiche Abfrage sein, damit „Dienst aktiv“ statt „unbekannt“ gilt (wie runner.js)

# Job, den der Dienst meldet („beschäftigt“), den der Monitor aber keinem Repository zuordnen kann
JOB_UNBEKANNT = {"repo": "", "privat": False, "workflow": "", "name": "", "ref": None, "schritte": [], "schritt": None,
                 "start": None, "url": "", "zuordenbar": False}


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
        return abfrage(klient or Klient(self.k.server or "", tok, zeitlimit=ZEITLIMIT, http_erlaubt=self.k.http_erlaubt),
                       self.k.org, self.kennung(), speicher, letzter_erfolg)

    def kennung(self) -> Kennung:
        """Name und UUID beim Dienst aus ``.runner`` (#145), dann Name aus der Konfiguration und Unit-Name."""
        unit = (self.k.unit or "").removesuffix(".service")
        namen = [self.k.name_beim_dienst, self.k.name, erkennung.pruefe_name(unit)]
        return Kennung(namen=tuple(dict.fromkeys(n for n in namen if n)), uuid=erkennung.pruefe_uuid(self.k.uuid),
                       name_aus_datei=self.k.name_beim_dienst)

    # ------------------------------------------------------------ Monitor

    def beim_dienst(self, ergebnis: dict | None) -> dict | None:
        erg = ergebnis or {}
        zustand = (erg.get("runner") or {}).get("zustand", "unbekannt") if erg.get("abfrage") == "ok" else "unbekannt"
        if zustand in ("online", "offline"):
            return {"zustand": zustand, "seit": None}
        if erg.get("abfrage") == "ok":
            # Abfrage gelungen, nur dieser Runner fehlt in den lesbaren Listen (#145): „nicht sichtbar“
            return {"zustand": "unbekannt", "seit": None, "sichtbar": False}
        return {"zustand": "unbekannt", "seit": None}

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
        runner_erg = erg.get("runner") if isinstance(erg.get("runner"), dict) else {}
        if not rest.get("labels"):
            rest["labels"] = list(runner_erg.get("labels") or [])
        e = super().eintrag(ergebnis=erg, **rest)
        st = e["status"]
        if e["faehig"]["jobs"] and st["zustand"] == "bereit":
            beim = st.get("beimDienst") or {}
            abgefragt = erg.get("abgefragt")
            aktuell = isinstance(abgefragt, (int, float)) and not isinstance(abgefragt, bool) \
                and time.time() - abgefragt < VERALTET
            if erg.get("abfrage") == "ok" and runner_erg.get("beschaeftigt") is True:
                # beim Dienst beschäftigt, Job aber nicht gefunden (anderes Repository, fehlende Rechte)
                st["zustand"] = "job"
                e["job"] = dict(JOB_UNBEKANNT)
            elif beim.get("sichtbar") is False and aktuell and not erg.get("laeufeNichtLesbar"):
                # Abfrage gelungen und aktuell, nur der Runner fehlt in den Listen (#145): beim lokalen Stand
                # bleiben („Dienst aktiv“) statt „unbekannt“ – „bereit“ wäre nicht belegt
                st["zustand"] = "aktiv"
            elif beim.get("zustand") == "unbekannt" or erg.get("laeufeNichtLesbar"):
                st["zustand"] = "unbekannt"  # Runner-Liste oder Läufe nicht lesbar: nie „bereit“ behaupten
        return e


@registriere
class Gitea(Forgejo):
    """Gitea: dieselben Pfade, Antworten wie GitHub geformt – der Adapter erkennt die Form selbst."""

    dienst = "gitea"
