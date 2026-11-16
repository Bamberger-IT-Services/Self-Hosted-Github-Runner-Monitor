"""Sicht auf Laufendes und Wartendes (#171): laufende Jobs, wartende Läufe und Vergleichsdauern – reine Auswertung ohne Netz.

Das Dashboard zeigt, was der Runner gerade abarbeitet: je Repository die laufenden Jobs (Workflow, Job,
Branch oder PR, seit wann, aktueller Schritt „n von m“) und die wartenden Läufe (seit wann, Position in der
Warteschlange). Die **geschätzte Restzeit** rechnet die Oberfläche selbst, damit sie live hochzählt: Der Server liefert
nur die Vergleichsdauern als ``vergleich = {"median": Sekunden, "anzahl": n}`` – der Median der Dauern der letzten
(höchstens 5) erfolgreichen Läufe desselben Workflows und Jobs (``vergleich()``). Ohne Vergleichswerte ist
``vergleich`` ``None`` („keine Schätzung“); wird der Median überschritten, zeigt die Oberfläche „länger als üblich“
(nie eine negative Zeit).

Format im Bereich ``jobsJeRepository`` (docs/FUNKTIONSWEISE.md › „Laufende und wartende Jobs“)::

    "laufende": [{"repo", "privat", "workflow", "name", "ref": {art, name, titel}, "runner": Name | None,
                  "eigener": True | False | None, "start": Unix | None,
                  "schritt": {"nr", "von", "name", "start"} | None, "vergleich": {...} | None}],
    "wartende": [{"repo", "privat", "workflow", "ref", "seit": Unix | None, "pos": 1 … | None, "blockiert": bool}]

Alle Werte stammen aus fremden Antworten und werden hier nur durchgereicht, nachdem der Adapter sie geprüft hat.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

VERGLEICH_ANZAHL = 5        # Median der letzten so vielen erfolgreichen Läufe
MAX_LAUFENDE = 12           # so viele laufende Jobs zeigt das Dashboard höchstens (je Runde im Ergebnis)
MAX_WARTENDE = 30           # so viele wartende Läufe zeigt das Dashboard höchstens
MAX_DAUER = 30 * 86400      # eine Dauer über 30 Tage ist keine Dauer eines Jobs


def _zahl(wert: object) -> float | None:
    if isinstance(wert, bool) or not isinstance(wert, (int, float)) or not math.isfinite(wert):
        return None
    return float(wert)


def dauer_zwischen(start: object, ende: object) -> float | None:
    """Sekunden zwischen zwei Unix-Zeiten; ``None``, wenn eine fehlt oder das Ergebnis nicht plausibel ist."""
    a, b = _zahl(start), _zahl(ende)
    if a is None or b is None:
        return None
    sekunden = b - a
    return sekunden if 0 < sekunden <= MAX_DAUER else None


def median(werte: Iterable[float]) -> float | None:
    liste = sorted(werte)
    if not liste:
        return None
    mitte = len(liste) // 2
    return liste[mitte] if len(liste) % 2 else (liste[mitte - 1] + liste[mitte]) / 2


def vergleich(dauern: Iterable[object]) -> dict | None:
    """``{"median", "anzahl"}`` aus den Dauern der letzten erfolgreichen Läufe (neueste zuerst; es zählen die
    ersten :data:`VERGLEICH_ANZAHL` brauchbaren). Nicht brauchbar: fehlende, nicht endliche, nicht positive und
    unglaubwürdig lange Dauern. Keine brauchbare Dauer → ``None`` („keine Schätzung“)."""
    brauchbar: list[float] = []
    for d in dauern:
        z = _zahl(d)
        if z is not None and 0 < z <= MAX_DAUER:
            brauchbar.append(z)
        if len(brauchbar) == VERGLEICH_ANZAHL:
            break
    m = median(brauchbar)
    return None if m is None else {"median": round(m, 1), "anzahl": len(brauchbar)}


def positionen(eintraege: list[dict], vollstaendig: bool) -> list[dict]:
    """Wartende Läufe in der Reihenfolge der Warteschlange, ältester zuerst; höchstens :data:`MAX_WARTENDE`.
    ``pos`` zählt nur Läufe, die wirklich auf einen Runner warten (nicht ``blockiert``, mit bekannter Zeit) und nur,
    wenn der Monitor alle Repositories der Organisation lesen konnte (``vollstaendig``) – sonst fehlen vielleicht
    Läufe vor diesem, und die Position wäre geraten. Blockierte Läufe (warten auf Freigabe oder einen anderen Job)
    stehen am Ende ohne Position. Das Feld ``_id`` dient nur der stabilen Reihenfolge und wird entfernt."""
    def schluessel(e: dict) -> tuple:
        seit = _zahl(e.get("seit"))
        return (bool(e.get("blockiert")), seit is None, seit or 0.0, e.get("_id") or 0)

    ergebnis: list[dict] = []
    nummer = 0
    for e in sorted(eintraege, key=schluessel)[:MAX_WARTENDE]:
        zaehlt = not e.get("blockiert") and _zahl(e.get("seit")) is not None
        if zaehlt:
            nummer += 1
        ergebnis.append({**{k: v for k, v in e.items() if not k.startswith("_")},
                         "pos": nummer if zaehlt and vollstaendig else None})
    return ergebnis
