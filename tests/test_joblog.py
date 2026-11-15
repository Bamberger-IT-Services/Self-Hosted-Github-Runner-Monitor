"""Job-Log laufender Forgejo-/Gitea-Jobs im Live-Log (#176): Leser beim Dienst (Range, Schritte, Grenzen),
Verwaltung im Sammler (Bedarf, Datei 0640), Verteilung im Webdienst (nur neue Zeilen, Lücken, Prüfung).

Kein Netz: Die Attrappe läuft auf 127.0.0.1 und verhält sich wie Forgejo 17.0.1 (gemessen): ``text/plain``
mit Zeitstempel je Zeile, Range wie Go ``http.ServeContent`` (206, 416 mit ``bytes */n``, leeres Log 200),
``?step=N`` mit ``number`` aus ``/actions/jobs/{id}``.
"""
import http.server
import json
import os
import queue
import re
import stat
import tempfile
import threading
import time
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

from runner_monitor import einrichtung, joblog, zustand
from runner_monitor.anbieter import forgejo as fj
from runner_monitor.anbieter import forgejo_log as fl

TOKEN = "f" * 40
JOB = "/api/v1/repos/beispiel-org/web-portal/actions/jobs/7"


def zeile(text: str, sekunde: int = 41) -> bytes:
    return f"2026-11-15T20:29:{sekunde:02d}.0510739Z {text}\n".encode()


class Attrappe:
    """Zustand der Forgejo-Attrappe: Schritte [Name, Status, Log] und Job-Status; ``range`` = Range beachten."""

    def __init__(self) -> None:
        self.schritte = [["Set up job", "success", zeile("Runner 0000 (version:v13.2.1) received task 9 of job build")],
                         ["actions/checkout@v7", "running", zeile("Syncing repository")],
                         ["Tests", "waiting", b""],
                         ["Complete job", "waiting", b""]]
        self.status = "running"
        self.range = True
        self.mit_schritt = True     # ?step= beachten (Forgejo); False: wie Gitea, immer das ganze Log
        self.detail = True          # /actions/jobs/{id} vorhanden
        self.codes: dict[str, int] = {}
        self.gesehen: list[tuple[str, dict, str | None, str | None]] = []
        self.sperre = threading.Lock()

    def log(self, schritt: int | None) -> bytes:
        if schritt is None or not self.mit_schritt:
            return b"".join(s[2] for s in self.schritte)
        return self.schritte[schritt][2]


def _handler(a: Attrappe):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            teile = urllib.parse.urlsplit(self.path)
            q = dict(urllib.parse.parse_qsl(teile.query))
            with a.sperre:
                a.gesehen.append((teile.path, q, self.headers.get("Range"), self.headers.get("Authorization")))
                if teile.path in a.codes:
                    return self._antwort(a.codes[teile.path], b'{"message":"nein"}', "application/json")
                if teile.path == JOB and a.detail:
                    steps = [{"number": i, "name": n, "status": st} for i, (n, st, _) in enumerate(a.schritte)]
                    return self._antwort(200, json.dumps({"id": 7, "status": a.status, "steps": steps}).encode(), "application/json")
                if teile.path == JOB + "/logs":
                    if "step" in q and a.mit_schritt and not 0 <= int(q["step"]) < len(a.schritte):
                        return self._antwort(404, b'{"message":"step index out of range"}', "application/json")
                    rumpf = a.log(int(q["step"]) if "step" in q else None)
                    return self._bereich(rumpf, self.headers.get("Range") if a.range else None)
            return self._antwort(404, b'{"message":"not found"}', "application/json")

        def _bereich(self, rumpf: bytes, bereich: str | None):
            n = len(rumpf)
            if not bereich or n == 0:  # Go: leeres Log → 200 statt 416
                return self._antwort(200, rumpf)
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", bereich)
            if m.group(1) == "":
                a0, b0 = max(0, n - int(m.group(2))), n - 1
            else:
                a0 = int(m.group(1))
                b0 = min(int(m.group(2)) if m.group(2) else n - 1, n - 1)
                if a0 >= n:
                    return self._antwort(416, b"invalid range: failed to overlap\n", kopf={"Content-Range": f"bytes */{n}"})
            return self._antwort(206, rumpf[a0:b0 + 1], kopf={"Content-Range": f"bytes {a0}-{b0}/{n}"})

        def _antwort(self, code, rumpf, typ="text/plain; charset=utf-8", kopf=None):
            self.send_response(code)
            self.send_header("Content-Type", typ)
            self.send_header("Accept-Ranges", "bytes")
            for k, v in (kopf or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(rumpf)))
            self.end_headers()
            self.wfile.write(rumpf)

        def log_message(self, *args):  # noqa: D102
            pass
    return H


