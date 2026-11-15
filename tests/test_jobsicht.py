"""Laufende und wartende Jobs je Repository (#171): Vergleichsdauern und Schätzung (Median der letzten 5 erfolgreichen
Läufe), Warteschlange mit Position, Forgejo-Abfrage mit Schritten, Grenzen der Anfragen und Zwischenspeicher, dazu
GitHub und GitLab, soweit ihre Antworten die Daten hergeben. Kein Netz: Attrappen mit erfundenen Antworten."""
import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from runner_monitor.anbieter import RunnerKonfig
from runner_monitor.anbieter import forgejo as fj
from runner_monitor.anbieter import github as gh_adapter
from runner_monitor.anbieter import gitlab, jobsicht
from tests.test_anbieter import AttrappeKlient
from tests.test_forgejo import Attrappe, lade, nicht_erreichbar

T0 = datetime(2026, 10, 29, 10, 0, 0, tzinfo=timezone(timedelta(hours=1)))
WEB = "/repos/beispiel-org/web-portal/actions"
API = "/repos/beispiel-org/api-dienst/actions"


def iso(sekunden: float) -> str:
    return (T0 + timedelta(seconds=sekunden)).isoformat()


# ---------------------------------------------------------------- reine Auswertung


class VergleichTest(unittest.TestCase):
    def test_median_gerade_und_ungerade(self):
        self.assertIsNone(jobsicht.median([]))
        self.assertEqual(jobsicht.median([5]), 5)
        self.assertEqual(jobsicht.median([300, 100, 200]), 200)
        self.assertEqual(jobsicht.median([100, 200, 300, 500]), 250)

    def test_vergleich_median_der_letzten_fuenf(self):
        # neueste zuerst: nur die ersten fünf zählen, der Ausreißer danach nicht
        self.assertEqual(jobsicht.vergleich([200, 400, 300, 360, 340, 9999]), {"median": 340.0, "anzahl": 5})
        self.assertEqual(jobsicht.vergleich([600, 660]), {"median": 630.0, "anzahl": 2})
        self.assertEqual(jobsicht.vergleich([274.4]), {"median": 274.4, "anzahl": 1})

    def test_ohne_vergleichswerte_keine_schaetzung(self):
        for dauern in ([], [0], [0, 0, 0], [None, "x", True, float("nan"), float("inf"), -5]):
            self.assertIsNone(jobsicht.vergleich(dauern), dauern)

    def test_unbrauchbare_dauern_werden_uebersprungen_und_zaehlen_nicht_als_fuenf(self):
        self.assertEqual(jobsicht.vergleich([0, 100, None, 300, 200, 400, 500, 600]), {"median": 300.0, "anzahl": 5})
        self.assertIsNone(jobsicht.vergleich([jobsicht.MAX_DAUER + 1]))   # länger als 30 Tage ist keine Jobdauer

    def test_dauer_zwischen(self):
        self.assertEqual(jobsicht.dauer_zwischen(100.0, 160.5), 60.5)
        for a, b in ((None, 1.0), (1.0, None), (5.0, 5.0), (9.0, 1.0), ("a", 1.0), (0.0, jobsicht.MAX_DAUER + 1), (True, 5.0)):
            self.assertIsNone(jobsicht.dauer_zwischen(a, b), (a, b))


