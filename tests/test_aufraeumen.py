"""Aufräumen der Platte für alle Runner (#144).

- ``runner_monitor.aufraeumen``: Der Sammler (root) prüft ohne Symlinks zu folgen, ob Skript, nächtlicher Lauf,
  Timer und Hook vor dem Job eingerichtet sind; der Monitor übernimmt nur geprüfte Felder.
- ``deploy/runner-aufraeumen``: gründlich, wenn kein Job läuft, sonst schonend; Schwelle; Hook vor dem Job.
- ``deploy/aufraeumen-einrichten.sh``: idempotent, Hook nur einmal in ``.env``, fremder Hook bleibt.
Die Shell-Skripte laufen mit Attrappen für docker, df, pgrep, systemctl … (kein root, keine echte Platte).
"""
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runner_monitor import aufraeumen, sammler, zustand
from tests.test_anbieter import lade_konfig

WURZEL = Path(__file__).resolve().parent.parent
SKRIPT = WURZEL / "deploy" / "runner-aufraeumen"
EINRICHTEN = WURZEL / "deploy" / "aufraeumen-einrichten.sh"
UID = os.getuid()


def ausfuehrbar(pfad: Path, text: str, modus: int = 0o755) -> Path:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(text, encoding="utf-8")
    pfad.chmod(modus)
    return pfad


class PruefeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        self.skript = self.d / "usr/local/bin/runner-aufraeumen"
        self.nacht = self.d / "etc/cron.daily/runner-aufraeumen"
        self.runner = self.d / "actions-runner"

    def pruefe(self, timer: bool = True) -> dict:
        return aufraeumen.pruefe(self.runner, skript=self.skript, nacht=self.nacht,
                                 timer_aktiv=lambda name: timer and name == "runner-aufraeumen.timer", besitzer=UID)

    def test_nichts_eingerichtet(self):
        self.assertEqual(self.pruefe(timer=False), {"skript": False, "nacht": False, "timer": False, "vorDemJob": None})

    def test_alles_eingerichtet_mit_hook(self):
        ausfuehrbar(self.skript, "#!/bin/sh\n")
        ausfuehrbar(self.nacht, "#!/bin/sh\n/usr/local/bin/runner-aufraeumen >/dev/null 2>&1\n")
        (self.runner).mkdir()
        (self.runner / ".runner").write_text("{}")
        ausfuehrbar(self.runner / "vor-dem-job.sh", "#!/bin/sh\nexec /usr/local/bin/runner-aufraeumen --vor-dem-job 25\n")
        (self.runner / ".env").write_text(f"LANG=C.UTF-8\nACTIONS_RUNNER_HOOK_JOB_STARTED={self.runner}/vor-dem-job.sh\n")
        self.assertEqual(self.pruefe(), {"skript": True, "nacht": True, "timer": True, "vorDemJob": True})

    def test_symlink_zaehlt_nie(self):
        ziel = ausfuehrbar(self.d / "woanders", "#!/bin/sh\n/usr/local/bin/runner-aufraeumen\n")
        self.skript.parent.mkdir(parents=True)
        self.skript.symlink_to(ziel)
        self.nacht.parent.mkdir(parents=True)
        self.nacht.symlink_to(ziel)
        st = self.pruefe()
        self.assertFalse(st["skript"])
        self.assertFalse(st["nacht"])

    def test_schreibbar_fuer_andere_oder_nicht_ausfuehrbar(self):
        ausfuehrbar(self.skript, "#!/bin/sh\n", 0o775)
        self.assertFalse(self.pruefe()["skript"])
        self.skript.chmod(0o644)
        self.assertFalse(self.pruefe()["skript"])
        self.skript.chmod(0o755)
        self.assertTrue(self.pruefe()["skript"])
        # fremder Besitzer (hier: jemand anderes als root bzw. der Testbenutzer)
        self.assertFalse(aufraeumen.pruefe(self.runner, skript=self.skript, nacht=self.nacht,
                                           timer_aktiv=lambda _: False, besitzer=UID + 1)["skript"])

    def test_nacht_muss_das_skript_aufrufen(self):
        ausfuehrbar(self.nacht, "#!/bin/sh\necho anderes\n")
        self.assertFalse(self.pruefe()["nacht"])

    def test_hook_falsch_oder_umgelenkt(self):
        self.runner.mkdir()
        (self.runner / ".runner").write_text("{}")
        self.assertIs(self.pruefe()["vorDemJob"], False)  # keine .env
        hook = ausfuehrbar(self.runner / "vor-dem-job.sh", "#!/bin/sh\nexec /usr/local/bin/runner-aufraeumen --vor-dem-job 25\n")
        # die letzte Zeile gilt wie beim Runner
        (self.runner / ".env").write_text(f"ACTIONS_RUNNER_HOOK_JOB_STARTED={hook}\nACTIONS_RUNNER_HOOK_JOB_STARTED=/tmp/anderes.sh\n")
        self.assertIs(self.pruefe()["vorDemJob"], False)
        (self.runner / ".env").write_text(f"ACTIONS_RUNNER_HOOK_JOB_STARTED={hook}\n")
        self.assertIs(self.pruefe()["vorDemJob"], True)
        # .env als Symlink: nicht gelesen
        echt = self.d / "env-echt"
        echt.write_text(f"ACTIONS_RUNNER_HOOK_JOB_STARTED={hook}\n")
        (self.runner / ".env").unlink()
        (self.runner / ".env").symlink_to(echt)
        self.assertIs(self.pruefe()["vorDemJob"], False)
        # Hook ruft das Skript nicht auf
        (self.runner / ".env").unlink()
        (self.runner / ".env").write_text(f"ACTIONS_RUNNER_HOOK_JOB_STARTED={hook}\n")
        hook.write_text("#!/bin/sh\necho nichts\n")
        self.assertIs(self.pruefe()["vorDemJob"], False)

    def test_lies_blockiert_nicht_und_ist_begrenzt(self):
        fifo = self.d / "fifo"
        os.mkfifo(fifo)
        self.assertIsNone(aufraeumen.lies(fifo))
        gross = self.d / "gross"
        gross.write_bytes(b"x" * (aufraeumen.MAX_LESEN + 1))
        self.assertIsNone(aufraeumen.lies(gross))
        self.assertIsNone(aufraeumen.lies(self.d / "fehlt"))

    def test_timer_ohne_systemctl(self):
        alt = os.environ.get("PATH", "")
        os.environ["PATH"] = str(self.d)  # kein systemctl
        try:
            self.assertFalse(aufraeumen._timer_aktiv("runner-aufraeumen.timer"))
        finally:
            os.environ["PATH"] = alt


