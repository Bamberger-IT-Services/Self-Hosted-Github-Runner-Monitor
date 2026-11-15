"""Job-Log laufender Forgejo-/Gitea-Jobs im Live-Log (#176): vom Sammler (root) zum Webdienst und Browser.

Das Token kann nur root lesen – also liest der **Sammler** das Job-Log beim Dienst
(:mod:`runner_monitor.anbieter.forgejo_log`), der Webdienst bekommt nur Log-Zeilen. Der Weg ist derselbe
wie bei allen Ergebnissen des Sammlers, nur in beide Richtungen eng begrenzt:

* **Bedarf** (Webdienst → Sammler): Solange ein Browser das Live-Log eines angebundenen Forgejo-/Gitea-Runners
  offen hat, legt der Webdienst höchstens alle ``BEDARF_TAKT`` Sekunden den Auftrag
  ``/var/lib/runner-monitor/auftraege/joblog-bedarf`` (``{"zeit", "runner": [IDs]}``) ab. Der Sammler holt ihn
  ab (umbenennen, streng lesen, löschen), prüft die IDs gegen seine Anbindungen und liest nur für sie –
  höchstens ``BEDARF_GUELTIG`` Sekunden nach dem letzten Auftrag (seine eigene Uhr), höchstens
  ``MAX_FOLGER`` Runner zugleich, je Runner nur den einen Job, den die Abfrage (30-s-Runde) ihm zuordnet.
* **Zeilen** (Sammler → Webdienst): ``/run/runner-monitor/joblog.json`` – je Runner der Stand des Lesers
  (Zeilen mit fortlaufender Nummer, Schritt, aktiv, Hinweis). **0640, Gruppe runner-monitor** (nicht 0644
  wie die übrigen Ergebnisse): Job-Logs privater Repositories sollen andere Benutzer der VM nicht lesen.
  Der Webdienst liest die Datei bei Änderung streng (regulär, ohne Symlink, begrenzt), prüft jede Zeile
  noch einmal und schickt nur neue Zeilen als Ereignis ``joblog`` an die Fenster, die genau diesen
  Runner zeigen (``/events?journal=<id>``).

Ohne Rechte oder auf älteren Servern liest der Sammler nicht weiter und meldet einen Hinweis
(``runner[].jobLog.hinweis``, Info › Verbindungen); das Live-Log bleibt still beim Journal.
"""

from __future__ import annotations

import grp
import json
import logging
import os
import queue
import tempfile
import threading
import time
from pathlib import Path

from . import einrichtung, erkennung
from .anbieter import forgejo as fj
from .anbieter import forgejo_log as fl
from .anbieter.token import pruefe_id

LOG = logging.getLogger("runner_monitor.joblog")

AUFTRAG = "joblog-bedarf"
DATEI = "joblog.json"
GRUPPE = "runner-monitor"     # Gruppe des Webdienstes (einrichten.sh: NUTZER)
BEDARF_TAKT = 10.0            # Webdienst: Auftrag höchstens so oft erneuern
BEDARF_GUELTIG = 30.0         # Sammler: so lange gilt ein Bedarf ohne neuen Auftrag
MAX_FOLGER = 2                # so viele Runner liest der Sammler höchstens zugleich
MAX_AUFTRAG = 4096
MAX_DATEI = 4 * 1024 * 1024   # joblog.json (Webdienst liest höchstens so viel)
MAX_IDS = 8
PAUSE_RECHTE = 3600.0         # 401/403 auf das Log: eine Stunde nicht wieder versuchen
PAUSE_FEHLER = 600.0          # unerwartete Antwort
PAUSE_KONTINGENT = 60.0
PAUSE_ERREICHBAR = 15.0
MAX_UNERREICHBAR = 4          # danach endet das Lesen (neuer Versuch mit dem nächsten Bedarf)
LEBENSZEICHEN = 20.0          # Sammler: joblog.json auch ohne Änderung so oft neu schreiben, solange er liest
VERALTET = 60.0               # Webdienst: ältere Datei (Sammler steht) → kein Job-Log mehr als „aktiv“ zeigen
HINWEISE = ("keine-rechte", "nicht-unterstuetzt", "zu-gross")


# ---------------------------------------------------------------- Datei (Sammler schreibt, Webdienst liest)


