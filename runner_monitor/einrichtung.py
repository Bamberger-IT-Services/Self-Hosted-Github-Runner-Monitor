"""Runner-Schritte der Einrichtung im Browser (Design 0.8.0, #96): Funde, Zuordnung und Ignorieren,
„Neu erkennen“ und „Verbindung prüfen“.

Wer was darf (E-22, Sicherheitsbericht S-EINR-01):

* Der Webserver (Benutzer ``runner-monitor``, aus dem Netz erreichbar) kann ``/etc/runner-monitor``
  nicht schreiben (``ProtectSystem=strict``). Er prüft eine Zuordnung mit :func:`pruefe_eintrag` und
  legt sie als **Auftrag** ``auftraege/runner-zuordnung`` ab. Der Sammler (root) liest den Auftrag
  streng (regulär, ohne Symlink, begrenzt), prüft jeden Eintrag **noch einmal** mit denselben Regeln
  und schreibt ``/etc/runner-monitor/runner.json`` atomar (root, Gruppe des Ordners, 0640).
* Über die Oberfläche lassen sich je Runner nur ``stand`` (``grund``, ``ignoriert`` oder „wie
  erkannt“), ``dienst``, ``name``, ``unit`` und ``log`` setzen. **Nie** ``server``, ``org``,
  ``http_erlaubt`` oder Zugangsdaten – die gehören auf die VM (``einrichten.sh zugang <runner>``,
  E-18, E-21, E-22). Alle anderen Felder in ``runner.json`` bleiben beim Schreiben unberührt.
* ``unit``: gültiger Name einer ``.service``-Unit, keine Systemdienste (Liste :data:`GESPERRTE_UNITS`).
* ``log``: nur eine ``*.log``-Datei unter ``/var/log``, ``/opt`` oder ``/srv``, ohne versteckte
  Bestandteile (also nie ``.runner`` oder ``.credentials``) und nie in den Ordnern des Monitors.
* Die Prüfung der Verbindung mit einem auf der VM hinterlegten Token macht der Sammler über den
  Adapter (Auftrag ``verbindung-pruefen``, höchstens alle 10 s); hier wird nur sein Ergebnis gelesen
  und in eine Ergebnisliste übersetzt.

Texte an die Oberfläche sind deutsch und zugleich der Schlüssel der Übersetzung in ``web/i18n.js``
(wie in ``server.py``, #81); ``tests/test_i18n.py`` liest sie auch aus dieser Datei.
"""

from __future__ import annotations

import json
import logging
import os
import re
import stat
import tempfile
import time
from pathlib import Path, PurePosixPath

from . import erkennung

LOG = logging.getLogger("runner_monitor.einrichtung")

AUFTRAG_ZUORDNUNG = "runner-zuordnung"
AUFTRAG_ERKENNUNG = "erkennung-neu"
AUFTRAG_PRUEFEN = "verbindung-pruefen"
MAX_AUFTRAG = 64 * 1024          # so groß darf ein Auftrag höchstens sein
MAX_JE_ANFRAGE = 20              # Einträge je POST
MAX_EINTRAEGE = 100              # Einträge in runner.json (mehr liest erkennung.lies_zuordnung nicht)
MAX_FUNDE = 50                   # so viele Funde zeigt die Einrichtung
WEB_SCHLUESSEL = ("stand", "dienst", "name", "unit", "log")
WEB_STAENDE = ("grund", "ignoriert")   # dazu None: „wie erkannt“ (Feld wird entfernt)
LOG_WURZELN = ("/var/log/", "/opt/", "/srv/")
LOG_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.log")
GESPERRTE_UNITS = re.compile(
    r"(?:ssh|sshd|cron|crond|atd|rsyslog|syslog|dbus|dbus-broker|getty@.*|serial-getty@.*|"
    r"ufw|firewalld|nftables|iptables|apparmor|auditd|sudo.*|login|polkit|networking|"
    r"NetworkManager.*|unattended-upgrades|apt-daily.*)\.service")


class EingabeFehler(ValueError):
    """Ungültige Zuordnung – der Text geht (übersetzt) an die Oberfläche."""


def meldung(vorlage: str, **werte: object) -> dict:
    """Text für die Oberfläche: ``text`` (deutsch, eingesetzt) und – mit Platzhaltern – ``vorlage``
    und ``werte``. Die Oberfläche übersetzt über web/i18n.js; der deutsche Text ist der Schlüssel (#81)."""
    if not werte:
        return {"text": vorlage}
    return {"text": vorlage.format(**werte), "vorlage": vorlage, "werte": {k: str(v) for k, v in werte.items()}}


