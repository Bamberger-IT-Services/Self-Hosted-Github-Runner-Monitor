"""Journal je Unit fürs Live-Log (Design 0.8.0 › „Nicht verfügbar“ ehrlich zeigen, #95).

Runner ohne eigene Schrittausgabe (Grundüberwachung, „teilweise“) zeigen im Live-Log das Journal
ihrer systemd-Unit. Je Unit läuft höchstens ein ``journalctl --follow`` – egal, wie viele Fenster
zusehen – und nur, solange jemand zusieht. Ein Fenster bekommt beim Verbinden die letzten Zeilen
(``PUFFER``), danach jede neue Zeile als Ereignis ``journal`` in seinem Live-Strom (``/events``).

Grenzen (S-JOURNAL-01, Sicherheitsbericht):

* Unit-Name nur nach :func:`erkennung.pruefe_unit` und nur aus ``runner[]`` des Servers, nie aus der
  Anfrage (die nennt nur die Runner-ID). Aufruf ohne Shell, Unit als ``--unit=<name>``.
* höchstens ``MAX_FOLGER`` Units gleichzeitig, je Zeile höchstens ``MAX_ZEILE`` Zeichen, je Rohzeile von
  journalctl höchstens ``MAX_ROH`` Bytes (längere werden verworfen), je Nachricht höchstens ``STAPEL``
  Zeilen (der Rest einer Flut wird als Lücke gezählt, nicht verschickt).
* Prozess beenden: ``terminate()``, nach ``ENDE_FRIST`` Sekunden ``kill()``; endet journalctl von selbst,
  startet der Folger nach ``NEUSTART_PAUSE`` Sekunden neu – ab dem letzten Cursor, ohne Doppelte.
* Bekannte Token-Muster werden vor dem Versand ersetzt (wie ``web/mail.js``). Das ist ein Schutz gegen
  Versehen, keine Garantie – deshalb gibt es das Journal nur für angemeldete Benutzer.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import select
import subprocess
import threading
import time
from collections import deque
from typing import Callable

from . import erkennung, runner

LOG = logging.getLogger("runner_monitor")

MAX_FOLGER = 4        # gleichzeitig verfolgte Units (je Unit ein journalctl)
RUECKBLICK = 200      # Zeilen beim ersten Start (--lines)
PUFFER = 200          # so viele Zeilen bekommt ein neu verbundenes Fenster (Review #117: kleiner Anfangsstand)
MAX_ZEILE = 4000      # Zeichen je Zeile (wie das Seiten-Log des GitHub-Runners)
MAX_ROH = 64 * 1024   # Bytes je Rohzeile (JSON) von journalctl
STAPEL = 200          # höchstens so viele Zeilen je Nachricht; mehr in einem Takt = Lücke
TAKT = 0.3            # Sekunden: so lange werden Zeilen gesammelt, bevor sie verschickt werden
ENDE_FRIST = 2.0      # Sekunden zwischen terminate() und kill()
NEUSTART_PAUSE = 5.0  # Sekunden, bevor ein von selbst beendetes journalctl neu startet
MAX_EREIGNISSE = 20   # Dienst gestartet/gestoppt aus dem Journal
FELDER = "MESSAGE,SYSLOG_IDENTIFIER,_PID,_COMM,__REALTIME_TIMESTAMP"
ERSATZ = "***"        # wie GitHub maskierte Geheimnisse; Log-Ausgabe wird nicht übersetzt

# Gängige Tokens (GitHub, GitLab, 40 Hex-Zeichen wie bei Forgejo/Gitea) und Authorization-Köpfe.
TOKEN = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|gl(?:pat|rt|cbt|dt|ptt|ft|oas)-[A-Za-z0-9_-]{16,})"
    r"|\b[0-9a-fA-F]{40}\b")
KOPF = re.compile(r"(?i)\b(authorization\s*[:=]\s*(?:bearer|token|basic)?\s*)[^\s\"']+")
STEUERZEICHEN = re.compile(r"[\x00-\x08\x0b-\x1a\x1c-\x1f\x7f]")  # ohne \t, \n, ESC (Farben)
KENNUNG = re.compile(r"[A-Za-z0-9_.@:+-]{1,64}")
CURSOR = re.compile(r"[A-Za-z0-9=;_.-]{1,512}")


def bereinige(text: str) -> str:
    """Tokens ersetzen, Steuerzeichen (außer Farben) entfernen, auf MAX_ZEILE kürzen."""
    text = STEUERZEICHEN.sub("", text.replace("\r", ""))
    text = KOPF.sub(lambda m: m.group(1) + ERSATZ, text)
    text = TOKEN.sub(ERSATZ, text)
    return text[:MAX_ZEILE]


def befehl(unit: str, cursor: str | None = None) -> list[str]:
    """Aufruf von journalctl – ohne Shell, Unit nur nach Prüfung (sonst ValueError)."""
    geprueft = erkennung.pruefe_unit(unit)
    if not geprueft:
        raise ValueError(f"ungültige Unit: {unit!r}")
    teile = ["journalctl", f"--unit={geprueft}", "--follow", "--output=json", f"--output-fields={FELDER}",
             "--no-pager", "--quiet"]
    if cursor and CURSOR.fullmatch(cursor):
        teile.append(f"--after-cursor={cursor}")
    else:
        teile.append(f"--lines={RUECKBLICK}")
    return teile


def _text(wert: object) -> str:
    if isinstance(wert, list):  # Nicht-UTF-8 liefert journalctl als Liste von Bytes
        try:
            return bytes(x for x in wert if isinstance(x, int) and 0 <= x < 256).decode("utf-8", "replace")
        except (TypeError, ValueError):
            return ""
    return wert if isinstance(wert, str) else ""


def deute(eintrag: dict) -> tuple[list[dict], dict | None]:
    """Ein Eintrag aus ``journalctl -o json`` → Zeilen ``{zeit, text}`` und ggf. ein Ereignis.

    Zeilen von systemd (Started …/Stopped …) stehen ohne Vorsatz, alle anderen wie im Journal
    als ``kennung[pid]: text``. Mehrzeilige Nachrichten werden zu mehreren Zeilen."""
    try:
        zeit = int(str(eintrag.get("__REALTIME_TIMESTAMP", "0"))) / 1_000_000
    except ValueError:
        zeit = 0.0
    if not 0 < zeit < 32503680000:  # vor dem Jahr 3000
        zeit = time.time()
    nachricht = _text(eintrag.get("MESSAGE"))
    kennung = _text(eintrag.get("SYSLOG_IDENTIFIER")) or _text(eintrag.get("_COMM"))
    kennung = kennung if KENNUNG.fullmatch(kennung) else ""
    pid = _text(eintrag.get("_PID"))
    pid = pid if pid.isdigit() and len(pid) <= 10 else ""
    # Nur echte Meldungen von systemd (PID 1) gelten als Dienst gestartet/gestoppt: _COMM und _PID setzt
    # journald selbst, SYSLOG_IDENTIFIER dagegen der Absender – ein Programm könnte sich sonst als systemd ausgeben.
    systemd = _text(eintrag.get("_COMM")) == "systemd" and pid == "1"
    vorsatz = "" if systemd or not kennung else (f"{kennung}[{pid}]: " if pid else f"{kennung}: ")
    zeilen = [{"zeit": zeit, "text": bereinige(vorsatz + teil)} for teil in nachricht.split("\n")[:50]] if nachricht else []
    ereignis = None
    if systemd:
        e = runner.deute_journalzeile({"MESSAGE": nachricht, "SYSLOG_IDENTIFIER": "systemd", "__REALTIME_TIMESTAMP": str(int(zeit * 1_000_000))})
        if e and e.art in ("dienst-gestartet", "dienst-gestoppt"):
            ereignis = {"zeit": e.zeit, "art": e.art}
    return zeilen, ereignis


def _starte(teile: list[str]) -> subprocess.Popen:  # pragma: no cover – braucht systemd
    return subprocess.Popen(teile, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            close_fds=True, start_new_session=True)


class Folger:
    """Verfolgt das Journal einer Unit und verteilt neue Zeilen an alle angemeldeten Schlangen.

    ``starte(befehl) -> Prozess`` ist austauschbar (Tests: Attrappe mit Pipe). Der Prozess braucht
    ``stdout`` (mit ``fileno()``), ``poll()``, ``terminate()``, ``kill()`` und ``wait(timeout)``."""

    def __init__(self, unit: str, starte: Callable[[list[str]], object] = _starte) -> None:
        befehl(unit)  # prüft die Unit, bevor irgendetwas läuft
        self.unit = unit
        self._starte = starte
        self._sperre = threading.Lock()
        self._schlangen: set = set()
        self.zeilen: deque[dict] = deque(maxlen=PUFFER)
        self.ereignisse: deque[dict] = deque(maxlen=MAX_EREIGNISSE)
        self._neu: list[dict] = []
        self._neu_ereignisse: list[dict] = []
        self._luecke = 0
        self._rest = b""
        self._verwerfen = False  # Rohzeile zu lang: bis zum nächsten Zeilenende überspringen
        self.cursor: str | None = None
        self.prozess = None
        self._halt = threading.Event()
        self._faden: threading.Thread | None = None
        self.starts = 0

    # ------------------------------------------------------------ Anmelden (unter der Sperre)

    def nachricht(self, neu: bool = False) -> dict:
        if neu:
            return {"unit": self.unit, "neu": True, "zeilen": list(self.zeilen), "ereignisse": list(self.ereignisse)}
        return {"unit": self.unit, "zeilen": [], "ereignisse": []}

    def anmelden(self, q) -> None:
        """Erst der Stand (``neu``), dann jede neue Zeile – ohne Lücke dazwischen."""
        with self._sperre:
            if self._sende(q, json.dumps(self.nachricht(neu=True), ensure_ascii=False, separators=(",", ":"))):
                self._schlangen.add(q)

    @staticmethod
    def _sende(q, text: str) -> bool:
        """In eine Schlange legen; ist sie voll, wie im Verteiler leeren und den Strom beenden (ENDE)."""
        from .zustand import ENDE  # noqa: PLC0415 – vermeidet einen Kreisimport
        try:
            q.put_nowait(("journal", text))
            return True
        except queue.Full:
            with q.mutex:
                q.queue.clear()
            q.put_nowait(ENDE)
            return False

    def abmelden(self, q) -> int:
        with self._sperre:
            self._schlangen.discard(q)
            return len(self._schlangen)

    # ------------------------------------------------------------ Lesen (reine Logik, testbar)

    def verarbeite(self, roh: bytes) -> None:
        """Ein Stück Ausgabe von journalctl: in Zeilen teilen, zu lange Rohzeilen verwerfen."""
        daten = self._rest + roh
        teile = daten.split(b"\n")
        self._rest = teile.pop()
        for teil in teile:
            if self._verwerfen:
                self._verwerfen = False  # das Ende der zu langen Zeile
                continue
            if len(teil) > MAX_ROH:
                self._luecke += 1
                continue
            self._zeile(teil)
        if len(self._rest) > MAX_ROH:
            self._rest = b""
            if not self._verwerfen:
                self._luecke += 1
            self._verwerfen = True

    def _zeile(self, teil: bytes) -> None:
        if not teil.strip():
            return
        try:
            eintrag = json.loads(teil.decode("utf-8", "replace"))
        except ValueError:
            return
        if not isinstance(eintrag, dict):
            return
        c = eintrag.get("__CURSOR")
        if isinstance(c, str) and CURSOR.fullmatch(c):
            self.cursor = c
        zeilen, ereignis = deute(eintrag)
        self._neu.extend(zeilen)
        if len(self._neu) > STAPEL:  # Flut: zwischen zwei Takten wächst der Speicher nicht (Review #117)
            self._luecke += len(self._neu) - STAPEL
            del self._neu[:-STAPEL]
        if ereignis:
            self._neu_ereignisse.append(ereignis)

    def leere(self) -> dict | None:
        """Gesammelte Zeilen verschicken (höchstens STAPEL, ältere einer Flut als Lücke)."""
        with self._sperre:
            if not self._neu and not self._neu_ereignisse and not self._luecke:
                return None
            if len(self._neu) > STAPEL:
                self._luecke += len(self._neu) - STAPEL
                self._neu = self._neu[-STAPEL:]
            zeilen = ([{"zeit": (self._neu[0]["zeit"] if self._neu else time.time()), "art": "luecke", "n": self._luecke}]
                      if self._luecke else []) + self._neu
            ereignisse = self._neu_ereignisse
            self._neu, self._neu_ereignisse, self._luecke = [], [], 0
            self.zeilen.extend(zeilen)
            self.ereignisse.extend(ereignisse)
            daten = {"unit": self.unit, "zeilen": zeilen, "ereignisse": ereignisse}
            text = json.dumps(daten, ensure_ascii=False, separators=(",", ":"))
            for q in list(self._schlangen):
                if not self._sende(q, text):
                    self._schlangen.discard(q)
            return daten

    # ------------------------------------------------------------ Faden und Prozess

    def start(self) -> None:
        self._faden = threading.Thread(target=self._lauf, name=f"journal-{self.unit}", daemon=True)
        self._faden.start()

    def _lauf(self) -> None:
        gemeldet = False
        while not self._halt.is_set():
            try:
                self.prozess = self._starte(befehl(self.unit, self.cursor))
                self.starts += 1
                self._lies(self.prozess)
            except OSError as fehler:
                if not gemeldet:  # nur einmal je Folger, nicht alle NEUSTART_PAUSE Sekunden
                    LOG.warning("Journal von %s nicht lesbar: %s", self.unit, fehler)
                gemeldet = True
            except Exception:  # noqa: BLE001 – ein Fehler darf das Mitlesen nie dauerhaft beenden
                LOG.exception("Journal von %s: unerwarteter Fehler", self.unit)
            finally:
                self._beende_prozess()
                self.leere()
            self._halt.wait(NEUSTART_PAUSE)

    def _lies(self, prozess) -> None:
        """Lesen, bis journalctl endet. Verschickt wird höchstens einmal je TAKT – auch bei einer Flut, in
        der select() sofort zurückkehrt (Review #117); das letzte Stück verschickt _lauf() nach dem Ende."""
        fd = prozess.stdout.fileno()
        geleert = time.monotonic()
        while not self._halt.is_set():
            bereit, _, _ = select.select([fd], [], [], TAKT)
            if bereit:
                stueck = os.read(fd, MAX_ROH)
                if not stueck:
                    return  # journalctl beendet
                self.verarbeite(stueck)
            if time.monotonic() - geleert >= TAKT:
                self.leere()
                geleert = time.monotonic()

    def _beende_prozess(self) -> None:
        p, self.prozess = self.prozess, None
        if p is None:
            return
        try:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=ENDE_FRIST)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=ENDE_FRIST)
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            p.stdout.close()
        except (OSError, AttributeError):
            pass

    def beenden(self) -> None:
        """Faden anhalten und journalctl beenden. Hier nur terminate(); Warten, kill() und Schließen der
        Pipe übernimmt der Lesefaden selbst (nach höchstens TAKT), damit kein fremder Faden die Pipe
        schließt, während er noch liest."""
        self._halt.set()
        p = self.prozess
        try:
            if p is not None and p.poll() is None:
                p.terminate()
        except (OSError, subprocess.SubprocessError):
            pass
        if self._faden and self._faden is not threading.current_thread():
            self._faden.join(timeout=2 * ENDE_FRIST + TAKT + 1)