class MitServer(unittest.TestCase):
    def setUp(self):
        self.a = Attrappe()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _handler(self.a))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.adresse = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def klient(self) -> fl.LogKlient:
        return fl.LogKlient(self.adresse, TOKEN, http_erlaubt=True)

    def folger(self, schritte=True) -> fl.LogFolger:
        return fl.LogFolger("beispiel-org", "web-portal", 7, schritte=schritte, lauf="7-test")

    def logs(self):
        return [(q, r) for p, q, r, _ in self.a.gesehen if p.endswith("/logs")]


def texte(f: fl.LogFolger) -> list[str]:
    return [z.get("text") if "text" in z else f"[{z['art']}:{z.get('nr', z.get('bytes'))}]" for z in f.puffer]


# ---------------------------------------------------------------- Zeilen


class ZeilenTest(unittest.TestCase):
    def test_zeitstempel_abgetrennt(self):
        z = fl.zeile_aus(b"2026-11-15T20:29:41.0510739Z Syncing repository")
        self.assertEqual(z["text"], "Syncing repository")
        self.assertAlmostEqual(z["zeit"], 1794774581.0510739, places=5)  # datetime: 2026-11-15T20:29:41+00:00
        self.assertEqual(fl.zeit_aus("2026-11-15T21:29:41+01:00 x"), (1794774581.0, "x"))
        zeit, text = fl.zeit_aus("ohne Zeitstempel")
        self.assertIsNone(zeit)
        self.assertEqual(text, "ohne Zeitstempel")
        self.assertGreater(fl.zeile_aus(b"ohne")["zeit"], 1.7e9)

    def test_ansi_nur_farben_steuerzeichen_weg(self):
        roh = "\x1b[90m8:29PM\x1b[0m \x1b[31mERR\x1b[0m \x1b[2K\x1b[1A\x1b]8;;https://x.example\x07link\x1b]8;;\x07 \x00\x08ok\r"
        self.assertEqual(fl.bereinige(roh), "\x1b[90m8:29PM\x1b[0m \x1b[31mERR\x1b[0m ]8;;https://x.examplelink]8;; ok")
        self.assertNotIn("\x07", fl.bereinige("a\x07b"))

    def test_tokens_maskiert_und_gekuerzt(self):
        self.assertEqual(fl.bereinige(f"token {TOKEN} ghp_{'a' * 36}"), "token *** ***")
        self.assertEqual(fl.bereinige("Authorization: token abc"), "Authorization: token ***")
        self.assertEqual(len(fl.bereinige("x" * 10_000)), fl.journal.MAX_ZEILE)


# ---------------------------------------------------------------- Klient


class KlientTest(MitServer):
    def test_suffix_dann_range_ab_offset(self):
        k = self.klient()
        s = k.log(JOB[len("/api/v1"):] + "/logs", {"step": 1}, None)
        self.assertEqual((s.start, s.gesamt, s.range_ok), (0, len(self.a.schritte[1][2]), True))
        s2 = k.log(JOB[len("/api/v1"):] + "/logs", {"step": 1}, s.gesamt)  # nichts Neues: 416 → leer
        self.assertEqual((s2.start, s2.daten, s2.gesamt), (s.gesamt, b"", s.gesamt))
        self.assertEqual([r for _, r in self.logs()], [f"bytes=-{fl.MAX_START}", f"bytes={s.gesamt}-{s.gesamt + fl.MAX_ABSCHNITT - 1}"])
        self.assertEqual({a for *_, a in self.a.gesehen}, {f"token {TOKEN}"})

    def test_ohne_range_nur_das_ende(self):
        self.a.range = False
        self.a.schritte[1][2] = b"".join(zeile(f"z{i}") for i in range(20000))  # > MAX_ABSCHNITT
        s = self.klient().log(JOB[len("/api/v1"):] + "/logs", None, 100)
        self.assertFalse(s.range_ok)
        gesamt = len(self.a.log(None))
        self.assertEqual((s.gesamt, len(s.daten), s.start), (gesamt, fl.MAX_ABSCHNITT, gesamt - fl.MAX_ABSCHNITT))

    def test_ohne_range_zu_gross(self):
        self.a.range = False
        self.a.schritte[1][2] = b"x" * 3000
        with mock.patch.object(fl, "MAX_OHNE_RANGE", 2048), self.assertRaises(fl.LogFehler) as f:
            self.klient().log(JOB[len("/api/v1"):] + "/logs", None, 0)
        self.assertEqual(f.exception.art, "zu-gross")

    def test_fehlercodes(self):
        for code, art in ((401, "token-ungueltig"), (403, "keine-rechte"), (404, "fehlt"), (429, "kontingent"), (502, "nicht-erreichbar")):
            self.a.codes[JOB + "/logs"] = code
            with self.assertRaises(fj.ForgejoFehler) as f:
                self.klient().log(JOB[len("/api/v1"):] + "/logs", None, None)
            self.assertEqual(f.exception.art, art, code)

    def test_http_ohne_erlaubnis_kein_token(self):
        k = fl.LogKlient(self.adresse, TOKEN)  # http:// ohne http_erlaubt (E-21)
        with self.assertRaises(fj.ForgejoFehler):
            k.log("/x/logs", None, None)
        self.assertEqual(self.a.gesehen, [])

    def test_content_range_muss_passen(self):
        antwort = mock.Mock()
        with self.assertRaises(fj.ForgejoFehler):
            fl._teil(antwort, {"content-range": "bytes 0-9/5"}, time.monotonic() + 5, 0)  # Ende hinter der Länge
        with self.assertRaises(fj.ForgejoFehler):
            fl._teil(antwort, {"content-range": "bytes 10-19/50"}, time.monotonic() + 5, 0)  # anderer Anfang
        with self.assertRaises(fj.ForgejoFehler):
            fl._teil(antwort, {"content-range": f"bytes 0-{fl.MAX_ABSCHNITT}/{fl.MAX_ABSCHNITT * 2}"}, time.monotonic() + 5, 0)
        with self.assertRaises(fj.ForgejoFehler):
            fl._teil(antwort, {}, time.monotonic() + 5, 0)


