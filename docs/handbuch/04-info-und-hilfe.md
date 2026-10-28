# 4 Info & Hilfe

**Stand: 25.10.2026 · Version 0.7.0**

„Info“ oben rechts öffnet ein Blatt von rechts. Schließen mit „Schließen“, Escape oder einem
Klick daneben.

![Info & Hilfe](bilder/info-hilfe.png)

Das Blatt bleibt beim Lesen ruhig stehen: Nur die Werte darin aktualisieren sich, Position und
aufgeklappte Anleitung bleiben.

| Abschnitt | Inhalt |
|---|---|
| **Updates** | installierte und neueste Version, wann zuletzt geprüft, Knopf **„Jetzt prüfen“** (fragt GitHub sofort, höchstens einmal je Minute; gesperrt, solange ein Update läuft), Neuerungen seit der installierten Version (je Version „Was ist neu“, einmalige Schritte farbig hervorgehoben, ältere Versionen zum Aufklappen), Knopf „Jetzt aktualisieren“ mit Fortschritt (gleich nach einem neuen Release steht dort kurz „wird gerade bereitgestellt“, bis das Paket am Release hängt), Schalter „Automatisch aktualisieren“ (ab 3 Uhr, sobald kein Job läuft, bis 7 Uhr; darunter steht, ob ein Update vorgemerkt ist) ([UPDATE.md](../UPDATE.md)) |
| **Darstellung** | Automatisch (folgt dem System), Hell, Dunkel – gilt für diesen Browser. Derselbe Umschalter sitzt als Knopf in der Kopfzeile. Darunter **Sprache**: Deutsch oder English (Vorgabe: Sprache des Browsers; die Seite lädt beim Wechsel einmal neu). Release-Notizen und Handbuch bleiben deutsch. |
| **Was tun, wenn …** | Schritt-für-Schritt-Anleitungen; jeder Befehl hat einen Knopf **Kopieren**: Token, GitHub nicht erreichbar, Dienst gestoppt, offline, **Runner-Logs abrufen**, Platte knapp, Verbindung zum Monitor, Monitor aktualisieren |
| **GitHub-Verbindung** | Organisation, Token-Zustand, Rechte, Ablaufdatum, letzte und nächste Abfrage, API-Kontingent, Ort der Token-Datei – nur zum Anschauen. Ändern auf der VM: „Was tun, wenn …“ › „GitHub-Token einrichten oder erneuern“ (`sudo /opt/runner-monitor/aktuell/einrichten.sh token`) |
| **Über diesen Monitor** | Version, Adresse, Dienst, Aktualisierungstakt, Ersteller und Link zum Repository |
| **Fehler gefunden oder Idee?** | zeigt die technischen Angaben (Version, System, Runner, Browser) und öffnet das E-Mail-Programm mit einer Nachricht an info@bamberger-it-services.de („Fehler melden“, „Idee vorschlagen“), in der Betreff, Vorlage und diese Angaben schon stehen. Gesendet wird erst, wenn Sie die Mail abschicken. **Keine Tokens oder Passwörter mitschicken, Log-Ausschnitte nur gekürzt einfügen.** Beim fehlgeschlagenen Update gibt es daneben einen Link „Fehler melden“ mit Platz für die Ausgabe von `journalctl -u runner-monitor-update -n 50`. |

## Runner-Logs abrufen

Die Anleitung „Runner-Logs abrufen (Diagnose)“ fasst zusammen, wo der Runner protokolliert:

| Was | Wo |
|---|---|
| Start, Stopp, Abstürze, Job-Start/-Ende | `journalctl -u 'actions.runner.*'` |
| Anmeldung bei GitHub, Verbindungsfehler, Updates | `/opt/actions-runner/_diag/Runner_*.log` |
| Ablauf eines Jobs | `/opt/actions-runner/_diag/Worker_*.log` |
| Ausgabe je Schritt | `/opt/actions-runner/_diag/pages/` |
| abgeschlossene Jobs | GitHub › Repository › Actions › Lauf › Job › „Download log archive“ |
