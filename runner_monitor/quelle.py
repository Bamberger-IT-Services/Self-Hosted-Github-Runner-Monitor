"""Update-Quelle (#138, ADR-0007): GitHub (Vorgabe) oder ein Forgejo-Server.

Der root-Sammler fragt die Quelle alle 6 Stunden nach dem neuesten Release und schreibt
``/run/runner-monitor/release.json``; der Update-Hilfsdienst lädt Archiv und Prüfsumme nur von genau
dieser Quelle. Für GitHub bleibt alles wie bisher (``github.neueste_version``, Downloads unter
``https://github.com/<repo>/releases/download/``). Für Forgejo gilt:

* Basis-Adresse aus ``MONITOR_UPDATE_FORGEJO`` (konfig.env, nur root schreibt), das Repository wie bei
  GitHub aus ``MONITOR_RELEASE_REPO``. **Kein Token**: Release-API und Downloads eines öffentlichen
  Repositorys brauchen keine Anmeldung, auf der VM liegt dafür kein Geheimnis.
* ``https://`` Pflicht, ``http://`` nur mit ``MONITOR_UPDATE_HTTP_ERLAUBT=1`` (wie E-21) und dann ohne
  Proxy aus der Umgebung.
* **Keiner Weiterleitung folgen** (API und Downloads). Die Download-Adressen baut der Monitor selbst aus
  Basis, Repository, Tag ``vX.Y.Z`` und festem Dateinamen; ``browser_download_url`` aus der Antwort wird
  nur als „Paket hängt am Release“ gewertet, nie aufgerufen.
* Herkunft wie bei GitHub mit ``gh attestation verify`` gegen das GitHub-Repository: Die Attestierung
  hängt am SHA-256 des Archivs, nicht am Ort des Downloads (ADR-0005, ADR-0007).

Aufruf von ``einrichten.sh quelle`` (alle Ausgaben ohne Geheimnisse)::

    python3 -m runner_monitor.quelle zeige --konfig /etc/runner-monitor/konfig.env
    python3 -m runner_monitor.quelle pruefe-adresse -- https://git.example.org   # 0 ok, 4 http://, 2 ungültig
    python3 -m runner_monitor.quelle abfrage --basis https://git.example.org [--http-erlaubt] [--repo o/r]
    python3 -m runner_monitor.quelle setze --konfig … --quelle github|forgejo [--basis URL] [--http-erlaubt]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import github
from .konfig import Konfig, KonfigFehler, lies_env_datei, update_quelle

NAMEN = {"github": "GitHub", "forgejo": "Forgejo"}
VERSION_MUSTER = re.compile(r"^\d+\.\d+\.\d+$")
SCHLUESSEL = ("MONITOR_UPDATE_QUELLE", "MONITOR_UPDATE_FORGEJO", "MONITOR_UPDATE_HTTP_ERLAUBT")


class _OhneWeiterleitung(urllib.request.HTTPRedirectHandler):
    """Eine 3xx-Antwort wird zum HTTPError: ein Download geht nie an eine andere Adresse."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102, PLR0913, ANN001
        return None


