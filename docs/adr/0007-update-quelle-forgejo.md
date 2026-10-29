# ADR-0007: Forgejo als wählbare Update-Quelle

**Status:** vorgeschlagen – Entwurf und Anforderungen von Tobias (#138), Umsetzung und Abwägung Claude;
die strenge Herkunftsregel (E-28) bitte bestätigen
**Datum:** 2026-10-29

## Ausgangslage
Seit dem 28.10.2026 ist GitHub für die Entwicklung eingefroren, Releases entstehen auch auf Forgejo
(0.8.0 gibt es nur dort als Paket). Der Update-Hilfsdienst lädt aber nur von
`https://github.com/<release-repo>/releases/download/` (ADR-0004), der Sammler fragt nur die
GitHub-API. Forgejo läuft derzeit im LAN über `http://`, wird eventuell öffentlich.

## Entscheidung
- **Wählbar, GitHub bleibt Vorgabe.** `MONITOR_UPDATE_QUELLE=github|forgejo` in
  `/etc/runner-monitor/konfig.env`, dazu `MONITOR_UPDATE_FORGEJO=<Basis-Adresse>`. Ohne Eintrag ändert
  sich für bestehende VMs nichts. Einstellbar mit `einrichten.sh quelle`, sichtbar in Info › Updates
  („Quelle“).
- **Ohne Token.** Release-API und Downloads eines öffentlichen Repositorys brauchen keine Anmeldung.
  Verlangt Forgejo eine (403, Anmeldeseite), endet das als klarer Fehler „Quelle verlangt Anmeldung“.
- **https Pflicht, http nur ausdrücklich.** `http://` nur mit `MONITOR_UPDATE_HTTP_ERLAUBT=1`
  (Rückfrage in `einrichten.sh quelle`), dann ohne Proxy aus der Umgebung – wie E-21. Eine
  ungültige oder nicht freigegebene Adresse hält den Start an (Anweisung 02).
- **Nur genau diese Adressen, keine Weiterleitung.** Der Sammler wertet `releases/latest` und
  `releases` unter `<basis>/api/v1/repos/<repo>/` aus und folgt keiner Weiterleitung. Die
  Download-Adressen baut der Monitor selbst:
  `<basis>/<repo>/releases/download/vX.Y.Z/runner-monitor-X.Y.Z.tar.gz` und `….sha256`. Aus der
  Antwort zählt nur, ob die zwei Dateien am Release hängen; `browser_download_url` und `html_url`
  werden nie benutzt. Der Hilfsdienst vergleicht beide Adressen aus `release.json` **exakt** mit den
  selbst gebauten und lädt ohne Weiterleitungen.
- **Herkunft gegen GitHub.** Die GitHub-Attestierung (ADR-0005) bestätigt einen SHA-256, nicht einen
  Ort. Der Hilfsdienst prüft deshalb auch Forgejo-Downloads mit
  `gh attestation verify <archiv> --repo <release-repo> --signer-workflow <release-repo>/.github/workflows/release.yml`.
  Geprüft am 29.10.2026: Das Paket 0.8.1 von Forgejo ist byte-gleich mit dem von GitHub und besteht
  die Prüfung; 0.8.0 (nur Forgejo) hat keine Attestierung.
- **Fehlende Attestierung = nicht bestätigt (E-28).** Mit GitHub-CLI und Token auf der VM bricht ein
  Update ab, wenn es zu diesem SHA-256 keine Attestierung gibt – genau wie bei GitHub als Quelle. Ein
  „nicht gefunden“ lässt sich von „auf Forgejo verändert“ nicht unterscheiden: Ein verändertes Archiv
  hat nie eine Attestierung. Ohne CLI oder Token bleibt es wie bisher bei der Prüfsumme mit Warnung,
  mit `MONITOR_UPDATE_HERKUNFT=pflicht` gibt es dann kein Update.
- **Paketversion prüfen.** Nach dem Entpacken muss `VERSION` im Paket die Zielversion nennen (für
  beide Quellen). Sonst ließe sich ein älteres, echtes, attestiertes Paket unter einer neueren Nummer
  anbieten und würde bis zur Gesundheitsprüfung gestartet.
- **Anmeldeseite erkennen.** Eine Antwort mit `Content-Type: text/html`, ein Inhalt, der mit `<`
  beginnt, eine Weiterleitung auf `/user/login` oder 401/403 beim Download enden als „Quelle verlangt
  Anmeldung“. Das Archiv muss mit der gzip-Kennung beginnen, die Prüfsumme folgt vor jeder weiteren
  Verwendung.

## Betrachtete Möglichkeiten
- **Forgejo mit Token** – verworfen: ein weiteres Geheimnis auf der VM nur für Updates; ein
  öffentliches Repository braucht keins.
- **`browser_download_url` aus der Antwort mit Präfix-Prüfung** (wie bei GitHub) – verworfen: Forgejo
  baut die Adresse aus seiner `ROOT_URL`, die von der eingetragenen Adresse abweichen kann, und ein
  übernommener Server bestimmte sonst Pfad und Tag.
- **Ohne Attestierung nur warnen** – verworfen (E-28): machte die Attestierung bei Forgejo wertlos.
- **Eigene Signatur (Ed25519/`ssh-keygen -Y verify`)** – nicht jetzt; Option, falls Releases künftig
  nicht mehr über GitHub laufen (siehe Folgen).

## Folgen
- Die Herkunftsprüfung trägt nur, solange jedes Release auch über den GitHub-Release-Workflow
  (`.github/workflows/release.yml`) gebaut und attestiert wird und das Forgejo-Paket byte-gleich ist.
  Gibt es ein Release nur auf Forgejo (wie 0.8.0), verweigern VMs mit GitHub-CLI und Token das Update
  („Herkunft nicht bestätigt“); VMs ohne CLI installieren es nur mit Prüfsumme.
- Für die Prüfung braucht die VM weiter GitHub-CLI, ein GitHub-Token in
  `/etc/runner-monitor/github-token` und Netz zu GitHub und Sigstore – auch bei Forgejo als Quelle.
- `release.json` trägt `quelle`; stammt sie von der vorigen Quelle, lehnt der Hilfsdienst ab, bis der
  Sammler neu geprüft hat.
- Repository-Pfad auf Forgejo = `MONITOR_RELEASE_REPO` (wie auf GitHub).
