"""Journal je Unit fürs Live-Log (#95): Aufruf, Begrenzungen, Token-Filter, Folger mit Attrappe, Anmeldung,
Neustarts/Letzter Stopp aus systemctl und die Auswahl des Runners nur über runner[] des Servers."""
import http.client
import json
import os
import queue
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from runner_monitor import journal, konfig, runner, server, zustand

WEB = Path(__file__).resolve().parent.parent / "web"


def eintrag(text, ident="buildagent", pid="2187", zeit=1_761_700_000.0, cursor=None, **mehr):
    e = {"MESSAGE": text, "SYSLOG_IDENTIFIER": ident, "_PID": pid, "__REALTIME_TIMESTAMP": str(int(zeit * 1_000_000))}
    if cursor:
        e["__CURSOR"] = cursor
    e.update(mehr)
    return e


def roh(*eintraege) -> bytes:
    return b"".join(json.dumps(e).encode() + b"\n" for e in eintraege)


class Attrappe:
    """Steht für journalctl: eine Pipe, in die der Test schreibt; zählt terminate()/kill()."""

    def __init__(self, befehl):
        self.befehl = befehl
        r, w = os.pipe()
        self.stdout = os.fdopen(r, "rb", buffering=0)
        self._w = w
        self.offen = True
        self.terminiert = 0

    def schreibe(self, daten: bytes) -> None:
        os.write(self._w, daten)

    def ende(self) -> None:  # journalctl endet von selbst
        if self.offen:
            self.offen = False
            os.close(self._w)

    def poll(self):
        return None if self.offen else 0

    def terminate(self):
        self.terminiert += 1
        self.ende()

    def kill(self):
        self.ende()

    def wait(self, timeout=None):  # noqa: ARG002
        return 0


class Fabrik:
    def __init__(self):
        self.prozesse: list[Attrappe] = []
        self.neu = threading.Event()

    def __call__(self, befehl):
        p = Attrappe(befehl)
        self.prozesse.append(p)
        self.neu.set()
        return p


def warte(bedingung, frist=5.0):
    ende = time.monotonic() + frist
    while time.monotonic() < ende:
        if bedingung():
            return True
        time.sleep(0.01)
    return False


def nachrichten(q: queue.Queue) -> list[dict]:
    aus = []
    while True:
        try:
            bereich, text = q.get_nowait()
        except queue.Empty:
            return aus
        if bereich == "journal":
            aus.append(json.loads(text))
        else:
            aus.append({"_bereich": bereich})


# ---------------------------------------------------------------- Aufruf und Deutung


class BefehlTest(unittest.TestCase):
    def test_ohne_shell_mit_gepruefter_unit(self):
        b = journal.befehl("buildagent.service")
        self.assertEqual(b[0], "journalctl")
        self.assertIn("--unit=buildagent.service", b)
        self.assertIn("--follow", b)
        self.assertIn("--output=json", b)
        self.assertIn(f"--lines={journal.RUECKBLICK}", b)
        self.assertNotIn("-u", b)  # Unit nie als eigenes Argument, das mit „-“ beginnen könnte
        self.assertTrue(all(isinstance(t, str) for t in b))

    def test_ungueltige_units(self):
        for unit in ("--help.service", "-x.service", "a b.service", "x;rm -rf.service", "../x.service", "buildagent", "", None, "x" * 300 + ".service"):
            with self.subTest(unit=unit), self.assertRaises(ValueError):
                journal.befehl(unit)

    def test_neustart_ab_cursor(self):
        b = journal.befehl("buildagent.service", "s=abc;i=1f;b=0a;m=12;t=5;x=9")
        self.assertIn("--after-cursor=s=abc;i=1f;b=0a;m=12;t=5;x=9", b)
        self.assertFalse(any(t.startswith("--lines") for t in b))
        b = journal.befehl("buildagent.service", "--boot; rm")  # kaputter Cursor: wie ein erster Start
        self.assertIn(f"--lines={journal.RUECKBLICK}", b)