def oeffner(k: Konfig) -> urllib.request.OpenerDirector | None:
    """Opener für Downloads. GitHub: ``None`` (Standard, folgt der Weiterleitung zum Speicher von GitHub –
    unverändert seit ADR-0004). Forgejo: ohne Weiterleitungen, bei ``http://`` ohne Proxy (E-21)."""
    if k.update_quelle != "forgejo":
        return None
    if k.update_forgejo.startswith("http://"):
        return urllib.request.build_opener(_OhneWeiterleitung, urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(_OhneWeiterleitung)


def _repo_pfad(repo: str) -> str:
    besitzer, name = repo.split("/", 1)
    return f"{urllib.parse.quote(besitzer, safe='')}/{urllib.parse.quote(name, safe='')}"


def download_praefix(k: Konfig) -> str:
    if k.update_quelle == "forgejo":
        return f"{k.update_forgejo}/{_repo_pfad(k.release_repo)}/releases/download/"
    return f"https://github.com/{k.release_repo}/releases/download/"


def download_urls(k: Konfig, version: str) -> tuple[str, str]:
    """Archiv und Prüfsumme einer Version – genau diese zwei Adressen lädt der Hilfsdienst bei Forgejo."""
    if not VERSION_MUSTER.match(version or ""):
        return "", ""
    archiv = f"{download_praefix(k)}v{version}/runner-monitor-{version}.tar.gz"
    return archiv, archiv + ".sha256"


def anzeige(k: Konfig) -> dict:
    """Für Info › Updates (über /api/update, ohne Geheimnisse): Art, Name, Adresse, http, Release-Seite."""
    if k.update_quelle == "forgejo":
        return {"art": "forgejo", "name": NAMEN["forgejo"], "adresse": k.update_forgejo,
                "http": k.update_forgejo.startswith("http://"),
                "releases": f"{k.update_forgejo}/{_repo_pfad(k.release_repo)}/releases"}
    return {"art": "github", "name": NAMEN["github"], "adresse": "https://github.com", "http": False,
            "releases": f"https://github.com/{k.release_repo}/releases"}


def _fehlertext(fehler: Exception) -> str:
    """Meldungen des Forgejo-Klienten für die Update-Quelle (er spricht sonst von runner.json)."""
    art, ursache = getattr(fehler, "art", ""), getattr(fehler, "ursache", None)
    if art in ("keine-rechte", "token-ungueltig"):
        return "Forgejo verlangt eine Anmeldung – ist das Repository öffentlich?"
    if art == "fehlt":
        return "Repository oder Release auf Forgejo nicht gefunden (404) – MONITOR_RELEASE_REPO prüfen"
    if ursache == "weiterleitung":
        return "Forgejo leitet weiter – MONITOR_UPDATE_FORGEJO prüfen (genaue Adresse, https://)"
    if ursache == "kein-dienst":
        return ("Keine gültige Antwort – ist MONITOR_UPDATE_FORGEJO ein Forgejo-Server, "
                "und ist er ohne Anmeldung lesbar?")
    return str(fehler)


def _forgejo_klient(k: Konfig):
    from .anbieter import forgejo  # spät: Paket anbieter lädt Erkennung und Runner
    # Ohne Token; http:// nur, wenn die Konfiguration es ausdrücklich erlaubt (sonst gar kein Server)
    return forgejo.Klient(k.update_forgejo, token="", http_erlaubt=k.update_http_erlaubt), forgejo.ForgejoFehler


def forgejo_release(k: Konfig, installiert: str, klient=None) -> dict:
    """Neuestes Release von Forgejo, dazu „aenderungen“ seit ``installiert`` – Felder wie bei GitHub."""
    if klient is None:
        klient, fehlerart = _forgejo_klient(k)
    else:
        from .anbieter.forgejo import ForgejoFehler as fehlerart
    pfad = f"/repos/{_repo_pfad(k.release_repo)}/releases"
    try:
        daten = github.deute_release(klient.hole(f"{pfad}/latest").daten)
    except fehlerart as fehler:
        return {"geprueft": time.time(), "fehler": _fehlertext(fehler), "version": ""}
    version = daten.get("version", "")
    seite = anzeige(k)["releases"]
    if daten.get("fehler") or daten.get("tag") != f"v{version}" or not VERSION_MUSTER.match(version):
        # Tag nicht „vX.Y.Z“: kein Paket, das der Hilfsdienst laden dürfte
        daten.update(archiv="", pruefsumme="", bereit=False)
        if not daten.get("fehler"):
            daten["fehler"] = f"Release-Tag {daten.get('tag', '')!r} ist nicht vX.Y.Z"
            daten["version"] = ""
        return daten
    archiv, summe = download_urls(k, version)
    # Nur ob die Dateien am Release hängen zählt; geladen wird von der selbst gebauten Adresse
    daten.update(archiv=archiv if daten.get("archiv") else "", pruefsumme=summe if daten.get("pruefsumme") else "",
                 url=f"{seite}/tag/v{version}")
    daten["bereit"] = bool(daten["archiv"] and daten["pruefsumme"])
    if github.vergleiche(version, installiert) > 0:
        try:
            liste = klient.hole(pfad, {"limit": 30}).daten
        except fehlerart:
            liste = []
        daten["aenderungen"] = [{**r, "url": f"{seite}/tag/v{r['version']}"}
                                for r in github.aenderungen_aus(liste, installiert, version)]
    return daten


# ---------------------------------------------------------------- konfig.env schreiben (einrichten.sh quelle)


def schreibe_konfig(pfad: Path, werte: dict[str, str | None]) -> None:
    """Schlüssel in konfig.env setzen (``None`` entfernt die Zeile), alle anderen Zeilen bleiben.
    Atomar, Besitzer und Rechte der alten Datei bleiben (root:runner-monitor 0640)."""
    zeilen = pfad.read_text(encoding="utf-8").splitlines() if pfad.is_file() else []
    offen = dict(werte)
    neu: list[str] = []
    for zeile in zeilen:
        schluessel = zeile.split("=", 1)[0].strip() if "=" in zeile and not zeile.lstrip().startswith("#") else ""
        if schluessel in offen:
            wert = offen.pop(schluessel)
            if wert is not None:
                neu.append(f"{schluessel}={wert}")
            continue
        if schluessel in werte:  # doppelt vorhanden: nur die erste Zeile zählt
            continue
        neu.append(zeile)
    zusatz = [f"{s}={w}" for s, w in offen.items() if w is not None]
    if zusatz:
        if neu and neu[-1].strip():
            neu.append("")
        neu.append("# Update-Quelle (einrichten.sh quelle, docs/UPDATE.md)")
        neu.extend(zusatz)
    tmp = pfad.with_name(pfad.name + ".neu")
    tmp.write_text("\n".join(neu) + "\n", encoding="utf-8")
    if pfad.exists():
        info = pfad.stat()
        os.chmod(tmp, info.st_mode & 0o777)
        try:
            os.chown(tmp, info.st_uid, info.st_gid)
        except PermissionError:  # pragma: no cover – nur ohne root (Tests)
            pass
    else:
        os.chmod(tmp, 0o640)
    os.replace(tmp, pfad)


def _main(argv: list[str] | None = None) -> int:
    teiler = argparse.ArgumentParser(prog="python3 -m runner_monitor.quelle")
    befehle = teiler.add_subparsers(dest="befehl", required=True)
    b = befehle.add_parser("zeige")
    b.add_argument("--konfig", type=Path, required=True)
    b = befehle.add_parser("pruefe-adresse")
    b.add_argument("adresse")
    b = befehle.add_parser("abfrage")
    b.add_argument("--basis", required=True)
    b.add_argument("--http-erlaubt", action="store_true")
    b.add_argument("--repo", default=Konfig.release_repo)
    b = befehle.add_parser("setze")
    b.add_argument("--konfig", type=Path, required=True)
    b.add_argument("--quelle", choices=("github", "forgejo"), required=True)
    b.add_argument("--basis", default="")
    b.add_argument("--http-erlaubt", action="store_true")
    a = teiler.parse_args(argv)

    if a.befehl == "zeige":
        werte = lies_env_datei(a.konfig)
        try:
            q, basis, http = update_quelle(werte)
            print(f"quelle={q}\nbasis={basis}\nhttp={1 if http else 0}\nfehler=")
        except KonfigFehler as fehler:
            print(f"quelle={werte.get('MONITOR_UPDATE_QUELLE', '')}\nbasis=\nhttp=0\nfehler={fehler}")
        return 0
    if a.befehl == "pruefe-adresse":
        try:
            _, basis, _ = update_quelle({"MONITOR_UPDATE_QUELLE": "forgejo", "MONITOR_UPDATE_FORGEJO": a.adresse,
                                         "MONITOR_UPDATE_HTTP_ERLAUBT": "1"})
        except KonfigFehler:
            basis = ""
        if not basis:
            print("Keine gültige Adresse – erwartet https://host[:port][/pfad] ohne Zugangsdaten, Abfrage und Anker.")
            return 2
        print(basis)
        return 4 if basis.startswith("http://") else 0
    if a.befehl == "abfrage":
        werte = {"MONITOR_UPDATE_QUELLE": "forgejo", "MONITOR_UPDATE_FORGEJO": a.basis,
                 "MONITOR_UPDATE_HTTP_ERLAUBT": "1" if a.http_erlaubt else "", "MONITOR_RELEASE_REPO": a.repo}
        try:
            q, basis, http = update_quelle(werte)
        except KonfigFehler as fehler:
            print(f"fehler|{fehler}")
            return 2
        if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", a.repo):
            print("fehler|Repository muss besitzer/repo sein")
            return 2
        k = Konfig(release_repo=a.repo, update_quelle=q, update_forgejo=basis, update_http_erlaubt=http)
        from . import VERSION
        daten = forgejo_release(k, VERSION)
        if daten.get("fehler"):
            print(f"fehler|{daten['fehler']}")
            return 1
        print(f"ok|Neuestes Release auf Forgejo: {daten.get('version')}"
              + (" (Archiv und Prüfsumme hängen am Release)" if daten.get("bereit") else " – Paket fehlt noch am Release"))
        return 0
    # setze
    # Zurück zu GitHub: Forgejo-Adresse und http-Freigabe entfernen, damit nichts davon stehen bleibt
    werte: dict[str, str | None] = {"MONITOR_UPDATE_QUELLE": a.quelle, "MONITOR_UPDATE_FORGEJO": None,
                                    "MONITOR_UPDATE_HTTP_ERLAUBT": None}
    if a.quelle == "forgejo":
        try:
            _, basis, _ = update_quelle({"MONITOR_UPDATE_QUELLE": "forgejo", "MONITOR_UPDATE_FORGEJO": a.basis,
                                         "MONITOR_UPDATE_HTTP_ERLAUBT": "1" if a.http_erlaubt else ""})
        except KonfigFehler as fehler:
            print(f"fehler|{fehler}")
            return 2
        werte.update(MONITOR_UPDATE_FORGEJO=basis, MONITOR_UPDATE_HTTP_ERLAUBT="1" if basis.startswith("http://") else None)
    schreibe_konfig(a.konfig, werte)
    print(f"ok|Update-Quelle: {NAMEN[a.quelle]}" + (f" ({werte['MONITOR_UPDATE_FORGEJO']})" if a.quelle == "forgejo" else ""))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main())
