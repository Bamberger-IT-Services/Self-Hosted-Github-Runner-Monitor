"""Update-Quelle Forgejo (#138, ADR-0007): Konfiguration, Release-Abfrage, Download nur von genau dieser
Quelle und ohne Weiterleitungen, Paket-Version, konfig.env schreiben. Lokale Fake-Server auf 127.0.0.1."""

import hashlib
import http.server
import io
import json
import os
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from runner_monitor import aktualisierer as a
from runner_monitor import konfig, quelle

REPO = "beispiel-org/runner-monitor"


def paket(version: str, version_drin: str | None = None) -> bytes:
    puffer = io.BytesIO()
    with tarfile.open(fileobj=puffer, mode="w:gz") as tar:
        for name, inhalt in ((f"runner-monitor-{version}/VERSION", f"{version_drin or version}\n".encode()),
                             (f"runner-monitor-{version}/runner_monitor/__init__.py", b"")):
            info = tarfile.TarInfo(name)
            info.size = len(inhalt)
            tar.addfile(info, io.BytesIO(inhalt))
    return puffer.getvalue()


class FakeForgejo:
    """Antwortet wie Forgejo 17 auf releases/latest, releases und die Downloads. ``antworten`` (Pfad →
    (Code, Kopf, Inhalt)) überschreibt einzelne Pfade; ``aufrufe`` hält alle angefragten Pfade."""

    def __init__(self, version="1.2.3", inhalt: bytes | None = None, praefix=""):
        self.aufrufe: list[str] = []
        self.antworten: dict[str, tuple[int, dict, bytes]] = {}
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                fake.aufrufe.append(self.path)
                code, kopf, daten = fake.antwort(self.path)
                self.send_response(code)
                for k, v in kopf.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(daten)))
                self.end_headers()
                self.wfile.write(daten)

            def log_message(self, *argumente):  # noqa: ANN002
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.basis = f"http://127.0.0.1:{self.server.server_address[1]}{praefix}"
        self.praefix = praefix
        self.version = version
        self.inhalt = inhalt if inhalt is not None else paket(version)

    def release(self, version, assets=True, tag=None):
        tag = tag or f"v{version}"
        boese = "https://boese.example.net/x"  # browser_download_url wird nie aufgerufen
        return {"tag_name": tag, "draft": False, "prerelease": False, "html_url": boese, "published_at": "2026-10-29T21:49:22+01:00",
                "body": "## Was ist neu\n- Forgejo als Quelle\n", "assets": [
                    {"name": f"runner-monitor-{version}.tar.gz", "browser_download_url": boese},
                    {"name": f"runner-monitor-{version}.tar.gz.sha256", "browser_download_url": boese}] if assets else []}

    def antwort(self, pfad):
        if pfad in self.antworten:
            return self.antworten[pfad]
        p, v = self.praefix, self.version
        json_kopf = {"Content-Type": "application/json"}
        if pfad == f"{p}/api/v1/repos/{REPO}/releases/latest":
            return 200, json_kopf, json.dumps(self.release(v)).encode()
        if pfad == f"{p}/api/v1/repos/{REPO}/releases?limit=30":
            return 200, json_kopf, json.dumps([self.release(v), self.release("1.2.2"), self.release("0.9.0")]).encode()
        if pfad == f"{p}/{REPO}/releases/download/v{v}/runner-monitor-{v}.tar.gz":
            return 200, {}, self.inhalt
        if pfad == f"{p}/{REPO}/releases/download/v{v}/runner-monitor-{v}.tar.gz.sha256":
            return 200, {}, f"{hashlib.sha256(self.inhalt).hexdigest()}  runner-monitor-{v}.tar.gz\n".encode()
        return 404, {}, b"{}"

    def schliessen(self):
        self.server.shutdown()
        self.server.server_close()


def k_forgejo(basis, **mehr):
    werte = {"MONITOR_UPDATE_QUELLE": "forgejo", "MONITOR_UPDATE_FORGEJO": basis, "MONITOR_UPDATE_HTTP_ERLAUBT": "1",
             "MONITOR_RELEASE_REPO": REPO, **mehr}
    return konfig.lade(datei=Path("/nicht/da.env"), umgebung=werte)


