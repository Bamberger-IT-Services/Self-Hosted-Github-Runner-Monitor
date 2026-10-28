"""Sammler (läuft als root): Docker-Status, GitHub-Abfrage, Update-Prüfung, Runner-Erkennung, Aufträge.

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
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from . import VERSION, erkennung, github, runner
from .konfig import Konfig, lade

LOG = logging.getLogger("runner_monitor.sammler")
TAKT_DOCKER = 2
TAKT_GITHUB = 30
TAKT_RELEASE = 6 * 3600
TAKT_ERKENNUNG = 6 * 3600  # Runner auf der VM erkennen: beim Start und alle 6 Stunden (#91)
MAX_STDERR = 2000         # so viel Fehlerausgabe der Erkennung kommt ins Journal
ERKENNUNG_FRIST = 60      # harte Grenze für einen Erkennungslauf (eigener Prozess)
PAKET_WURZEL = Path(__file__).resolve().parent.parent
AUTO_FENSTER = (3, 7)     # automatisches Update: ab 3 Uhr, spätestens bis 7 Uhr (#77)
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
        self.naechste_erkennung = 0.0
        self._erkennung: tuple | None = None  # (Prozess, Ausgabedatei, Startzeit) der laufenden Erkennung
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

    def erkennung_befehl(self) -> list[str]:
        return [sys.executable, "-m", "runner_monitor.erkennung", "--json",
                "--runner-verz", str(self.k.runner_verz), "--zuordnung", str(self.k.zuordnung_datei),
                "--token-datei", str(self.k.token_datei)]

    def erkennung(self, jetzt: float | None = None) -> None:
        """Runner auf der VM erkennen (#91) → ``erkennung.json``, beim Start und alle 6 Stunden.

        Läuft als root, weil ``.runner`` von Forgejo/Gitea und ``config.toml`` von GitLab meist nur
        für root lesbar sind; Tokens daraus landen nie im Ergebnis (die Datei ist 0644).

        Die Erkennung läuft als **eigener Prozess** und blockiert den Sammler nie: dieser Takt startet
        ihn, die folgenden Takte schauen nach. Nach ``ERKENNUNG_FRIST`` Sekunden wird er beendet
        (hängender DNS-Server, tröpfelnder Server, hängendes ``systemctl``). Die Ausgabe geht in eine
        temporäre Datei (kein volles Pipe) und wird geprüft, bevor sie geschrieben wird."""
        jetzt = time.monotonic() if jetzt is None else jetzt  # Frist und Takt unabhängig von Uhr-Sprüngen (#109)
        if self._erkennung is None:
            if jetzt < self.naechste_erkennung:
                return
            self.naechste_erkennung = jetzt + TAKT_ERKENNUNG
            ausgabe = tempfile.TemporaryFile()
            fehler_ausgabe = tempfile.TemporaryFile()
            try:
                prozess = subprocess.Popen(
                    self.erkennung_befehl(), stdin=subprocess.DEVNULL, stdout=ausgabe, stderr=fehler_ausgabe,
                    cwd=PAKET_WURZEL, close_fds=True,
                    env={"PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"), "LANG": "C.UTF-8",
                         "PYTHONPATH": str(PAKET_WURZEL), "PYTHONDONTWRITEBYTECODE": "1"})
            except OSError as fehler:
                ausgabe.close()
                fehler_ausgabe.close()
                LOG.warning("Runner-Erkennung nicht gestartet: %s", fehler)
                return
            self._erkennung = (prozess, ausgabe, jetzt, fehler_ausgabe)
            return
        prozess, ausgabe, start, fehler_ausgabe = self._erkennung
        if prozess.poll() is None:
            if jetzt - start < ERKENNUNG_FRIST:
                return
            prozess.kill()
            try:
                prozess.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            ausgabe.close()
            self._erkennung = None
            self._logge_stderr(fehler_ausgabe)
            LOG.warning("Runner-Erkennung nach %s s abgebrochen – nächster Versuch in 6 Stunden", ERKENNUNG_FRIST)
            return
        self._erkennung = None
        try:
            ausgabe.seek(0)
            roh = ausgabe.read(erkennung.MAX_ERGEBNIS + 1)
        finally:
            ausgabe.close()
        daten = erkennung.pruefe_ergebnis(roh) if prozess.returncode == 0 else None
        if daten is None or prozess.returncode:
            self._logge_stderr(fehler_ausgabe)
        else:
            fehler_ausgabe.close()
        if daten is None:
            LOG.warning("Runner-Erkennung ohne gültiges Ergebnis (Rückgabe %s)", prozess.returncode)
            return
        schreibe_oeffentlich(self.k.lauf_verz / "erkennung.json", daten)

    @staticmethod
    def _logge_stderr(datei) -> None:
        """stderr des Erkennungsprozesses (höchstens ``MAX_STDERR`` Byte) ins Journal, dann schließen."""
        try:
            datei.seek(0)
            text = datei.read(MAX_STDERR).decode("utf-8", "replace").strip()
        except (OSError, ValueError):
            text = ""
        finally:
            datei.close()
        if text:
            LOG.warning("Runner-Erkennung, Fehlerausgabe: %s", " ".join(text.split())[:MAX_STDERR])

    @staticmethod
    def _job_laeuft() -> bool:
        return subprocess.run(["pgrep", "-f", "Runner.Worker"], capture_output=True, check=False).returncode == 0

    def auto_update(self, jetzt: float | None = None) -> None:
        """Automatisches Update (#77): ab 3 Uhr vorgemerkt, gestartet, sobald kein Job läuft – bis
        spätestens 7 Uhr, danach erst in der nächsten Nacht. Höchstens ein Versuch je Nacht.

        Der Stand liegt in ``auto-update.json`` im Laufzeitordner (übersteht den Neustart des Sammlers
        durch das Update selbst, damit ein fehlgeschlagener Versuch nicht jede Minute wiederkommt)
        und wird in Info › Updates angezeigt. Das Update startet nur die Monitor-Dienste neu, der
        Runner und ein laufender Job bleiben unberührt."""
        jetzt = time.time() if jetzt is None else jetzt
        t = time.localtime(jetzt)
        nacht = time.strftime("%Y-%m-%d", t)
        datei = self.k.lauf_verz / "auto-update.json"
        stand = self._lies(datei) or {}
        einst = self._lies(self.k.einstellungen_datei) or {}
        release = self._lies(self.k.lauf_verz / "release.json") or {}
        version = release.get("version", "")
        faellig = bool(einst.get("autoUpdate")) and github.vergleiche(version, VERSION) > 0
        if not faellig:
            if stand:
                schreibe_oeffentlich(datei, {})
            return
        if not AUTO_FENSTER[0] <= t.tm_hour < AUTO_FENSTER[1]:
            if stand.get("zustand") == "vorgemerkt":
                # Die ganze Nacht lief ein Job: nächste Nacht erneut
                schreibe_oeffentlich(datei, {**stand, "zustand": "verschoben"})
            return
        if stand.get("nacht") == nacht and stand.get("zustand") == "gestartet":
            return  # heute schon versucht
        if not paket_bereit(release):
            return  # Paket wird noch hochgeladen – der Sammler fragt in 2 Minuten erneut
        if self._job_laeuft():
            if stand.get("zustand") != "vorgemerkt" or stand.get("nacht") != nacht or stand.get("version") != version:
                schreibe_oeffentlich(datei, {"nacht": nacht, "version": version, "zustand": "vorgemerkt", "seit": jetzt})
                LOG.info("Automatisches Update auf %s vorgemerkt – startet, sobald kein Job läuft", version)
            return  # in der nächsten Minute erneut prüfen
        schreibe_oeffentlich(datei, {"nacht": nacht, "version": version, "zustand": "gestartet", "seit": jetzt})
        auftrag = self.k.auftraege_verz / "update"
        auftrag.parent.mkdir(parents=True, exist_ok=True)
        auftrag.write_text(json.dumps({"version": version, "zeit": jetzt, "automatisch": True}), encoding="utf-8")
        LOG.info("Automatisches Update auf %s gestartet", version)

    @staticmethod
    def _lies(pfad: Path):
        try:
            return json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def ein_takt(self, jetzt: float, mono: float | None = None) -> None:
        self.auftraege()
        schreibe_oeffentlich(self.k.lauf_verz / "docker.json", docker_container())
        try:
            self.erkennung(mono)
        except Exception:  # noqa: BLE001 – die Erkennung darf GitHub und Docker nie aufhalten
            LOG.exception("Fehler bei der Runner-Erkennung")
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
