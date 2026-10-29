"""einrichten.sh zugang für Forgejo, Gitea, GitLab (#120, E-21, E-22, E-26): Server und Organisation prüfen,
runner.json atomar schreiben, Token neu bei neuer Adresse, Verbindungsprüfung. Kein Netz außer 127.0.0.1."""
import io
import json
import os
import re
import stat
import subprocess
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from runner_monitor.anbieter import anbindung
from runner_monitor.anbieter import token as zugangsdaten
from tests.test_forgejo import starte

WURZEL = Path(__file__).resolve().parent.parent
TOKEN_ALT = "alt" + "a" * 37
TOKEN_NEU = "neu" + "b" * 37


def fund(rid="runner-vm-02", dienst="forgejo", unit="forgejo-runner.service", server="https://srv.example.org", **mehr):
    return {"id": rid, "name": rid, "dienst": dienst, "server": server, "version": None, "grad": "sicher",
            "merkmale": [], "einstufung": "teil", "stand": "offen", "unit": unit, "log": None,
            "faehig": {"status": True, "jobs": False, "schritte": False, "logs": True, "updates": False},
            "aktiv": True, "grund": None, **mehr}


class Basis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.etc = self.d / "etc"
        self.etc.mkdir()
        self.zuordnung = self.etc / "runner.json"
        self.zugang = self.etc / "zugang"
        self.erkennung = self.d / "lauf" / "erkennung.json"
        self.erkennung.parent.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def schreibe_runner(self, runner: dict, **mehr):
        self.zuordnung.write_text(json.dumps({"version": 1, "runner": runner, **mehr}))

    def schreibe_erkennung(self, *funde):
        self.erkennung.write_text(json.dumps({"zeit": time.time(), "runner": list(funde)}))

    def lies_runner(self) -> dict:
        return json.loads(self.zuordnung.read_text())

    def token(self, rid="runner-vm-02") -> str:
        return zugangsdaten.lies(self.zugang / f"{rid}.token")


class PruefenTest(unittest.TestCase):
    def test_server_gut(self):
        self.assertEqual(anbindung.pruefe_server("https://Srv.Example.org/"), ("https://srv.example.org", False))
        self.assertEqual(anbindung.pruefe_server("  https://srv.example.org:3000/forgejo  "), ("https://srv.example.org:3000/forgejo", False))
        self.assertEqual(anbindung.pruefe_server("http://192.0.2.10:3000"), ("http://192.0.2.10:3000", True))

    def test_server_schlecht(self):
        for schlecht in ("", "   ", None, 3, "srv.example.org", "ftp://srv.example.org", "https://u:p@srv.example.org",
                         "https://srv.example.org?x=1", "https://srv.example.org#a", "https://srv.example.org/api/v1",
                         "https://srv.example.org/API/v4/", "https://srv.example.org/api", "https://srv example.org",
                         "https://srv.example.org/\x1b[31m", "https://-x.example.org", "https://srv.example.org/../x", "https://srv.example.org/a/./b", "https://srv.example.org/%2e%2e",
                         "https://" + "a" * 600):
            with self.assertRaises(anbindung.AnbindungFehler, msg=repr(schlecht)):
                anbindung.pruefe_server(schlecht)

    def test_org(self):
        self.assertEqual(anbindung.pruefe_org_eingabe("beispiel-org"), "beispiel-org")
        self.assertEqual(anbindung.pruefe_org_eingabe("Team_1.x"), "Team_1.x")
        for schlecht in ("", "..", "../x", "a/b", "-x", "a b", "x" * 65, None):
            with self.assertRaises(anbindung.AnbindungFehler, msg=repr(schlecht)):
                anbindung.pruefe_org_eingabe(schlecht)

    def test_token(self):
        self.assertEqual(anbindung.pruefe_token(" " + TOKEN_NEU + "\n"), TOKEN_NEU)
        for schlecht in ("", "kurz", "mit leerzeichen drin 123456", "x" * 513, "ä" * 20):
            with self.assertRaises(anbindung.AnbindungFehler):
                anbindung.pruefe_token(schlecht)

    def test_kommandozeile_pruefe(self):
        for wert, rc in (("https://srv.example.org", 0), ("http://192.0.2.10", 4), ("srv.example.org", 2), ("-x", 2)):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(anbindung.main(["pruefe-server", "--", wert]), rc, wert)
        with redirect_stdout(io.StringIO()) as aus:
            self.assertEqual(anbindung.main(["pruefe-org", "--", "beispiel-org"]), 0)
        self.assertEqual(aus.getvalue(), "beispiel-org\n")


