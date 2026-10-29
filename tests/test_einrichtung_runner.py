"""Einrichtung im Browser, Schritte „Runner“ und „Anbinden“ (#96, E-22): Prüfung der Zuordnung,
Aufträge an den Sammler, runner.json (Pfad, Rechte, atomar, fremde Felder bleiben), Endpunkte mit
CSRF, Anmeldung bzw. Einrichtungscode und Eingabeprüfung. Ohne Netz."""

import http.client
import json
import os
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path

from runner_monitor import einrichtung, konfig, sammler, server, zugang

WEB = Path(__file__).resolve().parent.parent / "web"


def lade_konfig(d: Path) -> konfig.Konfig:
    return konfig.lade(datei=d / "fehlt.env", umgebung={
        "MONITOR_ADRESSE": "127.0.0.1", "MONITOR_PORT": "1", "MONITOR_DATEN_VERZ": str(d / "daten"),
        "MONITOR_LAUF_VERZ": str(d / "lauf"), "MONITOR_WEB_VERZ": str(WEB),
        "MONITOR_TOKEN_DATEI": str(d / "etc" / "github-token"), "MONITOR_RUNNER_VERZ": str(d / "actions-runner"),
        "MONITOR_ORG": "beispiel-org"})


def fund(rid: str, dienst: str = "github", einstufung: str = "voll", **mehr) -> dict:
    return {"id": rid, "name": rid, "dienst": dienst, "server": "https://github.com/beispiel-org", "version": "2.338.1",
            "grad": "sicher", "merkmale": ["systemd-Unit x.service"], "einstufung": einstufung, "stand": "offen",
            "unit": f"{rid}.service", "log": "/opt/actions-runner/_diag", "aktiv": True, "grund": None,
            "faehig": {"status": True, "jobs": True, "schritte": True, "logs": True, "updates": False}, **mehr}


def schreibe_erkennung(k: konfig.Konfig, funde: list[dict]) -> None:
    k.lauf_verz.mkdir(parents=True, exist_ok=True)
    (k.lauf_verz / "erkennung.json").write_text(json.dumps({"zeit": time.time(), "geprueft": [], "runner": funde}), encoding="utf-8")


# ---------------------------------------------------------------- Prüfung der Eingabe


class PruefungTest(unittest.TestCase):
    def test_gueltig(self):
        e = einrichtung.pruefe_eintrag({"id": "buildagent", "stand": "grund", "dienst": "unbekannt", "name": "Build-Agent",
                                        "unit": "buildagent.service", "log": "/var/log/buildagent/agent.log"})
        self.assertEqual(e["log"], "/var/log/buildagent/agent.log")
        self.assertEqual(einrichtung.pruefe_eintrag({"id": "a", "stand": None, "log": ""})["log"], None)
        self.assertEqual(einrichtung.pruefe_eintrag({"id": "a", "stand": "ignoriert"}), {"id": "a", "stand": "ignoriert"})

    def test_nur_felder_der_oberflaeche(self):
        """server, org, http_erlaubt und Zugangsdaten gehören auf die VM (E-18, E-21, E-22)."""
        for fremd in ({"server": "https://boese.example"}, {"http_erlaubt": True}, {"token": "x" * 30}, {"org": "o"}):
            with self.assertRaises(einrichtung.EingabeFehler, msg=fremd):
                einrichtung.pruefe_eintrag({"id": "a", "stand": "grund", **fremd})

    def test_ungueltig(self):
        schlecht = [
            {"id": "../x", "stand": "grund"}, {"id": "Gross", "stand": "grund"}, {"id": "", "stand": "grund"}, {"id": "a" * 65, "stand": "grund"},
            {"id": "a"}, {"id": "a", "stand": "angebunden"}, {"id": "a", "stand": "offen"},
            {"id": "a", "stand": "grund", "dienst": "woodpecker"},
            {"id": "a", "stand": "grund", "name": "a b"}, {"id": "a", "stand": "grund", "name": "<script>"},
            "kein objekt", None,
        ]
        for roh in schlecht:
            with self.assertRaises(einrichtung.EingabeFehler, msg=roh):
                einrichtung.pruefe_eintrag(roh)

    def test_unit(self):
        for gut in ("buildagent.service", "forgejo-runner@1.service"):
            self.assertEqual(einrichtung.pruefe_unit(gut), gut)
        for schlecht in ("sshd.service", "ssh.service", "runner-monitor.service", "runner-monitor-sammler.service",
                         "systemd-journald.service", "-x.service", "buildagent", "a.socket", "getty@tty1.service", "cron.service"):
            self.assertIsNone(einrichtung.pruefe_unit(schlecht), schlecht)
            with self.assertRaises(einrichtung.EingabeFehler):
                einrichtung.pruefe_eintrag({"id": "a", "stand": "grund", "unit": schlecht})

    def test_log_pfad(self):
        """Nur *.log unter /var/log, /opt, /srv – nie Zugangsdaten, Registrierungen oder Dateien des Monitors."""
        for gut in ("/var/log/buildagent/agent.log", "/opt/agent/logs/run.log", "/srv/ci/agent.log"):
            self.assertEqual(einrichtung.pruefe_log(gut), gut)
        for schlecht in ("/etc/shadow", "/etc/runner-monitor/zugang/a.log", "/var/lib/runner-monitor/zugang.json",
                         "/var/log/runner-monitor/x.log", "/var/log/../../etc/x.log", "/var/log//a.log", "/opt/forgejo/.runner",
                         "/opt/x/.versteckt/a.log", "/var/log/a.txt", "/proc/self/environ", "var/log/a.log", "/var/log/a\n.log",
                         "/home/u/a.log", "/var/log/", "/opt/.log"):
            self.assertIsNone(einrichtung.pruefe_log(schlecht), schlecht)

    def test_liste(self):
        self.assertEqual(len(einrichtung.pruefe_liste([{"id": f"r{i}", "stand": "grund"} for i in range(20)])), 20)
        for roh in ([], None, {"id": "a"}, [{"id": f"r{i}", "stand": "grund"} for i in range(21)],
                    [{"id": "a", "stand": "grund"}, {"id": "a", "stand": "ignoriert"}]):
            with self.assertRaises(einrichtung.EingabeFehler, msg=roh):
                einrichtung.pruefe_liste(roh)