def schreibe_fuer_monitor(pfad: Path, daten: object, gruppe: str = GRUPPE) -> None:
    """Atomar schreiben: als root 0640 mit der Gruppe des Webdienstes, sonst (Entwicklung, Tests) 0640 für
    den eigenen Benutzer. Fehlt die Gruppe, 0600 – der Webdienst sieht dann kein Job-Log (sicherer Ausfall)."""
    pfad.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=pfad.parent, prefix=".tmp-joblog-")
    try:
        modus = 0o640
        if os.geteuid() == 0:
            try:
                os.fchown(fd, 0, grp.getgrnam(gruppe).gr_gid)
            except KeyError:
                modus = 0o600
        os.fchmod(fd, modus)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(daten, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, pfad)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def datei_kennung(pfad: Path | None) -> tuple | None:
    """(Inode, mtime in ns, Größe) ohne Symlink zu folgen; None, wenn die Datei fehlt."""
    if pfad is None:
        return None
    try:
        st = os.lstat(pfad)
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


# ---------------------------------------------------------------- Sammler (root)


class _Lauf:
    def __init__(self, rid: str, jid: int, folger: fl.LogFolger) -> None:
        self.rid, self.jid, self.folger = rid, jid, folger
        self.halt = threading.Event()
        self.faden: threading.Thread | None = None
        self.fertig = False  # Faden zu Ende (Job beendet, Fehler)
        self.stand = folger.stand()  # Abzug nach jedem Takt (der Faden ändert den Leser ohne Sperre)


