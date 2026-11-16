"""Forgejo liest nur .forgejo/workflows, sobald der Ordner existiert (#181). Dort liegt eine Kopie von ci.yml;
release.yml bleibt nur unter .github/workflows (GitHub-Rechte wie attestations kennt Forgejo nicht)."""
import pathlib
import unittest

WURZEL = pathlib.Path(__file__).resolve().parent.parent


class WorkflowTest(unittest.TestCase):
    def test_ci_kopie_fuer_forgejo_gleich(self):
        github = (WURZEL / ".github/workflows/ci.yml").read_bytes()
        forgejo = (WURZEL / ".forgejo/workflows/ci.yml").read_bytes()
        self.assertEqual(github, forgejo, ".forgejo/workflows/ci.yml muss eine Kopie von .github/workflows/ci.yml sein")

    def test_release_nicht_auf_forgejo(self):
        self.assertFalse((WURZEL / ".forgejo/workflows/release.yml").exists())


if __name__ == "__main__":
    unittest.main()
