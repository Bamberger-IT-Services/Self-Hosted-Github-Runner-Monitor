"""HTTP-Server: Seiten, Server-Sent Events und die wenigen Aktionen (Anmeldung, Einrichtung, Update).

Nur Standardbibliothek. Jede Antwort trägt die Sicherheits-Header aus Anweisung 04, jede
ändernde Anfrage (POST) wird gegen den ``Origin``-Kopf geprüft (CSRF), Sitzungen laufen über
ein ``HttpOnly``-Cookie mit ``SameSite=Strict``.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import re
import secrets
import threading
import time
import uuid
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import VERSION, github, zugang
from .konfig import Konfig
from .zustand import Zustand, lies_json

LOG = logging.getLogger("runner_monitor")
COOKIE = "rm_sitzung"
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


class App:
    """Alles, was die Anfragen gemeinsam brauchen."""

    def __init__(self, konfig: Konfig, zustand: Zustand | None = None) -> None:
        self.k = konfig
        self.zustand = zustand or Zustand(konfig)
        self.zugang = zugang.Zugang(konfig.zugang_datei, konfig.sitzungen_datei, konfig.sperren_datei)
        self.einrichtung: dict[str, float] = {}  # Token → gültig bis (nur im Speicher)
        self.sperre = threading.Lock()
        self.statisch = {p.name: p for p in konfig.web_verz.iterdir() if STATISCH.match(p.name)} if konfig.web_verz.is_dir() else {}

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

    def _fehler(self, status: int, text: str) -> None:
        fehler_id = uuid.uuid4().hex[:8]
        LOG.info("Fehler %s %s: %s %s", fehler_id, status, self.command, self.path)
        self._json(status, {"fehler": text, "fehlerId": fehler_id})

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
        if not herkunft or urlsplit(herkunft).netloc != host:
            self._fehler(HTTPStatus.FORBIDDEN, "Anfrage abgelehnt (Herkunft)")
            return None
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            self._fehler(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Erwartet JSON")
            return None
        try:
            laenge = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            laenge = -1
        if not 0 <= laenge <= MAX_KOERPER:
            self._fehler(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Anfrage zu groß")
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

    def _sitzungs_cookie(self, wert: str, max_alter: int | None) -> str:
        teile = [f"{COOKIE}={wert}", "Path=/", "HttpOnly", "SameSite=Strict"]
        if max_alter is not None:
            teile.append(f"Max-Age={max_alter}")
        return "; ".join(teile)

    # ------------------------------------------------------------ GET

    def do_GET(self) -> None:  # noqa: N802 – Name der Basisklasse
        pfad = urlsplit(self.path).path
        app = self.app
        if pfad == "/api/health":
            self._json(HTTPStatus.OK, {"ok": True, "version": VERSION})
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
        self._kopf(HTTPStatus.OK, "text/event-stream; charset=utf-8", None, {"X-Accel-Buffering": "no", "Connection": "close"})
        z = self.app.zustand
        q = z.verteiler.anmelden()
        try:
            for bereich, daten in z.momentaufnahme():
                self._sse(bereich, json.dumps(daten, ensure_ascii=False, separators=(",", ":")))
            while True:
                try:
                    bereich, text = q.get(timeout=15)
                except Exception:  # noqa: BLE001 – queue.Empty
                    self.wfile.write(b": lebt\n\n")
                    self.wfile.flush()
                    continue
                self._sse(bereich, text)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            z.verteiler.abmelden(q)

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
        neueste = (lies_json(app.k.lauf_verz / "release.json", {}) or {}).get("version", "")
        if not neueste or github.vergleiche(neueste, VERSION) <= 0:
            self._fehler(HTTPStatus.CONFLICT, "Keine neuere Version verfügbar.")
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
                cookie = f"{COOKIE_EINRICHTUNG}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={zugang.CODE_GUELTIG}"
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
        ergebnisse.append({"ok": True, "text": "Token gültig" + (", läuft ab am " + time.strftime("%d.%m.%Y", time.localtime(ablauf)) if ablauf else ", ohne Ablaufdatum"), "ablauf": ablauf})
        ergebnisse.append({"ok": True, "text": f"Organisation {org} gefunden, {anzahl}{'+' if anzahl == 100 else ''} Repositories"})
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
            "token-ungueltig": "Token ungültig oder abgelaufen.",
            "keine-rechte": f"Organisation {org} nicht gefunden oder kein Zugriff.",
            "nicht-erreichbar": "GitHub ist von der VM aus nicht erreichbar.",
            "kontingent": "API-Kontingent erschöpft, bitte später erneut prüfen.",
        }
        return {"ok": False, "ergebnisse": [{"fehler": True, "text": texte.get(fehler.art, str(fehler))}]}


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
        handler._json(HTTPStatus.OK, {"ok": True}, {"Set-Cookie": f"{COOKIE_EINRICHTUNG}=; Path=/; Max-Age=0"})  # noqa: SLF001
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