class StandTest(unittest.TestCase):
    def test_nur_bekannte_felder_und_typen(self):
        gut = {"skript": True, "nacht": False, "timer": True, "vorDemJob": None, "geprueft": 1.5, "boese": "<script>"}
        self.assertEqual(aufraeumen.pruefe_stand(gut),
                         {"skript": True, "nacht": False, "timer": True, "vorDemJob": None, "geprueft": 1.5})
        for kaputt in (None, [], "x", {**gut, "skript": "true"}, {**gut, "timer": None}, {**gut, "vorDemJob": 1}):
            self.assertIsNone(aufraeumen.pruefe_stand(kaputt), kaputt)
        self.assertIsNone(aufraeumen.pruefe_stand({**gut, "geprueft": float("nan")})["geprueft"])
        self.assertIsNone(aufraeumen.pruefe_stand({**gut, "geprueft": True})["geprueft"])


class SammlerZustandTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        self.k = lade_konfig(self.d)
        (self.d / "lauf").mkdir()

    def test_sammler_schreibt_nur_bei_aenderung_und_monitor_uebernimmt(self):
        s = sammler.Sammler(self.k)
        stand = {"skript": True, "nacht": True, "timer": False, "vorDemJob": None}
        datei = self.k.lauf_verz / "aufraeumen.json"
        with mock.patch.object(aufraeumen, "pruefe", return_value=dict(stand)) as pruefe:
            s.aufraeumen(100.0)
            self.assertEqual(json.loads(datei.read_text()), {**stand, "geprueft": 100.0})
            self.assertEqual(stat.S_IMODE(datei.stat().st_mode), 0o644)
            s.aufraeumen(130.0)  # vor dem nächsten Takt: keine Prüfung
            self.assertEqual(pruefe.call_count, 1)
            s.aufraeumen(160.0)  # Takt, unverändert: nicht neu geschrieben
            self.assertEqual(pruefe.call_count, 2)
            self.assertEqual(json.loads(datei.read_text())["geprueft"], 100.0)
            pruefe.return_value = {**stand, "timer": True}
            s.aufraeumen(220.0)
            self.assertEqual(json.loads(datei.read_text()), {**stand, "timer": True, "geprueft": 220.0})
        z = zustand.Zustand(self.k)
        z._github_dateien()
        self.assertEqual(z.bereiche["aufraeumen"], {**stand, "timer": True, "geprueft": 220.0})
        self.assertEqual(z.zustand_api()["aufraeumen"]["timer"], True)

    def test_monitor_verwirft_kaputte_datei(self):
        (self.k.lauf_verz / "aufraeumen.json").write_text(json.dumps({"skript": "ja"}))
        z = zustand.Zustand(self.k)
        z._github_dateien()
        self.assertNotIn("aufraeumen", z.bereiche)
        self.assertNotIn("aufraeumen", z.zustand_api())