class WarteschlangeTest(unittest.TestCase):
    def eintrag(self, repo, seit, nr, blockiert=False):
        return {"repo": repo, "privat": False, "workflow": "ci", "ref": {"art": "Branch", "name": "main", "titel": ""}, "seit": seit, "blockiert": blockiert, "_id": nr}

    def test_aeltester_zuerst_mit_position(self):
        liste = [self.eintrag("a", 300.0, 1), self.eintrag("b", 100.0, 2), self.eintrag("c", 200.0, 3)]
        erg = jobsicht.positionen(liste, True)
        self.assertEqual([(e["repo"], e["pos"]) for e in erg], [("b", 1), ("c", 2), ("a", 3)])
        self.assertFalse([k for e in erg for k in e if k.startswith("_")])

    def test_blockierte_stehen_am_ende_ohne_position_und_zaehlen_nicht(self):
        liste = [self.eintrag("a", 50.0, 1, blockiert=True), self.eintrag("b", 100.0, 2), self.eintrag("c", 200.0, 3)]
        self.assertEqual([(e["repo"], e["pos"]) for e in jobsicht.positionen(liste, True)], [("b", 1), ("c", 2), ("a", None)])

    def test_ohne_zeit_ohne_position_am_ende_der_unblockierten(self):
        liste = [self.eintrag("a", None, 1), self.eintrag("b", 100.0, 2)]
        self.assertEqual([(e["repo"], e["pos"]) for e in jobsicht.positionen(liste, True)], [("b", 1), ("a", None)])

    def test_position_nur_wenn_alle_repositories_lesbar_waren(self):
        liste = [self.eintrag("a", 1.0, 1), self.eintrag("b", 2.0, 2)]
        self.assertEqual([e["pos"] for e in jobsicht.positionen(liste, False)], [None, None])

    def test_gleiche_zeit_nach_lauf_id_und_begrenzt(self):
        liste = [self.eintrag("a", 5.0, 9), self.eintrag("b", 5.0, 2)]
        self.assertEqual([e["repo"] for e in jobsicht.positionen(liste, True)], ["b", "a"])
        viele = [self.eintrag("r", float(i), i + 1) for i in range(jobsicht.MAX_WARTENDE + 20)]
        self.assertEqual(len(jobsicht.positionen(viele, True)), jobsicht.MAX_WARTENDE)


# ---------------------------------------------------------------- Forgejo


class Erfolgreiche(Attrappe):
    """Wie die Attrappe, antwortet aber auf ``?status=success`` mit eigenen Listen (erfolgreiche Läufe je Repository)."""

    def __init__(self, antworten, erfolgreich=None, **kw):
        super().__init__(antworten, **kw)
        self.erfolgreich = erfolgreich or {}
        self.erfolg_fehler = None

    def hole(self, pfad, parameter=None, *, text=False):
        if pfad.endswith("/actions/runs") and (parameter or {}).get("status") == "success":
            self.zaehler["anfragen"] += 1
            self.pfade.append((pfad, parameter, text))
            if self.erfolg_fehler:
                raise self.erfolg_fehler
            return fj.Antwort({"workflow_runs": copy.deepcopy(self.erfolgreich.get(pfad, []))}, {})
        return super().hole(pfad, parameter, text=text)

    def vergleichsanfragen(self):
        return [p for p, par, _ in self.pfade if (par or {}).get("status") == "success"]


def erfolgslauf(nr, workflow, dauer, start=0):
    return {"id": nr, "workflow_id": workflow, "status": "success", "started": iso(start), "stopped": iso(start + dauer), "prettyref": "main"}


def mit_vergleichslaeufen(antworten, dauern, erster=21):
    """Erfolgreiche Läufe ``ci.yml`` mit je zwei Jobs (lint, build); ``dauern`` = Dauern von „build“, neueste zuletzt in der Liste."""
    laeufe = []
    for i, dauer in enumerate(dauern):
        nr = erster + i
        laeufe.append(erfolgslauf(nr, "ci.yml", dauer + 50, start=-86400 + nr))
        lint, build = 5000 + nr * 2, 5001 + nr * 2
        antworten[f"{WEB}/runs/{nr}/jobs"] = [{"id": lint, "name": "lint", "status": "success"}, {"id": build, "name": "build", "status": "success"}]
        antworten[f"{WEB}/jobs/{build}"] = {"id": build, "name": "build", "status": "success", "steps": [
            {"name": "Set up job", "status": "success", "started": iso(0), "stopped": iso(2)},
            {"name": "Tests", "status": "success", "started": iso(2), "stopped": iso(dauer)}]}
    return laeufe