# ---------------------------------------------------------------- Leser eines Jobs


class FolgerTest(MitServer):
    def test_wachsendes_log_nur_neues_mit_schrittgrenzen(self):
        f, k = self.folger(), self.klient()
        f.takt(k)
        self.assertEqual(texte(f), ["[schritt:2]", "Syncing repository"])
        self.assertEqual(f.schritt, {"nr": 2, "von": 4, "name": "actions/checkout@v7"})
        self.assertEqual(f.puffer[0]["name"], "actions/checkout@v7")
        # Log wächst: nur das Neue, ab dem gelesenen Byte
        alt = len(self.a.schritte[1][2])
        self.a.schritte[1][2] += zeile("Fetching") + zeile("Checking out")
        f.takt(k)
        self.assertEqual(texte(f)[2:], ["Fetching", "Checking out"])
        self.assertIn(({"step": "1"}, f"bytes={alt}-{alt + fl.MAX_ABSCHNITT - 1}"), self.logs())
        # Schritt wechselt: Rest des alten Schritts, dann Trenner und der neue
        self.a.schritte[1][2] += zeile("letzte Zeile von checkout")
        self.a.schritte[1][1], self.a.schritte[2][1] = "success", "running"
        self.a.schritte[2][2] = zeile("Ran 584 tests") + zeile("\x1b[32mOK\x1b[0m")
        f.takt(k)
        self.assertEqual(texte(f)[4:], ["letzte Zeile von checkout", "[schritt:3]", "Ran 584 tests", "\x1b[32mOK\x1b[0m"])
        self.assertEqual(f.schritt, {"nr": 3, "von": 4, "name": "Tests"})
        self.assertTrue(f.aktiv)
        # Job zu Ende: der letzte Schritt wird noch gelesen, dann aktiv False
        for s in self.a.schritte:
            s[1] = "success"
        self.a.schritte[3][2] = zeile("Job succeeded")
        self.a.status = "success"
        f.takt(k)
        self.assertEqual(texte(f)[-2:], ["[schritt:4]", "Job succeeded"])
        self.assertFalse(f.aktiv)
        self.assertEqual([z["seq"] for z in f.puffer], list(range(1, len(f.puffer) + 1)))

    def test_ohne_neues_keine_doppelten_zeilen(self):
        f, k = self.folger(), self.klient()
        for _ in range(3):
            f.takt(k)
        self.assertEqual(texte(f), ["[schritt:2]", "Syncing repository"])

    def test_unvollstaendige_zeile_wartet(self):
        f, k = self.folger(), self.klient()
        self.a.schritte[1][2] += b"2026-11-15T20:29:42.0000000Z hal"
        f.takt(k)
        self.assertEqual(texte(f), ["[schritt:2]", "Syncing repository"])
        self.a.schritte[1][2] += "bfertig – äöü\n".encode()
        f.takt(k)
        self.assertEqual(texte(f)[-1], "halbfertig – äöü")

    def test_einstieg_in_langen_schritt_nur_das_ende(self):
        self.a.schritte[1][2] = b"".join(zeile(f"Zeile {i:05d} " + "x" * 250) for i in range(300))  # ~85 KB > MAX_START
        f = self.folger()
        f.takt(self.klient())
        self.assertEqual(f.puffer[1]["art"], "gekuerzt")
        self.assertGreater(f.puffer[1]["bytes"], len(self.a.schritte[1][2]) - fl.MAX_START)
        self.assertTrue(texte(f)[-1].startswith("Zeile 00299 "))
        self.assertTrue(texte(f)[2].startswith("Zeile "))  # keine angeschnittene Zeile
        self.assertLessEqual(len(f.puffer), fl.PUFFER)

    def test_rueckstand_springt_ans_ende(self):
        f, k = self.folger(), self.klient()
        f.takt(k)
        self.a.schritte[1][2] += b"".join(zeile(f"viel {i:05d}") for i in range(2000))
        with mock.patch.object(fl, "MAX_RUECKSTAND", 4096), mock.patch.object(fl, "MAX_ABSCHNITT", 2048), \
                mock.patch.object(fl, "MAX_START", 1024):
            f.takt(k)
            f.takt(k)
        self.assertIn("gekuerzt", [z.get("art") for z in f.puffer])
        self.assertEqual(texte(f)[-1], "viel 01999")
        self.assertLessEqual(len(self.logs()), 1 + 2 * (fl.MAX_ANFRAGEN - 1))

    def test_anfragen_je_takt_begrenzt(self):
        f, k = self.folger(), self.klient()
        f.takt(k)
        vorher = len(self.a.gesehen)
        self.a.schritte[1][2] += b"".join(zeile(f"z {i:06d}", 42) for i in range(60000))  # ~2,3 MB in Stücken zu 256 KB
        with mock.patch.object(fl, "MAX_RUECKSTAND", 10**9):
            f.takt(k)
        self.assertLessEqual(len(self.a.gesehen) - vorher, fl.MAX_ANFRAGEN)
        self.assertLess(f.offset, len(self.a.schritte[1][2]))  # Rest im nächsten Takt

    def test_server_ignoriert_range(self):
        self.a.range = False
        f, k = self.folger(schritte=False), self.klient()
        f.takt(k)
        self.assertFalse(f.range_ok)
        self.assertEqual(f.pause(), fl.TAKT_OHNE_RANGE)
        n = len(f.puffer)
        self.a.schritte[1][2] += zeile("neu")
        f.takt(k)
        self.assertEqual(texte(f)[n:], ["neu"])  # nur das Neue, obwohl der Server alles schickt

    def test_leeres_log_ist_kein_fehlendes_range(self):
        self.a.schritte[1][2] = b""
        f = self.folger()
        f.takt(self.klient())
        self.assertTrue(f.range_ok)
        self.assertEqual(f.pause(), fl.TAKT)

    def test_log_neu_begonnen(self):
        f, k = self.folger(schritte=False), self.klient()
        f.takt(k)
        self.a.schritte = [["Set up job", "running", zeile("zweiter Versuch")]]
        f.takt(k)
        f.takt(k)
        self.assertEqual(texte(f)[-1], "zweiter Versuch")

    def test_gitea_ohne_schritte(self):
        self.a.mit_schritt = False
        f = self.folger(schritte=False)
        f.takt(self.klient())
        self.assertEqual(texte(f), ["Runner 0000 (version:v13.2.1) received task 9 of job build", "Syncing repository"])
        self.assertEqual(f.schritt, {"nr": 2, "von": 4, "name": "actions/checkout@v7"})  # Chip aus der Schrittliste
        self.assertFalse([q for q, _ in self.logs() if q])

    def test_aelterer_server_ohne_job_detail(self):
        self.a.detail = False
        f, k = self.folger(), self.klient()
        f.takt(k)
        self.assertFalse(f.mit_schritten)
        self.assertEqual(len(texte(f)), 2)
        f.takt(k)
        self.assertEqual(sum(1 for p, *_ in self.a.gesehen if p == JOB), 1)  # nur einmal versucht

    def test_ohne_log_endpunkt_nicht_unterstuetzt(self):
        self.a.codes[JOB + "/logs"] = 404
        f, k = self.folger(), self.klient()
        with self.assertRaises(fl.LogFehler) as fehler:
            for _ in range(fl.MAX_FEHLT):
                f.takt(k)
        self.assertEqual(fehler.exception.art, "nicht-unterstuetzt")

    def test_lange_zeile_begrenzt(self):
        self.a.schritte[1][2] = b"2026-11-15T20:29:41.0Z " + b"x" * (fl.MAX_REST + 100) + b"\n" + zeile("danach")
        f = self.folger()
        with mock.patch.object(fl, "MAX_START", 2 * fl.MAX_REST):
            f.takt(self.klient())
        self.assertEqual(len(f.puffer[1]["text"]), fl.journal.MAX_ZEILE)
        self.assertEqual(texte(f)[-1], "danach")

    def test_puffer_begrenzt(self):
        f = self.folger()
        for i in range(fl.PUFFER + 50):
            f.zeilen(zeile(f"z{i}"))
        self.assertEqual(len(f.puffer), fl.PUFFER)
        self.assertEqual(f.seq, fl.PUFFER + 50)
        f2 = self.folger()
        for _ in range(200):
            f2.zeilen(b"y" * 3000 + b"\n")
        self.assertLessEqual(sum(len(z["text"]) for z in f2.puffer), fl.MAX_PUFFER_ZEICHEN)

    def test_ungueltiger_job(self):
        for repo, jid in (("../x", 7), ("web-portal", 0), ("web-portal", "7"), ("a/b", 7)):
            with self.assertRaises(ValueError):
                fl.LogFolger("beispiel-org", repo, jid)


