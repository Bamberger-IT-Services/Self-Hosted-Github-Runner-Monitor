"""Update-Hilfsdienst (läuft als root, ADR-0004).

Wird von ``runner-monitor-update.path`` gestartet, sobald die Oberfläche einen Auftrag
``/var/lib/runner-monitor/auftraege/update`` ablegt. Der Auftrag enthält nur die Zielversion –
woher das Archiv kommt, bestimmt dieser Dienst selbst: aus ``/run/runner-monitor/release.json``,
das der root-Sammler vom offiziellen Release-Repository geholt hat.

Ablauf (die Nummern sind die Schritte, die die Oberfläche anzeigt):

1. Archiv und Prüfsumme herunterladen (nur https://github.com/<release-repo>/releases/…)
2. SHA-256 prüfen, dann die Herkunft: ``gh attestation verify`` bestätigt, dass das Archiv vom
   Release-Workflow dieses Repositorys gebaut wurde (GitHub-Attestierung/Sigstore, ADR-0005)
3. nach ``/opt/runner-monitor/versionen/<version>`` entpacken, ``aktuell`` umhängen
4. ``runner-monitor`` und ``runner-monitor-sammler`` neu starten
5. ``/api/health`` muss binnen 30 s die neue Version melden – sonst zurück zur alten

Aufruf von Hand: ``python3 -m runner_monitor.aktualisierer [--zurueck]``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

from . import VERSION, konfig as konfig_modul
from .konfig import Konfig

LOG = logging.getLogger("runner_monitor.aktualisierer")
BASIS = Path(os.environ.get("MONITOR_INSTALL_VERZ", "/opt/runner-monitor"))
DIENSTE = ("runner-monitor-sammler", "runner-monitor")
BEHALTEN = 3  # so viele Versionen bleiben liegen (für „zurück“)
VERSION_MUSTER = re.compile(r"^\d+\.\d+\.\d+$")


HERKUNFT_WORKFLOW = ".github/workflows/release.yml"


def herkunft_pruefen(k: Konfig, archiv: Path) -> str:
    """Prüft die GitHub-Attestierung des Archivs. Ergebnis „geprüft“ oder „nicht geprüft (Grund)“.

    MONITOR_UPDATE_HERKUNFT: ``pflicht`` – ohne erfolgreiche Prüfung kein Update;
    sonst (Vorgabe) wird geprüft, sobald die GitHub-CLI und ein Token da sind. Eine Prüfung, die
    läuft und scheitert, bricht das Update immer ab.
    """
    pflicht = k.update_herkunft == "pflicht"
    gh = shutil.which("gh")
    try:
        token = k.token_datei.read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    grund = "GitHub-CLI fehlt" if not gh else "kein GitHub-Token" if not token else ""
    if grund:
        if pflicht:
            raise UpdateFehler(2, f"Herkunft nicht prüfbar ({grund}) – MONITOR_UPDATE_HERKUNFT=pflicht")
        LOG.warning("Herkunft des Updates nicht geprüft: %s (nur Prüfsumme)", grund)
        return f"nicht geprüft ({grund})"
    befehl = [gh, "attestation", "verify", str(archiv), "--repo", k.release_repo,
              "--signer-workflow", f"{k.release_repo}/{HERKUNFT_WORKFLOW}"]
    umgebung = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/root", "GH_TOKEN": token, "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1"}
    try:
        lauf = subprocess.run(befehl, capture_output=True, text=True, timeout=90, env=umgebung, check=False)
    except (OSError, subprocess.SubprocessError) as fehler:
        raise UpdateFehler(2, f"Herkunftsprüfung lief nicht: {fehler}") from fehler
    if lauf.returncode != 0:
        letzte = (lauf.stderr or lauf.stdout).strip().splitlines()[-1:] or [""]
        raise UpdateFehler(2, f"Herkunft nicht bestätigt – Archiv verworfen ({letzte[0][:200]})")
    return "geprüft"


class UpdateFehler(Exception):
    def __init__(self, schritt: int, text: str) -> None:
        super().__init__(text)
        self.schritt = schritt


def status(k: Konfig, **daten) -> None:
    """update-status.json schreiben (lesbar für den Monitor, 0644)."""
    daten.setdefault("zeit", time.time())
    pfad = k.update_status_datei
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_suffix(".tmp")
    tmp.write_text(json.dumps(daten, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, 0o644)
    os.replace(tmp, pfad)


def erlaubte_url(url: str, repo: str) -> bool:
    return url.startswith(f"https://github.com/{repo}/releases/download/")


def lade(url: str, ziel: Path, max_bytes: int = 50 * 1024 * 1024) -> None:
    anfrage = urllib.request.Request(url, headers={"User-Agent": f"runner-monitor/{VERSION}"})
    with urllib.request.urlopen(anfrage, timeout=60) as antwort, open(ziel, "wb") as datei:  # noqa: S310 – nur https, geprüft
        gelesen = 0
        while True:
            block = antwort.read(65536)
            if not block:
                break
            gelesen += len(block)
            if gelesen > max_bytes:
                raise UpdateFehler(1, "Archiv ist unerwartet groß")
            datei.write(block)


def sha256(pfad: Path) -> str:
    h = hashlib.sha256()
    with open(pfad, "rb") as datei:
        for block in iter(lambda: datei.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def entpacke(archiv: Path, ziel: Path) -> None:
    """Entpackt nur reguläre Dateien und Ordner unterhalb von ``ziel`` (keine Links, kein ``..``)."""
    with tarfile.open(archiv, "r:gz") as tar:
        mitglieder = []
        for m in tar.getmembers():
            teile = Path(m.name).parts
            if not teile or m.name.startswith("/") or ".." in teile or not (m.isfile() or m.isdir()):
                raise UpdateFehler(3, f"unzulässiger Eintrag im Archiv: {m.name}")
            # Oberste Ebene „runner-monitor-X.Y.Z/“ abschneiden
            if len(teile) == 1:
                continue
            m.name = str(Path(*teile[1:]))
            m.mode = 0o755 if m.isdir() or m.mode & 0o111 else 0o644
            m.uid = m.gid = 0
            m.uname = m.gname = "root"
            mitglieder.append(m)
        ziel.mkdir(parents=True)
        if sys.version_info >= (3, 12):
            tar.extractall(ziel, members=mitglieder, filter="data")
        else:  # pragma: no cover – Ubuntu 22.04
            tar.extractall(ziel, members=mitglieder)  # noqa: S202 – Mitglieder oben geprüft


def aktuelle_version() -> str:
    try:
        return (BASIS / "aktuell").resolve().name
    except OSError:
        return ""


def haenge_um(version: str) -> None:
    neu = BASIS / "aktuell.neu"
    neu.unlink(missing_ok=True)
    neu.symlink_to(Path("versionen") / version)
    os.replace(neu, BASIS / "aktuell")


def neustart() -> None:
    subprocess.run(["systemctl", "restart", *DIENSTE], check=False, timeout=60)


def gesund(k: Konfig, version: str, warten: int = 30) -> bool:
    url = f"http://127.0.0.1:{k.port}/api/health"
    ende = time.time() + warten
    while time.time() < ende:
        try:
            with urllib.request.urlopen(url, timeout=3) as antwort:  # noqa: S310 – lokal
                if json.loads(antwort.read()).get("version") == version:
                    return True
        except (OSError, ValueError):
            pass
        time.sleep(1)
    return False


def aufraeumen() -> None:
    verz = BASIS / "versionen"
    aktiv = aktuelle_version()
    alle = sorted((p for p in verz.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
    for alt in alle[BEHALTEN:]:
        if alt.name != aktiv:
            shutil.rmtree(alt, ignore_errors=True)


def aktualisiere(k: Konfig, ziel: str) -> None:
    release = json.loads((k.lauf_verz / "release.json").read_text(encoding="utf-8"))
    if release.get("version") != ziel or not VERSION_MUSTER.match(ziel):
        raise UpdateFehler(1, f"Version {ziel} ist nicht das neueste offizielle Release")
    archiv_url, summe_url = release.get("archiv", ""), release.get("pruefsumme", "")
    if not (erlaubte_url(archiv_url, k.release_repo) and erlaubte_url(summe_url, k.release_repo)):
        raise UpdateFehler(1, "Release enthält kein Archiv mit Prüfsumme")
    alt = aktuelle_version()
    with tempfile.TemporaryDirectory(prefix="runner-monitor-update-") as tmp:
        status(k, zustand="laeuft", schritt=1, version=ziel)
        archiv, summe = Path(tmp) / "archiv.tar.gz", Path(tmp) / "archiv.sha256"
        try:
            lade(archiv_url, archiv)
            lade(summe_url, summe, max_bytes=4096)
        except OSError as fehler:
            raise UpdateFehler(1, f"Download fehlgeschlagen: {fehler}") from fehler
        status(k, zustand="laeuft", schritt=2, version=ziel)
        erwartet = summe.read_text(encoding="utf-8").split()[0].lower() if summe.stat().st_size else ""
        if not re.fullmatch(r"[0-9a-f]{64}", erwartet) or sha256(archiv) != erwartet:
            raise UpdateFehler(2, "Prüfsumme stimmt nicht – Archiv verworfen")
        herkunft = herkunft_pruefen(k, archiv)
        status(k, zustand="laeuft", schritt=3, version=ziel)
        ziel_verz = BASIS / "versionen" / ziel
        if ziel_verz.exists():
            shutil.rmtree(ziel_verz)
        entpacke(archiv, ziel_verz)
    haenge_um(ziel)
    status(k, zustand="laeuft", schritt=4, version=ziel)
    neustart()
    status(k, zustand="laeuft", schritt=5, version=ziel)
    if not gesund(k, ziel):
        if alt:
            haenge_um(alt)
            neustart()
        raise UpdateFehler(5, "die neue Version hat nach dem Neustart nicht geantwortet")
    status(k, zustand="erfolg", version=ziel, vorher=alt, herkunft=herkunft)
    aufraeumen()


def zurueck(k: Konfig) -> str:
    """Zur zuletzt installierten anderen Version zurück."""
    aktiv = aktuelle_version()
    andere = sorted((p for p in (BASIS / "versionen").iterdir() if p.is_dir() and p.name != aktiv), key=lambda p: p.stat().st_mtime, reverse=True)
    if not andere:
        raise SystemExit("Keine frühere Version vorhanden.")
    haenge_um(andere[0].name)
    neustart()
    status(k, zustand="erfolg", version=andere[0].name, vorher=aktiv, zurueck=True)
    return andere[0].name


def main(argv: list[str] | None = None) -> int:  # pragma: no cover – nur auf der VM
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    argv = sys.argv[1:] if argv is None else argv
    if os.geteuid() != 0:
        print("Der Update-Dienst braucht root.", file=sys.stderr)
        return 2
    k = konfig_modul.lade()
    if "--zurueck" in argv:
        print(f"Zurück auf Version {zurueck(k)}.")
        return 0
    auftrag = k.auftraege_verz / "update"
    if not auftrag.exists():
        return 0
    try:
        ziel = str(json.loads(auftrag.read_text(encoding="utf-8")).get("version", ""))
    except (OSError, ValueError):
        ziel = ""
    auftrag.unlink(missing_ok=True)
    if vergleiche_sicher(ziel, aktuelle_version() or VERSION) <= 0:
        LOG.info("Version %s ist nicht neuer als die installierte – nichts zu tun", ziel)
        return 0
    try:
        aktualisiere(k, ziel)
        LOG.info("Aktualisiert auf %s", ziel)
        return 0
    except UpdateFehler as fehler:
        LOG.error("Update auf %s fehlgeschlagen (Schritt %s): %s", ziel, fehler.schritt, fehler)
        status(k, zustand="fehler", schritt=fehler.schritt, version=ziel, meldung=str(fehler))
        return 1
    except Exception as fehler:  # noqa: BLE001 – jeder Fehler muss in der Oberfläche landen
        LOG.exception("Update auf %s fehlgeschlagen", ziel)
        status(k, zustand="fehler", schritt=1, version=ziel, meldung=f"unerwarteter Fehler: {fehler}")
        return 1


def vergleiche_sicher(a: str, b: str) -> int:
    from .github import vergleiche
    return vergleiche(a, b) if VERSION_MUSTER.match(a or "") else -1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
