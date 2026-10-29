import tempfile
import unittest
from pathlib import Path

from runner_monitor import github, runner, sammler


class JournalTest(unittest.TestCase):
    def eintrag(self, text, **extra):
        return {"MESSAGE": text, "__REALTIME_TIMESTAMP": "1792760000000000", **extra}

    def test_job_start_und_ende(self):
        e = runner.deute_journalzeile(self.eintrag("2026-10-23 12:02:11Z: Running job: test"))
        self.assertEqual((e.art, e.name), ("start", "test"))
        e = runner.deute_journalzeile(self.eintrag("2026-10-23 12:08:53Z: Job test completed with result: Failed"))
        self.assertEqual((e.art, e.name, e.ergebnis), ("ende", "test", "fehler"))
        e = runner.deute_journalzeile(self.eintrag("Job build (node 20) completed with result: Canceled"))
        self.assertEqual((e.name, e.ergebnis), ("build (node 20)", "abgebrochen"))

    def test_dienst_meldungen_von_systemd(self):
        e = runner.deute_journalzeile(self.eintrag("Stopped GitHub Actions Runner.", _COMM="systemd", _PID="1"))
        self.assertEqual(e.art, "dienst-gestoppt")
        e = runner.deute_journalzeile(self.eintrag("Started GitHub Actions Runner.", _COMM="systemd", _PID="1"))
        self.assertEqual(e.art, "dienst-gestartet")
        self.assertIsNone(runner.deute_journalzeile(self.eintrag("irgendwas anderes")))

    def test_gefaelschte_kennung_taeuscht_keinen_dienst_vor(self):
        # SYSLOG_IDENTIFIER setzt der Absender (ein Job), _COMM/_PID setzt journald (#119)
        for extra in ({"SYSLOG_IDENTIFIER": "systemd"},
                      {"SYSLOG_IDENTIFIER": "systemd", "_COMM": "bash", "_PID": "4711"},
                      {"SYSLOG_IDENTIFIER": "systemd", "_COMM": "systemd", "_PID": "2187"},
                      {"_COMM": "systemd"}):
            for text in ("Stopped GitHub Actions Runner.", "Stopping GitHub Actions Runner.", "Started GitHub Actions Runner."):
                self.assertIsNone(runner.deute_journalzeile(self.eintrag(text, **extra)), (text, extra))

    def test_byte_liste_wird_gelesen(self):
        e = runner.deute_journalzeile(self.eintrag(list(b"Running job: lint")))
        self.assertEqual(e.name, "lint")


class SeitenTest(unittest.TestCase):
    def test_zeitstempel_abtrennen(self):
        zeit, text = runner.deute_seitenzeile("2026-10-23T12:05:12.1234567Z \x1b[32m✓\x1b[39m ok", 0)
        self.assertEqual(text, "\x1b[32m✓\x1b[39m ok")
        self.assertGreater(zeit, 1.7e9)
        self.assertEqual(runner.deute_seitenzeile("ohne zeit", 5.0), (5.0, "ohne zeit"))

    def test_folger_meldet_neuen_schritt_und_zeilen(self):
        with tempfile.TemporaryDirectory() as verz:
            pfad = Path(verz)
            gemeldet = []
            folger = runner.SeitenFolger(pfad, lambda art, wert: gemeldet.append((art, wert)))
            (pfad / "1.log").write_text("2026-10-23T12:00:00Z eins\nzwei\nhalb")
            folger.schritt()
            self.assertEqual(gemeldet[0][0], "schritt")
            self.assertEqual([[t for _, t in w] for a, w in gemeldet if a == "zeilen"], [["eins", "zwei"]])
            with (pfad / "1.log").open("a") as f:
                f.write("e Zeile\n")
            folger.schritt()
            self.assertEqual(gemeldet[-1], ("zeilen", [gemeldet[-1][1][0]]))
            self.assertEqual(gemeldet[-1][1][0][1], "halbe Zeile")

    def test_flut_ist_eine_meldung(self):
        # Ein Build mit viel Ausgabe darf nicht tausende Einzelmeldungen erzeugen (Ursache für „Getrennt“ bis 0.3.0).
        with tempfile.TemporaryDirectory() as verz:
            pfad = Path(verz)
            gemeldet = []
            folger = runner.SeitenFolger(pfad, lambda art, wert: gemeldet.append((art, wert)))
            (pfad / "1.log").write_text("".join(f"Zeile {i}\n" for i in range(5000)))
            folger.schritt()
            self.assertEqual([a for a, _ in gemeldet], ["schritt", "zeilen"])
            self.assertEqual(len(gemeldet[1][1]), 5000)

    def test_aufraeumen_waehrend_der_suche(self):
        # Issue #57: Der Runner löscht hochgeladene Seiten – eine Datei verschwindet zwischen iterdir und stat
        with tempfile.TemporaryDirectory() as verz:
            pfad = Path(verz)
            (pfad / "a.log").write_text("x\n")
            (pfad / "b.log").write_text("y\n")
            folger = runner.SeitenFolger(pfad, lambda art, wert: None)
            echt = Path.stat

            def stat(selbst, *a, **k):
                if selbst.name == "a.log":
                    raise FileNotFoundError(selbst)
                return echt(selbst, *a, **k)

            Path.stat = stat
            try:
                self.assertEqual(folger.neueste().name, "b.log")
            finally:
                Path.stat = echt

    def test_ungueltiger_zeitstempel(self):
        self.assertEqual(runner.deute_seitenzeile("2026-13-40T25:00:00Z text", 7.0), (7.0, "text"))

    def test_registrierung_mit_bom(self):
        with tempfile.TemporaryDirectory() as verz:
            (Path(verz) / ".runner").write_text('﻿{"agentName":"runner-vm-01","gitHubUrl":"https://github.com/beispiel-org"}', encoding="utf-8")
            self.assertEqual(runner.lies_registrierung(Path(verz))["name"], "runner-vm-01")
            self.assertEqual(runner.lies_registrierung(Path(verz) / "fehlt"), {})


