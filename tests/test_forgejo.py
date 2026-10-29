"""Forgejo- und Gitea-Adapter (#93): Abfrage mit aufgezeichneten, neutralisierten Antworten, Fehlerfälle,
Klient (keine Weiterleitung, Grenzen), Konfiguration nur aus runner.json (E-18), Sammler und runner[].

Kein Netz: Die Abfrage läuft gegen eine Attrappe; der Klient-Test nutzt nur Server auf 127.0.0.1.
"""
import copy
import http.server
import json
import os
import socketserver
import stat
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from runner_monitor import anbieter, erkennung, runner, sammler, zustand
from runner_monitor.anbieter import forgejo as fj
from tests.test_anbieter import EINTRAG_SCHLUESSEL, fund, lade_konfig, registriere_runner

DATEN = Path(__file__).parent / "daten"
TOKEN = "f" * 40
UUID_02 = "00000000-0000-4000-8000-000000000002"


def lade(name: str) -> dict:
    daten = json.loads((DATEN / name).read_text(encoding="utf-8"))
    daten.pop("_hinweis", None)
    return daten


class Attrappe:
    """Antwortet wie der Server aus den aufgezeichneten Antworten. ``fehler`` = {Pfad: ForgejoFehler}."""

    def __init__(self, antworten: dict, token: str = TOKEN, server: str = "https://git.example.org", fehler: dict | None = None):
        self.antworten = antworten
        self.token = token
        self.server = server
        self.fehler = fehler or {}
        self.zaehler = {"anfragen": 0}
        self.pfade: list[tuple[str, dict | None, bool]] = []

    def hole(self, pfad, parameter=None, *, text=False):
        self.zaehler["anfragen"] += 1
        self.pfade.append((pfad, parameter, text))
        if pfad in self.fehler:
            raise self.fehler[pfad]
        if pfad not in self.antworten:
            raise fj.ForgejoFehler("fehlt", f"{pfad} nicht gefunden (404)")
        antwort = copy.deepcopy(self.antworten[pfad])
        if isinstance(antwort, list) and parameter and parameter.get("page", 1) > 1:
            antwort = []  # nur eine Seite
        return fj.Antwort(antwort, {})


def nicht_erreichbar():
    return fj.ForgejoFehler("nicht-erreichbar", "Server nicht erreichbar (Connection refused)")


# ---------------------------------------------------------------- Auswertung