# ---------------------------------------------------------------- Prüfen (Webserver und Sammler)


def pruefe_id(rid: object) -> str | None:
    if isinstance(rid, str) and rid and len(rid) <= 64 and erkennung.als_id(rid) == rid:
        return rid
    return None


def pruefe_log(pfad: object) -> str | None:
    """Log-Datei aus der Oberfläche: ``*.log`` unter ``/var/log``, ``/opt`` oder ``/srv``, ohne
    versteckte Bestandteile und nicht in den Ordnern des Monitors – sonst None."""
    sauber = erkennung.pruefe_pfad(pfad)
    if not sauber or sauber != pfad or not sauber.startswith(LOG_WURZELN):
        return None
    teile = PurePosixPath(sauber).parts[1:]
    if any(t.startswith(".") or "runner-monitor" in t.lower() for t in teile):
        return None
    return sauber if LOG_NAME.fullmatch(teile[-1]) else None


def pruefe_unit(unit: object) -> str | None:
    """Unit aus der Oberfläche: gültiger ``.service``-Name, kein Systemdienst und nicht der Monitor."""
    sauber = erkennung.pruefe_unit(unit)
    if not sauber or erkennung.AUSNAHMEN.fullmatch(sauber) or GESPERRTE_UNITS.fullmatch(sauber):
        return None
    return sauber


def unit_vorhanden(unit: str, bekannte: set[str] | frozenset[str] = frozenset(), wurzel: str = "/") -> bool:
    """Positivliste: eine Unit aus der Oberfläche muss ein Fund der Erkennung sein oder als Unit-Datei in
    den root-eigenen systemd-Verzeichnissen liegen (bei ``name@x.service`` auch die Vorlage ``name@.service``).
    So zeigt das Dashboard nie das Journal eines erfundenen oder beliebigen Namens."""
    if unit in bekannte:
        return True
    namen = [unit]
    if "@" in unit:
        namen.append(unit.split("@", 1)[0] + "@.service")
    for verz in erkennung.UNIT_VERZEICHNISSE:
        for name in namen:
            if os.path.lexists(os.path.join(wurzel, verz.lstrip("/"), name)):
                return True
    return False


def pruefe_units(eintraege: list[dict], bekannte: set[str] | frozenset[str] = frozenset(), wurzel: str = "/") -> list[dict]:
    """Einträge, deren Unit es auf der VM nicht gibt, als Fehler melden (Webserver) – siehe ``unit_vorhanden``."""
    for e in eintraege:
        if e.get("unit") and not unit_vorhanden(e["unit"], bekannte, wurzel):
            raise EingabeFehler("Diese systemd-Unit gibt es auf der VM nicht.")
    return eintraege


def bekannte_units(lauf_verz: Path) -> set[str]:
    """Units der Funde aus ``erkennung.json`` (geprüft)."""
    roh = erkennung.Quelle("/").lies(str((Path(lauf_verz) / "erkennung.json").absolute()), erkennung.MAX_ERGEBNIS)
    daten = erkennung.pruefe_ergebnis(roh) or {}
    return {u for f in daten.get("runner", []) if (u := erkennung.pruefe_unit(f.get("unit")))}