class Verwaltung:
    """Im Sammler: Bedarf abholen, je Runner höchstens einen Leser (eigener Faden) starten und beenden,
    ``joblog.json`` schreiben. ``takt`` blockiert nie (Netz nur in den Fäden)."""

    def __init__(self, lauf_verz: Path, auftraege_verz: Path, klient=fl.LogKlient, gruppe: str = GRUPPE) -> None:
        self.datei = Path(lauf_verz) / DATEI
        self.auftraege = Path(auftraege_verz)
        self._klient = klient
        self._gruppe = gruppe
        self._sperre = threading.Lock()
        self._schreib_sperre = threading.Lock()
        self._bedarf: dict[str, float] = {}       # Runner → Bedarf bis (monoton)
        self._laeufe: dict[str, _Lauf] = {}
        self._erledigt: dict[str, int] = {}       # Runner → Job, der zu Ende gelesen ist (nicht neu starten)
        self._pause: dict[str, float] = {}        # Runner → nicht vor (monoton)
        self._hinweis: dict[str, str] = {}        # Runner → Hinweis für Info
        self._pause_token: dict[str, tuple | None] = {}  # Runner → Token-Datei bei 401/403 (neues Token hebt die Pause auf)
        self._geschrieben: object = None
        self._geschrieben_um = float("-inf")
        self._alle: list[_Lauf] = []  # auch angehaltene Leser, bis ihr Faden endet (für beenden)
        self._erster = True  # nach dem Start einmal schreiben: ein Stand vom vorigen Lauf gilt nicht mehr

    # ------------------------------------------------------------ Bedarf

    def lies_bedarf(self, mono: float) -> None:
        auftrag = einrichtung.lies_einfachen_auftrag(self.auftraege, AUFTRAG)
        if auftrag is None:
            return
        ids = auftrag.get("runner") if isinstance(auftrag, dict) else None
        for rid in (ids if isinstance(ids, list) else [])[:MAX_IDS]:
            if pruefe_id(rid):
                self._bedarf[rid] = mono + BEDARF_GUELTIG

    def takt(self, mono: float, kandidaten: dict) -> None:
        """``kandidaten``: Runner-ID → (Adapter, Ziel ``{id, repo, art}`` oder None) – nur angebundene Runner
        mit Job-Log-Fähigkeit (Sammler). Startet und beendet Leser; schreibt bei Änderung die Datei."""
        try:
            self.lies_bedarf(mono)
        except OSError as fehler:
            LOG.warning("Auftrag %s nicht gelesen: %s", AUFTRAG, type(fehler).__name__)
        geaendert, self._erster = self._erster, False
        with self._sperre:
            for rid in [r for r, bis in self._bedarf.items() if bis < mono]:
                del self._bedarf[rid]
            for rid in set(self._hinweis) - set(kandidaten):
                del self._hinweis[rid]
                geaendert = True
            for rid, lauf in list(self._laeufe.items()):
                ziel = (kandidaten.get(rid) or (None, None))[1]
                gleich = isinstance(ziel, dict) and fj.ganzzahl(ziel.get("id")) == lauf.jid
                if rid in self._bedarf and gleich:
                    continue
                lauf.halt.set()  # kein Browser mehr, Job gewechselt oder Runner nicht mehr angebunden
                del self._laeufe[rid]
                geaendert = True
            for rid in [r for r in self._erledigt if not self._gleich(kandidaten.get(r), self._erledigt[r])]:
                del self._erledigt[rid]  # anderer Job: wieder lesen dürfen
            for rid, (a, _) in kandidaten.items():
                if rid in self._pause_token and datei_kennung(getattr(a.k, "token_datei", None)) != self._pause_token[rid]:
                    del self._pause_token[rid]  # Token-Datei geändert: die Stunde Pause nach 401/403 gilt nicht mehr
                    self._pause.pop(rid, None)
                    self._erledigt.pop(rid, None)  # auch den Job, an dem es scheiterte, wieder versuchen
            for rid, (a, ziel) in kandidaten.items():
                if len(self._laeufe) >= MAX_FOLGER:
                    break
                if rid in self._laeufe or rid not in self._bedarf or self._pause.get(rid, 0) > mono:
                    continue
                jid = fj.ganzzahl((ziel or {}).get("id")) if isinstance(ziel, dict) else None
                repo = (ziel or {}).get("repo") if isinstance(ziel, dict) else None
                if jid is None or not isinstance(repo, str) or self._erledigt.get(rid) == jid:
                    continue
                try:
                    folger = fl.LogFolger(a.k.org, repo, jid, schritte=(ziel.get("art") == "forgejo"))
                except ValueError:
                    continue
                lauf = _Lauf(rid, jid, folger)
                self._alle = [x for x in self._alle if not x.fertig] + [lauf]
                lauf.faden = threading.Thread(target=self._lauf, args=(lauf, a), name=f"joblog-{rid}"[:60], daemon=True)
                self._laeufe[rid] = lauf
                try:
                    lauf.faden.start()
                except RuntimeError:
                    del self._laeufe[rid]
                    LOG.warning("Job-Log von %s nicht gelesen (kein Faden frei)", rid)
                    break
        # immer: schreibt nur bei Änderung oder als Lebenszeichen (LEBENSZEICHEN), solange ein Leser läuft – auch
        # wenn er selbst gerade wartet (z. B. 60 s nach 429), sonst hielte der Webdienst die Datei für veraltet
        self.schreibe(erzwingen=geaendert)

    @staticmethod
    def _gleich(kandidat, jid: int) -> bool:
        ziel = (kandidat or (None, None))[1]
        return isinstance(ziel, dict) and fj.ganzzahl(ziel.get("id")) == jid

    # ------------------------------------------------------------ Leser (eigener Faden)

    def _lauf(self, lauf: _Lauf, a) -> None:
        token = a.token()
        unerreichbar = 0
        ende_grund = None
        try:
            while not lauf.halt.is_set():
                warte = lauf.folger.pause()
                try:
                    klient = self._klient(a.k.server or "", token, http_erlaubt=a.k.http_erlaubt)
                    lauf.folger.takt(klient)
                    unerreichbar = 0
                    with self._sperre:
                        lauf.stand = lauf.folger.stand()
                        if lauf.folger.gelesen:
                            self._hinweis.pop(lauf.rid, None)  # wieder lesbar (z. B. neues Token)
                except fl.LogFehler as fehler:
                    ende_grund = fehler.art
                    break
                except fj.ForgejoFehler as fehler:
                    if fehler.art in ("token-ungueltig", "keine-rechte"):
                        ende_grund = "keine-rechte"
                        break
                    if fehler.art == "kontingent":
                        warte = PAUSE_KONTINGENT
                    elif fehler.art == "nicht-erreichbar":
                        unerreichbar += 1
                        if unerreichbar >= MAX_UNERREICHBAR:
                            ende_grund = "nicht-erreichbar"
                            break
                        warte = PAUSE_ERREICHBAR
                    else:
                        ende_grund = "fehler"
                        break
                except Exception:  # noqa: BLE001 – ein Fehler beim Lesen darf den Sammler nie aufhalten
                    LOG.exception("Job-Log von %s: unerwarteter Fehler", lauf.rid)
                    ende_grund = "fehler"
                    break
                self.schreibe()
                if not lauf.folger.aktiv:
                    break
                lauf.halt.wait(warte)
        finally:
            self._beendet(lauf, ende_grund, a)

    def _beendet(self, lauf: _Lauf, grund: str | None, a=None) -> None:
        mono = time.monotonic()
        with self._sperre:
            lauf.fertig = True
            if self._laeufe.get(lauf.rid) is lauf:
                del self._laeufe[lauf.rid]  # der Platz wird frei; ein beendeter Job fehlt in der Datei = nicht aktiv
            if lauf.halt.is_set():
                grund = None  # angehalten (kein Browser mehr, Job gewechselt): ein Fehler danach zählt nicht
            if grund == "keine-rechte" and a is not None:
                self._pause_token[lauf.rid] = datei_kennung(getattr(a.k, "token_datei", None))
            if grund in HINWEISE:
                self._hinweis[lauf.rid] = grund
                self._erledigt[lauf.rid] = lauf.jid
            if grund in ("keine-rechte", "nicht-unterstuetzt"):
                self._pause[lauf.rid] = mono + PAUSE_RECHTE
            elif grund == "fehler":
                self._pause[lauf.rid] = mono + PAUSE_FEHLER
            elif grund == "nicht-erreichbar":
                self._pause[lauf.rid] = mono + PAUSE_ERREICHBAR * 4
            elif grund == "weg" or (grund is None and not lauf.folger.aktiv and not lauf.halt.is_set()):
                self._erledigt[lauf.rid] = lauf.jid  # zu Ende gelesen (oder Job weg): diesen Job nicht noch einmal
            if grund == "keine-rechte":
                LOG.info("Job-Log von %s: keine Berechtigung – bleibt beim Journal", lauf.rid)
            elif grund == "nicht-unterstuetzt":
                LOG.info("Job-Log von %s: vom Server nicht unterstützt – bleibt beim Journal", lauf.rid)
        self.schreibe()

    # ------------------------------------------------------------ Datei

    def daten(self) -> dict:
        with self._sperre:
            runner: dict[str, dict] = {}
            for rid, lauf in self._laeufe.items():
                runner[rid] = lauf.stand
            for rid, h in self._hinweis.items():
                runner.setdefault(rid, {"lauf": "", "job": None, "aktiv": False, "schritt": None, "seq": 0, "zeilen": [], "hinweis": h})
        return {"version": 1, "runner": runner}

    def schreibe(self, erzwingen: bool = False) -> None:
        """Stand aller Leser schreiben (bei Änderung, alle ``LEBENSZEICHEN`` Sekunden, solange einer läuft, oder
        ``erzwingen``). Stand bilden und Schreiben unter einer Sperre: Wer zuletzt schreibt, schreibt auch den
        neuesten Stand (ein Leser endet nie mit einem veralteten)."""
        with self._schreib_sperre:
            daten = self.daten()
            if not erzwingen and daten == self._geschrieben \
                    and (not daten["runner"] or time.monotonic() - self._geschrieben_um < LEBENSZEICHEN):
                return
            try:
                schreibe_fuer_monitor(self.datei, {**daten, "zeit": time.time()}, self._gruppe)
                self._geschrieben, self._geschrieben_um = daten, time.monotonic()
            except OSError as fehler:
                LOG.warning("%s nicht geschrieben: %s", DATEI, type(fehler).__name__)

    def beenden(self, warten: float = 0.0) -> None:
        """Alle Leser anhalten; mit ``warten`` auf ihr Ende warten (höchstens so viele Sekunden je Leser). Der Sammler
        ruft es beim Beenden (``Sammler.laufe``); die Fäden sind ohnehin Daemon-Fäden und enden mit dem Prozess."""
        with self._sperre:
            laeufe = list(self._laeufe.values()) + list(self._alle)
            self._laeufe.clear()
        for lauf in laeufe:
            lauf.halt.set()
        for lauf in laeufe:
            if warten and lauf.faden and lauf.faden.is_alive():
                lauf.faden.join(warten)