# ---------------------------------------------------------------- runner.json


class ZuordnungDateiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.etc = self.d / "etc"
        self.etc.mkdir()
        self.datei = self.etc / "runner.json"
        self.auftraege = self.d / "auftraege"

    def tearDown(self):
        self.tmp.cleanup()

    def test_fremde_felder_bleiben(self):
        alt = {"version": 1, "kommentar": "von Hand", "runner": {
            "runner-vm-04": {"http_erlaubt": True, "server": "http://192.0.2.10"},
            "buildagent": {"stand": "ignoriert", "unit": "buildagent.service", "zukunft": 1}}}
        neu = einrichtung.wende_an(alt, [{"id": "buildagent", "stand": None, "log": "/var/log/b/agent.log"},
                                         {"id": "runner-vm-04", "stand": "grund"}, {"id": "weg", "stand": None}])
        self.assertEqual(neu["kommentar"], "von Hand")
        self.assertEqual(neu["runner"]["runner-vm-04"], {"http_erlaubt": True, "server": "http://192.0.2.10", "stand": "grund"})
        self.assertEqual(neu["runner"]["buildagent"], {"unit": "buildagent.service", "zukunft": 1, "log": "/var/log/b/agent.log"})
        self.assertNotIn("weg", neu["runner"])
        self.assertEqual(alt["runner"]["buildagent"]["stand"], "ignoriert")  # Eingabe unverändert
        leer = einrichtung.wende_an(neu, [{"id": "runner-vm-04", "stand": None}])
        self.assertIn("runner-vm-04", leer["runner"])  # http_erlaubt bleibt, Eintrag also auch
        weg = einrichtung.wende_an({"runner": {"a": {"stand": "grund"}}}, [{"id": "a", "stand": None}])
        self.assertEqual(weg["runner"], {})

    def test_hoechstens_100(self):
        voll = {"runner": {f"r{i}": {"stand": "grund"} for i in range(100)}}
        with self.assertRaises(einrichtung.EingabeFehler):
            einrichtung.wende_an(voll, [{"id": "neu", "stand": "grund"}])
        einrichtung.wende_an(voll, [{"id": "r1", "stand": "ignoriert"}])  # bestehende ändern geht

    def test_schreiben_atomar_und_rechte(self):
        einrichtung.schreibe_zuordnung(self.datei, {"version": 1, "runner": {"a": {"stand": "grund"}}})
        self.assertEqual(stat.S_IMODE(os.stat(self.datei).st_mode), 0o640)
        self.assertEqual(json.loads(self.datei.read_text())["runner"]["a"]["stand"], "grund")
        self.assertEqual([p.name for p in self.etc.iterdir()], ["runner.json"])  # keine Reste
        from runner_monitor import erkennung
        self.assertEqual(erkennung.lies_zuordnung(self.datei), {"a": {"stand": "grund"}})

    def test_ordner_als_symlink_abgelehnt(self):
        echt = self.d / "anderswo"
        echt.mkdir()
        (self.d / "verweis").symlink_to(echt)
        with self.assertRaises(OSError):
            einrichtung.schreibe_zuordnung(self.d / "verweis" / "runner.json", {"runner": {}})
        self.assertFalse((echt / "runner.json").exists())

    def test_zu_gross(self):
        with self.assertRaises(einrichtung.EingabeFehler):
            einrichtung.schreibe_zuordnung(self.datei, {"runner": {}, "x": "y" * 70000})
        self.assertFalse(self.datei.exists())

    def test_kaputte_datei_wird_nicht_ueberschrieben(self):
        self.datei.write_text("{kaputt")
        einrichtung.lege_auftrag(self.auftraege, [{"id": "a", "stand": "grund"}])
        self.assertEqual(einrichtung.verarbeite_auftrag(self.auftraege, self.datei), 0)
        self.assertEqual(self.datei.read_text(), "{kaputt")
        self.assertFalse((self.auftraege / einrichtung.AUFTRAG_ZUORDNUNG).exists())

    def test_runner_json_als_symlink_wird_nicht_ersetzt(self):
        ziel = self.d / "ziel.json"
        ziel.write_text('{"runner": {}}')
        self.datei.symlink_to(ziel)
        einrichtung.lege_auftrag(self.auftraege, [{"id": "a", "stand": "grund"}])
        self.assertEqual(einrichtung.verarbeite_auftrag(self.auftraege, self.datei), 0)
        self.assertTrue(self.datei.is_symlink())
        self.assertEqual(ziel.read_text(), '{"runner": {}}')

    def test_auftrag_wird_noch_einmal_geprueft(self):
        """Der Sammler traut dem Webserver nicht: ungültige Einträge im Auftrag fallen weg."""
        self.auftraege.mkdir()
        (self.auftraege / einrichtung.AUFTRAG_ZUORDNUNG).write_text(json.dumps({"runner": [
            {"id": "a", "stand": "grund", "server": "https://boese.example"},
            {"id": "b", "stand": "grund", "log": "/etc/shadow"},
            {"id": "c", "stand": "ignoriert"}]}))
        self.assertEqual(einrichtung.verarbeite_auftrag(self.auftraege, self.datei), 1)
        self.assertEqual(json.loads(self.datei.read_text())["runner"], {"c": {"stand": "ignoriert"}})

    def test_auftrag_als_symlink_wird_nicht_gelesen(self):
        self.auftraege.mkdir()
        fremd = self.d / "fremd.json"
        fremd.write_text(json.dumps({"runner": [{"id": "c", "stand": "ignoriert"}]}))
        (self.auftraege / einrichtung.AUFTRAG_ZUORDNUNG).symlink_to(fremd)
        self.assertEqual(einrichtung.verarbeite_auftrag(self.auftraege, self.datei), 0)
        self.assertFalse(self.datei.exists())
        self.assertTrue(fremd.exists())  # nur der Verweis wurde entfernt
        self.assertFalse(os.path.lexists(self.auftraege / einrichtung.AUFTRAG_ZUORDNUNG))

    def test_auftraege_zusammenfuehren(self):
        einrichtung.lege_auftrag(self.auftraege, [{"id": "a", "stand": "grund"}, {"id": "b", "stand": "grund"}])
        einrichtung.lege_auftrag(self.auftraege, [{"id": "a", "stand": "ignoriert"}])
        pfad = self.auftraege / einrichtung.AUFTRAG_ZUORDNUNG
        self.assertEqual(stat.S_IMODE(os.stat(pfad).st_mode), 0o600)
        self.assertEqual({e["id"]: e["stand"] for e in einrichtung.lies_auftrag(pfad)}, {"a": "ignoriert", "b": "grund"})


