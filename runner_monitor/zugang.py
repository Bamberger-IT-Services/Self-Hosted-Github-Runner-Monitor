"""Anmeldung: Passwort-Hash, Sitzungen, Drosselung und Einrichtungscode.

Grundlage ist Anweisung 03 mit der Abweichung E-01 / ADR-0003: Anmeldung nur mit Passwort,
ohne 2FA, mit „Angemeldet bleiben“ (30 Tage). Alles liegt in Dateien unter
``/var/lib/runner-monitor`` (Rechte 0600, Besitzer ``runner-monitor``) – es gibt keine Datenbank.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path

# scrypt-Parameter (OWASP: N=2^17, r=8, p=1 – hier 2^15, damit die kleine VM unter Last flott bleibt)
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**15, 8, 1
PASSWORT_MIN, PASSWORT_MAX = 12, 128

SITZUNG_KURZ = 12 * 3600          # ohne „Angemeldet bleiben“
SITZUNG_LANG = 30 * 86400         # mit „Angemeldet bleiben“
INAKTIV_MAX = 7 * 86400           # Inaktivität beendet jede Sitzung (Anweisung 03)

FEHLVERSUCHE_KONTO = 5            # je Konto in 15 Minuten
FEHLVERSUCHE_IP = 30              # je IP in 15 Minuten
FENSTER = 15 * 60
SPERRE = 5 * 60                   # danach 5 Minuten gesperrt (Design v1)

CODE_ZEICHEN = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # ohne 0/O, 1/I
CODE_GUELTIG = 60 * 60
CODE_VERSUCHE = 10

# Häufige Passwörter (Auszug). Ziel nach Anweisung 03 sind die 10.000 häufigsten → A-08.
HAEUFIG = {
    "passwort1234", "password1234", "123456789012", "qwertzuiop12", "qwertyuiop12",
    "adminadmin12", "administrator", "letmein12345", "willkommen12", "welcome12345",
    "passwortpasswort", "passwordpassword", "000000000000", "111111111111", "abcdefghijkl",
    "runnermonitor", "runner-monitor", "github-runner", "iloveyou1234", "sommer2026!!",
}


class ZugangFehler(ValueError):
    pass


def _schreibe(pfad: Path, daten: object) -> None:
    """Atomar schreiben, Rechte 0600."""
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


def _lies(pfad: Path, vorgabe):
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return vorgabe


# ---------------------------------------------------------------- Passwort


def pruefe_passwort_regeln(passwort: str, nutzer: str) -> str | None:
    """Fehlermeldung oder None. Keine Zusammensetzungsregeln (NIST SP 800-63B)."""
    if len(passwort) < PASSWORT_MIN:
        return f"Das Passwort braucht mindestens {PASSWORT_MIN} Zeichen."
    if len(passwort) > PASSWORT_MAX:
        return f"Das Passwort darf höchstens {PASSWORT_MAX} Zeichen haben."
    klein = passwort.lower()
    if klein in HAEUFIG or (nutzer and nutzer.lower() in klein) or "runner" in klein and "monitor" in klein:
        return "Dieses Passwort ist zu leicht zu erraten. Bitte ein anderes wählen."
    if len(set(passwort)) < 4:
        return "Dieses Passwort ist zu leicht zu erraten. Bitte ein anderes wählen."
    return None


def hash_passwort(passwort: str) -> str:
    salz = secrets.token_bytes(16)
    wert = hashlib.scrypt(passwort.encode("utf-8"), salt=salz, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=128 * 1024 * 1024)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salz.hex()}${wert.hex()}"


def pruefe_hash(passwort: str, gespeichert: str) -> bool:
    try:
        art, n, r, p, salz, wert = gespeichert.split("$")
        if art != "scrypt":
            return False
        neu = hashlib.scrypt(passwort.encode("utf-8"), salt=bytes.fromhex(salz), n=int(n), r=int(r), p=int(p), maxmem=128 * 1024 * 1024)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(neu.hex(), wert)


# Ein fester Hash, damit eine Anmeldung mit unbekanntem Namen gleich lange dauert.
_LEER_HASH = None


def _leer_hash() -> str:
    global _LEER_HASH
    if _LEER_HASH is None:
        _LEER_HASH = hash_passwort(secrets.token_hex(16))
    return _LEER_HASH


# ---------------------------------------------------------------- Zugang (ein Konto)


class Zugang:
    def __init__(self, zugang_datei: Path, sitzungen_datei: Path, sperren_datei: Path) -> None:
        self.zugang_datei = zugang_datei
        self.sitzungen_datei = sitzungen_datei
        self.sperren_datei = sperren_datei
        self._sperre = threading.Lock()

    # Konto ----------------------------------------------------------

    def eingerichtet(self) -> bool:
        return bool(_lies(self.zugang_datei, {}).get("hash"))

    def nutzername(self) -> str:
        return _lies(self.zugang_datei, {}).get("nutzer", "")

    def lege_an(self, nutzer: str, passwort: str) -> None:
        nutzer = nutzer.strip()
        if not (1 <= len(nutzer) <= 64) or any(c.isspace() for c in nutzer):
            raise ZugangFehler("Der Benutzername braucht 1 bis 64 Zeichen ohne Leerzeichen.")
        fehler = pruefe_passwort_regeln(passwort, nutzer)
        if fehler:
            raise ZugangFehler(fehler)
        with self._sperre:
            _schreibe(self.zugang_datei, {"nutzer": nutzer, "hash": hash_passwort(passwort), "geaendert": time.time()})
            _schreibe(self.sitzungen_datei, {})  # neues Passwort beendet alle Sitzungen

    # Drosselung -----------------------------------------------------

    def _versuche(self) -> dict:
        daten = _lies(self.sperren_datei, {})
        grenze = time.time() - FENSTER
        return {k: [t for t in v if t > grenze] for k, v in daten.items() if isinstance(v, list)}

    def gesperrt_bis(self, ip: str) -> float:
        """0, wenn eine Anmeldung erlaubt ist, sonst Zeitpunkt, ab dem sie wieder geht."""
        versuche = self._versuche()
        konto = versuche.get("konto", [])
        per_ip = versuche.get(f"ip:{ip}", [])
        bis = 0.0
        if len(konto) >= FEHLVERSUCHE_KONTO:
            bis = max(bis, konto[-1] + SPERRE)
        if len(per_ip) >= FEHLVERSUCHE_IP:
            bis = max(bis, per_ip[-1] + SPERRE)
        return bis if bis > time.time() else 0.0

    def verbleibend(self) -> int:
        return max(0, FEHLVERSUCHE_KONTO - len(self._versuche().get("konto", [])))

    def _fehlversuch(self, ip: str) -> None:
        versuche = self._versuche()
        jetzt = time.time()
        versuche.setdefault("konto", []).append(jetzt)
        versuche.setdefault(f"ip:{ip}", []).append(jetzt)
        _schreibe(self.sperren_datei, versuche)

    # Anmeldung ------------------------------------------------------

    def anmelden(self, nutzer: str, passwort: str, ip: str, merken: bool) -> str | None:
        """Gibt ein Sitzungs-Token zurück oder None. Die Meldung nach außen ist immer gleich."""
        with self._sperre:
            if self.gesperrt_bis(ip):
                return None
            konto = _lies(self.zugang_datei, {})
            richtiger_name = hmac.compare_digest(nutzer.strip().encode(), konto.get("nutzer", "").encode())
            passt = pruefe_hash(passwort, konto.get("hash") or _leer_hash())
            if not (richtiger_name and passt and konto.get("hash")):
                self._fehlversuch(ip)
                return None
            _schreibe(self.sperren_datei, {k: v for k, v in self._versuche().items() if k not in ("konto", f"ip:{ip}")})
            return self._neue_sitzung(merken)

    def _neue_sitzung(self, merken: bool) -> str:
        token = secrets.token_urlsafe(32)
        jetzt = time.time()
        sitzungen = self._gueltige(_lies(self.sitzungen_datei, {}), jetzt)
        sitzungen[hashlib.sha256(token.encode()).hexdigest()] = {
            "erstellt": jetzt, "zuletzt": jetzt, "bis": jetzt + (SITZUNG_LANG if merken else SITZUNG_KURZ), "merken": merken,
        }
        _schreibe(self.sitzungen_datei, sitzungen)
        return token

    @staticmethod
    def _gueltige(sitzungen: dict, jetzt: float) -> dict:
        return {k: v for k, v in sitzungen.items() if v.get("bis", 0) > jetzt and v.get("zuletzt", 0) + INAKTIV_MAX > jetzt}

    def pruefe_sitzung(self, token: str | None) -> bool:
        if not token or len(token) > 100:
            return False
        schluessel = hashlib.sha256(token.encode()).hexdigest()
        with self._sperre:
            jetzt = time.time()
            sitzungen = self._gueltige(_lies(self.sitzungen_datei, {}), jetzt)
            eintrag = sitzungen.get(schluessel)
            if not eintrag:
                return False
            # „zuletzt“ höchstens einmal je Minute schreiben
            if jetzt - eintrag.get("zuletzt", 0) > 60:
                eintrag["zuletzt"] = jetzt
                _schreibe(self.sitzungen_datei, sitzungen)
            return True

    def abmelden(self, token: str | None) -> None:
        if not token:
            return
        schluessel = hashlib.sha256(token.encode()).hexdigest()
        with self._sperre:
            sitzungen = _lies(self.sitzungen_datei, {})
            if sitzungen.pop(schluessel, None) is not None:
                _schreibe(self.sitzungen_datei, sitzungen)

    def sitzung_dauer(self, token: str) -> int:
        eintrag = _lies(self.sitzungen_datei, {}).get(hashlib.sha256(token.encode()).hexdigest(), {})
        return int(max(0, eintrag.get("bis", 0) - time.time())) if eintrag.get("merken") else 0


# ---------------------------------------------------------------- Einrichtungscode


def neuer_code() -> str:
    roh = "".join(secrets.choice(CODE_ZEICHEN) for _ in range(8))
    return f"{roh[:4]}-{roh[4:]}"


def normalisiere_code(code: str) -> str:
    sauber = "".join(c for c in code.upper() if c in CODE_ZEICHEN)
    return f"{sauber[:4]}-{sauber[4:8]}" if len(sauber) == 8 else ""


def schreibe_code(datei: Path, code: str, gueltig: int = CODE_GUELTIG) -> None:
    _schreibe(datei, {"hash": hashlib.sha256(normalisiere_code(code).encode()).hexdigest(), "bis": time.time() + gueltig, "versuche": 0})


def pruefe_code(datei: Path, code: str) -> str:
    """``ok`` | ``falsch`` | ``abgelaufen`` | ``fehlt``. Nach 10 Fehlern ist der Code verbraucht."""
    daten = _lies(datei, {})
    if not daten.get("hash"):
        return "fehlt"
    if daten.get("bis", 0) < time.time() or daten.get("versuche", 0) >= CODE_VERSUCHE:
        return "abgelaufen"
    probe = hashlib.sha256(normalisiere_code(code).encode()).hexdigest()
    if hmac.compare_digest(probe, daten["hash"]):
        return "ok"
    daten["versuche"] = daten.get("versuche", 0) + 1
    _schreibe(datei, daten)
    return "falsch"