class ForgejoAbfrageTest(unittest.TestCase):
    def setUp(self):
        self.antworten = lade("forgejo-17.json")

    def abfrage(self, attrappe=None, speicher=None, name="runner-vm-02"):
        self.k = attrappe or Attrappe(self.antworten)
        self.speicher = {} if speicher is None else speicher
        return fj.abfrage(self.k, "beispiel-org", name, self.speicher)

    def test_runde_forgejo_17(self):
        erg = self.abfrage()
        self.assertEqual(erg["abfrage"], "ok", erg["fehler"])
        self.assertEqual((erg["art"], erg["serverVersion"]), ("forgejo", "17.0.1"))
        self.assertEqual(erg["runner"], {"zustand": "online", "beschaeftigt": True, "labels": ["linux-amd64", "ubuntu-latest"]})
        # archiviert, ohne Actions und ein ungültiger Name fehlen
        self.assertEqual(erg["repos"], [{"name": "web-portal", "privat": False, "laeuft": 1, "wartet": 0},
                                        {"name": "api-dienst", "privat": True, "laeuft": 1, "wartet": 1}])
        job = erg["job"]
        self.assertEqual((job["repo"], job["workflow"], job["name"]), ("web-portal", "ci", "build"))
        self.assertEqual(job["schritt"], {"nr": 3, "von": 5, "name": "Tests"})
        self.assertEqual(job["schritte"], ["Set up job", "actions/checkout@v7", "Tests", "Paket bauen", "Complete job"])
        self.assertEqual(job["ref"], {"art": "Branch", "name": "main", "titel": "Abhängigkeiten aktualisieren"})
        self.assertEqual(job["start"], 1793264401.0)  # erster Schritt, 10:00:01+01:00
        self.assertTrue(job["url"].startswith("https://git.example.org/"))
        self.assertFalse([k for k in job if k.startswith("_")])
        self.assertIs(erg["schritte"], True)
        self.assertEqual(erg["letzteJobs"], [])
        # nur lesend: alle Anfragen GET über hole(), keine Schreibpfade
        pfade = [p for p, _, _ in self.k.pfade]
        self.assertFalse([p for p in pfade if any(w in p for w in ("rerun", "cancel", "registration-token", "dispatches"))])
        self.assertNotIn("/repos/beispiel-org/altes-archiv/actions/runs", pfade)
        self.assertFalse([p for p in pfade if ".." in p])
        # der fremde Job (runner-vm-03) wurde nur am Log-Anfang erkannt, nicht im Detail geholt
        self.assertIn(("/repos/beispiel-org/api-dienst/actions/jobs/120/logs", None, True), self.k.pfade)
        self.assertNotIn("/repos/beispiel-org/api-dienst/actions/jobs/120", pfade)
        json.dumps(erg)  # wird so nach anbieter.json geschrieben
        self.assertNotIn(TOKEN, json.dumps(erg))

    def test_runner_wird_je_job_nur_einmal_im_log_gesucht(self):
        speicher = {}
        self.abfrage(speicher=speicher)
        k2 = Attrappe(self.antworten)
        fj.abfrage(k2, "beispiel-org", "runner-vm-02", speicher)
        self.assertFalse([p for p, _, text in k2.pfade if text])  # zweite Runde: aus dem Speicher
        self.assertEqual(speicher["besitzer"], "org")
        self.assertNotIn("/orgs/beispiel-org", [p for p, _, _ in k2.pfade])

    def test_anderer_runner_hat_den_job(self):
        erg = self.abfrage(name="runner-vm-03")
        self.assertEqual(erg["job"]["name"], "paket")
        self.assertEqual(erg["job"]["ref"]["art"], "Tag")
        self.assertEqual(erg["job"]["workflow"], "release")
        self.assertEqual(erg["runner"]["beschaeftigt"], False)

    def test_forgejo_ohne_schritte(self):
        """Forgejo vor 17: ``/actions/jobs/{id}`` fehlt – Job und Laufzeit ja, Schritte nein („teilweise“)."""
        del self.antworten["/repos/beispiel-org/web-portal/actions/jobs/99"]
        erg = self.abfrage()
        self.assertEqual(erg["job"]["name"], "build")
        self.assertEqual((erg["job"]["schritte"], erg["job"]["schritt"]), ([], None))
        self.assertIs(erg["schritte"], False)
        a = fj.Forgejo(anbieter.RunnerKonfig(id="runner-vm-02", name="runner-vm-02", dienst="forgejo", unit="forgejo-runner.service",
                                             server="https://git.example.org", org="beispiel-org"))
        e = a.eintrag(dienst={"zustand": "aktiv", "seit": 1, "grund": None}, ergebnis=erg, stand="angebunden")
        self.assertFalse(e["faehig"]["schritte"])
        self.assertTrue(e["faehig"]["jobs"])
        self.assertIsNone(e["job"]["schritt"])
        self.assertEqual(e["status"]["zustand"], "job")

    def test_ohne_recht_auf_die_runner_liste(self):
        """Ohne Besitzerrechte: Läufe ja, Online-Status unbekannt; Forgejo ordnet dann keinen Job zu
        (der Runner steht nur als UUID im Log)."""
        k = Attrappe(self.antworten, fehler={"/orgs/beispiel-org/actions/runners": fj.ForgejoFehler("keine-rechte", "403")})
        erg = self.abfrage(k)
        self.assertEqual(erg["abfrage"], "ok")
        self.assertEqual(erg["runner"]["zustand"], "unbekannt")
        self.assertIn("Besitzerrechte", erg["runner"]["grund"])
        self.assertEqual(len(erg["repos"]), 2)
        self.assertIsNone(erg["job"])
        a = fj.Forgejo(anbieter.RunnerKonfig(id="r", name="runner-vm-02", dienst="forgejo"))
        self.assertEqual(a.beim_dienst(erg), {"zustand": "unbekannt", "seit": None})
        self.assertIn("Besitzerrechte", a.jobs_je_repository(erg)["runnerGrund"])

    def test_letzte_jobs(self):
        speicher = {}
        self.abfrage(speicher=speicher)
        fertig = copy.deepcopy(self.antworten)
        fertig["/repos/beispiel-org/web-portal/actions/runs"]["workflow_runs"][0]["status"] = "success"
        detail = fertig["/repos/beispiel-org/web-portal/actions/jobs/99"]
        detail["status"] = "success"
        for s in detail["steps"]:
            s.update(status="success", started=s["started"] or "2026-10-29T10:03:00+01:00", stopped=s["stopped"] or "2026-10-29T10:04:00+01:00")
        erg = fj.abfrage(Attrappe(fertig), "beispiel-org", "runner-vm-02", speicher)
        self.assertIsNone(erg["job"])
        self.assertEqual(erg["letzteJobs"], [{"name": "build", "ergebnis": "erfolg", "dauer": 239.0, "ende": 1793264640.0,
                                              "repo": "web-portal", "workflow": "ci"}])
        self.assertEqual(speicher["laufend"], {})

    def test_letzte_jobs_ohne_job_detail_aus_der_liste(self):
        """Ältere Forgejo-Versionen: Ergebnis aus der Job-Liste des Laufs, Ende = jetzt; nie geraten."""
        del self.antworten["/repos/beispiel-org/web-portal/actions/jobs/99"]
        speicher = {}
        self.abfrage(speicher=speicher)
        fertig = copy.deepcopy(self.antworten)
        fertig["/repos/beispiel-org/web-portal/actions/runs"]["workflow_runs"][0]["status"] = "failure"
        fertig["/repos/beispiel-org/web-portal/actions/runs/11/jobs"][1]["status"] = "failure"
        erg = fj.abfrage(Attrappe(fertig), "beispiel-org", "runner-vm-02", speicher)
        self.assertEqual([(j["name"], j["ergebnis"]) for j in erg["letzteJobs"]], [("build", "fehler")])
        # Ergebnis nicht zu bekommen (Lauf gelöscht): nicht eintragen, später erneut versuchen
        speicher2 = {}
        self.abfrage(speicher=speicher2)
        weg = copy.deepcopy(self.antworten)
        weg["/repos/beispiel-org/web-portal/actions/runs"]["workflow_runs"] = []
        del weg["/repos/beispiel-org/web-portal/actions/runs/11/jobs"]
        erg = fj.abfrage(Attrappe(weg), "beispiel-org", "runner-vm-02", speicher2)
        self.assertEqual(erg["letzteJobs"], [])
        self.assertIn("99", speicher2["laufend"])

    def test_ruhige_repositories_seltener(self):
        for r in self.antworten["/orgs/beispiel-org/repos"]:
            r["updated_at"] = "2026-01-01T00:00:00Z"  # letzter Push lange her
        speicher = {}
        self.abfrage(speicher=speicher)
        for name in ("web-portal", "api-dienst"):
            speicher["ruhig"][name].update(laeuft=0, wartet=0)
        k2 = Attrappe(self.antworten)
        fj.abfrage(k2, "beispiel-org", "runner-vm-02", speicher)
        self.assertFalse([p for p, _, _ in k2.pfade if p.endswith("/actions/runs")])

    def test_benutzer_statt_organisation(self):
        antworten = {k.replace("/orgs/beispiel-org/repos", "/users/beispiel-org/repos")
                      .replace("/orgs/beispiel-org/actions/runners", "/user/actions/runners"): v
                     for k, v in self.antworten.items() if k != "/orgs/beispiel-org"}
        antworten["/users/beispiel-org"] = {"id": 3, "login": "beispiel-org"}
        erg = self.abfrage(Attrappe(antworten))
        self.assertEqual(erg["abfrage"], "ok", erg["fehler"])
        self.assertEqual(self.speicher["besitzer"], "user")
        self.assertEqual(erg["job"]["name"], "build")