class AutoUpdateTest(unittest.TestCase):
    """Nacht-Update wartet, bis der Runner frei ist (#77)."""

    def setUp(self):
        import json
        import time
        from runner_monitor import konfig
        self.verz = tempfile.TemporaryDirectory()
        d = Path(self.verz.name)
        self.k = konfig.lade(datei=d / "fehlt.env", umgebung={"MONITOR_DATEN_VERZ": str(d / "daten"), "MONITOR_LAUF_VERZ": str(d / "lauf")})
        self.k.lauf_verz.mkdir(parents=True)
        self.k.daten_verz.mkdir(parents=True)
        url = "https://github.com/beispiel-org/x/releases/download/v99.0.0/runner-monitor-99.0.0.tar.gz"
        (self.k.lauf_verz / "release.json").write_text(json.dumps({"version": "99.0.0", "archiv": url, "pruefsumme": url + ".sha256", "bereit": True}))
        self.k.einstellungen_datei.write_text(json.dumps({"autoUpdate": True}))
        self.s = sammler.Sammler(self.k)
        self.job = False
        self.s._job_laeuft = lambda: self.job
        self.um = lambda tag, stunde, minute=0: time.mktime((2026, 10, tag, stunde, minute, 0, 0, 0, -1))

    def tearDown(self):
        self.verz.cleanup()

    def stand(self):
        import json
        try:
            return json.loads((self.k.lauf_verz / "auto-update.json").read_text())
        except OSError:
            return {}

    def auftrag(self):
        return (self.k.auftraege_verz / "update").exists()

    def test_nicht_vor_drei_uhr(self):
        self.s.auto_update(self.um(25, 2, 59))
        self.assertFalse(self.auftrag())

    def test_frei_um_drei(self):
        self.s.auto_update(self.um(25, 3, 0))
        self.assertTrue(self.auftrag())
        self.assertEqual(self.stand()["zustand"], "gestartet")

    def test_job_laeuft_dann_vorgemerkt_und_nach_vier_uhr_gestartet(self):
        self.job = True
        self.s.auto_update(self.um(25, 3, 0))
        self.s.auto_update(self.um(25, 3, 59))
        self.assertFalse(self.auftrag())
        self.assertEqual(self.stand()["zustand"], "vorgemerkt")
        self.job = False
        self.s.auto_update(self.um(25, 4, 37))      # früher: Nacht verpasst
        self.assertTrue(self.auftrag())

    def test_ganze_nacht_belegt_dann_verschoben(self):
        self.job = True
        self.s.auto_update(self.um(25, 3, 0))
        self.s.auto_update(self.um(25, 7, 0))
        self.assertFalse(self.auftrag())
        self.assertEqual(self.stand()["zustand"], "verschoben")
        self.job = False
        self.s.auto_update(self.um(25, 12, 0))      # tagsüber nicht
        self.assertFalse(self.auftrag())
        self.s.auto_update(self.um(26, 3, 1))
        self.assertTrue(self.auftrag())

    def test_hoechstens_ein_versuch_je_nacht(self):
        self.s.auto_update(self.um(25, 3, 0))
        (self.k.auftraege_verz / "update").unlink()   # Update lief, schlug fehl (alte Version zurück)
        neu = sammler.Sammler(self.k)                 # Sammler wurde dabei neu gestartet
        neu._job_laeuft = lambda: False
        neu.auto_update(self.um(25, 3, 5))
        self.assertFalse(self.auftrag())
        neu.auto_update(self.um(26, 3, 0))
        self.assertTrue(self.auftrag())

    def test_ausgeschaltet_oder_aktuell(self):
        import json
        self.k.einstellungen_datei.write_text(json.dumps({"autoUpdate": False}))
        self.s.auto_update(self.um(25, 3, 0))
        self.assertFalse(self.auftrag())
