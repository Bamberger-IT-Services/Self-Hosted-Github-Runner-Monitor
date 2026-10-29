"""Anbieter-Adapter, Fähigkeiten, Zugangsdaten je Runner und /api/zustand (#92, E-19). Nur Attrappen, kein Netz."""
import http.client
import io
import json
import os
import stat
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from runner_monitor import anbieter, erkennung, github, konfig, runner, sammler, server, zustand
from runner_monitor.anbieter import forgejo as fj_adapter
from runner_monitor.anbieter import github as gh_adapter
from runner_monitor.anbieter import gitlab as gitlab_adapter
from runner_monitor.anbieter import token as zugangsdaten

# Bestand bis 0.7: Bereich „status“ (FUNKTIONSWEISE.md) – muss unverändert bleiben (E-19, additiv)
STATUS_SCHLUESSEL = {"vm", "runner", "eingerichtet", "labels", "version", "monitorVersion", "system", "dienst", "github", "job", "letzteJobs"}
WORKFLOWS_SCHLUESSEL = {"org", "abfrage", "abgefragt", "versucht", "naechste", "tokenAblauf", "kontingent", "repos", "fehler", "runnerGrund"}
EINTRAG_SCHLUESSEL = {"id", "name", "dienst", "server", "org", "unit", "stand", "einstufung", "version", "labels", "faehig",
                      "status", "job", "letzteJobs", "jobsJeRepository", "log"}


def lade_konfig(d: Path, **mehr) -> konfig.Konfig:
    return konfig.lade(datei=d / "fehlt.env", umgebung={
        "MONITOR_ADRESSE": "127.0.0.1", "MONITOR_DATEN_VERZ": str(d / "daten"), "MONITOR_LAUF_VERZ": str(d / "lauf"),
        "MONITOR_TOKEN_DATEI": str(d / "etc" / "github-token"), "MONITOR_RUNNER_VERZ": str(d / "actions-runner"),
        "MONITOR_ORG": "beispiel-org", **mehr})


def registriere_runner(d: Path, name: str = "runner-vm-01") -> None:
    (d / "actions-runner").mkdir(parents=True, exist_ok=True)
    (d / "actions-runner" / ".runner").write_text(json.dumps({"agentName": name, "gitHubUrl": "https://github.com/beispiel-org"}), encoding="utf-8")


# ---------------------------------------------------------------- Fähigkeiten und Registry


