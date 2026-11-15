"""Job-Log des laufenden Forgejo-/Gitea-Jobs fürs Live-Log (#176) – nur im Sammler (root, mit Token).

Endpunkt (geprüft an Forgejo 17.0.1, Swagger ``repoGetActionJobLogs``):
``GET /api/v1/repos/{o}/{r}/actions/jobs/{id}/logs`` liefert das Log als ``text/plain``, eine Zeile je
Ausgabezeile mit Zeitstempel davor (``2026-11-15T20:29:41.0510739Z <Text>``), und beachtet ``Range``
(206 mit ``Content-Range: bytes a-b/gesamt``; ab dem Ende 416 mit ``Content-Range: bytes */gesamt``).
``?step=N`` (Forgejo) liefert nur den Ausschnitt eines Schritts – ``N`` ist ``number`` aus
``GET …/actions/jobs/{id}`` (0 = „Set up job“, der letzte = „Complete job“) –, Range gilt dann im
Ausschnitt. Das Log selbst enthält **keine** Schrittmarken (der Runner schickt in den Schritten nur deren
Ausgabe); die Grenzen kommen deshalb aus der Schrittliste und ``?step=``. Gitea (ab 1.24) hat den Endpunkt
ohne ``?step=``: dort das ganze Log ohne Trenner. ``format=ndjson`` und ``q`` schalten Range ab und werden
nicht benutzt.

Grenzen (Sicherheitsbericht S-JOBLOG-01): je Anfrage höchstens ``MAX_ABSCHNITT`` Byte (Range), beim
Einstieg in einen Schritt nur dessen Ende (``MAX_START``, Suffix-Range), je Takt höchstens ``MAX_ANFRAGEN``
Anfragen und ``FRIST`` Sekunden, jede Anfrage ``ZEITLIMIT`` Sekunden (eigener Faden wie ``forgejo.Klient``).
Ignoriert der Server Range (200 statt 206), wird höchstens ``MAX_OHNE_RANGE`` Byte gelesen und nur das
Ende behalten, der Takt wird langsamer (``TAKT_OHNE_RANGE``); größer → Lesen endet („zu-gross“). Liegt der
Leser mehr als ``MAX_RUECKSTAND`` zurück, springt er ans Ende (Lücke statt Rückstau). Zeilen: Zeitstempel
abgetrennt, Steuerzeichen und ANSI-Folgen außer Farben (SGR) entfernt, bekannte Token-Muster ersetzt
(wie das Journal), höchstens ``journal.MAX_ZEILE`` Zeichen.
"""

from __future__ import annotations

import calendar
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass

from .. import journal
from . import forgejo as fj

TAKT = 3.0                     # Sekunden zwischen zwei Takten, solange ein Browser zusieht
TAKT_OHNE_RANGE = 15.0         # Server ignoriert Range: jeder Takt lädt das ganze Log – seltener
TAKT_FEHLT = 10.0              # Log eines Schritts (noch) nicht da (404, Job-Detail vorhanden): kurz pausieren
ZEITLIMIT = 5.0                # harte Frist je Anfrage
FRIST = 10.0                   # harte Frist je Takt (alle Anfragen zusammen)
MAX_ABSCHNITT = 256 * 1024     # Byte je Log-Anfrage
MAX_START = 64 * 1024          # Einstieg in einen Schritt: nur dessen letzte 64 KB
MAX_OHNE_RANGE = 4 * 1024 * 1024
MAX_RUECKSTAND = 1024 * 1024   # mehr Rückstand → ans Ende springen
MAX_ANFRAGEN = 6               # je Takt: Job (Schritte) + bis zu 5 Log-Abschnitte
MAX_REST = 64 * 1024           # unvollständige letzte Zeile höchstens so lang aufheben
PUFFER = 400                   # Zeilen, die ein neu verbundenes Fenster bekommt
MAX_PUFFER_ZEICHEN = 300_000   # und höchstens so viele Zeichen (Größe von joblog.json)
MAX_FEHLT = 3                  # so viele 404 hintereinander auf das Log: Job weg oder Server ohne Endpunkt
MAX_SCHRITTE = 200

