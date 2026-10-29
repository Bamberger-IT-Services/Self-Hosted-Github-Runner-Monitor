"""Konfiguration aus ``/etc/runner-monitor/konfig.env`` und Umgebungsvariablen.

Format der Datei: ``SCHLUESSEL=wert`` je Zeile, ``#`` leitet einen Kommentar ein.
Umgebungsvariablen gehen der Datei vor. Alle Schlüssel stehen in ``deploy/konfig.env.example``.
Fehlerhafte Werte brechen den Start mit einer klaren Meldung ab (Anweisung 02).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

KONFIG_DATEI = Path("/etc/runner-monitor/konfig.env")
PAKET_VERZ = Path(__file__).resolve().parent


class KonfigFehler(ValueError):
    """Ungültige Konfiguration – der Dienst startet nicht."""


@dataclass(frozen=True)
class Konfig:
    adresse: str = "0.0.0.0"
    port: int = 8090
    org: str = ""
    runner_verz: Path = Path("/opt/actions-runner")
    daten_verz: Path = Path("/var/lib/runner-monitor")
    lauf_verz: Path = Path("/run/runner-monitor")
    token_datei: Path = Path("/etc/runner-monitor/github-token")
    web_verz: Path = PAKET_VERZ.parent / "web"
    schwelle_frei_gb: int = 25
    release_repo: str = "Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor"
    vm_name: str = ""
    # Nur für die Entwicklung auf dem Mac: keine Anmeldung, nur 127.0.0.1, Demo-Daten erlaubt.
    entwicklung: bool = False
    https: bool = False  # hinter einem TLS-Proxy: Cookies mit Secure, HSTS (docs/HTTPS.md)
    update_herkunft: str = ""  # „pflicht“: Update nur mit bestätigter GitHub-Attestierung (ADR-0005)
    # Woher Updates kommen (#138, ADR-0007): „github“ (Vorgabe) oder „forgejo“ mit Basis-Adresse; http://
    # nur mit ausdrücklicher Freigabe (wie E-21). Das Repository ist auf beiden MONITOR_RELEASE_REPO.
    update_quelle: str = "github"
    update_forgejo: str = ""
    update_http_erlaubt: bool = False
    weitere: dict = field(default_factory=dict)

    @property
    def zugang_datei(self) -> Path:
        return self.daten_verz / "zugang.json"

    @property
    def sitzungen_datei(self) -> Path:
        return self.daten_verz / "sitzungen.json"

    @property
    def sperren_datei(self) -> Path:
        return self.daten_verz / "sperren.json"

    @property
    def einrichtungscode_datei(self) -> Path:
        return self.daten_verz / "einrichtungscode.json"

    @property
    def einstellungen_datei(self) -> Path:
        return self.daten_verz / "einstellungen.json"

    @property
    def zuordnung_datei(self) -> Path:
        """Zuordnung und Ignorieren der erkannten Runner (#91), neben dem Token, nur root schreibt."""
        return self.token_datei.parent / "runner.json"

    @property
    def zugang_verz(self) -> Path:
        """Zugangsdaten je Runner (#92, E-19): ``<id>.token``, Verzeichnis root 0700, Dateien 0600."""
        return self.token_datei.parent / "zugang"

    @property
    def auftraege_verz(self) -> Path:
        return self.daten_verz / "auftraege"

    @property
    def update_status_datei(self) -> Path:
        return self.daten_verz / "update-status.json"


_SCHLUESSEL = re.compile(r"^[A-Z][A-Z0-9_]*$")


def lies_env_datei(pfad: Path) -> dict[str, str]:
    werte: dict[str, str] = {}
    if not pfad.is_file():
        return werte
    for nr, zeile in enumerate(pfad.read_text(encoding="utf-8").splitlines(), start=1):
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#"):
            continue
        if "=" not in zeile:
            raise KonfigFehler(f"{pfad}:{nr}: erwartet SCHLUESSEL=wert")
        schluessel, wert = zeile.split("=", 1)
        schluessel = schluessel.strip()
        if not _SCHLUESSEL.match(schluessel):
            raise KonfigFehler(f"{pfad}:{nr}: ungültiger Schlüssel {schluessel!r}")
        werte[schluessel] = wert.strip().strip('"').strip("'")
    return werte


def _ganzzahl(werte: dict[str, str], name: str, vorgabe: int, mini: int, maxi: int) -> int:
    roh = werte.get(name)
    if roh in (None, ""):
        return vorgabe
    try:
        zahl = int(roh)
    except ValueError as fehler:
        raise KonfigFehler(f"{name} muss eine Zahl sein, gefunden: {roh!r}") from fehler
    if not mini <= zahl <= maxi:
        raise KonfigFehler(f"{name} muss zwischen {mini} und {maxi} liegen, gefunden: {zahl}")
    return zahl


JA = ("1", "ja", "true")


def update_quelle(werte: dict[str, str]) -> tuple[str, str, bool]:
    """MONITOR_UPDATE_QUELLE, MONITOR_UPDATE_FORGEJO, MONITOR_UPDATE_HTTP_ERLAUBT prüfen (#138, ADR-0007).

    Die Basis-Adresse muss ``https://host[:port][/pfad]`` sein, ohne Zugangsdaten, Abfrage und Anker;
    ``http://`` nur mit MONITOR_UPDATE_HTTP_ERLAUBT=1. Ein Fehler hält den Start an (Anweisung 02) –
    ``einrichten.sh quelle`` prüft vor dem Schreiben mit denselben Regeln."""
    quelle = (werte.get("MONITOR_UPDATE_QUELLE", "") or "github").strip().lower()
    if quelle not in ("github", "forgejo"):
        raise KonfigFehler(f"MONITOR_UPDATE_QUELLE muss github oder forgejo sein, gefunden: {quelle!r}")
    if quelle == "github":
        return quelle, "", False  # Forgejo-Werte gelten nur mit MONITOR_UPDATE_QUELLE=forgejo
    http_erlaubt = werte.get("MONITOR_UPDATE_HTTP_ERLAUBT", "").strip().lower() in JA
    roh = werte.get("MONITOR_UPDATE_FORGEJO", "").strip()
    forgejo = ""
    if roh:
        from .erkennung import pruefe_url  # spät: nur wenn gesetzt (Standardbibliothek, ohne Paket-Importe)
        # pruefe_url lässt Zugangsdaten, Abfrage und Anker still weg – hier sind sie ein Fehler
        forgejo = "" if any(z in roh for z in "@?#") else pruefe_url(roh) or ""
        if not forgejo:
            raise KonfigFehler("MONITOR_UPDATE_FORGEJO muss eine Adresse wie https://git.example.org sein "
                               f"(ohne Zugangsdaten, Abfrage und Anker), gefunden: {roh!r}")
        if forgejo.startswith("http://") and not http_erlaubt:
            raise KonfigFehler("MONITOR_UPDATE_FORGEJO mit http:// nur zusammen mit MONITOR_UPDATE_HTTP_ERLAUBT=1 "
                               "(Updates kämen sonst ungeschützt durchs Netz – lieber https://)")
    if not forgejo:
        raise KonfigFehler("MONITOR_UPDATE_QUELLE=forgejo braucht MONITOR_UPDATE_FORGEJO=https://…")
    return quelle, forgejo, http_erlaubt


def lade(datei: Path | None = None, umgebung: dict[str, str] | None = None) -> Konfig:
    werte = lies_env_datei(datei if datei is not None else KONFIG_DATEI)
    umgebung = dict(os.environ if umgebung is None else umgebung)
    for schluessel, wert in umgebung.items():
        if schluessel.startswith("MONITOR_"):
            werte[schluessel] = wert

    org = werte.get("MONITOR_ORG", "")
    if org and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", org):
        raise KonfigFehler(f"MONITOR_ORG ist kein gültiger GitHub-Name: {org!r}")
    repo = werte.get("MONITOR_RELEASE_REPO", Konfig.release_repo)
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", repo):
        raise KonfigFehler(f"MONITOR_RELEASE_REPO muss besitzer/repo sein, gefunden: {repo!r}")

    entwicklung = werte.get("MONITOR_ENTWICKLUNG", "") in ("1", "ja", "true")
    adresse = werte.get("MONITOR_ADRESSE", "127.0.0.1" if entwicklung else "0.0.0.0")
    if entwicklung and adresse not in ("127.0.0.1", "::1", "localhost"):
        raise KonfigFehler("MONITOR_ENTWICKLUNG ist nur mit MONITOR_ADRESSE=127.0.0.1 erlaubt")

    quelle, forgejo, http_erlaubt = update_quelle(werte)

    def pfad(name: str, vorgabe: Path) -> Path:
        roh = werte.get(name)
        return Path(roh) if roh else vorgabe

    return Konfig(
        adresse=adresse,
        port=_ganzzahl(werte, "MONITOR_PORT", 8090, 1, 65535),
        org=org,
        runner_verz=pfad("MONITOR_RUNNER_VERZ", Konfig.runner_verz),
        daten_verz=pfad("MONITOR_DATEN_VERZ", Konfig.daten_verz),
        lauf_verz=pfad("MONITOR_LAUF_VERZ", Konfig.lauf_verz),
        token_datei=pfad("MONITOR_TOKEN_DATEI", Konfig.token_datei),
        web_verz=pfad("MONITOR_WEB_VERZ", Konfig.web_verz),
        schwelle_frei_gb=_ganzzahl(werte, "MONITOR_SCHWELLE_FREI_GB", 25, 1, 10000),
        release_repo=repo,
        vm_name=werte.get("MONITOR_VM_NAME", ""),
        entwicklung=entwicklung,
        https=werte.get("MONITOR_HTTPS", "") in ("1", "ja", "true"),
        update_herkunft=werte.get("MONITOR_UPDATE_HERKUNFT", "").strip().lower(),
        update_quelle=quelle,
        update_forgejo=forgejo,
        update_http_erlaubt=http_erlaubt,
        weitere={k: v for k, v in werte.items() if not k.startswith("MONITOR_")},
    )
