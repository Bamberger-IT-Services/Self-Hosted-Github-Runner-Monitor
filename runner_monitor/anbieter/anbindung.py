"""Anbindung eines Forgejo-, Gitea- oder GitLab-Runners auf der VM (#120, E-18, E-21, E-22, E-26).

``sudo einrichten.sh zugang <runner>`` fragt für diese Dienste Server, Organisation (nicht bei GitLab)
und Token ab. Geprüft und geschrieben wird **hier**, nicht im Skript – mit denselben Regeln, nach denen
Erkennung, Sammler und Adapter ``/etc/runner-monitor/runner.json`` lesen:

* **Server** (:func:`pruefe_server`): ``erkennung.pruefe_url`` und wie ``erkennung.lies_zuordnung``
  ohne ``@``, ``?``, ``#`` (Zugangsdaten, Abfrage, Anker werden abgelehnt statt still gekürzt); dazu
  ohne ``/api…`` am Ende (der Adapter hängt ``/api/v1`` bzw. ``/api/v4`` selbst an). ``http://`` nur,
  wenn der Aufrufer es ausdrücklich erlaubt (``http_erlaubt: true``, E-21).
* **Organisation** (:func:`pruefe_org_eingabe`): ``erkennung.pruefe_org``; nur, wenn der Adapter sie
  braucht (``BRAUCHT_ORG``: Forgejo, Gitea).
* **runner.json** (:func:`setze`): gelesen wie in der Einrichtung (``einrichtung.lies_roh``: regulär,
  ohne Symlink, begrenzt; kaputt oder Symlink → nichts geschrieben), geschrieben mit
  ``einrichtung.schreibe_zuordnung`` (atomar, 0640, root, Gruppe des Ordners, Ordner muss ein echtes
  Verzeichnis von root sein). Geändert werden nur ``server``, ``org``, ``http_erlaubt`` und – auf
  Wunsch – ein ``stand: "grund"`` dieses Runners; alle anderen Felder und Runner bleiben.
* **Token** über den bestehenden Weg (``token.schreibe``: ``zugang/`` root 0700, Datei 0600, atomar,
  kein Symlink). Es kommt nur über die Standardeingabe, nie als Argument, und erscheint nie in der
  Ausgabe.
* **Neue Adresse, altes Token (E-22):** Ändert sich der Server eines Runners, der schon ein Token hat,
  ist ein neues Token Pflicht. Reihenfolge: altes Token löschen → ``runner.json`` schreiben → neues
  Token schreiben. Bricht etwas ab, bleibt höchstens „kein Token“ – nie das alte Token an der neuen
  Adresse. Bei gleicher Adresse darf das Token bleiben.
* **Verbindungsprüfung** (:func:`pruefe_verbindung`): eine Abfrage des vorhandenen Adapters (nur GET,
  keine Weiterleitung, harte Fristen) in einem eigenen Faden mit Gesamtfrist; Ausgabe ohne Token.

Kommandozeile (für ``einrichten.sh``; Rückgabe 0 = in Ordnung, 2 = Fehler, weitere siehe Befehl)::

    python3 -m runner_monitor.anbieter.anbindung info --runner ID --erkennung /run/runner-monitor/erkennung.json \\
        --zuordnung /etc/runner-monitor/runner.json --zugang-verz /etc/runner-monitor/zugang
    python3 -m runner_monitor.anbieter.anbindung pruefe-server -- WERT     # 0 https, 4 http, 2 ungültig
    python3 -m runner_monitor.anbieter.anbindung pruefe-org -- WERT        # 0 gültig, 2 ungültig
    printf '%s\\n' "$token" | python3 -m runner_monitor.anbieter.anbindung setze --runner ID \\
        --zuordnung … --zugang-verz … --server URL [--org ORG] [--http-erlaubt] [--stand-aufheben] [--token-stdin]
    python3 -m runner_monitor.anbieter.anbindung pruefe-verbindung --runner ID --erkennung … --zuordnung … \\
        --zugang-verz … [--frist 40]

``info`` gibt ``schluessel=wert`` je Zeile aus (nur geprüfte Werte), ``setze`` und
``pruefe-verbindung`` Zeilen ``art|text`` (``ok``, ``warn``, ``fehler``, ``hin``) für die Ausgabe im Skript.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import threading
import urllib.parse
from pathlib import Path

from .. import einrichtung, erkennung
from . import adapter, angebunden, klasse_fuer, konfig_aus
from . import token as zugangsdaten

DIENSTE_MIT_SERVER = ("forgejo", "gitea", "gitlab")
ANZEIGE = erkennung.ANZEIGE
API_ENDE = re.compile(r"/api(?:/v\d{1,2})?$", re.IGNORECASE)
# Wie die Prüfung in einrichten.sh (andere Dienste als GitHub): druckbar, ohne Leerzeichen, 16–512 Zeichen
TOKEN = re.compile(r"[A-Za-z0-9._~+/=-]{16,512}")
FRIST = 40.0             # Verbindungsprüfung insgesamt (Forgejo: 25 s je Runde, GitLab: 15 s je Anfrage)
MAX_TEXT = 300


class AnbindungFehler(ValueError):
    """Ungültige Angabe oder nicht geschrieben – der Text geht ins Terminal (ohne Token)."""


def _ist_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _text(wert: object) -> str:
    """Für das Terminal: Steuerzeichen ersetzen, kein ``|`` (Trenner der Ausgabe), begrenzt."""
    return erkennung.fuer_terminal(wert).replace("|", "/")[:MAX_TEXT]


# ---------------------------------------------------------------- Prüfen


def server_aus_zuordnung(roh: object) -> str | None:
    """Server so, wie Erkennung und Sammler ihn aus ``runner.json`` lesen (``erkennung.lies_zuordnung``)."""
    if not isinstance(roh, str) or any(z in roh for z in "@?#"):
        return None
    return erkennung.pruefe_url(roh)


def pruefe_server(roh: object) -> tuple[str, bool]:
    """Eingabe des Servers → ``(adresse, ist_http)``. Wirft :class:`AnbindungFehler` mit Begründung."""
    if not isinstance(roh, str) or not roh.strip():
        raise AnbindungFehler("Bitte die Adresse des Servers angeben, z. B. https://git.example.org.")
    wert = roh.strip()
    if any(z.isspace() for z in wert):
        raise AnbindungFehler("Die Adresse darf keine Leerzeichen enthalten.")
    if "://" not in wert:
        raise AnbindungFehler("Bitte mit https:// angeben, z. B. https://git.example.org.")
    if "@" in wert:
        raise AnbindungFehler("Die Adresse darf keine Zugangsdaten (@) enthalten – das Token wird getrennt abgefragt.")
    if "?" in wert or "#" in wert:
        raise AnbindungFehler("Die Adresse darf keine Abfrage (?) und keinen Anker (#) enthalten.")
    adresse = erkennung.pruefe_url(wert)
    if not adresse:
        raise AnbindungFehler("Keine gültige Adresse: erwartet wird https://host[:port][/pfad].")
    pfad = urllib.parse.urlsplit(adresse).path
    if "%" in pfad or any(teil in (".", "..") for teil in pfad.split("/")):
        raise AnbindungFehler("Der Pfad der Adresse darf weder „.“, „..“ noch %-Kodierung enthalten.")
    if API_ENDE.search(pfad):
        raise AnbindungFehler("Bitte ohne /api… angeben – der Monitor hängt /api/v1 (Forgejo, Gitea) bzw. /api/v4 (GitLab) selbst an.")
    return adresse, adresse.startswith("http://")


def pruefe_org_eingabe(roh: object) -> str:
    """Organisation oder Benutzer beim Dienst (``erkennung.pruefe_org``). Wirft :class:`AnbindungFehler`."""
    org = erkennung.pruefe_org(roh)
    if not org or not isinstance(roh, str) or org != roh.strip():
        raise AnbindungFehler("Ungültige Organisation: nur A-Z a-z 0-9 . _ - (höchstens 64 Zeichen), z. B. beispiel-org.")
    return org


def pruefe_token(roh: object) -> str:
    token = roh.strip() if isinstance(roh, str) else ""
    if not TOKEN.fullmatch(token):
        raise AnbindungFehler("Das Token ist zu kurz oder enthält ungültige Zeichen.")
    return token


# ---------------------------------------------------------------- Lesen


def finde_fund(erkennung_datei: Path | None, rid: str) -> dict | None:
    """Fund mit dieser ID aus ``erkennung.json`` (streng gelesen und geprüft) oder None."""
    if not erkennung_datei:
        return None
    roh = erkennung.Quelle("/").lies(str(Path(erkennung_datei).absolute()), erkennung.MAX_ERGEBNIS)
    daten = erkennung.pruefe_ergebnis(roh) or {}
    return next((f for f in daten.get("runner", []) if f.get("id") == rid), None)


def _dienst(fund: dict | None, eintrag: dict) -> str:
    """Wie ``erkennung.wende_zuordnung_an``: ein von Hand zugeordneter Dienst hat Vorrang vor dem Fund."""
    dienst = eintrag.get("dienst") or (fund or {}).get("dienst") or "unbekannt"
    return dienst if dienst in erkennung.DIENSTE else "unbekannt"


def info(rid: str, erkennung_datei: Path | None, zuordnung_datei: Path, zugang_verz: Path) -> dict:
    """Was ``einrichten.sh zugang`` über diesen Runner wissen muss – nur geprüfte Werte, nie ein Token."""
    if not zugangsdaten.pruefe_id(rid):
        raise AnbindungFehler("Ungültige Runner-ID.")
    fund = finde_fund(erkennung_datei, rid)
    eintrag = erkennung.lies_zuordnung(zuordnung_datei).get(rid, {})
    dienst = _dienst(fund, eintrag)
    vorschlag = ""
    # Vorschlag nur aus einem Fund mit systemd-Unit (E-17/E-18) – er ist nur ein Vorschlag, den root bestätigt.
    if fund and erkennung.pruefe_unit(fund.get("unit")) and not eintrag.get("server"):
        vorschlag = server_aus_zuordnung(fund.get("server")) or ""
    return {
        "dienst": dienst,
        "gefunden": int(bool(fund)),
        "eingetragen": int(rid in erkennung.lies_zuordnung(zuordnung_datei)),
        "braucht_org": int(dienst in DIENSTE_MIT_SERVER and klasse_fuer(dienst).BRAUCHT_ORG),
        "server": eintrag.get("server", ""),
        "org": eintrag.get("org", ""),
        "http": int(eintrag.get("http_erlaubt") is True),
        "vorschlag": vorschlag,
        "token": int(bool(zugangsdaten.lies(zugangsdaten.token_pfad(zugang_verz, rid)))),
        "stand": eintrag.get("stand", ""),
    }


# ---------------------------------------------------------------- Schreiben


def setze(rid: str, zuordnung_datei: Path, zugang_verz: Path, server: str, *, org: str | None = None,
          http_erlaubt: bool = False, token: str | None = None, stand_aufheben: bool = False) -> list[tuple[str, str]]:
    """Server, Organisation und ggf. Token eines Runners setzen (nur root). Gibt Zeilen ``(art, text)``
    zurück; wirft :class:`AnbindungFehler`, wenn nichts oder nicht alles geschrieben wurde."""
    if not zugangsdaten.pruefe_id(rid):
        raise AnbindungFehler("Ungültige Runner-ID.")
    adresse, ist_http = pruefe_server(server)
    if ist_http and http_erlaubt is not True:
        raise AnbindungFehler("http:// nur mit ausdrücklicher Erlaubnis (http_erlaubt) – sonst bitte https:// angeben.")
    if org is not None:
        org = pruefe_org_eingabe(org)
    if token is not None:
        token = pruefe_token(token)

    roh = einrichtung.lies_roh(Path(zuordnung_datei))
    if roh is None:
        raise AnbindungFehler(f"{zuordnung_datei} ist nicht lesbar, kein gültiges JSON oder ein Symlink – nichts geändert.")
    runner = roh["runner"]
    alt = runner.get(rid) if isinstance(runner.get(rid), dict) else {}
    if rid not in runner and len(runner) >= einrichtung.MAX_EINTRAEGE:
        raise AnbindungFehler("Zu viele Einträge in runner.json – nichts geändert.")
    token_datei = zugangsdaten.token_pfad(zugang_verz, rid)
    token_da = bool(zugangsdaten.lies(token_datei)) or os.path.lexists(token_datei)
    neue_adresse = server_aus_zuordnung(alt.get("server")) != adresse
    if neue_adresse and token_da and token is None:
        # E-22: das bisherige Token gehört zur bisherigen Adresse und geht nie an eine neue
        raise AnbindungFehler("Die Adresse ändert sich – dafür ist ein neues Token nötig. Nichts geändert.")

    eintrag = dict(alt)
    eintrag["server"] = adresse
    if ist_http:
        eintrag["http_erlaubt"] = True
    else:
        eintrag.pop("http_erlaubt", None)
    if org is not None:
        eintrag["org"] = org
    zeilen: list[tuple[str, str]] = []
    if stand_aufheben and eintrag.get("stand") == "grund":
        del eintrag["stand"]
        zeilen.append(("ok", "Stand „Grundüberwachung“ aufgehoben – der Runner wird angebunden"))
    neu = {**roh, "version": roh.get("version", 1), "runner": {**runner, rid: eintrag}}

    # Reihenfolge (E-22): altes Token weg → runner.json → neues Token. Dazwischen gilt höchstens „kein Token“.
    nachsatz = ""  # nach dem Entfernen: der Runner hat kein Token mehr, also nicht „nichts geändert“
    if neue_adresse and token_da:
        try:
            zugangsdaten.entferne(zugang_verz, rid)
        except OSError as fehler:
            raise AnbindungFehler(f"Bisheriges Token nicht entfernt ({type(fehler).__name__}) – nichts geändert.") from None
        zeilen.append(("ok", f"bisheriges Token entfernt (gehörte zu {_text(server_aus_zuordnung(alt.get('server')) or 'keiner Adresse')})"))
        nachsatz = " Das bisherige Token wurde bereits entfernt – bitte erneut ausführen."
    try:
        einrichtung.schreibe_zuordnung(Path(zuordnung_datei), neu)
    except (einrichtung.EingabeFehler, OSError) as fehler:
        grund = type(fehler).__name__ if isinstance(fehler, OSError) else str(fehler)
        raise AnbindungFehler(f"{zuordnung_datei} nicht geschrieben ({_text(grund)}).{nachsatz}") from None
    teile = [f"Server {adresse}"] + ([f"Organisation {org}"] if org is not None else []) + (["http_erlaubt"] if ist_http else [])
    zeilen.append(("ok", f"gespeichert in {zuordnung_datei}: {_text(', '.join(teile))}"))
    if token is not None:
        try:
            zugangsdaten.schreibe(zugang_verz, rid, token, ueberschreiben=True)
        except (zugangsdaten.TokenFehler, OSError) as fehler:
            grund = getattr(fehler, "strerror", None) or type(fehler).__name__
            raise AnbindungFehler(f"Token nicht gespeichert ({_text(grund)}) – Rechte prüfen: sudo ls -ld {zugang_verz}.{nachsatz}") from None
        zeilen.append(("ok", f"Token gespeichert in {token_datei} (nur root)"))
    elif token_da:
        zeilen.append(("ok", f"Token unverändert ({token_datei}, gleiche Adresse)"))
    else:
        zeilen.append(("warn", "noch kein Token hinterlegt – ohne Token fragt der Monitor den Dienst nicht ab"))
    return zeilen


# ---------------------------------------------------------------- Verbindung prüfen


URSACHEN = ("kein-dienst", "weiterleitung")  # Feld ``ursache`` der Adapter (ForgejoFehler, GitLabFehler)


def bewerte(dienst: str, erg: dict, org: str = "") -> tuple[int, list[tuple[str, str]]]:
    """Ergebnis einer Adapter-Abfrage → (Rückgabe, Zeilen). 0 = Verbindung in Ordnung."""
    art = erg.get("abfrage")
    fehler = str(erg.get("fehler") or "")
    detail = [("hin", _text(fehler))] if fehler else []
    name = ANZEIGE.get(dienst, "Server")
    if art == "ok":
        typ = {"forgejo": "Forgejo", "gitea": "Gitea"}.get(erg.get("art"), name)
        version = erkennung.pruefe_version(erg.get("serverVersion")) if isinstance(erg.get("serverVersion"), str) else None
        zeilen = [("ok", f"Server erreichbar · {typ}{' ' + version if version else ''}")]
        if dienst == "gitlab":
            zeilen.append(("ok", "Token gültig"))
        else:
            repos = erg.get("repos") if isinstance(erg.get("repos"), list) else []
            zeilen.append(("ok", f"Token gültig, Organisation {_text(org)} gefunden, {len(repos)} Repositories"))
        runner = erg.get("runner") if isinstance(erg.get("runner"), dict) else {}
        if runner.get("zustand") in ("online", "offline"):
            zeilen.append(("ok", f"Runner beim Server gefunden ({runner['zustand']})"))
        elif dienst == "gitlab":
            zeilen.append(("warn", f"Runner bei GitLab nicht gefunden: {_text(runner.get('grund') or 'Name muss der Beschreibung bei GitLab entsprechen')}"))
        elif runner.get("ursache") == "nicht-gefunden":  # #145: Liste lesbar, Runner nicht darin
            zeilen.append(("warn", "Runner in keiner lesbaren Runner-Liste gefunden (globaler Runner ohne Recht read:admin "
                                   "oder anderer Name beim Server): Online-Status bleibt „unbekannt“, Dienst und Jobs werden "
                                   "weiter angezeigt"))
        else:
            zeilen.append(("warn", "Runner-Status nur mit Organisations-Recht (Konto im Team „Owners“): Online-Status bleibt „unbekannt“"))
        if erg.get("laeufeNichtLesbar"):
            zeilen.append(("warn", f"Läufe von {int(erg['laeufeNichtLesbar'])} Repositories nicht lesbar (Server zu alt oder ohne Rechte)"))
        return 0, zeilen
    if art == "kein-token":
        return 1, [("fehler", "Kein Token hinterlegt.")]
    if art == "token-ungueltig":
        return 1, [("fehler", "Token ungültig oder abgelaufen."), *detail]
    if art == "keine-rechte":
        text = f"Keine Rechte: Organisation {_text(org)} nicht gefunden oder das Token darf sie nicht lesen." \
            if org else "Keine Rechte: das Token darf das nicht lesen (bei GitLab: Bereich read_api)."
        return 1, [("fehler", text), *detail]
    if art == "kontingent":
        return 1, [("fehler", "API-Kontingent erschöpft – bitte später erneut prüfen."), *detail]
    if erg.get("ursache") == "weiterleitung":
        return 1, [("fehler", f"Server nicht gefunden: die Adresse leitet weiter – bitte die endgültige Adresse von {name} angeben."), *detail]
    if erg.get("ursache") == "kein-dienst":
        return 1, [("fehler", f"Server nicht gefunden: unter dieser Adresse antwortet kein {name} (Adresse prüfen)."), *detail]
    if art == "nicht-erreichbar":
        return 1, [("fehler", "Server nicht erreichbar."), *detail]
    return 1, [("fehler", "Prüfung fehlgeschlagen."), *detail]


def pruefe_verbindung(rid: str, erkennung_datei: Path | None, zuordnung_datei: Path, zugang_verz: Path,
                      frist: float = FRIST) -> tuple[int, list[tuple[str, str]]]:
    """Nur lesend: eine Abfrage des Adapters mit Server, Organisation und Token aus der Konfiguration (E-18).
    Rückgabe 0 = in Ordnung, 1 = Problem (Zeilen sagen welches), 3 = für diesen Dienst nicht möglich."""
    if not zugangsdaten.pruefe_id(rid):
        return 2, [("fehler", "Ungültige Runner-ID.")]
    fund = finde_fund(erkennung_datei, rid)
    eintrag = erkennung.lies_zuordnung(zuordnung_datei).get(rid, {})
    dienst = _dienst(fund, eintrag)
    if dienst not in DIENSTE_MIT_SERVER:
        return 3, [("warn", "Für diesen Runner gibt es keine Verbindungsprüfung auf der VM.")]
    basis = fund or {"id": rid, "name": eintrag.get("name") or rid, "unit": eintrag.get("unit"), "stand": "offen"}
    basis = {**basis, "dienst": dienst, "name": eintrag.get("name") or basis.get("name"), "unit": eintrag.get("unit") or basis.get("unit")}
    k = konfig_aus(basis, eintrag, zugang_verz)
    if not k.server:
        return 1, [("fehler", "Server fehlt in runner.json.")]
    if k.server.startswith("http://") and not k.http_erlaubt:
        return 1, [("fehler", "http:// ohne „http_erlaubt“ – der Monitor schickt das Token so nicht.")]
    ergebnis: list = []

    def lauf() -> None:
        try:
            ergebnis.append(adapter(k).abfrage({}, None))
        except Exception:  # noqa: BLE001 – Prüfung meldet, stürzt nie ab (Text ohne Token)
            ergebnis.append({"abfrage": "fehler", "fehler": "unerwarteter Fehler bei der Abfrage"})

    faden = threading.Thread(target=lauf, name="verbindung-pruefen", daemon=True)
    faden.start()
    faden.join(frist)
    if faden.is_alive() or not ergebnis:
        rc, zeilen = 1, [("fehler", f"Server nicht erreichbar (keine vollständige Antwort innerhalb von {int(frist)} s).")]
    else:
        rc, zeilen = bewerte(dienst, ergebnis[0], k.org)
    # Stand aus runner.json – erkennung.json kann bis zur nächsten Erkennung noch den alten zeigen
    stand = eintrag.get("stand") or "offen"
    if not klasse_fuer(dienst).ANBINDUNG:
        zeilen.append(("hin", f"{ANZEIGE[dienst]}: Der Monitor fragt den Dienst noch nicht regelmäßig ab – bis dahin Grundüberwachung."))
    elif not fund:
        zeilen.append(("hin", "Runner noch nicht in der Erkennung – der Sammler sucht nach dem Neustart neu."))
    elif not angebunden(k, stand):
        if stand in ("grund", "ignoriert"):
            zeilen.append(("warn", f"Stand in der Einrichtung: „{'Grundüberwachung' if stand == 'grund' else 'ignoriert'}“ – der Monitor fragt den Dienst nicht ab."))
        elif not k.unit:
            zeilen.append(("warn", "Runner ohne systemd-Unit – der Monitor fragt den Dienst nicht ab (E-18)."))
    return rc, zeilen


# ---------------------------------------------------------------- Kommandozeile für einrichten.sh


def _zeilen(zeilen: list[tuple[str, str]]) -> None:
    for art, text in zeilen:
        print(f"{art}|{_text(text)}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="runner_monitor.anbieter.anbindung", description="Server, Organisation und Token eines Runners (ohne Ausgabe des Tokens)")
    unter = p.add_subparsers(dest="befehl", required=True)
    inf = unter.add_parser("info")
    srv = unter.add_parser("pruefe-server")
    srv.add_argument("wert")
    org = unter.add_parser("pruefe-org")
    org.add_argument("wert")
    st = unter.add_parser("setze")
    st.add_argument("--server", required=True)
    st.add_argument("--org")
    st.add_argument("--http-erlaubt", action="store_true")
    st.add_argument("--stand-aufheben", action="store_true")
    st.add_argument("--token-stdin", action="store_true", help="Token aus der Standardeingabe (nie als Argument)")
    vb = unter.add_parser("pruefe-verbindung")
    vb.add_argument("--frist", type=float, default=FRIST)
    for teil in (inf, st, vb):
        teil.add_argument("--runner", required=True)
        teil.add_argument("--zuordnung", required=True)
        teil.add_argument("--zugang-verz", required=True)
    for teil in (inf, vb):
        teil.add_argument("--erkennung")
    a = p.parse_args(argv)

    if a.befehl == "pruefe-server":
        try:
            adresse, ist_http = pruefe_server(a.wert)
        except AnbindungFehler as fehler:
            print(_text(fehler))
            return 2
        print(adresse)
        return 4 if ist_http else 0
    if a.befehl == "pruefe-org":
        try:
            print(pruefe_org_eingabe(a.wert))
        except AnbindungFehler as fehler:
            print(_text(fehler))
            return 2
        return 0

    zuordnung, zugang_verz = Path(a.zuordnung), Path(a.zugang_verz)
    if a.befehl == "info":
        try:
            werte = info(a.runner, Path(a.erkennung) if a.erkennung else None, zuordnung, zugang_verz)
        except AnbindungFehler as fehler:
            print(_text(fehler))
            return 2
        for schluessel, wert in werte.items():
            print(f"{schluessel}={_text(wert)}")
        return 0
    if a.befehl == "pruefe-verbindung":
        rc, zeilen = pruefe_verbindung(a.runner, Path(a.erkennung) if a.erkennung else None, zuordnung, zugang_verz, a.frist)
        _zeilen(zeilen)
        return rc

    # setze
    if not _ist_root():
        _zeilen([("fehler", "Nur als root (sudo) – runner.json und zugang/ gehören root.")])
        return 2
    token = None
    if a.token_stdin:
        token = sys.stdin.read(zugangsdaten.MAX_TOKEN + 1)
        if len(token) > zugangsdaten.MAX_TOKEN:
            _zeilen([("fehler", "Das Token ist zu lang.")])
            return 2
    try:
        zeilen = setze(a.runner, zuordnung, zugang_verz, a.server, org=a.org, http_erlaubt=a.http_erlaubt,
                       token=token, stand_aufheben=a.stand_aufheben)
    except AnbindungFehler as fehler:
        _zeilen([("fehler", str(fehler))])
        return 2
    _zeilen(zeilen)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
