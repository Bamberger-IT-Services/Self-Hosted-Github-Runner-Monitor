# Design-Tokens

**Stand: 23.10.2026 · Version 0.1.0** · Quelle der Wahrheit: `:root` in [`web/stil.css`](../../web/stil.css)

| Token | Hell | Dunkel | Verwendung |
|---|---|---|---|
| `--surface` | #ffffff | #0c1a24 | Seitenhintergrund |
| `--surface-alt` | #f6f6f6 | #13283a | Karten |
| `--ink` | #13212b | #eef2f5 | Text |
| `--ink-muted` | #4f5d67 | #a9b6c0 | Nebentext |
| `--border` | #d9dee2 | #2a3f50 | Linien |
| `--border-strong` | #8a96a0 | #62798c | Eingabefelder, hoher Kontrast |
| `--track` | #e2e6e9 | #20384c | Balken-Hintergrund |
| `--brand` | #0e628f | #5aa9d6 | Akzent, „Job läuft“, Knöpfe |
| `--success` | #1f7a4d | #5cc08a | Bereit, Erfolg |
| `--danger` | #b3261e | #f08a80 | Gestoppt, Fehler |
| `--warning` | #9a4d00 | #f0a35e | Offline, Platte knapp, Token läuft ab |
| `--log-bg` | #0f1d27 | #08131b | Terminal (immer dunkel) |
| `--r-sm` / `--r-md` | 2 px / 4 px | | Radien |
| `--feder` | cubic-bezier(.22,1,.36,1) | | Ein- und Ausblenden |

Schrift: Systemschrift (`-apple-system`, `system-ui`), Monospace `ui-monospace`/`SF Mono`.
Raster: Kopf 60 px; Spalten `clamp(400px,27vw,480px) · 1fr · clamp(400px,27vw,480px)`.
Balken federn kritisch gedämpft (Antwortzeit 0,55 s); bei `prefers-reduced-motion` springen sie.
Dunkel folgt dem System, außer `data-thema="hell|dunkel"` auf `<html>` (Umschalter, `localStorage rm-thema`).
