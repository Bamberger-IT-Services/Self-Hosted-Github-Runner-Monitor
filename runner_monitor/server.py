"""HTTP-Server: Seiten, Server-Sent Events und die wenigen Aktionen (Anmeldung, Einrichtung, Update).

Nur Standardbibliothek. Jede Antwort trägt die Sicherheits-Header aus Anweisung 04, jede
ändernde Anfrage (POST) wird gegen den ``Origin``-Kopf geprüft (CSRF), Sitzungen laufen über
ein ``HttpOnly``-Cookie mit ``SameSite=Strict``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import re
import secrets
import socket
import threading
import time
import uuid
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import VERSION, github, zugang
from .konfig import Konfig
from .zustand import ENDE, Zustand, lies_json

LOG = logging.getLogger("runner_monitor")
COOKIE = "rm_sitzung"
SSE_SCHREIB_FRIST = 60  # Sekunden, die ein write() an einen hängenden Browser höchstens blockiert
SSE_JE_SITZUNG = 6  # Live-Verbindungen je Sitzung (S-DOS-01); weitere werden mit 429 abgelehnt
COOKIE_EINRICHTUNG = "rm_einrichtung"
MAX_KOERPER = 16 * 1024

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
       "form-action 'self'; object-src 'none'")
SICHERHEITS_KOPF = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
}
STATISCH = re.compile(r"^[a-z0-9-]+\.(css|js|svg)$")
RUNNER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")  # /events?journal=<runner-id> (#95)


class App:
    """Alles, was die Anfragen gemeinsam brauchen."""

    def __init__(self, konfig: Konfig, zustand: Zustand | None = None) -> None:
        self.k = konfig
        self.zustand = zustand or Zustand(konfig)
        self.zugang = zugang.Zugang(konfig.zugang_datei, konfig.sitzungen_datei, konfig.sperren_datei)
        self.einrichtung: dict[str, float] = {}  # Token → gültig bis (nur im Speicher)
        self.sperre = threading.Lock()
        self.stroeme: dict[str, int] = {}  # Hash der Sitzung → offene Live-Verbindungen
        self.statisch = {p.name: p for p in konfig.web_verz.iterdir() if STATISCH.match(p.name)} if konfig.web_verz.is_dir() else {}

    # Live-Verbindungen je Sitzung (S-DOS-01) ---------------------------

    def strom_an(self, sitzung: str) -> bool:
        """Eine Live-Verbindung mehr – False, wenn die Sitzung schon SSE_JE_SITZUNG offen hat.

        Abgelehnt wird die neue, nicht die älteste Verbindung: sonst würden sich mehrere offene
        Fenster gegenseitig im Wechsel verdrängen.
        """
        with self.sperre:
            n = self.stroeme.get(sitzung, 0)
            if n >= SSE_JE_SITZUNG:
                return False
            self.stroeme[sitzung] = n + 1
            return True

    def strom_ab(self, sitzung: str) -> None:
        with self.sperre:
            n = self.stroeme.get(sitzung, 0) - 1
            if n > 0:
                self.stroeme[sitzung] = n
            else:
                self.stroeme.pop(sitzung, None)

    # Einrichtungs-Sitzung ---------------------------------------------

    def neue_einrichtung(self) -> str:
        token = secrets.token_urlsafe(32)
        with self.sperre:
            jetzt = time.time()
            self.einrichtung = {k: v for k, v in self.einrichtung.items() if v > jetzt}
            self.einrichtung[token] = jetzt + zugang.CODE_GUELTIG
        return token

    def einrichtung_gueltig(self, token: str | None) -> bool:
        with self.sperre:
            return bool(token) and self.einrichtung.get(token or "", 0) > time.time()



def meldung(vorlage: str, **werte: object) -> dict:
    """Text für die Oberfläche: ``text`` (deutsch, eingesetzt) und – mit Platzhaltern – ``vorlage``
    und ``werte``. Die Oberfläche übersetzt über web/i18n.js; der deutsche Text ist der Schlüssel (#81)."""
    if not werte:
        return {"text": vorlage}
    return {"text": vorlage.format(**werte), "vorlage": vorlage, "werte": {k: str(v) for k, v in werte.items()}}

class Handler(BaseHTTPRequestHandler):
    server_version = "runner-monitor"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    app: App  # wird in erstelle_server gesetzt

    # ------------------------------------------------------------ Grundlagen

    def log_message(self, format: str, *args) -> None:  # noqa: A002 – Signatur der Basisklasse
        LOG.debug("%s %s", self.address_string(), format % args)

    def _cookie(self, name: str) -> str | None:
        kopf = self.headers.get("Cookie")
        if not kopf:
            return None
        try:
            keks = SimpleCookie(kopf)
        except Exception:  # noqa: BLE001 – kaputte Cookies wie fehlende behandeln
            return None
        return keks[name].value if name in keks else None

    def _ip(self) -> str:
        return self.client_address[0]

    def _kopf(self, status: int, typ: str, laenge: int | None, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", typ)
        if laenge is not None:
            self.send_header("Content-Length", str(laenge))
        for k, v in SICHERHEITS_KOPF.items():
            self.send_header(k, v)
        if self.app.k.https:
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        for k, v in (extra or {}).items():
            if isinstance(v, list):
                for einzel in v:
                    self.send_header(k, einzel)
            else:
                self.send_header(k, v)
        self.end_headers()

    def _json(self, status: int, daten: object, extra: dict | None = None) -> None:
        roh = json.dumps(daten, ensure_ascii=False).encode("utf-8")
        self._kopf(status, "application/json; charset=utf-8", len(roh), extra)
        self.wfile.write(roh)

    def _weiter(self, ziel: str) -> None:
        self._kopf(HTTPStatus.FOUND, "text/plain; charset=utf-8", 0, {"Location": ziel})

    def _fehler(self, status: int, text: str, schliessen: bool = False, werte: dict | None = None) -> None:
        """Fehler als JSON. ``text`` ist der deutsche Text und zugleich der Schlüssel der Übersetzung
        in web/i18n.js; mit ``werte`` ist er eine Vorlage mit {platzhaltern} (#81)."""
        fehler_id = uuid.uuid4().hex[:8]
        LOG.info("Fehler %s %s: %s %s", fehler_id, status, self.command, getattr(self, "path", ""))
        extra = None
        if schliessen:
            self.close_connection = True
            extra = {"Connection": "close"}
        m = meldung(text, **(werte or {}))
        antwort = {"fehler": m.pop("text"), **m, "fehlerId": fehler_id}
        self._json(status, antwort, extra)

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """Fehler, die schon beim Lesen der Anfrage entstehen (kaputte Anfragezeile, unbekannte Methode):
        als JSON mit denselben Sicherheits-Kopfzeilen wie alle anderen Antworten (ZAP-Baseline, #20)."""
        try:
            text = HTTPStatus(code).phrase
        except ValueError:
            text = "Fehler"
        self._fehler(code, text, schliessen=True)

    def _datei(self, pfad: Path) -> None:
        try:
            roh = pfad.read_bytes()
        except OSError:
            self._fehler(HTTPStatus.NOT_FOUND, "Nicht gefunden")
            return
        typ = mimetypes.guess_type(pfad.name)[0] or "application/octet-stream"
        if typ.startswith("text/") or typ in ("application/javascript", "image/svg+xml"):
            typ += "; charset=utf-8"
        self._kopf(HTTPStatus.OK, typ, len(roh))
        self.wfile.write(roh)

    def _seite(self, name: str) -> None:
        self._datei(self.app.k.web_verz / name)

    def _angemeldet(self) -> bool:
        if self.app.k.entwicklung:
            return True
        return self.app.zugang.pruefe_sitzung(self._cookie(COOKIE))

    def _koerper(self) -> dict | None:
        """JSON-Körper einer POST-Anfrage nach CSRF-Prüfung, sonst None (Antwort ist dann schon raus)."""
        herkunft = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        # Abgelehnt, bevor der Körper gelesen ist: Verbindung schließen, sonst liest der Server den
        # ungelesenen Körper als nächste Anfrage (ZAP-Baseline, #20).
        if not herkunft or urlsplit(herkunft).netloc != host:
            self._fehler(HTTPStatus.FORBIDDEN, "Anfrage abgelehnt (Herkunft)", schliessen=True)
            return None
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            self._fehler(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Erwartet JSON", schliessen=True)
            return None
        try:
            laenge = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            laenge = -1
        if not 0 <= laenge <= MAX_KOERPER:
            self._fehler(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Anfrage zu groß", schliessen=True)
            return None
        try:
            daten = json.loads(self.rfile.read(laenge) or b"{}")
        except ValueError:
            self._fehler(HTTPStatus.BAD_REQUEST, "Ungültiges JSON")
            return None
        if not isinstance(daten, dict):
            self._fehler(HTTPStatus.BAD_REQUEST, "Erwartet ein Objekt")
            return None
        return daten

    def _sicher(self) -> str:
        """Hinter einem TLS-Proxy (MONITOR_HTTPS=1) gehen Cookies nur über HTTPS."""
        return "; Secure" if self.app.k.https else ""

    def _sitzungs_cookie(self, wert: str, max_alter: int | None) -> str:
        teile = [f"{COOKIE}={wert}", "Path=/", "HttpOnly", "SameSite=Strict"] + (["Secure"] if self.app.k.https else [])
        if max_alter is not None:
            teile.append(f"Max-Age={max_alter}")
        return "; ".join(teile)

    # ------------------------------------------------------------ GET

    def do_GET(self) -> None:  # noqa: N802 – Name der Basisklasse
        pfad = urlsplit(self.path).path
        app = self.app
        if pfad == "/api/health":
            # Name der VM für die Anmeldeseite (Design 0.3.0: unter „Runner-Monitor“)
            self._json(HTTPStatus.OK, {"ok": True, "version": VERSION, "vm": app.k.vm_name or socket.gethostname()})
            return
        if pfad.startswith("/static/"):
            name = pfad[len("/static/"):]
            if name in app.statisch:
                self._datei(app.statisch[name])
            else:
                self._fehler(HTTPStatus.NOT_FOUND, "Nicht gefunden")
            return
        eingerichtet = app.k.entwicklung or app.zugang.eingerichtet()
        if pfad == "/einrichtung":
            if eingerichtet:
                self._weiter("/")
            else:
                self._seite("einrichtung.html")
            return
        if not eingerichtet:
            if pfad.startswith("/api/einrichtung/"):
                self._einrichtung_get(pfad)
            else:
                self._weiter("/einrichtung")
            return
        if pfad == "/anmelden":
            if self._angemeldet():
                self._weiter("/")
            else:
                self._seite("anmelden.html")
            return
        if not self._angemeldet():
            if pfad.startswith(("/api/", "/events")):
                self._fehler(HTTPStatus.UNAUTHORIZED, "Nicht angemeldet")
            else:
                self._weiter("/anmelden")
            return
        if pfad in ("/", "/index.html"):
            self._seite("dashboard.html")
        elif pfad == "/events":
            self._ereignisse()
        elif pfad == "/api/sitzung":
            # Das Dashboard fragt hiermit nach einem Verbindungsfehler, ob es noch angemeldet ist (sonst 401).
            self._json(HTTPStatus.OK, {"ok": True})
        elif pfad == "/api/zustand":
            # Momentaufnahme ohne Live-Log (#92, E-19): bisherige Bereiche + vm, runner[], meldungen[].
            self._json(HTTPStatus.OK, app.zustand.zustand_api())
        else:
            self._fehler(HTTPStatus.NOT_FOUND, "Nicht gefunden")

    def _einrichtung_get(self, pfad: str) -> None:
        if pfad == "/api/einrichtung/status":
            pruefung = lies_json(self.app.k.daten_verz / "systempruefung.json", {}) or {}
            self._json(HTTPStatus.OK, {"pruefung": pruefung, "codeGueltig": self.app.einrichtung_gueltig(self._cookie(COOKIE_EINRICHTUNG))})
        else:
            self._fehler(HTTPStatus.NOT_FOUND, "Nicht gefunden")

    def _ereignisse(self) -> None:
        """Server-Sent Events: erst der aktuelle Stand, dann jede Änderung."""
        self.close_connection = True
        sitzung = hashlib.sha256((self._cookie(COOKIE) or "entwicklung").encode()).hexdigest()
        if not self.app.strom_an(sitzung):
            self._fehler(HTTPStatus.TOO_MANY_REQUESTS, "Zu viele Live-Verbindungen für diese Sitzung")
            return
        try:
            self._strom()
        finally:
            self.app.strom_ab(sitzung)

    def _journal_wunsch(self) -> str | None:
        """``/events?journal=<runner-id>``: Runner, dessen Journal dieses Fenster im Live-Log zeigt (#95).
        Nur die ID kommt aus der Anfrage; welche Unit gelesen wird, bestimmt allein ``runner[]`` des Servers."""
        try:
            werte = parse_qs(urlsplit(self.path).query, max_num_fields=4).get("journal") or [""]
        except ValueError:  # mehr als 4 Felder
            return None
        wunsch = werte[0]
        return wunsch if RUNNER_ID.fullmatch(wunsch) else None

    def _strom(self) -> None:
        self._kopf(HTTPStatus.OK, "text/event-stream; charset=utf-8", None, {"X-Accel-Buffering": "no", "Connection": "close"})
        z = self.app.zustand
        # Hängt der Browser (Rechner schläft, WLAN weg), blockiert write() sonst ewig und der Thread bleibt liegen.
        self.connection.settimeout(SSE_SCHREIB_FRIST)
        q = z.verteiler.anmelden()
        wunsch = self._journal_wunsch()
        journal = {"folger": None, "unit": None}

        def journal_abgleich() -> None:
            # Unit aus runner[]; ändert sie sich (Runner neu erkannt, Unit weg), wird umgehängt.
            unit = z.journal_unit(wunsch) if wunsch else None
            if unit == journal["unit"] and (unit is None or journal["folger"] is not None):
                return
            z.journale.abmelden(journal["folger"], q)
            journal["folger"], journal["unit"] = None, unit
            if unit:
                journal["folger"] = z.journale.anmelden(unit, q)
                if journal["folger"] is None:  # schon MAX_FOLGER Units offen
                    self._sse("journal", json.dumps({"unit": unit, "neu": True, "zeilen": [], "ereignisse": [], "hinweis": "grenze"}))
            elif wunsch:
                self._sse("journal", json.dumps({"unit": None, "neu": True, "zeilen": [], "ereignisse": []}))

        try:
            for bereich, daten in z.momentaufnahme():
                self._sse(bereich, json.dumps(daten, ensure_ascii=False, separators=(",", ":")))
            if wunsch:
                journal_abgleich()
            while True:
                try:
                    bereich, text = q.get(timeout=15)
                except Exception:  # noqa: BLE001 – queue.Empty
                    self.wfile.write(b": lebt\n\n")
                    self.wfile.flush()
                    continue
                if (bereich, text) == ENDE:
                    # Schlange lief über (siehe Verteiler): Strom beenden, der Browser verbindet neu.
                    LOG.info("Live-Verbindung beendet: Browser kam nicht hinterher, er verbindet sich neu")
                    return
                self._sse(bereich, text)
                if wunsch and bereich == "runner":
                    journal_abgleich()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            z.verteiler.abmelden(q)
            z.journale.abmelden(journal["folger"], q)

    def _sse(self, bereich: str, text: str) -> None:
        self.wfile.write(f"event: {bereich}\ndata: {text}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _nicht_erlaubt(self) -> None:
        """Alle anderen HTTP-Methoden: 405 (Anweisung 04 › HTTP)."""
        self._fehler(HTTPStatus.METHOD_NOT_ALLOWED, "Methode nicht erlaubt")

    do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = _nicht_erlaubt  # noqa: N815

    # ------------------------------------------------------------ POST

    def do_POST(self) -> None:  # noqa: N802
        pfad = urlsplit(self.path).path
        daten = self._koerper()
        if daten is None:
            return
        app = self.app
        if pfad.startswith(("/api/einrichtung/github/", "/api/einrichtung/fertig")):
            _github_routen(self, pfad, daten)
            return
        if pfad.startswith("/api/einrichtung/"):
            if app.zugang.eingerichtet():
                self._fehler(HTTPStatus.CONFLICT, "Die Einrichtung ist bereits abgeschlossen.")
                return
            self._einrichtung_post(pfad, daten)
            return
        if pfad == "/api/anmelden":
            self._anmelden(daten)
            return
        if pfad == "/api/abmelden":
            app.zugang.abmelden(self._cookie(COOKIE))
            self._json(HTTPStatus.OK, {"ok": True}, {"Set-Cookie": self._sitzungs_cookie("", 0)})
            return
        if not self._angemeldet():
            self._fehler(HTTPStatus.UNAUTHORIZED, "Nicht angemeldet")
            return
        if pfad == "/api/update/starten":
            self._update_starten()
        elif pfad == "/api/update/pruefen":
            # Nur ein Auftrag an den root-Sammler; der fragt GitHub ab (höchstens einmal je Minute).
            zugang._schreibe(app.k.auftraege_verz / "release-pruefen", {"zeit": time.time()})  # noqa: SLF001
            self._json(HTTPStatus.ACCEPTED, {"ok": True})
        elif pfad == "/api/update/auto":
            einst = lies_json(app.k.einstellungen_datei, {}) or {}
            einst["autoUpdate"] = bool(daten.get("an"))
            zugang._schreibe(app.k.einstellungen_datei, einst)  # noqa: SLF001
            self._json(HTTPStatus.OK, {"ok": True, "auto": einst["autoUpdate"]})
        else:
            self._fehler(HTTPStatus.NOT_FOUND, "Nicht gefunden")

    def _anmelden(self, daten: dict) -> None:
        app = self.app
        if not app.zugang.eingerichtet():
            self._fehler(HTTPStatus.CONFLICT, "Noch nicht eingerichtet")
            return
        nutzer = str(daten.get("nutzer", ""))[:100]
        passwort = str(daten.get("passwort", ""))[:zugang.PASSWORT_MAX + 1]
        merken = bool(daten.get("merken"))
        ip = self._ip()
        token = app.zugang.anmelden(nutzer, passwort, ip, merken)
        if token:
            alter = zugang.SITZUNG_LANG if merken else None
            self._json(HTTPStatus.OK, {"ok": True}, {"Set-Cookie": self._sitzungs_cookie(token, alter)})
            return
        bis = app.zugang.gesperrt_bis(ip)
        self._json(HTTPStatus.UNAUTHORIZED, {
            "ok": False,
            "fehler": "Benutzername oder Passwort stimmt nicht.",
            "verbleibend": app.zugang.verbleibend(),
            "gesperrtBis": bis or None,
        })

    def _update_starten(self) -> None:
        app = self.app
        release = lies_json(app.k.lauf_verz / "release.json", {}) or {}
        neueste = release.get("version", "")
        if not neueste or github.vergleiche(neueste, VERSION) <= 0:
            self._fehler(HTTPStatus.CONFLICT, "Keine neuere Version verfügbar.")
            return
        if not (release.get("bereit", True) and release.get("archiv") and release.get("pruefsumme")):
            # Paket hängt noch nicht am Release (#63): gleich neu prüfen lassen statt scheitern
            zugang._schreibe(app.k.auftraege_verz / "release-pruefen", {"zeit": time.time()})  # noqa: SLF001
            self._fehler(HTTPStatus.CONFLICT, "Version {v} wird noch bereitgestellt – bitte in ein bis zwei Minuten erneut versuchen.", werte={"v": neueste})
            return
        status = lies_json(app.k.update_status_datei, {}) or {}
        if status.get("zustand") == "laeuft" and time.time() - status.get("zeit", 0) < 600:
            self._fehler(HTTPStatus.CONFLICT, "Ein Update läuft bereits.")
            return
        # Nur ein Auftrag mit der Zielversion. Was installiert wird, entscheidet der root-Hilfsdienst
        # selbst anhand des offiziellen Releases und seiner Prüfsumme (ADR-0004).
        zugang._schreibe(app.k.auftraege_verz / "update", {"version": neueste, "zeit": time.time()})  # noqa: SLF001
        self._json(HTTPStatus.ACCEPTED, {"ok": True, "version": neueste})

    # ------------------------------------------------------------ Einrichtung

    def _einrichtung_post(self, pfad: str, daten: dict) -> None:
        app = self.app
        if pfad == "/api/einrichtung/code":
            ergebnis = zugang.pruefe_code(app.k.einrichtungscode_datei, str(daten.get("code", ""))[:20])
            if ergebnis == "ok":
                token = app.neue_einrichtung()
                cookie = f"{COOKIE_EINRICHTUNG}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={zugang.CODE_GUELTIG}{self._sicher()}"
                self._json(HTTPStatus.OK, {"ok": True}, {"Set-Cookie": cookie})
            else:
                text = {
                    "falsch": "Der Code stimmt nicht. Bitte genau so eingeben, wie ihn das Skript angezeigt hat.",
                    "abgelaufen": "Der Code ist abgelaufen. Einen neuen Code zeigt auf der VM: sudo ./einrichten.sh code",
                    "fehlt": "Es gibt noch keinen Einrichtungscode. Bitte zuerst auf der VM: sudo ./einrichten.sh",
                }[ergebnis]
                self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "fehler": text})
            return
        if not app.einrichtung_gueltig(self._cookie(COOKIE_EINRICHTUNG)):
            self._fehler(HTTPStatus.UNAUTHORIZED, "Bitte zuerst den Einrichtungscode eingeben.")
            return
        if pfad == "/api/einrichtung/zugang":
            try:
                app.zugang.lege_an(str(daten.get("nutzer", ""))[:64], str(daten.get("passwort", ""))[:zugang.PASSWORT_MAX + 1])
            except zugang.ZugangFehler as fehler:
                self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "fehler": str(fehler)})
                return
            # Zugang ist angelegt – ab hier gilt die Einrichtung als abgeschlossen (eine Sperre gegen
            # einen zweiten Inhaber). GitHub kann im selben Ablauf noch folgen.
            self._json(HTTPStatus.OK, {"ok": True})
            return
        self._fehler(HTTPStatus.NOT_FOUND, "Nicht gefunden")


def github_pruefen(org: str, token: str) -> dict:
    """Prüft ein Token, bevor es gespeichert wird. Gibt eine Liste von Ergebnissen zurück."""
    k = github.Klient(token)
    ergebnisse = []
    try:
        antwort = k.hole(f"/orgs/{org}/repos", {"per_page": 100})
        anzahl = len(antwort.daten) if isinstance(antwort.daten, list) else 0
        ablauf = github.token_ablauf(antwort.kopf.get("github-authentication-token-expiration"))
        gueltig = meldung("Token gültig, läuft ab am {d}", d=time.strftime("%d.%m.%Y", time.localtime(ablauf))) if ablauf else meldung("Token gültig, ohne Ablaufdatum")
        ergebnisse.append({"ok": True, **gueltig, "ablauf": ablauf})
        ergebnisse.append({"ok": True, **meldung("Organisation {org} gefunden, {n} Repositories", org=org, n=f"{anzahl}{'+' if anzahl == 100 else ''}")})
        try:
            if anzahl:
                erstes = antwort.daten[0]["name"]
                k.hole(f"/repos/{org}/{erstes}/actions/runs", {"per_page": 1})
            ergebnisse.append({"ok": True, "text": "Actions und Metadata: lesen"})
        except github.GitHubFehler:
            ergebnisse.append({"warn": True, "text": "Recht „Actions: Read-only“ fehlt – Workflows bleiben leer"})
        try:
            k.hole(f"/orgs/{org}/actions/runners", {"per_page": 1})
            ergebnisse.append({"ok": True, "text": "Self-hosted runners: lesen (Online-Status wird angezeigt)"})
        except github.GitHubFehler:
            ergebnisse.append({"warn": True, "text": "Self-hosted runners fehlt: Online-Status bleibt „unbekannt“ (optional)"})
        return {"ok": True, "ergebnisse": ergebnisse}
    except github.GitHubFehler as fehler:
        texte = {
            "token-ungueltig": meldung("Token ungültig oder abgelaufen."),
            "keine-rechte": meldung("Organisation {org} nicht gefunden oder kein Zugriff.", org=org),
            "nicht-erreichbar": meldung("GitHub ist von der VM aus nicht erreichbar."),
            "kontingent": meldung("API-Kontingent erschöpft, bitte später erneut prüfen."),
        }
        return {"ok": False, "ergebnisse": [{"fehler": True, **texte.get(fehler.art, {"text": str(fehler)})}]}


def _github_routen(handler: Handler, pfad: str, daten: dict) -> bool:
    """GitHub-Schritt der Einrichtung (auch nach angelegtem Zugang, solange die Einrichtung offen ist)."""
    app = handler.app
    erlaubt = app.einrichtung_gueltig(handler._cookie(COOKIE_EINRICHTUNG)) or handler._angemeldet()  # noqa: SLF001
    if pfad not in ("/api/einrichtung/github/pruefen", "/api/einrichtung/github/speichern", "/api/einrichtung/fertig"):
        handler._fehler(HTTPStatus.NOT_FOUND, "Nicht gefunden")  # noqa: SLF001
        return True
    if not erlaubt:
        handler._fehler(HTTPStatus.UNAUTHORIZED, "Bitte zuerst den Einrichtungscode eingeben.")  # noqa: SLF001
        return True
    if pfad == "/api/einrichtung/fertig":
        app.k.einrichtungscode_datei.unlink(missing_ok=True)
        with app.sperre:
            app.einrichtung.clear()
        handler._json(HTTPStatus.OK, {"ok": True}, {"Set-Cookie": f"{COOKIE_EINRICHTUNG}=; Path=/; Max-Age=0{handler._sicher()}"})  # noqa: SLF001
        return True
    org = str(daten.get("org", "")).strip()
    token = str(daten.get("token", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", org) or not re.fullmatch(r"[A-Za-z0-9_]{20,255}", token):
        handler._json(HTTPStatus.BAD_REQUEST, {"ok": False, "ergebnisse": [{"fehler": True, "text": "Organisation oder Token hat ein ungültiges Format."}]})  # noqa: SLF001
        return True
    if pfad == "/api/einrichtung/github/pruefen":
        handler._json(HTTPStatus.OK, github_pruefen(org, token))  # noqa: SLF001
        return True
    # speichern: Token als Auftrag für den root-Sammler ablegen, Organisation in die Einstellungen
    zugang._schreibe(app.k.auftraege_verz / "github-token", {"token": token})  # noqa: SLF001
    einst = lies_json(app.k.einstellungen_datei, {}) or {}
    einst["org"] = org
    zugang._schreibe(app.k.einstellungen_datei, einst)  # noqa: SLF001
    handler._json(HTTPStatus.OK, {"ok": True})  # noqa: SLF001
    return True


def erstelle_server(konfig: Konfig, zustand: Zustand | None = None) -> ThreadingHTTPServer:
    app = App(konfig, zustand)
    handler = type("MonitorHandler", (Handler,), {"app": app})
    server = ThreadingHTTPServer((konfig.adresse, konfig.port), handler)
    server.daemon_threads = True
    server.app = app  # type: ignore[attr-defined]
    return server