# ---------------------------------------------------------------- Webdienst (runner-monitor)


def _zahl(wert: object) -> int | None:
    return wert if isinstance(wert, int) and not isinstance(wert, bool) and 0 <= wert < 2**53 else None


def pruefe_zeile(z: object) -> dict | None:
    """Eine Zeile aus joblog.json noch einmal prüfen (der Webdienst traut der Datei nicht blind)."""
    if not isinstance(z, dict) or _zahl(z.get("seq")) is None:
        return None
    zeit = z.get("zeit")
    zeit = float(zeit) if isinstance(zeit, (int, float)) and not isinstance(zeit, bool) and 0 < zeit < 32503680000 else time.time()
    art = z.get("art")
    if art == "schritt":
        nr, von = _zahl(z.get("nr")), _zahl(z.get("von"))
        name = z.get("name") if isinstance(z.get("name"), str) else ""
        return {"seq": z["seq"], "zeit": zeit, "art": "schritt", "nr": nr or 1, "von": von or None, "name": fl.bereinige(name)[:200]}
    if art == "gekuerzt":
        return {"seq": z["seq"], "zeit": zeit, "art": "gekuerzt", "bytes": _zahl(z.get("bytes")) or 0}
    text = z.get("text")
    if not isinstance(text, str):
        return None
    return {"seq": z["seq"], "zeit": zeit, "text": fl.bereinige(text)}


