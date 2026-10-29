"""Sammler (läuft als root): Docker-Status, GitHub-Abfrage, Abfrage weiterer Dienste (Forgejo/Gitea, #93),
Update-Prüfung, Runner-Erkennung, Aufträge.

Warum root? Wer Docker abfragen darf, ist praktisch root, und das GitHub-Token soll nur
root lesen können. Deshalb macht der Weboberflächen-Dienst beides nicht selbst, sondern
liest nur die Ergebnisse aus ``/run/runner-monitor/*.json`` (ADR-0001, Sicherheitsbericht).

Aufträge der Oberfläche liegen als Dateien in ``/var/lib/runner-monitor/auftraege/``:

* ``github-token`` – neues Token aus der Einrichtung → nach ``/etc/runner-monitor/github-token`` und
  ``/etc/runner-monitor/zugang/<runner>.token`` (#92, E-19)
* ``runner-zuordnung`` – Zuordnung/Ignorieren aus der Einrichtung → ``/etc/runner-monitor/runner.json``
  (noch einmal geprüft, nur die Felder der Oberfläche, 0640; danach neu erkennen – #96, E-22)
* ``erkennung-neu`` – „Neu erkennen“: Erkennung sofort, höchstens alle 10 s (#96)
* ``verbindung-pruefen`` – „Verbindung prüfen“: nächste Abfrage des GitHub-Adapters sofort, höchstens
  alle 10 s; das Ergebnis steht wie immer in ``github.json`` (#96)
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
import threading
import time
from datetime import datetime
from pathlib import Path

from . import VERSION, anbieter, einrichtung, erkennung, github, runner
from .anbieter import github as gh_adapter
from .anbieter import token as zugangsdaten
from .konfig import Konfig, lade

LOG = logging.getLogger("runner_monitor.sammler")
TAKT_DOCKER = 2
TAKT_GITHUB = 30
TAKT_ANBIETER = 30        # weitere Dienste (Forgejo, Gitea): wie GitHub alle 30 s
MAX_ANBINDUNGEN = 20      # höchstens so viele Runner fragt der Sammler beim Dienst ab (wie runner[] im Monitor)
TAKT_RELEASE = 6 * 3600
TAKT_ERKENNUNG = 6 * 3600  # Runner auf der VM erkennen: beim Start und alle 6 Stunden (#91)
MAX_STDERR = 2000         # so viel Fehlerausgabe der Erkennung kommt ins Journal
ERKENNUNG_FRIST = 60      # harte Grenze für einen Erkennungslauf (eigener Prozess)
PAKET_WURZEL = Path(__file__).resolve().parent.parent
AUTO_FENSTER = (3, 7)     # automatisches Update: ab 3 Uhr, spätestens bis 7 Uhr (#77)
TAKT_NICHT_BEREIT = 120  # Release ohne Paket (Workflow lädt noch hoch): bald erneut fragen (#63)
MANUELL_MIN_ABSTAND = 60  # „Jetzt prüfen“ schont das GitHub-Kontingent
ERKENNUNG_MIN_ABSTAND = 10  # „Neu erkennen“ aus der Einrichtung: höchstens alle 10 s (#96)
PRUEFEN_MIN_ABSTAND = 10    # „Verbindung prüfen“ aus der Einrichtung: höchstens alle 10 s (#96)


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
        self.letzte_manuelle_erkennung = float("-inf")  # monotonic
        self.letzte_verbindungspruefung = float("-inf")
        self._erkennung_nochmal = False  # Anforderung während eines Laufs: danach gleich noch einmal
        self._gh_speicher: dict = {}  # ETags und ruhige Repositories über die Durchläufe (Issue #15)
        self._gh_speicher_token: tuple[str, str] = ("", "")
        self._token_migriert = False  # Übernahme des alten GitHub-Tokens nach zugang/ (#92), einmal je Start
        self.naechste_anbieter = 0.0
        self._anbieter_speicher: dict[str, tuple[tuple, dict]] = {}  # je Runner: (Schlüssel, Speicher der Abfrage)
        self._anbieter_erfolg: dict[str, float] = {}
        self._anbieter_faden: threading.Thread | None = None  # Abfrage weiterer Dienste läuft neben ein_takt

    def github_adapter(self) -> gh_adapter.GitHub:
        """Adapter des GitHub-Runners aus ``MONITOR_RUNNER_VERZ`` – Server, Organisation und Token aus
        der Konfiguration, nie aus der Erkennung (E-18)."""
        reg = runner.lies_registrierung(self.k.runner_verz)
        name = reg.get("name", "")
        rid = zugangsdaten.github_id(self.k.runner_verz) or ""
        return gh_adapter.GitHub(gh_adapter.konfig_fuer(name, rid, None, self.org(), self.k.runner_verz,
                                                        self.k.zugang_verz, self.k.token_datei))

    def token(self) -> str:
        """GitHub-Token: ``zugang/<runner>.token``, sonst der alte Ort (Rückfall bis #94/#96)."""
        return self.github_adapter().token()

    def migriere_token(self) -> None:
        """Bestehendes GitHub-Token nach ``zugang/<runner>.token`` kopieren (E-19), einmal je Start.

        Fehlt die Kopie, wird sie angelegt; ist der alte Ort neuer und anders, wird sie ersetzt.
        Der alte Ort bleibt (Rückfall, Update-Hilfsdienst, ältere Versionen). Gibt es noch keinen
        registrierten Runner, versucht der Sammler es im nächsten Takt erneut."""
        if self._token_migriert:
            return
        rid = zugangsdaten.github_id(self.k.runner_verz)
        if not rid:
            return
        self._token_migriert = True
        ziel = zugangsdaten.token_pfad(self.k.zugang_verz, rid)
        try:
            if zugangsdaten.migriere(self.k.token_datei, self.k.zugang_verz, rid):
                LOG.info("GitHub-Token nach %s übernommen (alter Ort bleibt)", ziel)
        except (zugangsdaten.TokenFehler, OSError) as fehler:
            self._zugang_verwerfen(rid, f"GitHub-Token nicht nach {ziel} übernommen: {type(fehler).__name__}")

    def _zugang_verwerfen(self, rid: str, grund: str) -> None:
        """Nach einem Schreibfehler die (dann veraltete) Kopie entfernen – es gilt der alte Ort."""
        try:
            entfernt = zugangsdaten.entferne(self.k.zugang_verz, rid)
        except OSError:
            entfernt = False
        LOG.warning("%s – %s; es gilt %s", grund, "veraltete Kopie entfernt" if entfernt else "keine Kopie vorhanden",
                    self.k.token_datei)

    def org(self) -> str:
        try:
            einst = json.loads(self.k.einstellungen_datei.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            einst = {}
        return einst.get("org") or self.k.org

    def auftraege(self) -> None:
        self.auftrag_release_pruefen()
        try:
            self.auftrag_einrichtung()
        except Exception:  # noqa: BLE001 – ein kaputter Auftrag darf das Token nicht aufhalten
            LOG.exception("Auftrag aus der Einrichtung nicht verarbeitet")
        datei = self.k.auftraege_verz / "github-token"
        if not os.path.lexists(datei):
            return
        # Wie alle Aufträge streng lesen: regulär, ohne Symlink, begrenzt (der Ordner gehört dem Webserver).
        auftrag = einrichtung.lies_streng(datei, 4096)
        token = auftrag.get("token", "") if isinstance(auftrag, dict) else ""
        token = token.strip() if isinstance(token, str) else ""
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
        # Auch je Runner ablegen (E-19): sonst gälte eine ältere Kopie in zugang/ weiter.
        rid = zugangsdaten.github_id(self.k.runner_verz)
        if rid:
            try:
                zugangsdaten.schreibe(self.k.zugang_verz, rid, token)
            except (zugangsdaten.TokenFehler, OSError) as fehler:
                self._zugang_verwerfen(rid, f"Neues GitHub-Token nicht nach zugang/ geschrieben: {type(fehler).__name__}")
        LOG.info("Neues GitHub-Token übernommen")
        self.naechste_github = 0

    def auftrag_einrichtung(self, jetzt: float | None = None, mono: float | None = None) -> None:
        """Aufträge aus der Einrichtung (#96): Zuordnung schreiben, neu erkennen, Verbindung prüfen."""
        jetzt = time.time() if jetzt is None else jetzt
        mono = time.monotonic() if mono is None else mono
        if einrichtung.verarbeite_auftrag(self.k.auftraege_verz, self.k.zuordnung_datei):
            self.erkennung_anfordern(mono)  # erkennung.json übernimmt Ignorieren und Zuordnung
        if einrichtung.lies_einfachen_auftrag(self.k.auftraege_verz, einrichtung.AUFTRAG_ERKENNUNG) is not None:
            LOG.info("Runner-Erkennung von Hand angestoßen")
            self.erkennung_anfordern(mono)
        auftrag = einrichtung.lies_einfachen_auftrag(self.k.auftraege_verz, einrichtung.AUFTRAG_PRUEFEN)
        if auftrag is not None:
            rid = zugangsdaten.github_id(self.k.runner_verz)
            if not rid or auftrag.get("id") != rid:
                return  # andere Runner fragt der Sammler noch nicht ab (die Oberfläche sagt das selbst)
            start = max(jetzt, self.letzte_verbindungspruefung + PRUEFEN_MIN_ABSTAND)
            self.letzte_verbindungspruefung = start
            self.naechste_github = min(self.naechste_github, start)

    def erkennung_anfordern(self, mono: float | None = None) -> None:
        """Erkennung bald starten – frühestens 10 s nach der letzten Anforderung; läuft gerade eine,
        dann gleich nach ihr (sie hat die neue Zuordnung womöglich noch nicht gelesen)."""
        mono = time.monotonic() if mono is None else mono
        if self._erkennung is not None:
            self._erkennung_nochmal = True
            return
        start = max(mono, self.letzte_manuelle_erkennung + ERKENNUNG_MIN_ABSTAND)
        self.letzte_manuelle_erkennung = start
        self.naechste_erkennung = min(self.naechste_erkennung, start)

    def _erkennung_beendet(self, mono: float) -> None:
        if self._erkennung_nochmal:
            self._erkennung_nochmal = False
            self.erkennung_anfordern(mono)

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
        adapter = self.github_adapter()
        token, org = adapter.token(), adapter.k.org
        if (token, org) != self._gh_speicher_token:  # neues Token oder andere Organisation: neu anfangen
            self._gh_speicher, self._gh_speicher_token = {}, (token, org)
        ergebnis = adapter.abfrage(self._gh_speicher, self.letzter_erfolg, token=token)
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

    def anbindungen(self) -> list[anbieter.Anbieter]:
        """Runner, die der Sammler außer dem GitHub-Runner beim Dienst abfragt (#93): erkannt (mit Unit),
        Dienst mit Adapter (Forgejo, Gitea), Server und Organisation in ``runner.json``, nicht
        „grund“/„ignoriert“. Server, Organisation und Token kommen nie aus dem Fund (E-18)."""
        roh = erkennung.Quelle("/").lies(str((self.k.lauf_verz / "erkennung.json").absolute()), erkennung.MAX_ERGEBNIS)
        daten = erkennung.pruefe_ergebnis(roh)
        zuordnung = erkennung.lies_zuordnung(self.k.zuordnung_datei)
        liste: list[anbieter.Anbieter] = []
        for fund in (daten or {}).get("runner", []):
            k = anbieter.konfig_aus(fund, zuordnung.get(fund["id"]), self.k.zugang_verz)
            if anbieter.angebunden(k, fund.get("stand")) and len(liste) < MAX_ANBINDUNGEN:
                liste.append(anbieter.adapter(k))
        return liste

    def anbieter_abfragen(self) -> None:
        """Je angebundenem Runner eine Abfrage → ``/run/runner-monitor/anbieter.json`` (0644, ohne Token).

        Bei Fehlern bleibt wie bei GitHub der letzte gute Stand (Repositories, Runner, Job) stehen."""
        alt = (self._lies(self.k.lauf_verz / "anbieter.json") or {}).get("runner") or {}
        neu: dict[str, dict] = {}
        for a in self.anbindungen():
            token = a.token()
            schluessel = (a.k.server, a.k.org, a.k.name, token)
            gemerkt = self._anbieter_speicher.get(a.k.id)
            speicher = gemerkt[1] if gemerkt and gemerkt[0] == schluessel else {}  # neues Token/Ziel: neu anfangen
            self._anbieter_speicher[a.k.id] = (schluessel, speicher)
            try:
                ergebnis = a.abfrage(speicher, self._anbieter_erfolg.get(a.k.id), token=token)
            except Exception:  # noqa: BLE001 – ein Dienst darf die anderen nie aufhalten
                LOG.exception("Abfrage von %s fehlgeschlagen", a.k.id)
                continue
            if ergebnis["abfrage"] == "ok":
                self._anbieter_erfolg[a.k.id] = ergebnis["abgefragt"]
            else:
                vorher = alt.get(a.k.id) if isinstance(alt.get(a.k.id), dict) else {}
                if vorher.get("repos") and ergebnis["abfrage"] != "kein-token":
                    for feld in ("repos", "runner", "job", "letzteJobs", "art", "serverVersion"):
                        ergebnis[feld] = vorher.get(feld)
                    ergebnis["letzterErfolg"] = vorher.get("letzterErfolg")
            neu[a.k.id] = ergebnis
        for rid in set(self._anbieter_speicher) - set(neu):
            self._anbieter_speicher.pop(rid, None)
            self._anbieter_erfolg.pop(rid, None)
        if neu or alt:
            schreibe_oeffentlich(self.k.lauf_verz / "anbieter.json", {"zeit": time.time(), "runner": neu})

    def _anbieter_sicher(self) -> None:
        try:
            self.anbieter_abfragen()
        except Exception:  # noqa: BLE001 – Forgejo/Gitea dürfen den Sammler nie aufhalten
            LOG.exception("Fehler bei der Abfrage weiterer Dienste")

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
            self._erkennung_beendet(jetzt)
            return
        self._erkennung = None
        self._erkennung_beendet(jetzt)
        try:
            ausgabe.seek(0)
            roh = ausgabe.read(erkennung.MAX_ERGEBNIS + 1)
        except BaseException:
            fehler_ausgabe.close()
            raise
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
        try:
            self.migriere_token()
        except Exception:  # noqa: BLE001 – die Übernahme darf den Sammler nie aufhalten
            LOG.exception("Übernahme des GitHub-Tokens fehlgeschlagen")
        self.auftraege()
        schreibe_oeffentlich(self.k.lauf_verz / "docker.json", docker_container())
        try:
            self.erkennung(mono)
        except Exception:  # noqa: BLE001 – die Erkennung darf GitHub und Docker nie aufhalten
            LOG.exception("Fehler bei der Runner-Erkennung")
        if jetzt >= self.naechste_github:
            self.naechste_github = jetzt + TAKT_GITHUB
            self.github()
        if jetzt >= self.naechste_anbieter and not (self._anbieter_faden and self._anbieter_faden.is_alive()):
            # Eigener Faden: ein hängender oder tröpfelnder Forgejo-/Gitea-Server hält GitHub, Docker,
            # Erkennung und Updates nie auf. Läuft die vorige Runde noch, wartet die nächste.
            self.naechste_anbieter = jetzt + TAKT_ANBIETER
            self._anbieter_faden = threading.Thread(target=self._anbieter_sicher, name="anbieter-abfrage", daemon=True)
            self._anbieter_faden.start()
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