class ForgejoLaufendeTest(unittest.TestCase):
    def setUp(self):
        self.antworten = lade("forgejo-17.json")

    def abfrage(self, attrappe=None, speicher=None, name="runner-vm-02"):
        self.k = attrappe or Attrappe(self.antworten)
        self.speicher = {} if speicher is None else speicher
        return fj.abfrage(self.k, "beispiel-org", name, self.speicher)

    def test_laufende_jobs_mit_schritt_runner_und_start(self):
        erg = self.abfrage()
        eigener, fremder = erg["laufende"]
        self.assertEqual((eigener["repo"], eigener["workflow"], eigener["name"], eigener["eigener"], eigener["runner"]), ("web-portal", "ci", "build", True, "runner-vm-02"))
        self.assertEqual(eigener["schritt"], {"nr": 3, "von": 5, "name": "Tests", "start": 1793264404.0})
        self.assertEqual(eigener["start"], 1793264401.0)
        self.assertEqual(eigener["ref"], {"art": "Branch", "name": "main", "titel": "Abhängigkeiten aktualisieren"})
        # der Job eines anderen Runners: Runner unbekannt (Forgejo nennt ihn nur als UUID im Log), Schritte aus /actions/jobs/{id}
        self.assertEqual((fremder["repo"], fremder["name"], fremder["eigener"], fremder["runner"]), ("api-dienst", "paket", False, None))
        self.assertIsNone(fremder["schritt"])   # die Attrappe kennt /actions/jobs/120 nicht (Forgejo vor 17)
        self.assertEqual(sorted(eigener), ["eigener", "name", "privat", "ref", "repo", "runner", "schritt", "start", "vergleich", "workflow"])
        json.dumps(erg)

    def test_schritte_der_anderen_jobs_nur_begrenzt(self):
        self.antworten[f"{API}/jobs/120"] = {"id": 120, "name": "paket", "status": "running", "steps": [
            {"name": "Set up job", "status": "success", "started": iso(0), "stopped": iso(3)}, {"name": "Paket bauen", "status": "running", "started": iso(3)}]}
        erg = self.abfrage()
        self.assertEqual(erg["laufende"][1]["schritt"], {"nr": 2, "von": 2, "name": "Paket bauen", "start": T0.timestamp() + 3})
        with mock.patch.object(fj, "MAX_SCHRITT_JOBS", 0):
            k = Attrappe(self.antworten)
            erg = fj.abfrage(k, "beispiel-org", "runner-vm-02", {})
        self.assertNotIn(f"{API}/jobs/120", [p for p, _, _ in k.pfade])
        self.assertIsNone(erg["laufende"][1]["schritt"])
        self.assertEqual(erg["laufende"][0]["schritt"]["nr"], 3)   # der eigene Job kennt seine Schritte immer

    def test_zuordnung_unbekannt_ist_kein_anderer_runner(self):
        """Runner beim Dienst nicht erkennbar (kein Fund, keine UUID): „eigener“ bleibt offen, nie „anderer Runner“."""
        erg = self.abfrage(name="runner-vm-99")
        self.assertEqual([(j["repo"], j["eigener"], j["runner"]) for j in erg["laufende"]], [("web-portal", None, None), ("api-dienst", None, None)])
        self.assertIsNone(erg["job"])

    def test_wartende_mit_position_nach_alter(self):
        a = self.antworten
        a[f"{WEB}/runs"]["workflow_runs"] += [
            {"id": 40, "workflow_id": "ci.yml", "prettyref": "feature/a", "trigger_event": "push", "status": "waiting", "created": iso(-1800)},
            {"id": 41, "workflow_id": "ci.yml", "prettyref": "main", "trigger_event": "push", "status": "waiting", "created": iso(-3000)},
            {"id": 42, "workflow_id": "deploy.yml", "prettyref": "main", "trigger_event": "push", "status": "blocked", "created": iso(-4000)}]
        a[f"{API}/runs"]["workflow_runs"][1]["created"] = iso(-2400)   # Lauf 14: wartet
        erg = self.abfrage()
        self.assertEqual([(w["repo"], w["workflow"], w["pos"], w["blockiert"]) for w in erg["wartende"]],
                         [("web-portal", "ci", 1, False), ("api-dienst", "ci", 2, False), ("web-portal", "ci", 3, False), ("web-portal", "deploy", None, True)])
        self.assertEqual(erg["wartende"][0]["seit"], T0.timestamp() - 3000)
        self.assertEqual(erg["wartende"][1]["ref"], {"art": "PR", "name": "#12", "titel": "Tests"})
        self.assertEqual([(r["name"], r["wartet"]) for r in erg["repos"]], [("web-portal", 3), ("api-dienst", 1)])

    def test_keine_position_wenn_ein_repository_nicht_lesbar_war(self):
        self.antworten[f"{API}/runs"]["workflow_runs"][1]["created"] = iso(-2400)
        erg = self.abfrage(Attrappe(self.antworten, fehler={f"{WEB}/runs": fj.ForgejoFehler("fehlt", "404")}))
        self.assertEqual(erg["laeufeNichtLesbar"], 1)
        self.assertEqual([(w["repo"], w["pos"]) for w in erg["wartende"]], [("api-dienst", None)])

    def test_ohne_zeit_keine_position(self):
        erg = self.abfrage()   # die aufgezeichnete Antwort nennt für den wartenden Lauf kein „created“
        self.assertEqual([(w["repo"], w["seit"], w["pos"]) for w in erg["wartende"]], [("api-dienst", None, None)])

    def test_gesamte_runde_fehler_leert_die_neuen_felder(self):
        erg = self.abfrage(Attrappe({}, fehler={"/version": nicht_erreichbar()}))
        self.assertEqual((erg["abfrage"], erg["laufende"], erg["wartende"]), ("nicht-erreichbar", [], []))

    def test_job_listen_je_runde_nur_einmal(self):
        self.abfrage()
        pfade = [p for p, _, _ in self.k.pfade]
        self.assertEqual(len([p for p in pfade if p.endswith("/runs/11/jobs")]), 1)
        self.assertEqual(len([p for p in pfade if p.endswith("/runs/13/jobs")]), 1)

    def test_nur_die_ersten_laeufe_werden_gelesen(self):
        laeufe = [{"id": 100 + i, "workflow_id": "ci.yml", "prettyref": "main", "status": "running"} for i in range(jobsicht.MAX_LAUFENDE + 5)]
        a = {**self.antworten, f"{WEB}/runs": {"workflow_runs": laeufe}}
        for lauf in laeufe:
            a[f"{WEB}/runs/{lauf['id']}/jobs"] = [{"id": 900 + lauf["id"], "name": "build", "status": "running"}]
            a[f"{WEB}/jobs/{900 + lauf['id']}/logs"] = ""   # noch ohne erste Zeile: Runner unbekannt
        k = Attrappe(a)
        erg = fj.abfrage(k, "beispiel-org", fj.Kennung(), {})   # ohne Namen und UUID: nur die Sicht auf die Organisation
        self.assertEqual(len([p for p, _, _ in k.pfade if p.endswith("/jobs") and "/runs/" in p and p.startswith(WEB)]), fj.MAX_LAUFENDE_LAEUFE)
        self.assertLessEqual(len(erg["laufende"]), jobsicht.MAX_LAUFENDE)
        self.assertEqual(erg["repos"][0]["laeuft"], len(laeufe))   # der Zähler zählt trotzdem alle


