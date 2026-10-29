"""GitLab-Adapter (#99): Abfrage gegen einen lokalen Testserver mit aufgezeichneten (neutralisierten)
Antworten der GitLab-REST-API v4. Namen: gitlab.example.org, beispiel-org, runner-vm-03, 192.0.2.x."""

import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from runner_monitor import anbieter, erkennung
from runner_monitor.anbieter import gitlab
from runner_monitor.anbieter import token as zugangsdaten

TOKEN = "glpat-attrappe-0000000000"

# ---- aufgezeichnete Antworten (GET /api/v4/…), Namen neutralisiert
TOKEN_SELF = {"id": 7, "name": "runner-monitor", "revoked": False, "created_at": "2026-10-01T09:00:00.000Z",
              "scopes": ["read_api"], "user_id": 12, "active": True, "expires_at": "2026-11-30"}
RUNNER_LISTE = [
    {"id": 41, "description": "runner-vm-04", "ip_address": "192.0.2.14", "active": True, "paused": False, "is_shared": False,
     "runner_type": "group_type", "name": "gitlab-runner", "online": True, "created_by": None, "status": "online"},
    {"id": 42, "description": "runner-vm-03", "ip_address": "192.0.2.13", "active": True, "paused": False, "is_shared": False,
     "runner_type": "group_type", "name": "gitlab-runner", "online": True, "created_by": None, "status": "online"},
]
RUNNER_42 = {**RUNNER_LISTE[1], "architecture": "amd64", "platform": "linux", "version": "17.5.1", "revision": "abc12345",
             "contacted_at": "2026-10-29T08:00:00.000Z", "tag_list": ["self-hosted", "linux"], "locked": False}
JOBS_LAUFEND = [
    {"id": 4711, "status": "running", "stage": "test", "name": "unit-tests", "ref": "refs/merge-requests/12/head", "tag": False,
     "created_at": "2026-10-29T07:58:00.000Z", "started_at": "2026-10-29T07:59:00.000Z", "finished_at": None, "duration": None,
     "web_url": "https://gitlab.example.org/beispiel-org/web-portal/-/jobs/4711",
     "pipeline": {"id": 900, "project_id": 5, "ref": "refs/merge-requests/12/head", "sha": "0" * 40, "status": "running"},
     "commit": {"id": "0" * 40, "title": "Anmeldung überarbeiten"},
     "project": {"id": 5, "name": "web-portal", "name_with_namespace": "beispiel-org / web-portal"}},
]
JOBS_LETZTE = [
    {**JOBS_LAUFEND[0]},
    {"id": 4700, "status": "success", "stage": "build", "name": "build", "ref": "v1.2.0", "tag": True,
     "started_at": "2026-10-29T07:00:00.000Z", "finished_at": "2026-10-29T07:04:34.000Z", "duration": 274.2,
     "web_url": "https://gitlab.example.org/beispiel-org/api-dienst/-/jobs/4700",
     "pipeline": {"id": 897, "project_id": 6, "status": "success"}, "project": {"id": 6, "name": "api-dienst"}},
    {"id": 4690, "status": "failed", "stage": "test", "name": "lint", "ref": "main", "tag": False,
     "started_at": "2026-10-29T06:00:00.000Z", "finished_at": "2026-10-29T06:01:00.000Z", "duration": 60.0,
     "web_url": "https://gitlab.example.org/beispiel-org/api-dienst/-/jobs/4690",
     "pipeline": {"id": 890, "project_id": 6, "status": "failed"}, "project": {"id": 6, "name": "api-dienst"}},
    {"id": 4680, "status": "canceled", "stage": "test", "name": "e2e", "ref": "main", "tag": False,
     "started_at": "2026-10-29T05:00:00.000Z", "finished_at": "2026-10-29T05:00:30.000Z", "duration": 30.0,
     "pipeline": {"id": 880, "project_id": 7}},
]
FEHLER_401 = (401, {"message": "401 Unauthorized"})
FEHLER_403_BEREICH = (403, {"error": "insufficient_scope", "error_description": "Request was forbidden", "scope": "read_api"})
FEHLER_403 = (403, {"message": "403 Forbidden"})
FEHLER_404 = (404, {"message": "404 Not Found"})

LAUFEND = "/api/v4/runners/42/jobs?status=running&per_page=100"
LETZTE = "/api/v4/runners/42/jobs?order_by=id&sort=desc&per_page=20"