class DeuteTest(unittest.TestCase):
    def test_programm_und_systemd(self):
        zeilen, e = journal.deute(eintrag("waiting for work"))
        self.assertEqual(zeilen, [{"zeit": 1_761_700_000.0, "text": "buildagent[2187]: waiting for work"}])
        self.assertIsNone(e)
        zeilen, e = journal.deute(eintrag("Started buildagent.service - Build Agent.", ident="systemd", pid="1", _COMM="systemd"))
        self.assertEqual(zeilen[0]["text"], "Started buildagent.service - Build Agent.")
        self.assertEqual(e, {"zeit": 1_761_700_000.0, "art": "dienst-gestartet"})
        _, e = journal.deute(eintrag("Stopped buildagent.service - Build Agent.", ident="systemd", pid="1", _COMM="systemd"))
        self.assertEqual(e["art"], "dienst-gestoppt")
        # „Running job“ eines fremden Dienstes wird nicht zum Job-Ereignis
        _, e = journal.deute(eintrag("Running job: build"))
        self.assertIsNone(e)
        # Ein Programm, das sich als systemd ausgibt (SYSLOG_IDENTIFIER setzt der Absender), bleibt ein Programm
        zeilen, e = journal.deute(eintrag("Stopped buildagent.service", ident="systemd", pid="2187", _COMM="buildagent"))
        self.assertIsNone(e)
        self.assertEqual(zeilen[0]["text"], "systemd[2187]: Stopped buildagent.service")

    def test_bytes_mehrzeilig_steuerzeichen(self):
        zeilen, _ = journal.deute(eintrag(list("Grüße\x07".encode("utf-8")) + [0xFF]))
        self.assertEqual(zeilen[0]["text"], "buildagent[2187]: Grüße�")
        zeilen, _ = journal.deute(eintrag("eins\nzwei\r\n\x1b[32mgrün\x1b[0m"))
        self.assertEqual([z["text"] for z in zeilen], ["buildagent[2187]: eins", "buildagent[2187]: zwei", "buildagent[2187]: \x1b[32mgrün\x1b[0m"])

    def test_laenge_kennung_zeit(self):
        zeilen, _ = journal.deute(eintrag("x" * 10_000))
        self.assertEqual(len(zeilen[0]["text"]), journal.MAX_ZEILE)
        zeilen, _ = journal.deute(eintrag("hallo", ident="<script>", pid="12; rm"))
        self.assertEqual(zeilen[0]["text"], "hallo")  # ungültige Kennung entfällt, nichts Eingeschleustes
        zeilen, _ = journal.deute({"MESSAGE": "ohne Zeit", "__REALTIME_TIMESTAMP": "kaputt"})
        self.assertLess(abs(zeilen[0]["zeit"] - time.time()), 5)
        self.assertEqual(journal.deute({"MESSAGE": None}), ([], None))

    def test_tokens_werden_ersetzt(self):
        geheim = [
            "ghp_" + "A" * 36, "github_pat_" + "B1_" * 10, "glpat-" + "c" * 20, "glrt-" + "D" * 20,
            "0123456789abcdef0123456789abcdef01234567",
        ]
        for g in geheim:
            with self.subTest(g=g[:8]):
                zeilen, _ = journal.deute(eintrag(f"token={g} weiter"))
                self.assertNotIn(g, zeilen[0]["text"])
                self.assertIn(journal.ERSATZ, zeilen[0]["text"])
        zeilen, _ = journal.deute(eintrag("Authorization: Bearer abc.def-123 weiter"))
        self.assertEqual(zeilen[0]["text"], "buildagent[2187]: Authorization: Bearer *** weiter")
        zeilen, _ = journal.deute(eintrag("commit 3f2a9c1 ist kurz"))  # kurze Hashes bleiben
        self.assertIn("3f2a9c1", zeilen[0]["text"])


# ---------------------------------------------------------------- Folger: Lesen, Begrenzen, Verteilen