def pruefe_eintrag(roh: object) -> dict:
    """Eine Zuordnung aus der Oberfläche prüfen. ``stand`` muss da sein (``grund``, ``ignoriert``
    oder ``null`` = wie erkannt); ``dienst``, ``name``, ``unit``, ``log`` sind freiwillig, ``null`` bzw.
    leer entfernt das Feld. Unbekannte Felder (``server``, ``http_erlaubt`` …) sind ein Fehler."""
    if not isinstance(roh, dict):
        raise EingabeFehler("Ungültige Zuordnung.")
    rid = pruefe_id(roh.get("id"))
    if not rid:
        raise EingabeFehler("Ungültige Runner-ID.")
    fremd = set(roh) - {"id", *WEB_SCHLUESSEL}
    if fremd:
        raise EingabeFehler("Diese Angabe lässt sich nur auf der VM ändern.")
    if "stand" not in roh or (roh["stand"] is not None and roh["stand"] not in WEB_STAENDE):
        raise EingabeFehler("Ungültige Zuordnung.")
    eintrag: dict = {"id": rid, "stand": roh["stand"]}
    if "dienst" in roh:
        if roh["dienst"] is not None and roh["dienst"] not in erkennung.DIENSTE:
            raise EingabeFehler("Unbekannter Dienst.")
        eintrag["dienst"] = roh["dienst"]
    if "name" in roh:
        name = roh["name"]
        if name in (None, ""):
            eintrag["name"] = None
        elif not (isinstance(name, str) and erkennung.pruefe_name(name) == name):
            raise EingabeFehler("Der Anzeigename darf nur Buchstaben, Ziffern und . _ @ + - enthalten (höchstens 64 Zeichen).")
        else:
            eintrag["name"] = name
    if "unit" in roh:
        unit = roh["unit"]
        if unit in (None, ""):
            eintrag["unit"] = None
        elif not pruefe_unit(unit) or pruefe_unit(unit) != unit:
            raise EingabeFehler("Ungültige systemd-Unit: erwartet wird ein Name wie buildagent.service (keine Systemdienste).")
        else:
            eintrag["unit"] = unit
    if "log" in roh:
        log = roh["log"]
        if log in (None, ""):
            eintrag["log"] = None
        elif not pruefe_log(log):
            raise EingabeFehler("Log-Pfad nicht erlaubt: nur eine .log-Datei unter /var/log, /opt oder /srv.")
        else:
            eintrag["log"] = log
    return eintrag


def pruefe_liste(roh: object) -> list[dict]:
    """``{"runner": [Eintrag, …]}`` aus einer Anfrage: höchstens 20 Einträge, jede ID einmal."""
    if not isinstance(roh, list) or not roh or len(roh) > MAX_JE_ANFRAGE:
        raise EingabeFehler("Ungültige Zuordnung.")
    eintraege = [pruefe_eintrag(e) for e in roh]
    if len({e["id"] for e in eintraege}) != len(eintraege):
        raise EingabeFehler("Ungültige Zuordnung.")
    return eintraege


# ---------------------------------------------------------------- Aufträge