class KonfigTest(unittest.TestCase):
    def lade(self, **werte):
        return konfig.lade(datei=Path("/nicht/da.env"), umgebung=werte)

    def test_vorgabe_github_unveraendert(self):
        k = self.lade()
        self.assertEqual((k.update_quelle, k.update_forgejo, k.update_http_erlaubt), ("github", "", False))
        self.assertEqual(quelle.download_praefix(k), "https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/releases/download/")
        self.assertIsNone(quelle.oeffner(k))  # GitHub folgt wie bisher der Weiterleitung zum Speicher

    def test_github_ignoriert_forgejo_werte(self):
        k = self.lade(MONITOR_UPDATE_FORGEJO="http://192.0.2.10:3000")
        self.assertEqual((k.update_quelle, k.update_forgejo), ("github", ""))

    def test_forgejo_https(self):
        k = self.lade(MONITOR_UPDATE_QUELLE="Forgejo", MONITOR_UPDATE_FORGEJO="https://Git.Example.org/")
        self.assertEqual((k.update_quelle, k.update_forgejo, k.update_http_erlaubt), ("forgejo", "https://git.example.org", False))
        self.assertEqual(quelle.download_urls(k, "1.2.3"), (
            "https://git.example.org/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/releases/download/v1.2.3/runner-monitor-1.2.3.tar.gz",
            "https://git.example.org/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/releases/download/v1.2.3/runner-monitor-1.2.3.tar.gz.sha256"))
        self.assertEqual(quelle.download_urls(k, "1.2.3/../x"), ("", ""))

    def test_fehler_halten_den_start_an(self):
        for werte in ({"MONITOR_UPDATE_QUELLE": "gitlab"},
                      {"MONITOR_UPDATE_QUELLE": "forgejo"},
                      {"MONITOR_UPDATE_QUELLE": "forgejo", "MONITOR_UPDATE_FORGEJO": "http://192.0.2.10:3000"},
                      {"MONITOR_UPDATE_QUELLE": "forgejo", "MONITOR_UPDATE_FORGEJO": "https://nutzer:pw@git.example.org"},
                      {"MONITOR_UPDATE_QUELLE": "forgejo", "MONITOR_UPDATE_FORGEJO": "https://git.example.org/?x=1"},
                      {"MONITOR_UPDATE_QUELLE": "forgejo", "MONITOR_UPDATE_FORGEJO": "ftp://git.example.org"}):
            with self.subTest(werte=werte), self.assertRaises(konfig.KonfigFehler):
                self.lade(**werte)

    def test_http_nur_mit_freigabe(self):
        k = self.lade(MONITOR_UPDATE_QUELLE="forgejo", MONITOR_UPDATE_FORGEJO="http://192.0.2.10:3000", MONITOR_UPDATE_HTTP_ERLAUBT="1")
        self.assertEqual((k.update_forgejo, k.update_http_erlaubt), ("http://192.0.2.10:3000", True))
        self.assertTrue(quelle.anzeige(k)["http"])
        # bei http:// ohne Proxy aus der Umgebung (E-21)
        handler = [type(h).__name__ for h in quelle.oeffner(k).handlers]
        self.assertIn("_OhneWeiterleitung", handler)
        self.assertNotIn("ProxyHandler", handler)

    def test_anzeige(self):
        self.assertEqual(quelle.anzeige(self.lade())["releases"], "https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/releases")
        q = quelle.anzeige(self.lade(MONITOR_UPDATE_QUELLE="forgejo", MONITOR_UPDATE_FORGEJO="https://git.example.org/forgejo"))
        self.assertEqual(q, {"art": "forgejo", "name": "Forgejo", "adresse": "https://git.example.org/forgejo", "http": False,
                             "releases": "https://git.example.org/forgejo/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/releases"})


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeForgejo(praefix="/git")
        self.k = k_forgejo(self.fake.basis)

    def tearDown(self):
        self.fake.schliessen()

    def test_neuestes_release_mit_selbst_gebauten_adressen(self):
        daten = quelle.forgejo_release(self.k, "1.0.0")
        self.assertEqual(daten["fehler"], "")
        self.assertEqual(daten["version"], "1.2.3")
        self.assertTrue(daten["bereit"])
        self.assertEqual((daten["archiv"], daten["pruefsumme"]), quelle.download_urls(self.k, "1.2.3"))
        self.assertTrue(daten["archiv"].startswith(f"{self.fake.basis}/{REPO}/releases/download/v1.2.3/"))
        self.assertEqual(daten["url"], f"{self.fake.basis}/{REPO}/releases/tag/v1.2.3")
        self.assertEqual([r["version"] for r in daten["aenderungen"]], ["1.2.3", "1.2.2"])
        self.assertEqual(daten["aenderungen"][0]["neu"], ["Forgejo als Quelle"])
        self.assertNotIn("boese", json.dumps(daten))
        # nur API-Aufrufe, kein Download, keine Anmeldung
        self.assertTrue(all("/api/v1/" in p for p in self.fake.aufrufe))

    def test_ohne_paket_nicht_bereit(self):
        self.fake.antworten[f"/git/api/v1/repos/{REPO}/releases/latest"] = (200, {}, json.dumps(self.fake.release("1.2.3", assets=False)).encode())
        daten = quelle.forgejo_release(self.k, "1.0.0")
        self.assertEqual((daten["version"], daten["bereit"], daten["archiv"]), ("1.2.3", False, ""))

    def test_tag_ohne_v_wird_nicht_angeboten(self):
        self.fake.antworten[f"/git/api/v1/repos/{REPO}/releases/latest"] = (200, {}, json.dumps(self.fake.release("1.2.3", tag="1.2.3")).encode())
        daten = quelle.forgejo_release(self.k, "1.0.0")
        self.assertEqual((daten["version"], daten["bereit"]), ("", False))
        self.assertIn("vX.Y.Z", daten["fehler"])

    def test_anmeldung_verlangt(self):
        self.fake.antworten[f"/git/api/v1/repos/{REPO}/releases/latest"] = (403, {}, b"{}")
        daten = quelle.forgejo_release(self.k, "1.0.0")
        self.assertEqual(daten["version"], "")
        self.assertIn("Anmeldung", daten["fehler"])

    def test_weiterleitung_wird_nicht_gefolgt(self):
        zweiter = FakeForgejo()
        try:
            self.fake.antworten[f"/git/api/v1/repos/{REPO}/releases/latest"] = (
                302, {"Location": f"{zweiter.basis}/api/v1/repos/{REPO}/releases/latest"}, b"")
            daten = quelle.forgejo_release(self.k, "1.0.0")
            self.assertIn("leitet weiter", daten["fehler"])
            self.assertEqual(zweiter.aufrufe, [])
        finally:
            zweiter.schliessen()

    def test_http_ohne_freigabe_fragt_nicht(self):
        k = konfig.Konfig(release_repo=REPO, update_quelle="forgejo", update_forgejo=self.fake.basis, update_http_erlaubt=False)
        daten = quelle.forgejo_release(k, "1.0.0")
        self.assertEqual(daten["version"], "")
        self.assertEqual(self.fake.aufrufe, [])

    def test_sammler_schreibt_quelle(self):
        from runner_monitor import sammler
        with tempfile.TemporaryDirectory() as tmp:
            k = k_forgejo(self.fake.basis, MONITOR_LAUF_VERZ=tmp, MONITOR_DATEN_VERZ=tmp)
            daten = sammler.Sammler(k).release()
            gespeichert = json.loads((Path(tmp) / "release.json").read_text())
        self.assertEqual((daten["quelle"], gespeichert["quelle"], gespeichert["version"]), ("forgejo", "forgejo", "1.2.3"))