class AenderungenTest(unittest.TestCase):
    """Änderungen seit der installierten Version (#78)."""

    def test_notiz_aus_dem_repo(self):
        text = Path("docs/releases/v0.6.1.md").read_text(encoding="utf-8")
        d = github.deute_notiz(text)
        self.assertTrue(d["neu"] and d["neu"][0].startswith("Runner-Einrichtung"))
        self.assertIn("einrichten.sh runner", d["einmalig"])
        d = github.deute_notiz(Path("docs/releases/v0.5.0.md").read_text(encoding="utf-8"))
        self.assertEqual(d["einmalig"].split(".")[0], "Offene Dashboard-Fenster dürfen neu geladen werden, müssen aber nicht")

    def test_alte_notiz_ohne_abschnitte(self):
        self.assertEqual(github.deute_notiz("Text\n- eins\n* zwei\n")["neu"], ["eins", "zwei"])

    def test_versionen_zwischen_installiert_und_neueste(self):
        def rel(tag, body="## Was ist neu\n- x\n", **mehr):
            return {"tag_name": tag, "body": body, "html_url": f"https://example.org/{tag}", "published_at": "2026-10-25T00:00:00Z", **mehr}

        class Klient:
            def hole(self, pfad, parameter=None):
                return github.Antwort([rel("v0.7.0"), rel("v0.6.2"), rel("v0.6.1"), rel("v0.6.10", prerelease=True),
                                       rel("v0.8.0", draft=True), rel("kaputt")], {})
        liste = github.aenderungen(Klient(), "beispiel-org/x", "0.6.1", "0.7.0")
        self.assertEqual([r["version"] for r in liste], ["0.7.0", "0.6.2"])
        self.assertEqual(liste[0]["neu"], ["x"])

    def test_fehler_ergibt_leere_liste(self):
        class Klient:
            def hole(self, pfad, parameter=None):
                raise github.GitHubFehler("nicht-erreichbar", "weg")
        self.assertEqual(github.aenderungen(Klient(), "beispiel-org/x", "0.6.1", "0.7.0"), [])


class DienstGrundTest(unittest.TestCase):
    """Gestoppter Dienst: Ursache aus systemd „Result“ (#68)."""

    def status(self, ausgabe):
        import subprocess
        from unittest import mock
        lauf = subprocess.CompletedProcess([], 0, stdout=ausgabe, stderr="")
        with mock.patch.object(runner.subprocess, "run", return_value=lauf):
            return runner.dienst_status("actions.runner.beispiel-org.runner-vm.service")

    def test_oom(self):
        st = self.status("ActiveState=failed\nInactiveEnterTimestamp=Sat 2026-10-24 16:35:54 UTC\nResult=oom-kill\n")
        self.assertEqual((st["zustand"], st["grund"]), ("gestoppt", "oom-kill"))
        self.assertIsNotNone(st["seit"])

    def test_normal_gestoppt_ohne_grund(self):
        self.assertIsNone(self.status("ActiveState=inactive\nResult=success\n")["grund"])

    def test_aktiv_ohne_grund(self):
        self.assertIsNone(self.status("ActiveState=active\nActiveEnterTimestamp=Sun 2026-10-25 00:31:13 UTC\nResult=oom-kill\n")["grund"])

    def test_unerwarteter_wert(self):
        self.assertIsNone(self.status("ActiveState=failed\nResult=<script>\n")["grund"])