class ForgejoVergleichTest(unittest.TestCase):
    def setUp(self):
        self.antworten = lade("forgejo-17.json")
        self.erfolgreich = {}

    def runde(self, speicher):
        self.k = Erfolgreiche(self.antworten, self.erfolgreich)
        return fj.abfrage(self.k, "beispiel-org", "runner-vm-02", speicher)

    def eigener(self, erg):
        return next(j for j in erg["laufende"] if j["eigener"])

    def test_median_der_letzten_fuenf_ueber_mehrere_runden_mit_grenze(self):
        # fünf erfolgreiche Läufe mit zwei Jobs: je Lauf Job-Liste und Job-Detail nötig (10 Anfragen) – mehr als eine Runde zulässt
        self.erfolgreich[f"{WEB}/runs"] = mit_vergleichslaeufen(self.antworten, [200, 400, 300, 360, 340])
        speicher = {}
        erg = self.runde(speicher)
        zusaetzlich = len([p for p, par, _ in self.k.pfade if (par or {}).get("status") == "success" or "/runs/2" in p or "/jobs/50" in p])
        self.assertLessEqual(zusaetzlich, fj.VERGLEICH_ANFRAGEN)
        teil = self.eigener(erg)["vergleich"]
        self.assertTrue(0 < teil["anzahl"] < 5, teil)
        self.assertEqual(erg["job"]["vergleich"], teil)   # derselbe Wert in der Runner-Karte
        erg = self.runde(speicher)
        self.assertEqual(self.eigener(erg)["vergleich"], {"median": 340.0, "anzahl": 5})
        self.assertEqual(erg["job"]["vergleich"], {"median": 340.0, "anzahl": 5})
        self.assertLessEqual(len([p for p, _, _ in self.k.pfade if "/runs/2" in p or "/jobs/50" in p]), fj.VERGLEICH_ANFRAGEN)
        # dritte Runde, kurz danach: alles gemerkt, keine Anfrage nach erfolgreichen Läufen mehr
        erg = self.runde(speicher)
        self.assertEqual(self.k.vergleichsanfragen(), [])
        self.assertEqual(self.eigener(erg)["vergleich"], {"median": 340.0, "anzahl": 5})
        self.assertNotIn("Token", json.dumps(speicher))

    def test_nur_gleicher_workflow_und_nur_erfolgreiche(self):
        laeufe = mit_vergleichslaeufen(self.antworten, [100, 200, 300])
        laeufe.append(erfolgslauf(30, "release.yml", 9999, start=-5))    # anderer Workflow
        laeufe.append({**erfolgslauf(31, "ci.yml", 9999, start=-4), "status": "failure"})  # nicht erfolgreich
        self.erfolgreich[f"{WEB}/runs"] = laeufe
        self.runde({})
        erg = self.runde({})
        self.assertEqual(self.eigener(erg)["vergleich"], {"median": 200.0, "anzahl": 3})
        self.assertNotIn(f"{WEB}/runs/30/jobs", [p for p, _, _ in self.k.pfade])

    def test_ein_job_im_lauf_braucht_keine_weiteren_anfragen(self):
        # api-dienst/release: der laufende Lauf 13 hat nur den Job „paket“ – die Laufzeit der früheren Läufe genügt
        self.erfolgreich[f"{API}/runs"] = [erfolgslauf(31, "release.yaml", 100, start=-300), erfolgslauf(32, "release.yaml", 200, start=-200), erfolgslauf(33, "release.yaml", 300, start=-100)]
        erg = self.runde({})
        fremder = next(j for j in erg["laufende"] if j["repo"] == "api-dienst")
        self.assertEqual(fremder["vergleich"], {"median": 200.0, "anzahl": 3})
        self.assertFalse([p for p, _, _ in self.k.pfade if f"{API}/runs/3" in p])

    def test_ohne_erfolgreiche_laeufe_keine_schaetzung(self):
        erg = self.runde({})
        self.assertEqual([j["vergleich"] for j in erg["laufende"]], [None, None])
        self.assertIsNone(erg["job"]["vergleich"])

    def test_lauf_ohne_den_job_oder_ohne_zeiten_zaehlt_nicht_und_wird_nicht_erneut_gefragt(self):
        laeufe = mit_vergleichslaeufen(self.antworten, [100, 200])
        laeufe.append(erfolgslauf(30, "ci.yml", 50, start=-5))   # Job „build“ fehlt in diesem Lauf
        self.antworten[f"{WEB}/runs/30/jobs"] = [{"id": 7001, "name": "lint", "status": "success"}]
        self.erfolgreich[f"{WEB}/runs"] = laeufe
        speicher = {}
        self.runde(speicher)
        erg = self.runde(speicher)
        self.assertEqual(self.eigener(erg)["vergleich"], {"median": 150.0, "anzahl": 2})
        self.assertEqual(speicher["vergleich"]["web-portal|ci|build"]["dauern"]["30"], 0)

    def test_erneuert_erst_nach_zehn_minuten(self):
        self.erfolgreich[f"{WEB}/runs"] = mit_vergleichslaeufen(self.antworten, [100])
        speicher = {}
        web = lambda: [p for p in self.k.vergleichsanfragen() if p.startswith(WEB)]  # noqa: E731
        self.runde(speicher)
        self.assertEqual(len(web()), 1)
        self.runde(speicher)
        self.assertEqual(web(), [])
        speicher["vergleich"]["web-portal|ci|build"]["geprueft"] -= fj.VERGLEICH_TAKT + 1
        self.runde(speicher)
        self.assertEqual(len(web()), 1)

    def test_zeitueberschreitung_oder_429_kostet_die_runde_nichts(self):
        self.erfolgreich[f"{WEB}/runs"] = mit_vergleichslaeufen(self.antworten, [100])
        for fehler in (nicht_erreichbar(), fj.ForgejoFehler("kontingent", "429")):
            k = Erfolgreiche(self.antworten, self.erfolgreich)
            k.erfolg_fehler = fehler
            erg = fj.abfrage(k, "beispiel-org", "runner-vm-02", {})
            self.assertEqual(erg["abfrage"], "ok", erg["fehler"])
            self.assertEqual(self.eigener(erg)["vergleich"], None)
            self.assertEqual(len(k.vergleichsanfragen()), 1, "nach dem Fehler keine weiteren Anfragen nach Vergleichsdauern")

    def test_wenig_zeit_in_der_runde_keine_freiwilligen_anfragen(self):
        self.erfolgreich[f"{WEB}/runs"] = mit_vergleichslaeufen(self.antworten, [100])
        k = Erfolgreiche(self.antworten, self.erfolgreich)
        k.rest = lambda: fj.SICHT_MIN_REST - 1
        erg = fj.abfrage(k, "beispiel-org", "runner-vm-02", {})
        self.assertEqual(erg["abfrage"], "ok")
        self.assertEqual(k.vergleichsanfragen(), [])
        self.assertNotIn(f"{API}/jobs/120", [p for p, _, _ in k.pfade])   # auch keine Schritte der anderen Jobs
        self.assertEqual(erg["laufende"][0]["schritt"]["nr"], 3)          # der eigene Job ist davon unberührt

    def test_speicher_merkt_hoechstens_so_viele_paare(self):
        speicher = {"vergleich": {f"r|w|{i}": {"dauern": {}, "geprueft": float(i)} for i in range(fj.MAX_VERGLEICHE + 10)}}
        self.runde(speicher)
        self.assertLessEqual(len(speicher["vergleich"]), fj.MAX_VERGLEICHE)
        self.assertIn("web-portal|ci|build", speicher["vergleich"])

    def test_beschaedigter_speicher_wird_ersetzt(self):
        speicher = {"vergleich": {"web-portal|ci|build": "kaputt", "api-dienst|release|paket": {"dauern": [1, 2]}}}
        erg = self.runde(speicher)
        self.assertEqual(erg["abfrage"], "ok")
        self.assertIsInstance(speicher["vergleich"]["web-portal|ci|build"], dict)