class Journale:
    """Ein Folger je Unit, geteilt von allen Fenstern; endet mit dem letzten Fenster."""

    def __init__(self, starte: Callable[[list[str]], object] = _starte, max_folger: int = MAX_FOLGER) -> None:
        self._starte = starte
        self.max_folger = max_folger
        self._folger: dict[str, Folger] = {}
        self._sperre = threading.Lock()

    def anmelden(self, unit: str | None, q) -> Folger | None:
        """None, wenn die Unit ungültig ist oder schon MAX_FOLGER Units verfolgt werden."""
        geprueft = erkennung.pruefe_unit(unit)
        if not geprueft:
            return None
        with self._sperre:
            f = self._folger.get(geprueft)
            if f is None:
                if len(self._folger) >= self.max_folger:
                    return None
                f = Folger(geprueft, self._starte)
                self._folger[geprueft] = f
                f.start()
            f.anmelden(q)
        return f

    def abmelden(self, f: Folger | None, q) -> None:
        if f is None:
            return
        with self._sperre:
            rest = f.abmelden(q)
            if rest == 0 and self._folger.get(f.unit) is f:
                del self._folger[f.unit]
            else:
                return
        f.beenden()  # außerhalb der Sperre: wartet bis zu ENDE_FRIST

    @property
    def anzahl(self) -> int:
        return len(self._folger)