class RunnerVersionTest(unittest.TestCase):
    """Version ohne Programmaufruf aus deps.json (#69)."""

    def setUp(self):
        self.verz = tempfile.TemporaryDirectory()
        self.d = Path(self.verz.name)
        runner._version_cache = (0.0, "")
        self.alt = runner.version_aus_programm
        runner.version_aus_programm = lambda verz: ""

    def tearDown(self):
        runner.version_aus_programm = self.alt
        runner._version_cache = (0.0, "")
        self.verz.cleanup()

    def deps(self, ordner, version, bom=False):
        import json
        (self.d / ordner).mkdir(parents=True, exist_ok=True)
        inhalt = json.dumps({"libraries": {f"Runner.Listener/{version}": {"type": "project"}, "Runner.Sdk/1.0.0": {"type": "project"}}})
        (self.d / ordner / "Runner.Listener.deps.json").write_text(("\ufeff" if bom else "") + inhalt, encoding="utf-8")

    def test_aus_deps(self):
        self.deps("bin", "2.338.1", bom=True)
        self.assertEqual(runner.version_aus_deps(self.d), "2.338.1")

    def test_nach_selbst_update_ueber_verweis(self):
        self.deps("bin.2.339.0", "2.339.0")
        (self.d / "bin").symlink_to(self.d / "bin.2.339.0")
        self.assertEqual(runner.version_aus_deps(self.d), "2.339.0")

    def test_kaputt_oder_fehlt(self):
        self.assertEqual(runner.version_aus_deps(self.d), "")
        (self.d / "bin").mkdir()
        (self.d / "bin" / "Runner.Listener.deps.json").write_text("{kaputt")
        self.assertEqual(runner.version_aus_deps(self.d), "")

    def test_leeres_ergebnis_nur_kurz_merken(self):
        self.assertEqual(runner.runner_version(self.d, jetzt=1000.0), "")
        self.deps("bin", "2.338.1")
        self.assertEqual(runner.runner_version(self.d, jetzt=1010.0), "")        # noch gemerkt
        self.assertEqual(runner.runner_version(self.d, jetzt=1000.0 + runner.VERSION_LEER_TAKT), "2.338.1")
        self.deps("bin", "2.339.0")
        self.assertEqual(runner.runner_version(self.d, jetzt=1100.0), "2.338.1")  # gefunden: 10 Min. gemerkt


class ReleasePruefenTest(unittest.TestCase):
    def test_auftrag_holt_abfrage_vor_und_bremst(self):
        import tempfile
        from pathlib import Path
        from runner_monitor import konfig
        with tempfile.TemporaryDirectory() as verz:
            d = Path(verz)
            k = konfig.lade(datei=d / "fehlt.env", umgebung={"MONITOR_DATEN_VERZ": str(d / "daten"), "MONITOR_LAUF_VERZ": str(d / "lauf")})
            k.auftraege_verz.mkdir(parents=True)
            s = sammler.Sammler(k)
            s.naechste_release = 10_000.0
            (k.auftraege_verz / "release-pruefen").write_text("{}")
            s.auftrag_release_pruefen(jetzt=1000.0)
            self.assertEqual(s.naechste_release, 0.0)
            self.assertFalse((k.auftraege_verz / "release-pruefen").exists())
            # zweiter Klick innerhalb einer Minute: Auftrag weg, keine neue Abfrage
            s.naechste_release = 10_000.0
            (k.auftraege_verz / "release-pruefen").write_text("{}")
            s.auftrag_release_pruefen(jetzt=1030.0)
            self.assertEqual(s.naechste_release, 10_000.0)
            self.assertFalse((k.auftraege_verz / "release-pruefen").exists())


class ReleaseBereitTest(unittest.TestCase):
    """Gleich nach dem Veröffentlichen fehlt das Paket noch (#63): bald erneut fragen, nicht 6 h warten."""

    def sammler(self, verz, antworten):
        from runner_monitor import konfig
        d = Path(verz)
        k = konfig.lade(datei=d / "fehlt.env", umgebung={"MONITOR_DATEN_VERZ": str(d / "daten"), "MONITOR_LAUF_VERZ": str(d / "lauf")})
        k.lauf_verz.mkdir(parents=True)
        s = sammler.Sammler(k)
        s.naechste_github = float("inf")
        s.naechste_erkennung = float("inf")
        s.auftraege = lambda: None
        s.auto_update = lambda: None
        s.release = lambda: antworten.pop(0)
        return s

    def test_ohne_paket_bald_wieder(self):
        url = "https://github.com/beispiel-org/x/releases/download/v99.0.0/runner-monitor-99.0.0.tar.gz"
        ohne = {"version": "99.0.0", "archiv": "", "pruefsumme": "", "bereit": False}
        mit = {"version": "99.0.0", "archiv": url, "pruefsumme": url + ".sha256", "bereit": True}
        with tempfile.TemporaryDirectory() as verz:
            s = self.sammler(verz, [ohne, mit])
            alt = sammler.docker_container
            sammler.docker_container = lambda: {}
            try:
                s.ein_takt(1000.0)
                self.assertEqual(s.naechste_release, 1000.0 + sammler.TAKT_NICHT_BEREIT)
                s.ein_takt(1000.0 + sammler.TAKT_NICHT_BEREIT)
                self.assertEqual(s.naechste_release, 1000.0 + sammler.TAKT_NICHT_BEREIT + sammler.TAKT_RELEASE)
            finally:
                sammler.docker_container = alt

    def test_paket_bereit(self):
        self.assertFalse(sammler.paket_bereit({"version": "1.0.0", "archiv": "", "pruefsumme": ""}))
        self.assertFalse(sammler.paket_bereit({"archiv": "a", "pruefsumme": "b", "bereit": False}))
        self.assertTrue(sammler.paket_bereit({"archiv": "a", "pruefsumme": "b"}))  # ältere release.json ohne „bereit“

    def test_neueste_version_meldet_bereit(self):
        class Klient:
            def __init__(self, assets):
                self.assets = assets

            def hole(self, pfad):
                return github.Antwort({"tag_name": "v1.2.3", "assets": self.assets, "body": ""}, {})
        self.assertFalse(github.neueste_version(Klient([]), "beispiel-org/x")["bereit"])
        assets = [{"name": "runner-monitor-1.2.3.tar.gz", "browser_download_url": "u"},
                  {"name": "runner-monitor-1.2.3.tar.gz.sha256", "browser_download_url": "u.sha256"}]
        self.assertTrue(github.neueste_version(Klient(assets), "beispiel-org/x")["bereit"])