class InfoTest(Basis):
    def test_dienst_vorschlag_token(self):
        self.schreibe_erkennung(fund(), fund("ohne-unit", unit=None, server="https://fremd.example.org"),
                                fund("gl", dienst="gitlab", unit="gitlab-runner.service"))
        self.assertTrue(zugangsdaten.schreibe(self.zugang, "runner-vm-02", TOKEN_ALT))
        i = anbindung.info("runner-vm-02", self.erkennung, self.zuordnung, self.zugang)
        self.assertEqual((i["dienst"], i["braucht_org"], i["token"], i["vorschlag"], i["server"]),
                         ("forgejo", 1, 1, "https://srv.example.org", ""))
        # ohne Unit kein Vorschlag (E-17/E-18), GitLab ohne Organisation
        self.assertEqual(anbindung.info("ohne-unit", self.erkennung, self.zuordnung, self.zugang)["vorschlag"], "")
        gl = anbindung.info("gl", self.erkennung, self.zuordnung, self.zugang)
        self.assertEqual((gl["dienst"], gl["braucht_org"], gl["token"]), ("gitlab", 0, 0))

    def test_zuordnung_hat_vorrang(self):
        self.schreibe_erkennung(fund(dienst="unbekannt"))
        self.schreibe_runner({"runner-vm-02": {"dienst": "gitea", "server": "https://srv.example.org", "org": "o",
                                               "http_erlaubt": True, "stand": "grund"}})
        i = anbindung.info("runner-vm-02", self.erkennung, self.zuordnung, self.zugang)
        self.assertEqual((i["dienst"], i["server"], i["org"], i["http"], i["stand"], i["vorschlag"]),
                         ("gitea", "https://srv.example.org", "o", 1, "grund", ""))

    def test_unbekannt_und_ohne_dateien(self):
        i = anbindung.info("nirgends", None, self.zuordnung, self.zugang)
        self.assertEqual((i["dienst"], i["gefunden"]), ("unbekannt", 0))
        with self.assertRaises(anbindung.AnbindungFehler):
            anbindung.info("../x", None, self.zuordnung, self.zugang)

    def test_ausgabe_nur_schluessel_wert(self):
        self.schreibe_erkennung(fund())
        with redirect_stdout(io.StringIO()) as aus:
            self.assertEqual(anbindung.main(["info", "--runner", "runner-vm-02", "--erkennung", str(self.erkennung),
                                             "--zuordnung", str(self.zuordnung), "--zugang-verz", str(self.zugang)]), 0)
        for zeile in aus.getvalue().splitlines():
            self.assertRegex(zeile, r"^[a-z_]+=[^\s|]*$")