class EinstufungTest(unittest.TestCase):
    def test_tabelle_verspricht_nie_mehr_als_ausgeliefert(self):
        """E-23 (#126): Forgejo „voll“ mit Jobs und Schritten; Gitea bleibt Grundüberwachung bis zur Prüfung an
        einem echten Server. Die Tabelle verspricht nie mehr als die Adapter-Klasse."""
        self.assertEqual(erkennung.EINSTUFUNG["forgejo"], "voll")
        self.assertTrue(erkennung.FAEHIG["forgejo"]["jobs"] and erkennung.FAEHIG["forgejo"]["schritte"])
        self.assertEqual(erkennung.EINSTUFUNG["gitea"], "teil")
        self.assertFalse(erkennung.FAEHIG["gitea"]["jobs"])
        self.assertFalse(erkennung.FAEHIG["gitea"]["schritte"])
        for dienst in ("forgejo", "gitea"):
            klasse = anbieter.klasse_fuer(dienst)
            self.assertTrue(klasse.FAEHIG["jobs"] and klasse.FAEHIG["schritte"], dienst)
            for f, wert in erkennung.FAEHIG[dienst].items():
                self.assertTrue(klasse.FAEHIG[f] or not wert, f"{dienst}.{f}")


class GiteaAbfrageTest(unittest.TestCase):
    def test_runde_gitea(self):
        speicher = {}
        k = Attrappe(lade("gitea.json"))
        erg = fj.abfrage(k, "beispiel-org", "runner-vm-04", speicher)
        self.assertEqual(erg["abfrage"], "ok", erg["fehler"])
        self.assertEqual((erg["art"], erg["serverVersion"]), ("gitea", "1.24.6"))
        self.assertEqual(erg["runner"], {"zustand": "online", "beschaeftigt": True, "labels": ["ubuntu-latest", "self-hosted"]})
        self.assertEqual(erg["repos"], [{"name": "web-portal", "privat": True, "laeuft": 1, "wartet": 1}])
        job = erg["job"]
        self.assertEqual((job["name"], job["workflow"], job["schritt"]), ("test", "ci", {"nr": 2, "von": 3, "name": "Tests"}))
        self.assertEqual(job["ref"], {"art": "PR", "name": "#7", "titel": "Anmeldung überarbeiten"})
        self.assertEqual(job["start"], 1793264405.0)
        self.assertFalse([p for p, _, text in k.pfade if text])  # Gitea nennt runner_name: kein Log nötig
        # nächste Runde: Job beendet (fehlgeschlagen)
        fertig = lade("gitea.json")
        fertig["/repos/beispiel-org/web-portal/actions/runs"]["workflow_runs"][0]["status"] = "completed"
        erg = fj.abfrage(Attrappe(fertig), "beispiel-org", "runner-vm-04", speicher)
        self.assertEqual(erg["letzteJobs"], [{"name": "test", "ergebnis": "fehler", "dauer": 240.0, "ende": 1793264645.0,
                                              "repo": "web-portal", "workflow": "ci"}])

    def test_offline(self):
        erg = fj.abfrage(Attrappe(lade("gitea.json")), "beispiel-org", "runner-vm-05", {})
        self.assertEqual(erg["runner"]["zustand"], "offline")
        a = fj.Gitea(anbieter.RunnerKonfig(id="runner-vm-05", name="runner-vm-05", dienst="gitea", unit="act_runner.service"))
        e = a.eintrag(dienst={"zustand": "aktiv", "seit": 1, "grund": None}, ergebnis={**erg, "job": None}, stand="angebunden")
        self.assertEqual(e["status"]["zustand"], "offline")