# Attrappe für docker: protokolliert jeden Aufruf; Lage aus $LAGE (JSON): „namen“ der laufenden Container,
# „images“ {id: {"tags": [...], "tagzeit": Unix-Zeit}}, „container“ {id: image-id}, „events“ [Actor.ID …],
# „ref“ {name: image-id}; „kaputt“: true → jeder Aufruf scheitert (Docker nicht erreichbar).
DOCKER = """#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
with open(os.environ["PROTOKOLL"], "a", encoding="utf-8") as f:
    f.write(" ".join(a) + "\\n")
try:
    with open(os.environ["LAGE"], encoding="utf-8") as f:
        lage = json.load(f)
except (KeyError, OSError, ValueError):
    lage = {}
if lage.get("kaputt"):
    sys.exit(1)
images, container = lage.get("images", {}), lage.get("container", {})
def ref(n):
    return n if n in images else lage.get("ref", {}).get(n)
if a[:2] == ["ps", "--format"]:
    print("\\n".join(lage.get("namen", [])))
elif a[:2] == ["ps", "-aq"]:
    print("\\n".join(container))
elif a[:1] == ["inspect"]:
    print("\\n".join(container[c] for c in a[3:] if c in container))
elif a[:2] == ["image", "ls"]:
    print("\\n".join(i for i, d in images.items() for _ in (d.get("tags") or [None])))
elif a[:2] == ["image", "inspect"]:
    fmt, ziele, fehler = a[3], a[4:], 0
    for z in ziele:
        i = ref(z)
        if i not in images:
            fehler = 1
            continue
        if "LastTagTime" in fmt:
            print(i, images[i].get("tagzeit", -62135596800))
        elif "RepoTags" in fmt:
            print("".join(t + " " for t in images[i].get("tags", [])))
        else:
            print(i)
    sys.exit(fehler)
elif a[:1] == ["events"]:
    print("\\n".join(lage.get("events", [])))
"""


def sha(zeichen: str) -> str:
    return "sha256:" + zeichen * 64