class SetzeTest(Basis):
    def setze(self, server="https://srv.example.org", rid="runner-vm-02", **mehr):
        return anbindung.setze(rid, self.zuordnung, self.zugang, server, **mehr)

    def test_erstes_mal_schreibt_atomar_mit_rechten(self):
        zeilen = self.setze(org="beispiel-org", token=TOKEN_NEU)
        daten = self.lies_runner()
        self.assertEqual(daten, {"version": 1, "runner": {"runner-vm-02": {"server": "https://srv.example.org", "org": "beispiel-org"}}})
        self.assertEqual(stat.S_IMODE(os.stat(self.zuordnung).st_mode), 0o640)
        self.assertEqual(self.token(), TOKEN_NEU)
        self.assertEqual(stat.S_IMODE(os.stat(self.zugang / "runner-vm-02.token").st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.zugang).st_mode), 0o700)
        self.assertEqual(sorted(p.name for p in self.etc.iterdir()), ["runner.json", "zugang"])  # keine Reste
        self.assertNotIn(TOKEN_NEU, repr(zeilen))

    def test_andere_felder_und_runner_bleiben(self):
        self.schreibe_runner({"runner-vm-02": {"stand": "ignoriert", "name": "Bau", "unit": "forgejo-runner.service",
                                               "log": None, "eigenes": [1, 2], "http_erlaubt": True,
                                               "server": "http://192.0.2.10"},
                              "anderer": {"server": "https://x.example.org", "org": "y", "http_erlaubt": True}},
                             kommentar="von Hand")
        self.setze(org="beispiel-org", token=TOKEN_NEU)
        daten = self.lies_runner()
        self.assertEqual(daten["kommentar"], "von Hand")
        self.assertEqual(daten["runner"]["anderer"], {"server": "https://x.example.org", "org": "y", "http_erlaubt": True})
        self.assertEqual(daten["runner"]["runner-vm-02"], {"stand": "ignoriert", "name": "Bau", "unit": "forgejo-runner.service",
                                                          "log": None, "eigenes": [1, 2], "server": "https://srv.example.org",
                                                          "org": "beispiel-org"})  # http_erlaubt entfällt mit https

    def test_http_nur_mit_erlaubnis(self):
        with self.assertRaises(anbindung.AnbindungFehler):
            self.setze("http://192.0.2.10:3000", token=TOKEN_NEU)
        self.assertFalse(self.zuordnung.exists())
        self.assertFalse(self.zugang.exists())
        self.setze("http://192.0.2.10:3000", http_erlaubt=True, token=TOKEN_NEU)
        self.assertIs(self.lies_runner()["runner"]["runner-vm-02"]["http_erlaubt"], True)

    def test_ungueltiges_wird_abgelehnt_ohne_schreiben(self):
        for argumente in ({"server": "https://u@srv.example.org"}, {"server": "https://srv.example.org/api/v1"},
                          {"org": "../x"}, {"token": "kurz"}, {"rid": "../x"}):
            with self.assertRaises(anbindung.AnbindungFehler, msg=argumente):
                self.setze(**{"server": "https://srv.example.org", "token": TOKEN_NEU, **argumente})
        self.assertFalse(self.zuordnung.exists())
        self.assertFalse(self.zugang.exists())

    def test_gleiche_adresse_token_bleibt(self):
        self.schreibe_runner({"runner-vm-02": {"server": "https://SRV.example.org/", "org": "alt"}})
        zugangsdaten.schreibe(self.zugang, "runner-vm-02", TOKEN_ALT)
        zeilen = self.setze(org="neu")
        self.assertEqual(self.token(), TOKEN_ALT)
        self.assertEqual(self.lies_runner()["runner"]["runner-vm-02"]["org"], "neu")
        self.assertIn("Token unverändert", " ".join(t for _, t in zeilen))

    def test_neue_adresse_ohne_neues_token_aendert_nichts(self):
        """E-22: ein vorhandenes Token geht nie an eine neue Adresse."""
        for alt in ({"server": "https://srv.example.org"}, {}, {"server": "https://kaputt.example.org?x"}):
            with self.subTest(alt=alt):
                self.schreibe_runner({"runner-vm-02": dict(alt)})
                vorher = self.zuordnung.read_bytes()
                zugangsdaten.schreibe(self.zugang, "runner-vm-02", TOKEN_ALT)
                with self.assertRaises(anbindung.AnbindungFehler):
                    self.setze("https://anders.example.org", org="o")
                self.assertEqual(self.zuordnung.read_bytes(), vorher)
                self.assertEqual(self.token(), TOKEN_ALT)
        # auch https → http (gleicher Host) ist eine neue Adresse
        self.schreibe_runner({"runner-vm-02": {"server": "https://srv.example.org"}})
        with self.assertRaises(anbindung.AnbindungFehler):
            self.setze("http://srv.example.org", http_erlaubt=True)

    def test_neue_adresse_mit_neuem_token(self):
        self.schreibe_runner({"runner-vm-02": {"server": "https://srv.example.org", "org": "o"}})
        zugangsdaten.schreibe(self.zugang, "runner-vm-02", TOKEN_ALT)
        zeilen = self.setze("https://anders.example.org", org="o", token=TOKEN_NEU)
        self.assertEqual(self.token(), TOKEN_NEU)
        self.assertEqual(self.lies_runner()["runner"]["runner-vm-02"]["server"], "https://anders.example.org")
        text = " ".join(t for _, t in zeilen)
        self.assertIn("bisheriges Token entfernt", text)
        self.assertNotIn(TOKEN_ALT, text)
        self.assertNotIn(TOKEN_NEU, text)

    def test_reihenfolge_nie_altes_token_an_neuer_adresse(self):
        """Scheitert das Schreiben von runner.json oder des Tokens, bleibt höchstens „kein Token“."""
        self.schreibe_runner({"runner-vm-02": {"server": "https://srv.example.org", "org": "o"}})
        zugangsdaten.schreibe(self.zugang, "runner-vm-02", TOKEN_ALT)
        with mock.patch("runner_monitor.einrichtung.schreibe_zuordnung", side_effect=OSError(28, "voll")):
            with self.assertRaises(anbindung.AnbindungFehler):
                self.setze("https://anders.example.org", org="o", token=TOKEN_NEU)
        self.assertEqual(self.lies_runner()["runner"]["runner-vm-02"]["server"], "https://srv.example.org")
        self.assertEqual(self.token(), "")  # altes Token weg, neues nicht an die alte Adresse
        zugangsdaten.schreibe(self.zugang, "runner-vm-02", TOKEN_ALT)
        with mock.patch.object(zugangsdaten, "schreibe", side_effect=OSError(13, "verboten")):
            with self.assertRaises(anbindung.AnbindungFehler) as f:
                self.setze("https://anders.example.org", org="o", token=TOKEN_NEU)
        self.assertNotIn(TOKEN_NEU, str(f.exception))
        self.assertEqual(self.lies_runner()["runner"]["runner-vm-02"]["server"], "https://anders.example.org")
        self.assertEqual(self.token(), "")

    def test_stand_grund_nur_auf_wunsch(self):
        self.schreibe_runner({"runner-vm-02": {"stand": "grund"}, "b": {"stand": "grund"}})
        self.setze(org="o", token=TOKEN_NEU)
        self.assertEqual(self.lies_runner()["runner"]["runner-vm-02"]["stand"], "grund")
        self.setze(org="o", stand_aufheben=True)
        daten = self.lies_runner()["runner"]
        self.assertNotIn("stand", daten["runner-vm-02"])
        self.assertEqual(daten["b"], {"stand": "grund"})
        self.schreibe_runner({"runner-vm-02": {"stand": "ignoriert", "server": "https://srv.example.org"}})
        self.setze(org="o", stand_aufheben=True)
        self.assertEqual(self.lies_runner()["runner"]["runner-vm-02"]["stand"], "ignoriert")

    def test_kaputte_datei_wird_nicht_ueberschrieben(self):
        self.zuordnung.write_text("{kaputt")
        with self.assertRaises(anbindung.AnbindungFehler):
            self.setze(org="o", token=TOKEN_NEU)
        self.assertEqual(self.zuordnung.read_text(), "{kaputt")
        self.assertFalse(self.zugang.exists())

    def test_symlink_runner_json_wird_nicht_gefolgt(self):
        ziel = self.d / "fremd.json"
        ziel.write_text(json.dumps({"version": 1, "runner": {}}))
        self.zuordnung.symlink_to(ziel)
        with self.assertRaises(anbindung.AnbindungFehler):
            self.setze(org="o", token=TOKEN_NEU)
        self.assertTrue(self.zuordnung.is_symlink())
        self.assertEqual(json.loads(ziel.read_text()), {"version": 1, "runner": {}})

    def test_symlink_als_ordner_abgelehnt(self):
        echt = self.d / "anderswo"
        echt.mkdir()
        link = self.d / "etc-link"
        link.symlink_to(echt)
        with self.assertRaises(anbindung.AnbindungFehler):
            anbindung.setze("runner-vm-02", link / "runner.json", link / "zugang", "https://srv.example.org", token=TOKEN_NEU)
        self.assertEqual(list(echt.iterdir()), [])

    def test_symlink_als_token_wird_entfernt_nicht_verfolgt(self):
        self.schreibe_runner({"runner-vm-02": {"server": "https://srv.example.org"}})
        self.zugang.mkdir(mode=0o700)
        fremd = self.d / "fremd.token"
        fremd.write_text("geheim\n")
        (self.zugang / "runner-vm-02.token").symlink_to(fremd)
        with self.assertRaises(anbindung.AnbindungFehler):  # neue Adresse, Datei da → neues Token nötig
            self.setze("https://anders.example.org")
        self.setze("https://anders.example.org", token=TOKEN_NEU)
        self.assertFalse((self.zugang / "runner-vm-02.token").is_symlink())
        self.assertEqual(self.token(), TOKEN_NEU)
        self.assertEqual(fremd.read_text(), "geheim\n")

    def test_kommandozeile_nur_root_token_ueber_stdin(self):
        argv = ["setze", "--runner", "runner-vm-02", "--zuordnung", str(self.zuordnung), "--zugang-verz", str(self.zugang),
                "--server", "https://srv.example.org", "--org", "beispiel-org", "--token-stdin"]
        with mock.patch.object(anbindung, "_ist_root", return_value=False), redirect_stdout(io.StringIO()) as aus, \
                mock.patch("sys.stdin", io.StringIO(TOKEN_NEU + "\n")):
            self.assertEqual(anbindung.main(argv), 2)
        self.assertIn("Nur als root", aus.getvalue())
        self.assertFalse(self.zuordnung.exists())
        with mock.patch.object(anbindung, "_ist_root", return_value=True), redirect_stdout(io.StringIO()) as aus, \
                mock.patch("sys.stdin", io.StringIO(TOKEN_NEU + "\n")):
            self.assertEqual(anbindung.main(argv), 0)
        self.assertEqual(self.token(), TOKEN_NEU)
        self.assertNotIn(TOKEN_NEU, aus.getvalue())
        for zeile in aus.getvalue().splitlines():
            self.assertRegex(zeile, r"^(ok|warn|fehler|hin)\|")
        with mock.patch.object(anbindung, "_ist_root", return_value=True), redirect_stdout(io.StringIO()) as aus, \
                mock.patch("sys.stdin", io.StringIO("x" * 5000)):
            self.assertEqual(anbindung.main(argv), 2)
        self.assertNotIn("x" * 20, aus.getvalue())