class FehlerTest(unittest.TestCase):
    """Fehlerfälle wie bei GitHub: kein Token, Token ungültig, keine Rechte, nicht erreichbar."""

    def runde(self, **fehler):
        return fj.abfrage(Attrappe(lade("forgejo-17.json"), fehler=fehler.get("fehler")), "beispiel-org", "runner-vm-02", {})

    def test_kein_token_fragt_nicht(self):
        k = Attrappe({}, token="")
        erg = fj.abfrage(k, "beispiel-org", "runner-vm-02", {})
        self.assertEqual(erg["abfrage"], "kein-token")
        self.assertEqual(k.pfade, [])

    def test_ohne_server_oder_organisation(self):
        self.assertEqual(fj.abfrage(Attrappe({}), "", "r", {})["abfrage"], "fehler")
        self.assertEqual(fj.abfrage(Attrappe({}, server=""), "beispiel-org", "r", {})["abfrage"], "fehler")

    def test_token_ungueltig(self):
        erg = self.runde(fehler={"/version": fj.ForgejoFehler("token-ungueltig", "Token ungültig oder abgelaufen (401)")})
        self.assertEqual(erg["abfrage"], "token-ungueltig")
        self.assertIn("401", erg["fehler"])

    def test_keine_rechte(self):
        erg = self.runde(fehler={"/orgs/beispiel-org/repos": fj.ForgejoFehler("keine-rechte", "Keine Berechtigung (403)")})
        self.assertEqual(erg["abfrage"], "keine-rechte")

    def test_organisation_unbekannt(self):
        antworten = lade("forgejo-17.json")
        del antworten["/orgs/beispiel-org"]
        erg = fj.abfrage(Attrappe(antworten), "beispiel-org", "runner-vm-02", {})
        self.assertEqual(erg["abfrage"], "keine-rechte")
        self.assertIn("nicht gefunden", erg["fehler"])

    def test_nicht_erreichbar(self):
        erg = self.runde(fehler={"/version": nicht_erreichbar()})
        self.assertEqual(erg["abfrage"], "nicht-erreichbar")
        self.assertIsNone(erg["letzterErfolg"])

    def test_kein_forgejo(self):
        antworten = lade("forgejo-17.json")
        del antworten["/version"]
        erg = fj.abfrage(Attrappe(antworten), "beispiel-org", "runner-vm-02", {})
        self.assertEqual(erg["abfrage"], "fehler")

    def test_laeufe_nicht_lesbar(self):
        """404 auf /actions/runs trotz has_actions (z. B. Gitea ohne den Pfad): nie „bereit“ behaupten."""
        antworten = lade("forgejo-17.json")
        del antworten["/repos/beispiel-org/api-dienst/actions/runs"]
        antworten["/orgs/beispiel-org/actions/runners"][0]["status"] = "idle"
        antworten["/repos/beispiel-org/web-portal/actions/runs"]["workflow_runs"][0]["status"] = "success"
        erg = fj.abfrage(Attrappe(antworten), "beispiel-org", "runner-vm-02", {})
        self.assertEqual(erg["abfrage"], "ok")
        self.assertEqual([r["name"] for r in erg["repos"]], ["web-portal"])
        self.assertEqual(erg["laeufeNichtLesbar"], 1)
        e = fj.Forgejo(anbieter.RunnerKonfig(id="runner-vm-02", name="runner-vm-02", dienst="forgejo", unit="forgejo-runner.service",
                                 server="https://git.example.org", org="beispiel-org")).eintrag(dienst={"zustand": "aktiv", "seit": 1, "grund": None}, ergebnis=erg, stand="angebunden")
        self.assertEqual(e["status"]["zustand"], "unbekannt")
        ok = lade("forgejo-17.json")
        ok["/orgs/beispiel-org/actions/runners"][0]["status"] = "idle"
        for name in ("web-portal", "api-dienst"):
            for lauf in ok[f"/repos/beispiel-org/{name}/actions/runs"]["workflow_runs"]:
                lauf["status"] = "success"
        erg = fj.abfrage(Attrappe(ok), "beispiel-org", "runner-vm-02", {})
        e = fj.Forgejo(anbieter.RunnerKonfig(id="runner-vm-02", name="runner-vm-02", dienst="forgejo", unit="forgejo-runner.service",
                                 server="https://git.example.org", org="beispiel-org")).eintrag(dienst={"zustand": "aktiv", "seit": 1, "grund": None}, ergebnis=erg, stand="angebunden")
        self.assertEqual(e["status"]["zustand"], "bereit")

    def test_beschaeftigt_ohne_zuordenbaren_job(self):
        """Der Dienst meldet „active“, der Job liegt aber in keinem Repository der Organisation."""
        antworten = lade("forgejo-17.json")
        for name in ("web-portal", "api-dienst"):
            for lauf in antworten[f"/repos/beispiel-org/{name}/actions/runs"]["workflow_runs"]:
                lauf["status"] = "success"
        erg = fj.abfrage(Attrappe(antworten), "beispiel-org", "runner-vm-02", {})
        self.assertTrue(erg["runner"]["beschaeftigt"])
        self.assertIsNone(erg["job"])
        e = fj.Forgejo(anbieter.RunnerKonfig(id="runner-vm-02", name="runner-vm-02", dienst="forgejo", unit="forgejo-runner.service",
                                 server="https://git.example.org", org="beispiel-org")).eintrag(dienst={"zustand": "aktiv", "seit": 1, "grund": None}, ergebnis=erg, stand="angebunden")
        self.assertEqual(e["status"]["zustand"], "job")
        self.assertIs(e["job"]["zuordenbar"], False)
        self.assertIs(fj.Forgejo(anbieter.RunnerKonfig(id="runner-vm-02", name="runner-vm-02", dienst="forgejo", unit="forgejo-runner.service",
                                 server="https://git.example.org", org="beispiel-org")).eintrag(dienst={"zustand": "aktiv", "seit": 1, "grund": None}, ergebnis=self.ok(), stand="angebunden")["job"]["zuordenbar"], True)

    def ok(self):
        return fj.abfrage(Attrappe(lade("forgejo-17.json")), "beispiel-org", "runner-vm-02", {})

    def test_runner_liste_nicht_lesbar_ist_unbekannt(self):
        antworten = lade("forgejo-17.json")
        for name in ("web-portal", "api-dienst"):
            for lauf in antworten[f"/repos/beispiel-org/{name}/actions/runs"]["workflow_runs"]:
                lauf["status"] = "success"
        k = Attrappe(antworten, fehler={"/orgs/beispiel-org/actions/runners": fj.ForgejoFehler("keine-rechte", "403")})
        erg = fj.abfrage(k, "beispiel-org", "runner-vm-02", {})
        e = fj.Forgejo(anbieter.RunnerKonfig(id="runner-vm-02", name="runner-vm-02", dienst="forgejo", unit="forgejo-runner.service",
                                 server="https://git.example.org", org="beispiel-org")).eintrag(dienst={"zustand": "aktiv", "seit": 1, "grund": None}, ergebnis=erg, stand="angebunden")
        self.assertEqual(e["status"]["zustand"], "unbekannt")
        nicht_erreichbar_erg = fj.abfrage(Attrappe({}, fehler={"/version": nicht_erreichbar()}), "beispiel-org", "runner-vm-02", {})
        e = fj.Forgejo(anbieter.RunnerKonfig(id="runner-vm-02", name="runner-vm-02", dienst="forgejo", unit="forgejo-runner.service",
                                 server="https://git.example.org", org="beispiel-org")).eintrag(dienst={"zustand": "aktiv", "seit": 1, "grund": None}, ergebnis=nicht_erreichbar_erg, stand="angebunden")
        self.assertEqual(e["status"]["zustand"], "unbekannt")

    def test_fremde_antworten(self):
        """Falsche Typen werden übergangen; was trotzdem scheitert, wird „unerwartete Antwort“ statt Absturz."""
        antworten = lade("forgejo-17.json")
        antworten["/repos/beispiel-org/web-portal/actions/runs"]["workflow_runs"][0]["status"] = ["running"]
        antworten["/repos/beispiel-org/api-dienst/actions/runs"]["workflow_runs"][0]["status"] = {"x": 1}
        antworten["/orgs/beispiel-org/actions/runners"][0]["labels"] = "kein-array"
        antworten["/orgs/beispiel-org/actions/runners"][0]["busy"] = "ja"
        antworten["/orgs/beispiel-org/repos"][0]["updated_at"] = 10**30
        erg = fj.abfrage(Attrappe(antworten), "beispiel-org", "runner-vm-02", {})
        self.assertEqual(erg["abfrage"], "ok")
        self.assertEqual([(r["laeuft"], r["wartet"]) for r in erg["repos"]], [(0, 0), (0, 1)])
        self.assertEqual(erg["runner"]["labels"], [])
        for ausnahme in (TypeError, ValueError, AttributeError, OverflowError, KeyError, IndexError, RecursionError):
            with mock.patch.object(fj, "zaehle", side_effect=ausnahme("kaputt")):
                erg = fj.abfrage(Attrappe(lade("forgejo-17.json")), "beispiel-org", "runner-vm-02", {})
            self.assertEqual((erg["abfrage"], erg["fehler"]), ("fehler", "unerwartete Antwort des Servers"), ausnahme)
            self.assertEqual((erg["repos"], erg["job"]), ([], None))

    def test_adapter_liest_token_aus_zugang(self):
        with tempfile.TemporaryDirectory() as t:
            verz = Path(t) / "zugang"
            from runner_monitor.anbieter import token as zugangsdaten
            zugangsdaten.schreibe(verz, "runner-vm-02", TOKEN)
            k = anbieter.RunnerKonfig(id="runner-vm-02", name="runner-vm-02", dienst="forgejo", server="https://git.example.org",
                                      org="beispiel-org", token_datei=verz / "runner-vm-02.token")
            a = fj.Forgejo(k)
            self.assertEqual(a.token(), TOKEN)
            with mock.patch.object(fj, "Klient", wraps=fj.Klient) as klient:
                with mock.patch.object(fj, "abfrage", return_value={"abfrage": "ok"}):
                    a.abfrage({})
            self.assertEqual(klient.call_args.args, ("https://git.example.org", TOKEN))