# ---------------------------------------------------------------- Funde und Ergebnis „Verbindung prüfen“


class FundeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.k = lade_konfig(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_funde_mit_zuordnung_und_offenem_auftrag(self):
        schreibe_erkennung(self.k, [fund("runner-vm-01"), fund("buildagent", "unbekannt", "unbekannt", server=None, log=None)])
        self.k.zuordnung_datei.parent.mkdir(parents=True)
        self.k.zuordnung_datei.write_text(json.dumps({"runner": {"runner-vm-01": {"stand": "ignoriert", "http_erlaubt": True}}}))
        einrichtung.lege_auftrag(self.k.auftraege_verz, [{"id": "buildagent", "stand": "grund", "dienst": "gitlab"}])
        d = einrichtung.funde(self.k.lauf_verz, self.k.zuordnung_datei, self.k.auftraege_verz, "runner-vm-01")
        nach = {f["id"]: f for f in d["runner"]}
        self.assertTrue(nach["runner-vm-01"]["primaer"])
        self.assertEqual(nach["runner-vm-01"]["stand"], "ignoriert")
        self.assertEqual(nach["runner-vm-01"]["zuordnung"], {"stand": "ignoriert"})  # http_erlaubt geht nicht raus
        self.assertEqual(nach["buildagent"]["stand"], "grund")
        self.assertEqual(nach["buildagent"]["dienst"], "gitlab")
        self.assertFalse(nach["buildagent"]["primaer"])
        self.assertTrue(d["auftrag"]["zuordnung"])
        for f in d["runner"]:
            self.assertNotIn("log", f)  # Pfade der VM nicht in die Oberfläche

    def test_zurueckgenommener_stand(self):
        schreibe_erkennung(self.k, [fund("a", stand="ignoriert")])  # Erkennung lief noch mit alter Zuordnung
        d = einrichtung.funde(self.k.lauf_verz, self.k.zuordnung_datei, self.k.auftraege_verz, None)
        self.assertEqual(d["runner"][0]["stand"], "offen")

    def test_ohne_erkennung(self):
        d = einrichtung.funde(self.k.lauf_verz, self.k.zuordnung_datei, self.k.auftraege_verz, None)
        self.assertEqual(d["runner"], [])
        self.assertIsNone(d["zeit"])

    def test_verbindung_aus_github_json(self):
        jetzt = time.time()
        ok = einrichtung.verbindung_aus({"abfrage": "ok", "abgefragt": jetzt, "org": "beispiel-org", "tokenAblauf": jetzt + 86400 * 30,
                                         "repos": [{}, {}], "runner": {"zustand": "online"}})
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["ergebnisse"][1]["werte"], {"org": "beispiel-org", "n": "2"})
        self.assertTrue(all(z.get("ok") for z in ok["ergebnisse"]))
        ohne = einrichtung.verbindung_aus({"abfrage": "ok", "abgefragt": jetzt, "org": "o", "repos": [], "runner": {"zustand": "unbekannt"}})
        self.assertTrue(ohne["ergebnisse"][-1]["warn"])
        for art in ("kein-token", "token-ungueltig", "keine-rechte", "nicht-erreichbar", "kontingent", "fehler", "unsinn"):
            e = einrichtung.verbindung_aus({"abfrage": art, "abgefragt": jetzt, "org": "o"})
            self.assertFalse(e["ok"], art)
            self.assertTrue(e["ergebnisse"][0]["fehler"], art)
        self.assertFalse(einrichtung.verbindung_aus({"abfrage": "ok", "abgefragt": jetzt - 60}, seit=jetzt)["fertig"])
        self.assertFalse(einrichtung.verbindung_aus(None, seit=jetzt)["fertig"])
        self.assertTrue(einrichtung.verbindung_aus({"abfrage": "ok", "abgefragt": jetzt + 1, "org": "o"}, seit=jetzt)["fertig"])


