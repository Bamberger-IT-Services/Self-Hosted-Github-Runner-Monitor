"""Sammler (läuft als root): Docker-Status, GitHub-Abfrage, Update-Prüfung, Aufträge.

Warum root? Wer Docker abfragen darf, ist praktisch root, und das GitHub-Token soll nur
root lesen können. Deshalb macht der Weboberflächen-Dienst beides nicht selbst, sondern
liest nur die Ergebnisse aus ``/run/runner-monitor/*.json`` (ADR-0001, Sicherheitsbericht).

Aufträge der Oberfläche liegen als Dateien in ``/var/lib/runner-monitor/auftraege/``:

* ``github-token`` – neues Token aus der Einrichtung → nach ``/etc/runner-monitor/github-token``
* ``update``       – wird vom systemd-Pfad ``runner-monitor-update.path`` verarbeitet, nicht hier
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

from . import VERSION, github, runner
from .konfig import Konfig, lade

LOG = logging.getLogger("runner_monitor.sammler")
TAKT_DOCKER = 2
TAKT_GITHUB = 30
TAKT_RELEASE = 6 * 3600
TAKT_NICHT_BEREIT = 120  # Release ohne Paket (Workflow lädt noch hoch): bald erneut fragen (#63)
MANUELL_MIN_ABSTAND = 60  # „Jetzt prüfen“ schont das GitHub-Kontingent


def schreibe_oeffentlich(pfad: Path, daten: object) -> None:
    """Atomar schreiben, lesbar für den Monitor-Benutzer (0644). Nie Geheimnisse hier ablegen!"""
    pfad.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=pfad.parent, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False)
    os.chmod(tmp, 0o644)
    os.replace(tmp, pfad)


# ---------------------------------------------------------------- Docker

GESUNDHEIT = re.compile(r"\((healthy|unhealthy|health: starting)\)")


def deute_container(zeile: dict) -> dict | None:
    zustand = zeile.get("State", "")
    status_text = zeile.get("Status", "")
    if zustand not in ("running", "restarting", "paused"):
        # Beendete Container nur zeigen, wenn sie gerade erst beendet wurden.
        if not re.search(r"(second|minute)s? ago", status_text):
            return None
        status = "beendet"
    else:
        g = GESUNDHEIT.search(status_text)
        status = {"unhealthy": "ungesund", "health: starting": "startet"}.get(g.group(1) if g else "", "läuft")
        if zustand == "restarting":
            status = "startet"
    seit = None
    erstellt = zeile.get("CreatedAt", "")
    treffer = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) ([+-]\d{4})", erstellt)
    if treffer:
        seit = datetime.strptime(f"{treffer.group(1)} {treffer.group(2)}", "%Y-%m-%d %H:%M:%S %z").timestamp()
    return {"name": zeile.get("Names", ""), "image": zeile.get("Image", ""), "status": status, "seit": seit}


def docker_container() -> dict:
    try:
        lauf = subprocess.run(["docker", "ps", "-a", "--no-trunc", "--format", "{{json .}}"],
                              capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as fehler:
        return {"container": [], "fehler": str(fehler), "zeit": time.time()}
    liste = []
    for zeile in lauf.stdout.splitlines():
        try:
            eintrag = deute_container(json.loads(zeile))
        except ValueError:
            continue
        if eintrag:
            liste.append(eintrag)
    liste.sort(key=lambda c: c["name"])
    return {"container": liste, "fehler": lauf.stderr.strip()[:200] if lauf.returncode else "", "zeit": time.time()}


# ---------------------------------------------------------------- Sammler



def paket_bereit(release: dict) -> bool:
    """Hängen Archiv und Prüfsumme schon am Release? (ältere release.json ohne „bereit“ mitgedacht)"""
    return bool(release.get("bereit", True) and release.get("archiv") and release.get("pruefsumme"))

class Sammler:
    def __init__(self, k: Konfig) -> None:
        self.k = k
        self.letzter_erfolg: float | None = None
        self.naechste_github = 0.0
        self.naechste_release = 0.0
        self.letztes_auto_update = ""
        self.letzte_manuelle_pruefung = 0.0
        self._gh_speicher: dict = {}  # ETags und ruhige Repositories über die Durchläufe (Issue #15)
        self._gh_speicher_token: tuple[str, str] = ("", "")

    def token(self) -> str:
        try:
            return self.k.token_datei.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def org(self) -> str:
        try:
            einst = json.loads(self.k.einstellungen_datei.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            einst = {}
        return einst.get("org") or self.k.org

    def auftraege(self) -> None:
        self.auftrag_release_pruefen()
        datei = self.k.auftraege_verz / "github-token"
        if not datei.is_file():
            return
        try:
            token = json.loads(datei.read_text(encoding="utf-8")).get("token", "").strip()
        except (OSError, ValueError):
            token = ""
        datei.unlink(missing_ok=True)
        if not re.fullmatch(r"[A-Za-z0-9_]{20,255}", token):
            LOG.warning("Auftrag github-token verworfen: ungültiges Format")
            return
        self.k.token_datei.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.k.token_datei.parent, prefix=".tmp-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(token + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.k.token_datei)
        LOG.info("Neues GitHub-Token übernommen")
        self.naechste_github = 0

    def auftrag_release_pruefen(self, jetzt: float | None = None) -> None:
        """„Jetzt prüfen“ aus Info › Updates: nächste Release-Abfrage sofort, höchstens einmal je Minute."""
        datei = self.k.auftraege_verz / "release-pruefen"
        if not datei.is_file():
            return
        datei.unlink(missing_ok=True)
        jetzt = time.time() if jetzt is None else jetzt
        if jetzt - self.letzte_manuelle_pruefung < MANUELL_MIN_ABSTAND:
            return  # zu kurz hintereinander – die Oberfläche zeigt dann den letzten Stand
        self.letzte_manuelle_pruefung = jetzt
        self.naechste_release = 0.0
        LOG.info("Update-Prüfung von Hand angestoßen")

    def github(self) -> None:
        reg = runner.lies_registrierung(self.k.runner_verz)
        token, org = self.token(), self.org()
        if (token, org) != self._gh_speicher_token:  # neues Token oder andere Organisation: neu anfangen
            self._gh_speicher, self._gh_speicher_token = {}, (token, org)
        ergebnis = github.abfrage(github.Klient(token, speicher=self._gh_speicher), org, reg.get("name", ""), self.letzter_erfolg)
        if ergebnis["abfrage"] == "ok":
            self.letzter_erfolg = ergebnis["abgefragt"]
        else:
            # Bei Fehlern den letzten guten Stand stehen lassen und nur den Fehler ergänzen.
            alt = self._lies(self.k.lauf_verz / "github.json")
            if alt and alt.get("repos") and ergebnis["abfrage"] != "kein-token":
                for schluessel in ("repos", "runner", "job", "tokenAblauf"):
                    ergebnis[schluessel] = alt.get(schluessel)
                ergebnis["letzterErfolg"] = alt.get("letzterErfolg")
        schreibe_oeffentlich(self.k.lauf_verz / "github.json", ergebnis)

    def release(self) -> dict:
        klient = github.Klient(self.token())
        daten = github.neueste_version(klient, self.k.release_repo)
        daten["installiert"] = VERSION
        if github.vergleiche(daten.get("version", ""), VERSION) > 0:
            daten["aenderungen"] = github.aenderungen(klient, self.k.release_repo, VERSION, daten["version"])
        schreibe_oeffentlich(self.k.lauf_verz / "release.json", daten)
        return daten

    def auto_update(self) -> None:
        """Nachts um 3 Uhr, nur wenn eingeschaltet, eine neuere Version da ist und kein Job läuft."""
        jetzt = time.localtime()
        heute = time.strftime("%Y-%m-%d", jetzt)
        if jetzt.tm_hour != 3 or self.letztes_auto_update == heute:
            return
        einst = self._lies(self.k.einstellungen_datei) or {}
        release = self._lies(self.k.lauf_verz / "release.json") or {}
        if not einst.get("autoUpdate") or github.vergleiche(release.get("version", ""), VERSION) <= 0:
            return
        if not paket_bereit(release):
            return  # Paket wird noch hochgeladen – der Sammler fragt in 2 Minuten erneut
        if subprocess.run(["pgrep", "-f", "Runner.Worker"], capture_output=True, check=False).returncode == 0:
            return  # Job läuft – in der nächsten Minute erneut prüfen
        self.letztes_auto_update = heute
        auftrag = self.k.auftraege_verz / "update"
        auftrag.parent.mkdir(parents=True, exist_ok=True)
        auftrag.write_text(json.dumps({"version": release["version"], "zeit": time.time(), "automatisch": True}), encoding="utf-8")

    @staticmethod
    def _lies(pfad: Path):
        try:
            return json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def ein_takt(self, jetzt: float) -> None:
        self.auftraege()
        schreibe_oeffentlich(self.k.lauf_verz / "docker.json", docker_container())
        if jetzt >= self.naechste_github:
            self.naechste_github = jetzt + TAKT_GITHUB
            self.github()
        if jetzt >= self.naechste_release:
            self.naechste_release = jetzt + TAKT_RELEASE
            daten = self.release()
            if github.vergleiche(daten.get("version", ""), VERSION) > 0 and not paket_bereit(daten):
                self.naechste_release = jetzt + TAKT_NICHT_BEREIT
        self.auto_update()

    def laufe(self) -> None:  # pragma: no cover – Endlosschleife
        while True:
            try:
                self.ein_takt(time.time())
            except Exception:  # noqa: BLE001 – der Sammler darf nie stehen bleiben
                LOG.exception("Fehler im Sammler")
            time.sleep(TAKT_DOCKER)


def main() -> None:  # pragma: no cover
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(levelname)s %(name)s: %(message)s")
    if os.geteuid() != 0:
        raise SystemExit("Der Sammler muss als root laufen (systemd: runner-monitor-sammler.service).")
    Sammler(lade()).laufe()


if __name__ == "__main__":  # pragma: no cover
    main()
