import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from runner_monitor import zugang


class PasswortTest(unittest.TestCase):
    def test_regeln(self):
        self.assertIsNotNone(zugang.pruefe_passwort_regeln("kurz", "admin"))
        self.assertIsNotNone(zugang.pruefe_passwort_regeln("x" * 129, "admin"))
        self.assertIsNotNone(zugang.pruefe_passwort_regeln("adminadminadmin", "admin"))
        self.assertIsNotNone(zugang.pruefe_passwort_regeln("passwort1234", "verwaltung"))
        self.assertIsNotNone(zugang.pruefe_passwort_regeln("aaaaaaaaaaaaaa", "verwaltung"))
        # Keine Zusammensetzungsregeln: nur Kleinbuchstaben und Leerzeichen sind erlaubt
        self.assertIsNone(zugang.pruefe_passwort_regeln("blauer himmel über hohenlohe", "admin"))

    def test_hash(self):
        h = zugang.hash_passwort("richtiges passwort")
        self.assertTrue(zugang.pruefe_hash("richtiges passwort", h))
        self.assertFalse(zugang.pruefe_hash("falsches passwort", h))
        self.assertFalse(zugang.pruefe_hash("x", "kaputt"))


class ZugangTest(unittest.TestCase):
    def setUp(self):
        self.verz = tempfile.TemporaryDirectory()
        p = Path(self.verz.name)
        self.z = zugang.Zugang(p / "zugang.json", p / "sitzungen.json", p / "sperren.json")
        self.z.lege_an("admin", "ein langes sicheres passwort")

    def tearDown(self):
        self.verz.cleanup()

    def test_anmelden_und_sitzung(self):
        self.assertTrue(self.z.eingerichtet())
        token = self.z.anmelden("admin", "ein langes sicheres passwort", "192.0.2.10", merken=True)
        self.assertTrue(token)
        self.assertTrue(self.z.pruefe_sitzung(token))
        self.assertFalse(self.z.pruefe_sitzung("erfunden"))
        self.z.abmelden(token)
        self.assertFalse(self.z.pruefe_sitzung(token))

    def test_falscher_name_oder_passwort(self):
        self.assertIsNone(self.z.anmelden("admin", "falsch falsch falsch", "192.0.2.10", False))
        self.assertIsNone(self.z.anmelden("root", "ein langes sicheres passwort", "192.0.2.10", False))

    def test_sperre_nach_fuenf_fehlversuchen(self):
        for _ in range(5):
            self.assertIsNone(self.z.anmelden("admin", "falsch falsch falsch", "192.0.2.10", False))
        self.assertGreater(self.z.gesperrt_bis("192.0.2.10"), time.time())
        # Auch das richtige Passwort hilft während der Sperre nicht.
        self.assertIsNone(self.z.anmelden("admin", "ein langes sicheres passwort", "192.0.2.10", False))
        self.assertEqual(self.z.verbleibend(), 0)

    def test_neues_passwort_beendet_sitzungen(self):
        token = self.z.anmelden("admin", "ein langes sicheres passwort", "192.0.2.10", False)
        self.z.lege_an("admin", "ein anderes langes passwort")
        self.assertFalse(self.z.pruefe_sitzung(token))

    def test_inaktivitaet_beendet_sitzung(self):
        token = self.z.anmelden("admin", "ein langes sicheres passwort", "192.0.2.10", True)
        spaeter = time.time() + zugang.INAKTIV_MAX + 10
        with mock.patch("runner_monitor.zugang.time.time", return_value=spaeter):
            self.assertFalse(self.z.pruefe_sitzung(token))

    def test_dateirechte(self):
        modus = (Path(self.verz.name) / "zugang.json").stat().st_mode & 0o777
        self.assertEqual(modus, 0o600)


class CodeTest(unittest.TestCase):
    def test_code_ablauf_und_versuche(self):
        with tempfile.TemporaryDirectory() as verz:
            datei = Path(verz) / "code.json"
            self.assertEqual(zugang.pruefe_code(datei, "ABCD-EFGH"), "fehlt")
            code = zugang.neuer_code()
            zugang.schreibe_code(datei, code)
            self.assertEqual(zugang.pruefe_code(datei, code.lower().replace("-", " ")), "ok")
            self.assertEqual(zugang.pruefe_code(datei, "AAAA-AAAA"), "falsch")
            for _ in range(10):
                zugang.pruefe_code(datei, "AAAA-AAAA")
            self.assertEqual(zugang.pruefe_code(datei, code), "abgelaufen")
            zugang.schreibe_code(datei, code, gueltig=-1)
            self.assertEqual(zugang.pruefe_code(datei, code), "abgelaufen")
            self.assertNotIn(code, json.loads(datei.read_text())["hash"])


if __name__ == "__main__":
    unittest.main()
