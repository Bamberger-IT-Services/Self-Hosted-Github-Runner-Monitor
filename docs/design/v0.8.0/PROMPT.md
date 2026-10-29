Kopiere den Text unter der Linie in Claude (Desktop, Claude Code) – mit dem Repo `Self-Hosted-Github-Runner-Monitor` als Arbeitsordner. Den Ordner `design_handoff_runner_monitor_0.8.0/` vorher ins Repo legen, z. B. nach `docs/design/0.8.0/`.

---

Im Repo liegt unter `docs/design/v0.8.0/` das freigegebene **Design 0.8.0** des Runner-Monitors (anbieterunabhängig, mehrere Runner, echter Verlauf, Deutsch/Englisch). Lies zuerst `docs/design/v0.8.0/README.md` vollständig. Die HTML-Dateien dort sind **Design-Referenzen**, kein Code zum Kopieren; öffne bei Bedarf `Runner-Monitor 0.8.0.dc.html` über `python3 -m http.server` im Ordner, um Verhalten und Zustände anzusehen. `i18n-0.8.0.js` enthält alle englischen Texte.

Vorgehen:
1. Verschaffe dir einen Überblick über das Repo (`runner_monitor/`, `web/`, `einrichten.sh`, `docs/`, Tests) und gleiche ihn mit dem README ab. Nenne mir kurz, wo das Design auf den bestehenden Code trifft und wo du Annahmen treffen musst.
2. Lege für jeden Punkt aus „Umsetzung als Forgejo-Issues“ ein Issue im Forgejo-Repo an (Titel, Ziel, Akzeptanzkriterien aus dem README, betroffene Dateien, Verweis auf den Bildschirm im Spielplatz). Wenn du keinen Zugriff auf Forgejo hast, schreib die Issues als Markdown nach `docs/design/v0.8.0/issues/` und sag mir Bescheid.
3. Setze dann **nur Issue 1** (Verlauf mit festen Zeitfenstern und Zeitraum-Umschalter) um: eigener Branch, kleine Commits, Tests ergänzen, `web/demo.js` anpassen. Danach stoppen und mir zeigen, was sich geändert hat und wie ich es lokal prüfe.

Regeln:
- Bestehendes aus 0.4.0 nicht verändern, außer das README verlangt es.
- Kein Framework einführen, Vanilla JS und die vorhandenen CSS-Bausteine nutzen.
- Dashboard-Texte neutral (nie „du“), Einrichtung und Anmeldung „Sie“. Texte über i18n-Schlüssel, Standard Deutsch bzw. Systemsprache (nicht Deutsch → Englisch).
- Nur neutrale Beispieldaten (runner-vm, beispiel-org, git.example.org, 192.0.2.0/24); das Projekt ist öffentlich.
- Zugangsdaten bleiben nur auf der VM (`einrichten.sh zugang <runner>`), nie über die Weboberfläche.
- Frag nach, bevor du größere Umbauten am Backend-Format (`/api/zustand`) machst.