class BewertungTest(unittest.TestCase):
    def test_ok(self):
        rc, zeilen = anbindung.bewerte("forgejo", {"abfrage": "ok", "art": "forgejo", "serverVersion": "13.0.1",
                                                    "repos": [{}, {}], "runner": {"zustand": "online"}}, "beispiel-org")
        self.assertEqual(rc, 0)
        self.assertEqual([a for a, _ in zeilen], ["ok", "ok", "ok"])
        self.assertIn("Forgejo 13.0.1", zeilen[0][1])
        self.assertIn("beispiel-org gefunden, 2 Repositories", zeilen[1][1])
        rc, zeilen = anbindung.bewerte("gitlab", {"abfrage": "ok", "runner": {"zustand": "unbekannt", "grund": "nicht gefunden"}})
        self.assertEqual((rc, zeilen[-1][0]), (0, "warn"))

    def test_fehlerarten(self):
        faelle = {
            ("forgejo", "token-ungueltig", "Token ungültig oder abgelaufen (401)"): "Token ungültig",
            ("forgejo", "keine-rechte", "Organisation oder Benutzer „x“ nicht gefunden"): "Keine Rechte",
            ("gitlab", "keine-rechte", "Token ohne Bereich read_api"): "read_api",
            ("forgejo", "nicht-erreichbar", "Server nicht erreichbar (Name or service not known)"): "Server nicht erreichbar",
            ("forgejo", "fehler", "Server antwortet nicht wie Forgejo oder Gitea (/api/v1/version fehlt)"): "Server nicht gefunden",
            ("forgejo", "fehler", "Keine gültige JSON-Antwort auf /version"): "Server nicht gefunden",
            ("gitlab", "nicht-erreichbar", "GitLab antwortet nicht mit JSON (falsche Adresse oder Proxy?)"): "Server nicht gefunden",
            ("gitlab", "nicht-erreichbar", "GitLab leitet weiter (301) – Adresse des Servers prüfen"): "Server nicht gefunden",
            ("forgejo", "kein-token", ""): "Kein Token",
            ("forgejo", "kontingent", ""): "Kontingent",
            ("forgejo", "fehler", "unerwartete Antwort des Servers"): "Prüfung fehlgeschlagen",
        }
        for (dienst, art, fehler), erwartet in faelle.items():
            rc, zeilen = anbindung.bewerte(dienst, {"abfrage": art, "fehler": fehler}, "" if dienst == "gitlab" else "x")
            self.assertEqual((rc, zeilen[0][0]), (1, "fehler"), art)
            self.assertIn(erwartet, " ".join(t for _, t in zeilen), (dienst, art, fehler))

    def test_text_entschaerft(self):
        _, zeilen = anbindung.bewerte("forgejo", {"abfrage": "fehler", "fehler": "a|b\x1b[2Jc"}, "x")
        self.assertNotIn("\x1b", zeilen[-1][1])
        self.assertNotIn("|", zeilen[-1][1])


