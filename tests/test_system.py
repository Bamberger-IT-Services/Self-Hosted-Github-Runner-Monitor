import unittest

from runner_monitor import system

STAT_VORHER = """cpu  100 0 100 800 0 0 0 0 0 0
cpu0 50 0 50 400 0 0 0 0 0 0
cpu1 50 0 50 400 0 0 0 0 0 0
intr 1
"""
STAT_JETZT = """cpu  300 0 200 900 0 0 0 0 0 0
cpu0 150 0 100 400 0 0 0 0 0 0
cpu1 100 0 100 450 10 0 0 0 0 0
"""

MEMINFO = """MemTotal:       14680064 kB
MemFree:          500000 kB
MemAvailable:    1048576 kB
SwapTotal:       2097152 kB
SwapFree:        1677722 kB
"""

MOUNTS = """/dev/sda2 / ext4 rw,relatime 0 0
proc /proc proc rw 0 0
overlay /var/lib/docker/overlay2/abc/merged overlay rw 0 0
/dev/loop1 /snap/core/1 squashfs ro 0 0
/dev/sdb1 /var/lib/docker ext4 rw 0 0
/dev/sda2 /home ext4 rw 0 0
tmpfs /run tmpfs rw 0 0
/dev/sda1 /boot/efi vfat rw 0 0
"""


NETZ_VORHER = """Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo: 5000      10    0    0    0     0          0         0     5000      10    0    0    0     0       0          0
 ens18: 1000000  900    0    0    0     0          0         0   200000     500    0    0    0     0       0          0
docker0: 777777  10    0    0    0     0          0         0   777777      10    0    0    0     0       0          0
vethab12: 99999  10    0    0    0     0          0         0    99999      10    0    0    0     0       0          0
"""
NETZ_JETZT = NETZ_VORHER.replace("1000000", "3000000").replace("200000 ", "300000 ")


class NetzTest(unittest.TestCase):
    def test_nur_echte_schnittstellen(self):
        werte = system.lies_netz(NETZ_VORHER)
        self.assertEqual(werte, {"ens18": (1000000, 200000)})

    def test_rate_je_sekunde(self):
        rate = system.netz_rate(system.lies_netz(NETZ_VORHER), system.lies_netz(NETZ_JETZT), 2.0)
        self.assertEqual(rate["empfangen"], 1000000)
        self.assertEqual(rate["gesendet"], 50000)
        self.assertEqual(rate["schnittstellen"], ["ens18"])

    def test_zaehler_neustart_und_neue_schnittstelle(self):
        vorher = {"ens18": (5000, 5000)}
        jetzt = {"ens18": (100, 200), "ens19": (999, 999)}
        rate = system.netz_rate(vorher, jetzt, 1.0)
        self.assertEqual((rate["empfangen"], rate["gesendet"]), (0, 0))
        self.assertEqual(system.netz_rate(vorher, jetzt, 0)["empfangen"], 0)


class BeschreibungTest(unittest.TestCase):
    def test_os_und_python(self):
        import tempfile, sys
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "os-release"
            f.write_text('NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 24.04.1 LTS"\n')
            self.assertEqual(system.beschreibung(f), f"Ubuntu 24.04.1 LTS, Python {sys.version_info.major}.{sys.version_info.minor}")
            self.assertTrue(system.beschreibung(Path(d) / "fehlt").startswith("Python "))


class CpuTest(unittest.TestCase):
    def test_auslastung_je_kern(self):
        vorher = system.lies_cpu_zeiten(STAT_VORHER)
        jetzt = system.lies_cpu_zeiten(STAT_JETZT)
        self.assertEqual(len(vorher), 2)
        werte = system.cpu_auslastung(vorher, jetzt)
        self.assertEqual(werte[0], 100.0)  # nur user/system gestiegen
        self.assertEqual(werte[1], 62.5)  # (160 - 60 Leerlauf inkl. iowait) / 160

    def test_keine_aenderung_ergibt_null(self):
        vorher = system.lies_cpu_zeiten(STAT_VORHER)
        self.assertEqual(system.cpu_auslastung(vorher, vorher), [0.0, 0.0])


class SpeicherTest(unittest.TestCase):
    def test_ram_und_swap(self):
        sp = system.speicher(system.lies_meminfo(MEMINFO))
        self.assertEqual(sp["ram"]["gesamt"], 14 * 1024**3)
        self.assertEqual(sp["ram"]["belegt"], 14 * 1024**3 - 1024**3)
        self.assertEqual(sp["swap"]["belegt"], (2097152 - 1677722) * 1024)

    def test_last(self):
        self.assertEqual(system.lies_last("3.92 3.71 2.88 5/600 1234\n"), [3.92, 3.71, 2.88])


class PlattenTest(unittest.TestCase):
    def test_nur_echte_laufwerke_wurzel_zuerst(self):
        self.assertEqual(system.einhaengepunkte(MOUNTS), ["/", "/var/lib/docker"])


if __name__ == "__main__":
    unittest.main()


class NetzlaufwerkTest(unittest.TestCase):
    """Issue #26: ein hängendes NFS/CIFS-Laufwerk darf die Messung nicht anhalten."""

    MOUNTS = "/dev/sda1 / ext4 rw 0 0\nnas:/daten /mnt/nas nfs4 rw 0 0\n"

    def setUp(self):
        import threading
        self.frei = threading.Event()
        self.echt = system.os.statvfs
        system._haengend.clear()

    def tearDown(self):
        self.frei.set()
        system.os.statvfs = self.echt
        system._haengend.clear()

    def test_haengendes_netzlaufwerk_wird_uebersprungen(self):
        import time
        echt = self.echt

        def statvfs(punkt):
            if punkt == "/mnt/nas":
                self.frei.wait(10)  # hängt, bis der Test es freigibt
            return echt("/")

        system.os.statvfs = statvfs
        alt = system.NETZ_FRIST
        system.NETZ_FRIST = 0.2
        try:
            beginn = time.monotonic()
            liste = system.platten(self.MOUNTS, 25)
            self.assertLess(time.monotonic() - beginn, 2)
            self.assertEqual([p["pfad"] for p in liste], ["/"])
            # Solange es hängt, wird es nicht erneut gefragt (kein neuer Thread, keine Wartezeit)
            beginn = time.monotonic()
            system.platten(self.MOUNTS, 25)
            self.assertLess(time.monotonic() - beginn, 0.15)
            # Antwortet es wieder, erscheint es wieder
            self.frei.set()
            system._haengend["/mnt/nas"].join(2)
            self.assertEqual([p["pfad"] for p in system.platten(self.MOUNTS, 25)], ["/", "/mnt/nas"])
        finally:
            system.NETZ_FRIST = alt
