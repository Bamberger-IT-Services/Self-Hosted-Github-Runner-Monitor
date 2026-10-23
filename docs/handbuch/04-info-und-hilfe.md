# 4 Info & Hilfe

**Stand: 23.10.2026 · Version 0.1.0**

„Info“ oben rechts öffnet ein Blatt von rechts. Schließen mit „Schließen“, Escape oder einem
Klick daneben.

![Info & Hilfe](bilder/info-hilfe.png)

| Abschnitt | Inhalt |
|---|---|
| **Updates** | installierte und neueste Version, wann zuletzt geprüft, Neuerungen, Knopf „Jetzt aktualisieren“ mit Fortschritt, Schalter „Automatisch aktualisieren“ ([UPDATE.md](../UPDATE.md)) |
| **Darstellung** | Automatisch (folgt dem System), Hell, Dunkel – gilt für diesen Browser. Derselbe Umschalter sitzt als Knopf in der Kopfzeile. |
| **Was tun, wenn …** | Schritt-für-Schritt-Anleitungen mit Befehlen zum Kopieren: Token, GitHub nicht erreichbar, Dienst gestoppt, offline, **Runner-Logs abrufen**, Platte knapp, Verbindung zum Monitor, Monitor aktualisieren |
| **GitHub-Verbindung** | Organisation, Token-Zustand, Rechte, Ablaufdatum, letzte und nächste Abfrage, API-Kontingent, Ort der Token-Datei |
| **Über diesen Monitor** | Version, Adresse, Dienst, Aktualisierungstakt, Ersteller und Link zum Repository |
| **Fehler gefunden oder Idee?** | öffnet ein vorbereitetes GitHub-Issue (Version, Runner-Version und Browser sind eingetragen). **Keine IPs, Namen oder Tokens hineinschreiben – das Repository ist öffentlich.** |

## Runner-Logs abrufen

Die Anleitung „Runner-Logs abrufen (Diagnose)“ fasst zusammen, wo der Runner protokolliert:

| Was | Wo |
|---|---|
| Start, Stopp, Abstürze, Job-Start/-Ende | `journalctl -u 'actions.runner.*'` |
| Anmeldung bei GitHub, Verbindungsfehler, Updates | `/opt/actions-runner/_diag/Runner_*.log` |
| Ablauf eines Jobs | `/opt/actions-runner/_diag/Worker_*.log` |
| Ausgabe je Schritt | `/opt/actions-runner/_diag/pages/` |
| abgeschlossene Jobs | GitHub › Repository › Actions › Lauf › Job › „Download log archive“ |
