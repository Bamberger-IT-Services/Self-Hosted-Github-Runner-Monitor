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