class FaehigkeitenTest(unittest.TestCase):
    def test_tabelle_passt_zur_erkennung(self):
        """Die ausgelieferte Tabelle (``erkennung.FAEHIG``) verspricht nie mehr, als der Adapter kann; sie
        darf weniger versprechen, solange der Sammler den Adapter nicht aufruft (E-20). Mit Adapter gleich: GitHub."""
        adapter = anbieter.faehigkeiten_tabelle()
        for dienst, f in erkennung.FAEHIG.items():
            for faehigkeit, wert in f.items():
                self.assertTrue(adapter[dienst][faehigkeit] or not wert, f"{dienst}.{faehigkeit}")
        self.assertEqual(adapter["github"], erkennung.FAEHIG["github"])
        self.assertEqual(erkennung.FAEHIG["gitlab"]["jobs"], False)  # bis zur Anbindung im Sammler (#94)

    def test_tabelle_vollstaendig(self):
        tabelle = anbieter.faehigkeiten_tabelle()
        self.assertEqual(set(tabelle), set(erkennung.DIENSTE))
        for dienst, f in tabelle.items():
            self.assertEqual(set(f), set(anbieter.FAEHIGKEITEN), dienst)
            self.assertFalse(f["updates"], dienst)  # E-16: Updates des Runners kann noch kein Adapter
        self.assertTrue(all(tabelle["github"][k] for k in ("status", "jobs", "schritte", "logs")))

    def test_registry(self):
        self.assertIs(anbieter.klasse_fuer("github"), gh_adapter.GitHub)
        self.assertIs(anbieter.klasse_fuer("gitlab"), gitlab_adapter.GitLab)
        self.assertIs(anbieter.klasse_fuer("forgejo"), fj_adapter.Forgejo)
        self.assertIs(anbieter.klasse_fuer("gitea"), fj_adapter.Gitea)
        for dienst in ("unbekannt", "gibt-es-nicht"):
            self.assertIs(anbieter.klasse_fuer(dienst), anbieter.Grundueberwachung, dienst)
        a = anbieter.adapter(anbieter.RunnerKonfig(id="x", name="x", dienst="unbekannt", unit="buildagent.service"))
        self.assertIsInstance(a, anbieter.Grundueberwachung)

    def test_registry_prueft(self):
        class Falsch(anbieter.Anbieter):
            dienst = "bitbucket"
        with self.assertRaises(ValueError):
            anbieter.registriere(Falsch)

        class Halb(anbieter.Anbieter):
            dienst = "gitlab"
            FAEHIG = {"status": True}
        with self.assertRaises(ValueError):
            anbieter.registriere(Halb)
        self.assertIs(anbieter.klasse_fuer("gitlab"), gitlab_adapter.GitLab)  # nichts überschrieben

    def test_ohne_unit_kein_status_und_kein_log(self):
        a = anbieter.Grundueberwachung(anbieter.RunnerKonfig(id="x", name="x", dienst="forgejo"))
        self.assertEqual(a.faehig(), {"status": False, "jobs": False, "schritte": False, "logs": False, "updates": False})
        e = a.eintrag()
        self.assertEqual(set(e), EINTRAG_SCHLUESSEL)
        self.assertEqual(e["status"]["zustand"], "fehlt")  # wie die Karte „Kein Dienst“, nicht „unbekannt“ (Review #114)
        self.assertEqual(e["status"]["dienst"]["zustand"], "fehlt")
        self.assertIsNone(e["log"])
        self.assertIsNone(e["job"])
        self.assertIsNone(e["jobsJeRepository"])

    def test_log_quelle_nur_aus_konfiguration(self):
        mit_datei = anbieter.Grundueberwachung(anbieter.RunnerKonfig(id="x", name="x", unit="buildagent.service", log="/var/log/buildagent/agent.log"))
        self.assertEqual(mit_datei.log_quelle(), {"art": "datei", "pfad": "/var/log/buildagent/agent.log"})
        journal = anbieter.Grundueberwachung(anbieter.RunnerKonfig(id="x", name="x", unit="buildagent.service"))
        self.assertEqual(journal.log_quelle(), {"art": "journal", "unit": "buildagent.service"})

    def test_grundueberwachung_status(self):
        a = anbieter.Grundueberwachung(anbieter.RunnerKonfig(id="x", name="x", unit="buildagent.service"))
        with mock.patch.object(runner, "dienst_status", return_value={"zustand": "gestoppt", "seit": 5.0, "unit": "buildagent.service", "grund": "oom-kill",
                                                                     "neustarts": 3, "letzterStopp": 5.0}):
            e = a.eintrag(job={"name": "geheim"}, letzte_jobs=[{"name": "x"}])
        self.assertEqual(e["status"], {"zustand": "gestoppt", "beimDienst": None, "dienst": {
            "zustand": "gestoppt", "seit": 5.0, "grund": "oom-kill", "neustarts": 3, "letzterStopp": 5.0}})  # kv-Zeilen (#95)
        self.assertIsNone(e["job"])          # ohne Fähigkeit „jobs“ nie ein Job
        self.assertIsNone(e["letzteJobs"])
        with mock.patch.object(runner, "dienst_status", return_value={"zustand": "aktiv", "seit": 5.0, "unit": "u", "grund": None}):
            self.assertEqual(a.eintrag()["status"]["zustand"], "aktiv")  # „Dienst aktiv“

    def test_ungueltige_unit_wird_nie_aufgerufen(self):
        a = anbieter.Grundueberwachung(anbieter.RunnerKonfig(id="x", name="x", unit="--help.service"))
        with mock.patch.object(runner, "dienst_status") as aufruf:
            self.assertEqual(a.dienst_status()["zustand"], "fehlt")
        aufruf.assert_not_called()

    def test_teilweise_ohne_schritte(self):
        class Teil(anbieter.Anbieter):
            dienst = "unbekannt"
            FAEHIG = {"status": True, "jobs": True, "schritte": False, "logs": True, "updates": False}
        e = Teil(anbieter.RunnerKonfig(id="x", name="x", unit="u.service")).eintrag(
            dienst={"zustand": "aktiv", "seit": 1, "grund": None}, job={"name": "build", "schritt": {"nr": 2, "von": 5, "name": "Tests"}, "schritte": ["a"]})
        self.assertIsNone(e["job"]["schritt"])  # „Schritte nicht verfügbar“
        self.assertEqual(e["status"]["zustand"], "job")

    def test_steuerung_nur_ueber_faehigkeiten(self):
        """#95: Gleiche Fähigkeiten ergeben denselben Eintrag, egal welcher Dienst – die Oberfläche kann sich
        auf faehig{…} verlassen und muss den Namen nie auswerten."""
        dienst = {"zustand": "aktiv", "seit": 1.0, "grund": None, "neustarts": 0, "letzterStopp": None}
        job = {"name": "build", "schritt": {"nr": 2, "von": 5, "name": "Tests"}, "schritte": ["a", "b"]}
        for faehig in ({"status": True, "jobs": False, "schritte": False, "logs": True, "updates": False},
                       {"status": True, "jobs": True, "schritte": False, "logs": True, "updates": False},
                       {"status": True, "jobs": True, "schritte": True, "logs": True, "updates": False}):
            eintraege = []
            for name in ("github", "forgejo", "gitlab", "unbekannt"):
                klasse = type(f"A_{name}", (anbieter.Anbieter,), {"dienst": name, "FAEHIG": faehig})
                e = klasse(anbieter.RunnerKonfig(id="x", name="x", dienst=name, unit="u.service")).eintrag(
                    dienst=dict(dienst), job=dict(job), letzte_jobs=[{"name": "alt"}])
                eintraege.append({k: v for k, v in e.items() if k not in ("dienst", "einstufung")})
            for e in eintraege[1:]:
                self.assertEqual(e, eintraege[0], faehig)
        self.assertEqual(eintraege[0]["log"], {"art": "journal", "unit": "u.service"})