class Testserver:
    """Antwortet wie GitLab: ``antworten[pfad]`` → (Code, JSON oder Bytes[, Kopfzeilen])."""

    def __init__(self) -> None:
        self.antworten: dict[str, tuple] = {}
        self.anfragen: list[tuple[str, dict]] = []
        aussen = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                aussen.anfragen.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
                a = aussen.antworten.get(self.path) or aussen.antworten.get(self.path.split("?")[0]) or FEHLER_404
                roh = a[1] if isinstance(a[1], bytes) else json.dumps(a[1]).encode()
                self.send_response(a[0])
                for k, v in (a[2] if len(a) > 2 else {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(roh)))
                self.end_headers()
                self.wfile.write(roh)

            def log_message(self, *a):  # noqa: ANN002
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def schliessen(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def normal(self) -> None:
        self.antworten = {
            "/api/v4/personal_access_tokens/self": (200, TOKEN_SELF),
            "/api/v4/runners": (200, RUNNER_LISTE),
            "/api/v4/runners/42": (200, RUNNER_42),
            LAUFEND: (200, JOBS_LAUFEND),
            LETZTE: (200, JOBS_LETZTE),
        }


class Basis(unittest.TestCase):
    def setUp(self):
        self.s = Testserver()
        self.addCleanup(self.s.schliessen)
        self.s.normal()

    def frage(self, token: str = TOKEN, speicher: dict | None = None, name: str = "runner-vm-03", server: str | None = None) -> dict:
        return gitlab.abfrage(gitlab.Klient(server if server is not None else self.s.url, token), name, None, speicher)


class AbfrageTest(Basis):
    def test_runde_ok(self):
        e = self.frage()
        self.assertEqual(e["abfrage"], "ok")
        self.assertEqual(e["runner"], {"zustand": "online", "beschaeftigt": True, "labels": ["self-hosted", "linux"], "version": "17.5.1", "id": 42})
        self.assertEqual(e["repos"], [{"name": "web-portal", "privat": False, "laeuft": 1, "wartet": 0}])
        job = e["job"]
        self.assertEqual((job["repo"], job["workflow"], job["name"], job["stage"]), ("web-portal", "Pipeline #900", "unit-tests", "test"))
        self.assertEqual(job["ref"], {"art": "PR", "name": "!12", "titel": "Anmeldung überarbeiten"})
        self.assertEqual((job["schritte"], job["schritt"]), ([], None))  # keine Schritte per API
        self.assertEqual(job["url"], "https://gitlab.example.org/beispiel-org/web-portal/-/jobs/4711")
        self.assertEqual(job["start"], 1793260740.0)
        self.assertEqual([(j["name"], j["ergebnis"], j["dauer"], j["repo"]) for j in e["letzteJobs"]],
                         [("build", "erfolg", 274, "api-dienst"), ("lint", "fehler", 60, "api-dienst"), ("e2e", "abgebrochen", 30, "Projekt 7")])
        self.assertIsNotNone(e["letzterErfolg"])
        self.assertAlmostEqual(e["tokenAblauf"], time.mktime(time.strptime("2026-11-30", "%Y-%m-%d")) + 86399, delta=1)

    def test_token_nur_im_kopf_nie_in_der_adresse_oder_im_ergebnis(self):
        e = self.frage()
        for pfad, kopf in self.s.anfragen:
            self.assertEqual(kopf.get("private-token"), TOKEN)
            self.assertNotIn(TOKEN, pfad)
        self.assertNotIn(TOKEN, json.dumps(e))

    def test_nur_bekannte_lesende_pfade(self):
        self.frage()
        pfade = {p.split("?")[0] for p, _ in self.s.anfragen}
        self.assertEqual(pfade, {"/api/v4/personal_access_tokens/self", "/api/v4/runners", "/api/v4/runners/42", "/api/v4/runners/42/jobs"})

    def test_zweite_runde_spart_anfragen(self):
        speicher: dict = {}
        self.frage(speicher=speicher)
        self.s.anfragen.clear()
        self.frage(speicher=speicher)
        pfade = [p.split("?")[0] for p, _ in self.s.anfragen]
        self.assertNotIn("/api/v4/runners", pfade)                       # Nummer gemerkt
        self.assertNotIn("/api/v4/personal_access_tokens/self", pfade)    # höchstens stündlich

    def test_gemerkter_runner_geloescht_sucht_neu(self):
        speicher = {"runner_id": 99}  # 99 gibt es nicht (404)
        e = self.frage(speicher=speicher)
        self.assertEqual(e["abfrage"], "ok")
        self.assertEqual(speicher["runner_id"], 42)

    def test_leerlauf(self):
        self.s.antworten[LAUFEND] = (200, [])
        e = self.frage()
        self.assertIsNone(e["job"])
        self.assertEqual((e["repos"], e["runner"]["beschaeftigt"]), ([], False))

    def test_offline_beim_dienst(self):
        for status in ("offline", "stale", "never_contacted"):
            self.s.antworten["/api/v4/runners/42"] = (200, {**RUNNER_42, "status": status, "online": False})
            self.assertEqual(self.frage()["runner"]["zustand"], "offline", status)

    def test_alte_version_nur_online_feld(self):
        alt = {k: v for k, v in RUNNER_42.items() if k != "status"}
        self.s.antworten["/api/v4/runners"] = (200, [{k: v for k, v in r.items() if k != "status"} for r in RUNNER_LISTE])
        self.s.antworten["/api/v4/runners/42"] = (200, {**alt, "online": False})
        self.assertEqual(self.frage()["runner"]["zustand"], "offline")

    def test_runner_nicht_gefunden_ehrlich_unbekannt(self):
        e = self.frage(name="runner-vm-99")
        self.assertEqual(e["abfrage"], "ok")
        self.assertEqual(e["runner"]["zustand"], "unbekannt")
        self.assertIn("nicht gefunden", e["runner"]["grund"])
        self.assertIsNone(e["job"])

    def test_name_nicht_eindeutig(self):
        self.s.antworten["/api/v4/runners"] = (200, RUNNER_LISTE + [{**RUNNER_LISTE[1], "id": 43}])
        e = self.frage()
        self.assertEqual(e["runner"]["zustand"], "unbekannt")
        self.assertIn("nicht eindeutig", e["runner"]["grund"])

    def test_einzelheiten_ohne_recht_sind_freiwillig(self):
        self.s.antworten["/api/v4/runners/42"] = FEHLER_403
        e = self.frage()
        self.assertEqual(e["abfrage"], "ok")
        self.assertEqual((e["runner"]["zustand"], e["runner"]["labels"]), ("online", []))

    def test_token_route_fehlt_bei_aelterem_gitlab(self):
        self.s.antworten["/api/v4/personal_access_tokens/self"] = FEHLER_404
        e = self.frage()
        self.assertEqual((e["abfrage"], e["tokenAblauf"]), ("ok", None))

    def test_seitenweise_runnerliste(self):
        seite1 = [{"id": 1000 + i, "description": f"x-{i}", "status": "online"} for i in range(100)]
        self.s.antworten["/api/v4/runners?per_page=100&page=1"] = (200, seite1)
        self.s.antworten["/api/v4/runners?per_page=100&page=2"] = (200, RUNNER_LISTE)
        self.assertEqual(self.frage()["runner"]["id"], 42)

    def test_kontingent_aus_den_kopfzeilen(self):
        self.s.antworten["/api/v4/runners"] = (200, RUNNER_LISTE, {"RateLimit-Remaining": "1990", "RateLimit-Limit": "2000", "RateLimit-Reset": "1761700060"})
        klient = gitlab.Klient(self.s.url, TOKEN)
        klient.hole("/runners")
        self.assertEqual(klient.kontingent(), {"frei": 1990, "limit": 2000, "reset": 1761700060})
        self.assertEqual(gitlab.Klient(self.s.url, TOKEN).kontingent(), {})  # Server ohne RateLimit-Kopfzeilen


class FehlerTest(Basis):
    def test_kein_token(self):
        e = self.frage(token="")
        self.assertEqual(e["abfrage"], "kein-token")
        self.assertEqual(self.s.anfragen, [])  # ohne Token keine Anfrage

    def test_token_ungueltig(self):
        self.s.antworten = {"/api/v4/personal_access_tokens/self": FEHLER_401, "/api/v4/runners": FEHLER_401}
        e = self.frage()
        self.assertEqual(e["abfrage"], "token-ungueltig")
        self.assertIn("401", e["fehler"])
        self.assertIsNone(e["job"])
        self.assertNotIn(TOKEN, json.dumps(e))

    def test_token_ohne_bereich_read_api(self):
        self.s.antworten["/api/v4/personal_access_tokens/self"] = (200, {**TOKEN_SELF, "scopes": ["read_repository"]})
        e = self.frage()
        self.assertEqual(e["abfrage"], "keine-rechte")
        self.assertIn("read_api", e["fehler"])

    def test_bereich_api_genuegt(self):
        self.s.antworten["/api/v4/personal_access_tokens/self"] = (200, {**TOKEN_SELF, "scopes": ["api"]})
        self.assertEqual(self.frage()["abfrage"], "ok")

    def test_keine_rechte_403_und_404(self):
        for antwort in (FEHLER_403_BEREICH, FEHLER_403, FEHLER_404):
            self.s.antworten["/api/v4/runners"] = antwort
            e = self.frage()
            self.assertEqual(e["abfrage"], "keine-rechte", antwort)
            self.assertIsNone(e["job"])

    def test_kontingent_erschoepft(self):
        self.s.antworten["/api/v4/runners"] = (429, {"message": "Retry later"}, {"Retry-After": "30"})
        self.assertEqual(self.frage()["abfrage"], "kontingent")

    def test_serverfehler(self):
        self.s.antworten["/api/v4/runners"] = (502, b"<html>Bad Gateway</html>")
        e = self.frage()
        self.assertEqual(e["abfrage"], "nicht-erreichbar")  # wie GitHub: 5xx zählt als „nicht erreichbar“
        self.assertIn("502", e["fehler"])

    def test_nicht_erreichbar(self):
        tot = Testserver()
        url = tot.url
        tot.schliessen()
        e = gitlab.abfrage(gitlab.Klient(url, TOKEN, zeitlimit=2), "runner-vm-03")
        self.assertEqual(e["abfrage"], "nicht-erreichbar")
        self.assertTrue(e["fehler"])
        self.assertNotIn(TOKEN, e["fehler"])

    def test_html_statt_json(self):
        self.s.antworten["/api/v4/runners"] = (200, b"<html><title>Sign in</title></html>")
        e = self.frage()
        self.assertEqual(e["abfrage"], "nicht-erreichbar")
        self.assertIn("JSON", e["fehler"])

    def test_zu_grosse_antwort(self):
        self.s.antworten["/api/v4/runners"] = (200, b"[" + b"0," * (gitlab.MAX_ANTWORT // 2) + b"0]")
        self.assertEqual(self.frage()["abfrage"], "nicht-erreichbar")

    def test_weiterleitung_wird_nicht_gefolgt(self):
        fremd = Testserver()
        self.addCleanup(fremd.schliessen)
        fremd.antworten = {"/api/v4/runners": (200, RUNNER_LISTE)}
        self.s.antworten["/api/v4/runners"] = (302, b"", {"Location": f"{fremd.url}/api/v4/runners"})
        e = self.frage()
        self.assertEqual(e["abfrage"], "nicht-erreichbar")
        self.assertIn("leitet weiter", e["fehler"])
        self.assertEqual(fremd.anfragen, [], "das Token darf nie an die Weiterleitungsadresse gehen")

    def test_ungueltiger_server(self):
        for server in ("", "ftp://gitlab.example.org", "gitlab.example.org", "https://", "https://gitlab.example.org/a b"):
            e = self.frage(server=server)
            self.assertEqual(e["abfrage"], "fehler", server)
        self.assertEqual(self.s.anfragen, [])

    def test_pfad_des_servers_bleibt(self):
        self.assertEqual(gitlab.Klient("https://gitlab.example.org/gitlab/", TOKEN).server, "https://gitlab.example.org/gitlab")
        # Zugangsdaten und Abfrage in der Adresse werden verworfen, nie weitergereicht
        self.assertEqual(gitlab.Klient("https://user:pw@gitlab.example.org/?x=1#a", TOKEN).server, "https://gitlab.example.org")


class AuswertungTest(unittest.TestCase):
    def test_ref_arten(self):
        self.assertEqual(gitlab.ref_aus_job({"ref": "main"})["art"], "Branch")
        self.assertEqual(gitlab.ref_aus_job({"ref": "v1.2.0", "tag": True})["art"], "Tag")
        self.assertEqual(gitlab.ref_aus_job({"ref": "refs/merge-requests/7/merge"}), {"art": "PR", "name": "!7", "titel": ""})

    def test_zaehle_laufende(self):
        jobs = [{"project": {"name": "b"}}, {"project": {"name": "a"}}, {"project": {"name": "b"}}, {}]
        self.assertEqual(gitlab.zaehle_laufende(jobs), [{"name": "a", "privat": False, "laeuft": 1, "wartet": 0},
                                                         {"name": "b", "privat": False, "laeuft": 2, "wartet": 0}])

    def test_workflows_aus(self):
        w = gitlab.workflows_aus({"abfrage": "ok", "abgefragt": 100.0, "letzterErfolg": 100.0, "repos": []})
        self.assertTrue(w["wartetUnbekannt"])  # wartende Jobs gibt die Runner-API nicht her
        self.assertEqual(w["naechste"], 100.0 + gitlab.TAKT)
        self.assertEqual(gitlab.workflows_aus(None)["abfrage"], "kein-token")


class AdapterTest(Basis):
    def konfig(self, d: Path) -> anbieter.RunnerKonfig:
        return gitlab.konfig_fuer("runner-vm-03", "runner-vm-03", "gitlab-runner.service", self.s.url, d / "zugang")

    def test_faehigkeiten_ehrlich(self):
        f = anbieter.faehigkeiten_tabelle()["gitlab"]
        self.assertEqual(f, {"status": True, "jobs": True, "schritte": False, "logs": True, "updates": False})
        self.assertEqual(f, erkennung.FAEHIG["gitlab"])
        self.assertIs(anbieter.klasse_fuer("gitlab"), gitlab.GitLab)

    def test_eintrag_ohne_schritte_mit_jobs(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            zugangsdaten.schreibe(d / "zugang", "runner-vm-03", TOKEN)
            a = anbieter.adapter(self.konfig(d))
            self.assertIsInstance(a, gitlab.GitLab)
            erg = a.abfrage({}, None)
            self.assertEqual(erg["abfrage"], "ok")
            e = a.eintrag(dienst={"zustand": "aktiv", "seit": 1, "grund": None}, job=a.api_job(erg), letzte_jobs=a.letzte_jobs(erg), ergebnis=erg)
        self.assertEqual((e["dienst"], e["server"]), ("gitlab", self.s.url))
        self.assertEqual(e["status"]["zustand"], "job")
        self.assertEqual(e["status"]["beimDienst"], {"zustand": "online", "seit": None})
        self.assertIsNone(e["job"]["schritt"])           # „Schritte nicht verfügbar“
        self.assertEqual(e["job"]["schritte"], [])
        self.assertEqual(len(e["letzteJobs"]), 3)
        self.assertEqual(e["jobsJeRepository"]["repos"][0]["name"], "web-portal")
        self.assertEqual(e["log"], {"art": "journal", "unit": "gitlab-runner.service"})
        self.assertNotIn(TOKEN, json.dumps(e))

    def test_bereit_offline_unbekannt(self):
        a = anbieter.adapter(anbieter.RunnerKonfig(id="runner-vm-03", name="runner-vm-03", dienst="gitlab", unit="gitlab-runner.service"))
        aktiv = {"zustand": "aktiv", "seit": 1, "grund": None}
        self.assertEqual(a.eintrag(dienst=aktiv, ergebnis={"abfrage": "ok", "runner": {"zustand": "online"}})["status"]["zustand"], "bereit")
        self.assertEqual(a.eintrag(dienst=aktiv, ergebnis={"abfrage": "ok", "runner": {"zustand": "offline"}})["status"]["zustand"], "offline")
        self.assertEqual(a.eintrag(dienst=aktiv, ergebnis={"abfrage": "token-ungueltig"})["status"]["beimDienst"]["zustand"], "unbekannt")

    def test_token_nur_aus_zugang(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            (d / "github-token").write_text("github-token-darf-nicht-zu-gitlab\n")
            a = gitlab.GitLab(self.konfig(d))
            self.assertEqual(a.token(), "")
            self.assertEqual(a.abfrage({})["abfrage"], "kein-token")
            self.assertEqual(self.s.anfragen, [])

    def test_server_nur_aus_der_konfiguration(self):
        k = gitlab.konfig_fuer("x", "x", None, "ftp://gitlab.example.org", Path("/nicht/da"))
        self.assertIsNone(k.server)
        self.assertEqual(gitlab.GitLab(k).abfrage({}, None, token=TOKEN)["abfrage"], "fehler")
        # ohne Eintrag in der Konfiguration gibt es keinen Server – ein Fund der Erkennung ersetzt ihn nie
        self.assertIsNone(gitlab.konfig_fuer("x", "x", None, None, Path("/nicht/da")).server)

    def test_ungueltige_unit_wird_verworfen(self):
        self.assertIsNone(gitlab.konfig_fuer("x", "x", "--help.service", self.s.url, Path("/x")).unit)


if __name__ == "__main__":
    unittest.main()
