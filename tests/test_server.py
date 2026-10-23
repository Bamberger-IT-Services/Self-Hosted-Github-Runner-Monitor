"""HTTP-Schicht: Weiterleitungen, Sicherheits-Header, CSRF, Einrichtung und Anmeldung."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from runner_monitor import konfig, server, zugang

WEB = Path(__file__).resolve().parent.parent / "web"


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.verz = tempfile.TemporaryDirectory()
        d = Path(self.verz.name)
        (d / "lauf").mkdir()
        self.k = konfig.lade(datei=d / "fehlt.env", umgebung={
            "MONITOR_ADRESSE": "127.0.0.1", "MONITOR_PORT": "1", "MONITOR_DATEN_VERZ": str(d / "daten"),
            "MONITOR_LAUF_VERZ": str(d / "lauf"), "MONITOR_WEB_VERZ": str(WEB),
        })
        self.k.auftraege_verz.mkdir(parents=True)
        self.app = server.App(self.k)
        self.srv = server.ThreadingHTTPServer(("127.0.0.1", 0), type("H", (server.Handler,), {"app": self.app}))
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.cookies: dict[str, str] = {}

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.verz.cleanup()

    def anfrage(self, methode, pfad, daten=None, origin=True, typ="application/json"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        kopf = {"Host": f"127.0.0.1:{self.port}"}
        if self.cookies:
            kopf["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        koerper = None
        if methode == "POST":
            koerper = json.dumps(daten or {}).encode()
            kopf["Content-Type"] = typ
            if origin:
                kopf["Origin"] = f"http://127.0.0.1:{self.port}"
        c.request(methode, pfad, body=koerper, headers=kopf)
        r = c.getresponse()
        inhalt = r.read()
        c.close()
        for wert in r.headers.get_all("Set-Cookie") or []:
            name, _, rest = wert.partition("=")
            self.cookies[name] = rest.split(";")[0]
        return r, inhalt

    def test_kopfzeilen_und_weiterleitung(self):
        r, _ = self.anfrage("GET", "/")
        self.assertEqual(r.status, 302)
        self.assertEqual(r.headers["Location"], "/einrichtung")
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        r, d = self.anfrage("GET", "/api/health")
        self.assertEqual(r.status, 200)
        self.assertEqual(set(json.loads(d)), {"ok", "version", "vm"})
        r, _ = self.anfrage("GET", "/static/../server.py")
        self.assertEqual(r.status, 404)
        r, _ = self.anfrage("DELETE", "/")
        self.assertEqual(r.status, 405)

    def test_csrf(self):
        r, _ = self.anfrage("POST", "/api/anmelden", {"nutzer": "a"}, origin=False)
        self.assertEqual(r.status, 403)
        r, _ = self.anfrage("POST", "/api/anmelden", {"nutzer": "a"}, typ="text/plain")
        self.assertEqual(r.status, 415)

    def test_einrichtung_und_anmeldung(self):
        zugang.schreibe_code(self.k.einrichtungscode_datei, "ABCD-2345")
        r, _ = self.anfrage("POST", "/api/einrichtung/zugang", {"nutzer": "admin", "passwort": "x" * 14})
        self.assertEqual(r.status, 401)  # ohne Code
        r, _ = self.anfrage("POST", "/api/einrichtung/code", {"code": "abcd-0000"})
        self.assertEqual(r.status, 401)
        r, _ = self.anfrage("POST", "/api/einrichtung/code", {"code": "abcd2345"})
        self.assertEqual(r.status, 200)
        r, b = self.anfrage("POST", "/api/einrichtung/zugang", {"nutzer": "admin", "passwort": "kurz"})
        self.assertEqual(r.status, 400)
        r, _ = self.anfrage("POST", "/api/einrichtung/zugang", {"nutzer": "admin", "passwort": "ein langer satz zum merken"})
        self.assertEqual(r.status, 200)
        r, _ = self.anfrage("POST", "/api/einrichtung/fertig")
        self.assertEqual(r.status, 200)
        self.assertFalse(self.k.einrichtungscode_datei.exists())
        # Zweiter Inhaber ausgeschlossen
        r, _ = self.anfrage("POST", "/api/einrichtung/code", {"code": "abcd2345"})
        self.assertEqual(r.status, 409)
        # Ohne Sitzung: Anmeldeseite und 401 für die API
        self.cookies.clear()
        r, _ = self.anfrage("GET", "/")
        self.assertEqual(r.headers["Location"], "/anmelden")
        # Ohne JavaScript darf das Formular das Passwort nicht in die Adresse schreiben (ZAP 10024, #20)
        r, seite = self.anfrage("GET", "/anmelden")
        self.assertIn(b'method="post"', seite)
        r, _ = self.anfrage("GET", "/events")
        self.assertEqual(r.status, 401)
        r, b = self.anfrage("POST", "/api/anmelden", {"nutzer": "admin", "passwort": "falsch falsch falsch"})
        self.assertEqual(r.status, 401)
        self.assertIn("verbleibend", json.loads(b))
        r, _ = self.anfrage("POST", "/api/anmelden", {"nutzer": "admin", "passwort": "ein langer satz zum merken"})
        self.assertEqual(r.status, 200)
        self.assertIn("rm_sitzung", self.cookies)
        r, b = self.anfrage("GET", "/")
        self.assertEqual(r.status, 200)
        self.assertIn(b"dashboard.js", b)
        r, _ = self.anfrage("GET", "/api/sitzung")
        self.assertEqual(r.status, 200)
        self.live_strom_endet_bei_ueberlauf()
        self.grenze_je_sitzung()
        # Update nur, wenn ein neueres Release bekannt ist
        r, _ = self.anfrage("POST", "/api/update/starten")
        self.assertEqual(r.status, 409)
        # Release schon veröffentlicht, Paket noch nicht angehängt (#63): 409 und gleich neu prüfen lassen
        (self.k.lauf_verz / "release.json").write_text(json.dumps({"version": "99.0.0", "archiv": "", "pruefsumme": "", "bereit": False}))
        r, daten = self.anfrage("POST", "/api/update/starten")
        self.assertEqual(r.status, 409)
        self.assertIn("bereitgestellt", daten.decode())
        self.assertTrue((self.k.auftraege_verz / "release-pruefen").is_file())
        (self.k.auftraege_verz / "release-pruefen").unlink()
        self.assertFalse((self.k.auftraege_verz / "update").exists())
        url = "https://github.com/beispiel-org/runner-monitor/releases/download/v99.0.0/runner-monitor-99.0.0.tar.gz"
        (self.k.lauf_verz / "release.json").write_text(json.dumps({"version": "99.0.0", "archiv": url, "pruefsumme": url + ".sha256", "bereit": True}))
        r, _ = self.anfrage("POST", "/api/update/starten")
        self.assertEqual(r.status, 202)
        self.assertEqual(json.loads((self.k.auftraege_verz / "update").read_text())["version"], "99.0.0")
        # „Jetzt prüfen“ legt nur einen Auftrag für den Sammler ab
        r, _ = self.anfrage("POST", "/api/update/pruefen")
        self.assertEqual(r.status, 202)
        self.assertTrue((self.k.auftraege_verz / "release-pruefen").is_file())
        r, _ = self.anfrage("POST", "/api/abmelden")
        r, _ = self.anfrage("GET", "/api/sitzung")
        self.assertEqual(r.status, 401)

    def test_abgelehnter_koerper_bleibt_nicht_in_der_verbindung(self):
        """POST ohne Origin wird vor dem Lesen des Körpers abgelehnt: Verbindung zu, kein Rest als nächste Anfrage (#20)."""
        import socket
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as s:
            koerper = b"nutzer=ZAP&passwort=ZAP"
            s.sendall(b"POST /api/anmelden HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/x-www-form-urlencoded\r\n"
                      b"Content-Length: " + str(len(koerper)).encode() + b"\r\n\r\n" + koerper +
                      b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            antwort = b""
            while chunk := s.recv(65536):
                antwort += chunk
        self.assertTrue(antwort.startswith(b"HTTP/1.1 403"))
        self.assertIn(b"Connection: close", antwort)
        self.assertNotIn(b"501", antwort)

    def test_kaputte_anfrage_mit_sicherheitskopf(self):
        import socket
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as s:
            s.sendall(b"UNSINN / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            antwort = s.recv(65536)
        self.assertIn(b"Content-Security-Policy", antwort)
        self.assertIn(b"application/json", antwort)

    def live_strom_endet_bei_ueberlauf(self):
        """Kommt ein Browser nicht hinterher, endet der Strom (er verbindet neu), statt stumm offen zu bleiben."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", "/events", headers={"Host": f"127.0.0.1:{self.port}", "Cookie": f"rm_sitzung={self.cookies['rm_sitzung']}"})
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        self.assertIn("text/event-stream", r.headers["Content-Type"])
        v = self.app.zustand.verteiler
        for _ in range(200):  # warten, bis der Strom angemeldet ist
            if v.anzahl:
                break
            threading.Event().wait(0.01)
        self.assertEqual(v.anzahl, 1)
        for i in range(2100):
            v.sende("system", {"i": i})
        rest = r.read()  # endet nur, wenn der Server den Strom schließt (sonst Zeitüberschreitung)
        self.assertLessEqual(rest.count(b"event: system"), 2000)
        c.close()
        self.assertEqual(v.anzahl, 0)

    def grenze_je_sitzung(self):
        """S-DOS-01 / Issue #19: höchstens SSE_JE_SITZUNG Live-Verbindungen je Sitzung."""
        kopf = {"Host": f"127.0.0.1:{self.port}", "Cookie": f"rm_sitzung={self.cookies['rm_sitzung']}"}
        offen = []
        for _ in range(server.SSE_JE_SITZUNG):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            c.request("GET", "/events", headers=kopf)
            self.assertEqual(c.getresponse().status, 200)
            offen.append(c)
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", "/events", headers=kopf)
        r = c.getresponse()
        self.assertEqual(r.status, 429)
        r.read()
        c.close()
        offen.pop().close()  # ein Fenster zu → wieder Platz
        for _ in range(200):
            if self.app.stroeme and sum(self.app.stroeme.values()) < server.SSE_JE_SITZUNG:
                break
            # Der Server merkt das Schließen beim nächsten Schreiben; anstoßen mit einer Nachricht
            self.app.zustand.verteiler.sende("status", {})
            threading.Event().wait(0.02)
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", "/events", headers=kopf)
        self.assertEqual(c.getresponse().status, 200)
        c.close()
        for o in offen:
            o.close()


if __name__ == "__main__":
    unittest.main()
