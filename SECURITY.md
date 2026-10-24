# Sicherheit

## Eine Lücke melden

Bitte **nicht** als öffentliches Issue. Stattdessen vertraulich über GitHub:
Repository › **Security** › **Report a vulnerability**
(„Private vulnerability reporting“). Nur die Betreuer des Repositorys sehen die Meldung.

Hilfreich sind: betroffene Version (Info › Updates im Monitor oder `/api/health`), Schritte zum
Nachstellen und was ein Angreifer damit erreichen kann. Bitte keine echten Zugangsdaten, Tokens
oder Adressen mitschicken.

## Was wir tun

- Eingang bestätigen, Lücke nachstellen und bewerten.
- Behebung in einer neuen Version; der Befund kommt in den
  [Sicherheitsbericht](docs/sicherheit/bericht.md), die Release-Notiz nennt ihn.
- Updates spielen Sie im Monitor über Info › Updates ein ([UPDATE.md](docs/UPDATE.md)).

## Unterstützte Versionen

Nur die jeweils neueste Version erhält Sicherheitskorrekturen.

## Rahmen

Der Monitor ist für den Betrieb im lokalen Netz gedacht (ein Zugang, nur lesend). Einsatzrahmen,
bekannte und akzeptierte Befunde: [Sicherheitsbericht](docs/sicherheit/bericht.md).