class LogKopfTest(unittest.TestCase):
    def test_forgejo_runner_und_act_runner(self):
        self.assertEqual(fj.wer_aus_log(f"2026-10-29T09:00:01.3521170Z Runner {UUID_02} (version:v13.2.0) received task 83 of job build, triggered by event: push\n"), UUID_02)
        self.assertEqual(fj.wer_aus_log("runner-vm-03(version:v0.2.11) received task 12 of job build, be triggered by event: push"), "runner-vm-03")
        self.assertEqual(fj.wer_aus_log("﻿2026-10-29T09:00:01Z runner-vm-03 (version:v0.2.11) received task 12 of job x"), "runner-vm-03")
        for unsinn in ("", "workflow prepared", "Runner  (version:) received task", "x" * 5000):
            self.assertIsNone(fj.wer_aus_log(unsinn), unsinn[:20])

    def test_art_aus_version(self):
        self.assertEqual(fj.art_aus_version("17.0.1+gitea-1.22.0"), "forgejo")
        self.assertEqual(fj.art_aus_version("7.0.0+gitea-1.22.0"), "forgejo")
        self.assertEqual(fj.art_aus_version("1.24.6"), "gitea")
        self.assertEqual(fj.art_aus_version("1.25.0+dev-12-gabc"), "gitea")
        self.assertIsNone(fj.art_aus_version("<script>"))
        self.assertIsNone(fj.art_aus_version(None))

    def test_pfadteile_kodiert(self):
        self.assertEqual(fj.q("../admin"), "..%2Fadmin")
        self.assertEqual(fj.q("a b?c#d"), "a%20b%3Fc%23d")


# ---------------------------------------------------------------- Klient (nur 127.0.0.1)


class _Handler(http.server.BaseHTTPRequestHandler):
    antworten: dict = {}
    gesehen: list = []

    def do_GET(self):  # noqa: N802
        type(self).gesehen.append((self.path, dict(self.headers)))
        code, kopf, rumpf = type(self).antworten.get(self.path.split("?")[0], (404, {}, b'{"message":"not found"}'))
        self.send_response(code)
        for k, v in kopf.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(rumpf)))
        self.end_headers()
        self.wfile.write(rumpf)

    def log_message(self, *args):  # noqa: D102
        pass


class _Troepfeln(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            self.request.recv(4096)
            for z in b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n" + b" " * 100:
                self.request.sendall(bytes([z]))
                time.sleep(1)
        except OSError:
            pass


def starte_troepfelnd():
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Troepfeln)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, None


def starte(antworten: dict):
    handler = type("H", (_Handler,), {"antworten": antworten, "gesehen": []})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, handler


