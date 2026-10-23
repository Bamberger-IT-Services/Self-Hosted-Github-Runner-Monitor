# Der selbst gehostete Runner

**Stand: 23.10.2026 · Version 0.1.2**

Dieses Repository ist der eine Ort für den Runner der Organisation: Einrichtung der
Runner-VM, Pflege, Fehlerhilfe und der Monitor. Die Regeln stehen in der gemeinsamen
[Anweisung 01](https://github.com/Bamberger-IT-Services/Public/blob/main/anweisungen/01-runner-ci-release.md);
hier steht die Umsetzung. Das Skript [`deploy/runner-einrichten.sh`](../deploy/runner-einrichten.sh)
ist die projektneutrale Fassung der Vorlage aus dem Public-Repository.

## 1. VM anlegen

- Ubuntu Server 24.04 LTS als **eigene VM** (kein LXC – Docker in LXC macht Ärger), z. B.
  4 vCPU, 12–16 GB RAM, 80 GB Platte. Im Hypervisor die Platte mit **„Discard“** einstellen,
  damit `fstrim` Platz zurückgibt.
- Nur ausgehendes Internet nötig. **Nie** auf einer Produktiv-VM: Jobs laufen faktisch als root.

## 2. Registrierungs-Token holen

GitHub › Organisation › Settings › Actions › Runners › „New runner“ › „New self-hosted runner“ ›
Linux. Nur den Wert hinter `--token` kopieren. Er gilt eine Stunde und gehört nicht in Chats
oder Notizen.

## 3. Einrichten

Mit dem Monitor zusammen (empfohlen) – das Paket herunterladen wie in
[EINRICHTUNG.md](EINRICHTUNG.md), dann:

```bash
sudo RUNNER_LABELS=bits ./einrichten.sh            # Monitor; fehlt der Runner, fragt das Skript
# oder nur den Runner:
sudo RUNNER_LABELS=bits ./einrichten.sh runner
```

`RUNNER_LABELS=bits` gilt für Bamberger-IT-Services (Label „eigene Maschine“, Anweisung 01);
andere Organisationen wählen eigene Labels oder keine.

Das Skript

- installiert Docker und Werkzeuge (git, jq, Python, Build-Tools …),
- legt den Benutzer `github-runner` an (sudo ohne Passwort, weil Workflows Pakete installieren; Gruppe `docker`),
- lädt die neueste Runner-Version, meldet sie bei der Organisation an und startet den Dienst
  `actions.runner.<organisation>.<name>.service`,
- richtet das **Aufräumen** ein: vor jedem Job unter 25 GB frei (`runner-aufraeumen 25`),
  jede Nacht gründlich, dazu `fstrim`.

Ein zweiter Aufruf ohne Token bringt Pakete und Aufräumen auf den neuesten Stand und lässt
einen registrierten Runner stehen; ein laufender Job wird nie unterbrochen.

Prüfen: `sudo systemctl status 'actions.runner.*'` → `active (running)`; in GitHub steht der Runner auf „Idle“.

## 4. Repositories umschalten

Jeder Workflow wählt seinen Rechner so:

```yaml
runs-on: ${{ fromJSON(vars.EIGENER_RUNNER || '"ubuntu-latest"') }}
```

Je **privatem** Repository: Settings › Secrets and variables › Actions › Variables ›
„New repository variable“: `EIGENER_RUNNER` = `["self-hosted","bits"]` (genau so). Im
kostenlosen GitHub-Tarif gelten Organisations-Variablen nur für öffentliche Repositories.
Rückweg bei Ausfall der VM: Variable löschen → GitHubs Rechner.

**Öffentliche Repositories** (wie dieses) nutzen den eigenen Runner nie – sonst könnte jeder
per Pull Request Code auf der VM ausführen. In der Runner-Gruppe „Default“ bleibt
„Allow public repositories“ aus.

## 5. Umzug eines bestehenden Runners

War der Runner bisher nur bei einem Repository angemeldet (oder wurde er in GitHub gelöscht):

```bash
sudo RUNNER_LABELS=bits ./einrichten.sh runner --umziehen    # Organisations-Token angeben
```

Danach den alten Eintrag im Repository unter Settings › Actions › Runners entfernen, ebenso
eine alte Repository-Variable für den Runner.

## 6. Pflege

| Was | Wie |
|---|---|
| Platz | Monitor zeigt „/“ mit Schwelle. Von Hand: `sudo runner-aufraeumen`, `docker system df`, `sudo fstrim -av` |
| Runner-Updates | aktualisiert sich selbst (Diagnose: `_diag/Runner_*.log`) |
| Ubuntu-Updates | `sudo apt update && sudo apt upgrade`; Neustart nur, wenn kein Job läuft (Monitor: „Bereit“) |
| Neustart des Runners | `sudo systemctl restart 'actions.runner.*'` – wartet nicht auf laufende Jobs, also vorher im Monitor prüfen |
| Monitor | [UPDATE.md](UPDATE.md) |

## 7. Fehlerhilfe

| Anzeichen | Ursache und Abhilfe |
|---|---|
| **Job hängt auf „Queued“** | Kein passender Runner frei: Labels im `runs-on` passen nicht (z. B. `bits` fehlt am Runner), Variable `EIGENER_RUNNER` falsch geschrieben, Runner offline oder belegt (Jobs laufen nacheinander). Monitor zeigt „wartet“ je Repository. Labels prüfen: GitHub › Organisation › Settings › Actions › Runners. |
| **Runner offline** | [Runbook runner-dienst-gestoppt](runbooks/runner-dienst-gestoppt.md) |
| **„Instanz ci existiert schon“** (Wegwerf-Datenbank eines abgebrochenen Laufs) | Reste des vorigen Laufs: `docker ps -a`, dann die Container des Projekts stoppen und entfernen (`docker rm -f <name>`); gründlich: `sudo runner-aufraeumen`. Der nächste Lauf legt sie neu an. |
| **„No space left on device“** | [Runbook platte-voll](runbooks/platte-voll.md) |
| **Node fehlt** | Auf dem eigenen Runner ist Node nicht vorinstalliert: `actions/setup-node` mit `node-version-file: .nvmrc` |
| **Runner nimmt nach Löschung in GitHub nichts an** | `sudo ./einrichten.sh runner --umziehen` |

Diagnose sammeln: Info › „Runner-Logs abrufen“ im Monitor oder [Handbuch Kap. 4](handbuch/04-info-und-hilfe.md#runner-logs-abrufen).

## 8. Sicherheit

- Jobs laufen als `github-runner` mit sudo und Docker – **faktisch root**. Nur eigene, private
  Repositories dürfen den Runner nutzen.
- Das GitHub-Token des Monitors ist nur lesend; es liegt root-only, ist für einen bösartigen
  Job mit sudo aber erreichbar (Sicherheitsbericht S-HOST-01). Kurze Laufzeit wählen.
- Port 8090 des Monitors nur aus dem LAN (Firewall-Regel des Einrichtungsskripts).
