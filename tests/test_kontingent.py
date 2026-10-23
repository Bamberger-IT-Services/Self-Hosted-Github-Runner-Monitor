"""GitHub-Kontingent schonen: ETag/304 und ruhige Repositories (Issue #15)."""
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from runner_monitor import github


class FakeGitHub(BaseHTTPRequestHandler):
    zaehler = {"200": 0, "304": 0}

    def do_GET(self):  # noqa: N802
        etag = '"v1"'
        if self.headers.get("If-None-Match") == etag:
            FakeGitHub.zaehler["304"] += 1
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("X-RateLimit-Remaining", "4999")
            self.end_headers()
            return
        FakeGitHub.zaehler["200"] += 1
        roh = json.dumps([{"name": "web-portal"}]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("ETag", etag)
        self.send_header("X-RateLimit-Remaining", "4998")
        self.send_header("github-authentication-token-expiration", "2026-11-06 12:00:00 UTC")
        self.end_headers()
        self.wfile.write(roh)

    def log_message(self, *a):
        pass


class ETagTest(unittest.TestCase):
    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeGitHub)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.alt = github.API
        github.API = f"http://127.0.0.1:{self.srv.server_address[1]}"
        FakeGitHub.zaehler = {"200": 0, "304": 0}

    def tearDown(self):
        github.API = self.alt
        self.srv.shutdown()
        self.srv.server_close()

    def test_zweite_anfrage_ist_304_mit_gemerkter_antwort(self):
        speicher = {}
        a = github.Klient("t", speicher=speicher).hole("/orgs/beispiel-org/repos")
        k = github.Klient("t", speicher=speicher)       # neuer Durchlauf, gleicher Speicher
        b = k.hole("/orgs/beispiel-org/repos")
        self.assertEqual(a.daten, b.daten)
        self.assertEqual(FakeGitHub.zaehler, {"200": 1, "304": 1})
        self.assertEqual(k.zaehler, {"anfragen": 1, "unveraendert": 1})
        # Token-Ablauf bleibt auch bei 304 lesbar (aus der gemerkten Antwort)
        self.assertIn("github-authentication-token-expiration", b.kopf)
        self.assertEqual(k.kontingent()["frei"], 4999)

    def test_ohne_speicher_keine_bedingte_anfrage(self):
        github.Klient("t").hole("/x")
        github.Klient("t").hole("/x")
        self.assertEqual(FakeGitHub.zaehler, {"200": 2, "304": 0})


class RuhigTest(unittest.TestCase):
    class Klient(github.Klient):
        def __init__(self, speicher, laeufe):
            super().__init__("t", speicher=speicher)
            self.pfade, self.laeufe = [], laeufe

        def hole(self, pfad, parameter=None):
            self.pfade.append(pfad)
            if pfad.endswith("/repos"):
                alt = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 7200))
                neu = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 60))
                return github.Antwort([{"name": "ruhig", "pushed_at": alt}, {"name": "aktiv", "pushed_at": neu}])
            if pfad.endswith("/actions/runs"):
                return github.Antwort({"workflow_runs": self.laeufe.get(pfad.split("/")[3], [])})
            return github.Antwort({"runners": []})

    def test_ruhiges_repo_seltener(self):
        speicher = {}
        k = self.Klient(speicher, {})
        github.abfrage(k, "beispiel-org", "runner-vm-01")
        self.assertIn("/repos/beispiel-org/ruhig/actions/runs", k.pfade)
        k2 = self.Klient(speicher, {})
        e = github.abfrage(k2, "beispiel-org", "runner-vm-01")
        self.assertNotIn("/repos/beispiel-org/ruhig/actions/runs", k2.pfade)   # übersprungen
        self.assertIn("/repos/beispiel-org/aktiv/actions/runs", k2.pfade)      # kürzlich gepusht
        self.assertEqual([r["name"] for r in e["repos"]], ["ruhig", "aktiv"])
        speicher["ruhig"]["ruhig"]["zeit"] -= github.RUHIG_TAKT + 1             # Takt abgelaufen
        k3 = self.Klient(speicher, {})
        github.abfrage(k3, "beispiel-org", "runner-vm-01")
        self.assertIn("/repos/beispiel-org/ruhig/actions/runs", k3.pfade)

    def test_wartender_lauf_haelt_repo_wach(self):
        speicher = {}
        github.abfrage(self.Klient(speicher, {"ruhig": [{"status": "queued"}]}), "beispiel-org", "")
        k = self.Klient(speicher, {})
        github.abfrage(k, "beispiel-org", "")
        self.assertIn("/repos/beispiel-org/ruhig/actions/runs", k.pfade)


if __name__ == "__main__":
    unittest.main()
