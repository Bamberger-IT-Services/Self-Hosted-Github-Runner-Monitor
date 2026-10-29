"""Sprachumschaltung (#79): Jeder deutsche Text, der über t() oder data-t läuft, hat eine englische
Fassung in web/i18n.js, und die Platzhalter stimmen überein. Dazu die Meldungen des Servers (#81):
Der deutsche Text (bzw. die Vorlage mit {platzhaltern}) ist der Schlüssel."""

import html
import json
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
SEITEN = ["gemeinsam.js", "dashboard.js", "mail.js", "dashboard.html", "anmelden.js", "anmelden.html", "einrichtung.js", "einrichtung.html"]
WURZEL = WEB.parent


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


def server_meldungen() -> list[str]:
    """Feste Texte und Vorlagen, die der Server an die Oberfläche schickt."""
    from runner_monitor import zugang
    s = (WURZEL / "runner_monitor" / "server.py").read_text(encoding="utf-8")
    texte = re.findall(r'_fehler\(HTTPStatus\.\w+, "([^"]+)"', s)
    texte += re.findall(r'meldung\("([^"]+)"', s)
    texte += re.findall(r'"(?:fehler|text)": "([^"]+)"', s)
    texte += re.findall(r'"(?:falsch|abgelaufen|fehlt)": "([^"]+)"', s)
    # Runner-Schritte der Einrichtung (#96): Prüfergebnisse und Eingabefehler
    e = (WURZEL / "runner_monitor" / "einrichtung.py").read_text(encoding="utf-8")
    texte += re.findall(r'meldung\("([^"]+)"', e)
    texte += re.findall(r'"text": "([^"]+)"', e)
    texte += re.findall(r'EingabeFehler\("([^"]+)"\)', e)
    z = (WURZEL / "runner_monitor" / "zugang.py").read_text(encoding="utf-8")
    texte += re.findall(r'ZugangFehler\("([^"]+)"\)', z)
    texte += re.findall(r'return "(Dieses[^"]+)"', z)
    texte += [f"Das Passwort braucht mindestens {zugang.PASSWORT_MIN} Zeichen.",
              f"Das Passwort darf höchstens {zugang.PASSWORT_MAX} Zeichen haben."]
    return texte


class I18nTest(unittest.TestCase):
    def test_alles_uebersetzt(self):
        en = englisch()
        fehlt = sorted({k for datei in SEITEN for k in schluessel(datei) if k not in en})
        self.assertEqual(fehlt, [], "ohne englische Fassung")

    def test_server_meldungen_uebersetzt(self):
        en = englisch()
        meldungen = server_meldungen()
        self.assertGreater(len(meldungen), 20)
        self.assertEqual(sorted({m for m in meldungen if m not in en}), [], "Server-Meldung ohne englische Fassung")

    def test_meldung_mit_vorlage(self):
        from runner_monitor import server
        self.assertEqual(server.meldung("Nicht gefunden"), {"text": "Nicht gefunden"})
        m = server.meldung("Version {v} wird noch bereitgestellt – bitte in ein bis zwei Minuten erneut versuchen.", v="1.2.3")
        self.assertEqual(m["werte"], {"v": "1.2.3"})
        self.assertTrue(m["text"].startswith("Version 1.2.3 "))

    def test_platzhalter_gleich(self):
        for de, en in englisch().items():
            self.assertEqual(sorted(re.findall(r"\{(\w+)\}", de)), sorted(re.findall(r"\{(\w+)\}", en)), de)

    def test_keine_toten_eintraege(self):
        alle = {k for datei in SEITEN for k in schluessel(datei)} | set(server_meldungen())
        tot = sorted(set(englisch()) - alle)
        self.assertEqual(tot, [], "Übersetzungen ohne Verwendung")

    def test_skript_vor_gemeinsam(self):
        for seite in ("dashboard.html", "anmelden.html", "einrichtung.html"):
            s = (WEB / seite).read_text(encoding="utf-8")
            self.assertLess(s.index("/static/i18n.js"), s.index("/static/gemeinsam.js"), seite)

    def test_englisch_nicht_leer(self):
        for de, en in englisch().items():
            self.assertTrue(en.strip(), de)

    def test_sprachwahl_im_info_blatt(self):
        """#90: Segment Automatisch | Deutsch | English mit Hinweis; Speicherort und Altlast."""
        d = (WEB / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn("['auto', t('Automatisch')", d)
        self.assertIn("['de', 'Deutsch'", d)
        self.assertIn("['en', 'English'", d)
        hinweis = "„Automatisch“ folgt der Sprache des Systems. Andere Sprachen als Deutsch zeigen Englisch. Die Wahl gilt nur für diesen Browser."
        self.assertIn(f"t('{hinweis}')", d)
        self.assertIn(hinweis, englisch())
        i = (WEB / "i18n.js").read_text(encoding="utf-8")
        self.assertIn("'runner-monitor.sprache'", i)
        for datei in WEB.glob("*.js"):
            if datei.name != "i18n.js":
                self.assertNotIn("rm-sprache", datei.read_text(encoding="utf-8"), datei.name)

    def test_automatisch_folgt_systemsprache(self):
        i = (WEB / "i18n.js").read_text(encoding="utf-8")
        self.assertIn("navigator.languages", i)
        self.assertIn("(?:$|[-_])", i)   # de, de-DE, de_AT – nicht „deu“; Logik: tests/js/i18n.test.mjs
