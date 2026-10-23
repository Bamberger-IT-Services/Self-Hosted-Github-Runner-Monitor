# Datenschutz

**Stand: 23.10.2026 · Version 0.1.0**

Der Runner-Monitor läuft vollständig auf der eigenen VM. Es gibt keine Telemetrie, keine
Analyse, keine externen Schriften oder Skripte.

| Daten | Wo | Wie lange |
|---|---|---|
| Benutzername, Passwort-Hash | `/var/lib/runner-monitor/zugang.json` | bis zum Zurücksetzen |
| Sitzungen (Hash des Tokens, Zeitpunkte) | `sitzungen.json` | bis Ablauf (höchstens 30 Tage) |
| Fehlversuche (IP-Adresse, Zeit) | `sperren.json` | 15 Minuten |
| Systemwerte, Prozesse, Log-Zeilen | nur im Arbeitsspeicher | 10 Minuten bzw. 1500 Zeilen, weg beim Neustart |
| GitHub-Daten (Repository-Namen, Workflow- und Jobnamen, Branch/PR-Titel) | `/run/runner-monitor` (Arbeitsspeicher) | bis zur nächsten Abfrage bzw. Neustart |
| Darstellungswahl hell/dunkel | `localStorage` des Browsers | bis der Browser sie löscht |

Personenbezug: Benutzername und IP-Adressen der Fehlversuche; im Live-Log kann stehen, was
Workflows ausgeben (z. B. Autorennamen von Commits). Nach außen gehen nur Anfragen an die
GitHub-API mit dem hinterlegten Token. Der Knopf „Fehler melden“ öffnet GitHub im Browser mit
Version, Runner-Version und Browserkennung – abgeschickt wird erst, was man selbst bestätigt.

Cookies: nur `rm_sitzung` (Anmeldung) und während der Einrichtung `rm_einrichtung` – beide
technisch notwendig, kein Einwilligungsbanner nötig.