def pruefe_stand(roh: object) -> dict | None:
    if not isinstance(roh, dict):
        return None
    schritt = roh.get("schritt")
    if isinstance(schritt, dict):
        schritt = {"nr": _zahl(schritt.get("nr")) or 1, "von": _zahl(schritt.get("von")),
                   "name": fl.bereinige(schritt.get("name") if isinstance(schritt.get("name"), str) else "")[:200]}
    else:
        schritt = None
    zeilen = [z for z in (pruefe_zeile(z) for z in (roh.get("zeilen") if isinstance(roh.get("zeilen"), list) else [])[-fl.PUFFER:]) if z]
    hinweis = roh.get("hinweis") if roh.get("hinweis") in HINWEISE else None
    lauf = roh.get("lauf") if isinstance(roh.get("lauf"), str) else ""
    return {"lauf": lauf[:64], "job": _zahl(roh.get("job")), "aktiv": roh.get("aktiv") is True and not hinweis,
            "schritt": schritt, "seq": _zahl(roh.get("seq")) or 0, "zeilen": zeilen, "hinweis": hinweis}


def _ohne_seq(zeilen: list[dict]) -> list[dict]:
    return [{k: v for k, v in z.items() if k != "seq"} for z in zeilen]


class JobLogs:
    """Im Webdienst: liest ``joblog.json`` (vom Sammler), verteilt neue Zeilen an die Fenster eines Runners
    und legt den Bedarf als Auftrag ab, solange ein Fenster zusieht."""

    def __init__(self, lauf_verz: Path, auftraege_verz: Path) -> None:
        self.datei = Path(lauf_verz) / DATEI
        self.auftraege = Path(auftraege_verz)
        self._sperre = threading.Lock()
        self._staende: dict[str, dict] = {}
        self._schlangen: dict[str, set] = {}
        self._kennung: tuple | None = None  # (st_ino, st_mtime_ns, st_size) der zuletzt gelesenen Datei
        self._datei_zeit = 0.0  # „zeit“ in joblog.json (Uhr des Sammlers)
        self._bedarf_zeit = float("-inf")
        self._bedarf_ids: tuple = ()

    # ------------------------------------------------------------ Fenster

    def nachricht(self, rid: str, stand: dict | None, neu: bool, zeilen: list[dict] | None = None) -> str:
        s = stand or {}
        daten = {"runner": rid, "neu": neu, "aktiv": bool(s.get("aktiv")), "job": s.get("job"), "schritt": s.get("schritt"),
                 "hinweis": s.get("hinweis"), "zeilen": _ohne_seq((s.get("zeilen") or []) if zeilen is None else zeilen)}
        return json.dumps(daten, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _sende(q, text: str) -> bool:
        from .zustand import ENDE  # noqa: PLC0415 – vermeidet einen Kreisimport
        try:
            q.put_nowait(("joblog", text))
            return True
        except queue.Full:
            with q.mutex:
                q.queue.clear()
            q.put_nowait(ENDE)
            return False

    def anmelden(self, rid: str | None, q) -> None:
        """Erst der Stand (``neu``), dann jede neue Zeile – ohne Lücke dazwischen."""
        if not rid:
            return
        with self._sperre:
            if self._sende(q, self.nachricht(rid, self._staende.get(rid), True)):
                neu = rid not in self._schlangen
                self._schlangen.setdefault(rid, set()).add(q)
                if neu:
                    self._bedarf_zeit = float("-inf")  # gleich melden, nicht erst nach BEDARF_TAKT

    def abmelden(self, rid: str | None, q) -> None:
        if not rid:
            return
        with self._sperre:
            menge = self._schlangen.get(rid)
            if menge is not None:
                menge.discard(q)
                if not menge:
                    del self._schlangen[rid]

    def zuschauer(self) -> list[str]:
        with self._sperre:
            return sorted(self._schlangen)

    def hinweis(self, rid: str) -> str | None:
        with self._sperre:
            return (self._staende.get(rid) or {}).get("hinweis")

    # ------------------------------------------------------------ Takt (Zustand, jede Sekunde)

    def takt(self, mono: float | None = None) -> None:
        mono = time.monotonic() if mono is None else mono
        self.lies()
        self.veraltet()
        self.bedarf(mono)

    def veraltet(self, jetzt: float | None = None) -> None:
        """Schreibt der Sammler nicht mehr (gestoppt, hängt), gilt kein Job-Log mehr als aktiv – das Live-Log
        geht zurück aufs Journal, statt eine stehende Ausgabe als laufend zu zeigen."""
        jetzt = time.time() if jetzt is None else jetzt
        with self._sperre:
            staende = dict(self._staende)
        if abs(jetzt - self._datei_zeit) <= VERALTET or not any(s.get("aktiv") for s in staende.values()):
            return
        self.uebernimm({rid: {**s, "aktiv": False} for rid, s in staende.items()})

    def bedarf(self, mono: float) -> None:
        ids = tuple(self.zuschauer()[:MAX_IDS])
        if not ids or (mono - self._bedarf_zeit < BEDARF_TAKT and ids == self._bedarf_ids):
            return
        self._bedarf_zeit, self._bedarf_ids = mono, ids
        try:
            einrichtung.lege_auftrag_einfach(self.auftraege, AUFTRAG, {"runner": list(ids)})
        except OSError as fehler:
            LOG.warning("Auftrag %s nicht abgelegt: %s", AUFTRAG, type(fehler).__name__)

    def lies(self) -> None:
        # Änderung an Inode, Zeit (ns) und Größe erkennen: der Sammler ersetzt die Datei atomar (neue Inode), eine
        # grobe mtime allein könnte zwei Stände in derselben Zeitspanne nicht unterscheiden
        kennung = datei_kennung(self.datei)
        if kennung == self._kennung:
            return
        self._kennung = kennung
        roh = erkennung.Quelle("/").lies(str(self.datei.absolute()), MAX_DATEI) if kennung is not None else None
        try:
            daten = json.loads(roh.decode("utf-8")) if roh else {}
        except (UnicodeDecodeError, ValueError):
            daten = {}
        runner = daten.get("runner") if isinstance(daten, dict) and isinstance(daten.get("runner"), dict) else {}
        zeit = daten.get("zeit") if isinstance(daten, dict) else None
        self._datei_zeit = float(zeit) if isinstance(zeit, (int, float)) and not isinstance(zeit, bool) else 0.0
        neu: dict[str, dict] = {}
        for rid, roh_stand in list(runner.items())[:MAX_IDS * 2]:
            stand = pruefe_stand(roh_stand) if pruefe_id(rid) else None
            if stand:
                neu[rid] = stand
        self.uebernimm(neu)

    def uebernimm(self, neu: dict[str, dict]) -> None:
        """Neue Stände übernehmen und je Runner nur das Neue verschicken (gleicher Lauf, höhere ``seq``);
        ein anderer Lauf (anderer Job, Sammler neu gestartet) geht als Stand mit ``neu`` hinaus."""
        with self._sperre:
            alt = self._staende
            self._staende = neu
            for rid, schlangen in list(self._schlangen.items()):
                a, n = alt.get(rid), neu.get(rid)
                if a == n:
                    continue
                if n and a and n["lauf"] == a["lauf"] and n["seq"] >= a["seq"]:
                    frisch = [z for z in n["zeilen"] if z["seq"] > a["seq"]]
                    erste = frisch[0]["seq"] if frisch else n["seq"] + 1
                    if erste > a["seq"] + 1:  # dazwischen mehr, als die Datei hält: Lücke
                        frisch.insert(0, {"seq": 0, "zeit": frisch[0]["zeit"] if frisch else time.time(), "art": "luecke",
                                          "n": erste - a["seq"] - 1})
                    text = self.nachricht(rid, n, False, frisch)
                else:
                    text = self.nachricht(rid, n, True)
                for q in list(schlangen):
                    if not self._sende(q, text):
                        schlangen.discard(q)