@unittest.skipUnless(shutil.which("sh"), "sh fehlt")
class SkriptTest(unittest.TestCase):
    """deploy/runner-aufraeumen mit Attrappen: df meldet $FREI GB, pgrep -fc zählt $WORKER, docker liest $LAGE."""

    SHELL = "sh"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        self.bin = self.d / "bin"
        ausfuehrbar(self.bin / "docker", DOCKER)
        ausfuehrbar(self.bin / "df", '#!/bin/sh\necho "Avail"\necho " ${FREI}G"\n')
        ausfuehrbar(self.bin / "pgrep", '#!/bin/sh\necho "${WORKER:-0}"\n[ "${WORKER:-0}" -gt 0 ]\n')
        ausfuehrbar(self.bin / "journalctl", "#!/bin/sh\nexit 0\n")
        self.protokoll = self.d / "docker.log"
        self.lage = self.d / "lage.json"
        self.w = self.d / "wurzel"
        self.liste = self.w / "var/lib/runner-aufraeumen/images"

    def lauf(self, *argumente: str, frei: int = 10, worker: int = 0, container: str = "",
             lage: dict | None = None, wurzel: bool = True) -> subprocess.CompletedProcess:
        self.protokoll.write_text("")
        self.lage.write_text(json.dumps({"namen": [n for n in container.splitlines() if n], **(lage or {})}))
        umgebung = {"PATH": f"{self.bin}:/usr/bin:/bin", "FREI": str(frei), "WORKER": str(worker),
                    "PROTOKOLL": str(self.protokoll), "LAGE": str(self.lage), "LANG": "C.UTF-8"}
        if wurzel:
            umgebung["AUFRAEUMEN_WURZEL"] = str(self.w)
        return subprocess.run([self.SHELL, str(SKRIPT), *argumente], capture_output=True, text=True, env=umgebung, timeout=60, check=False)

    def befehle(self) -> list[str]:
        return [z for z in self.protokoll.read_text().splitlines()
                if not z.startswith(("ps", "image ls", "image inspect", "inspect", "events"))]

    def gemerkt(self) -> dict[str, int]:
        return {z.split()[0]: int(z.split()[1]) for z in self.liste.read_text().splitlines()}

    def test_ueber_der_schwelle_nichts(self):
        r = self.lauf("25", frei=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.befehle(), [])  # nur die Liste der Images wird gelesen
        self.assertEqual(r.stdout, "")

    @unittest.skipIf(os.geteuid() == 0, "als root ist jedes Verzeichnis schreibbar (Forgejo-CI läuft als root)")
    def test_ohne_schreibrecht_kein_docker_aufruf(self):
        r = self.lauf("25", frei=30, wurzel=False)  # /var/lib/runner-aufraeumen nicht schreibbar (kein root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.protokoll.read_text(), "")

    def test_gruendlich_ohne_job(self):
        r = self.lauf("25", frei=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        b = self.befehle()
        self.assertIn("container prune -f", b)
        self.assertIn("volume prune -af", b)
        self.assertIn("image prune -af --filter until=24h", b)
        self.assertIn("(gruendlich)", r.stdout)

    def test_gruendlich_docker_vor_23(self):
        """volume prune -af scheitert (Docker < 23 kennt -a nicht) → volume prune -f."""
        ausfuehrbar(self.bin / "docker", '#!/bin/sh\necho "$*" >> "$PROTOKOLL"\n'
                    'case "$*" in "volume prune -af") exit 1 ;; esac\nexit 0\n')
        r = self.lauf(frei=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        b = self.befehle()
        self.assertEqual(b[b.index("volume prune -af") + 1], "volume prune -f")

    def test_schonend_waehrend_github_job(self):
        r = self.lauf("25", frei=10, worker=1)
        self.assertEqual(r.returncode, 0, r.stderr)
        b = self.befehle()
        self.assertIn("container prune -f --filter until=24h", b)
        self.assertIn("volume prune -f --filter all=false", b)  # nur anonyme Volumes
        self.assertFalse(any(x.startswith("image prune") for x in b), b)  # Images nur einzeln und geprüft
        self.assertFalse(any("-af" in x and "volume" in x for x in b), b)
        self.assertFalse(any(x == "container prune -f" for x in b), b)
        self.assertIn("(schonend)", r.stdout)

    def test_hook_vor_dem_job_zaehlt_den_eigenen_job_nicht(self):
        r = self.lauf("--vor-dem-job", "25", frei=10, worker=1)
        self.assertIn("(gruendlich)", r.stdout)
        r = self.lauf("--vor-dem-job", "25", frei=10, worker=2)  # ein zweiter Job läuft
        self.assertIn("(schonend)", r.stdout)

    def test_schonend_waehrend_forgejo_oder_gitlab_job(self):
        for name in ("FORGEJO-ACTIONS-TASK-42_WORKFLOW-ci_JOB-test", "GITEA-ACTIONS-TASK-7_x",
                     "runner-abc123-project-5-concurrent-0-0123456789abcdef-build"):
            r = self.lauf("--vor-dem-job", "25", frei=10, container=f"postgres\n{name}\n")
            self.assertIn("(schonend)", r.stdout, name)
        r = self.lauf(frei=50, container="postgres\nmein-dienst\n")
        self.assertIn("(gruendlich)", r.stdout)

    def test_liste_der_images_seit_wann(self):
        """Jeder Lauf (auch über der Schwelle) merkt sich, seit wann es jedes Image gibt; bekannte Zeiten bleiben."""
        self.liste.parent.mkdir(parents=True)
        self.liste.write_text(f"{sha('a')} 1000\n{sha('f')} 2000\nkaputt zeile\n")
        lage = {"images": {sha("a"): {"tags": ["alt:1", "alt:2"]}, sha("b"): {}}}
        r = self.lauf("25", frei=30, lage=lage)
        self.assertEqual(r.returncode, 0, r.stderr)
        stand = self.gemerkt()
        self.assertEqual(stand[sha("a")], 1000)                  # bekannt: Zeit bleibt
        self.assertNotIn(sha("f"), stand)                        # nicht mehr da: vergessen
        self.assertGreater(stand[sha("b")], 1_600_000_000)       # neu: jetzt
        self.assertEqual(len(stand), 2)                          # „alt:1“ und „alt:2“ nur einmal
        self.assertEqual(stat.S_IMODE(self.liste.stat().st_mode), 0o644)
        self.assertEqual([p.name for p in self.liste.parent.iterdir()], ["images"])  # keine Zwischendatei
        # Docker nicht erreichbar: die Liste bleibt, wie sie ist
        vorher = self.liste.read_text()
        self.lauf("25", frei=30, lage={"kaputt": True})
        self.assertEqual(self.liste.read_text(), vorher)

    def test_schonend_images_nur_alt_unbenutzt_und_nicht_frisch(self):
        """E-31: während eines Jobs nur Images, die ≥ 30 Min. bekannt sind, die kein Container nutzt und die
        nicht gerade gezogen, gebaut, geladen oder neu benannt wurden."""
        alt, neu = 1000, 4_000_000_000  # „neu“ liegt in der Zukunft, ist also jünger als 30 Minuten
        self.liste.parent.mkdir(parents=True)
        self.liste.write_text("".join(f"{sha(z)} {alt}\n" for z in "abdef") + f"{sha('c')} {neu}\n")
        lage = {
            "namen": ["FORGEJO-ACTIONS-TASK-1_x"],
            "images": {
                sha("a"): {"tags": ["weg:1", "weg:2"]},          # alt, unbenutzt → weg
                sha("b"): {"tags": ["dienst:1"]},                # ein gestoppter Container nutzt es → bleibt
                sha("c"): {"tags": ["frisch:1"]},                # erst seit Kurzem bekannt → bleibt
                sha("d"): {"tags": ["gebaut:1"], "tagzeit": neu},  # gerade gebaut/benannt (LastTagTime) → bleibt
                sha("e"): {"tags": ["node:20"]},                 # gerade gezogen (Ereignis „pull node:20“) → bleibt
                sha("f"): {},                                    # alt, ohne Namen, unbenutzt → weg
                sha("9"): {"tags": ["unbekannt:1"]},             # nicht in der Liste (neu) → bleibt
            },
            "container": {"c" * 64: sha("b")},
            "events": ["node:20"],
            "ref": {"node:20": sha("e")},
        }
        r = self.lauf("25", frei=10, lage=lage)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("(schonend)", r.stdout)
        rmi = [x for x in self.befehle() if x.startswith("rmi")]
        self.assertEqual(rmi, ["rmi weg:1 weg:2", f"rmi {sha('a')}", f"rmi {sha('f')}"])
        self.assertIn(sha("9"), self.gemerkt())

    def test_schonend_ohne_liste_oder_ohne_docker_kein_image(self):
        lage = {"namen": ["GITEA-ACTIONS-TASK-1_x"], "images": {sha("a"): {"tags": ["x:1"]}}}
        r = self.lauf("25", frei=10, lage=lage, wurzel=False)  # keine Liste lesbar
        self.assertIn("(schonend)", r.stdout)
        self.assertFalse(any(x.startswith("rmi") for x in self.befehle()))
        # Liste da, aber „docker ps -a“ scheitert: kein Image
        self.liste.parent.mkdir(parents=True)
        self.liste.write_text(f"{sha('a')} 1000\n")
        ausfuehrbar(self.bin / "docker", '#!/bin/sh\necho "$*" >> "$PROTOKOLL"\n'
                    'case "$1 $2" in "ps --format") echo GITEA-ACTIONS-TASK-1_x ;; "image ls") echo ' + sha("a") + ' ;; '
                    '"ps -aq") exit 1 ;; esac\nexit 0\n')
        r = self.lauf("25", frei=10, lage=lage)
        self.assertIn("(schonend)", r.stdout)
        self.assertFalse(any(x.startswith("rmi") for x in self.befehle()))

    def test_ohne_schwelle_immer(self):
        r = self.lauf(frei=500)
        self.assertIn("(gruendlich)", r.stdout)

    def test_ungueltige_angabe(self):
        for arg in ("--alles", "25GB", "-1"):
            r = self.lauf(arg)
            self.assertEqual(r.returncode, 2, arg)
            self.assertEqual(self.protokoll.read_text(), "", arg)

    def test_hilfe_nur_der_kopf(self):
        r = self.lauf("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--vor-dem-job", r.stdout)
        self.assertIn("30 Minuten", r.stdout)
        self.assertNotIn("GRENZE", r.stdout)
        self.assertNotIn("shellcheck", r.stdout)
        self.assertEqual(self.protokoll.read_text(), "")


@unittest.skipUnless(shutil.which("dash"), "dash fehlt")
class DashSkriptTest(SkriptTest):
    """Dasselbe unter dash (/bin/sh auf Ubuntu/Debian)."""

    SHELL = "dash"


@unittest.skipUnless(shutil.which("bash"), "bash fehlt")
class EinrichtenTest(unittest.TestCase):
    """deploy/aufraeumen-einrichten.sh unter AUFRAEUMEN_WURZEL mit Attrappen für id, systemctl, runuser …"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        self.w = self.d / "wurzel"
        for verz in ("usr/local/bin", "etc/cron.daily", "etc/cron.weekly", "etc/systemd/system"):
            (self.w / verz).mkdir(parents=True)
        self.bin = self.d / "bin"
        self.log = self.d / "aufrufe.log"
        ausfuehrbar(self.bin / "id", '#!/bin/sh\necho 0\n')
        ausfuehrbar(self.bin / "chown", "#!/bin/sh\nexit 0\n")
        ausfuehrbar(self.bin / "pgrep", "#!/bin/sh\nexit 1\n")
        ausfuehrbar(self.bin / "stat", "#!/bin/sh\necho testnutzer\n")
        ausfuehrbar(self.bin / "systemctl", '#!/bin/sh\necho "systemctl $*" >> "$LOG"\nexit 0\n')
        ausfuehrbar(self.bin / "systemd-run", '#!/bin/sh\necho "systemd-run $*" >> "$LOG"\n')
        # runuser -u NUTZER -- befehl …: im Test einfach als dieser Benutzer ausführen
        ausfuehrbar(self.bin / "runuser", '#!/bin/sh\necho "runuser $2" >> "$LOG"\nshift 3\nexec "$@"\n')
        # install -m … -o root -g root …: ohne Besitzerwechsel
        ausfuehrbar(self.bin / "install", "#!/bin/sh\n"
                    'for a; do shift; case "$a" in -o|-g) weg=1 ;; *) [ -n "$weg" ] && weg= || set -- "$@" "$a" ;; esac; done\n'
                    'exec /usr/bin/install "$@"\n')
        self.runner = self.d / "actions-runner"

    def lauf(self) -> subprocess.CompletedProcess:
        umgebung = {"PATH": f"{self.bin}:/usr/bin:/bin", "AUFRAEUMEN_WURZEL": str(self.w), "RUNNER_VERZ": str(self.runner),
                    "LOG": str(self.log), "LANG": "C.UTF-8"}
        return subprocess.run(["bash", str(EINRICHTEN)], capture_output=True, text=True, env=umgebung, timeout=60, check=False)

    def test_ohne_github_runner_idempotent(self):
        (self.w / "etc/cron.weekly/runner-aufraeumen").write_text("alt")
        for _ in range(2):
            r = self.lauf()
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        skript = self.w / "usr/local/bin/runner-aufraeumen"
        self.assertEqual(skript.read_bytes(), SKRIPT.read_bytes())
        self.assertEqual(stat.S_IMODE(skript.stat().st_mode), 0o755)
        nacht = (self.w / "etc/cron.daily/runner-aufraeumen").read_text()
        self.assertIn("/usr/local/bin/runner-aufraeumen", nacht)
        self.assertFalse((self.w / "etc/cron.weekly/runner-aufraeumen").exists())
        self.assertTrue((self.w / "etc/systemd/system/runner-aufraeumen.timer").is_file())
        self.assertTrue((self.w / "etc/systemd/system/runner-aufraeumen.service").is_file())
        self.assertIn("systemctl enable --now runner-aufraeumen.timer", self.log.read_text())
        self.assertNotIn("runuser", self.log.read_text())
        # keine Zwischendateien übrig (run-parts überspränge sie, trotzdem sauber)
        self.assertEqual(sorted(p.name for p in (self.w / "etc/cron.daily").iterdir()), ["runner-aufraeumen"])

    def test_symlink_am_ziel_wird_ersetzt_nicht_verfolgt(self):
        opfer = self.d / "opfer"
        opfer.write_text("bleibt")
        (self.w / "usr/local/bin/runner-aufraeumen").symlink_to(opfer)
        self.assertEqual(self.lauf().returncode, 0)
        self.assertEqual(opfer.read_text(), "bleibt")
        self.assertFalse((self.w / "usr/local/bin/runner-aufraeumen").is_symlink())

    def test_github_runner_hook_einmal(self):
        self.runner.mkdir()
        (self.runner / ".runner").write_text("{}")
        (self.runner / ".env").write_text("LANG=C.UTF-8\n")
        (self.runner / "vor-dem-job.sh").write_text("#!/bin/sh\n/usr/local/bin/runner-aufraeumen 25\n")  # alte Fassung
        r = self.lauf()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Dienst neu gestartet", r.stdout)
        self.assertIn("systemctl try-restart actions.runner.*", self.log.read_text())
        r = self.lauf()
        self.assertNotIn("neu gestartet", r.stdout)
        env = (self.runner / ".env").read_text().splitlines()
        self.assertEqual(env, ["LANG=C.UTF-8", f"ACTIONS_RUNNER_HOOK_JOB_STARTED={self.runner}/vor-dem-job.sh"])
        hook = (self.runner / "vor-dem-job.sh").read_text()
        self.assertIn("exec /usr/local/bin/runner-aufraeumen --vor-dem-job 25", hook)
        self.assertTrue(os.access(self.runner / "vor-dem-job.sh", os.X_OK))
        # und der Monitor erkennt den Hook
        self.assertIs(aufraeumen._hook(self.runner), True)

    def test_hook_neu_waehrend_eines_jobs_neustart_erst_danach(self):
        """Läuft ein Job, startet der Runner nicht sofort neu, sondern per systemd-run nach dem Job; ein
        gescheiterter Vorgänger gleichen Namens wird vorher zurückgesetzt. Scheitert systemd-run, endet das
        Einrichten nicht mit Fehler, sondern nennt den Befehl für später."""
        self.runner.mkdir()
        (self.runner / ".runner").write_text("{}")
        ausfuehrbar(self.bin / "pgrep", "#!/bin/sh\nexit 0\n")  # Runner.Worker läuft
        r = self.lauf()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        log = self.log.read_text()
        self.assertIn("systemctl reset-failed runner-neustart", log)
        self.assertLess(log.index("reset-failed runner-neustart"), log.index("systemd-run --unit=runner-neustart"))
        self.assertNotIn("systemctl try-restart actions.runner.*", log.splitlines())  # kein sofortiger Neustart
        self.assertIn("Neustart folgt automatisch", r.stdout)
        # systemd-run scheitert (z. B. Name noch belegt)
        (self.runner / ".env").write_text("")
        ausfuehrbar(self.bin / "systemd-run", "#!/bin/sh\nexit 1\n")
        r = self.lauf()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("erst nach einem Neustart", r.stdout)

    def test_fremder_hook_bleibt(self):
        self.runner.mkdir()
        (self.runner / ".runner").write_text("{}")
        (self.runner / ".env").write_text("ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/eigener-hook.sh\n")
        r = self.lauf()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("anderen Hook", r.stdout)
        self.assertEqual((self.runner / ".env").read_text(), "ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/eigener-hook.sh\n")
        self.assertNotIn("try-restart", self.log.read_text())


if __name__ == "__main__":
    unittest.main()
