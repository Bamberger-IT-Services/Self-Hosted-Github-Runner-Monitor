# Der selbst gehostete Runner

**Stand: 29.10.2026 · Version 0.8.0**

Dieses Repository ist der eine Ort für den Runner der Organisation: Einrichtung der
Runner-VM, Pflege, Fehlerhilfe und der Monitor. Die Regeln stehen in der gemeinsamen
[Anweisung 01](https://github.com/Bamberger-IT-Services/Public/blob/main/anweisungen/01-runner-ci-release.md);
hier steht die Umsetzung. Das Skript [`deploy/runner-einrichten.sh`](../deploy/runner-einrichten.sh)
ist die projektneutrale Fassung der Vorlage aus dem Public-Repository.

## 1. VM anlegen

- Ubuntu Server 24.04 LTS als **eigene VM** (kein LXC – Docker in LXC macht Ärger), z. B.
  4 vCPU, 8–16 GB RAM (siehe unten), 80 GB Platte. Im Hypervisor die Platte mit **„Discard“** einstellen,
  damit `fstrim` Platz zurückgibt.
- Nur ausgehendes Internet nötig. **Nie** auf einer Produktiv-VM: Jobs laufen faktisch als root.

### Wie viel Arbeitsspeicher?

| Was auf dem Runner läuft | RAM | Swap |
|---|---|---|
| nur leichte Jobs: Lint, Typprüfung, Tests ohne Build, Geheimnis-Scan | 4 GB | 2–4 GB |
| **Builds von Web-Apps und Docker-Images, Datenbank-Tests in Containern** (z. B. `pruefen`, `db-test`, `image-probe`) | **mindestens 8 GB** | 4 GB |
| mehrere große Projekte, Images mit vielen Schichten, Puffer für Wachstum | 12–16 GB | 4 GB |

- **Messwert:** Ein `image-probe`-Job brauchte allein im Runner-Dienst 3,0 GB. Dazu kommen
  Docker (`dockerd`, `containerd`, Build- und Datenbank-Container laufen außerhalb des
  Runner-Dienstes), das System und der Monitor (unter 100 MB). Mit 4 GB RAM ohne Swap hat der
  Kernel den Job deshalb per OOM-Killer beendet. systemd hat dabei den ganzen Runner-Dienst
  gestoppt, und er blieb aus, bis er von Hand neu gestartet wurde (Fehlerhilfe unten).
- **Zum Vergleich:** Die Standard-Linux-Runner von GitHub haben für private Repositories
  2 CPUs und 8 GB RAM, für öffentliche 4 CPUs und 16 GB
  ([GitHub-Doku](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)).
  Was dort durchläuft, braucht auf dem eigenen Runner ähnlich viel.
- Jobs laufen nacheinander (ein Runner, ein Job). Der Bedarf richtet sich also nach dem
  **größten einzelnen Job** plus Containern, die ein voriger Job stehen gelassen hat.
- Swap ist ein Puffer gegen Spitzen und kein Ersatz für RAM: Ein Build im Swap wird sehr langsam.
- Im Monitor zeigt die Karte „Auslastung“ RAM und Swap. Liegt der RAM bei Builds dauerhaft über
  90 % oder wird viel Swap genutzt, braucht die VM mehr Speicher.

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
  jede Nacht gründlich, dazu `fstrim`,
- sichert den Dienst gegen **Speichermangel**: Drop-in `speicher.conf` mit `OOMPolicy=continue`
  (dann scheitert nur der Job, der Dienst läuft weiter) und `Restart=on-failure`. Fehlt Swap,
  legt das Skript `/swapfile` an (4 GB, ab 16 GB RAM 2 GB, nur bei genug freiem Platz) und
  setzt `vm.swappiness=10`. Bei weniger als 8 GB RAM gibt es einen Hinweis (seit 0.6.1).

Ein zweiter Aufruf ohne Token bringt Pakete, Aufräumen und Speicher-Einstellung auf den neuesten Stand und lässt
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
| **Runner-Dienst gestoppt, im Status steht `Result: oom-kill`** (`systemctl status 'actions.runner.*'`) | Ein Job hat den Arbeitsspeicher gesprengt, und systemd hat den ganzen Dienst gestoppt. Abhilfe: mehr RAM (Tabelle oben), Swap anlegen und den Dienst so einstellen, dass nur der Job scheitert und der Dienst nach einem Absturz neu startet. Ab 0.6.1 erledigt `sudo /opt/runner-monitor/aktuell/einrichten.sh runner` das (Abschnitt 3). Von Hand:<br>`U=$(systemctl list-units --all --plain --no-legend 'actions.runner.*' \| awk '{print $1}')`<br>`sudo mkdir -p "/etc/systemd/system/$U.d"`<br>`printf '[Service]\nOOMPolicy=continue\nRestart=on-failure\nRestartSec=15\n' \| sudo tee "/etc/systemd/system/$U.d/speicher.conf"`<br>`sudo systemctl daemon-reload && sudo systemctl restart "$U"` (wenn kein Job läuft)<br>Swap, falls `swapon --show` leer ist: `sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`, dann `/swapfile none swap sw 0 0` in `/etc/fstab` eintragen. |
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
