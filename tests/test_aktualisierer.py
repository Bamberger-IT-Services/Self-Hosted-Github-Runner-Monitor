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
