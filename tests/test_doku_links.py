"""Doku-Links der Oberfläche und des Einrichtungsskripts zeigen auf vorhandene Dateien und Überschriften (#132)."""
import re
import unittest
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
BASIS = "https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/blob/"


def slug(ueberschrift: str) -> str:
    """Anker wie GitHub: klein, nur Buchstaben/Ziffern/Leerzeichen/Bindestrich/Unterstrich, Leerzeichen -> Bindestrich."""
    s = re.sub(r"[`*_]{1}(?=\S)|(?<=\S)[`*]", "", ueberschrift.strip().lower())
    s = re.sub(r"[^\w\s-]", "", s)
    return s.replace(" ", "-")


def anker_von(datei: Path) -> set:
    namen, zaehler, im_code = set(), {}, False
    for zeile in datei.read_text(encoding="utf-8").splitlines():
        if zeile.startswith("```"):
            im_code = not im_code
        m = None if im_code else re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", zeile)
        if m:
            s = slug(m.group(1))
            n = zaehler.get(s, 0)
            zaehler[s] = n + 1
            namen.add(s if n == 0 else f"{s}-{n}")
    return namen


def links() -> list:
    """(Quelle, Datei unter docs/, Anker oder None) aus web/*.js und einrichten.sh."""
    funde = []
    for q in sorted((WURZEL / "web").glob("*.js")) + [WURZEL / "einrichten.sh"]:
        text = q.read_text(encoding="utf-8")
        muster = [
            re.compile(re.escape(BASIS) + r"(?:main|v[\d.]+)/docs/([\w.-]+\.md)(?:#([\w-]+))?"),
            re.compile(r"DOKU\.url\('([\w.-]+\.md)'(?:,\s*'([\w-]+)')?\)"),
            re.compile(r"\$DOKU/([\w.-]+\.md)(?:#([\w-]+))?"),
        ]
        for mu in muster:
            for m in mu.finditer(text):
                funde.append((q.name, m.group(1), m.group(2)))
    return funde


class DokuLinks(unittest.TestCase):
    def test_links_vorhanden(self):
        quellen = {q for q, _, _ in links()}
        self.assertIn("einrichtung.js", quellen)
        self.assertIn("einrichten.sh", quellen)

    def test_dateien_und_anker_stimmen(self):
        for quelle, datei, anker in links():
            pfad = WURZEL / "docs" / datei
            self.assertTrue(pfad.is_file(), f"{quelle}: docs/{datei} fehlt")
            if anker:
                self.assertIn(anker, anker_von(pfad), f"{quelle}: Anker #{anker} fehlt in docs/{datei}")

    def test_keine_festen_main_links(self):
        # Doku-Links gehen über DOKU.url() (web) bzw. $DOKU (Skript) auf den Tag der Version
        for q in sorted((WURZEL / "web").glob("*.js")) + [WURZEL / "einrichten.sh"]:
            if q.name == "doku.js":
                continue
            text = q.read_text(encoding="utf-8")
            self.assertNotRegex(text, re.escape(BASIS) + r"main/docs/", f"{q.name}: fester main-Link")

    def test_skript_basis_ist_der_tag_der_version(self):
        text = (WURZEL / "einrichten.sh").read_text(encoding="utf-8")
        self.assertIn(BASIS + "v$VERSION/docs", text)

    def test_slug_regeln(self):
        self.assertEqual(slug("Forgejo- oder Gitea-Runner anbinden (#93)"), "forgejo--oder-gitea-runner-anbinden-93")
        self.assertEqual(slug("GitLab anbinden"), "gitlab-anbinden")
        self.assertEqual(slug("Prüfen & Größe: Änderungen"), "prüfen--größe-änderungen")


if __name__ == "__main__":
    unittest.main()
