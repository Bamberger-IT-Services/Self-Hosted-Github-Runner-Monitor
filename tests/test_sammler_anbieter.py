"""Sammler fragt alle angebundenen Runner ab (#115): je Runner ein eigener Faden mit Frist, höchstens
MAX_GLEICHZEITIG zugleich, keine Fadenlecks; GitLab im Sammler; Fehler als Meldung mit Runner.

Kein Netz: Attrappen bzw. Server auf 127.0.0.1. Namen: runner-vm-0x, beispiel-org, git.example.org.
"""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from runner_monitor import runner, sammler, zustand
from runner_monitor.anbieter import forgejo as fj
from runner_monitor.anbieter import gitlab
from runner_monitor.anbieter import token as zugangsdaten
from tests.test_anbieter import fund, lade_konfig, registriere_runner
from tests.test_forgejo import TOKEN, Attrappe, lade, starte_troepfelnd
from tests.test_gitlab import TOKEN as GL_TOKEN
from tests.test_gitlab import Testserver as GitLabServer

ECHTER_KLIENT = fj.Klient


def faeden(rid: str) -> list[threading.Thread]:
    return [f for f in threading.enumerate() if f.name == f"anbieter-{rid}" and f.is_alive()]


def warte(bedingung, frist: float = 10.0) -> bool:
    ende = time.monotonic() + frist
    while time.monotonic() < ende:
        if bedingung():
            return True
        time.sleep(0.02)
    return bedingung()


class Basis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.k = lade_konfig(self.d)
        (self.d / "lauf").mkdir()
        self.k.token_datei.parent.mkdir(parents=True)
        registriere_runner(self.d)
        self.antworten = lade("forgejo-17.json")

    def runner(self, eintraege: dict[str, dict], dienst: str = "forgejo") -> None:
        """Funde mit Unit, runner.json und Token je Runner."""
        funde = [fund(rid, e.pop("_dienst", dienst), unit=f"{rid}.service") for rid, e in eintraege.items()]
        (self.d / "lauf" / "erkennung.json").write_text(json.dumps({"zeit": 1.0, "runner": funde}))
        self.k.zuordnung_datei.write_text(json.dumps({"version": 1, "runner": eintraege}))
        for rid in eintraege:
            zugangsdaten.schreibe(self.k.zugang_verz, rid, TOKEN)

    def datei(self) -> dict:
        try:
            return json.loads((self.k.lauf_verz / "anbieter.json").read_text())["runner"]
        except (OSError, ValueError):
            return {}


def ergebnis_ok(**mehr) -> dict:
    return {"org": "beispiel-org", "abfrage": "ok", "abgefragt": time.time(), "letzterErfolg": time.time(), "tokenAblauf": None,
            "kontingent": {}, "repos": [{"name": "web-portal", "privat": False, "laeuft": 0, "wartet": 0}],
            "runner": {"zustand": "online"}, "job": None, "letzteJobs": [], "fehler": "", **mehr}