class ForgejoLetzteJobsTest(unittest.TestCase):
    def test_letzte_jobs_der_organisation_wenn_der_runner_nicht_erkennbar_ist(self):
        antworten = lade("forgejo-17.json")
        speicher = {}
        fj.abfrage(Attrappe(antworten), "beispiel-org", "runner-vm-99", speicher)
        self.assertEqual(sorted(speicher["laufend"]), ["120", "99"])
        # eine Runde später: die Läufe sind beendet
        ende = copy.deepcopy(antworten)
        for pfad in (f"{WEB}/runs", f"{API}/runs"):
            ende[pfad] = {"workflow_runs": []}
        ende[f"{WEB}/jobs/99"]["status"] = "success"
        k = Attrappe(ende)
        erg = fj.abfrage(k, "beispiel-org", "runner-vm-99", speicher)
        self.assertEqual(len(erg["letzteJobs"]), 1)
        letzter = erg["letzteJobs"][0]
        self.assertEqual((letzter["repo"], letzter["workflow"], letzter["name"], letzter["ergebnis"]), ("web-portal", "ci", "build", "erfolg"))
        self.assertGreater(letzter["dauer"], 0)
        self.assertEqual(erg["laufende"], [])

    def test_mit_erkennbarem_runner_nur_dessen_jobs(self):
        antworten = lade("forgejo-17.json")
        speicher = {}
        fj.abfrage(Attrappe(antworten), "beispiel-org", "runner-vm-02", speicher)
        self.assertEqual(sorted(speicher["laufend"]), ["99"])   # der Job von runner-vm-03 gehört nicht in „Letzte Jobs“ dieses Runners