class DownloadTest(unittest.TestCase):
    """Der Update-Hilfsdienst mit Forgejo als Quelle – Neustart, Gesundheitsprüfung und Herkunft
    sind ersetzt, alles andere (Download, Prüfsumme, Entpacken, Umhängen) läuft echt."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / "opt" / "versionen" / "1.0.0").mkdir(parents=True)
        (self.d / "opt" / "aktuell").symlink_to(Path("versionen") / "1.0.0")
        self.fake = FakeForgejo()
        self.patches = [mock.patch.object(a, "BASIS", self.d / "opt"), mock.patch.object(a, "neustart"),
                        mock.patch.object(a, "gesund", return_value=True),
                        mock.patch.object(a, "herkunft_pruefen", return_value="geprüft")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.fake.schliessen()
        self.tmp.cleanup()

    def konfig(self, **mehr):
        return k_forgejo(self.fake.basis, MONITOR_LAUF_VERZ=str(self.d / "lauf"), MONITOR_DATEN_VERZ=str(self.d / "daten"), **mehr)

    def release_json(self, k, **mehr):
        (self.d / "lauf").mkdir(exist_ok=True)
        archiv, summe = quelle.download_urls(k, "1.2.3")
        daten = {"version": "1.2.3", "archiv": archiv, "pruefsumme": summe, "bereit": True, "quelle": "forgejo", **mehr}
        (self.d / "lauf" / "release.json").write_text(json.dumps(daten))

    def status(self):
        return json.loads((self.d / "daten" / "update-status.json").read_text())

    def test_update_von_forgejo(self):
        k = self.konfig()
        self.release_json(k)
        a.aktualisiere(k, "1.2.3")
        self.assertEqual(os.readlink(self.d / "opt" / "aktuell"), "versionen/1.2.3")
        self.assertEqual((self.d / "opt" / "versionen" / "1.2.3" / "VERSION").read_text(), "1.2.3\n")
        self.assertEqual((self.status()["zustand"], self.status()["quelle"]), ("erfolg", "forgejo"))
        self.assertEqual(sorted(self.fake.aufrufe), [f"/{REPO}/releases/download/v1.2.3/runner-monitor-1.2.3.tar.gz",
                                                     f"/{REPO}/releases/download/v1.2.3/runner-monitor-1.2.3.tar.gz.sha256"])

    def test_nur_genau_die_eigenen_adressen(self):
        k = self.konfig()
        fremd = [f"{self.fake.basis}/fremd/repo/releases/download/v1.2.3/runner-monitor-1.2.3.tar.gz",
                 f"{self.fake.basis}/{REPO}/releases/download/v1.2.3/../../../x/runner-monitor-1.2.3.tar.gz",
                 f"https://github.com/{REPO}/releases/download/v1.2.3/runner-monitor-1.2.3.tar.gz",
                 f"{self.fake.basis}/{REPO}/releases/download/v1.2.3/runner-monitor-1.2.3.tar.gz?x=1"]
        for url in fremd:
            with self.subTest(url=url):
                self.release_json(k, archiv=url)
                with self.assertRaises(a.UpdateFehler) as f:
                    a.aktualisiere(k, "1.2.3")
                self.assertEqual(f.exception.schritt, 1)
        self.assertEqual(self.fake.aufrufe, [])

    def test_release_json_der_vorigen_quelle(self):
        k = self.konfig()
        self.release_json(k, quelle="github")
        with self.assertRaises(a.UpdateFehler) as f:
            a.aktualisiere(k, "1.2.3")
        self.assertIn("vorigen Update-Quelle", str(f.exception))

    def test_download_folgt_keiner_weiterleitung(self):
        zweiter = FakeForgejo()
        try:
            k = self.konfig()
            self.release_json(k)
            self.fake.antworten[f"/{REPO}/releases/download/v1.2.3/runner-monitor-1.2.3.tar.gz"] = (
                302, {"Location": f"{zweiter.basis}/{REPO}/releases/download/v1.2.3/runner-monitor-1.2.3.tar.gz"}, b"")
            with self.assertRaises(a.UpdateFehler) as f:
                a.aktualisiere(k, "1.2.3")
            self.assertIn("Weiterleitung", str(f.exception))
            self.assertEqual(zweiter.aufrufe, [])
            self.assertEqual(os.readlink(self.d / "opt" / "aktuell"), "versionen/1.0.0")
        finally:
            zweiter.schliessen()

    def test_anmeldeseite_ist_klarer_fehler(self):
        """Nicht öffentlicher Server: Anmeldeseite als HTML mit 200, als Weiterleitung oder 403 –
        immer „Quelle verlangt Anmeldung“, nie „kaputtes Archiv“ und nie entpackt."""
        archiv = f"/{REPO}/releases/download/v1.2.3/runner-monitor-1.2.3.tar.gz"
        seite = b"<!DOCTYPE html><html><body>Anmelden</body></html>"
        faelle = [(200, {"Content-Type": "text/html; charset=utf-8"}, seite),
                  (200, {"Content-Type": "application/octet-stream"}, b"\n  " + seite),
                  (303, {"Location": "/user/login"}, b""),
                  (403, {}, b"")]
        k = self.konfig()
        for antwort in faelle:
            with self.subTest(antwort=antwort[:2]):
                self.release_json(k)
                self.fake.antworten[archiv] = antwort
                with self.assertRaises(a.UpdateFehler) as f:
                    a.aktualisiere(k, "1.2.3")
                self.assertEqual(f.exception.schritt, 1)
                self.assertIn("Quelle verlangt Anmeldung", str(f.exception))
                self.assertFalse((self.d / "opt" / "versionen" / "1.2.3").exists())

    def test_kein_gzip_wird_vor_der_pruefsumme_verworfen(self):
        self.fake.inhalt = b"kein archiv"
        k = self.konfig()
        self.release_json(k)
        with self.assertRaises(a.UpdateFehler) as f:
            a.aktualisiere(k, "1.2.3")
        self.assertEqual(f.exception.schritt, 1)
        self.assertIn("kein tar.gz", str(f.exception))

    def test_falsche_pruefsumme(self):
        k = self.konfig()
        self.release_json(k)
        self.fake.antworten[f"/{REPO}/releases/download/v1.2.3/runner-monitor-1.2.3.tar.gz.sha256"] = (200, {}, b"0" * 64 + b"\n")
        with self.assertRaises(a.UpdateFehler) as f:
            a.aktualisiere(k, "1.2.3")
        self.assertEqual(f.exception.schritt, 2)
        self.assertFalse((self.d / "opt" / "versionen" / "1.2.3").exists())

    def test_paket_mit_anderer_version_wird_verworfen(self):
        self.fake.inhalt = paket("1.2.3", version_drin="0.9.0")  # echtes älteres Paket unter neuer Nummer
        k = self.konfig()
        self.release_json(k)
        with self.assertRaises(a.UpdateFehler) as f:
            a.aktualisiere(k, "1.2.3")
        self.assertEqual(f.exception.schritt, 3)
        self.assertIn("0.9.0", str(f.exception))
        self.assertFalse((self.d / "opt" / "versionen" / "1.2.3").exists())
        self.assertEqual(os.readlink(self.d / "opt" / "aktuell"), "versionen/1.0.0")
        a.neustart.assert_not_called()


class HerkunftForgejoTest(unittest.TestCase):
    """Die Attestierung wird bei Forgejo gegen das GitHub-Repository geprüft (sie hängt am SHA-256)."""

    def test_gh_gegen_github_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "bin").mkdir()
            gh = d / "bin" / "gh"
            gh.write_text(f"#!/bin/sh\necho \"$@\" > {d}/aufruf\nexit 1\n")
            gh.chmod(0o755)
            (d / "github-token").write_text("t")
            (d / "a.tar.gz").write_bytes(b"x")
            k = k_forgejo("https://git.example.org", MONITOR_TOKEN_DATEI=str(d / "github-token"))
            with mock.patch.dict(os.environ, {"PATH": str(d / "bin")}):
                # Keine Attestierung zu diesem SHA-256 (z. B. auf Forgejo verändert): Update bricht ab
                with self.assertRaises(a.UpdateFehler):
                    a.herkunft_pruefen(k, d / "a.tar.gz")
            aufruf = (d / "aufruf").read_text()
            self.assertIn(f"--repo {REPO} --signer-workflow {REPO}/.github/workflows/release.yml", aufruf)
            self.assertNotIn("git.example.org", aufruf)


class KonfigSchreibenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pfad = Path(self.tmp.name) / "konfig.env"
        self.pfad.write_text("# Kopf\nMONITOR_PORT=8090\n\n#MONITOR_UPDATE_HERKUNFT=pflicht\nMONITOR_RELEASE_REPO=a/b\n")
        os.chmod(self.pfad, 0o640)

    def tearDown(self):
        self.tmp.cleanup()

    def setze(self, *argumente):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as aus:
            rc = quelle._main(["setze", "--konfig", str(self.pfad), *argumente])  # noqa: SLF001
        return rc, aus.getvalue()

    def test_forgejo_setzen_und_zurueck(self):
        rc, aus = self.setze("--quelle", "forgejo", "--basis", "https://Git.Example.org/")
        self.assertEqual(rc, 0, aus)
        text = self.pfad.read_text()
        self.assertIn("MONITOR_PORT=8090\n", text)
        self.assertIn("#MONITOR_UPDATE_HERKUNFT=pflicht\n", text)
        self.assertIn("MONITOR_UPDATE_QUELLE=forgejo\nMONITOR_UPDATE_FORGEJO=https://git.example.org\n", text)
        self.assertNotIn("HTTP_ERLAUBT", text)
        self.assertEqual(self.pfad.stat().st_mode & 0o777, 0o640)
        k = konfig.lade(datei=self.pfad, umgebung={})
        self.assertEqual((k.update_quelle, k.update_forgejo), ("forgejo", "https://git.example.org"))
        rc, _ = self.setze("--quelle", "github")
        text = self.pfad.read_text()
        self.assertEqual(rc, 0)
        self.assertIn("MONITOR_UPDATE_QUELLE=github", text)
        self.assertNotIn("MONITOR_UPDATE_FORGEJO", text)
        self.assertEqual(text.count("MONITOR_UPDATE_QUELLE"), 1)

    def test_http_nur_mit_freigabe(self):
        rc, aus = self.setze("--quelle", "forgejo", "--basis", "http://192.0.2.10:3000")
        self.assertEqual(rc, 2)
        self.assertIn("MONITOR_UPDATE_HTTP_ERLAUBT", aus)
        self.assertNotIn("MONITOR_UPDATE_QUELLE", self.pfad.read_text())
        rc, _ = self.setze("--quelle", "forgejo", "--basis", "http://192.0.2.10:3000", "--http-erlaubt")
        self.assertEqual(rc, 0)
        k = konfig.lade(datei=self.pfad, umgebung={})
        self.assertEqual((k.update_forgejo, k.update_http_erlaubt), ("http://192.0.2.10:3000", True))

    def test_ungueltige_adresse_schreibt_nichts(self):
        vorher = self.pfad.read_text()
        rc, _ = self.setze("--quelle", "forgejo", "--basis", "https://nutzer:geheim@git.example.org")
        self.assertEqual(rc, 2)
        self.assertEqual(self.pfad.read_text(), vorher)

    def test_pruefe_adresse_und_zeige(self):
        def rufe(*argumente):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as aus:
                return quelle._main(list(argumente)), aus.getvalue().strip()  # noqa: SLF001
        self.assertEqual(rufe("pruefe-adresse", "--", "https://git.example.org/"), (0, "https://git.example.org"))
        self.assertEqual(rufe("pruefe-adresse", "--", "http://192.0.2.10:3000"), (4, "http://192.0.2.10:3000"))
        self.assertEqual(rufe("pruefe-adresse", "--", "git.example.org")[0], 2)
        self.assertEqual(rufe("zeige", "--konfig", str(self.pfad)), (0, "quelle=github\nbasis=\nhttp=0\nfehler="))


if __name__ == "__main__":
    unittest.main()