# ---------------------------------------------------------------- GitHub-Adapter


class AttrappeKlient:
    """Antwortet wie die GitHub-API, ohne Netz."""

    def __init__(self, token="t" * 20):
        self.token = token
        self.speicher = {}
        self.zaehler = {"anfragen": 0, "unveraendert": 0}
        self.pfade = []

    def hole(self, pfad, parameter=None):
        self.pfade.append(pfad)
        if pfad == "/orgs/beispiel-org/repos":
            return github.Antwort([{"name": "projekt-a", "private": True, "pushed_at": "2026-10-29T10:00:00Z"}], {})
        if pfad.endswith("/actions/runs"):
            return github.Antwort({"workflow_runs": [{"id": 7, "status": "in_progress", "name": "CI", "event": "push", "head_branch": "main",
                                                      "repository": {"name": "projekt-a", "private": True}}, {"status": "queued"}]}, {})
        if pfad.endswith("/jobs"):
            return github.Antwort({"jobs": [{"status": "in_progress", "runner_name": "runner-vm-01", "name": "test", "started_at": "2026-10-29T10:00:00Z",
                                             "steps": [{"name": "Set up job", "status": "completed"}, {"name": "Tests", "status": "in_progress"}]}]}, {})
        if pfad == "/orgs/beispiel-org/actions/runners":
            return github.Antwort({"runners": [{"name": "runner-vm-01", "status": "online", "busy": True, "labels": [{"name": "self-hosted"}]}]}, {})
        raise AssertionError(pfad)

    def kontingent(self):
        return {"frei": 4999, "limit": 5000, "reset": 0}


class GitHubAdapterTest(unittest.TestCase):
    def test_alte_namen_zeigen_auf_den_adapter(self):
        for name in ("abfrage", "job_fuer_runner", "zaehle_laeufe", "ref_aus_lauf", "RUHIG_AB", "LAEUFT"):
            self.assertIs(getattr(github, name), getattr(gh_adapter, name), name)
        with self.assertRaises(AttributeError):
            github.gibt_es_nicht  # noqa: B018

    def test_abfrage_mit_attrappe(self):
        k = AttrappeKlient()
        erg = gh_adapter.abfrage(k, "beispiel-org", "runner-vm-01")
        self.assertEqual(erg["abfrage"], "ok")
        self.assertEqual(erg["repos"], [{"name": "projekt-a", "privat": True, "laeuft": 1, "wartet": 1}])
        self.assertEqual((erg["job"]["name"], erg["job"]["schritt"], erg["job"]["schritte"]), ("test", 2, ["Set up job", "Tests"]))
        self.assertEqual(erg["runner"]["zustand"], "online")
        a = gh_adapter.GitHub(anbieter.RunnerKonfig(id="runner-vm-01", name="runner-vm-01", dienst="github"))
        self.assertEqual(a.jobs_je_repository(erg)["repos"], erg["repos"])
        self.assertEqual(a.api_job(erg)["name"], "test")
        self.assertEqual(a.beim_dienst(erg), {"zustand": "online", "seit": None})
        self.assertEqual(a.beim_dienst({**erg, "abfrage": "nicht-erreichbar"})["zustand"], "unbekannt")

    def test_adapter_ohne_token_fragt_nicht(self):
        a = gh_adapter.GitHub(anbieter.RunnerKonfig(id="r", name="r", dienst="github", org="beispiel-org"))
        self.assertEqual(a.abfrage({}, token="")["abfrage"], "kein-token")

    def test_workflows_wie_bisher(self):
        with tempfile.TemporaryDirectory() as t:
            z = zustand.Zustand(lade_konfig(Path(t)))
            gh = {"org": "beispiel-org", "abfrage": "ok", "abgefragt": 100.0, "letzterErfolg": 90.0, "repos": [{"name": "a"}], "runner": {"grund": "x"}}
            w = z._workflows(gh)
        self.assertEqual(set(w), WORKFLOWS_SCHLUESSEL)
        self.assertEqual((w["abgefragt"], w["versucht"], w["naechste"], w["runnerGrund"]), (90.0, 100.0, 130.0, "x"))
        self.assertEqual(gh_adapter.workflows_aus(None)["abfrage"], "kein-token")

    def test_server_und_log_aus_der_konfiguration(self):
        k = gh_adapter.konfig_fuer("runner-vm-01", "runner-vm-01", "actions.runner.beispiel-org.runner-vm-01.service", "beispiel-org",
                                   Path("/opt/actions-runner"), Path("/etc/runner-monitor/zugang"), Path("/etc/runner-monitor/github-token"))
        self.assertEqual(k.server, "https://github.com")
        self.assertEqual(k.token_datei, Path("/etc/runner-monitor/zugang/runner-vm-01.token"))
        self.assertEqual(gh_adapter.GitHub(k).log_quelle()["pfad"], "/opt/actions-runner/_diag/pages")
        self.assertIsNone(gh_adapter.konfig_fuer("x", "../boese", None, "", None, Path("/z"), None).token_datei)