# ---------------------------------------------------------------- Sammler


class SammlerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.k = lade_konfig(self.d)
        self.k.token_datei.parent.mkdir(parents=True)
        self.k.auftraege_verz.mkdir(parents=True)
        (self.d / "actions-runner").mkdir()
        (self.d / "actions-runner" / ".runner").write_text(json.dumps({"agentName": "runner-vm-01"}))
        self.s = sammler.Sammler(self.k)
        self.s.naechste_erkennung = 1e12
        self.s.naechste_github = 1e12

    def tearDown(self):
        self.tmp.cleanup()

    def test_zuordnung_schreibt_runner_json_und_erkennt_neu(self):
        schreibe_erkennung(self.k, [fund("buildagent", "unbekannt", "unbekannt", server=None)])
        einrichtung.lege_auftrag(self.k.auftraege_verz, [{"id": "buildagent", "stand": "grund", "unit": "buildagent.service"}])
        self.s.auftrag_einrichtung(jetzt=1000.0, mono=500.0)
        self.assertEqual(json.loads(self.k.zuordnung_datei.read_text())["runner"]["buildagent"]["unit"], "buildagent.service")
        self.assertEqual(stat.S_IMODE(os.stat(self.k.zuordnung_datei).st_mode), 0o640)
        self.assertEqual(self.s.naechste_erkennung, 500.0)
        self.assertFalse(os.path.lexists(self.k.auftraege_verz / einrichtung.AUFTRAG_ZUORDNUNG))

    def test_neu_erkennen_hoechstens_alle_10_s(self):
        einrichtung.lege_auftrag_einfach(self.k.auftraege_verz, einrichtung.AUFTRAG_ERKENNUNG)
        self.s.auftrag_einrichtung(jetzt=1000.0, mono=500.0)
        self.assertEqual(self.s.naechste_erkennung, 500.0)
        self.s.naechste_erkennung = 1e12  # lief durch
        einrichtung.lege_auftrag_einfach(self.k.auftraege_verz, einrichtung.AUFTRAG_ERKENNUNG)
        self.s.auftrag_einrichtung(jetzt=1003.0, mono=503.0)
        self.assertEqual(self.s.naechste_erkennung, 510.0)  # nicht verworfen, nur verschoben

    def test_anforderung_waehrend_eines_laufs(self):
        self.s._erkennung = object()  # läuft gerade
        self.s.erkennung_anfordern(500.0)
        self.assertTrue(self.s._erkennung_nochmal)
        self.s._erkennung = None
        self.s._erkennung_beendet(530.0)
        self.assertEqual(self.s.naechste_erkennung, 530.0)
        self.assertFalse(self.s._erkennung_nochmal)

    def test_verbindung_pruefen_nur_fuer_den_github_runner(self):
        einrichtung.lege_auftrag_einfach(self.k.auftraege_verz, einrichtung.AUFTRAG_PRUEFEN, {"id": "anderer"})
        self.s.auftrag_einrichtung(jetzt=1000.0, mono=500.0)
        self.assertEqual(self.s.naechste_github, 1e12)
        einrichtung.lege_auftrag_einfach(self.k.auftraege_verz, einrichtung.AUFTRAG_PRUEFEN, {"id": "runner-vm-01"})
        self.s.auftrag_einrichtung(jetzt=1000.0, mono=500.0)
        self.assertEqual(self.s.naechste_github, 1000.0)
        self.s.naechste_github = 1e12
        einrichtung.lege_auftrag_einfach(self.k.auftraege_verz, einrichtung.AUFTRAG_PRUEFEN, {"id": "runner-vm-01"})
        self.s.auftrag_einrichtung(jetzt=1002.0, mono=502.0)
        self.assertEqual(self.s.naechste_github, 1010.0)

    def test_github_token_auftrag_folgt_keinem_symlink(self):
        geheim = self.d / "geheim"
        geheim.write_text(json.dumps({"token": "ghp_" + "a" * 36}))
        (self.k.auftraege_verz / "github-token").symlink_to(geheim)
        self.s.auftraege()
        self.assertFalse(self.k.token_datei.exists())
        self.assertFalse(os.path.lexists(self.k.auftraege_verz / "github-token"))
        self.assertTrue(geheim.exists())