INHALT = re.compile(r"bytes (\d{1,15})-(\d{1,15})/(\d{1,15}|\*)")
UNERFUELLBAR = re.compile(r"bytes \*/(\d{1,15})")
ZEIT = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2}) ")
# OSC (Titel, Hyperlinks: ESC ] … BEL bzw. ESC \\) und DCS/SOS/PM/APC (ESC P|X|^|_ … ESC \\) samt Nutzlast;
# eine nicht abgeschlossene Folge bis zum Zeilenende
STRING_FOLGE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\|$)|\x1b[PX^_].*?(?:\x1b\\|$)", re.S)
CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SGR = re.compile(r"\x1b\[[0-9;]*m")
ESC_FREMD = re.compile(r"\x1b(?!\[[0-9;]*m)")
# C1-Steuerzeichen (u. a. 8-Bit-CSI \x9b) und Bidi-Steuerzeichen (Text umdrehen, „Trojan Source“)
C1_BIDI = re.compile("[\x80-\x9f\u202a-\u202e\u2066-\u2069]")
SGR_REST = re.compile(r"\x1b(?:\[[0-9;]*)?$")  # beim Kürzen abgeschnittene Farbfolge am Zeilenende


class LogFehler(Exception):
    """Lesen endet für diesen Job (``art``: zu-gross | nicht-unterstuetzt)."""

    def __init__(self, art: str) -> None:
        super().__init__(art)
        self.art = art


@dataclass
class Stueck:
    """Antwort auf eine Log-Anfrage: ``daten`` beginnen bei Byte ``start``; ``gesamt`` = Länge des Logs bzw.
    des Schritts (None = unbekannt); ``range_ok`` = der Server hat Range beachtet."""

    start: int
    daten: bytes
    gesamt: int | None
    range_ok: bool = True


# ---------------------------------------------------------------- Zeilen (testbar ohne Netz)


def bereinige(text: str) -> str:
    """Wie das Journal (Tokens, Steuerzeichen, Länge), dazu alle Escape-Folgen außer Farben (SGR) entfernen:
    OSC/DCS/SOS/PM/APC samt Nutzlast (Titel, Hyperlinks), andere CSI-Folgen (Cursor, Löschen), einzelne ESC,
    C1- und Bidi-Steuerzeichen; eine beim Kürzen angeschnittene Farbfolge am Ende fällt weg."""
    text = STRING_FOLGE.sub("", text)
    text = CSI.sub(lambda m: m.group(0) if SGR.fullmatch(m.group(0)) else "", text)
    text = ESC_FREMD.sub("", text)
    text = C1_BIDI.sub("", text)
    return SGR_REST.sub("", journal.bereinige(text))


def zeit_aus(text: str) -> tuple[float | None, str]:
    """``2026-11-15T20:29:41.0510739Z Text`` → (Unix-Zeit, ``Text``); ohne Zeitstempel (None, Zeile)."""
    m = ZEIT.match(text)
    if not m:
        return None, text
    j, mo, t, h, mi, s, bruch, zone = m.groups()
    try:
        wert = calendar.timegm((int(j), int(mo), int(t), int(h), int(mi), int(s), 0, 0, 0))
    except (ValueError, OverflowError):
        return None, text
    if bruch:
        wert += int(bruch) / 10 ** len(bruch)
    if zone != "Z":
        vz = 1 if zone[0] == "+" else -1
        wert -= vz * (int(zone[1:3]) * 3600 + int(zone[4:6]) * 60)
    return (wert if 0 < wert < 32503680000 else None), text[m.end():]


def zeile_aus(roh: bytes, jetzt: float | None = None) -> dict:
    zeit, text = zeit_aus(roh.decode("utf-8", "replace"))
    return {"zeit": zeit if zeit is not None else (time.time() if jetzt is None else jetzt), "text": bereinige(text)}


# ---------------------------------------------------------------- Klient