# ---------------------------------------------------------------- Zugangsdaten je Runner und Übernahme


class TokenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.verz = self.d / "etc" / "zugang"
        self.alt = self.d / "etc" / "github-token"
        self.alt.parent.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ids(self):
        for gut in ("runner-vm-01", "buildagent", "a.b_c"):
            self.assertEqual(zugangsdaten.pruefe_id(gut), gut)
        for schlecht in ("", ".", "..", "../x", "a/b", ".versteckt", "-a", "Gross", "a" * 65, None, 3):
            self.assertIsNone(zugangsdaten.pruefe_id(schlecht), schlecht)
            if isinstance(schlecht, str):
                with self.assertRaises(zugangsdaten.TokenFehler):
                    zugangsdaten.token_pfad(self.verz, schlecht)

    def test_schreiben_mit_rechten(self):
        self.assertTrue(zugangsdaten.schreibe(self.verz, "runner-vm-01", "ghp_" + "a" * 36))
        datei = self.verz / "runner-vm-01.token"
        self.assertEqual(stat.S_IMODE(os.stat(self.verz).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(datei).st_mode), 0o600)
        self.assertEqual(zugangsdaten.lies(datei), "ghp_" + "a" * 36)
        self.assertEqual([p.name for p in self.verz.iterdir()], ["runner-vm-01.token"])  # keine Reste
        with self.assertRaises(zugangsdaten.TokenFehler):
            zugangsdaten.schreibe(self.verz, "runner-vm-01", "mit leerzeichen")

    def test_lockeres_verzeichnis_wird_0700(self):
        self.verz.mkdir()
        os.chmod(self.verz, 0o755)
        zugangsdaten.schreibe(self.verz, "r", "x" * 20)
        self.assertEqual(stat.S_IMODE(os.stat(self.verz).st_mode), 0o700)

    def test_symlink_wird_nicht_gelesen(self):
        self.verz.mkdir()
        ziel = self.d / "fremd"
        ziel.write_text("geheim\n")
        (self.verz / "r.token").symlink_to(ziel)
        self.assertEqual(zugangsdaten.lies(self.verz / "r.token"), "")

    def test_symlink_als_verzeichnis_abgelehnt(self):
        (self.d / "anderswo").mkdir()
        self.verz.symlink_to(self.d / "anderswo")
        with self.assertRaises(zugangsdaten.TokenFehler):
            zugangsdaten.schreibe(self.verz, "r", "x" * 20)

    def test_migration_einmal_als_kopie(self):
        self.alt.write_text("ghp_" + "b" * 36 + "\n")
        self.assertTrue(zugangsdaten.migriere(self.alt, self.verz, "runner-vm-01"))
        self.assertEqual(zugangsdaten.lies(self.verz / "runner-vm-01.token"), "ghp_" + "b" * 36)
        self.assertTrue(self.alt.is_file())  # alter Ort bleibt (Rückfall)
        # später erneuert (zugang) – eine zweite Übernahme überschreibt das nie
        zugangsdaten.schreibe(self.verz, "runner-vm-01", "ghp_" + "c" * 36)
        self.assertFalse(zugangsdaten.migriere(self.alt, self.verz, "runner-vm-01"))
        self.assertEqual(zugangsdaten.lies(self.verz / "runner-vm-01.token"), "ghp_" + "c" * 36)

    def test_veraltete_kopie_wird_ersetzt(self):
        self.alt.write_text("ghp_" + "a" * 36)
        zugangsdaten.migriere(self.alt, self.verz, "r")
        neu = self.verz / "r.token"
        os.utime(neu, (1000.0, 1000.0))
        # alter Ort neuer, gleicher Inhalt: nichts zu tun
        os.utime(self.alt, (2000.0, 2000.0))
        self.assertFalse(zugangsdaten.migriere(self.alt, self.verz, "r"))
        # alter Ort neuer und anders (Token mit älterer Version gewechselt): Kopie ersetzen
        self.alt.write_text("ghp_" + "b" * 36)
        os.utime(self.alt, (3000.0, 3000.0))
        self.assertTrue(zugangsdaten.migriere(self.alt, self.verz, "r"))
        self.assertEqual(zugangsdaten.lies(neu), "ghp_" + "b" * 36)
        self.assertEqual(stat.S_IMODE(os.stat(neu).st_mode), 0o600)
        # Kopie neuer (zugang gesetzt): bleibt, auch wenn anders
        zugangsdaten.schreibe(self.verz, "r", "ghp_" + "c" * 36)
        os.utime(self.alt, (10.0, 10.0))
        self.assertFalse(zugangsdaten.migriere(self.alt, self.verz, "r"))
        self.assertEqual(zugangsdaten.lies(neu), "ghp_" + "c" * 36)

    def test_schreibfehler_entfernt_veraltete_kopie(self):
        registriere_runner(self.d)
        zugangsdaten.schreibe(self.verz, "runner-vm-01", "alt_" + "a" * 36)
        self.alt.write_text("ghp_" + "g" * 36)
        argv = ["kopiere", "--ueberschreiben", "--alt", str(self.alt), "--verz", str(self.verz), "--runner-verz", str(self.d / "actions-runner")]
        aus, fehler = io.StringIO(), io.StringIO()
        with mock.patch.object(zugangsdaten, "schreibe", side_effect=OSError(28, "No space left on device")), \
             redirect_stdout(aus), mock.patch.object(zugangsdaten.sys, "stderr", fehler):
            self.assertEqual(zugangsdaten.main(argv), 2)
        self.assertEqual(aus.getvalue(), "runner-vm-01\n")
        self.assertNotIn("ghp_", fehler.getvalue() + aus.getvalue())
        self.assertFalse((self.verz / "runner-vm-01.token").exists())  # es gilt der alte Ort

    def test_migration_nichts_zu_tun(self):
        self.assertFalse(zugangsdaten.migriere(self.alt, self.verz, "runner-vm-01"))  # kein altes Token
        self.alt.write_text("t" * 20)
        self.assertFalse(zugangsdaten.migriere(self.alt, self.verz, None))            # kein Runner
        self.assertFalse(zugangsdaten.migriere(self.alt, self.verz, "../x"))          # ungültige ID
        self.assertFalse(self.verz.exists())

    def test_kommandozeile_gibt_nie_das_token_aus(self):
        self.alt.write_text("ghp_" + "d" * 36)
        rv = self.d / "actions-runner"
        argv = ["kopiere", "--alt", str(self.alt), "--verz", str(self.verz), "--runner-verz", str(rv)]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(zugangsdaten.main(argv), 3)  # noch kein Runner registriert
        registriere_runner(self.d, "Runner VM 01")       # ungültiger Name → keine ID
        with redirect_stdout(io.StringIO()):
            self.assertEqual(zugangsdaten.main(argv), 3)
        registriere_runner(self.d)
        aus = io.StringIO()
        with redirect_stdout(aus):
            self.assertEqual(zugangsdaten.main(argv), 0)
        self.assertEqual(aus.getvalue(), "runner-vm-01\n")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(zugangsdaten.main(argv), 3)  # schon da
        self.alt.write_text("ghp_" + "e" * 36)
        aus = io.StringIO()
        with redirect_stdout(aus):
            self.assertEqual(zugangsdaten.main([*argv, "--ueberschreiben"]), 0)
        self.assertNotIn("ghp_", aus.getvalue())
        self.assertEqual(zugangsdaten.lies(self.verz / "runner-vm-01.token"), "ghp_" + "e" * 36)

    def test_liste_aus_der_erkennung(self):
        datei = self.d / "erkennung.json"
        datei.write_text(json.dumps({"zeit": 1, "runner": [
            {"id": "runner-vm-02", "name": "runner-vm-02\x1b[31m", "dienst": "forgejo", "grad": "sicher", "stand": "offen", "einstufung": "teil", "merkmale": [], "faehig": {}},
            {"id": "alt", "name": "alt", "dienst": "gitea", "grad": "sicher", "stand": "ignoriert", "einstufung": "teil", "merkmale": [], "faehig": {}}]}))
        aus = io.StringIO()
        with redirect_stdout(aus):
            self.assertEqual(zugangsdaten.main(["liste", "--erkennung", str(datei)]), 0)
        self.assertIn("runner-vm-02", aus.getvalue())
        self.assertIn("Forgejo", aus.getvalue())
        self.assertNotIn("\x1b", aus.getvalue())
        self.assertNotIn("alt ", aus.getvalue())
        # mit --runner-verz: GitHub-Runner des Monitors gekennzeichnet
        registriere_runner(self.d, "runner-vm-02")
        aus = io.StringIO()
        with redirect_stdout(aus):
            zugangsdaten.main(["liste", "--erkennung", str(datei), "--runner-verz", str(self.d / "actions-runner")])
        self.assertIn("GitHub-Runner des Monitors", aus.getvalue())


class SammlerTokenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.k = lade_konfig(self.d)
        self.k.token_datei.parent.mkdir(parents=True)
        self.k.auftraege_verz.mkdir(parents=True)
        registriere_runner(self.d)
        self.s = sammler.Sammler(self.k)
        self.neu = self.k.zugang_verz / "runner-vm-01.token"

    def tearDown(self):
        self.tmp.cleanup()

    def test_migration_beim_start(self):
        self.k.token_datei.write_text("ghp_" + "a" * 36 + "\n")
        self.s.migriere_token()
        self.assertEqual(zugangsdaten.lies(self.neu), "ghp_" + "a" * 36)
        self.assertEqual(self.k.token_datei.read_text(), "ghp_" + "a" * 36 + "\n")  # alt unverändert
        self.assertEqual(self.k.zugang_verz, self.k.token_datei.parent / "zugang")

    def test_migration_wartet_auf_den_runner(self):
        (self.d / "actions-runner" / ".runner").unlink()
        self.k.token_datei.write_text("ghp_" + "a" * 36)
        self.s.migriere_token()
        self.assertFalse(self.neu.exists())
        registriere_runner(self.d)
        self.s.migriere_token()   # nächster Takt
        self.assertTrue(self.neu.exists())

    def test_token_je_runner_geht_vor(self):
        self.k.token_datei.write_text("alt_" + "a" * 36)
        self.assertEqual(self.s.token(), "alt_" + "a" * 36)   # Rückfall
        zugangsdaten.schreibe(self.k.zugang_verz, "runner-vm-01", "neu_" + "b" * 36)
        self.assertEqual(self.s.token(), "neu_" + "b" * 36)

    def test_auftrag_aus_der_einrichtung_schreibt_beide_orte(self):
        zugangsdaten.schreibe(self.k.zugang_verz, "runner-vm-01", "alt_" + "a" * 36)
        (self.k.auftraege_verz / "github-token").write_text(json.dumps({"token": "ghp_" + "f" * 36}))
        self.s.auftraege()
        self.assertEqual(self.k.token_datei.read_text().strip(), "ghp_" + "f" * 36)
        self.assertEqual(zugangsdaten.lies(self.neu), "ghp_" + "f" * 36)
        self.assertEqual(self.s.token(), "ghp_" + "f" * 36)

    def test_veraltete_kopie_beim_start_ersetzt(self):
        zugangsdaten.schreibe(self.k.zugang_verz, "runner-vm-01", "alt_" + "a" * 36)
        os.utime(self.neu, (1000.0, 1000.0))
        self.k.token_datei.write_text("ghp_" + "n" * 36)   # z. B. mit einer älteren Version erneuert
        self.s.migriere_token()
        self.assertEqual(self.s.token(), "ghp_" + "n" * 36)

    def test_schreibfehler_im_sammler(self):
        zugangsdaten.schreibe(self.k.zugang_verz, "runner-vm-01", "alt_" + "a" * 36)
        (self.k.auftraege_verz / "github-token").write_text(json.dumps({"token": "ghp_" + "h" * 36}))
        with mock.patch.object(zugangsdaten, "schreibe", side_effect=OSError(28, "No space left on device")), \
             self.assertLogs("runner_monitor.sammler", "WARNING") as log:
            self.s.auftraege()
        self.assertIn("veraltete Kopie entfernt", log.output[0])
        self.assertNotIn("ghp_", " ".join(log.output))
        self.assertFalse(self.neu.exists())
        self.assertEqual(self.s.token(), "ghp_" + "h" * 36)  # der alte Ort hat das neue Token

    def test_github_ueber_den_adapter(self):
        with mock.patch.object(gh_adapter, "abfrage", wraps=gh_adapter.abfrage) as aufruf:
            self.s.github()
        klient, org, name, _ = aufruf.call_args.args
        self.assertEqual((klient.token, org, name), ("", "beispiel-org", "runner-vm-01"))
        erg = json.loads((self.k.lauf_verz / "github.json").read_text())
        self.assertEqual(erg["abfrage"], "kein-token")


