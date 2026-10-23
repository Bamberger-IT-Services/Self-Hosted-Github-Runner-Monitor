"""Live-Verbindung: Verteiler und Log-Zeilen (Ursache für „Getrennt“ bis 0.3.0)."""
import queue
import unittest

from runner_monitor import zustand


class VerteilerTest(unittest.TestCase):
    def test_volle_schlange_bekommt_ende(self):
        v = zustand.Verteiler()
        q = v.anmelden()
        for i in range(q.maxsize):
            v.sende("system", {"i": i})
        self.assertEqual(v.anzahl, 1)
        v.sende("system", {"i": "zu viel"})
        # rausgeworfen, geleert, nur noch ENDE – der Server beendet daraufhin den Strom
        self.assertEqual(v.anzahl, 0)
        self.assertEqual(q.get_nowait(), zustand.ENDE)
        with self.assertRaises(queue.Empty):
            q.get_nowait()
        v.sende("system", {"i": "danach"})
        with self.assertRaises(queue.Empty):
            q.get_nowait()

    def test_normale_schlange_bleibt(self):
        v = zustand.Verteiler()
        q = v.anmelden()
        v.sende("status", {"a": 1})
        self.assertEqual(q.get_nowait()[0], "status")
        v.abmelden(q)
        self.assertEqual(v.anzahl, 0)


class LogZeilenTest(unittest.TestCase):
    def test_viele_zeilen_eine_nachricht(self):
        z = zustand.Zustand.__new__(zustand.Zustand)  # ohne Messung und Threads
        import threading
        from collections import deque
        z._sperre = threading.Lock()
        z.zeilen = deque(maxlen=zustand.MAX_ZEILEN)
        z.verteiler = zustand.Verteiler()
        q = z.verteiler.anmelden()
        z.bei_seite("zeilen", [(1.0, f"Zeile {i}") for i in range(5000)])
        bereich, text = q.get_nowait()
        self.assertEqual(bereich, "log")
        with self.assertRaises(queue.Empty):
            q.get_nowait()
        import json
        daten = json.loads(text)
        self.assertEqual(len(daten["zeilen"]), zustand.MAX_ZEILEN)
        self.assertEqual(daten["zeilen"][-1]["text"], "Zeile 4999")
        self.assertEqual(len(z.zeilen), zustand.MAX_ZEILEN)


if __name__ == "__main__":
    unittest.main()