class KlientTest(unittest.TestCase):
    def setUp(self):
        self.ziel, self.ziel_handler = starte({"/api/v1/version": (200, {}, b'{"version":"1"}')})
        z = f"http://127.0.0.1:{self.ziel.server_port}"
        self.server, self.handler = starte({
            "/api/v1/version": (200, {"Content-Type": "application/json"}, b'{"version":"17.0.1+gitea-1.22.0"}'),
            "/api/v1/weiter": (302, {"Location": f"{z}/api/v1/version"}, b""),
            "/api/v1/kaputt": (200, {}, b"<html>"),
            "/api/v1/gross": (200, {}, b"[" + b"1," * (fj.MAX_ANTWORT // 2) + b"1]"),
            "/api/v1/log": (200, {}, b"x" * (fj.MAX_LOGKOPF * 4)),
            "/api/v1/401": (401, {}, b"{}"), "/api/v1/403": (403, {}, b"{}"), "/api/v1/429": (429, {}, b"{}"),
            "/api/v1/502": (502, {}, b"bad gateway"), "/api/v1/418": (418, {}, b"{}"),
        })
        self.k = fj.Klient(f"http://127.0.0.1:{self.server.server_port}/", TOKEN, http_erlaubt=True)

    def tearDown(self):
        for s in (self.server, self.ziel):
            s.shutdown()
            s.server_close()

    def test_get_mit_token(self):
        self.assertEqual(self.k.hole("/version", {"limit": 50}).daten, {"version": "17.0.1+gitea-1.22.0"})
        pfad, kopf = self.handler.gesehen[-1]
        self.assertEqual(pfad, "/api/v1/version?limit=50")
        self.assertEqual(kopf.get("Authorization"), f"token {TOKEN}")
        self.assertEqual(self.k.zaehler["anfragen"], 1)

    def test_folgt_keiner_weiterleitung(self):
        """Das Token darf nie an eine andere Adresse gehen."""
        with self.assertRaises(fj.ForgejoFehler) as f:
            self.k.hole("/weiter")
        self.assertEqual(f.exception.art, "fehler")
        self.assertIn("Weiterleitung", str(f.exception))
        self.assertEqual(self.ziel_handler.gesehen, [])

    def test_fehlerarten(self):
        for pfad, art in (("/401", "token-ungueltig"), ("/403", "keine-rechte"), ("/fehlt", "fehlt"), ("/429", "kontingent"),
                          ("/502", "nicht-erreichbar"), ("/418", "fehler"), ("/kaputt", "fehler"), ("/gross", "fehler")):
            with self.assertRaises(fj.ForgejoFehler, msg=pfad) as f:
                self.k.hole(pfad)
            self.assertEqual(f.exception.art, art, pfad)
            self.assertNotIn(TOKEN, str(f.exception))

    def test_log_nur_der_anfang(self):
        text = self.k.hole("/log", text=True).daten
        self.assertEqual(len(text), fj.MAX_LOGKOPF)
        self.assertEqual(self.handler.gesehen[-1][1].get("Range"), f"bytes=0-{fj.MAX_LOGKOPF - 1}")

    def test_nicht_erreichbar(self):
        port = self.ziel.server_port
        self.ziel.shutdown()
        self.ziel.server_close()
        self.ziel, _ = starte({})  # läuft, damit tearDown ihn beenden kann
        with self.assertRaises(fj.ForgejoFehler) as f:
            fj.Klient(f"http://127.0.0.1:{port}", TOKEN, zeitlimit=2, http_erlaubt=True).hole("/version")
        self.assertEqual(f.exception.art, "nicht-erreichbar")

    def test_frist_der_runde(self):
        k = fj.Klient(f"http://127.0.0.1:{self.server.server_port}", TOKEN, frist=-1, http_erlaubt=True)
        with self.assertRaises(fj.ForgejoFehler) as f:
            k.hole("/version")
        self.assertEqual(f.exception.art, "nicht-erreichbar")
        self.assertEqual(self.handler.gesehen, [])

    def test_http_nur_mit_erlaubnis(self):
        """E-21: ohne ``http_erlaubt`` geht das Token nie über http:// – es wird gar nicht erst gefragt."""
        for erlaubt in (False, "true", 1):
            k = fj.Klient(f"http://127.0.0.1:{self.server.server_port}", TOKEN, http_erlaubt=erlaubt)
            self.assertEqual(k.server, "")
            with self.assertRaises(fj.ForgejoFehler) as f:
                k.hole("/version")
            self.assertEqual(f.exception.art, "fehler")
            self.assertEqual(fj.abfrage(k, "beispiel-org", "r", {})["abfrage"], "fehler")
        self.assertEqual(self.handler.gesehen, [])
        self.assertEqual(fj.Klient("https://git.example.org/", TOKEN).server, "https://git.example.org")

    def test_http_ohne_proxy_aus_der_umgebung(self):
        with mock.patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "no_proxy": ""}):
            k = fj.Klient(f"http://127.0.0.1:{self.server.server_port}", TOKEN, http_erlaubt=True)
            self.assertEqual(k.hole("/version").daten["version"], "17.0.1+gitea-1.22.0")

    def test_troepfelnder_server_harte_frist(self):
        server, _ = starte_troepfelnd()
        try:
            k = fj.Klient(f"http://127.0.0.1:{server.server_address[1]}", TOKEN, zeitlimit=0.5, http_erlaubt=True)
            beginn = time.monotonic()
            with self.assertRaises(fj.ForgejoFehler) as f:
                k.hole("/version")
            self.assertEqual(f.exception.art, "nicht-erreichbar")
            self.assertLess(time.monotonic() - beginn, 1.5)
        finally:
            server.shutdown()
            server.server_close()

    def test_nan_und_unendlich_abgelehnt(self):
        _, handler = self.server, self.handler
        handler.antworten["/api/v1/nan"] = (200, {}, b'{"version": NaN}')
        with self.assertRaises(fj.ForgejoFehler) as f:
            self.k.hole("/nan")
        self.assertEqual(f.exception.art, "fehler")

    def test_weiterleitungs_handler(self):
        self.assertIsNone(fj._OhneWeiterleitung().redirect_request(urllib.request.Request("http://127.0.0.1/"), None, 302, "", {}, "http://192.0.2.1/"))


# ---------------------------------------------------------------- Konfiguration nur aus runner.json (E-18)