# ---------------------------------------------------------------- runner[], meldungen[] und /api/zustand


def fund(rid, dienst, **mehr):
    f = {"id": rid, "name": rid, "dienst": dienst, "server": None, "version": None, "grad": "sicher", "merkmale": [],
         "einstufung": erkennung.EINSTUFUNG[dienst], "stand": "offen", "unit": None, "log": None,
         "faehig": dict(erkennung.FAEHIG[dienst]), "aktiv": True, "grund": None}
    f.update(mehr)
    return f


class RunnerListeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.k = lade_konfig(self.d)
        (self.d / "lauf").mkdir()
        self.k.token_datei.parent.mkdir(parents=True)
        registriere_runner(self.d)
        self.z = zustand.Zustand(self.k)
        self.unit = "actions.runner.beispiel-org.runner-vm-01.service"
        diag = f"{self.k.runner_verz}/_diag"
        self.funde = [
            fund("runner-vm-01", "github", unit=self.unit, log=diag, stand="angebunden", version="2.338.1"),
            fund("runner-vm-02", "forgejo", unit="forgejo-runner.service", server="https://git.example.org", log="/tmp/aus-dem-fund.log"),
            fund("buildagent", "unbekannt", unit="buildagent.service", grad="unklar"),
            fund("runner-vm-03", "gitea", unit="act_runner.service", stand="ignoriert"),
            fund("nur-datei", "github", grad="wahrscheinlich"),  # ohne Unit (.runner in /home)
        ]
        (self.d / "lauf" / "erkennung.json").write_text(json.dumps({"zeit": 1.0, "runner": self.funde}))
        (self.k.zuordnung_datei).write_text(json.dumps({"version": 1, "runner": {"buildagent": {"log": "/var/log/buildagent/agent.log"}}}))
        self.dienste = {self.unit: "aktiv", "forgejo-runner.service": "gestoppt", "buildagent.service": "aktiv"}

    def tearDown(self):
        self.tmp.cleanup()

    def dienst_status(self, unit):
        return {"zustand": self.dienste.get(unit, "fehlt"), "seit": 10.0, "unit": unit, "grund": None}

    def takt(self):
        with mock.patch.object(runner, "finde_unit", return_value=self.unit), \
             mock.patch.object(runner, "dienst_status", side_effect=self.dienst_status), \
             mock.patch.object(runner, "runner_version", return_value="2.338.1"):
            self.z.ein_takt(0)
        return self.z.bereiche["status"], self.z.bereiche["runner"], self.z.bereiche["meldungen"]

    def test_bestehender_status_bleibt(self):
        status, _, _ = self.takt()
        self.assertEqual(set(status), STATUS_SCHLUESSEL)
        self.assertEqual((status["runner"], status["dienst"]["zustand"]), ("runner-vm-01", "aktiv"))
        self.assertEqual(set(self.z.bereiche["workflows"]), WORKFLOWS_SCHLUESSEL)

    def test_runner_liste(self):
        status, liste, _ = self.takt()
        self.assertEqual([r["id"] for r in liste], ["runner-vm-01", "runner-vm-02", "buildagent", "nur-datei"])  # ignoriert fehlt
        for r in liste:
            self.assertEqual(set(r), EINTRAG_SCHLUESSEL, r["id"])
        gh, fj, ba, nd = liste
        # github.json fehlt (noch keine Abfrage): trotz Fund „angebunden“ nur „offen“ (Review #111)
        self.assertEqual((gh["dienst"], gh["server"], gh["org"], gh["stand"], gh["einstufung"]), ("github", "https://github.com", "beispiel-org", "offen", "voll"))
        self.assertEqual(gh["faehig"], erkennung.FAEHIG["github"])
        self.assertEqual(gh["status"]["zustand"], "bereit")
        self.assertEqual(gh["status"]["dienst"], status["dienst"])
        self.assertEqual(gh["log"], {"art": "seiten", "unit": self.unit})  # keine Pfade der VM in /api/zustand
        self.assertEqual(gh["jobsJeRepository"], self.z.bereiche["workflows"])
        self.assertEqual(gh["letzteJobs"], [])
        # Forgejo ohne Server/Organisation in runner.json: Grundüberwachung, Server und Log nie aus dem Fund (E-18)
        self.assertEqual((fj["status"]["zustand"], fj["server"], fj["einstufung"]), ("gestoppt", None, "teil"))
        self.assertEqual(fj["faehig"], {"status": True, "jobs": False, "schritte": False, "logs": True, "updates": False})
        self.assertEqual(fj["log"], {"art": "journal", "unit": "forgejo-runner.service"})
        self.assertIsNone(fj["jobsJeRepository"])
        # Log-Datei nur aus runner.json
        self.assertEqual(ba["log"], {"art": "datei", "unit": "buildagent.service"})
        self.assertEqual(ba["status"]["zustand"], "aktiv")
        # ohne Unit: weder Status noch Log, kein systemctl-Aufruf
        self.assertEqual((nd["status"]["zustand"], nd["log"], nd["faehig"]["status"]), ("fehlt", None, False))

    def test_job_mit_schritt(self):
        self.z.bei_journal(runner.JobEreignis(art="start", zeit=100.0, name="test"))
        (self.d / "lauf" / "github.json").write_text(json.dumps({
            "abfrage": "ok", "org": "beispiel-org", "abgefragt": 100.0, "runner": {"zustand": "online"},
            "job": {"name": "test", "start": 100.0, "repo": "projekt-a", "schritte": ["Set up job", "Tests", "Build"], "schritt": 2}}))
        _, liste, _ = self.takt()
        self.assertEqual(liste[0]["status"]["beimDienst"], {"zustand": "online", "seit": None})
        job = liste[0]["job"]
        self.assertEqual(liste[0]["status"]["zustand"], "job")
        self.assertEqual(job["schritt"], {"nr": 2, "von": 3, "name": "Tests"})
        self.assertEqual(job, self.z.bereiche["status"]["job"])

    def test_stand_nach_abfrage(self):
        pfad = self.d / "lauf" / "github.json"
        for abfrage, erwartet in (("ok", "angebunden"), ("nicht-erreichbar", "angebunden"), ("kontingent", "angebunden"),
                                  ("kein-token", "offen"), ("token-ungueltig", "offen"), ("keine-rechte", "offen"), ("fehler", "offen")):
            pfad.write_text(json.dumps({"abfrage": abfrage, "org": "beispiel-org", "abgefragt": 100.0}))
            os.utime(pfad, (len(abfrage) * 1000.0, len(abfrage) * 1000.0 + hash(abfrage) % 997))  # mtime ändert sich sicher
            _, liste, _ = self.takt()
            self.assertEqual(liste[0]["stand"], erwartet, abfrage)
        # ohne Fund (noch keine Erkennung) gilt dieselbe Regel
        (self.d / "lauf" / "erkennung.json").unlink()
        pfad.write_text(json.dumps({"abfrage": "ok", "org": "beispiel-org", "abgefragt": 1.0}))
        os.utime(pfad, (5.0, 5.0))
        _, liste, _ = self.takt()
        self.assertEqual(liste[0]["stand"], "angebunden")

    def test_stand_grund_bleibt(self):
        self.funde[0]["stand"] = "grund"
        (self.d / "lauf" / "erkennung.json").write_text(json.dumps({"zeit": 1.0, "runner": self.funde}))
        (self.d / "lauf" / "github.json").write_text(json.dumps({"abfrage": "ok", "abgefragt": 1.0}))
        _, liste, _ = self.takt()
        self.assertEqual(liste[0]["stand"], "grund")

    def test_meldungen_mit_runner(self):
        _, _, meldungen = self.takt()
        arten = [(m["id"], m["runner"], m["stufe"]) for m in meldungen]
        self.assertIn(("gestoppt", "runner-vm-02", "fehler"), arten)
        self.assertIn(("token", "runner-vm-01", "neutral"), arten)  # github.json fehlt → kein Token
        self.assertEqual(arten[0][2], "fehler")  # nach Schwere sortiert
        self.assertNotIn("buildagent", [m["runner"] for m in meldungen])

    def test_platte_ohne_runner(self):
        self.z.bereiche["platten"] = [{"pfad": "/", "gesamt": 100, "frei": 5, "belegt": 95, "schwelleFrei": 25}]
        _, _, meldungen = self.takt()
        platte = [m for m in meldungen if m["id"] == "platte"]
        self.assertEqual(platte[0]["runner"], None)

    def test_ohne_runner(self):
        (self.d / "actions-runner" / ".runner").unlink()
        (self.d / "lauf" / "erkennung.json").unlink()
        _, liste, meldungen = self.takt()
        self.assertEqual(liste, [])
        self.assertEqual([(m["id"], m["runner"]) for m in meldungen], [("fehlt", None)])

    def test_kaputte_erkennung_wird_ignoriert(self):
        (self.d / "lauf" / "erkennung.json").write_text('{"zeit": 1, "runner": [{"id": "../x"}]}')
        _, liste, _ = self.takt()
        self.assertEqual([r["id"] for r in liste], ["runner-vm-01"])

    def test_nur_bei_aenderung_gesendet(self):
        q = self.z.verteiler.anmelden()
        self.takt()
        self.takt()
        bereiche = []
        while not q.empty():
            bereiche.append(q.get_nowait()[0])
        self.assertEqual(bereiche.count("runner"), 1)
        self.assertEqual(bereiche.count("meldungen"), 1)
        self.assertEqual(bereiche.count("status"), 2)  # status wie bisher in jedem Takt

    def test_zustand_api_additiv(self):
        self.takt()
        api = self.z.zustand_api()
        alt = dict(self.z.momentaufnahme())
        for bereich in ("status", "workflows"):
            self.assertEqual(api[bereich], alt[bereich], bereich)
        self.assertEqual(api["format"], 2)
        self.assertEqual(api["runner"], alt["runner"])
        self.assertEqual(api["meldungen"], alt["meldungen"])
        self.assertEqual(set(api["vm"]), {"name", "system", "monitorVersion", "auslastung", "verlauf", "prozesse", "platten", "container"})
        self.assertIn("start", api["vm"]["verlauf"])
        self.assertNotIn("_github", api)
        self.assertNotIn("log", api)
        json.dumps(api)  # serialisierbar


class ApiZustandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.k = lade_konfig(d, MONITOR_PORT="1", MONITOR_WEB_VERZ=str(Path(__file__).resolve().parent.parent / "web"))
        self.app = server.App(self.k)
        self.srv = server.ThreadingHTTPServer(("127.0.0.1", 0), type("H", (server.Handler,), {"app": self.app}))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def hole(self, cookie=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=5)
        c.request("GET", "/api/zustand", headers={"Cookie": cookie} if cookie else {})
        r = c.getresponse()
        inhalt = r.read()
        c.close()
        return r, inhalt

    def test_nur_angemeldet(self):
        r, _ = self.hole()
        self.assertEqual(r.status, 302)  # noch nicht eingerichtet → /einrichtung
        self.app.zugang.lege_an("verwaltung", "Pferd-Batterie-Heftklammer-42")
        r, _ = self.hole()
        self.assertEqual(r.status, 401)
        token = self.app.zugang.anmelden("verwaltung", "Pferd-Batterie-Heftklammer-42", "127.0.0.1", False)
        self.app.zustand._setze("status", {"vm": "runner-vm"})
        r, inhalt = self.hole(f"{server.COOKIE}={token}")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        daten = json.loads(inhalt)
        self.assertEqual(daten["status"], {"vm": "runner-vm"})
        self.assertEqual(daten["vm"]["name"], "runner-vm")
        self.assertEqual((daten["format"], daten["runner"], daten["meldungen"]), (2, [], []))


if __name__ == "__main__":
    unittest.main()
