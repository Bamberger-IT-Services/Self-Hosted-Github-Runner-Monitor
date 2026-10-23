"""Hinter einem TLS-Proxy (MONITOR_HTTPS=1): Secure-Cookies und HSTS (Issue #17)."""
import http.client
import tempfile
import threading
import unittest
from pathlib import Path

from runner_monitor import konfig, server, zugang

WEB = Path(__file__).resolve().parent.parent / "web"


def starte(verz: Path, https: bool):
    umgebung = {"MONITOR_ADRESSE": "127.0.0.1", "MONITOR_DATEN_VERZ": str(verz / "daten"), "MONITOR_LAUF_VERZ": str(verz / "lauf"), "MONITOR_WEB_VERZ": str(WEB)}
    if https:
        umgebung["MONITOR_HTTPS"] = "1"
    k = konfig.lade(datei=verz / "fehlt.env", umgebung=umgebung)
    (verz / "lauf").mkdir(exist_ok=True)
    srv = server.ThreadingHTTPServer(("127.0.0.1", 0), type("H", (server.Handler,), {"app": server.App(k)}))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return k, srv


class HttpsTest(unittest.TestCase):
    def anfrage(self, port, methode, pfad, koerper=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        kopf = {"Host": f"127.0.0.1:{port}", "Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json"}
        c.request(methode, pfad, body=koerper, headers=kopf)
        r = c.getresponse(); r.read(); c.close()
        return r

    def test_secure_und_hsts_nur_mit_https(self):
        for https in (False, True):
            with tempfile.TemporaryDirectory() as t:
                k, srv = starte(Path(t), https)
                try:
                    port = srv.server_address[1]
                    r = self.anfrage(port, "GET", "/api/health")
                    self.assertEqual("Strict-Transport-Security" in r.headers, https)
                    zugang.schreibe_code(k.einrichtungscode_datei, "ABCD-2345")
                    r = self.anfrage(port, "POST", "/api/einrichtung/code", b'{"code": "abcd2345"}')
                    self.assertEqual(r.status, 200)
                    self.assertEqual("; Secure" in r.headers["Set-Cookie"], https)
                finally:
                    srv.shutdown(); srv.server_close()


if __name__ == "__main__":
    unittest.main()