class VerbindungTest(Basis):
    def setUp(self):
        super().setUp()
        self.schreibe_erkennung(fund())

    def test_echter_adapter_nur_get(self):
        server, handler = starte({
            "/api/v1/version": (200, {"Content-Type": "application/json"}, b'{"version":"13.0.1+gitea-1.22.0"}'),
            "/api/v1/orgs/beispiel-org": (401, {}, b"{}"),
        })
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        adresse = f"http://127.0.0.1:{server.server_port}"
        self.schreibe_runner({"runner-vm-02": {"server": adresse, "org": "beispiel-org", "http_erlaubt": True}})
        zugangsdaten.schreibe(self.zugang, "runner-vm-02", TOKEN_NEU)
        rc, zeilen = anbindung.pruefe_verbindung("runner-vm-02", self.erkennung, self.zuordnung, self.zugang, frist=10)
        self.assertEqual(rc, 1)
        self.assertIn("Token ungültig", zeilen[0][1])
        self.assertTrue(handler.gesehen)
        self.assertTrue(all(kopf.get("Authorization") == f"token {TOKEN_NEU}" for _, kopf in handler.gesehen[1:]))
        self.assertNotIn(TOKEN_NEU, repr(zeilen))

    def test_echter_adapter_ok(self):
        json_kopf = {"Content-Type": "application/json"}
        server, handler = starte({
            "/api/v1/version": (200, json_kopf, b'{"version":"13.0.1+gitea-1.22.0"}'),
            "/api/v1/orgs/beispiel-org": (200, json_kopf, b'{"username":"beispiel-org"}'),
            "/api/v1/orgs/beispiel-org/repos": (200, json_kopf, b'[{"name":"app","private":true,"updated_at":"2026-10-01T00:00:00Z"}]'),
            "/api/v1/repos/beispiel-org/app/actions/runs": (200, json_kopf, b'{"workflow_runs":[]}'),
        })
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.schreibe_runner({"runner-vm-02": {"server": f"http://127.0.0.1:{server.server_port}", "org": "beispiel-org",
                                               "http_erlaubt": True}})
        zugangsdaten.schreibe(self.zugang, "runner-vm-02", TOKEN_NEU)
        rc, zeilen = anbindung.pruefe_verbindung("runner-vm-02", self.erkennung, self.zuordnung, self.zugang, frist=10)
        self.assertEqual(rc, 0, zeilen)
        self.assertEqual(zeilen[0], ("ok", "Server erreichbar · Forgejo 13.0.1"))
        self.assertIn("beispiel-org gefunden, 1 Repositories", zeilen[1][1])
        self.assertEqual(zeilen[2][0], "warn")  # Runner-Liste ohne Owner-Recht: ehrlich „unbekannt“

    def test_http_ohne_erlaubnis_fragt_nicht(self):
        with mock.patch.object(anbindung, "adapter") as a:
            self.schreibe_runner({"runner-vm-02": {"server": "http://192.0.2.10", "org": "o"}})
            rc, zeilen = anbindung.pruefe_verbindung("runner-vm-02", self.erkennung, self.zuordnung, self.zugang)
        self.assertEqual(rc, 1)
        a.assert_not_called()
        self.assertIn("http_erlaubt", zeilen[0][1])

    def test_ohne_server_und_fremder_dienst(self):
        self.assertEqual(anbindung.pruefe_verbindung("runner-vm-02", self.erkennung, self.zuordnung, self.zugang)[0], 1)
        self.assertEqual(anbindung.pruefe_verbindung("nirgends", self.erkennung, self.zuordnung, self.zugang)[0], 3)

    def test_harte_frist(self):
        class Haengt:
            def abfrage(self, *_):
                time.sleep(5)

        self.schreibe_runner({"runner-vm-02": {"server": "https://srv.example.org", "org": "o"}})
        with mock.patch.object(anbindung, "adapter", return_value=Haengt()):
            beginn = time.monotonic()
            rc, zeilen = anbindung.pruefe_verbindung("runner-vm-02", self.erkennung, self.zuordnung, self.zugang, frist=0.3)
        self.assertLess(time.monotonic() - beginn, 2)
        self.assertEqual(rc, 1)
        self.assertIn("nicht erreichbar", zeilen[0][1])

    def test_hinweise_zum_stand(self):
        ok = {"abfrage": "ok", "art": "forgejo", "repos": [], "runner": {"zustand": "online"}}
        attrappe = mock.Mock(**{"abfrage.return_value": ok})
        self.schreibe_runner({"runner-vm-02": {"server": "https://srv.example.org", "org": "o", "stand": "grund"}})
        with mock.patch.object(anbindung, "adapter", return_value=attrappe):
            rc, zeilen = anbindung.pruefe_verbindung("runner-vm-02", self.erkennung, self.zuordnung, self.zugang)
        self.assertEqual(rc, 0)
        self.assertIn("Grundüberwachung", zeilen[-1][1])
        # GitLab: Adapter da, Sammler fragt noch nicht ab (#115) – ehrlich sagen
        self.schreibe_erkennung(fund("gl", dienst="gitlab", unit="gitlab-runner.service"))
        self.schreibe_runner({"gl": {"server": "https://gitlab.example.org"}})
        with mock.patch.object(anbindung, "adapter", return_value=attrappe):
            _, zeilen = anbindung.pruefe_verbindung("gl", self.erkennung, self.zuordnung, self.zugang)
        self.assertIn("#115", zeilen[-1][1])


