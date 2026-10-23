// Entwickler-Dashboard: Merkzettel für Aufgaben (A-nn), Entscheidungen (E-nn) und Verlauf.
// Nach jeder Arbeitsrunde pflegen (Anweisung 00). `stand` aus: TZ=Europe/Berlin date +"%d.%m.%Y %H:%M"
window.DATEN = {
  projekt: 'Runner-Monitor',
  repo: 'https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor',
  version: '0.1.2',
  versionStatus: 'Release v0.1.2 veröffentlicht (23.10.2026); Update-Test auf der Runner-VM läuft',
  stand: '23.10.2026 18:16',
  naechsteSchritte: [
    'Auf der VM das Update auf 0.1.1 per Knopf testen, danach Rückweg (A-03)',
    'Abnahme auf der Runner-VM weiterführen (A-03): Live-Log mit echtem Job, Update und Rückweg',
    'Helios-Repo kürzen (A-14, Helios-Chat)',
  ],


  aufgaben: [
    { id: 'A-01', titel: 'Design v1 einfrieren (Canvas + Kopie in docs/design/v1)', status: 'erledigt', prio: 'hoch', bereich: 'Design' },
    { id: 'A-02', titel: 'Version 0.1.0 programmieren: Server, Sammler, Update-Hilfsdienst, Oberfläche, einrichten.sh, Doku, CI', status: 'erledigt', prio: 'hoch', bereich: 'Code', notiz: '36 Unit-Tests, Browser-Rauchtest mit Playwright, shellcheck sauber' },
    { id: 'A-03', titel: 'Abnahme auf einer Test-VM: einrichten.sh (frisch und über alte ttyd-Ansicht), Runner-Erkennung, Firewall, Einrichtung im Browser, Live-Log mit echtem Job, Update und Rückweg mit einem Test-Release', status: 'offen', prio: 'hoch', bereich: 'Betrieb', wer: 'Tobias' },
    { id: 'A-04', titel: 'Branch pushen, PR öffnen, CI grün, mergen', status: 'erledigt', prio: 'hoch', bereich: 'Repo', wer: 'Tobias (Push) / Claude (Merge)', notiz: 'PR #1 am 23.10.2026 gemergt' },
    { id: 'A-05', titel: 'Lizenz festlegen (öffentliches Repo ohne Lizenz = alle Rechte vorbehalten)', status: 'erledigt', prio: 'mittel', bereich: 'Repo', wer: 'Tobias (Entscheidung)', notiz: 'E-11: keine Lizenz' },
    { id: 'A-06', titel: 'Erstes Release veröffentlichen (Tag, Release-Workflow hängt Paket + Prüfsumme an)', status: 'erledigt', prio: 'hoch', bereich: 'Release', wer: 'OK von Tobias', notiz: 'v0.1.1 am 23.10.2026 – zugleich Test für Update und Rückweg' },
    { id: 'A-07', titel: 'GitHub-Kontingent schonen: bedingte Anfragen (ETag/304) und ruhige Repositories seltener abfragen – heute reicht es für ca. 35 Repositories', status: 'offen', prio: 'mittel', bereich: 'Code' },
    { id: 'A-08', titel: 'Liste der 10 000 häufigsten Passwörter statt 20 Einträgen (S-AUTH-02)', status: 'offen', prio: 'niedrig', bereich: 'Sicherheit' },
    { id: 'A-09', titel: 'Anleitung HTTPS über Reverse-Proxy (z. B. Caddy) für Zugriff außerhalb des LAN (S-NET-01)', status: 'offen', prio: 'niedrig', bereich: 'Doku' },
    { id: 'A-10', titel: 'Releases signieren (minisign/Sigstore) und im Update-Hilfsdienst prüfen (S-UPD-01)', status: 'offen', prio: 'mittel', bereich: 'Sicherheit' },
    { id: 'A-11', titel: 'SSE-Verbindungen je Sitzung begrenzen (S-DOS-01)', status: 'offen', prio: 'niedrig', bereich: 'Sicherheit' },
    { id: 'A-12', titel: 'OWASP ZAP Baseline gegen eine Testinstanz, Ergebnis in den Sicherheitsbericht', status: 'offen', prio: 'mittel', bereich: 'Sicherheit' },
    { id: 'A-13', titel: 'GitHub-Einstellungen: Branch-Schutz main mit Pflicht-Check CI, „Private vulnerability reporting“ an, Issue-Labels fehler/idee', status: 'offen', prio: 'mittel', bereich: 'Repo', wer: 'Tobias (Einstellungen bei GitHub nur nach OK)' },
    { id: 'A-14', titel: 'Helios-Repo: docs/RUNNER.md kürzen und hierher verweisen, deploy/runner/runner-einrichten.sh entfernen', status: 'offen', prio: 'mittel', bereich: 'Helios', wer: 'Helios-Chat' },
    { id: 'A-15', titel: 'Docker-Ansicht (Daten werden schon gesammelt)', status: 'später', prio: 'niedrig', bereich: 'Code' },
    { id: 'A-16', titel: 'Mehrere Runner je VM', status: 'später', prio: 'niedrig', bereich: 'Code' },
    { id: 'A-17', titel: 'Klären: Projektanweisung sagt „Als Docker sollte es dennoch funktionieren“ – widerspricht E-02/ADR-0002 (kein Docker). Optionaler Container (privilegiert, --pid=host, Journal- und Runner-Mounts) zusätzlich zum systemd-Dienst?', status: 'erledigt', prio: 'mittel', bereich: 'Entscheidung', wer: 'Tobias', notiz: 'E-12: kein Docker, auch nicht zusätzlich' },
    { id: 'A-18', titel: 'Info-Blatt baute sich jede Sekunde neu auf; Live-Log ließ sich nicht hochscrollen; einrichten.sh token vergaß die Organisation', status: 'erledigt', prio: 'hoch', bereich: 'Code', notiz: 'Version 0.1.1' },
    { id: 'A-20', titel: 'Netzwerkauslastung in der Karte Auslastung (empfangen, gesendet, Spitze 10 Min.)', status: 'erledigt', prio: 'mittel', bereich: 'Code', notiz: 'Wunsch Tobias, Version 0.1.1' },
    { id: 'A-21', titel: 'Knopf „Jetzt prüfen“ in Info › Updates (Release sofort abfragen)', status: 'erledigt', prio: 'mittel', bereich: 'Code', notiz: 'Wunsch Tobias, Version 0.1.2' },
    { id: 'A-19', titel: 'Public-Repo: Anweisung 01 verweist zur Runner-Einrichtung auf dieses Repo, vorlagen/runner-einrichten.sh entfällt (Entscheidung „alles hierher verschieben“)', status: 'erledigt', prio: 'mittel', bereich: 'Public', wer: 'Claude', notiz: 'Public PR #15' },
  ],

  entscheidungen: [
    { id: 'E-01', datum: '23.10.2026', titel: 'Anmeldung nur mit Passwort, keine 2FA (Abweichung von Anweisung 03)', von: 'Tobias', beleg: 'docs/adr/0003-nur-passwort.md' },
    { id: 'E-02', datum: '23.10.2026', titel: 'Normaler systemd-Dienst statt Docker', von: 'Tobias', beleg: 'docs/adr/0002-systemd-statt-docker.md' },
    { id: 'E-03', datum: '23.10.2026', titel: 'Updates aus GitHub-Releases per Knopf über root-Hilfsdienst (Variante 2)', von: 'Tobias', beleg: 'docs/adr/0004-update-hilfsdienst.md' },
    { id: 'E-04', datum: '23.10.2026', titel: 'Design v1 eingefroren als Grundlage für 0.1.0', von: 'Tobias', beleg: 'docs/design/README.md' },
    { id: 'E-05', datum: '23.10.2026', titel: 'Docker-Container in 0.1 nicht anzeigen', von: 'Tobias' },
    { id: 'E-06', datum: '23.10.2026', titel: 'Prozesse und Platten in einer Karte, Log breiter und höher, Top 6 Prozesse', von: 'Tobias' },
    { id: 'E-07', datum: '23.10.2026', titel: 'Meldungen zentral in der Kopfzeile mit „Was tun?“ zur Anleitung', von: 'Tobias' },
    { id: 'E-08', datum: '23.10.2026', titel: 'Ersteinrichtung: Skript auf der VM → Code im Browser → Zugang → GitHub → Anmeldung', von: 'Tobias' },
    { id: 'E-09', datum: '23.10.2026', titel: 'Python-Standardbibliothek statt Next.js', von: 'Tobias', beleg: 'docs/adr/0001-python-standardbibliothek.md' },
    { id: 'E-10', datum: '23.10.2026', titel: 'Ansprache „Sie“ in Anmeldung/Einrichtung, neutral im Dashboard (Design v1 hatte „du“)', von: 'Claude (Anweisungen)' },
    { id: 'E-11', datum: '23.10.2026', titel: 'Keine Lizenz – alle Rechte vorbehalten, Code nur zum Lesen öffentlich', von: 'Tobias' },
    { id: 'E-12', datum: '23.10.2026', titel: 'Kein Docker-Container, auch nicht zusätzlich (Projektanweisung „Als Docker …“ gilt nicht)', von: 'Tobias' },
  ],

  abweichungen: [
    ['02 Stack', 'Python-Standardbibliothek, JSON-Dateien statt Next.js/Postgres', 'ADR-0001'],
    ['01 Release', 'tar.gz + SHA-256 am Release statt GHCR-Images', 'ADR-0002'],
    ['03 Zwei-Faktor', 'nur Passwort', 'ADR-0003'],
    ['04 CSP mit Nonce', 'script-src \'self\' ohne Inline-Skripte', 'S-CSP-01'],
    ['01 CI auf eigenem Runner', 'öffentliches Repo → immer ubuntu-latest', 'Anweisung 01 selbst'],
  ],

  verlauf: [
    { datum: '23.10.2026 18:16', text: '0.1.2: Knopf „Jetzt prüfen“ in Info › Updates (Auftrag release-pruefen an den Sammler, höchstens einmal je Minute). Release v0.1.1 veröffentlicht (Workflow grün, Prüfsumme geprüft).' },
    { datum: '23.10.2026 18:04', text: 'Release v0.1.1 (OK Tobias): CHANGELOG, Release-Notiz, Doku-Stand, Bildschirmfotos neu. Public-Repo: Anweisung 01 verweist zur Runner-Einrichtung hierher (PR #15).' },
    { datum: '23.10.2026 17:56', text: 'Netzwerkauslastung ergänzt (Zeile „Netz“ in der Auslastung, /proc/net/dev ohne virtuelle Schnittstellen). PR #4 und Dependabot #2/#3 gemergt.' },
    { datum: '23.10.2026 17:49', text: '0.1.1: Info-Blatt bleibt ruhig stehen, Live-Log lässt sich hochscrollen, Token-Befehl im Info-Menü, einrichten.sh token fragt die Organisation. Entscheidungen E-11 (keine Lizenz) und E-12 (kein Docker) nachgetragen.' },
    { datum: '23.10.2026 16:29', text: 'Version 0.1.0 programmiert: Server, Sammler, Update-Hilfsdienst, Oberfläche nach Design v1, einrichten.sh (inkl. Runner-Einrichtung und Ablösung der ttyd-Ansicht), Doku (Funktionsweise, Handbuch mit Bildern, Einrichtung, Update, Runner, Runbooks, Sicherheit), CI und Release-Workflow. Tests und Browser-Rauchtest grün.' },
    { datum: '23.10.2026', text: 'Design v1 abgestimmt und eingefroren (21 Bildschirme inkl. Einrichtung, Anmeldung, Updates). Entscheidungen E-01 bis E-08.' },
  ],

  links: [
    ['Repository', 'https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor'],
    ['Gemeinsame Anweisungen', 'https://github.com/Bamberger-IT-Services/Public/tree/main/anweisungen'],
    ['Funktionsweise', '../docs/FUNKTIONSWEISE.md'],
    ['Handbuch', '../docs/handbuch/README.md'],
    ['Sicherheitsbericht', '../docs/sicherheit/bericht.md'],
    ['Design-Abgleich', '../docs/design/README.md'],
    ['Entscheidungen', '../DECISIONS.md'],
  ],
};