# ---------------------------------------------------------------- GitHub und GitLab


class GitHubLaufendeTest(unittest.TestCase):
    def test_laufende_und_wartende_laeufe_ohne_weitere_anfragen(self):
        k = AttrappeKlient()
        erg = gh_adapter.abfrage(k, "beispiel-org", "runner-vm-01")
        self.assertEqual(erg["abfrage"], "ok")
        self.assertEqual(len(erg["laufende"]), 1)
        lauf = erg["laufende"][0]
        # der eigene Job (Job-Liste des Laufs) gibt dem laufenden Lauf Job-Name, Runner und Schritt
        self.assertEqual((lauf["repo"], lauf["workflow"], lauf["name"], lauf["eigener"], lauf["runner"]), ("projekt-a", "CI", "test", True, "runner-vm-01"))
        self.assertEqual(lauf["schritt"], {"nr": 2, "von": 2, "name": "Tests", "start": None})
        self.assertIsNone(lauf["vergleich"])       # GitHub: keine Vergleichsdauern (Kontingent schonen)
        self.assertEqual(len(erg["wartende"]), 1)
        self.assertEqual((erg["wartende"][0]["repo"], erg["wartende"][0]["blockiert"]), ("projekt-a", False))
        # keine zusätzlichen Anfragen gegenüber bisher: Repositories, Läufe, Job-Liste, Runner
        self.assertEqual(len(k.pfade), 4)
        a = gh_adapter.GitHub(RunnerKonfig(id="runner-vm-01", name="runner-vm-01", dienst="github"))
        w = a.jobs_je_repository(erg)
        self.assertEqual((w["laufende"], w["wartende"]), (erg["laufende"], erg["wartende"]))
        json.dumps(erg)

    def test_ohne_laeufe_leere_listen(self):
        self.assertEqual(gh_adapter.workflows_aus(None)["laufende"], [])
        self.assertEqual(gh_adapter.workflows_aus({"org": "x"})["wartende"], [])

    def test_waiting_ist_bei_github_blockiert(self):
        lauf = {"id": 3, "status": "waiting", "name": "Deploy", "created_at": "2026-10-29T09:00:00Z", "event": "push", "head_branch": "main"}
        w = gh_adapter.wartend_aus_lauf(lauf, "projekt-a", True, 3)
        self.assertTrue(w["blockiert"])
        self.assertEqual(jobsicht.positionen([w], True)[0]["pos"], None)


class GitLabLaufendeTest(unittest.TestCase):
    def test_laufende_jobs_dieses_runners(self):
        job = {"id": 7, "name": "build", "stage": "test", "ref": "main", "status": "running", "started_at": "2026-10-29T10:00:00Z",
               "project": {"name": "web-portal"}, "pipeline": {"id": 55}, "commit": {"title": "Abhängigkeiten aktualisiert"}}
        e = gitlab.laufender_aus(job)
        self.assertEqual((e["repo"], e["workflow"], e["name"], e["eigener"], e["schritt"], e["vergleich"]), ("web-portal", "Pipeline #55", "build", True, None, None))
        self.assertEqual(e["ref"]["name"], "main")
        w = gitlab.workflows_aus({"laufende": [e]})
        self.assertEqual((w["laufende"], w["wartende"], w["wartetUnbekannt"]), ([e], [], True))


if __name__ == "__main__":
    unittest.main()
