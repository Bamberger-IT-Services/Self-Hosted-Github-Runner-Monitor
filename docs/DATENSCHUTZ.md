# Datenschutz

**Stand: 29.10.2026 · Version 0.8.0 (in Arbeit)**

Der Runner-Monitor läuft vollständig auf der eigenen VM. Es gibt keine Telemetrie, keine
Analyse, keine externen Schriften oder Skripte.

| Daten | Wo | Wie lange |
|---|---|---|
| Benutzername, Passwort-Hash | `/var/lib/runner-monitor/zugang.json` | bis zum Zurücksetzen |
| Sitzungen (Hash des Tokens, Zeitpunkte) | `sitzungen.json` | bis Ablauf (höchstens 30 Tage) |
| Fehlversuche (IP-Adresse, Zeit) | `sperren.json` | 15 Minuten |
| Verlauf von CPU, RAM und Netz (Prozentwerte, Bytes je Sekunde) | `verlauf.json` (alle 10 s gesichert) | 10 Minuten; nach mehr als 60 s Pause verworfen |
| Prozesse, Log-Zeilen | nur im Arbeitsspeicher | 1500 Zeilen, weg beim Neustart |
| GitHub-Daten (Repository-Namen, Workflow- und Jobnamen, Branch/PR-Titel) | `/run/runner-monitor` (Arbeitsspeicher) | bis zur nächsten Abfrage bzw. Neustart |
| Darstellungswahl hell/dunkel | `localStorage` des Browsers | bis der Browser sie löscht |

Personenbezug: Benutzername und IP-Adressen der Fehlversuche; im Live-Log kann stehen, was
Workflows ausgeben (z. B. Autorennamen von Commits). Nach außen gehen nur Anfragen an die
GitHub-API mit dem hinterlegten Token. 

**E-Mail an Bamberger IT Services:** Die Knöpfe unter Info › „Fehler gefunden oder Idee?“ öffnen das
E-Mail-Programm mit einer vorbereiteten Nachricht an info@bamberger-it-services.de (Bamberger IT
Services, Ersteller des Monitors). Der Browser setzt die Vorlage zusammen; der Monitor selbst
verschickt nichts und stellt keine Verbindung her. Abgeschickt wird erst, was man selbst sendet; vorher
lässt sich alles ändern oder löschen. In der Vorlage stehen:

| Knopf | Angaben in der Mail |
|---|---|
| Idee vorschlagen | Monitor-Version |
| Fehler melden (Info-Blatt) | Monitor-Version, System (Betriebssystem, Python-Version), Runnername mit Dienst und Version, Dienstzustand des Runners, Browserkennung (User-Agent, gekürzt) |
| Fehler melden (fehlgeschlagenes Update) | wie „Fehler melden“, dazu alte und neue Version und die Meldung des Aktualisierers; die Ausgabe von `journalctl -u runner-monitor-update -n 50` fügt man bei Bedarf selbst ein |

Token-ähnliche Zeichenfolgen werden entfernt; der Hinweis bittet, keine Tokens oder Passwörter und Logs
nur gekürzt mitzuschicken. Absender und Inhalt der Mail sind dann Sache des E-Mail-Programms.

Cookies: nur `rm_sitzung` (Anmeldung) und während der Einrichtung `rm_einrichtung` – beide
technisch notwendig, kein Einwilligungsbanner nötig.