# ---------------------------------------------------------------- Endpunkte


class ServerBasis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.k = lade_konfig(d)
        self.k.auftraege_verz.mkdir(parents=True)
        (d / "actions-runner").mkdir()
        (d / "actions-runner" / ".runner").write_text(json.dumps({"agentName": "runner-vm-01"}))
        schreibe_erkennung(self.k, [fund("runner-vm-01"), fund("buildagent", "unbekannt", "unbekannt", server=None)])
        self.app = server.App(self.k)
        self.srv = server.ThreadingHTTPServer(("127.0.0.1", 0), type("H", (server.Handler,), {"app": self.app}))
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.cookies: dict[str, str] = {}

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

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
        return r, (json.loads(inhalt) if inhalt else {})

    def code(self):
        zugang.schreibe_code(self.k.einrichtungscode_datei, "ABCD-2345")
        r, _ = self.anfrage("POST", "/api/einrichtung/code", {"code": "abcd2345"})
        self.assertEqual(r.status, 200)


class EndpunktTest(ServerBasis):
    def test_ohne_code_kein_zugriff(self):
        r, _ = self.anfrage("GET", "/api/einrichtung/runner")
        self.assertEqual(r.status, 401)
        for pfad in ("zuordnung", "erkennen", "pruefen"):
            r, _ = self.anfrage("POST", f"/api/einrichtung/runner/{pfad}", {"runner": [{"id": "a", "stand": "grund"}], "id": "a"})
            self.assertEqual(r.status, 401, pfad)
        self.assertEqual(list(self.k.auftraege_verz.iterdir()), [])

    def test_csrf(self):
        self.code()
        r, _ = self.anfrage("POST", "/api/einrichtung/runner/zuordnung", {"runner": [{"id": "a", "stand": "grund"}]}, origin=False)
        self.assertEqual(r.status, 403)
        r, _ = self.anfrage("POST", "/api/einrichtung/runner/erkennen", {}, typ="text/plain")
        self.assertEqual(r.status, 415)
        self.assertEqual(list(self.k.auftraege_verz.iterdir()), [])

    def test_funde_und_zuordnung(self):
        self.code()
        r, d = self.anfrage("GET", "/api/einrichtung/runner")
        self.assertEqual(r.status, 200)
        self.assertEqual([f["id"] for f in d["runner"]], ["runner-vm-01", "buildagent"])
        self.assertTrue(d["runner"][0]["primaer"])
        self.assertEqual(d["github"]["id"], "runner-vm-01")
        self.assertEqual(d["github"]["org"], "beispiel-org")
        self.assertNotIn("_diag", json.dumps(d))  # keine Pfade der Erkennung
        # ungültig: nichts wird abgelegt
        for schlecht in ([{"id": "buildagent", "stand": "grund", "server": "https://boese.example"}],
                         [{"id": "buildagent", "stand": "grund", "log": "/etc/shadow"}],
                         [{"id": "buildagent", "stand": "grund", "unit": "sshd.service"}],
                         [{"id": "../etc", "stand": "grund"}], "nein"):
            r, d = self.anfrage("POST", "/api/einrichtung/runner/zuordnung", {"runner": schlecht})
            self.assertEqual(r.status, 400, schlecht)
            self.assertIn("fehler", d)
        self.assertEqual(list(self.k.auftraege_verz.iterdir()), [])
        r, d = self.anfrage("POST", "/api/einrichtung/runner/zuordnung", {"runner": [
            {"id": "buildagent", "stand": "grund", "dienst": "unbekannt", "name": "Build-Agent", "unit": "buildagent.service",
             "log": "/var/log/buildagent/agent.log"}, {"id": "runner-vm-01", "stand": "ignoriert"}]})
        self.assertEqual(r.status, 202)
        self.assertFalse(self.k.zuordnung_datei.exists())  # schreibt nur der Sammler (root)
        auftrag = self.k.auftraege_verz / einrichtung.AUFTRAG_ZUORDNUNG
        self.assertEqual(stat.S_IMODE(os.stat(auftrag).st_mode), 0o600)
        r, d = self.anfrage("GET", "/api/einrichtung/runner")
        nach = {f["id"]: f for f in d["runner"]}
        self.assertEqual(nach["runner-vm-01"]["stand"], "ignoriert")  # Wahl übersteht das Neuladen
        self.assertEqual(nach["buildagent"]["name"], "Build-Agent")
        self.assertTrue(d["auftrag"]["zuordnung"])
        # Der Sammler übernimmt den Auftrag
        s = sammler.Sammler(self.k)
        self.k.zuordnung_datei.parent.mkdir(parents=True, exist_ok=True)
        s.auftrag_einrichtung(jetzt=1.0, mono=1.0)
        self.assertEqual(json.loads(self.k.zuordnung_datei.read_text())["runner"]["buildagent"]["log"], "/var/log/buildagent/agent.log")

    def test_erkennen_und_pruefen(self):
        self.code()
        r, d = self.anfrage("POST", "/api/einrichtung/runner/erkennen", {})
        self.assertEqual(r.status, 202)
        self.assertTrue((self.k.auftraege_verz / einrichtung.AUFTRAG_ERKENNUNG).is_file())
        r, d = self.anfrage("POST", "/api/einrichtung/runner/pruefen", {"id": "../x"})
        self.assertEqual(r.status, 400)
        r, d = self.anfrage("POST", "/api/einrichtung/runner/pruefen", {"id": "buildagent"})
        self.assertEqual(r.status, 200)
        self.assertTrue(d["fertig"])
        self.assertFalse(d["ok"])
        self.assertFalse((self.k.auftraege_verz / einrichtung.AUFTRAG_PRUEFEN).exists())
        r, d = self.anfrage("POST", "/api/einrichtung/runner/pruefen", {"id": "runner-vm-01"})
        self.assertEqual(r.status, 202)
        self.assertEqual(json.loads((self.k.auftraege_verz / einrichtung.AUFTRAG_PRUEFEN).read_text())["id"], "runner-vm-01")
        # Ergebnis des Sammlers in github.json → Ergebnisliste in GET
        (self.k.lauf_verz / "github.json").write_text(json.dumps({"abfrage": "token-ungueltig", "abgefragt": d["seit"] + 1, "org": "beispiel-org"}))
        r, d = self.anfrage("GET", "/api/einrichtung/runner")
        self.assertFalse(d["github"]["pruefung"]["ok"])
        self.assertEqual(d["github"]["pruefung"]["ergebnisse"][0]["text"], "Token ungültig oder abgelaufen.")
        r, _ = self.anfrage("POST", "/api/einrichtung/runner/unbekannt", {})
        self.assertEqual(r.status, 404)

    def test_nach_der_einrichtung(self):
        """Angemeldet: Runner-Endpunkte ja (Info › Runner), Token über die Oberfläche nein (E-22)."""
        self.code()
        r, _ = self.anfrage("POST", "/api/einrichtung/zugang", {"nutzer": "admin", "passwort": "ein langer satz zum merken"})
        self.assertEqual(r.status, 200)
        r, _ = self.anfrage("GET", "/api/einrichtung/runner")
        self.assertEqual(r.status, 200)  # Einrichtung noch offen (Code gilt)
        r, _ = self.anfrage("POST", "/api/einrichtung/fertig")
        self.assertEqual(r.status, 200)
        self.cookies.pop(server.COOKIE_EINRICHTUNG, None)
        r, _ = self.anfrage("GET", "/api/einrichtung/runner")
        self.assertEqual(r.status, 401)
        r, _ = self.anfrage("POST", "/api/anmelden", {"nutzer": "admin", "passwort": "ein langer satz zum merken"})
        self.assertEqual(r.status, 200)
        r, _ = self.anfrage("GET", "/api/einrichtung/runner")
        self.assertEqual(r.status, 200)
        r, _ = self.anfrage("POST", "/api/einrichtung/runner/zuordnung", {"runner": [{"id": "buildagent", "stand": "ignoriert"}]})
        self.assertEqual(r.status, 202)
        for pfad in ("/api/einrichtung/github/pruefen", "/api/einrichtung/github/speichern"):
            r, _ = self.anfrage("POST", pfad, {"org": "beispiel-org", "token": "ghp_" + "a" * 36})
            self.assertEqual(r.status, 401, pfad)
        self.assertFalse((self.k.auftraege_verz / "github-token").exists())

    def test_status_zaehlt_funde(self):
        r, d = self.anfrage("GET", "/api/einrichtung/status")
        self.assertEqual(r.status, 200)
        self.assertEqual(d["runnerAnzahl"], 2)
        self.assertNotIn("runner", d)  # Funde erst nach dem Code


