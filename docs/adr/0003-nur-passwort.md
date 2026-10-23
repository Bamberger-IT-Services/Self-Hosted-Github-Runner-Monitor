# ADR-0003: Anmeldung nur mit Passwort (ohne Zwei-Faktor)

**Status:** angenommen (Abweichung von Anweisung 03)
**Datum:** 2026-10-23 · **Entschieden von:** Tobias (Auswahlfrage: „Nur Passwort, Abweichung“), E-01

## Ausgangslage
Anweisung 03 verlangt Zwei-Faktor (Passkey/TOTP) für Konten. Der Monitor hat einen einzigen
Zugang, ist nur im LAN erreichbar, nur lesend und zeigt keine Geheimnisse.

## Entscheidung
Benutzer + Passwort (scrypt, Sperre nach Fehlversuchen, Sitzungen mit Ablauf), keine 2FA.

## Betrachtete Möglichkeiten
- **A: nur Passwort** – einfach, passt zum Risiko.
- **B: TOTP** – mehr Aufwand in Einrichtung und Wiederherstellung (Wiederherstellungscodes),
  geringer Gewinn bei LAN-only und nur lesendem Zugriff.
- **C: gar keine Anmeldung** (wie im ersten Brief) – verworfen: Repository- und Jobnamen sind
  interne Informationen, und es gibt den Update-Knopf.

## Folgen
- Sicherheitsbericht S-AUTH-01 (akzeptiert).
- neu prüfen, wenn: der Monitor aus dem Internet erreichbar sein soll oder schreibende Funktionen bekommt.