# ---------------------------------------------------------------- Sammler: Verwaltung


class _K:
    def __init__(self, server):
        self.server, self.org, self.http_erlaubt = server, "beispiel-org", True


class _Adapter:
    JOB_LOG = True

    def __init__(self, server, token=TOKEN):
        self.k = _K(server)
        self._token = token

    def token(self):
        return self._token


class VerwaltungTest(MitServer):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.v = joblog.Verwaltung(self.d / "lauf", self.d / "auftraege")
        self.ziel = {"id": 7, "repo": "web-portal", "art": "forgejo"}

    def tearDown(self):
        self.v.beenden(warten=fl.FRIST + 1)
        self.tmp.cleanup()
        super().tearDown()

    def kandidaten(self, ziel="std"):
        return {"runner-vm-02": (_Adapter(self.adresse), self.ziel if ziel == "std" else ziel)}

    def warte(self, bedingung, frist=5.0):
        ende = time.monotonic() + frist
        while time.monotonic() < ende:
            if bedingung():
                return True
            time.sleep(0.02)
        return False

    def datei(self):
        try:
            return json.loads((self.d / "lauf" / joblog.DATEI).read_text())
        except (OSError, ValueError):
            return {}

    def test_ohne_bedarf_keine_anfrage(self):
        self.v.takt(time.monotonic(), self.kandidaten())
        time.sleep(0.2)
        self.assertEqual(self.a.gesehen, [])
        self.assertEqual(self.datei()["runner"], {})  # nach dem Start einmal leer: alter Stand gilt nicht mehr

    @mock.patch.object(joblog.os, "geteuid", return_value=1000)  # CI im Forgejo-Runner läuft als root (#133)
    def test_mit_bedarf_liest_und_schreibt_0640(self, _):
        einrichtung.lege_auftrag_einfach(self.d / "auftraege", joblog.AUFTRAG, {"runner": ["runner-vm-02", "../boese", 5]})
        self.v.takt(time.monotonic(), self.kandidaten())
        self.assertTrue(self.warte(lambda: (self.datei().get("runner", {}).get("runner-vm-02") or {}).get("seq")))
        stand = self.datei()["runner"]["runner-vm-02"]
        self.assertEqual([z.get("text") for z in stand["zeilen"]][1:], ["Syncing repository"])
        self.assertTrue(stand["aktiv"])
        pfad = self.d / "lauf" / joblog.DATEI
        self.assertEqual(stat.S_IMODE(os.stat(pfad).st_mode), 0o640)
        self.assertNotIn(TOKEN, pfad.read_text())
        self.assertFalse(os.path.lexists(self.d / "auftraege" / joblog.AUFTRAG))  # abgeholt
        self.assertEqual(list(self.v.daten()["runner"]), ["runner-vm-02"])

    def test_bedarf_laeuft_ab(self):
        einrichtung.lege_auftrag_einfach(self.d / "auftraege", joblog.AUFTRAG, {"runner": ["runner-vm-02"]})
        jetzt = time.monotonic()
        self.v.takt(jetzt, self.kandidaten())
        self.assertTrue(self.warte(lambda: self.a.gesehen))
        self.v.takt(jetzt + joblog.BEDARF_GUELTIG + 1, self.kandidaten())
        self.assertEqual(self.v.daten()["runner"], {})
        self.assertEqual(self.datei()["runner"], {})

    def test_job_gewechselt_oder_keiner(self):
        einrichtung.lege_auftrag_einfach(self.d / "auftraege", joblog.AUFTRAG, {"runner": ["runner-vm-02"]})
        jetzt = time.monotonic()
        self.v.takt(jetzt, self.kandidaten())
        self.v.takt(jetzt + 1, self.kandidaten(None))
        self.assertEqual(self.v.daten()["runner"], {})

    def test_ohne_rechte_hinweis_und_pause(self):
        self.a.codes[JOB] = 403
        einrichtung.lege_auftrag_einfach(self.d / "auftraege", joblog.AUFTRAG, {"runner": ["runner-vm-02"]})
        jetzt = time.monotonic()
        self.v.takt(jetzt, self.kandidaten())
        self.assertTrue(self.warte(lambda: (self.datei().get("runner", {}).get("runner-vm-02") or {}).get("hinweis")))
        self.assertEqual(self.datei()["runner"]["runner-vm-02"]["hinweis"], "keine-rechte")
        n = len(self.a.gesehen)
        einrichtung.lege_auftrag_einfach(self.d / "auftraege", joblog.AUFTRAG, {"runner": ["runner-vm-02"]})
        self.v.takt(jetzt + 5, self.kandidaten())
        time.sleep(0.2)
        self.assertEqual(len(self.a.gesehen), n)  # eine Stunde Pause

    def test_beendeter_job_wird_nicht_neu_gelesen(self):
        for s in self.a.schritte:
            s[1] = "success"
        self.a.status = "success"
        einrichtung.lege_auftrag_einfach(self.d / "auftraege", joblog.AUFTRAG, {"runner": ["runner-vm-02"]})
        jetzt = time.monotonic()
        self.v.takt(jetzt, self.kandidaten())
        self.assertTrue(self.warte(lambda: "runner-vm-02" in self.v._erledigt))
        n = len(self.a.gesehen)
        self.v.takt(jetzt + 2, self.kandidaten())
        time.sleep(0.2)
        self.assertEqual(len(self.a.gesehen), n)

    def test_hoechstens_max_folger(self):
        einrichtung.lege_auftrag_einfach(self.d / "auftraege", joblog.AUFTRAG, {"runner": [f"r{i}" for i in range(5)]})
        kand = {f"r{i}": (_Adapter(self.adresse), self.ziel) for i in range(5)}
        self.v.takt(time.monotonic(), kand)
        self.assertEqual(len(self.v._laeufe), joblog.MAX_FOLGER)


