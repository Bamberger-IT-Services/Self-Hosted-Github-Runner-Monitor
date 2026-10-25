"""Sprachumschaltung (#79): Jeder deutsche Text, der über t() oder data-t läuft, hat eine englische
Fassung in web/i18n.js, und die Platzhalter stimmen überein."""

import html
import json
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
SEITEN = ["gemeinsam.js", "dashboard.js", "dashboard.html"]


def englisch() -> dict[str, str]:
    text = (WEB / "i18n.js").read_text(encoding="utf-8")
    roh = text[text.index("const EN = {") + len("const EN = "): text.index("\n  };", text.index("const EN = {")) + 4]
    return json.loads(roh)


def schluessel(datei: str) -> list[str]:
    s = (WEB / datei).read_text(encoding="utf-8")
    gefunden: list[str] = []
    if datei.endswith(".js"):
        for m in re.finditer(r"\bt\('((?:[^'\\]|\\.)*)'", s):
            gefunden.append(m.group(1).replace("\\'", "'"))
        return gefunden
    for m in re.finditer(r"<[a-z0-9]+[^>]*\sdata-t(?=[\s>])[^>]*>([^<]*)<", s):
        gefunden.append(html.unescape(m.group(1).strip()))
    for attr, marke in (("title", "data-t-title"), ("aria-label", "data-t-aria"), ("placeholder", "data-t-placeholder")):
        for m in re.finditer(r"<[^>]*>", s):
            tag = m.group(0)
            if marke in tag:
                wert = re.search(rf'\s{attr}="([^"]*)"', tag)
                if wert:
                    gefunden.append(html.unescape(wert.group(1)))
    return gefunden


class I18nTest(unittest.TestCase):
    def test_alles_uebersetzt(self):
        en = englisch()
        fehlt = sorted({k for datei in SEITEN for k in schluessel(datei) if k not in en})
        self.assertEqual(fehlt, [], "ohne englische Fassung")

    def test_platzhalter_gleich(self):
        for de, en in englisch().items():
            self.assertEqual(sorted(re.findall(r"\{(\w+)\}", de)), sorted(re.findall(r"\{(\w+)\}", en)), de)

    def test_keine_toten_eintraege(self):
        alle = {k for datei in SEITEN + ["anmelden.js", "anmelden.html", "einrichtung.js", "einrichtung.html"]
                if (WEB / datei).exists() for k in schluessel(datei)}
        tot = sorted(set(englisch()) - alle)
        self.assertEqual(tot, [], "Übersetzungen ohne Verwendung")

    def test_skript_vor_gemeinsam(self):
        for seite in ("dashboard.html", "anmelden.html", "einrichtung.html"):
            s = (WEB / seite).read_text(encoding="utf-8")
            self.assertLess(s.index("/static/i18n.js"), s.index("/static/gemeinsam.js"), seite)