class LogKlient(fj.Klient):
    """``forgejo.Klient`` (nur GET, keine Weiterleitung, Token nur über https bzw. ``http_erlaubt``, harte
    Fristen) mit einer Anfrage für Log-Abschnitte per Range."""

    def __init__(self, server: str, token: str = "", zeitlimit: float = ZEITLIMIT, frist: float = FRIST,
                 oeffner: urllib.request.OpenerDirector | None = None, http_erlaubt: bool = False) -> None:
        super().__init__(server, token, zeitlimit=zeitlimit, frist=frist, oeffner=oeffner, http_erlaubt=http_erlaubt)

    def log(self, pfad: str, parameter: dict | None = None, von: int | None = None) -> Stueck:
        """Ab Byte ``von`` höchstens ``MAX_ABSCHNITT`` Byte; ``von=None``: die letzten ``MAX_START`` Byte."""
        if not self.server:
            raise fj.ForgejoFehler("fehler", "Server fehlt, ist keine gültige Adresse oder nicht https://")
        rest = min(self.zeitlimit, self._ende - time.monotonic())
        if rest <= 0:
            raise fj.ForgejoFehler("nicht-erreichbar", "Frist für die Abfrage überschritten")
        url = f"{self.server}/api/v1{pfad}"
        if parameter:
            url += "?" + urllib.parse.urlencode(parameter)
        bereich = f"bytes=-{MAX_START}" if von is None else f"bytes={von}-{von + MAX_ABSCHNITT - 1}"
        anfrage = urllib.request.Request(url, headers={"Accept": "text/plain", "User-Agent": "runner-monitor", "Range": bereich})
        if self.token:
            anfrage.add_header("Authorization", f"token {self.token}")
        self.zaehler["anfragen"] += 1
        ergebnis: list = []
        frist = time.monotonic() + rest
        faden = threading.Thread(target=self._hole_log, args=(anfrage, frist, von, ergebnis), name="forgejo-log", daemon=True)
        faden.start()
        faden.join(rest)
        if faden.is_alive() or not ergebnis:
            raise fj.ForgejoFehler("nicht-erreichbar", "Zeitüberschreitung (keine vollständige Antwort innerhalb der Frist)")
        art, wert = ergebnis[0]
        if art == "fehler":
            raise wert
        if art == "code":
            self._pruefe_code(wert, pfad)
        return wert

    def _hole_log(self, anfrage, frist: float, von: int | None, ergebnis: list) -> None:
        try:
            try:
                with self._oeffner.open(anfrage, timeout=max(0.1, frist - time.monotonic())) as antwort:
                    kopf = {k.lower(): v for k, v in antwort.headers.items()}
                    code = getattr(antwort, "status", None) or antwort.getcode()
                    if code == 206:
                        ergebnis.append(("ok", _teil(antwort, kopf, frist, von)))
                    elif code == 200:
                        ergebnis.append(("ok", _ganz(antwort, frist)))
                    else:
                        ergebnis.append(("code", code))
            except urllib.error.HTTPError as fehler:
                try:
                    if fehler.code == 416:
                        m = UNERFUELLBAR.fullmatch((fehler.headers.get("Content-Range") or "").strip())
                        if not m:
                            raise fj.ForgejoFehler("fehler", "416 ohne gültigen Content-Range") from None
                        gesamt = int(m.group(1))
                        ergebnis.append(("ok", Stueck(start=gesamt, daten=b"", gesamt=gesamt)))
                    else:
                        ergebnis.append(("code", fehler.code))
                finally:
                    fehler.close()
        except (fj.ForgejoFehler, LogFehler) as fehler:
            ergebnis[:] = [("fehler", fehler)]
        except Exception as fehler:  # noqa: BLE001 – Netz, DNS, TLS, http.client
            grund = getattr(fehler, "reason", None) or type(fehler).__name__
            ergebnis[:] = [("fehler", fj.ForgejoFehler("nicht-erreichbar", f"Server nicht erreichbar ({grund})"))]


def _teil(antwort, kopf: dict, frist: float, von: int | None) -> Stueck:
    """206: genau der angefragte Bereich – nie mehr, als angefragt war."""
    m = INHALT.fullmatch((kopf.get("content-range") or "").strip())
    if not m:
        raise fj.ForgejoFehler("fehler", "206 ohne gültigen Content-Range")
    a, b = int(m.group(1)), int(m.group(2))
    gesamt = None if m.group(3) == "*" else int(m.group(3))
    grenze = MAX_START if von is None else MAX_ABSCHNITT
    if b < a or b - a + 1 > grenze or (gesamt is not None and b >= gesamt) or (von is not None and a != von):
        raise fj.ForgejoFehler("fehler", "Content-Range passt nicht zur Anfrage")
    roh = fj._lies_antwort(antwort, frist, b - a + 1)  # noqa: SLF001 – dieselbe Lese-Grenze wie der Klient
    if len(roh) > b - a + 1:
        raise fj.ForgejoFehler("fehler", "Antwort länger als Content-Range")
    return Stueck(start=a, daten=roh, gesamt=gesamt)