class DateiRechteTest(unittest.TestCase):
    def test_als_root_gruppe_des_webdienstes(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / joblog.DATEI
            gruppe = mock.Mock(gr_gid=4711)
            with mock.patch.object(joblog.os, "geteuid", return_value=0), \
                    mock.patch.object(joblog.grp, "getgrnam", return_value=gruppe) as nam, \
                    mock.patch.object(joblog.os, "fchown") as chown:
                joblog.schreibe_fuer_monitor(pfad, {"runner": {}})
            nam.assert_called_once_with("runner-monitor")
            self.assertEqual(chown.call_args[0][1:], (0, 4711))
            self.assertEqual(stat.S_IMODE(os.stat(pfad).st_mode), 0o640)
            with mock.patch.object(joblog.os, "geteuid", return_value=0), \
                    mock.patch.object(joblog.grp, "getgrnam", side_effect=KeyError("runner-monitor")):
                joblog.schreibe_fuer_monitor(pfad, {"runner": {}})
            self.assertEqual(stat.S_IMODE(os.stat(pfad).st_mode), 0o600)  # ohne Gruppe: niemand außer root
            self.assertEqual([p.name for p in Path(tmp).iterdir()], [joblog.DATEI])  # keine Reste


class SammlerZielTest(unittest.TestCase):
    def test_abfrage_merkt_den_job_fuers_job_log(self):
        from tests.test_forgejo import Attrappe as FjAttrappe
        from tests.test_forgejo import lade
        speicher: dict = {}
        fj.abfrage(FjAttrappe(lade("forgejo-17.json")), "beispiel-org", "runner-vm-02", speicher)
        ziel = speicher["jobLogZiel"]
        self.assertEqual((ziel["repo"], ziel["art"]), ("web-portal", "forgejo"))
        self.assertIsInstance(ziel["id"], int)


# ---------------------------------------------------------------- Webdienst: Verteilung


class JobLogsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / "lauf").mkdir()
        self.j = joblog.JobLogs(self.d / "lauf", self.d / "auftraege")
        self.q: queue.Queue = queue.Queue(maxsize=100)

    def tearDown(self):
        self.tmp.cleanup()

    def schreibe(self, runner: dict, zeit: float | None = None):
        pfad = self.d / "lauf" / joblog.DATEI
        joblog.schreibe_fuer_monitor(pfad, {"version": 1, "runner": runner, "zeit": time.time() if zeit is None else zeit})
        t = time.time() + len(self.__dict__.setdefault("_n", [])) + 1
        self._n.append(1)
        os.utime(pfad, (t, t))  # mtime sicher anders
        self.j.lies()

    @staticmethod
    def stand(seq, zeilen, lauf="7-a", aktiv=True, **mehr):
        return {"lauf": lauf, "job": 7, "aktiv": aktiv, "schritt": {"nr": 2, "von": 4, "name": "Tests"}, "seq": seq,
                "zeilen": zeilen, "hinweis": None, **mehr}

    def nachrichten(self):
        aus = []
        while not self.q.empty():
            bereich, text = self.q.get_nowait()
            self.assertEqual(bereich, "joblog")
            aus.append(json.loads(text))
        return aus

    def test_stand_dann_nur_neue_zeilen(self):
        self.schreibe({"runner-vm-02": self.stand(2, [{"seq": 1, "zeit": 1.0, "text": "a"}, {"seq": 2, "zeit": 2.0, "text": "b"}])})
        self.j.anmelden("runner-vm-02", self.q)
        erst = self.nachrichten()
        self.assertEqual(len(erst), 1)
        self.assertTrue(erst[0]["neu"])
        self.assertEqual([z["text"] for z in erst[0]["zeilen"]], ["a", "b"])
        self.assertNotIn("seq", erst[0]["zeilen"][0])
        self.schreibe({"runner-vm-02": self.stand(3, [{"seq": 2, "zeit": 2.0, "text": "b"}, {"seq": 3, "zeit": 3.0, "text": "c"}])})
        n = self.nachrichten()
        self.assertEqual((n[0]["neu"], [z["text"] for z in n[0]["zeilen"]]), (False, ["c"]))
        self.assertEqual(n[0]["schritt"], {"nr": 2, "von": 4, "name": "Tests"})

    def test_luecke_und_neuer_lauf(self):
        self.schreibe({"runner-vm-02": self.stand(1, [{"seq": 1, "zeit": 1.0, "text": "a"}])})
        self.j.anmelden("runner-vm-02", self.q)
        self.nachrichten()
        self.schreibe({"runner-vm-02": self.stand(900, [{"seq": 900, "zeit": 9.0, "text": "z"}])})
        n = self.nachrichten()[0]
        self.assertEqual(n["zeilen"][0], {"zeit": 9.0, "art": "luecke", "n": 898})
        self.schreibe({"runner-vm-02": self.stand(1, [{"seq": 1, "zeit": 1.0, "text": "neuer Job"}], lauf="8-b")})
        n = self.nachrichten()[0]
        self.assertTrue(n["neu"])
        self.assertEqual([z["text"] for z in n["zeilen"]], ["neuer Job"])

    def test_nur_fenster_des_runners(self):
        andere: queue.Queue = queue.Queue()
        self.j.anmelden("runner-vm-03", andere)
        self.j.anmelden("runner-vm-02", self.q)
        self.nachrichten()
        andere.get_nowait()
        self.schreibe({"runner-vm-02": self.stand(1, [{"seq": 1, "zeit": 1.0, "text": "a"}])})
        self.assertEqual(len(self.nachrichten()), 1)
        self.assertTrue(andere.empty())
        self.j.abmelden("runner-vm-02", self.q)
        self.schreibe({"runner-vm-02": self.stand(2, [{"seq": 2, "zeit": 1.0, "text": "b"}])})
        self.assertEqual(self.nachrichten(), [])

    def test_pruefung_der_datei(self):
        boese = [{"seq": 1, "zeit": 1.0, "text": "ok \x1b]0;titel\x07 \x1b[2J" + "y" * 9000},
                 {"seq": 2, "text": 5}, {"zeit": 1.0, "text": "ohne seq"}, "kaputt",
                 {"seq": 3, "art": "schritt", "nr": True, "von": -1, "name": {"x": 1}},
                 {"seq": 4, "zeit": float("inf"), "text": f"Token {TOKEN}"}]
        self.schreibe({"runner-vm-02": self.stand(4, boese, hinweis="erfunden"), "../x": self.stand(1, []), "runner-vm-04": "kaputt"})
        self.j.anmelden("runner-vm-02", self.q)
        n = self.nachrichten()[0]
        self.assertEqual(len(n["zeilen"]), 3)
        self.assertTrue(n["zeilen"][0]["text"].startswith("ok ]0;titel "))
        self.assertEqual(len(n["zeilen"][0]["text"]), fl.journal.MAX_ZEILE)
        self.assertEqual(n["zeilen"][1], {"zeit": n["zeilen"][1]["zeit"], "art": "schritt", "nr": 1, "von": None, "name": ""})
        self.assertEqual(n["zeilen"][2]["text"], "Token ***")
        self.assertIsNone(n["hinweis"])
        self.assertEqual(set(self.j._staende), {"runner-vm-02"})

    def test_symlink_wird_nicht_gelesen(self):
        echt = self.d / "echt.json"
        echt.write_text(json.dumps({"runner": {"runner-vm-02": self.stand(1, [{"seq": 1, "zeit": 1.0, "text": "geheim"}])}}))
        os.symlink(echt, self.d / "lauf" / joblog.DATEI)
        self.j.lies()
        self.assertEqual(self.j._staende, {})

    def test_bedarf_als_auftrag_nur_mit_zuschauern(self):
        self.j.bedarf(100.0)
        self.assertFalse((self.d / "auftraege" / joblog.AUFTRAG).exists())
        self.j.anmelden("runner-vm-02", self.q)
        self.j.bedarf(100.0)
        pfad = self.d / "auftraege" / joblog.AUFTRAG
        self.assertEqual(json.loads(pfad.read_text())["runner"], ["runner-vm-02"])
        self.assertEqual(stat.S_IMODE(os.stat(pfad).st_mode), 0o600)
        pfad.unlink()
        self.j.bedarf(105.0)
        self.assertFalse(pfad.exists())  # höchstens alle BEDARF_TAKT Sekunden
        self.j.bedarf(100.0 + joblog.BEDARF_TAKT)
        self.assertTrue(pfad.exists())

    def test_sammler_steht_kein_aktives_job_log(self):
        self.schreibe({"runner-vm-02": self.stand(1, [{"seq": 1, "zeit": 1.0, "text": "a"}])}, zeit=time.time() - 3 * joblog.VERALTET)
        self.j.anmelden("runner-vm-02", self.q)
        self.assertTrue(self.nachrichten()[0]["aktiv"])
        self.j.veraltet()
        n = self.nachrichten()
        self.assertEqual(len(n), 1)
        self.assertFalse(n[0]["aktiv"])
        self.j.veraltet()
        self.assertEqual(self.nachrichten(), [])  # nur einmal

    def test_hinweis(self):
        self.schreibe({"runner-vm-02": self.stand(0, [], aktiv=False, hinweis="keine-rechte")})
        self.assertEqual(self.j.hinweis("runner-vm-02"), "keine-rechte")
        self.j.anmelden("runner-vm-02", self.q)
        self.assertFalse(self.nachrichten()[0]["aktiv"])


