# AGENTS.md – Runner-Monitor

Für Codex und andere Agenten gelten dieselben Regeln wie für Claude:

- Gemeinsame Anweisungen: Repo `Public` auf Forgejo, Ordner `anweisungen/` (00–08, Vorlagen),
  besonders README › Forgejo statt GitHub und 08 · Aufgaben als Issues.
- Seit 28.10.2026 nur noch Forgejo; GitHub ist eingefroren. Branches `develop` (Standard),
  `main`, `feature/*`, `fix/*`, `release/*`; Arbeit per PR nach `develop`.
- Projektregeln und Abweichungen: [CLAUDE.md](CLAUDE.md) (öffentliches Repo mit Platzhaltern,
  nur Python-Standardbibliothek und Vanilla-JS, kein Docker, keine Lizenz, CSP ohne Inline-Skripte).
- Aufgaben: Issues dieses Repos auf Forgejo. Nächstes Issue ist ein offenes ohne `agent:`-Label
  und ohne `blocked`, höchste Priorität zuerst; vor dem Start `agent:codex` setzen. Issues mit
  fremdem `agent:`-Label nicht anfassen.
- Entscheidungen (`E-nn`) und Verlauf: `entwickler-dashboard/daten.js` und `DECISIONS.md`.
