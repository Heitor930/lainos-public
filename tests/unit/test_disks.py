"""O instalador só pode oferecer discos em que é seguro instalar."""
import unittest

import _paths  # noqa: F401
from installer import disks

GIB = 1024**3

SAMPLE = {"blockdevices": [
    {"name": "sda", "path": "/dev/sda", "size": 1000 * GIB, "model": "WDC WD10EZEX", "vendor": "ATA     ",
     "tran": "sata", "rota": True, "rm": False, "hotplug": False, "ro": False, "type": "disk",
     "children": [{"name": "sda1", "path": "/dev/sda1", "size": 999 * GIB, "type": "part", "fstype": "ext4"}]},
    {"name": "nvme0n1", "path": "/dev/nvme0n1", "size": 500 * GIB, "model": "Samsung SSD 970 EVO", "tran": "nvme",
     "rota": False, "rm": False, "hotplug": False, "ro": False, "type": "disk",
     "children": [
         {"name": "nvme0n1p1", "path": "/dev/nvme0n1p1", "size": GIB, "type": "part", "fstype": "vfat"},
         {"name": "nvme0n1p2", "path": "/dev/nvme0n1p2", "size": 499 * GIB, "type": "part", "fstype": "ntfs"}]},
    # o pendrive de instalação gravado com a ISO
    {"name": "sdb", "path": "/dev/sdb", "size": 32 * GIB, "model": "Ultra Fit", "vendor": "SanDisk ", "tran": "usb",
     "rm": True, "hotplug": True, "ro": False, "type": "disk", "fstype": "iso9660",
     "children": [{"name": "sdb1", "path": "/dev/sdb1", "size": 3 * GIB, "type": "part", "fstype": "iso9660"}]},
    # o pendrive de instalação feito com o Ventoy (a ISO fica dentro de uma partição exFAT)
    {"name": "sdc", "path": "/dev/sdc", "size": 64 * GIB, "model": "Ventoy", "tran": "usb",
     "rm": True, "hotplug": True, "ro": False, "type": "disk",
     "children": [{"name": "sdc1", "path": "/dev/sdc1", "size": 63 * GIB, "type": "part", "fstype": "exfat"}]},
    {"name": "sdd", "path": "/dev/sdd", "size": 8 * GIB, "model": "Pequeno", "tran": "usb", "rm": True,
     "ro": False, "type": "disk"},
    {"name": "sde", "path": "/dev/sde", "size": 128 * GIB, "model": "Externo", "tran": "usb", "rm": True,
     "hotplug": True, "ro": False, "type": "disk"},
    {"name": "sdf", "path": "/dev/sdf", "size": 256 * GIB, "model": "Protegido", "tran": "sata", "rm": False,
     "ro": True, "type": "disk"},
    {"name": "zram0", "path": "/dev/zram0", "size": 64 * GIB, "type": "disk", "rm": False, "ro": False},
    {"name": "loop0", "path": "/dev/loop0", "size": 64 * GIB, "type": "loop", "rm": False, "ro": False},
    {"name": "sr0", "path": "/dev/sr0", "size": 64 * GIB, "type": "rom", "rm": True, "ro": False},
]}


class ListDisks(unittest.TestCase):
    def setUp(self):
        self.disks = disks.list_disks(SAMPLE, live_source="/dev/sdc1")
        self.paths = [d.path for d in self.disks]

    def test_only_real_writable_big_disks(self):
        self.assertEqual(self.paths, ["/dev/nvme0n1", "/dev/sda", "/dev/sde"])

    def test_install_medium_is_never_offered(self):
        self.assertNotIn("/dev/sdb", self.paths)   # ISO9660
        self.assertNotIn("/dev/sdc", self.paths)   # de onde a sessão ao vivo subiu

    def test_live_source_can_be_the_whole_disk(self):
        found = disks.list_disks(SAMPLE, live_source="/dev/sde")
        self.assertNotIn("/dev/sde", [d.path for d in found])

    def test_multiboot_pendrive_is_recognised_through_its_mapping(self):
        # pendrives multiboot expõem a ISO por um dispositivo mapeado em cima da partição
        data = {"blockdevices": [
            {"name": "sdc", "path": "/dev/sdc", "size": 64 * GIB, "type": "disk", "tran": "usb", "rm": True,
             "children": [{"name": "sdc1", "path": "/dev/sdc1", "size": 63 * GIB, "type": "part", "fstype": "exfat",
                           "children": [{"name": "ventoy", "path": "/dev/mapper/ventoy", "size": 3 * GIB,
                                         "type": "dm"}]}]},
            {"name": "sda", "path": "/dev/sda", "size": 240 * GIB, "type": "disk", "tran": "sata"},
        ]}
        found = disks.list_disks(data, live_source=["/dev/mapper/ventoy", "/dev/loop0"])
        self.assertEqual([d.path for d in found], ["/dev/sda"])

    def test_internal_ssd_comes_first(self):
        self.assertEqual(self.disks[0].kind, "SSD NVMe")
        self.assertEqual(self.disks[1].kind, "HD SATA")
        self.assertEqual(self.disks[2].kind, "USB")

    def test_description(self):
        nvme = self.disks[0]
        self.assertEqual(nvme.title, "Samsung SSD 970 EVO")
        self.assertIn("2 partições", nvme.contents)
        self.assertIn("Windows (NTFS)", nvme.contents)
        self.assertEqual(self.disks[1].title, "WDC WD10EZEX")   # "ATA" some do nome
        self.assertEqual(self.disks[2].contents, "vazio")

    def test_minimum_size_is_configurable(self):
        found = disks.list_disks(SAMPLE, live_source="", min_bytes=4 * GIB)
        self.assertIn("/dev/sdd", [d.path for d in found])

    def test_bad_input_does_not_crash(self):
        self.assertEqual(disks.list_disks({}, live_source=""), [])
        self.assertEqual(disks.list_disks({"blockdevices": [{"type": "disk", "size": "x"}]}, live_source=""), [])


class HumanSize(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(disks.human_size(500_107_862_016), "500 GB")
        self.assertEqual(disks.human_size(1_000_204_886_016), "1 TB")
        self.assertEqual(disks.human_size(30_752_636_928), "30,8 GB")
        self.assertEqual(disks.human_size(512), "512 B")


if __name__ == "__main__":
    unittest.main()