class ZustandZielTest(unittest.TestCase):
    def test_nur_angebundene_forgejo_gitea_runner(self):
        from tests.test_anbieter import lade_konfig
        with tempfile.TemporaryDirectory() as tmp:
            z = zustand.Zustand(lade_konfig(Path(tmp)))
            fae = {"status": True, "jobs": True, "schritte": True, "logs": True, "updates": False}
            z.bereiche["runner"] = [
                {"id": "a", "dienst": "forgejo", "stand": "angebunden", "faehig": fae},
                {"id": "b", "dienst": "gitea", "stand": "angebunden", "faehig": fae},
                {"id": "c", "dienst": "forgejo", "stand": "offen", "faehig": fae},
                {"id": "d", "dienst": "github", "stand": "angebunden", "faehig": fae},
                {"id": "e", "dienst": "gitlab", "stand": "angebunden", "faehig": fae},
                {"id": "f", "dienst": "forgejo", "stand": "angebunden", "faehig": {**fae, "jobs": False}},
            ]
            self.assertEqual([r for r in "abcdefx" if z.joblog_ziel(r)], ["a", "b"])
            self.assertIsNone(z.joblog_ziel(None))
            liste = [dict(r) for r in z.bereiche["runner"]]
            z.joblogs._staende = {"a": {"hinweis": "nicht-unterstuetzt"}}
            z._joblog_hinweise(liste)
            self.assertEqual(liste[0]["jobLog"], {"hinweis": "nicht-unterstuetzt"})
            self.assertNotIn("jobLog", liste[1])
            self.assertNotIn("jobLog", liste[3])


if __name__ == "__main__":
    unittest.main()
