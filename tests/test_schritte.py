"""Job-Schritt aus einer Quelle (Design 0.4.0, Issue #44)."""
import tempfile
import unittest
from pathlib import Path

from runner_monitor import konfig, runner, zustand


class SchrittTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        k = konfig.lade(datei=d / "fehlt.env", umgebung={"MONITOR_ADRESSE": "127.0.0.1", "MONITOR_DATEN_VERZ": str(d / "daten"), "MONITOR_LAUF_VERZ": str(d / "lauf")})
        self.z = zustand.Zustand(k)
        self.q = self.z.verteiler.anmelden()
        self.z.bei_journal(runner.JobEreignis(art="start", zeit=1.0, name="test"))

    def tearDown(self):
        self.tmp.cleanup()

    def github(self, schritte, nr, name="test"):
        self.z.bereiche["_github"] = {"job": {"name": name, "schritte": schritte, "schritt": nr}}

    def trenner(self):
        while True:
            bereich, text = self.q.get_nowait()
            if bereich == "log" and '"art":"schritt"' in text:
                import json
                return json.loads(text)["zeilen"][0]

    def test_ohne_github_von_ist_none(self):
        for _ in range(3):
            self.z.bei_seite("schritt", Path("x.log"))
        t = self.trenner()
        self.assertEqual((t["nr"], t["von"], t["name"]), (1, None, ""))
        self.assertEqual(self.z._schritt(None), {"nr": 3, "von": None, "name": ""})

    def test_max_aus_lokal_und_github(self):
        self.z.schritt_nr = 2
        self.github(["Set up job", "Checkout", "Tests", "Build"], 3)
        self.assertEqual(self.z._schritt(self.z._gh_job()), {"nr": 3, "von": 4, "name": "Tests"})
        self.z.schritt_nr = 4
        self.assertEqual(self.z._schritt(self.z._gh_job())["name"], "Build")

    def test_springt_nie_zurueck(self):
        self.z.schritt_nr = 5
        self.assertEqual(self.z._schritt(None)["nr"], 5)
        self.github(["a", "b", "c"], 2)   # GitHub hinkt hinterher
        s = self.z._schritt(self.z._gh_job())
        self.assertEqual((s["nr"], s["von"], s["name"]), (5, 5, ""))  # von = max(len, nr)

    def test_neuer_job_beginnt_bei_eins(self):
        self.z.schritt_nr = 6
        self.z._schritt(None)
        self.z.bei_journal(runner.JobEreignis(art="start", zeit=2.0, name="build"))
        self.assertEqual(self.z._schritt(None)["nr"], 1)

    def test_fremder_github_job_zaehlt_nicht(self):
        self.github(["a", "b", "c", "d"], 4, name="anderer")
        self.assertIsNone(self.z._gh_job())
        self.assertEqual(self.z._schritt(self.z._gh_job()), {"nr": 1, "von": None, "name": ""})

    def test_gleichnamiger_folgejob_uebernimmt_alte_abfrage_nicht(self):
        # Review zu #44: Job „test“ endet, der nächste „test“ startet, die Abfrage ist noch alt
        self.z.bereiche["_github"] = {"job": {"name": "test", "schritte": list("abcdefgh"), "schritt": 8, "start": 1.0}}
        self.z.bei_journal(runner.JobEreignis(art="ende", zeit=500.0, name="test", ergebnis="erfolg"))
        self.assertIsNone(self.z._gh_job())   # beendet, Abfrage meldet ihn noch
        self.z.bei_journal(runner.JobEreignis(art="start", zeit=510.0, name="test"))
        self.assertIsNone(self.z._gh_job())   # neuer Job, alte Startzeit passt nicht
        self.assertEqual(self.z._schritt(self.z._gh_job()), {"nr": 1, "von": None, "name": ""})
        self.z.bereiche["_github"] = {"job": {"name": "test", "schritte": list("abc"), "schritt": 2, "start": 505.0}}
        self.assertEqual(self.z._schritt(self.z._gh_job()), {"nr": 2, "von": 3, "name": "b"})


if __name__ == "__main__":
    unittest.main()