class GitHubTest(unittest.TestCase):
    def test_zaehlen(self):
        runs = [{"status": "in_progress"}, {"status": "queued"}, {"status": "waiting"}, {"status": "completed"}]
        self.assertEqual(github.zaehle_laeufe(runs), (1, 2))

    def test_token_ablauf(self):
        self.assertIsNotNone(github.token_ablauf("2026-11-06 12:00:00 UTC"))
        self.assertIsNone(github.token_ablauf(None))

    def test_ref(self):
        self.assertEqual(github.ref_aus_lauf({"event": "pull_request", "pull_requests": [{"number": 142}], "display_title": "Suche"})["name"], "#142")
        self.assertEqual(github.ref_aus_lauf({"event": "push", "head_branch": "v1.8.0"})["art"], "Tag")
        self.assertEqual(github.ref_aus_lauf({"event": "push", "head_branch": "main"})["art"], "Branch")

    def test_job_fuer_runner_mit_schritten(self):
        lauf = {"name": "CI", "repository": {"name": "projekt-a", "private": True}, "event": "push", "head_branch": "main"}
        jobs = [
            {"status": "in_progress", "runner_name": "anderer", "name": "x", "steps": []},
            {"status": "in_progress", "runner_name": "runner-vm-01", "name": "test", "started_at": "2026-10-23T12:02:11Z",
             "steps": [{"name": "Set up job", "status": "completed"}, {"name": "Tests", "status": "in_progress"}, {"name": "Complete job", "status": "queued"}]},
        ]
        job = github.job_fuer_runner(lauf, jobs, "runner-vm-01")
        self.assertEqual((job["repo"], job["name"], job["schritt"]), ("projekt-a", "test", 2))
        self.assertEqual(job["schritte"][1], "Tests")

    def test_ohne_token(self):
        self.assertEqual(github.abfrage(github.Klient(""), "beispiel-org", "r")["abfrage"], "kein-token")

    def test_versionen(self):
        self.assertEqual(github.vergleiche("0.2.0", "0.1.9"), 1)
        self.assertEqual(github.vergleiche("1.0.0", "1.0.0"), 0)
        self.assertEqual(github.vergleiche("0.10.0", "0.9.0"), 1)


class DockerTest(unittest.TestCase):
    def test_zustaende(self):
        laeuft = sammler.deute_container({"Names": "supabase_db_ci", "Image": "supabase/postgres", "State": "running", "Status": "Up 4 minutes (healthy)", "CreatedAt": "2026-10-23 14:04:41 +0200 CEST"})
        self.assertEqual(laeuft["status"], "läuft")
        self.assertIsNotNone(laeuft["seit"])
        startet = sammler.deute_container({"Names": "a", "State": "running", "Status": "Up 3 seconds (health: starting)"})
        self.assertEqual(startet["status"], "startet")
        alt = sammler.deute_container({"Names": "b", "State": "exited", "Status": "Exited (0) 3 days ago"})
        self.assertIsNone(alt)
        frisch = sammler.deute_container({"Names": "c", "State": "exited", "Status": "Exited (1) 2 minutes ago"})
        self.assertEqual(frisch["status"], "beendet")


if __name__ == "__main__":
    unittest.main()
