# ADR-0006: Anbieter-Adapter, Zugangsdaten je Runner und Format von `/api/zustand`

**Status:** angenommen
**Datum:** 2026-10-29 · **Entschieden von:** Claude im Auftrag von Tobias (E-19, Issue #92; jederzeit widerrufbar)

## Ausgangslage
Bis 0.7 kennt der Monitor genau einen GitHub-Runner: `github.py` fragt die API ab, `runner.py` liest
Dienst, Journal und `_diag/pages`, `zustand.py` baut daraus die Einzelobjekte `status` und
`workflows`. Design 0.8.0 verlangt mehrere Runner verschiedener Dienste (GitHub, Forgejo, Gitea,
GitLab, unbekannt) und eine Oberfläche, die sich nach **Fähigkeiten** richtet, nicht nach dem Namen
(README › „Nicht verfügbar“ ehrlich zeigen). Die Runner-Erkennung (#91) liefert die Funde, aber ein
Fund darf nie bestimmen, wohin der Monitor mit einem Token fragt (E-18).

## Entscheidung
- **Paket `runner_monitor/anbieter/`** mit Basisklasse `Anbieter`, `RunnerKonfig` und Registry
  (`registriere`, `klasse_fuer`, `faehigkeiten_tabelle`). Je Dienst ein Adapter mit derselben
  Schnittstelle: Status, Jobs je Repository, aktueller Job mit `schritt: {nr, von|null, name}`,
  Log-Quelle, Fähigkeiten `status/jobs/schritte/logs/updates`. Ohne eigenen Adapter gilt die
  Grundüberwachung (Dienst und Journal). GitHub ist der erste Adapter (`anbieter/github.py`), sein
  Verhalten für genau einen Runner ist unverändert; `github.py` bleibt REST-Klient und Releases.
- **Konfiguration statt Fund:** `RunnerKonfig` (Server, Organisation, Unit, Log-Pfad, Token-Datei)
  wird nur aus `konfig.env`, `einstellungen.json`, `runner.json` und `zugang/` gebaut. Vom Fund
  kommen nur Anzeigewerte.
- **Zugangsdaten je Runner** in `/etc/runner-monitor/zugang/<id>.token` (Verzeichnis root 0700,
  Dateien 0600), gesetzt über `sudo einrichten.sh zugang <runner>`, im Dashboard weder sichtbar noch
  änderbar. Das bisherige `github-token` wird beim Start nach dem Update **kopiert** und bleibt als
  Rückfall, bis #94/#96 abgeschlossen sind; ist der alte Ort später neuer und anders, wird die Kopie
  ersetzt. Alle Wege, die das GitHub-Token erneuern, schreiben beide Orte; scheitert das Schreiben
  nach `zugang/`, wird die veraltete Kopie entfernt (Review #111).
- **`/api/zustand` additiv** (Format 2): `GET /api/zustand` liefert die bisherigen Bereiche
  unverändert und zusätzlich `vm`, `runner[]` und `meldungen[]` (mit Runner-ID). `/events` bekommt
  die Ereignisse `runner` und `meldungen`. Die Oberfläche bleibt beim Altformat, bis #94 sie umstellt;
  danach entfällt das Altformat in einem eigenen Issue.

## Betrachtete Möglichkeiten
- **Format sofort umstellen** (nur `vm`, `runner[]`, `meldungen[]`) – sauberer, aber #92 müsste die
  ganze Oberfläche mit umbauen; verworfen, weil #94 das ohnehin mit dem neuen Layout tut.
- **Additiv erweitern** (gewählt) – die bestehende Oberfläche läuft unverändert, die neuen Felder
  sind testbar und für #94 fertig; kostet für eine Übergangszeit doppelte Daten.
- **Token verschieben statt kopieren** – verworfen: ältere Versionen (`einrichten.sh zurueck`) und
  der Update-Hilfsdienst (`gh attestation verify`) lesen nur den alten Ort.
- **Token-Datei nach dem Unit-Namen benennen** – root-eigen, aber die ID aus der Erkennung ist das,
  was Oberfläche, `runner.json` und `einrichten.sh zugang` verwenden; verworfen.

## Folgen
- Neue Dienste brauchen nur einen Adapter und eine Zeile in der Fähigkeiten-Tabelle; ein Test hält
  `anbieter.faehigkeiten_tabelle()` und `erkennung.FAEHIG` gleich.
- Übergangsweise zwei Orte für das GitHub-Token; die Rückfall-Regel entfällt mit #94/#96.
- Der Name der Token-Datei hängt am `agentName` in `.runner`, den der Runner-Benutzer ändern kann
  (Sicherheitsbericht S-ADAPTER-01: Restrisiko gering, weil Server nie aus Funden kommen).
- `runner[].log` nennt nur `art` und `unit`, keine Pfade der VM (Review #111); `stand` ist beim
  GitHub-Runner nur bei gültigem Token „angebunden“.
- `runner[]` umfasst höchstens 20 Runner; weitere GitHub-Runner neben `MONITOR_RUNNER_VERZ` laufen bis
  #94 in der Grundüberwachung.
