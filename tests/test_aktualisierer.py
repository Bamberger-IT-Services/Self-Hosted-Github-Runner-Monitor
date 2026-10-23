import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from runner_monitor import aktualisierer as a


def archiv(pfad: Path, eintraege: dict[str, bytes], link: str | None = None) -> None:
    with tarfile.open(pfad, "w:gz") as tar:
        for name, inhalt in eintraege.items():
            info = tarfile.TarInfo(name)
            info.size = len(inhalt)
            tar.addfile(info, io.BytesIO(inhalt))
        if link:
            info = tarfile.TarInfo("runner-monitor-1.0.0/boese")
            info.type = tarfile.SYMTYPE
            info.linkname = link
            tar.addfile(info)


class AktualisiererTest(unittest.TestCase):
    def setUp(self):
        self.verz = tempfile.TemporaryDirectory()
        self.d = Path(self.verz.name)

    def tearDown(self):
        self.verz.cleanup()

    def test_url_nur_offizielles_release(self):
        repo = "Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor"
        self.assertTrue(a.erlaubte_url(f"https://github.com/{repo}/releases/download/v1.0.0/x.tar.gz", repo))
        self.assertFalse(a.erlaubte_url("https://example.org/x.tar.gz", repo))
        self.assertFalse(a.erlaubte_url(f"http://github.com/{repo}/releases/download/v1/x", repo))
        self.assertFalse(a.erlaubte_url("https://github.com/fremd/repo/releases/download/v1/x", repo))

    def test_entpacken_ohne_obersten_ordner(self):
        archiv(self.d / "a.tar.gz", {"runner-monitor-1.0.0/VERSION": b"1.0.0\n", "runner-monitor-1.0.0/web/stil.css": b"x"})
        a.entpacke(self.d / "a.tar.gz", self.d / "ziel")
        self.assertEqual((self.d / "ziel" / "VERSION").read_text(), "1.0.0\n")
        self.assertTrue((self.d / "ziel" / "web" / "stil.css").exists())

    def test_entpacken_lehnt_ausbruch_ab(self):
        archiv(self.d / "b.tar.gz", {"runner-monitor-1.0.0/../../boese": b"x"})
        with self.assertRaises(a.UpdateFehler):
            a.entpacke(self.d / "b.tar.gz", self.d / "ziel")
        archiv(self.d / "c.tar.gz", {"runner-monitor-1.0.0/VERSION": b"1"}, link="/etc/passwd")
        with self.assertRaises(a.UpdateFehler):
            a.entpacke(self.d / "c.tar.gz", self.d / "ziel2")

    def test_pruefsumme(self):
        (self.d / "x").write_bytes(b"abc")
        self.assertEqual(a.sha256(self.d / "x"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


if __name__ == "__main__":
    unittest.main()


class HerkunftTest(unittest.TestCase):
    """Issue #18: GitHub-Attestierung des Archivs mit `gh attestation verify` (ADR-0005)."""

    def setUp(self):
        import os
        from runner_monitor import konfig
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.bin = d / "bin"
        self.bin.mkdir()
        self.token = d / "github-token"
        self.archiv = d / "a.tar.gz"
        self.archiv.write_bytes(b"x")
        self.pfad = os.environ.get("PATH", "")
        os.environ["PATH"] = str(self.bin)
        self.konfig = lambda **w: konfig.lade(datei=d / "fehlt.env", umgebung={"MONITOR_TOKEN_DATEI": str(self.token), **w})

    def tearDown(self):
        import os
        os.environ["PATH"] = self.pfad
        self.tmp.cleanup()

    def gh(self, code: int):
        skript = self.bin / "gh"
        skript.write_text(f"#!/bin/sh\necho \"$@\" > {self.bin}/aufruf\necho 'verification failed' >&2\nexit {code}\n")
        skript.chmod(0o755)

    def test_ohne_cli_nur_pruefsumme(self):
        self.assertTrue(a.herkunft_pruefen(self.konfig(), self.archiv).startswith("nicht geprüft (GitHub-CLI fehlt"))

    def test_pflicht_ohne_cli_bricht_ab(self):
        with self.assertRaises(a.UpdateFehler):
            a.herkunft_pruefen(self.konfig(MONITOR_UPDATE_HERKUNFT="pflicht"), self.archiv)

    def test_bestaetigt(self):
        self.gh(0)
        self.token.write_text("t")
        self.assertEqual(a.herkunft_pruefen(self.konfig(), self.archiv), "geprüft")
        aufruf = (self.bin / "aufruf").read_text()
        self.assertIn("attestation verify", aufruf)
        self.assertIn("--signer-workflow Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/.github/workflows/release.yml", aufruf)

    def test_nicht_bestaetigt_bricht_immer_ab(self):
        self.gh(1)
        self.token.write_text("t")
        with self.assertRaises(a.UpdateFehler) as f:
            a.herkunft_pruefen(self.konfig(), self.archiv)
        self.assertIn("Herkunft nicht bestätigt", str(f.exception))