class KonfigurationTest(unittest.TestCase):
    def test_server_und_org_nur_aus_runner_json(self):
        f = fund("runner-vm-02", "forgejo", unit="forgejo-runner.service", server="https://boese.example.net", log="/tmp/aus-dem-fund.log")
        k = anbieter.konfig_aus(f, {}, Path("/etc/runner-monitor/zugang"))
        self.assertEqual((k.server, k.org, k.log), (None, "", None))
        self.assertFalse(anbieter.angebunden(k, "offen"))
        k = anbieter.konfig_aus(f, {"server": "https://git.example.org", "org": "beispiel-org"}, Path("/etc/runner-monitor/zugang"))
        self.assertEqual((k.server, k.org, k.unit), ("https://git.example.org", "beispiel-org", "forgejo-runner.service"))
        self.assertEqual(k.token_datei, Path("/etc/runner-monitor/zugang/runner-vm-02.token"))
        self.assertTrue(anbieter.angebunden(k, "offen"))
        self.assertFalse(anbieter.angebunden(k, "grund"))
        self.assertFalse(anbieter.angebunden(k, "ignoriert"))

    def test_http_nur_mit_http_erlaubt(self):
        f = fund("runner-vm-02", "forgejo", unit="forgejo-runner.service")
        lan = {"server": "http://192.0.2.10:3000", "org": "beispiel-org"}
        self.assertFalse(anbieter.angebunden(anbieter.konfig_aus(f, lan, Path("/z")), "offen"))
        for falsch in ("true", 1, "ja"):
            k = anbieter.konfig_aus(f, {**lan, "http_erlaubt": falsch}, Path("/z"))
            self.assertFalse(k.http_erlaubt, falsch)
        k = anbieter.konfig_aus(f, {**lan, "http_erlaubt": True}, Path("/z"))
        self.assertTrue(k.http_erlaubt)
        self.assertTrue(anbieter.angebunden(k, "offen"))

    def test_gitlab_braucht_keine_organisation(self):
        """Für #115: ``angebunden`` verlangt die Organisation nur, wenn der Adapter sie braucht."""
        k = anbieter.konfig_aus(fund("runner-vm-06", "gitlab", unit="gitlab-runner.service"), {"server": "https://git.example.org"}, Path("/z"))
        self.assertTrue(anbieter.angebunden(k, "offen"))  # seit #115 angebunden, ohne Organisation
        self.assertFalse(anbieter.angebunden(anbieter.konfig_aus(fund("runner-vm-06", "gitlab", unit="gitlab-runner.service"), {}, Path("/z")), "offen"))
        k = anbieter.konfig_aus(fund("runner-vm-02", "forgejo", unit="forgejo-runner.service"), {"server": "https://git.example.org"}, Path("/z"))
        self.assertFalse(anbieter.angebunden(k, "offen"))  # Forgejo ohne org

    def test_ohne_unit_nie_angebunden(self):
        f = fund("nur-datei", "forgejo")
        k = anbieter.konfig_aus(f, {"server": "https://git.example.org", "org": "beispiel-org"}, Path("/z"))
        self.assertFalse(anbieter.angebunden(k, "offen"))

    def test_github_und_unbekannt_nicht_ueber_diesen_weg(self):
        for dienst in ("github", "unbekannt"):  # GitLab seit #115 über diesen Weg
            k = anbieter.konfig_aus(fund("x", dienst, unit="x.service"), {"server": "https://git.example.org", "org": "o"}, Path("/z"))
            self.assertFalse(anbieter.angebunden(k, "offen"), dienst)

    def test_runner_json_prueft_server_und_org(self):
        with tempfile.TemporaryDirectory() as t:
            pfad = Path(t) / "runner.json"
            pfad.write_text(json.dumps({"version": 1, "runner": {
                "gut": {"server": "https://git.example.org/", "org": "beispiel-org"},
                "lan": {"server": "http://192.0.2.10:3000", "org": "beispiel_org"},
                "zugangsdaten": {"server": "https://nutzer:geheim@git.example.org", "org": "../admin"},
                "abfrage": {"server": "https://git.example.org/?x=1", "org": "a/b"},
                "kein-http": {"server": "file:///etc/passwd", "org": ""}}}))
            z = erkennung.lies_zuordnung(pfad)
        self.assertEqual(z["gut"], {"server": "https://git.example.org", "org": "beispiel-org"})
        self.assertEqual(z["lan"], {"server": "http://192.0.2.10:3000", "org": "beispiel_org"})
        for rid in ("zugangsdaten", "abfrage", "kein-http"):
            self.assertEqual(z[rid], {}, rid)


# ---------------------------------------------------------------- Sammler und runner[]


class SammlerZustandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.k = lade_konfig(self.d)
        (self.d / "lauf").mkdir()
        self.k.token_datei.parent.mkdir(parents=True)
        registriere_runner(self.d)
        funde = [fund("runner-vm-02", "forgejo", unit="forgejo-runner.service", server="https://boese.example.net"),
                 fund("runner-vm-03", "gitea", unit="act_runner.service"),
                 fund("runner-vm-05", "forgejo", unit="forgejo-runner-2.service", stand="grund")]
        (self.d / "lauf" / "erkennung.json").write_text(json.dumps({"zeit": 1.0, "runner": funde}))
        self.k.zuordnung_datei.write_text(json.dumps({"version": 1, "runner": {
            "runner-vm-02": {"server": "https://git.example.org", "org": "beispiel-org"},
            "runner-vm-05": {"server": "https://git.example.org", "org": "beispiel-org"}}}))
        from runner_monitor.anbieter import token as zugangsdaten
        zugangsdaten.schreibe(self.k.zugang_verz, "runner-vm-02", TOKEN)
        self.s = sammler.Sammler(self.k)
        self.antworten = lade("forgejo-17.json")
        self.klienten: list = []

    def tearDown(self):
        self.tmp.cleanup()

    def klient(self, server, token, **_):
        k = Attrappe(self.antworten, token=token, server=server)
        self.klienten.append(k)
        return k

    def abfragen(self):
        with mock.patch.object(fj, "Klient", side_effect=self.klient):
            self.s.anbieter_abfragen()
        pfad = self.k.lauf_verz / "anbieter.json"
        return pfad, json.loads(pfad.read_text())

    def test_nur_angebundene_runner_mit_ziel_aus_runner_json(self):
        pfad, daten = self.abfragen()
        self.assertEqual(list(daten["runner"]), ["runner-vm-02"])  # vm-03 ohne runner.json, vm-05 „grund“
        self.assertEqual([k.server for k in self.klienten], ["https://git.example.org"])  # nie der Server aus dem Fund
        self.assertEqual(daten["runner"]["runner-vm-02"]["abfrage"], "ok")
        self.assertEqual(stat.S_IMODE(os.stat(pfad).st_mode), 0o644)
        self.assertNotIn(TOKEN, pfad.read_text())

    def test_letzter_guter_stand_bleibt(self):
        self.abfragen()
        self.antworten = {}  # alles 404 → /version fehlt
        with mock.patch.object(fj, "Klient", side_effect=lambda server, token, **_: Attrappe({}, token=token, server=server,
                                                                                     fehler={"/version": nicht_erreichbar()})):
            self.s.anbieter_abfragen()
        erg = json.loads((self.k.lauf_verz / "anbieter.json").read_text())["runner"]["runner-vm-02"]
        self.assertEqual(erg["abfrage"], "nicht-erreichbar")
        self.assertEqual(erg["job"]["name"], "build")
        self.assertEqual(len(erg["repos"]), 2)

    def test_takt_im_sammler(self):
        with mock.patch.object(self.s, "_anbieter_planen") as aufruf, mock.patch.object(self.s, "github"), \
             mock.patch.object(self.s, "release", return_value={}), mock.patch.object(self.s, "erkennung"), \
             mock.patch.object(sammler, "docker_container", return_value={}), mock.patch.object(self.s, "auto_update"):
            for zeitpunkt in (1000.0, 1010.0, 1031.0):
                self.s.ein_takt(zeitpunkt)
        self.assertEqual(aufruf.call_count, 2)  # fällig alle 30 s

    def test_haengender_server_haelt_ein_takt_nicht_auf(self):
        """Tröpfelnder Server (ein Byte je Sekunde): ein_takt bleibt unter 1 s, die Abfrage läuft im Faden."""
        server, _ = starte_troepfelnd()
        try:
            self.k.zuordnung_datei.write_text(json.dumps({"version": 1, "runner": {"runner-vm-02": {
                "server": f"http://127.0.0.1:{server.server_address[1]}", "org": "beispiel-org", "http_erlaubt": True}}}))
            with mock.patch.object(self.s, "github"), mock.patch.object(self.s, "release", return_value={}), \
                 mock.patch.object(self.s, "erkennung"), mock.patch.object(sammler, "docker_container", return_value={}), \
                 mock.patch.object(self.s, "auto_update"), mock.patch.object(fj, "ZEITLIMIT", 1.0):
                beginn = time.monotonic()
                self.s.ein_takt(1000.0)
                self.assertLess(time.monotonic() - beginn, 1.0)
                faden = self.s._anbieter_laeufe["runner-vm-02"][0]  # je Runner ein eigener Faden (#115)
                self.assertTrue(faden.is_alive())
                faden.join(10)
            erg = json.loads((self.k.lauf_verz / "anbieter.json").read_text())["runner"]["runner-vm-02"]
            self.assertEqual(erg["abfrage"], "nicht-erreichbar")
        finally:
            server.shutdown()
            server.server_close()

    def test_fehler_im_adapter_haelt_den_sammler_nicht_auf(self):
        with mock.patch.object(fj.Forgejo, "abfrage", side_effect=RuntimeError("kaputt")), self.assertLogs("runner_monitor.sammler", "ERROR"):
            self.s.anbieter_abfragen()

    def test_runner_liste_im_monitor(self):
        self.abfragen()
        z = zustand.Zustand(self.k)
        unit = "actions.runner.beispiel-org.runner-vm-01.service"
        dienste = {unit: "aktiv", "forgejo-runner.service": "aktiv", "act_runner.service": "aktiv", "forgejo-runner-2.service": "aktiv"}
        with mock.patch.object(runner, "finde_unit", return_value=unit), \
             mock.patch.object(runner, "dienst_status", side_effect=lambda u: {"zustand": dienste.get(u, "fehlt"), "seit": 10.0, "grund": None}), \
             mock.patch.object(runner, "runner_version", return_value="2.338.1"):
            z.ein_takt(0)
        liste = {r["id"]: r for r in z.bereiche["runner"]}
        fj02 = liste["runner-vm-02"]
        self.assertEqual(set(fj02), EINTRAG_SCHLUESSEL)
        self.assertEqual((fj02["server"], fj02["org"], fj02["stand"], fj02["einstufung"]),
                         ("https://git.example.org", "beispiel-org", "angebunden", "voll"))
        self.assertEqual(fj02["faehig"], fj.Forgejo.FAEHIG)  # von Hand angebunden: was der Adapter liefert
        self.assertEqual(fj02["status"]["zustand"], "job")
        self.assertEqual(fj02["status"]["beimDienst"], {"zustand": "online", "seit": None})
        self.assertEqual(fj02["job"]["schritt"], {"nr": 3, "von": 5, "name": "Tests"})
        self.assertEqual(fj02["labels"], ["linux-amd64", "ubuntu-latest"])
        self.assertEqual(fj02["jobsJeRepository"]["abfrage"], "ok")
        self.assertEqual(fj02["log"], {"art": "journal", "unit": "forgejo-runner.service"})
        # ohne runner.json bzw. „grund“: Grundüberwachung, obwohl ein Adapter da wäre
        for rid in ("runner-vm-03", "runner-vm-05"):
            self.assertFalse(liste[rid]["faehig"]["jobs"], rid)
            self.assertEqual(liste[rid]["status"]["zustand"], "aktiv", rid)
            self.assertIsNone(liste[rid]["jobsJeRepository"], rid)
        self.assertIsNone(liste["runner-vm-03"]["server"])  # nie der Server aus dem Fund
        self.assertEqual(liste["runner-vm-05"]["server"], "https://git.example.org")  # aus runner.json, nur angezeigt
        self.assertFalse([m for m in z.bereiche["meldungen"] if m["runner"] == "runner-vm-02"])

    def test_meldung_bei_ungueltigem_token(self):
        (self.k.lauf_verz / "anbieter.json").write_text(json.dumps({"zeit": 1, "runner": {"runner-vm-02": {
            "org": "beispiel-org", "abfrage": "token-ungueltig", "abgefragt": 100.0, "repos": [], "runner": {}, "fehler": "401"}}}))
        z = zustand.Zustand(self.k)
        with mock.patch.object(runner, "finde_unit", return_value=""), \
             mock.patch.object(runner, "dienst_status", return_value={"zustand": "aktiv", "seit": 1.0, "grund": None}), \
             mock.patch.object(runner, "runner_version", return_value=""):
            z.ein_takt(0)
        r = next(r for r in z.bereiche["runner"] if r["id"] == "runner-vm-02")
        self.assertEqual(r["stand"], "offen")
        self.assertEqual(r["status"]["beimDienst"]["zustand"], "unbekannt")
        self.assertIn({"id": "token", "stufe": "fehler", "runner": "runner-vm-02", "dienst": "forgejo",
                       "daten": {"abfrage": "token-ungueltig"}}, z.bereiche["meldungen"])


if __name__ == "__main__":
    unittest.main()