class FaedenTest(Basis):
    def test_troepfelnder_server_blockiert_den_anderen_runner_nicht(self):
        """Runner A an einem tröpfelnden Server (ein Byte je Sekunde), Runner B normal: B ist nach Sekundenbruchteilen
        fertig, A läuft in seinem eigenen Faden bis zu seiner Frist und meldet dann „nicht erreichbar“."""
        server, _ = starte_troepfelnd()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.runner({"runner-vm-02": {"server": f"http://127.0.0.1:{server.server_address[1]}", "org": "beispiel-org", "http_erlaubt": True},
                     "runner-vm-04": {"server": "https://git.example.org", "org": "beispiel-org"}})
        s = sammler.Sammler(self.k)

        def klient(server_adr, token, **rest):
            if server_adr.startswith("http://127.0.0.1"):
                return ECHTER_KLIENT(server_adr, token, **rest)
            return Attrappe(self.antworten, token=token, server=server_adr)

        with mock.patch.object(fj, "Klient", side_effect=klient), mock.patch.object(fj, "ZEITLIMIT", 2.0):
            beginn = time.monotonic()
            s.anbieter_takt(1000.0)
            self.assertLess(time.monotonic() - beginn, 0.5, "anbieter_takt blockiert nie")
            self.assertTrue(warte(lambda: self.datei().get("runner-vm-04", {}).get("abfrage") == "ok", 3))
            self.assertLess(time.monotonic() - beginn, 2.0, "B wartet nicht auf A")
            self.assertTrue(faeden("runner-vm-02"), "A läuft noch in seinem eigenen Faden")
            self.assertNotIn("runner-vm-02", self.datei())
            self.assertTrue(warte(lambda: not faeden("runner-vm-02"), 10))
        erg = self.datei()
        self.assertEqual(erg["runner-vm-02"]["abfrage"], "nicht-erreichbar")
        self.assertEqual(erg["runner-vm-04"]["abfrage"], "ok")
        self.assertEqual(len(erg["runner-vm-04"]["repos"]), 2)

    def test_hoechstens_vier_zugleich_und_alle_kommen_dran(self):
        self.runner({f"runner-vm-{i:02d}": {"server": "https://git.example.org", "org": "beispiel-org"} for i in range(2, 9)})
        s = sammler.Sammler(self.k)
        frei = threading.Event()
        zaehler = {"jetzt": 0, "hoechst": 0}
        sperre = threading.Lock()

        def abfrage(a, speicher, letzter_erfolg=None, token=None):  # noqa: ARG001
            with sperre:
                zaehler["jetzt"] += 1
                zaehler["hoechst"] = max(zaehler["hoechst"], zaehler["jetzt"])
            frei.wait(10)
            with sperre:
                zaehler["jetzt"] -= 1
            return ergebnis_ok()

        with mock.patch.object(fj.Forgejo, "abfrage", abfrage):
            s.anbieter_takt(1000.0)
            self.assertTrue(warte(lambda: zaehler["jetzt"] == sammler.MAX_GLEICHZEITIG, 3))
            time.sleep(0.1)
            s.anbieter_takt(1002.0)  # weitere Takte starten keine fünfte Abfrage
            self.assertEqual(len(s._anbieter_laeufe), sammler.MAX_GLEICHZEITIG)
            self.assertEqual(len(s._anbieter_wartend), 3)
            frei.set()
            self.assertTrue(warte(lambda: (s.anbieter_takt(1004.0), len(self.datei()) == 7)[1], 5))
        self.assertEqual(zaehler["hoechst"], sammler.MAX_GLEICHZEITIG)
        self.assertTrue(warte(lambda: not s._anbieter_laeufe, 3))

    def test_rundenfrist_und_keine_fadenlecks(self):
        """Eine hängende Runde: nach RUNDENFRIST „nicht erreichbar“ (letzter guter Stand bleibt), nie ein zweiter
        Faden für denselben Runner, nach ihrem Ende wieder regulär."""
        self.runner({"runner-vm-02": {"server": "https://git.example.org", "org": "beispiel-org"}})
        s = sammler.Sammler(self.k)
        (self.k.lauf_verz / "anbieter.json").write_text(json.dumps({"zeit": 1, "runner": {"runner-vm-02": ergebnis_ok(
            job={"name": "build"}, letzterErfolg=500.0)}}))
        frei = threading.Event()
        aufrufe = []

        def abfrage(a, speicher, letzter_erfolg=None, token=None):  # noqa: ARG001
            aufrufe.append(time.monotonic())
            frei.wait(10)
            return ergebnis_ok()

        with mock.patch.object(fj.Forgejo, "abfrage", abfrage), mock.patch.object(sammler, "RUNDENFRIST", 0.3), \
             self.assertLogs("runner_monitor.sammler", "WARNING") as protokoll:
            s.anbieter_takt(1000.0)
            self.assertTrue(warte(lambda: aufrufe, 2))
            time.sleep(0.4)
            s.anbieter_takt(1002.0)
            erg = self.datei()["runner-vm-02"]
            self.assertEqual(erg["abfrage"], "nicht-erreichbar")
            self.assertIn("Frist", erg["fehler"])
            self.assertEqual((erg["job"], erg["letzterErfolg"]), ({"name": "build"}, 500.0))  # letzter guter Stand
            for zeitpunkt in (1031.0, 1062.0, 1093.0):  # wieder fällig, aber die Runde hängt noch
                s.anbieter_takt(zeitpunkt)
            self.assertEqual(len(faeden("runner-vm-02")), 1)
            self.assertEqual(len(aufrufe), 1)
            frei.set()
            self.assertTrue(warte(lambda: not faeden("runner-vm-02"), 3))
        self.assertEqual(self.datei()["runner-vm-02"]["abfrage"], "ok")  # die späte Antwort zählt
        self.assertEqual(sum("hängt" in z for z in protokoll.output), 1)  # einmal gemeldet, nicht je Takt
        with mock.patch.object(fj.Forgejo, "abfrage", abfrage):
            s.anbieter_takt(1124.0)
            self.assertTrue(warte(lambda: len(aufrufe) == 2 and not faeden("runner-vm-02"), 3))

    def test_nicht_mehr_angebunden_wird_verworfen(self):
        self.runner({"runner-vm-02": {"server": "https://git.example.org", "org": "beispiel-org"}})
        s = sammler.Sammler(self.k)
        with mock.patch.object(fj.Forgejo, "abfrage", lambda *a, **k: ergebnis_ok()):
            s.anbieter_abfragen()
            self.assertIn("runner-vm-02", self.datei())
            self.k.zuordnung_datei.write_text(json.dumps({"version": 1, "runner": {}}))
            s.anbieter_takt(2000.0)
        self.assertEqual(self.datei(), {})
        self.assertEqual(s._anbieter_speicher, {})

    def test_letzter_stand_ueberdauert_den_neustart(self):
        self.runner({"runner-vm-02": {"server": "https://git.example.org", "org": "beispiel-org"}})
        (self.k.lauf_verz / "anbieter.json").write_text(json.dumps({"zeit": 1, "runner": {
            "runner-vm-02": ergebnis_ok(job={"name": "build"}), "runner-vm-99": ergebnis_ok()}}))
        s = sammler.Sammler(self.k)  # frisch gestartet
        with mock.patch.object(fj, "Klient", side_effect=lambda server, token, **_: Attrappe(
                {}, token=token, server=server, fehler={"/version": fj.ForgejoFehler("nicht-erreichbar", "weg")})):
            s.anbieter_abfragen()
        erg = self.datei()
        self.assertEqual(list(erg), ["runner-vm-02"])  # nicht mehr angebunden: weg
        self.assertEqual((erg["runner-vm-02"]["abfrage"], erg["runner-vm-02"]["job"]), ("nicht-erreichbar", {"name": "build"}))

    def test_ein_takt_bleibt_schnell(self):
        self.runner({"runner-vm-02": {"server": "https://git.example.org", "org": "beispiel-org"}})
        s = sammler.Sammler(self.k)
        frei = threading.Event()
        with mock.patch.object(fj.Forgejo, "abfrage", lambda *a, **k: (frei.wait(10), ergebnis_ok())[1]), \
             mock.patch.object(s, "github"), mock.patch.object(s, "release", return_value={}), mock.patch.object(s, "erkennung"), \
             mock.patch.object(sammler, "docker_container", return_value={}), mock.patch.object(s, "auto_update"):
            beginn = time.monotonic()
            s.ein_takt(1000.0)
            s.ein_takt(1002.0)
            self.assertLess(time.monotonic() - beginn, 0.5)
            frei.set()
        self.assertTrue(warte(lambda: not s._anbieter_laeufe, 3))