def lies_streng(pfad: Path, grenze: int = MAX_AUFTRAG) -> object | None:
    """JSON-Datei streng lesen (regulär, ohne Symlink, begrenzt) – None, wenn sie fehlt oder kaputt ist."""
    roh = erkennung.Quelle("/").lies(str(Path(pfad).absolute()), grenze)
    if roh is None:
        return None
    try:
        return json.loads(roh.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def _schreibe_privat(pfad: Path, daten: object) -> None:
    """Auftrag atomar ablegen (0600, Benutzer des Webservers)."""
    pfad.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=pfad.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(daten, f, ensure_ascii=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, pfad)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def lies_auftrag(pfad: Path) -> list[dict]:
    """Einträge eines Zuordnungs-Auftrags; ungültige werden verworfen (der Auftrag kommt vom Webserver)."""
    daten = lies_streng(pfad)
    roh = daten.get("runner") if isinstance(daten, dict) else None
    if not isinstance(roh, list):
        return []
    eintraege: dict[str, dict] = {}
    for e in roh[:MAX_EINTRAEGE]:
        try:
            gut = pruefe_eintrag(e)
        except EingabeFehler:
            continue
        eintraege[gut["id"]] = gut
    return list(eintraege.values())


def lege_auftrag(auftraege_verz: Path, eintraege: list[dict]) -> None:
    """Zuordnungen als Auftrag ablegen. Liegt noch einer (der Sammler hat ihn nicht abgeholt), werden
    die Einträge zusammengeführt – der neuere je ID gilt. Der Aufrufer hält die Sperre."""
    pfad = Path(auftraege_verz) / AUFTRAG_ZUORDNUNG
    alle = {e["id"]: e for e in lies_auftrag(pfad)}
    for e in eintraege:
        alle.pop(e["id"], None)
        alle[e["id"]] = e
    liste = list(alle.values())[-MAX_EINTRAEGE:]
    daten = {"zeit": time.time(), "runner": liste}
    if len(json.dumps(daten, ensure_ascii=False).encode("utf-8")) > MAX_AUFTRAG:
        # Sonst verwürfe der Sammler den Auftrag später still (Lesegrenze) – lieber jetzt ablehnen.
        raise EingabeFehler("Zu viele offene Änderungen. Bitte kurz warten, bis der Monitor sie übernommen hat, und erneut speichern.")
    _schreibe_privat(pfad, daten)


def lege_auftrag_einfach(auftraege_verz: Path, name: str, daten: dict | None = None) -> float:
    """Auftrag ohne Inhalt außer der Zeit (``erkennung-neu``) bzw. mit geprüfter ID (``verbindung-pruefen``)."""
    jetzt = time.time()
    _schreibe_privat(Path(auftraege_verz) / name, {"zeit": jetzt, **(daten or {})})
    return jetzt


# ---------------------------------------------------------------- runner.json (nur der Sammler)


def lies_roh(pfad: Path) -> dict | None:
    """``runner.json`` mit allen Feldern (auch denen, die die Oberfläche nicht kennt). ``{}``-Gerüst,
    wenn die Datei fehlt; None, wenn sie da, aber nicht lesbar oder kaputt ist – dann wird nichts
    überschrieben (die Datei könnte von Hand gepflegt sein)."""
    p = Path(pfad)
    if not os.path.lexists(p):
        return {"version": 1, "runner": {}}
    daten = lies_streng(p, erkennung.MAX_REGISTRIERUNG)
    if not isinstance(daten, dict) or not isinstance(daten.get("runner", {}), dict):
        return None
    return {**daten, "runner": dict(daten.get("runner") or {})}


def wende_an(roh: dict, eintraege: list[dict]) -> dict:
    """Einträge in den Inhalt von ``runner.json`` übernehmen – nur die Felder der Oberfläche; ``None``
    entfernt ein Feld, ein leerer Eintrag fällt weg. Andere Felder und Runner bleiben unberührt."""
    neu = {**roh, "version": roh.get("version", 1), "runner": {k: (dict(v) if isinstance(v, dict) else v) for k, v in roh.get("runner", {}).items()}}
    runner = neu["runner"]
    for e in eintraege:
        alt = runner.get(e["id"])
        ziel = dict(alt) if isinstance(alt, dict) else {}
        for schluessel in WEB_SCHLUESSEL:
            if schluessel not in e:
                continue
            if e[schluessel] is None:
                ziel.pop(schluessel, None)
            else:
                ziel[schluessel] = e[schluessel]
        if ziel:
            if e["id"] not in runner and len(runner) >= MAX_EINTRAEGE:
                raise EingabeFehler("Zu viele Einträge in runner.json.")
            runner[e["id"]] = ziel
        else:
            runner.pop(e["id"], None)
    return neu


def schreibe_zuordnung(pfad: Path, daten: dict) -> None:
    """``runner.json`` atomar schreiben: 0640, Besitzer der Sammler (root), Gruppe die des Ordners
    (``root:runner-monitor``) – der Webserver darf lesen, nicht schreiben. Der Ordner muss ein echtes
    Verzeichnis sein (kein Symlink); größer als die Lesegrenze der Erkennung wird die Datei nie."""
    pfad = Path(pfad)
    verz = pfad.parent
    info = os.lstat(verz)
    root = hasattr(os, "geteuid") and os.geteuid() == 0
    if not stat.S_ISDIR(info.st_mode) or (root and info.st_uid != 0):
        raise OSError(f"{verz} ist kein Verzeichnis von root")
    roh = (json.dumps(daten, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(roh) > erkennung.MAX_REGISTRIERUNG:
        raise EingabeFehler("Zu viele Einträge in runner.json.")
    fd, tmp = tempfile.mkstemp(dir=verz, prefix=".tmp-runner-")
    try:
        with os.fdopen(fd, "wb") as f:
            os.fchmod(f.fileno(), 0o640)
            if root:
                os.fchown(f.fileno(), 0, info.st_gid)
            f.write(roh)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, pfad)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def verarbeite_auftrag(auftraege_verz: Path, zuordnung_datei: Path, lauf_verz: Path | None = None, wurzel: str = "/") -> int:
    """Sammler: Zuordnungs-Auftrag abholen, prüfen, in ``runner.json`` schreiben. Gibt die Zahl der
    übernommenen Einträge zurück (0: kein Auftrag, nichts Gültiges oder nicht geschrieben)."""
    pfad = Path(auftraege_verz) / AUFTRAG_ZUORDNUNG
    arbeit = _abholen(pfad)
    if arbeit is None:
        return 0
    eintraege = lies_auftrag(arbeit)
    arbeit.unlink(missing_ok=True)
    bekannte = bekannte_units(lauf_verz) if lauf_verz else set()
    vorher = len(eintraege)
    eintraege = [e for e in eintraege if not e.get("unit") or unit_vorhanden(e["unit"], bekannte, wurzel)]
    if len(eintraege) < vorher:
        LOG.warning("Auftrag %s: %d Einträge mit unbekannter Unit verworfen", AUFTRAG_ZUORDNUNG, vorher - len(eintraege))
    if not eintraege:
        LOG.warning("Auftrag %s verworfen: keine gültigen Einträge", AUFTRAG_ZUORDNUNG)
        return 0
    roh = lies_roh(zuordnung_datei)
    if roh is None:
        LOG.warning("%s ist nicht lesbar oder kein gültiges JSON – Zuordnung aus der Oberfläche nicht übernommen", zuordnung_datei)
        return 0
    try:
        schreibe_zuordnung(zuordnung_datei, wende_an(roh, eintraege))
    except (EingabeFehler, OSError) as fehler:
        LOG.warning("Zuordnung nicht geschrieben: %s", type(fehler).__name__ if isinstance(fehler, OSError) else fehler)
        return 0
    LOG.info("Zuordnung aus der Oberfläche übernommen: %d Runner", len(eintraege))
    return len(eintraege)


def lies_einfachen_auftrag(auftraege_verz: Path, name: str) -> dict | None:
    """``erkennung-neu`` bzw. ``verbindung-pruefen`` abholen (lesen, löschen). None ohne Auftrag."""
    arbeit = _abholen(Path(auftraege_verz) / name)
    if arbeit is None:
        return None
    daten = lies_streng(arbeit, 4096)
    arbeit.unlink(missing_ok=True)
    return daten if isinstance(daten, dict) else {}


def _abholen(pfad: Path) -> Path | None:
    """Auftrag erst umbenennen, dann lesen: schreibt der Webserver währenddessen einen neuen, bleibt
    der für den nächsten Takt liegen und geht nicht mit dem Löschen verloren. Umbenannt wird der
    Verzeichniseintrag selbst (auch ein Symlink wird nicht verfolgt)."""
    if not os.path.lexists(pfad):
        return None
    arbeit = pfad.with_name(pfad.name + ".in-arbeit")
    try:
        os.replace(pfad, arbeit)
    except FileNotFoundError:
        return None
    except OSError as fehler:
        LOG.warning("Auftrag %s nicht abgeholt: %s", pfad.name, type(fehler).__name__)
        return None
    return arbeit


# ---------------------------------------------------------------- Funde für die Oberfläche (Webserver)

FUND_FELDER = ("id", "name", "dienst", "server", "version", "grad", "merkmale", "einstufung", "stand",
               "unit", "faehig", "aktiv", "grund")


def funde(lauf_verz: Path, zuordnung_datei: Path, auftraege_verz: Path, github_id: str | None,
          zugang_verz: Path | None = None) -> dict:
    """Funde aus ``erkennung.json`` (noch einmal geprüft) mit der Zuordnung aus ``runner.json`` und
    einem noch nicht abgeholten Auftrag – so sieht die Oberfläche ihre Wahl auch nach dem Neuladen.

    Ohne Pfade der Erkennung (``log``); ``zuordnung`` enthält nur die Felder der Oberfläche.
    ``primaer`` markiert den GitHub-Runner aus ``MONITOR_RUNNER_VERZ`` (nur er bekommt im Schritt
    „Anbinden“ ein Token-Feld, E-22)."""
    roh = erkennung.Quelle("/").lies(str((Path(lauf_verz) / "erkennung.json").absolute()), erkennung.MAX_ERGEBNIS)
    daten = erkennung.pruefe_ergebnis(roh)
    liste = [dict(f, merkmale=list(f.get("merkmale") or [])) for f in (daten or {}).get("runner", [])][:MAX_FUNDE]
    zuordnung = erkennung.lies_zuordnung(zuordnung_datei)
    offen = lies_auftrag(Path(auftraege_verz) / AUFTRAG_ZUORDNUNG)
    for e in offen:  # noch nicht abgeholt: so tun, als stünde er schon in runner.json
        ziel = dict(zuordnung.get(e["id"], {}))
        for s in WEB_SCHLUESSEL:
            if s in e:
                if e[s] is None:
                    ziel.pop(s, None)
                else:
                    ziel[s] = e[s]
        zuordnung[e["id"]] = ziel
    liste = erkennung.wende_zuordnung_an(liste, zuordnung)
    ergebnis = []
    for f in liste:
        eintrag = {k: f.get(k) for k in FUND_FELDER}
        z = zuordnung.get(f["id"], {})
        eintrag["zuordnung"] = {k: z[k] for k in WEB_SCHLUESSEL if k in z}
        eintrag["primaer"] = bool(github_id) and f["id"] == github_id and f.get("dienst") == "github"
        eintrag["anbindung"] = "github" if eintrag["primaer"] else anbindung(f, zuordnung, zugang_verz)
        if "stand" not in z and eintrag["stand"] in ("grund", "ignoriert"):
            # Die Erkennung selbst kennt nur „angebunden“ und „offen“; grund/ignoriert stammen aus einer
            # inzwischen zurückgenommenen Zuordnung. Bis der Sammler neu erkannt hat: „offen“.
            eintrag["stand"] = "offen"
        ergebnis.append(eintrag)
    return {"zeit": (daten or {}).get("zeit"), "runner": ergebnis,
            "auftrag": {"erkennung": os.path.lexists(Path(auftraege_verz) / AUFTRAG_ERKENNUNG),
                        "zuordnung": bool(offen)}}


# ---------------------------------------------------------------- Verbindung prüfen (Ergebnis des Sammlers)


def verbindung_aus(gh: dict | None, seit: float | None = None) -> dict:
    """Ergebnis der letzten Abfrage des GitHub-Adapters (``github.json``) als Ergebnisliste für
    „Verbindung prüfen“. ``fertig`` ist False, solange keine Abfrage nach ``seit`` vorliegt."""
    gh = gh if isinstance(gh, dict) else {}
    abgefragt = gh.get("abgefragt") if isinstance(gh.get("abgefragt"), (int, float)) else None
    if seit is not None and (abgefragt is None or abgefragt < seit):
        return {"fertig": False, "ok": False, "ergebnisse": []}
    art = gh.get("abfrage")
    org = str(gh.get("org") or "")
    if art == "ok":
        ablauf = gh.get("tokenAblauf") if isinstance(gh.get("tokenAblauf"), (int, float)) else None
        repos = gh.get("repos") if isinstance(gh.get("repos"), list) else []
        zeilen = [{"ok": True, **(meldung("Token gültig, läuft ab am {d}", d=time.strftime("%d.%m.%Y", time.localtime(ablauf)))
                                  if ablauf else meldung("Token gültig, ohne Ablaufdatum")), "ablauf": ablauf},
                  {"ok": True, **meldung("Organisation {org} gefunden, {n} Repositories", org=org, n=len(repos))}]
        zustand = (gh.get("runner") or {}).get("zustand") if isinstance(gh.get("runner"), dict) else None
        if zustand in ("online", "offline"):
            zeilen.append({"ok": True, "text": "Self-hosted runners: lesen (Online-Status wird angezeigt)"})
        else:
            zeilen.append({"warn": True, "text": "Self-hosted runners fehlt: Online-Status bleibt „unbekannt“ (optional)"})
        return {"fertig": True, "ok": True, "ergebnisse": zeilen}
    texte = {
        "kein-token": meldung("Auf der VM ist noch kein Token hinterlegt. Token links eingeben oder auf der VM eintragen."),
        "token-ungueltig": meldung("Token ungültig oder abgelaufen."),
        "keine-rechte": meldung("Organisation {org} nicht gefunden oder kein Zugriff.", org=org) if org else meldung("Token ohne Zugriff."),
        "nicht-erreichbar": meldung("GitHub ist von der VM aus nicht erreichbar."),
        "kontingent": meldung("API-Kontingent erschöpft, bitte später erneut prüfen."),
    }
    zeile = {"fehler": True, **texte.get(art, meldung("Prüfung fehlgeschlagen."))}
    if art == "fehler" and not org:
        zeile = {"fehler": True, **meldung("Organisation fehlt. Bitte links eingeben.")}
    return {"fertig": True, "ok": False, "ergebnisse": [zeile]}


def anbindung(fund: dict, zuordnung: dict, zugang_verz: Path | None) -> str:
    """Wie fragt der Sammler diesen Runner ab? ``angebunden`` (Adapter, Unit, Server und – wenn nötig –
    Organisation aus runner.json, #93), ``ohne-server`` (Adapter da, aber Server/Organisation fehlen) oder
    ``ohne-adapter`` (Grundüberwachung). Der GitHub-Runner des Monitors hat seinen eigenen Weg."""
    from . import anbieter  # spät: anbieter importiert erkennung und runner

    k = anbieter.konfig_aus(fund, zuordnung.get(fund.get("id")), zugang_verz)
    if anbieter.angebunden(k, fund.get("stand")):
        return "angebunden"
    if anbieter.klasse_fuer(k.dienst).ANBINDUNG and k.dienst != "github":
        return "ohne-server"
    return "ohne-adapter"


def verbindung_anbieter(erg: dict | None, seit: float | None = None) -> dict:
    """Ergebnis der letzten Abfrage eines weiteren Adapters (Forgejo/Gitea, ``anbieter.json`` › ``runner.<id>``)
    als Ergebnisliste im Muster von :func:`verbindung_aus`. Server, Organisation und Token stammen aus
    ``runner.json`` bzw. ``zugang/`` auf der VM (E-18, E-22)."""
    erg = erg if isinstance(erg, dict) else {}
    abgefragt = erg.get("abgefragt") if isinstance(erg.get("abgefragt"), (int, float)) else None
    if seit is not None and (abgefragt is None or abgefragt < seit):
        return {"fertig": False, "ok": False, "ergebnisse": []}
    art = erg.get("abfrage")
    if art == "ausstehend":  # neu angebunden, die erste Runde des Sammlers läuft noch (E-25, #115)
        return {"fertig": False, "ok": False, "ergebnisse": []}
    org = str(erg.get("org") or "")
    if art == "ok":
        dienst = {"forgejo": "Forgejo", "gitea": "Gitea"}.get(erg.get("art"), "Server")
        version = erkennung.pruefe_version(erg.get("serverVersion")) if erg.get("serverVersion") else None
        repos = erg.get("repos") if isinstance(erg.get("repos"), list) else []
        zeilen = [{"ok": True, **(meldung("Server erreichbar · {dienst} {version}", dienst=dienst, version=version)
                                  if version else meldung("Server erreichbar · {dienst}", dienst=dienst))},
                  {"ok": True, **meldung("Token gültig, Organisation {org} gefunden, {n} Repositories", org=org, n=len(repos))}]
        zustand = (erg.get("runner") or {}).get("zustand") if isinstance(erg.get("runner"), dict) else None
        if zustand in ("online", "offline"):
            zeilen.append({"ok": True, "text": "Runner beim Server gefunden (Online-Status wird angezeigt)"})
        else:
            zeilen.append({"warn": True, "text": "Runner-Status nur mit Organisations-Recht: Online-Status bleibt „unbekannt“"})
        return {"fertig": True, "ok": True, "ergebnisse": zeilen}
    texte = {
        "kein-token": meldung("Auf der VM ist noch kein Token hinterlegt. Bitte mit dem Befehl links eintragen."),
        "token-ungueltig": meldung("Token ungültig oder abgelaufen."),
        "keine-rechte": meldung("Organisation {org} nicht gefunden oder kein Zugriff.", org=org) if org else meldung("Token ohne Zugriff."),
        "nicht-erreichbar": meldung("Der Server ist von der VM aus nicht erreichbar."),
        "kontingent": meldung("API-Kontingent erschöpft, bitte später erneut prüfen."),
    }
    return {"fertig": True, "ok": False, "ergebnisse": [{"fehler": True, **texte.get(art, meldung("Prüfung fehlgeschlagen."))}]}


def ohne_server() -> dict:
    """„Verbindung prüfen“ für einen Runner mit Adapter, dem Server oder Organisation in runner.json fehlen."""
    return {"fertig": True, "ok": False, "ergebnisse": [
        {"warn": True, "text": "Server und Organisation fehlen in /etc/runner-monitor/runner.json – siehe Anleitung zu einrichten.sh zugang."}]}


def ohne_abfrage() -> dict:
    """„Verbindung prüfen“ für einen Runner, den der Sammler (noch) nicht abfragt – ehrlich statt grün."""
    return {"fertig": True, "ok": False, "ergebnisse": [
        {"warn": True, "text": "Für diesen Runner fragt der Monitor den Dienst noch nicht ab – er läuft mit Grundüberwachung."}]}
