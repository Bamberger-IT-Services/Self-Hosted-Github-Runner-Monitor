"""Zugangsdaten je Runner: ``/etc/runner-monitor/zugang/<runner>.token`` (Design 0.8.0, #92, E-19).

* Verzeichnis ``zugang/`` gehört root, Rechte 0700; jede Datei 0600 – nur der Sammler (root) liest sie.
  Der Webserver (Benutzer ``runner-monitor``) kann weder lesen noch auflisten. Zugangsdaten gehen nie
  über die Weboberfläche; gesetzt werden sie mit ``sudo einrichten.sh zugang <runner>``.
* Dateiname ist die ``id`` des Runners (Erkennung, ``erkennung.als_id``): nur ``a-z 0-9 . _ -``,
  höchstens 64 Zeichen, nie mit Punkt oder Minus am Anfang – kein Pfad, kein „..“.
* Gelesen wird wie in der Erkennung: nur reguläre Dateien, ohne Symlinks, höchstens 4 KB.
* **Übernahme (Migration):** Das bisherige GitHub-Token (``/etc/runner-monitor/github-token``) wird
  beim Start des Sammlers nach ``zugang/<id>.token`` **kopiert**. Eine vorhandene Kopie bleibt, außer
  der alte Ort ist neuer und anders (z. B. nach ``einrichten.sh zurueck`` und einem Token-Wechsel mit
  der älteren Version) – dann wird sie atomar ersetzt. Der alte Ort bleibt als Rückfall, bis #94/#96
  abgeschlossen sind – ältere Versionen und der Update-Hilfsdienst lesen nur ihn. Wer das Token über
  die alten Wege erneuert (Einrichtung im Browser, ``einrichten.sh token``), schreibt beide Orte;
  scheitert das Schreiben nach ``zugang/``, wird die veraltete Kopie entfernt (es gilt der alte Ort).

Kommandozeile (für ``einrichten.sh``, gibt nie ein Token aus)::

    python3 -m runner_monitor.anbieter.token github-id --runner-verz /opt/actions-runner
    python3 -m runner_monitor.anbieter.token kopiere --alt /etc/runner-monitor/github-token \\
        --verz /etc/runner-monitor/zugang --runner-verz /opt/actions-runner [--ueberschreiben]
    python3 -m runner_monitor.anbieter.token liste --erkennung /run/runner-monitor/erkennung.json \
        [--runner-verz /opt/actions-runner]

Rückgabe: 0 = erledigt (gibt die ID bzw. die Liste aus), 3 = nichts zu tun, 2 = Fehler.
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
import tempfile
from pathlib import Path

from .. import erkennung, runner

MAX_TOKEN = 4096
VERZ_RECHTE = 0o700
DATEI_RECHTE = 0o600


class TokenFehler(Exception):
    pass


def pruefe_id(rid: object) -> str | None:
    """Gültige Runner-ID (wie aus der Erkennung) oder None."""
    if isinstance(rid, str) and rid and erkennung.als_id(rid) == rid and rid not in (".", ".."):
        return rid
    return None


def token_pfad(verz: Path, rid: str) -> Path:
    if not pruefe_id(rid):
        raise TokenFehler(f"ungültige Runner-ID: {rid!r}")
    return Path(verz) / f"{rid}.token"


def github_id(runner_verz: Path) -> str | None:
    """ID des GitHub-Runners aus ``MONITOR_RUNNER_VERZ`` (Registrierung ``.runner``), wie die Erkennung sie vergibt."""
    name = erkennung.pruefe_name(runner.lies_registrierung(Path(runner_verz)).get("name"))
    return erkennung.als_id(name) if name else None


def lies(pfad: Path | None) -> str:
    """Token aus ``zugang/`` lesen – streng (regulär, ohne Symlink, begrenzt). Leer, wenn es fehlt."""
    if not pfad:
        return ""
    roh = erkennung.Quelle("/").lies(str(Path(pfad).absolute()), MAX_TOKEN)
    if roh is None:
        return ""
    try:
        return roh.decode("utf-8").strip()
    except UnicodeDecodeError:
        return ""


def lies_rueckfall(pfad: Path | None) -> str:
    """Alter Ort (``/etc/runner-monitor/github-token``) – genau wie bis 0.7 gelesen."""
    if not pfad:
        return ""
    try:
        return Path(pfad).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def _verz_bereit(verz: Path) -> None:
    """``zugang/`` anlegen bzw. prüfen: echtes Verzeichnis, gehört diesem Benutzer (root), 0700."""
    verz = Path(verz)
    try:
        os.mkdir(verz, VERZ_RECHTE)
    except FileExistsError:
        pass
    info = os.lstat(verz)
    if not stat.S_ISDIR(info.st_mode):
        raise TokenFehler(f"{verz} ist kein Verzeichnis")
    if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
        raise TokenFehler(f"{verz} gehört nicht diesem Benutzer")
    if stat.S_IMODE(info.st_mode) != VERZ_RECHTE:
        os.chmod(verz, VERZ_RECHTE)


def schreibe(verz: Path, rid: str, token: str, ueberschreiben: bool = True) -> bool:
    """Token atomar ablegen (0600). Ohne ``ueberschreiben`` bleibt eine vorhandene Datei unberührt
    (``os.link`` schlägt dann fehl) – Ergebnis False. Wirft TokenFehler bei ungültiger ID oder Token."""
    ziel = token_pfad(verz, rid)
    token = (token or "").strip()
    if not token or len(token) > MAX_TOKEN - 1 or any(z.isspace() or not z.isprintable() for z in token):
        raise TokenFehler("Token leer oder mit ungültigen Zeichen")
    _verz_bereit(Path(verz))
    fd, tmp = tempfile.mkstemp(dir=verz, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            os.fchmod(f.fileno(), DATEI_RECHTE)  # mkstemp legt 0600 an, sicher ist sicher
            f.write(token + "\n")
            f.flush()
            os.fsync(f.fileno())
        if ueberschreiben:
            os.replace(tmp, ziel)
            return True
        try:
            os.link(tmp, ziel)  # atomar und nie über eine vorhandene Datei
        except FileExistsError:
            return False
        return True
    finally:
        Path(tmp).unlink(missing_ok=True)


def _mtime(pfad: Path, folgen: bool) -> float | None:
    try:
        return (os.stat(pfad) if folgen else os.lstat(pfad)).st_mtime
    except (OSError, ValueError):
        return None


def migriere(alt: Path, verz: Path, rid: str | None) -> bool:
    """Bisheriges Token nach ``zugang/<rid>.token`` übernehmen (Kopie; der alte Ort bleibt).

    * Fehlt die Kopie, wird sie angelegt (``os.link``, überschreibt nie eine gleichzeitig angelegte).
    * Gibt es sie, bleibt sie – außer der alte Ort ist **neuer** und hat ein anderes Token: dann ist
      die Kopie veraltet und wird atomar ersetzt (``os.replace``).

    True, wenn jetzt geschrieben wurde. Nichts zu tun (False): kein Runner, kein altes Token, Kopie
    aktuell. Schreibfehler (``TokenFehler``, ``OSError``) gehen an den Aufrufer – der entscheidet,
    ob er die veraltete Kopie entfernt."""
    if not pruefe_id(rid):
        return False
    token = lies_rueckfall(alt)
    if not token:
        return False
    ziel = token_pfad(verz, rid)  # type: ignore[arg-type]
    neu_zeit = _mtime(ziel, folgen=False)
    if neu_zeit is None:
        return schreibe(verz, rid, token, ueberschreiben=False)  # type: ignore[arg-type]
    alt_zeit = _mtime(alt, folgen=True)
    if alt_zeit is None or alt_zeit <= neu_zeit or lies(ziel) == token:
        return False
    return schreibe(verz, rid, token, ueberschreiben=True)  # type: ignore[arg-type]


def entferne(verz: Path, rid: str | None) -> bool:
    """Veraltete Kopie entfernen (nach einem Schreibfehler) – danach gilt der alte Ort."""
    if not pruefe_id(rid):
        return False
    try:
        token_pfad(verz, rid).unlink()  # type: ignore[arg-type]
    except FileNotFoundError:
        return False
    return True


# ---------------------------------------------------------------- Kommandozeile für einrichten.sh


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="runner_monitor.anbieter.token", description="Zugangsdaten je Runner (ohne Ausgabe des Tokens)")
    unter = p.add_subparsers(dest="befehl", required=True)
    gid = unter.add_parser("github-id", help="ID des GitHub-Runners ausgeben")
    gid.add_argument("--runner-verz", required=True)
    kop = unter.add_parser("kopiere", help="altes GitHub-Token nach zugang/<id>.token kopieren")
    kop.add_argument("--alt", required=True)
    kop.add_argument("--verz", required=True)
    kop.add_argument("--runner-verz", required=True)
    kop.add_argument("--ueberschreiben", action="store_true")
    lis = unter.add_parser("liste", help="erkannte Runner (ID, Dienst, Name) aus erkennung.json")
    lis.add_argument("--erkennung", required=True)
    lis.add_argument("--runner-verz", help="markiert den GitHub-Runner aus MONITOR_RUNNER_VERZ")
    a = p.parse_args(argv)
    if a.befehl == "liste":
        daten = erkennung.pruefe_ergebnis(erkennung.Quelle("/").lies(str(Path(a.erkennung).absolute()), erkennung.MAX_ERGEBNIS))
        funde = [f for f in (daten or {}).get("runner", []) if f.get("stand") != "ignoriert"]
        gid = github_id(Path(a.runner_verz)) if a.runner_verz else None
        for f in funde:
            zusatz = "  ← GitHub-Runner des Monitors (schreibt auch github-token)" if f["id"] == gid else ""
            print(f"  {erkennung.fuer_terminal(f['id'])[:40]:<40} {erkennung.ANZEIGE.get(f['dienst'], 'unbekannt'):<10} "
                  f"{erkennung.fuer_terminal(f.get('name') or '')[:28]}{zusatz}")
        return 0 if funde else 3
    rid = github_id(Path(a.runner_verz))
    if a.befehl == "github-id":
        if not rid:
            return 3
        print(rid)
        return 0
    if not rid:
        return 3
    try:
        if not a.ueberschreiben:
            if not migriere(Path(a.alt), Path(a.verz), rid):
                return 3
        else:
            token = lies_rueckfall(Path(a.alt))
            if not token:
                return 3
            schreibe(Path(a.verz), rid, token, ueberschreiben=True)
    except (TokenFehler, OSError) as fehler:
        # Kopie wäre jetzt veraltet: entfernen, damit der alte Ort gilt. Meldung ohne Token.
        try:
            entferne(Path(a.verz), rid)
        except OSError:
            pass
        print(f"Fehler: {type(fehler).__name__}: {getattr(fehler, 'strerror', None) or fehler}", file=sys.stderr)
        print(rid)
        return 2
    print(rid)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
