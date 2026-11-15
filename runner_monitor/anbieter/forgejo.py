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
  Repositories (#145). Zugeordnet wird über UUID bzw. Name aus der ``.runner``-Datei (Fund der Erkennung)
  oder den von Hand eingetragenen Namen beim Server (``runner.json`` › ``name_beim_dienst``, #172), in der
  eigenen Liste auch über den Namen aus der Konfiguration bzw. der Unit – nie über die Monitor-ID allein.
* Läufe: ``/repos/{o}/{r}/actions/runs`` – Forgejo ``status: running|waiting|blocked|success|…``,
  Gitea wie GitHub (``in_progress``, ``queued`` …). Forgejo (gemessen an 17.0.1) beachtet ``limit`` nur
  zusammen mit ``page`` und liefert sonst **alle** Läufe (je Lauf rund 27 KB); ``status`` filtert serverseitig,
  mehrfach angegeben als Oder, ein unbekannter Wert gibt 400 (#163). Gefragt wird deshalb nur nach
  ``running``, ``waiting`` und ``blocked``, seitenweise; Gitea (und ein Server, der den Filter mit 400
  ablehnt) ohne Filter, erste Seite.
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

import contextlib
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
from . import jobsicht

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
SUCHE_MIN_REST = 6.0          # die erweiterte Suche (nach Läufen und Jobs) nur, wenn von der Runde noch so viele Sekunden übrig sind
SUCHE_RESERVE = 2.0           # jede Anfrage der erweiterten Suche endet so viele Sekunden vor dem Ende der Runde (#151)
LAUF_STATUS = ("running", "waiting", "blocked")  # Forgejo-Werte aus LAEUFT/WARTET (Forgejo kennt unknown, waiting,
#                                                  running, success, failure, cancelled, skipped, blocked)
LAUF_SEITEN = 4               # mit Statusfilter höchstens 200 laufende/wartende Läufe je Repository
LAUF_OHNE_FILTER = 30         # ohne Filter (Gitea): nur die neuesten Läufe
FILTER_ERNEUT = 3600          # lehnt der Server den Statusfilter ab (400), erst nach einer Stunde wieder versuchen
MAX_LAUFENDE_LAEUFE = 8       # laufende und wartende Läufe im Dashboard (#171): Job-Listen höchstens dieser laufenden Läufe …
MAX_SCHRITT_JOBS = 6          # … Schritte (/actions/jobs/{id}) höchstens dieser laufenden Jobs je Runde …
SICHT_MIN_REST = 12.0         # … nur, wenn von der Runde noch so viele Sekunden übrig sind (die Suche nach dem Runner hat Vorrang) …
VERGLEICH_TAKT = 600          # … Vergleichsdauern je Workflow und Job höchstens alle 10 Minuten neu …
VERGLEICH_ANFRAGEN = 8        # … und dafür höchstens so viele Anfragen je Runde (der Rest folgt in der nächsten)
VERGLEICH_LAEUFE = 20         # erfolgreiche Läufe je Repository, aus denen die letzten 5 desselben Workflows kommen
MAX_VERGLEICHE = 40           # so viele Workflow/Job-Paare merkt der Speicher
FRUEHESTENS = 946684800.0     # Zeiten vor dem Jahr 2000 sind „nicht gesetzt“ (Forgejo schreibt 0001-01-01)
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
    def __init__(self, art: str, text: str = "", ursache: str | None = None, code: int | None = None) -> None:
        super().__init__(text or art)
        self.code = code  # HTTP-Status, wenn der Server mit einem Fehlercode antwortete
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
        self._deckel: float | None = None  # früheres Ende für freiwillige Anfragen (siehe begrenze)
        if oeffner is None:
            # bei http:// ohne Proxy aus der Umgebung: das Token ginge sonst unverschlüsselt über ihn (E-21)
            oeffner = (urllib.request.build_opener(_OhneWeiterleitung, urllib.request.ProxyHandler({}))
                       if adresse.startswith("http://") else urllib.request.build_opener(_OhneWeiterleitung))
        self._oeffner = oeffner

    def rest(self) -> float:
        """Sekunden, die von der Runde noch übrig sind."""
        return self._ende - time.monotonic()

    @contextlib.contextmanager
    def begrenze(self, reserve: float):
        """Anfragen im Block enden spätestens ``reserve`` Sekunden vor dem Ende der Runde (freiwillige Suche, #151)."""
        alt = self._deckel
        self._deckel = self._ende - reserve
        try:
            yield
        finally:
            self._deckel = alt

    def hole(self, pfad: str, parameter: dict | None = None, *, text: bool = False) -> Antwort:
        """Eine GET-Anfrage (im Block von :meth:`begrenze` mit früherem Ende) mit **harter Frist**: Sie läuft in einem eigenen Daemon-Faden; ist er nach
        ``min(zeitlimit, Rest der Runde)`` nicht fertig (hängender DNS, tröpfelnder Server), gilt der
        Server als nicht erreichbar und der Faden wird zurückgelassen (wie ``gitlab.Klient``)."""
        if not self.server:
            raise ForgejoFehler("fehler", "Server fehlt, ist keine gültige Adresse oder nicht https:// (http:// nur mit „http_erlaubt“ in runner.json)")
        ende = self._ende if self._deckel is None else min(self._ende, self._deckel)
        rest = min(self.zeitlimit, ende - time.monotonic())
        if rest <= 0:
            raise ForgejoFehler("nicht-erreichbar", "Frist für die Abfrage überschritten")
        url = f"{self.server}/api/v1{pfad}"
        if parameter:
            url += "?" + urllib.parse.urlencode(parameter, doseq=True)  # Listen: ?status=a&status=b
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
        raise ForgejoFehler("fehler", f"Server antwortet mit {code}", code=code)

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


def spaeter_als_2000(wert: float | None) -> float | None:
    return wert if wert is not None and wert >= FRUEHESTENS else None


def schritt_start(schritte: list[dict], nr: int) -> float | None:
    """Beginn des Schritts Nr. ``nr`` (1 = erster), wenn der Server ihn nennt."""
    if not 1 <= nr <= len(schritte):
        return None
    s = schritte[nr - 1]
    return spaeter_als_2000(zeit(s.get("started")) or zeit(s.get("started_at")))


def job_dauer(job: dict, schritte: list[dict] | None) -> float | None:
    """Dauer eines beendeten Jobs: ``started_at``/``completed_at`` des Jobs, sonst vom Beginn des ersten bis zum Ende
    des letzten Schritts."""
    d = jobsicht.dauer_zwischen(spaeter_als_2000(zeit(job.get("started_at"))), spaeter_als_2000(zeit(job.get("completed_at"))))
    if d:
        return d
    start = next((z for s in schritte or [] if (z := spaeter_als_2000(zeit(s.get("started")) or zeit(s.get("started_at"))))), None)
    ende = next((z for s in reversed(schritte or []) if (z := spaeter_als_2000(zeit(s.get("stopped")) or zeit(s.get("completed_at"))))), None)
    return jobsicht.dauer_zwischen(start, ende)


def erfolgreich(lauf: dict) -> bool:
    """Forgejo: ``status: success``; Gitea wie GitHub: ``completed`` mit ``conclusion: success``."""
    return status(lauf) == "success" or (status(lauf) == "completed" and status(lauf, "conclusion") == "success")


def lauf_dauer(lauf: dict) -> float | None:
    """Laufzeit eines beendeten Laufs: Forgejo ``started``/``stopped``, Gitea ``started_at``/``completed_at``."""
    start = spaeter_als_2000(zeit(lauf.get("started")) or zeit(lauf.get("started_at")) or zeit(lauf.get("run_started_at")))
    ende = spaeter_als_2000(zeit(lauf.get("stopped")) or zeit(lauf.get("completed_at")))
    return jobsicht.dauer_zwischen(start, ende)


def wartend_aus(lauf: dict, repo: dict) -> dict:
    """Wartender Lauf für die Warteschlange (``jobsicht.positionen``); ``blocked`` wartet nicht auf einen Runner."""
    return {"repo": repo["name"], "privat": repo["privat"], "workflow": workflow_aus(lauf), "ref": ref_aus(lauf),
            "seit": spaeter_als_2000(zeit(lauf.get("created")) or zeit(lauf.get("created_at"))),
            "blockiert": status(lauf) == "blocked", "_id": ganzzahl(lauf.get("id"))}


def wer_aus_log(kopf: str) -> str | None:
    """UUID (Forgejo Runner) bzw. Name (act_runner) aus der ersten Zeile des Job-Logs."""
    treffer = LOG_KOPF.match((kopf or "").lstrip("﻿"))
    return treffer.group("wer") if treffer else None


@dataclass(frozen=True)
class Kennung:
    """Wer „dieser Runner“ beim Dienst ist (#145): ``uuid`` aus der ``.runner``-Datei (Fund der Erkennung),
    ``name_aus_datei`` = Name beim Server – von Hand aus ``runner.json`` › ``name_beim_dienst`` (#172) oder aus
    der Registrierung –, ``namen`` = dieser Name und Ersatznamen (Anzeigename aus der Konfiguration, Unit ohne
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


def passt(r: dict, kennung: Kennung, streng: bool = False) -> int | None:
    """Rang eines Eintrags der Runner-Liste (0 = UUID, 1 … = Name in der Reihenfolge der Kennung) oder None.
    Kennt der Monitor die UUID und nennt der Dienst eine, zählt nur sie – ein gleichnamiger, neu
    registrierter Runner ist ein anderer. ``streng`` (Liste der Instanz, Repository-Listen; #152): ohne
    UUID zählt nur der Name beim Server (aus der ``.runner``-Datei oder von Hand, #172) – Ersatznamen
    (Monitor-ID, Unit) könnten dort einen gleichnamigen Runner einer anderen Organisation treffen."""
    ruuid = erkennung.pruefe_uuid(r.get("uuid"))
    if kennung.uuid and ruuid:
        return 0 if ruuid == kennung.uuid else None
    name = r.get("name")
    if not isinstance(name, str) or name not in kennung.namen:
        return None
    if streng and name != kennung.name_aus_datei:
        return None
    return 1 + kennung.namen.index(name)


def bester(liste: list[dict], kennung: Kennung, streng: bool = False) -> dict | None:
    raenge = [(rang, i) for i, r in enumerate(liste) if (rang := passt(r, kennung, streng)) is not None]
    return liste[min(raenge)[1]] if raenge else None


def _durchsuche(klient: Klient, pfad: str, kennung: Kennung, streng: bool = False) -> dict | None:
    for seite in range(1, MAX_SEITEN + 1):
        liste = liste_aus(klient.hole(pfad, {"visible": "true", "page": seite, "limit": SEITE}).daten, "runners")
        treffer = bester(liste, kennung, streng)
        if treffer or len(liste) < SEITE:
            return treffer
    return None


def _rest(klient: object) -> float:
    rest = getattr(klient, "rest", None)
    return rest() if callable(rest) else math.inf


class RunnerSuche:
    """Online-Status beim Dienst (optional), in zwei Stufen (#151). ``eigene()`` liest vor Läufen und Jobs nur die
    eigene Liste (Organisation bzw. Benutzer). ``erweitert()`` läuft erst NACH Läufen und Jobs: zuerst der
    gemerkte Ort des letzten Funds (z. B. ``/admin``, jede Runde), fehlt der Runner, die Liste der Instanz
    (``/admin``, nach 403/404 erst nach ``ADMIN_ERNEUT`` wieder) und die der zuletzt geänderten Repositories,
    höchstens alle ``SUCHE_TAKT`` Sekunden und nur mit ``SUCHE_MIN_REST`` Sekunden Rest. Jede Anfrage dort
    endet ``SUCHE_RESERVE`` Sekunden vor der Rundenfrist; Zeitüberschreitung und 429 kosten die Runde nichts
    (die Erreichbarkeit ist in der Runde schon belegt). UUID und Name des letzten Funds merkt ``speicher``
    (``runnerWer``), damit Läufe und Jobs schon vorher richtig zugeordnet werden. Nur lesend; 403/404 einer
    Liste heißt „darf nicht“."""

    def __init__(self, klient: Klient, org: str, besitzer: str, kennung: "Kennung | str", speicher: dict | None = None,
                 repos: list[dict] | None = None, jetzt: float | None = None) -> None:
        self.klient = klient
        self.org = org
        self.kennung = Kennung.aus(kennung)
        self.speicher = {} if speicher is None else speicher
        self.jetzt = time.time() if jetzt is None else jetzt
        self.eigen = f"/orgs/{q(org)}/actions/runners" if besitzer == "org" else "/user/actions/runners"
        self.repo_namen = [r["name"] for r in sorted(repos or [], key=lambda r: -(r.get("geaendert") or 0))]
        self.gelesen = False

    def _pfad_fuer(self, ort: str) -> str | None:
        if ort == "eigen":
            return self.eigen
        if ort == "admin":
            return "/admin/actions/runners"
        name = ort[5:] if ort.startswith("repo:") else ""
        return f"/repos/{q(self.org)}/{q(name)}/actions/runners" if name in self.repo_namen else None

    def _versuche(self, ort: str, still: bool = False) -> dict | None:
        pfad = self._pfad_fuer(ort)
        if not pfad:
            return None
        try:
            treffer = _durchsuche(self.klient, pfad, self.kennung, streng=ort != "eigen")
        except ForgejoFehler as fehler:
            # die eigene Liste wie bisher; die zusätzlichen Listen sind freiwillig – ein älterer Server ohne
            # den Pfad (400/405) kostet dort nicht die ganze Runde. In der erweiterten Suche (still) auch
            # „nicht erreichbar“ und 429 nicht: Läufe und Jobs sind dann schon gelesen
            if still and fehler.art in ("nicht-erreichbar", "kontingent"):
                raise _SucheAbbruch from None
            if fehler.art not in ("keine-rechte", "fehlt") and (ort == "eigen" or fehler.art != "fehler"):
                raise
            if ort == "admin":
                self.speicher["adminAb"] = self.jetzt + ADMIN_ERNEUT  # Token ohne read:admin oder kein Administrator
            return None
        self.gelesen = True
        if treffer:
            self.speicher["runnerOrt"] = ort
            self.speicher["runnerWer"] = {"uuid": text(treffer.get("uuid")) or None, "name": text(treffer.get("name")) or None}
        elif self.speicher.get("runnerOrt") == ort:
            self.speicher.pop("runnerOrt", None)  # dort nicht mehr; wieder suchen
            self.speicher.pop("runnerWer", None)
        return treffer

    def eigene(self) -> dict | None:
        return self._versuche("eigen")

    def erweitert(self) -> dict | None:
        """Gemerkter Ort, dann – höchstens alle ``SUCHE_TAKT`` – ``/admin`` und die Repository-Listen."""
        ort0 = self.speicher.get("runnerOrt")
        voll = self.jetzt >= (self.speicher.get("sucheAb") or 0) and _rest(self.klient) >= SUCHE_MIN_REST
        if not voll and not (ort0 and ort0 != "eigen"):
            return None
        orte = [ort0] if ort0 and ort0 != "eigen" else []
        gefunden = None
        abgebrochen = False
        with self.klient.begrenze(SUCHE_RESERVE):
            for ort in orte:
                try:
                    gefunden = self._versuche(ort, still=True)
                except _SucheAbbruch:
                    abgebrochen = True  # Ort bleibt gemerkt, nächste Runde wieder
            if not gefunden and voll:
                self.speicher["sucheAb"] = self.jetzt + SUCHE_TAKT
                weitere = (["admin"] if self.jetzt >= (self.speicher.get("adminAb") or 0) else []) \
                    + [f"repo:{n}" for n in self.repo_namen[:MAX_REPO_SUCHE]]
                for ort in weitere:
                    if ort in orte:
                        continue
                    if _rest(self.klient) < SUCHE_RESERVE + 1:
                        break  # für die Runde bleibt nichts mehr übrig
                    try:
                        if (gefunden := self._versuche(ort, still=True)):
                            break
                    except _SucheAbbruch:
                        if ort != "admin":
                            break  # Zeitüberschreitung oder 429: nächste Runde nach der Pause wieder
                        # an /admin gescheitert: die Repository-Listen, solange Zeit bleibt (K3)
        if not gefunden and not abgebrochen and ort0 and ort0 == self.speicher.get("runnerOrt"):
            self.speicher.pop("runnerOrt", None)  # dort nicht (mehr) lesbar oder nicht mehr drin
            self.speicher.pop("runnerWer", None)
        if voll:
            self.speicher["gelesen"] = self.gelesen
        return gefunden

    def ergebnis(self, gefunden: dict | None) -> tuple[dict, dict | None]:
        """``(Ergebnis, Rohdaten)``; nicht gefunden → ``zustand: unbekannt`` mit ``grund`` und ``ursache``
        (``nicht-lesbar``: keine Liste lesbar, ``nicht-gefunden``: in keiner lesbaren Liste)."""
        if gefunden:
            return runner_eintrag(gefunden), gefunden
        if self.gelesen or self.speicher.get("gelesen"):
            return {"zustand": "unbekannt", "grund": GRUND_NICHT_SICHTBAR, "ursache": "nicht-gefunden"}, None
        return {"zustand": "unbekannt", "grund": GRUND_NICHT_LESBAR, "ursache": "nicht-lesbar"}, None


class _SucheAbbruch(Exception):
    """Die freiwillige Suche endet still (siehe :meth:`RunnerSuche.erweitert`)."""


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
    if schritt:
        schritt = {**schritt, "start": schritt_start(schritte or [], schritt["nr"])}
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


def _laeufe(klient: Klient, pfad: str, filtern: bool) -> list[dict]:
    """Läufe eines Repositorys, die gezählt werden (läuft/wartet). Mit ``filtern`` (Forgejo) serverseitig nach
    :data:`LAUF_STATUS` gefiltert und seitenweise – ``page`` muss mit, sonst beachtet Forgejo ``limit`` nicht
    (#163). Ohne Filter (Gitea) die neuesten Läufe der ersten Seite. Gezählt wird in jedem Fall mit
    :func:`zaehle` auf dem Client – ein Server, der den Filter übergeht, zählt so trotzdem richtig."""
    if not filtern:
        return liste_aus(klient.hole(pfad, {"page": 1, "limit": LAUF_OHNE_FILTER}).daten, "workflow_runs")
    laeufe: dict = {}
    for seite in range(1, LAUF_SEITEN + 1):
        liste = liste_aus(klient.hole(pfad, {"status": list(LAUF_STATUS), "page": seite, "limit": SEITE}).daten, "workflow_runs")
        neu = 0
        for lauf in liste:
            schluessel = ganzzahl(lauf.get("id")) or f"ohne-id-{len(laeufe)}"
            if schluessel not in laeufe:
                laeufe[schluessel] = lauf
                neu += 1
        # letzte Seite, Server blättert nicht (nichts Neues) oder filtert nicht (Erledigtes dabei): aufhören
        if len(liste) < SEITE or not neu or any(status(lauf) not in LAEUFT | WARTET for lauf in liste):
            break
    return list(laeufe.values())


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
        "laeufeNichtLesbar": 0, "laufende": [], "wartende": [],
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
        suche = RunnerSuche(klient, org, besitzer, kennung, speicher, repos, jetzt)
        mein = suche.eigene()
        ergebnis["runner"], mein = suche.ergebnis(mein)
        # Wer hat einen Job? Forgejo Runner schreibt die UUID ins Log, act_runner/Gitea den Namen. Ist der Runner
        # in einer Liste gefunden, zählt sein Name dort; sonst der aus .runner bzw. die Ersatznamen (#145).
        # Ein früherer Fund (speicher["runnerWer"]) gilt schon vor der erweiterten Suche (#151).
        wer = mein or speicher.get("runnerWer") or {}
        namen = [wer.get("name")] if wer.get("name") else [kennung.name_aus_datei] if kennung.name_aus_datei else list(kennung.namen)
        ich = {_wer(w) for w in (wer.get("uuid"), kennung.uuid, *namen) if isinstance(w, str) and w}

        ruhige = speicher.setdefault("ruhig", {})
        laufend: list[tuple[dict, dict]] = []
        wartend: list[dict] = []
        luecken = False  # Läufe fehlen vielleicht (Liste ohne Statusfilter voll, Seitengrenze): keine Position (K2)
        runde: dict = {}  # Zwischenspeicher dieser Runde (Job-Listen, erfolgreiche Läufe; #171)
        filtern = ergebnis["art"] != "gitea" and jetzt >= (speicher.get("filterAb") or 0)
        for repo in repos:
            alt = ruhige.get(repo["name"])
            if (alt and not alt["laeuft"] and not alt["wartet"] and jetzt - repo["geaendert"] > gh_adapter.RUHIG_AB
                    and jetzt - alt["zeit"] < gh_adapter.RUHIG_TAKT):
                ergebnis["repos"].append({"name": repo["name"], "privat": repo["privat"], "laeuft": 0, "wartet": 0})
                continue
            pfad = f"/repos/{q(org)}/{q(repo['name'])}/actions/runs"
            try:
                try:
                    laeufe = _laeufe(klient, pfad, filtern)
                except ForgejoFehler as fehler:
                    if not (filtern and fehler.code == 400):
                        raise
                    # Server kennt den Statusfilter nicht (z. B. Gitea): ohne Filter, eine Stunde lang
                    filtern = False
                    speicher["filterAb"] = jetzt + FILTER_ERNEUT
                    laeufe = _laeufe(klient, pfad, False)
            except ForgejoFehler as fehler:
                if fehler.art not in ("fehlt", "fehler"):
                    raise  # Token, Rechte, Erreichbarkeit, Kontingent: die ganze Runde wie bisher
                # 404 trotz has_actions (z. B. Gitea vor 1.24 ohne /actions/runs), Antwort zu groß oder ungültig
                # (#163): nur die Läufe dieses Repositorys sind nicht lesbar – es fehlt in der Liste, die übrige
                # Runde bleibt „ok“, und „bereit“ wird nicht behauptet
                ergebnis["laeufeNichtLesbar"] += 1
                continue
            luecken = luecken or len(laeufe) >= (LAUF_SEITEN * SEITE if filtern else LAUF_OHNE_FILTER)
            laeuft, wartet = zaehle(laeufe)
            ruhige[repo["name"]] = {"zeit": jetzt, "laeuft": laeuft, "wartet": wartet}
            ergebnis["repos"].append({"name": repo["name"], "privat": repo["privat"], "laeuft": laeuft, "wartet": wartet})
            laufend.extend((repo, lauf) for lauf in laeufe if status(lauf) in LAEUFT and ganzzahl(lauf.get("id")))
            wartend.extend(wartend_aus(lauf, repo) for lauf in laeufe if status(lauf) in WARTET)
        for name in set(ruhige) - {r["name"] for r in repos}:
            del ruhige[name]

        meine = _meine_jobs(klient, org, laufend, ich, speicher, runde) if ich else []
        if meine:
            ergebnis["job"] = meine[0]
            if meine[0]["schritte"] or speicher.get("schritte") is None:
                ergebnis["schritte"] = speicher["schritte"] = bool(meine[0]["schritte"])
        # Lässt sich der Runner beim Dienst nicht erkennen (globaler Runner ohne UUID, nicht in den lesbaren Listen, #145),
        # kennt der Monitor nur die Jobs der Organisation: „Letzte Jobs“ zeigt dann diese (#171) und die laufenden Jobs
        # tragen kein „anderer Runner“. Sonst nur die Jobs dieses Runners.
        org_modus = not (mein or speicher.get("runnerWer") or kennung.uuid)
        org_jobs = _org_jobs(klient, org, laufend, runde)
        modus = "org" if org_modus and not meine else "eigen"
        _letzte_jobs(klient, org, [job_fuer(lauf, repo, job, None) for repo, lauf, job, _ in org_jobs] if modus == "org" else meine, speicher, jetzt, modus)
        ergebnis["letzteJobs"] = list(speicher.get("letzte") or [])
        _sicht(klient, org, ergebnis, wartend, org_jobs, meine, not org_modus, namen[0] if namen else None, speicher, runde, jetzt, not luecken)
        if not mein:
            # erweiterte Suche erst jetzt (#151): Läufe und Jobs der Runde sind gelesen, ein langsamer Server
            # kostet die Runde nicht mehr
            ergebnis["runner"], mein = suche.ergebnis(suche.erweitert())
        ergebnis["letzterErfolg"] = jetzt
    except ForgejoFehler as fehler:
        ergebnis["abfrage"] = "keine-rechte" if fehler.art == "fehlt" else fehler.art
        ergebnis["fehler"] = str(fehler)
        if fehler.ursache:
            ergebnis["ursache"] = fehler.ursache
    except (TypeError, ValueError, AttributeError, OverflowError, KeyError, IndexError, RecursionError):
        # Fremde Antwort in unerwarteter Form: Runde als Fehler, nie abstürzen oder Halbes zeigen –
        # der Sammler behält den letzten guten Stand
        ergebnis.update(abfrage="fehler", fehler="unerwartete Antwort des Servers", repos=[], job=None, laufende=[], wartende=[],
                        runner={"zustand": "unbekannt"}, letzteJobs=list(speicher.get("letzte") or []))
    ergebnis["anfragen"] = dict(klient.zaehler)
    if ergebnis["job"]:
        ergebnis["job"] = {k: v for k, v in ergebnis["job"].items() if not k.startswith("_")}
    return ergebnis


def _wer(wert: str) -> str:
    """UUIDs ohne Rücksicht auf Groß-/Kleinschreibung vergleichen, Namen genau."""
    return erkennung.pruefe_uuid(wert) or wert


def _jobs_des_laufs(klient: Klient, org: str, repo: str, lauf_id: int, runde: dict) -> list[dict]:
    """Job-Liste eines Laufs, je Runde einmal gelesen (``runde`` ist der Zwischenspeicher dieser Runde, #171)."""
    schluessel = ("jobs", repo, lauf_id)
    if schluessel not in runde:
        runde[schluessel] = liste_aus(klient.hole(f"/repos/{q(org)}/{q(repo)}/actions/runs/{lauf_id}/jobs").daten, "jobs")
    return runde[schluessel]


def _meine_jobs(klient: Klient, org: str, laufend: list[tuple[dict, dict]], ich: set[str], speicher: dict,
                runde: dict | None = None) -> list[dict]:
    """Laufende Jobs dieses Runners. Gitea nennt ``runner_name``; bei Forgejo steht der Runner nur in der
    ersten Log-Zeile – je Job (und Versuch) einmal gelesen und gemerkt."""
    runde = {} if runde is None else runde
    wer_je_job = speicher.setdefault("wer", {})
    gesehen: set[str] = set()
    meine: list[dict] = []
    for repo, lauf in laufend[:20]:
        for job in _jobs_des_laufs(klient, org, repo["name"], ganzzahl(lauf["id"]), runde):
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


MAX_ENDEN_ORG = 3  # im Organisations-Modus (#171) höchstens so viele Ergebnisse beendeter Jobs je Runde nachfragen


def _letzte_jobs(klient: Klient, org: str, meine: list[dict], speicher: dict, jetzt: float, modus: str = "eigen") -> None:
    """Jobs, die dieser Runner in der vorigen Runde hatte und jetzt nicht mehr: Ergebnis und Ende holen
    und vorn in ``letzte`` (höchstens 5) eintragen. Jobs, die zwischen zwei Runden (30 s) begannen und
    endeten, sieht der Monitor nicht. Ist das Ergebnis (noch) nicht zu bekommen, wird es bis zu einer
    Stunde lang erneut versucht und sonst nicht eingetragen – nie ein geratenes Ergebnis."""
    org_modus = modus == "org"
    jetzt_ids = {j["_id"] for j in meine if j.get("_id")}
    # Wechselt der Modus (z. B. der Runner wird erkannt), gehören die gemerkten Jobs nicht mehr zu diesem Runner: verwerfen,
    # nie fremde Jobs als „Letzte Jobs“ des Runners eintragen
    vorher: dict = (speicher.get("laufend") or {}) if speicher.get("laufendModus", "eigen") == modus else {}
    speicher["laufendModus"] = modus
    letzte: list = speicher.setdefault("letzte", [])
    bleibt: dict = {}
    offen = {k: v for k, v in vorher.items() if str(k).isdigit() and isinstance(v, dict) and int(k) not in jetzt_ids}
    fragen = 0
    still = False  # Zeitüberschreitung oder 429 im Organisations-Modus: den Rest in der nächsten Runde
    try:
        with klient.begrenze(SUCHE_RESERVE) if org_modus else contextlib.nullcontext():
            for jid, j in list(offen.items()):
                if org_modus and (still or fragen >= MAX_ENDEN_ORG):
                    continue  # bleibt in ``offen`` und damit gemerkt
                offen.pop(jid)
                fragen += 1
                try:
                    ergebnis, ende = _job_am_ende(klient, org, int(jid), j)
                except ForgejoFehler as fehler:
                    offen[jid] = j  # Ergebnis nicht zu bekommen: gemerkt, nächste Runde wieder
                    if not org_modus:
                        raise
                    still = still or fehler.art in ("nicht-erreichbar", "kontingent")
                    continue
                if ergebnis is None:
                    if jetzt - (j.get("gesehen") or jetzt) < 3600:
                        bleibt[jid] = j
                    continue
                ende = ende or jetzt
                start = j.get("start")
                eintrag = {"name": j["name"], "ergebnis": ergebnis, "dauer": ende - start if isinstance(start, (int, float)) else None,
                           "ende": ende, "repo": j["repo"], "workflow": j["workflow"]}
                if eintrag not in letzte:
                    letzte.insert(0, eintrag)
    finally:
        # auch bei einem Fehler: nichts doppelt eintragen, nichts verlieren
        bleibt.update(offen)
        del letzte[MAX_LETZTE:]
        bleibt.update({str(j["_id"]): {"name": j["name"], "repo": j["repo"], "workflow": j["workflow"], "start": j["start"],
                                       "lauf": j.get("_lauf"), "gesehen": jetzt}
                       for j in meine if j.get("_id")})
        speicher["laufend"] = dict(list(bleibt.items())[:20])


# ---------------------------------------------------------------- Laufende und wartende Jobs, Vergleichsdauern (#171)


class _Budget(Exception):
    """Die Anfragen dieser Runde für Vergleichsdauern sind aufgebraucht; der Rest folgt in der nächsten."""


def _sicht(klient: Klient, org: str, ergebnis: dict, wartend: list[dict], org_jobs: list[tuple[dict, dict, dict, int]], meine: list[dict],
           ich_bekannt: bool, eigener_name: str | None, speicher: dict, runde: dict, jetzt: float, vollstaendig: bool = True) -> None:
    """Trägt ``wartende`` (mit Position) und ``laufende`` (mit Schritt und Vergleichsdauern) ins Ergebnis ein, dazu die
    Vergleichsdauern des eigenen Jobs. Die Position gilt nur, wenn alle Repositories lesbar waren und keine Lauf-Liste
    abgeschnitten wurde (Gitea ohne Statusfilter: nur die 30 neuesten Läufe)."""
    ergebnis["wartende"] = jobsicht.positionen(wartend, vollstaendig and not ergebnis["laeufeNichtLesbar"])
    laufende = _laufende(klient, org, org_jobs, meine, ich_bekannt, eigener_name, speicher, runde, jetzt)
    if ergebnis["job"]:
        ergebnis["job"]["vergleich"] = next((e["vergleich"] for e in laufende if e["eigener"] and e["_id"] == ergebnis["job"].get("_id")), None)
    ergebnis["laufende"] = [{k: v for k, v in e.items() if not k.startswith("_")} for e in laufende]


def _org_jobs(klient: Klient, org: str, laufend: list[tuple[dict, dict]], runde: dict) -> list[tuple[dict, dict, dict, int]]:
    """Laufende Jobs der Organisation ``(repo, lauf, job, Zahl der Jobs im Lauf)`` aus den Job-Listen der ersten
    :data:`MAX_LAUFENDE_LAEUFE` laufenden Läufe (je Runde einmal gelesen, auch für ``_meine_jobs``). Freiwillig:
    endet früh vor der Rundenfrist, ein Fehler bei einem Lauf lässt nur diesen aus; Zeitüberschreitung und 429
    beenden das Lesen still – für die Runde zählt nur, was ``_meine_jobs`` schon gelesen hat."""
    jobs: list[tuple[dict, dict, dict, int]] = []
    with klient.begrenze(SUCHE_RESERVE):
        for repo, lauf in laufend[:MAX_LAUFENDE_LAEUFE]:
            try:
                liste = _jobs_des_laufs(klient, org, repo["name"], ganzzahl(lauf["id"]), runde)
            except ForgejoFehler as fehler:
                if fehler.art in ("nicht-erreichbar", "kontingent"):
                    break
                continue
            jobs.extend((repo, lauf, job, len(liste)) for job in liste if ganzzahl(job.get("id")) and status(job) in LAEUFT)
    return jobs


def _laufende(klient: Klient, org: str, org_jobs: list[tuple[dict, dict, dict, int]], meine: list[dict], ich_bekannt: bool,
              eigener_name: str | None, speicher: dict, runde: dict, jetzt: float) -> list[dict]:
    """Laufende Jobs für die Karte „Jobs je Repository“: zuerst die dieses Runners (Schritte kennt ``_meine_jobs``),
    dann die übrigen der Organisation – deren Schritte nur für höchstens :data:`MAX_SCHRITT_JOBS` Jobs je Runde
    (``/actions/jobs/{id}``). Dazu je Job die Vergleichsdauern (:func:`_vergleich`). Alles Freiwillige läuft nur mit
    genug Rest der Runde und in :meth:`Klient.begrenze`; Zeitüberschreitung und 429 beenden es still."""
    eigene = {j["_id"] for j in meine if j.get("_id")}
    # (Eintrag, Zahl der Jobs des Laufs oder None)
    eintraege: list[tuple[dict, int | None]] = [
        ({**j, "eigener": True, "runner": eigener_name}, len(runde[("jobs", j["repo"], j.get("_lauf"))]) if ("jobs", j["repo"], j.get("_lauf")) in runde else None)
        for j in meine]
    voll = _rest(klient) >= SICHT_MIN_REST
    schritt_budget = MAX_SCHRITT_JOBS
    with klient.begrenze(SUCHE_RESERVE):
        for repo, lauf, job, anzahl in org_jobs:
            if ganzzahl(job.get("id")) in eigene:
                continue
            schritte, details = None, job
            if voll and schritt_budget > 0:
                schritt_budget -= 1
                try:
                    schritte, details = job_details(klient, org, repo["name"], job)
                except ForgejoFehler as fehler:
                    voll = fehler.art not in ("nicht-erreichbar", "kontingent")
            eintraege.append(({**job_fuer(lauf, repo, details, schritte), "eigener": False if ich_bekannt else None, "runner": None}, anzahl))
        ergebnis: list[dict] = []
        # das Budget der Vergleichsanfragen zählt ab hier, nicht schon vor den Schritt-Anfragen (S5)
        runde["grenze"] = getattr(klient, "zaehler", {}).get("anfragen", 0) + VERGLEICH_ANFRAGEN
        for e, anzahl in eintraege[:jobsicht.MAX_LAUFENDE]:
            vg = _vergleich(klient, org, e, anzahl == 1, speicher, runde, jetzt) if voll else _gemerkt(speicher, e)
            ergebnis.append({**{k: e.get(k) for k in ("repo", "privat", "workflow", "name", "ref", "runner", "eigener", "start", "schritt")},
                             "vergleich": vg, "_id": e.get("_id")})
    return ergebnis


def _gemerkt(speicher: dict, e: dict) -> dict | None:
    """Vergleichsdauern aus dem Speicher, ohne Anfrage."""
    alt = (speicher.get("vergleich") or {}).get(f"{e['repo']}|{e['workflow']}|{e['name']}")
    return jobsicht.vergleich(_neueste(alt["dauern"])) if isinstance(alt, dict) and isinstance(alt.get("dauern"), dict) else None


def _neueste(dauern: dict) -> list:
    """Dauern der letzten Läufe, neueste (höchste Lauf-ID) zuerst."""
    return [d for _, d in sorted(((int(k), d) for k, d in dauern.items() if str(k).isdigit()), reverse=True)]


def _vergleich(klient: Klient, org: str, e: dict, einzeln: bool, speicher: dict, runde: dict, jetzt: float) -> dict | None:
    """Median der Dauern der letzten 5 erfolgreichen Läufe desselben Workflows und Jobs (:func:`jobsicht.vergleich`).
    Die Dauern je Lauf werden im Speicher gemerkt (ein beendeter Lauf ändert sich nie) und höchstens alle
    :data:`VERGLEICH_TAKT` Sekunden erneuert; je Runde höchstens :data:`VERGLEICH_ANFRAGEN` Anfragen. ``einzeln``: Der
    Lauf hat nur diesen einen Job – dann genügt die Laufzeit der früheren Läufe aus der Lauf-Liste, ohne weitere Anfrage."""
    if not (e["repo"] and e["workflow"] and e["name"]):
        return None
    cache = speicher.setdefault("vergleich", {})
    schluessel = f"{e['repo']}|{e['workflow']}|{e['name']}"
    eintrag = cache.get(schluessel)
    if not isinstance(eintrag, dict) or not isinstance(eintrag.get("dauern"), dict):
        eintrag = cache[schluessel] = {"dauern": {}, "geprueft": 0}
    if jetzt - (eintrag.get("geprueft") or 0) >= VERGLEICH_TAKT and runde.get("vergleich_online", True):
        try:
            _vergleich_erneuern(klient, org, e, einzeln, eintrag, runde)
            eintrag["geprueft"] = jetzt
        except _Budget:
            pass  # Rest in der nächsten Runde; „geprueft“ bleibt alt, die gemerkten Dauern gelten schon
        except ForgejoFehler as fehler:
            if fehler.art in ("nicht-erreichbar", "kontingent"):
                runde["vergleich_online"] = False  # nur freiwillig: keine weiteren Anfragen dieser Runde, kein Fehler
    for alt in sorted(cache, key=lambda k: cache[k].get("geprueft") or 0)[:max(0, len(cache) - MAX_VERGLEICHE)]:
        del cache[alt]
    return jobsicht.vergleich(_neueste(eintrag["dauern"]))


def _anfrage_erlaubt(klient: Klient, runde: dict) -> None:
    if getattr(klient, "zaehler", {}).get("anfragen", 0) >= runde.get("grenze", 0):
        raise _Budget


def _vergleich_erneuern(klient: Klient, org: str, e: dict, einzeln: bool, eintrag: dict, runde: dict) -> None:
    repo = e["repo"]
    erfolg = runde.get(("erfolg", repo))
    if erfolg is None:
        _anfrage_erlaubt(klient, runde)
        daten = klient.hole(f"/repos/{q(org)}/{q(repo)}/actions/runs", {"status": "success", "page": 1, "limit": VERGLEICH_LAEUFE}).daten
        erfolg = runde[("erfolg", repo)] = [lauf for lauf in liste_aus(daten, "workflow_runs") if erfolgreich(lauf) and ganzzahl(lauf.get("id"))]
    gleiche = sorted((lauf for lauf in erfolg if workflow_aus(lauf) == e["workflow"]), key=lambda lauf: -ganzzahl(lauf["id"]))[:jobsicht.VERGLEICH_ANZAHL]
    dauern = eintrag["dauern"]
    for k in set(dauern) - {str(ganzzahl(lauf["id"])) for lauf in gleiche}:
        del dauern[k]  # nicht mehr unter den letzten 5
    for lauf in gleiche:
        k = str(ganzzahl(lauf["id"]))
        if k in dauern:
            continue
        if einzeln:
            sekunden = lauf_dauer(lauf)
        else:
            sekunden = _job_dauer_im_lauf(klient, org, repo, lauf, e["name"], runde)
        dauern[k] = sekunden or 0  # 0 = nicht zu ermitteln: wird nicht noch einmal gefragt und zählt nicht


def _job_dauer_im_lauf(klient: Klient, org: str, repo: str, lauf: dict, name: str, runde: dict) -> float | None:
    lauf_id = ganzzahl(lauf["id"])
    if ("jobs", repo, lauf_id) not in runde:
        _anfrage_erlaubt(klient, runde)
    try:
        job = next((j for j in _jobs_des_laufs(klient, org, repo, lauf_id, runde) if text(j.get("name")) == name), None)
        if job is None:
            return None
        sekunden = job_dauer(job, None)
        if sekunden:
            return sekunden
        _anfrage_erlaubt(klient, runde)
        schritte, details = job_details(klient, org, repo, job)
        return job_dauer(details, schritte)
    except ForgejoFehler as fehler:
        if fehler.art in ("fehlt", "keine-rechte", "fehler"):
            return None  # dieser Lauf liefert keine Dauer (gelöscht, keine Rechte, ungültige Antwort): nicht erneut fragen
        raise


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
        """Name beim Dienst (von Hand aus runner.json, #172, sonst aus ``.runner``) und UUID aus ``.runner``
        (#145), dann Anzeigename aus der Konfiguration und Unit-Name (Ersatznamen, nur in der eigenen Liste)."""
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
