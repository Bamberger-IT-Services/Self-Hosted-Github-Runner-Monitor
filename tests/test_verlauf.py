"""Verlauf sichern und nach einem Neustart übernehmen (Design 0.4.0, Issue #43)."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from runner_monitor import konfig, zustand


def neuer_zustand(verz: Path) -> zustand.Zustand:
    k = konfig.lade(datei=verz / "fehlt.env", umgebung={
        "MONITOR_ADRESSE": "127.0.0.1", "MONITOR_DATEN_VERZ": str(verz / "daten"), "MONITOR_LAUF_VERZ": str(verz / "lauf"),
    })
    return zustand.Zustand(k)


class VerlaufTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.verz = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def fuelle(self, z, n):
        for i in range(n):
            z._haenge_an(float(i % 100), 40.0, [1000 + i, 100])

    def test_sichern_und_laden(self):
        z = neuer_zustand(self.verz)
        self.fuelle(z, 120)
        jetzt = time.time()
        z.sichere_verlauf(jetzt)
        d = json.loads(z.verlauf_datei.read_text())
        self.assertEqual(len(d["cpu"]), 120)
        self.assertFalse(list(z.verlauf_datei.parent.glob(".verlauf-*")), "keine Reste der temporären Datei")
        neu = neuer_zustand(self.verz)
        neu.lade_verlauf(jetzt + 20)              # 20 s später neu gestartet
        self.assertEqual(len(neu.cpu_verlauf), 120)
        neu._haenge_an(55.0, 41.0, [5, 6])         # erster Messwert füllt die Lücke von 20 s
        self.assertEqual(len(neu.cpu_verlauf), 141)
        self.assertEqual(list(neu.cpu_verlauf)[-21:], [55.0] * 21)
        self.assertLessEqual(abs(neu.verlauf_start - d["start"]), 1)

    def test_grosse_luecke_verwirft(self):
        z = neuer_zustand(self.verz)
        self.fuelle(z, 300)
        jetzt = time.time()
        z.sichere_verlauf(jetzt)
        neu = neuer_zustand(self.verz)
        neu.lade_verlauf(jetzt + 61)
        self.assertEqual(len(neu.cpu_verlauf), 0)
        self.assertIsNone(neu.verlauf_start)

    def test_kaputte_datei_wird_ignoriert(self):
        z = neuer_zustand(self.verz)
        z.verlauf_datei.parent.mkdir(parents=True, exist_ok=True)
        z.verlauf_datei.write_text("{kaputt")
        z.lade_verlauf()
        z.verlauf_datei.write_text(json.dumps({"zeit": "x", "cpu": [1]}))
        z.lade_verlauf()
        jetzt = time.time()
        for kaputt in ({"zeit": jetzt, "cpu": [1, None], "ram": [1, 2], "netz": [[1, 2], [3, 4]]},
                       {"zeit": jetzt, "cpu": [1, 2], "ram": [1, 2], "netz": [[1, 2], [3]]},
                       {"zeit": jetzt, "cpu": [1, 2], "ram": [1], "netz": [[1, 2], [3, 4]]},
                       {"zeit": jetzt, "cpu": [1, float("nan")], "ram": [1, 2], "netz": [[1, 2], [3, 4]]}):
            z.verlauf_datei.write_text(json.dumps(kaputt))
            z.lade_verlauf(jetzt + 1)   # darf nie werfen und nichts halb übernehmen
            self.assertEqual((len(z.cpu_verlauf), len(z.ram_verlauf), len(z.netz_verlauf)), (0, 0, 0))

    def test_voller_verlauf_bleibt_bei_600(self):
        z = neuer_zustand(self.verz)
        self.fuelle(z, 700)
        jetzt = time.time()
        z.sichere_verlauf(jetzt)
        neu = neuer_zustand(self.verz)
        neu.lade_verlauf(jetzt + 5)
        neu._haenge_an(1.0, 1.0, [0, 0])
        self.assertEqual(len(neu.cpu_verlauf), 600)
        self.assertAlmostEqual(neu._start_des_verlaufs(), time.time() - 600, delta=2)

    def test_momentaufnahme_nennt_start(self):
        z = neuer_zustand(self.verz)
        z.bereiche["system"] = {"cpu": 1}
        self.fuelle(z, 30)
        v = dict(z.momentaufnahme())["system"]["verlauf"]
        self.assertEqual(len(v["cpu"]), 30)
        self.assertAlmostEqual(v["start"], time.time(), delta=2)


if __name__ == "__main__":
    unittest.main()