class SkriptTest(unittest.TestCase):
    """einrichten.sh lässt sich ohne root nicht ausführen – geprüft werden Syntax, Hilfsfunktionen und Regeln."""

    skript = (WURZEL / "einrichten.sh").read_text(encoding="utf-8")

    def funktion(self, name: str) -> str:
        treffer = re.search(rf"^{name}\(\) \{{.*?^\}}$", self.skript, re.S | re.M)
        self.assertIsNotNone(treffer, name)
        return treffer.group(0)

    def bash(self, code: str) -> str:
        return subprocess.run(["bash", "-c", "set -euo pipefail\n" + code], capture_output=True, text=True, check=True, timeout=10).stdout

    def test_syntax(self):
        subprocess.run(["bash", "-n", str(WURZEL / "einrichten.sh")], check=True, timeout=10)

    def test_wert_aus(self):
        code = self.funktion("wert_aus") + '\ninfo=$(printf "dienst=forgejo\\nserver=https://srv.example.org/a=b\\norg=\\n")\n' \
            'printf "[%s]" "$(wert_aus "$info" dienst)" "$(wert_aus "$info" server)" "$(wert_aus "$info" org)" "$(wert_aus "$info" fehlt)"'
        self.assertEqual(self.bash(code), "[forgejo][https://srv.example.org/a=b][][]")

    def test_zeilen_ausgeben(self):
        code = "ok() { echo \"OK:$*\"; }\nhinweis() { echo \"W:$*\"; }\nhin() { echo \"H:$*\"; }\n" + self.funktion("zeilen_ausgeben") \
            + '\nzeilen_ausgeben "$(printf "ok|gut\\nwarn|achtung\\nhin|leise\\nunbekannt|x\\n\\n")"'
        self.assertEqual(self.bash(code).splitlines(), ["OK:gut", "W:achtung", "H:leise"])

    def test_token_nie_als_argument(self):
        rumpf = self.funktion("zugang_server")
        for zeile in rumpf.splitlines():
            if "anbindung_helfer" in zeile or "anbindung " in zeile:
                self.assertNotIn('"$t"', zeile.split("|", 1)[-1], zeile)
        self.assertIn("printf '%s\\n' \"$t\" | anbindung_helfer setze", rumpf)
        self.assertIn("read -r -s -p", rumpf)
        for zeile in rumpf.splitlines():  # jede Eingabe vom Terminal, roh
            if re.search(r"\bread\b", zeile) and "IFS" not in zeile:
                self.assertIn("-r", zeile)
                self.assertIn("</dev/tty", zeile)
        self.assertIn("timeout --foreground", rumpf)  # Verbindungsprüfung mit harter Grenze