class GitLabImSammlerTest(Basis):
    def setUp(self):
        super().setUp()
        self.gl = GitLabServer()
        self.addCleanup(self.gl.schliessen)
        self.gl.normal()
        self.runner({"runner-vm-03": {"server": self.gl.url, "http_erlaubt": True, "_dienst": "gitlab"}})
        zugangsdaten.schreibe(self.k.zugang_verz, "runner-vm-03", GL_TOKEN)

    def zustand(self) -> zustand.Zustand:
        z = zustand.Zustand(self.k)
        unit = "actions.runner.beispiel-org.runner-vm-01.service"
        with mock.patch.object(runner, "finde_unit", return_value=unit), \
             mock.patch.object(runner, "dienst_status", return_value={"zustand": "aktiv", "seit": 10.0, "grund": None}), \
             mock.patch.object(runner, "runner_version", return_value="2.338.1"):
            z.ein_takt(0)
        return z

    def test_gitlab_ohne_organisation_angebunden(self):
        s = sammler.Sammler(self.k)
        self.assertEqual([(a.k.id, a.k.dienst, a.k.org) for a in s.anbindungen()], [("runner-vm-03", "gitlab", "")])
        s.anbieter_abfragen()
        erg = self.datei()["runner-vm-03"]
        self.assertEqual(erg["abfrage"], "ok", erg.get("fehler"))
        self.assertNotIn(GL_TOKEN, (self.k.lauf_verz / "anbieter.json").read_text())
        self.assertTrue(all(h.get("private-token") == GL_TOKEN for _, h in self.gl.anfragen))
        r = next(r for r in self.zustand().bereiche["runner"] if r["id"] == "runner-vm-03")
        self.assertEqual((r["dienst"], r["stand"], r["server"]), ("gitlab", "angebunden", self.gl.url))
        self.assertEqual(r["faehig"], gitlab.GitLab.FAEHIG)  # von Hand angebunden: was der Adapter liefert
        self.assertEqual(r["status"]["zustand"], "job")
        self.assertEqual((r["job"]["name"], r["job"]["schritt"], r["job"]["schritte"]), ("unit-tests", None, []))
        self.assertEqual(len(r["letzteJobs"]), 3)
        self.assertEqual(r["labels"], ["self-hosted", "linux"])
        self.assertTrue(r["jobsJeRepository"]["wartetUnbekannt"])

    def test_fehler_als_meldung_mit_runner(self):
        s = sammler.Sammler(self.k)
        for antwort, erwartet in (((401, {"message": "401"}), {"id": "token", "stufe": "fehler", "daten": {"abfrage": "token-ungueltig"}}),
                                  ((403, {"message": "403"}), {"id": "token", "stufe": "fehler", "daten": {"abfrage": "keine-rechte"}})):
            self.gl.antworten = {"/api/v4/personal_access_tokens/self": antwort, "/api/v4/runners": antwort}
            s.anbieter_abfragen()
            meldungen = self.zustand().bereiche["meldungen"]
            self.assertIn({**erwartet, "runner": "runner-vm-03", "dienst": "gitlab"}, meldungen)
        self.gl.schliessen()  # Server weg: nicht erreichbar
        s.anbieter_abfragen()
        m = [m for m in self.zustand().bereiche["meldungen"] if m["runner"] == "runner-vm-03"]
        self.assertEqual([(x["id"], x["daten"]["abfrage"]) for x in m], [("abfrage", "nicht-erreichbar")])


if __name__ == "__main__":
    unittest.main()