class FolgerTest(unittest.TestCase):
    def test_ungueltige_unit_startet_nichts(self):
        fabrik = Fabrik()
        with self.assertRaises(ValueError):
            journal.Folger("--help.service", fabrik)
        self.assertEqual(fabrik.prozesse, [])
        j = journal.Journale(starte=fabrik)
        self.assertIsNone(j.anmelden("../etc/passwd", queue.Queue()))
        self.assertIsNone(j.anmelden(None, queue.Queue()))
        self.assertEqual(fabrik.prozesse, [])

    def test_stuecke_ueber_zeilengrenzen(self):
        f = journal.Folger("buildagent.service", Fabrik())
        daten = roh(eintrag("eins", cursor="c1"), eintrag("zwei", cursor="c2"))
        for i in range(0, len(daten), 7):
            f.verarbeite(daten[i:i + 7])
        q = queue.Queue()
        f.anmelden(q)
        d = f.leere()
        self.assertEqual([z["text"] for z in d["zeilen"]], ["buildagent[2187]: eins", "buildagent[2187]: zwei"])
        self.assertEqual(f.cursor, "c2")
        neu, frisch = nachrichten(q)
        self.assertTrue(neu["neu"])
        self.assertEqual(neu["zeilen"], [])
        self.assertEqual(len(frisch["zeilen"]), 2)
        self.assertIsNone(f.leere())  # nichts Neues → nichts verschickt

    def test_zu_lange_rohzeile_wird_verworfen(self):
        f = journal.Folger("buildagent.service", Fabrik())
        lang = json.dumps(eintrag("x" * (journal.MAX_ROH + 10))).encode()
        f.verarbeite(lang[: journal.MAX_ROH // 2])
        f.verarbeite(lang[journal.MAX_ROH // 2:])  # Rest ohne Zeilenende überschreitet MAX_ROH
        f.verarbeite(b"\n" + roh(eintrag("danach")))
        d = f.leere()
        self.assertEqual(d["zeilen"][0], {"zeit": d["zeilen"][0]["zeit"], "art": "luecke", "n": 1})
        self.assertEqual(d["zeilen"][1]["text"], "buildagent[2187]: danach")
        f.verarbeite(lang + b"\n")  # in einem Stück
        self.assertEqual(f.leere()["zeilen"][0]["n"], 1)

    def test_flut_wird_begrenzt(self):
        f = journal.Folger("buildagent.service", Fabrik())
        f.verarbeite(roh(*[eintrag(f"z{i}") for i in range(journal.STAPEL + 50)]))
        d = f.leere()
        self.assertEqual(len(d["zeilen"]), journal.STAPEL + 1)
        self.assertEqual(d["zeilen"][0]["art"], "luecke")
        self.assertEqual(d["zeilen"][0]["n"], 50)
        self.assertEqual(d["zeilen"][-1]["text"], f"buildagent[2187]: z{journal.STAPEL + 49}")
        for _ in range(5):
            f.verarbeite(roh(*[eintrag("x") for _ in range(journal.STAPEL)]))
            f.leere()
        self.assertEqual(len(f.zeilen), journal.PUFFER)  # neu verbundene Fenster bekommen höchstens PUFFER Zeilen

    def test_volle_schlange_beendet_den_strom(self):
        f = journal.Folger("buildagent.service", Fabrik())
        q = queue.Queue(maxsize=1)
        f.anmelden(q)  # Stand füllt die Schlange
        f.verarbeite(roh(eintrag("zu viel")))
        f.leere()
        self.assertEqual(q.get_nowait(), zustand.ENDE)
        self.assertEqual(f.abmelden(q), 0)

    def test_mit_attrappe_lesen_und_beenden(self):
        fabrik = Fabrik()
        j = journal.Journale(starte=fabrik)
        q1, q2 = queue.Queue(), queue.Queue()
        f = j.anmelden("buildagent.service", q1)
        self.assertTrue(fabrik.neu.wait(5))
        self.assertIs(j.anmelden("buildagent.service", q2), f)  # ein journalctl je Unit
        self.assertEqual(len(fabrik.prozesse), 1)
        p = fabrik.prozesse[0]
        self.assertIn("--unit=buildagent.service", p.befehl)
        p.schreibe(roh(eintrag("Started buildagent.service - Build Agent.", ident="systemd", pid="1", _COMM="systemd"), eintrag("heartbeat ok")))
        self.assertTrue(warte(lambda: len(f.zeilen) == 2))
        for q in (q1, q2):
            self.assertTrue(warte(lambda q=q: q.qsize() >= 2))
            alle = nachrichten(q)
            self.assertTrue(alle[0]["neu"])
            self.assertEqual([z["text"] for z in alle[1]["zeilen"]], ["Started buildagent.service - Build Agent.", "buildagent[2187]: heartbeat ok"])
            self.assertEqual(alle[1]["ereignisse"][0]["art"], "dienst-gestartet")
        # wer später kommt, bekommt den Stand
        q3 = queue.Queue()
        j.anmelden("buildagent.service", q3)
        self.assertEqual(len(nachrichten(q3)[0]["zeilen"]), 2)
        j.abmelden(f, q1)
        j.abmelden(f, q3)
        self.assertEqual(p.terminiert, 0)  # q2 sieht noch zu
        j.abmelden(f, q2)
        self.assertEqual(p.terminiert, 1)  # letztes Fenster zu → journalctl beendet
        self.assertFalse(f._faden.is_alive())  # noqa: SLF001
        self.assertEqual(j.anzahl, 0)

    def test_neustart_nach_ende_ab_cursor(self):
        fabrik = Fabrik()
        with mock.patch.object(journal, "NEUSTART_PAUSE", 0.05):
            j = journal.Journale(starte=fabrik)
            q = queue.Queue()
            f = j.anmelden("buildagent.service", q)
            self.assertTrue(warte(lambda: len(fabrik.prozesse) == 1))
            fabrik.prozesse[0].schreibe(roh(eintrag("eins", cursor="s=1;i=2")))
            self.assertTrue(warte(lambda: f.cursor == "s=1;i=2"))
            fabrik.prozesse[0].ende()
            self.assertTrue(warte(lambda: len(fabrik.prozesse) == 2))
            self.assertIn("--after-cursor=s=1;i=2", fabrik.prozesse[1].befehl)  # keine doppelten Zeilen
            j.abmelden(f, q)
        self.assertFalse(f._faden.is_alive())  # noqa: SLF001

    def test_grenze_der_units(self):
        fabrik = Fabrik()
        j = journal.Journale(starte=fabrik, max_folger=2)
        q = queue.Queue()
        a = j.anmelden("a.service", q)
        b = j.anmelden("b.service", q)
        self.assertIsNone(j.anmelden("c.service", q))
        j.abmelden(a, q)
        c = j.anmelden("c.service", q)
        self.assertIsNotNone(c)
        j.abmelden(b, q)
        j.abmelden(c, q)
        self.assertEqual(j.anzahl, 0)

    def test_journalctl_fehlt(self):
        def fehlt(_befehl):
            raise FileNotFoundError("journalctl")
        with mock.patch.object(journal, "NEUSTART_PAUSE", 0.05), self.assertLogs("runner_monitor", "WARNING") as log:
            j = journal.Journale(starte=fehlt)
            q = queue.Queue()
            f = j.anmelden("buildagent.service", q)
            time.sleep(0.3)
            j.abmelden(f, q)
        self.assertEqual(len(log.records), 1)  # einmal gemeldet, nicht bei jedem Versuch


# ---------------------------------------------------------------- systemctl: Neustarts, Letzter Stopp


AKTIV_SEIT = datetime(2026, 10, 25, 0, 31, 13, tzinfo=timezone.utc).timestamp()
GESTOPPT = datetime(2026, 10, 24, 16, 35, 54, tzinfo=timezone.utc).timestamp()


class DienstStatusTest(unittest.TestCase):
    def status(self, ausgabe):
        lauf = mock.Mock(stdout=ausgabe)
        with mock.patch.object(runner.subprocess, "run", return_value=lauf) as aufruf:
            st = runner.dienst_status("buildagent.service")
        self.assertIn("NRestarts", aufruf.call_args[0][0][4])
        return st

    def test_aktiv_mit_neustarts_und_stopp(self):
        st = self.status("ActiveState=active\nActiveEnterTimestamp=Sun 2026-10-25 00:31:13 UTC\n"
                         "InactiveEnterTimestamp=Sat 2026-10-24 16:35:54 UTC\nResult=success\nNRestarts=3\n")
        self.assertEqual(st["zustand"], "aktiv")
        self.assertEqual(st["neustarts"], 3)
        self.assertEqual(st["seit"], AKTIV_SEIT)
        self.assertEqual(st["letzterStopp"], GESTOPPT)

    def test_nie_gestoppt_und_kaputte_werte(self):
        st = self.status("ActiveState=active\nActiveEnterTimestamp=Sun 2026-10-25 00:31:13 UTC\nInactiveEnterTimestamp=\nNRestarts=0\n")
        self.assertEqual((st["neustarts"], st["letzterStopp"]), (0, None))
        st = self.status("ActiveState=active\nNRestarts=-1\n")
        self.assertIsNone(st["neustarts"])
        st = self.status("ActiveState=active\nNRestarts=99999999999\n")
        self.assertIsNone(st["neustarts"])

    def test_gestoppt_seit_ist_letzter_stopp(self):
        st = self.status("ActiveState=failed\nInactiveEnterTimestamp=Sat 2026-10-24 16:35:54 UTC\nResult=exit-code\nNRestarts=5\n")
        self.assertEqual((st["zustand"], st["seit"], st["letzterStopp"], st["grund"], st["neustarts"]),
                         ("gestoppt", GESTOPPT, GESTOPPT, "exit-code", 5))


# ---------------------------------------------------------------- Server: /events?journal=<runner-id>


def zu(c, r):
    """Antwort und Verbindung schließen – die Antwort hält den Socket sonst offen."""
    r.close()
    c.close()


GRUND = {"status": True, "jobs": False, "schritte": False, "logs": True, "updates": False}
VOLL = {"status": True, "jobs": True, "schritte": True, "logs": True, "updates": False}


def runner_eintrag(rid, faehig, log):
    return {"id": rid, "name": rid, "dienst": "unbekannt", "faehig": faehig, "log": log, "status": {"zustand": "aktiv"}}


class ServerJournalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "lauf").mkdir()
        self.k = konfig.lade(datei=d / "fehlt.env", umgebung={
            "MONITOR_ADRESSE": "127.0.0.1", "MONITOR_PORT": "1", "MONITOR_DATEN_VERZ": str(d / "daten"),
            "MONITOR_LAUF_VERZ": str(d / "lauf"), "MONITOR_WEB_VERZ": str(WEB)})
        self.app = server.App(self.k)
        self.fabrik = Fabrik()
        self.app.zustand.journale = journal.Journale(starte=self.fabrik)
        self.app.zustand._setze("runner", [  # noqa: SLF001
            runner_eintrag("runner-vm-01", VOLL, {"art": "seiten", "unit": "actions.runner.beispiel-org.runner-vm-01.service"}),
            runner_eintrag("buildagent", GRUND, {"art": "journal", "unit": "buildagent.service"}),
            runner_eintrag("ohne-logs", {**GRUND, "logs": False}, {"art": "journal", "unit": "geheim.service"}),
            runner_eintrag("datei", GRUND, {"art": "datei", "unit": "datei.service"}),
        ])
        self.srv = server.ThreadingHTTPServer(("127.0.0.1", 0), type("H", (server.Handler,), {"app": self.app}))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.app.zugang.lege_an("verwaltung", "Pferd-Batterie-Heftklammer-42")
        self.cookie = f"{server.COOKIE}=" + self.app.zugang.anmelden("verwaltung", "Pferd-Batterie-Heftklammer-42", "127.0.0.1", False)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def strom(self, pfad, cookie=True):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=5)
        c.request("GET", pfad, headers={"Cookie": self.cookie} if cookie else {})
        return c, c.getresponse()

    @staticmethod
    def lies_bis(r, bereich, frist=5.0):
        """SSE lesen, bis ein Ereignis ``bereich`` kommt; liefert dessen Daten (oder None)."""
        ende = time.monotonic() + frist
        aktuell = None
        while time.monotonic() < ende:
            zeile = r.fp.readline().decode("utf-8").rstrip("\n")
            if zeile.startswith("event: "):
                aktuell = zeile[7:]
            elif zeile.startswith("data: ") and aktuell == bereich:
                return json.loads(zeile[6:])
        return None

    def test_nur_angemeldet(self):
        c, r = self.strom("/events?journal=buildagent", cookie=False)
        self.assertEqual(r.status, 401)
        r.read()
        zu(c, r)
        self.assertEqual(self.fabrik.prozesse, [])

    def test_journal_des_gewaehlten_runners(self):
        c, r = self.strom("/events?journal=buildagent")
        self.assertEqual(r.status, 200)
        stand = self.lies_bis(r, "journal")
        self.assertEqual((stand["unit"], stand["neu"]), ("buildagent.service", True))
        self.assertTrue(warte(lambda: self.fabrik.prozesse))
        p = self.fabrik.prozesse[0]
        self.assertIn("--unit=buildagent.service", p.befehl)
        p.schreibe(roh(eintrag("heartbeat ok")))
        neu = self.lies_bis(r, "journal")
        self.assertEqual(neu["zeilen"][0]["text"], "buildagent[2187]: heartbeat ok")
        zu(c, r)
        # Fenster zu: der Server merkt es beim nächsten Schreiben, dann endet journalctl
        for _ in range(300):
            if p.terminiert:
                break
            self.app.zustand.verteiler.sende("status", {})
            time.sleep(0.02)
        self.assertEqual(p.terminiert, 1)

    def test_kein_journal_ohne_faehigkeit_oder_mit_anderer_quelle(self):
        for rid in ("runner-vm-01", "ohne-logs", "datei", "gibt-es-nicht", "..%2Fetc", "a%20b", "-x"):
            with self.subTest(rid=rid):
                c, r = self.strom(f"/events?journal={rid}")
                self.assertEqual(r.status, 200)
                self.assertIsNotNone(self.lies_bis(r, "runner"))
                zu(c, r)
                # der Server merkt das Schließen beim nächsten Schreiben (Grenze je Sitzung, S-DOS-01)
                self.assertTrue(warte(lambda: self.app.zustand.verteiler.sende("status", {}) or not self.app.stroeme))
        time.sleep(0.2)
        self.assertEqual(self.fabrik.prozesse, [])

    def test_unit_nur_aus_runner_liste(self):
        z = self.app.zustand
        self.assertEqual(z.journal_unit("buildagent"), "buildagent.service")
        for rid in ("runner-vm-01", "ohne-logs", "datei", "x", "", None, 5):
            self.assertIsNone(z.journal_unit(rid), rid)
        z._setze("runner", [runner_eintrag("boese", GRUND, {"art": "journal", "unit": "--help.service"})])  # noqa: SLF001
        self.assertIsNone(z.journal_unit("boese"))

    def test_runner_kommt_spaeter(self):
        """Direkt nach dem Start gibt es runner[] noch nicht: das Journal hängt sich mit dem ersten Ereignis „runner“ an."""
        alt = self.app.zustand.bereiche.pop("runner")
        c, r = self.strom("/events?journal=buildagent")
        time.sleep(0.3)
        self.assertEqual(self.fabrik.prozesse, [])
        self.app.zustand._setze("runner", alt)  # noqa: SLF001
        stand = self.lies_bis(r, "journal")
        self.assertEqual(stand["unit"], "buildagent.service")
        zu(c, r)

    def test_grenze_wird_gemeldet(self):
        self.app.zustand.journale.max_folger = 0
        c, r = self.strom("/events?journal=buildagent")
        stand = self.lies_bis(r, "journal")
        self.assertEqual((stand["hinweis"], stand["zeilen"]), ("grenze", []))
        zu(c, r)


if __name__ == "__main__":
    unittest.main()
