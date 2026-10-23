# ADR-0005: Herkunft der Updates per GitHub-Attestierung (Sigstore)

**Status:** angenommen
**Datum:** 2026-10-23 · **Entschieden von:** Tobias (Auswahl „GitHub-Attestierung (Sigstore)“, Issue #18)

## Ausgangslage
Der Update-Hilfsdienst prüft nur die SHA-256-Prüfsumme, die im selben Release liegt wie das
Archiv (S-UPD-01). Wer das Repository oder den Release-Ablauf übernimmt, kann damit ein passendes
Paar aus Archiv und Prüfsumme ausliefern.

## Entscheidung
- Der Release-Workflow bestätigt das gebaute Archiv mit `actions/attest@v4` (SLSA-Herkunft,
  signiert über GitHubs OIDC und Sigstore). Es gibt keinen eigenen Schlüssel und kein Secret.
- Der Update-Hilfsdienst prüft nach der Prüfsumme mit
  `gh attestation verify <archiv> --repo <release-repo> --signer-workflow <release-repo>/.github/workflows/release.yml`.
  Scheitert die Prüfung, wird das Archiv verworfen und nichts installiert.
- Fehlen GitHub-CLI oder Token auf der VM, läuft das Update vorerst nur mit Prüfsumme weiter
  (Warnung im Journal, `herkunft` in `update-status.json`). Mit `MONITOR_UPDATE_HERKUNFT=pflicht`
  gibt es dann kein Update.

## Betrachtete Möglichkeiten
- **Ed25519 mit eigener Prüfung in der Standardbibliothek** – keine neue Abhängigkeit, aber ein
  Schlüssel, den jemand erzeugen, als Secret hinterlegen und schützen muss.
- **GitHub-Attestierung** (gewählt) – kein Schlüssel zu verwalten, an Repository und Workflow
  gebunden; braucht die GitHub-CLI (ab 2.49) auf der VM und Netz zu GitHub und Sigstore.
- **Bei der Prüfsumme bleiben** – verworfen, S-UPD-01 bliebe offen.

## Folgen
- Die GitHub-CLI ist eine Abhängigkeit des Update-Hilfsdienstes auf der VM (nicht des Monitors
  selbst, der bleibt bei der Python-Standardbibliothek). Installation: `docs/UPDATE.md`.
- Releases vor 0.5 sind nicht attestiert; die Prüfung greift ab dem ersten attestierten Release.
- Der Release-Workflow braucht `id-token: write`, `attestations: write`, `artifact-metadata: write`.