# ---------------------------------------------------------------- Review #118


class ReviewTest(ServerBasis):
    """Nachträge aus dem Review: Forgejo-Prüfung über anbieter.json, 401-Text, Größe, Units, Einstufung."""

    def forgejo(self, server=True):
        schreibe_erkennung(self.k, [fund("runner-vm-01"), fund("runner-vm-02", "forgejo", "teil", server="https://git.example.org")])
        self.k.zuordnung_datei.parent.mkdir(parents=True, exist_ok=True)
        eintrag = {"server": "https://git.example.org", "org": "beispiel-org"} if server else {"name": "runner-vm-02"}
        self.k.zuordnung_datei.write_text(json.dumps({"runner": {"runner-vm-02": eintrag}}))

    def test_pruefen_forgejo_angebunden(self):
        self.forgejo()
        self.code()
        r, d = self.anfrage("GET", "/api/einrichtung/runner")
        self.assertEqual({f["id"]: f["anbindung"] for f in d["runner"]}, {"runner-vm-01": "github", "runner-vm-02": "angebunden"})
        r, d = self.anfrage("POST", "/api/einrichtung/runner/pruefen", {"id": "runner-vm-02"})
        self.assertEqual(r.status, 202)
        seit = d["seit"]
        self.assertEqual(json.loads((self.k.auftraege_verz / einrichtung.AUFTRAG_PRUEFEN).read_text())["id"], "runner-vm-02")
        (self.k.lauf_verz / "anbieter.json").write_text(json.dumps({"zeit": seit + 1, "runner": {"runner-vm-02": {
            "abfrage": "ok", "abgefragt": seit + 1, "org": "beispiel-org", "art": "forgejo", "serverVersion": "13.0.1",
            "repos": [{}] * 6, "runner": {"zustand": "unbekannt"}}}}))
        r, d = self.anfrage("GET", "/api/einrichtung/runner")
        p = d["anbieter"]["runner-vm-02"]["pruefung"]
        self.assertTrue(p["ok"])
        self.assertEqual(p["ergebnisse"][0]["text"], "Server erreichbar · Forgejo 13.0.1")
        self.assertTrue(p["ergebnisse"][-1]["warn"])
        # Sammler: nächste Runde der weiteren Dienste sofort
        s = sammler.Sammler(self.k)
        s.naechste_anbieter = 1e12
        s.auftrag_einrichtung(jetzt=1000.0, mono=1.0)
        self.assertEqual(s.naechste_anbieter, 1000.0)

    def test_pruefen_forgejo_ohne_server(self):
        self.forgejo(server=False)
        self.code()
        r, d = self.anfrage("POST", "/api/einrichtung/runner/pruefen", {"id": "runner-vm-02"})
        self.assertEqual(r.status, 200)
        self.assertIn("Server und Organisation fehlen", d["ergebnisse"][0]["text"])
        self.assertFalse((self.k.auftraege_verz / einrichtung.AUFTRAG_PRUEFEN).exists())

    def test_verbindung_anbieter_fehler(self):
        for art, teil in (("kein-token", "kein Token"), ("nicht-erreichbar", "nicht erreichbar"), ("token-ungueltig", "ungültig")):
            e = einrichtung.verbindung_anbieter({"abfrage": art, "abgefragt": 1.0, "org": "o"})
            self.assertFalse(e["ok"])
            self.assertIn(teil, e["ergebnisse"][0]["text"])
        self.assertFalse(einrichtung.verbindung_anbieter({"abfrage": "ok", "abgefragt": 1.0}, seit=5.0)["fertig"])
        # neu angebunden (#115, E-25): noch keine Runde – „läuft“, nicht „fehlgeschlagen“
        self.assertEqual(einrichtung.verbindung_anbieter({"abfrage": "ausstehend", "abgefragt": None}), {"fertig": False, "ok": False, "ergebnisse": []})

    def test_verbindung_anbieter_gitlab(self):
        """#126: GitLab nennt den Dienst, kennt keine Organisation und keine Repository-Zahl."""
        ok = einrichtung.verbindung_anbieter({"abfrage": "ok", "abgefragt": 1.0, "org": "", "repos": [],
                                              "runner": {"zustand": "online"}}, dienst="gitlab")
        self.assertTrue(ok["ok"])
        texte = [z["text"] for z in ok["ergebnisse"]]
        self.assertEqual(texte[:2], ["Server erreichbar · GitLab", "Token gültig"])
        self.assertTrue(all("Organisation" not in t and "Repositories" not in t for t in texte))
        self.assertIn("Runner beim Server gefunden", texte[2])
        nicht = einrichtung.verbindung_anbieter({"abfrage": "ok", "abgefragt": 1.0, "org": "", "runner": {"zustand": "unbekannt"}}, dienst="gitlab")
        self.assertTrue(nicht["ergebnisse"][2]["warn"])
        self.assertIn("nicht gefunden oder nicht eindeutig", nicht["ergebnisse"][2]["text"])
        self.assertNotIn("Organisations-Recht", nicht["ergebnisse"][2]["text"])
        # keine leere Organisation in der Fehlermeldung
        rechte = einrichtung.verbindung_anbieter({"abfrage": "keine-rechte", "abgefragt": 1.0, "org": ""}, dienst="gitlab")
        self.assertEqual(rechte["ergebnisse"][0]["text"], "Token ohne Zugriff.")
        # Forgejo unverändert
        fj = einrichtung.verbindung_anbieter({"abfrage": "ok", "abgefragt": 1.0, "org": "beispiel-org", "art": "forgejo", "repos": [1, 2]}, dienst="forgejo")
        self.assertEqual(fj["ergebnisse"][0]["text"], "Server erreichbar · Forgejo")
        self.assertIn("Organisation beispiel-org gefunden, 2 Repositories", fj["ergebnisse"][1]["text"])

    def test_abgelaufener_code_verweist_auf_die_vm(self):
        self.code()
        r, _ = self.anfrage("POST", "/api/einrichtung/zugang", {"nutzer": "admin", "passwort": "ein langer satz zum merken"})
        self.assertEqual(r.status, 200)
        with self.app.sperre:
            self.app.einrichtung.clear()  # Code abgelaufen (60 min) oder Dienst neu gestartet
        for pfad, daten in (("/api/einrichtung/github/pruefen", {"org": "beispiel-org", "token": "ghp_" + "a" * 36}),
                            ("/api/einrichtung/github/speichern", {"org": "beispiel-org", "token": "ghp_" + "a" * 36}),
                            ("/api/einrichtung/runner/pruefen", {"id": "runner-vm-01"})):
            r, d = self.anfrage("POST", pfad, daten)
            self.assertEqual(r.status, 401, pfad)
            self.assertIn("einrichten.sh zugang <runner>", d["fehler"], pfad)
        self.assertFalse((self.k.auftraege_verz / "github-token").exists())

    def test_auftrag_zu_gross(self):
        self.code()
        lang = "/var/log/" + "/".join(["a" * 120] * 6) + "/agent.log"
        self.assertTrue(einrichtung.pruefe_log(lang))
        status, d = [], {}
        for runde in range(10):  # je Anfrage höchstens 16 KB, der offene Auftrag wächst bis über 64 KB
            eintraege = [{"id": f"r{runde}-{i}", "stand": "grund", "log": lang} for i in range(18)]
            r, d = self.anfrage("POST", "/api/einrichtung/runner/zuordnung", {"runner": eintraege})
            status.append(r.status)
            if r.status != 202:
                break
        self.assertEqual(status[0], 202)
        self.assertEqual(status[-1], 400)
        self.assertIn("Zu viele offene Änderungen", d["fehler"])
        self.assertLessEqual(os.path.getsize(self.k.auftraege_verz / einrichtung.AUFTRAG_ZUORDNUNG), einrichtung.MAX_AUFTRAG)

    def test_unit_positivliste(self):
        self.code()
        r, d = self.anfrage("POST", "/api/einrichtung/runner/zuordnung", {"runner": [{"id": "x", "stand": "grund", "unit": "erfunden.service"}]})
        self.assertEqual(r.status, 400)
        self.assertIn("gibt es auf der VM nicht", d["fehler"])
        r, _ = self.anfrage("POST", "/api/einrichtung/runner/zuordnung", {"runner": [{"id": "x", "stand": "grund", "unit": "buildagent.service"}]})
        self.assertEqual(r.status, 202)  # Unit eines Funds
        wurzel = Path(self.tmp.name) / "wurzel"
        (wurzel / "etc/systemd/system").mkdir(parents=True)
        (wurzel / "etc/systemd/system/agent@.service").write_text("[Service]\n")
        self.assertTrue(einrichtung.unit_vorhanden("agent@2.service", set(), str(wurzel)))
        self.assertFalse(einrichtung.unit_vorhanden("nicht.service", set(), str(wurzel)))
        # Der Sammler verwirft eine unbekannte Unit, auch wenn der Auftrag am Webserver vorbei entstand
        (self.k.auftraege_verz / einrichtung.AUFTRAG_ZUORDNUNG).write_text(json.dumps({"runner": [
            {"id": "x", "stand": "grund", "unit": "erfunden.service"}, {"id": "y", "stand": "ignoriert"}]}))
        self.k.zuordnung_datei.parent.mkdir(parents=True, exist_ok=True)
        self.assertEqual(einrichtung.verarbeite_auftrag(self.k.auftraege_verz, self.k.zuordnung_datei, self.k.lauf_verz, str(wurzel)), 1)
        self.assertEqual(json.loads(self.k.zuordnung_datei.read_text())["runner"], {"y": {"stand": "ignoriert"}})

    def test_log_pfad_gross_klein(self):
        self.assertIsNone(einrichtung.pruefe_log("/var/log/Runner-Monitor/a.log"))
        self.assertIsNone(einrichtung.pruefe_log("/opt/RUNNER-MONITOR-alt/a.log"))

    def test_einstufung_wird_geprueft(self):
        from runner_monitor import erkennung
        self.assertIsNotNone(erkennung.pruefe_ergebnis(json.dumps({"zeit": 1.0, "runner": [fund("a")]}).encode()))
        for falsch in ("super", None, 3):
            roh = json.dumps({"zeit": 1.0, "runner": [fund("a", einstufung=falsch)]}).encode()
            self.assertIsNone(erkennung.pruefe_ergebnis(roh), falsch)


if __name__ == "__main__":
    unittest.main()