def _ganz(antwort, frist: float) -> Stueck:
    """200: Range nicht beachtet (oder leeres Log) – höchstens ``MAX_OHNE_RANGE`` lesen, nur das Ende behalten."""
    lese = getattr(antwort, "read1", None) or antwort.read
    ende = bytearray()
    gelesen = 0
    while True:
        if time.monotonic() > frist:
            raise fj.ForgejoFehler("nicht-erreichbar", "Antwort zu langsam")
        stueck = lese(65536)
        if not stueck:
            break
        gelesen += len(stueck)
        if gelesen > MAX_OHNE_RANGE:
            raise LogFehler("zu-gross")
        ende += stueck
        if len(ende) > MAX_ABSCHNITT:
            del ende[:len(ende) - MAX_ABSCHNITT]
    return Stueck(start=gelesen - len(ende), daten=bytes(ende), gesamt=gelesen, range_ok=False)


# ---------------------------------------------------------------- Leser eines Jobs


def _nummer(s: dict, i: int) -> int:
    n = s.get("number")
    return n if isinstance(n, int) and not isinstance(n, bool) and 0 <= n < 10_000 else i


class LogFolger:
    """Liest das Log **eines** Jobs Takt für Takt nach. ``schritte``: Forgejo mit ``?step=`` (Trenner
    „Schritt n/m · Name“), sonst (Gitea, Forgejo ohne ``/actions/jobs/{id}``) das ganze Log ohne Trenner.

    Stand für den Monitor (:meth:`stand`): Zeilen mit fortlaufender Nummer ``seq`` (der Monitor schickt nur
    neue; eine Lücke in ``seq`` heißt „ausgelassen“), ``aktiv`` (Job läuft), ``schritt`` und ``hinweis``."""

    def __init__(self, org: str, repo: str, jid: int, schritte: bool = True, lauf: str = "") -> None:
        if not fj.REPO.fullmatch(repo or "") or fj.ganzzahl(jid) is None:
            raise ValueError("ungültiger Job")
        self.basis = f"/repos/{fj.q(org)}/{fj.q(repo)}/actions/jobs/{jid}"
        self.jid = jid
        self.lauf = lauf or f"{jid}-{time.monotonic_ns()}"
        self.mit_schritten = schritte
        self.detail = True        # /actions/jobs/{id} vorhanden (Forgejo ab 17, Gitea)
        self.detail_da = False    # im letzten Takt ein Job-Detail bekommen
        self.fehlt_pause = False  # im letzten Takt 404 aufs Log bei vorhandenem Job-Detail
        self.idx: int | None = None  # Schritt, dessen Ausschnitt gelesen wird (nur mit Schritten)
        self.offset: int | None = None
        self.rest = b""
        self.verwerfen = False    # bis zum nächsten Zeilenende überspringen (nach einem Sprung)
        self.namen: list[str] = []
        self.schritt: dict | None = None
        self.aktiv = True
        self.hinweis: str | None = None
        self.range_ok = True
        self.gelesen = False      # schon einmal ein Log bekommen?
        self.fehlt = 0
        self.seq = 0
        self.puffer: deque[dict] = deque(maxlen=PUFFER)
        self._zeichen = 0
        self.anfragen = 0

    # ------------------------------------------------------------ Ergebnis

    def pause(self) -> float:
        takt = TAKT if self.range_ok else TAKT_OHNE_RANGE
        return max(takt, TAKT_FEHLT) if self.fehlt_pause else takt

    def stand(self) -> dict:
        return {"lauf": self.lauf, "job": self.jid, "aktiv": self.aktiv, "schritt": self.schritt, "seq": self.seq,
                "zeilen": list(self.puffer), "hinweis": self.hinweis}

    def _neu(self, eintrag: dict) -> None:
        self.seq += 1
        eintrag["seq"] = self.seq
        if len(self.puffer) == self.puffer.maxlen:
            self._zeichen -= len(self.puffer[0].get("text") or "")
        self.puffer.append(eintrag)
        self._zeichen += len(eintrag.get("text") or "")
        while self._zeichen > MAX_PUFFER_ZEICHEN and len(self.puffer) > 1:
            self._zeichen -= len(self.puffer.popleft().get("text") or "")

    def _trenner(self) -> None:
        nr = (self.idx or 0) + 1
        self._neu({"zeit": time.time(), "art": "schritt", "nr": nr, "von": len(self.namen),
                   "name": self.namen[self.idx] if self.idx is not None and self.idx < len(self.namen) else ""})

    def _gekuerzt(self, n: int) -> None:
        if n > 0:
            self._neu({"zeit": time.time(), "art": "gekuerzt", "bytes": int(n)})

    # ------------------------------------------------------------ Zeilen

    def zeilen(self, daten: bytes) -> None:
        """Ein Stück Log: in Zeilen teilen; die letzte, unvollständige bleibt bis zum nächsten Stück liegen."""
        if self.verwerfen:
            i = daten.find(b"\n")
            if i < 0:
                return
            daten, self.verwerfen = daten[i + 1:], False
        teile = (self.rest + daten).split(b"\n")
        self.rest = teile.pop()
        for teil in teile:
            self._neu(zeile_aus(teil[:MAX_REST]))
        if len(self.rest) > MAX_REST:
            self._neu(zeile_aus(self.rest[:MAX_REST]))
            self.rest, self.verwerfen = b"", True

    def _abschluss(self) -> None:
        """Ende eines Schritts: eine letzte Zeile ohne Zeilenende ausgeben."""
        if self.rest:
            self._neu(zeile_aus(self.rest))
        self.rest, self.verwerfen = b"", False

    # ------------------------------------------------------------ Takt

    def nimm(self, stueck: Stueck, von: int | None) -> bool:
        """Antwort auf eine Anfrage ab ``von`` einarbeiten; True = es liegt schon mehr bereit."""
        if stueck.range_ok or stueck.gesamt:
            self.range_ok = stueck.range_ok  # ein leeres Log kommt auch bei beachtetem Range als 200 (Go: ServeContent)
        gesamt = stueck.gesamt
        if von is not None and gesamt is not None and gesamt < von:
            # Log kürzer als schon gelesen: neuer Versuch des Jobs – den Ausschnitt neu beginnen
            self.offset, self.rest, self.verwerfen = None, b"", False
            return True
        anfang, daten = stueck.start, stueck.daten
        if von is None or anfang > von:
            # nur das Ende (Einstieg oder Server ohne Range): die erste, angeschnittene Zeile verwerfen
            vorher = 0 if von is None else von
            if anfang > 0:
                i = daten.find(b"\n")
                weg = i + 1 if i >= 0 else len(daten)
                self._gekuerzt(anfang - vorher + weg)
                daten = daten[weg:]
                self.rest, self.verwerfen = b"", False
        elif anfang < von:
            daten = daten[von - anfang:]
        self.offset = anfang + len(stueck.daten)
        self.gelesen = True
        self.zeilen(daten)
        if gesamt is None:
            return False
        if gesamt - self.offset > MAX_RUECKSTAND:
            # zu weit zurück: zum Ende springen, statt Megabytes nachzulesen
            self._gekuerzt(gesamt - MAX_START - self.offset)
            self.offset, self.rest, self.verwerfen = gesamt - MAX_START, b"", True
        return stueck.range_ok and self.offset < gesamt

    def _lies(self, klient: LogKlient, schritt: int | None = None) -> bool:
        """Ab ``offset`` nachlesen – mit ``schritt`` (``number`` laut Server) nur dessen Ausschnitt."""
        parameter = {"step": schritt} if schritt is not None else None
        von = self.offset
        self.anfragen += 1
        try:
            stueck = klient.log(f"{self.basis}/logs", parameter, von)
        except fj.ForgejoFehler as fehler:
            if fehler.art != "fehlt":
                raise
            if self.detail_da:
                # Den Job gibt es (Detail kam eben): Schritt übersprungen oder noch nicht geschrieben – kein Zeichen
                # für einen Server ohne Endpunkt, also still kurz pausieren
                self.fehlt_pause = True
                return False
            self.fehlt += 1  # noch nicht ausgeführt, Job gelöscht, Server ohne Endpunkt
            if self.fehlt >= MAX_FEHLT:
                raise LogFehler("nicht-unterstuetzt" if not self.gelesen else "weg") from None
            return False
        self.fehlt = 0
        return self.nimm(stueck, von)

    def _job(self, klient: LogKlient) -> tuple[list[dict], bool]:
        """Schrittliste und „Job beendet?“ aus ``/actions/jobs/{id}``."""
        self.detail_da = False
        if not self.detail:
            return [], False
        self.anfragen += 1
        try:
            daten = klient.hole(self.basis).daten
        except fj.ForgejoFehler as fehler:
            if fehler.art != "fehlt":
                raise
            if self.mit_schritten:  # bisher Ausschnitte eines Schritts: im ganzen Log neu einsteigen
                self.idx, self.offset, self.rest, self.verwerfen = None, None, b"", False
            self.detail = self.mit_schritten = False  # älterer Server: das ganze Log ohne Trenner
            return [], False
        if not isinstance(daten, dict):
            return [], False
        self.detail_da = True
        zustand = fj.status(daten)
        fertig = zustand in fj.ERLEDIGT or bool(fj.status(daten, "conclusion"))
        schritte = [s for s in (daten.get("steps") if isinstance(daten.get("steps"), list) else []) if isinstance(s, dict)]
        return schritte[:MAX_SCHRITTE], fertig

    def takt(self, klient: LogKlient) -> None:
        """Ein Takt: Schritte lesen, neue Ausgabe nachlesen (höchstens ``MAX_ANFRAGEN`` Anfragen)."""
        self.anfragen, self.fehlt_pause = 0, False
        schritte, fertig = self._job(klient)
        if self.mit_schritten:
            if schritte:
                self._takt_schritte(klient, schritte, fertig)
            elif fertig:
                self.aktiv = False  # beendet, ohne je eine Schrittliste zu liefern (nie ausgeführt)
            return  # noch keine Schritte (Job eben vergeben): nächster Takt
        if schritte:
            self.namen, self.schritt = fj.schritt_aus(schritte)
        mehr = True
        while mehr and self.anfragen < MAX_ANFRAGEN:
            mehr = self._lies(klient)
        if fertig and not mehr:
            self._abschluss()
            self.aktiv = False

    def _takt_schritte(self, klient: LogKlient, schritte: list[dict], fertig: bool) -> None:
        self.namen = [fj.text(s.get("name")) for s in schritte]
        nummern = [_nummer(s, i) for i, s in enumerate(schritte)]
        laufend = next((i for i, s in enumerate(schritte) if fj.status(s) in fj.LAEUFT), None)
        if laufend is None:
            # zwischen zwei Schritten oder beendet: der erste noch nicht erledigte, sonst der letzte
            laufend = next((i for i, s in enumerate(schritte) if fj.status(s) not in fj.ERLEDIGT), len(schritte) - 1)
        ziel = len(schritte) - 1 if fertig else laufend
        self.schritt = {"nr": laufend + 1, "von": len(schritte), "name": self.namen[laufend]}
        if self.idx is None or self.idx > ziel:
            self.idx, self.offset, self.rest, self.verwerfen = ziel, None, b"", False  # Einstieg (oder neuer Versuch)
            self.fehlt = 0
            self._trenner()
        mehr = False
        while self.anfragen < MAX_ANFRAGEN:
            mehr = self._lies(klient, nummern[self.idx])
            if mehr:
                continue
            if self.idx >= ziel:
                break
            self._abschluss()  # Schritt zu Ende (ein späterer läuft schon): weiter zum nächsten
            self.idx, self.offset, self.fehlt = self.idx + 1, None, 0
            self._trenner()
        if fertig and self.idx >= ziel and not mehr:
            self._abschluss()
            self.aktiv = False
