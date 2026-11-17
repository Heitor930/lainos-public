"""O programa que aplica o primeiro início como root, rodado em modo de teste.

No modo de teste (LAIN_FIRSTBOOT_ROOT) ele escreve dentro de uma pasta e só
anota os comandos que rodaria, então dá para conferir tudo sem ser root.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _paths

HELPER = _paths.LIB / "firstboot-apply"


class Helper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "root"
        self.zoneinfo = Path(self.tmp.name) / "zoneinfo"
        (self.zoneinfo / "America").mkdir(parents=True)
        (self.zoneinfo / "America/Manaus").write_bytes(b"TZif")
        (self.root / "var/lib/lainos").mkdir(parents=True)
        self.marker = self.root / "var/lib/lainos/firstboot"
        self.marker.touch()
        skel = self.root / "etc/skel/.config/hypr/conf"
        skel.mkdir(parents=True)
        source = _paths.AIROOTFS / "etc/skel/.config/hypr/conf/input.conf"
        (skel / "input.conf").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, action, data, extra_env=None, raw=None):
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LAIN_FIRSTBOOT_ROOT": str(self.root),
            "LAIN_LIB_DIR": str(_paths.LIB),
            "LAIN_ZONEINFO": str(self.zoneinfo),
        }
        env.update(extra_env or {})
        proc = subprocess.run(
            [sys.executable, "-I", str(HELPER), action],
            input=raw if raw is not None else json.dumps(data),
            capture_output=True, text=True, env=env, timeout=30, check=False,
        )
        try:
            reply = json.loads(proc.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            self.fail(f"resposta inesperada: {proc.stdout!r} {proc.stderr!r}")
        self.assertEqual(proc.returncode, 0 if reply["ok"] else 1)
        return reply

    def read(self, name):
        return (self.root / name.lstrip("/")).read_text(encoding="utf-8")

    def commands(self):
        log = self.root / "commands.log"
        return log.read_text(encoding="utf-8").splitlines() if log.exists() else []

    # ---- teclado e fuso -------------------------------------------------
    def test_system_writes_keyboard_and_timezone(self):
        reply = self.call("system", {"keyboard": "us-intl", "timezone": "America/Manaus"})
        self.assertTrue(reply["ok"], reply)
        xorg = self.read("/etc/X11/xorg.conf.d/00-keyboard.conf")
        self.assertIn('Option "XkbLayout" "us"', xorg)
        self.assertIn('Option "XkbVariant" "intl"', xorg)
        self.assertEqual(self.read("/etc/vconsole.conf"), "KEYMAP=us-acentos\n")
        self.assertEqual(os.readlink(self.root / "etc/localtime"), str(self.zoneinfo / "America/Manaus"))
        hypr = self.read("/etc/skel/.config/hypr/conf/input.conf")
        self.assertIn("kb_layout = us", hypr)
        self.assertIn("kb_variant = intl", hypr)
        self.assertEqual(hypr.count("kb_layout"), 1)
        self.assertTrue(self.marker.exists(), "a marca só some quando a conta é criada")

    def test_system_without_variant_removes_old_variant(self):
        self.call("system", {"keyboard": "us-intl", "timezone": "America/Manaus"})
        self.call("system", {"keyboard": "br", "timezone": "America/Manaus"})
        hypr = self.read("/etc/skel/.config/hypr/conf/input.conf")
        self.assertIn("kb_layout = br", hypr)
        self.assertNotIn("kb_variant", hypr)

    def test_system_rejects_unknown_values(self):
        self.assertFalse(self.call("system", {"keyboard": "klingon", "timezone": "America/Manaus"})["ok"])
        self.assertFalse(self.call("system", {"keyboard": "br", "timezone": "../../etc/shadow"})["ok"])
        self.assertFalse(self.call("system", {"keyboard": "br", "timezone": "America/Nada"})["ok"])
        self.assertFalse((self.root / "etc/vconsole.conf").exists())

    # ---- conta ----------------------------------------------------------
    def test_account_creates_user_and_ends_first_boot(self):
        reply = self.call("account", {"fullname": "Ana Clara", "username": "ana",
                                      "password": "lain-1998", "hostname": "navi"})
        self.assertEqual(reply, {"ok": True, "username": "ana"})
        commands = self.commands()
        self.assertEqual(len(commands), 2, commands)
        self.assertTrue(commands[0].startswith("useradd -m -U -c Ana Clara -s "), commands[0])
        self.assertTrue(commands[0].endswith(" ana"), commands[0])
        self.assertEqual(commands[1], "chpasswd")
        self.assertNotIn("lain-1998", "\n".join(commands), "a senha nunca vai para a linha de comando")
        self.assertEqual(self.read("/etc/hostname"), "navi\n")
        self.assertIn("127.0.1.1   navi.localdomain navi", self.read("/etc/hosts"))
        self.assertEqual(self.read("/var/lib/lainos/owner"), "ana\n")
        self.assertFalse(self.marker.exists())

    def test_account_default_hostname(self):
        self.call("account", {"fullname": "", "username": "ana", "password": "lain-1998"})
        self.assertEqual(self.read("/etc/hostname"), "lainos\n")
        self.assertIn("-c ana ", self.commands()[0])

    def test_account_rejects_bad_input(self):
        bad = [
            {"username": "root", "password": "lain-1998"},
            {"username": "Ana", "password": "lain-1998"},
            {"username": "ana;id", "password": "lain-1998"},
            {"username": "ana", "password": "123"},
            {"username": "ana", "password": "lain\n1998"},
            {"username": "ana", "password": "lain-1998", "hostname": "meu pc"},
            {"username": "ana", "password": "lain-1998", "hostname": "x;reboot"},
        ]
        for data in bad:
            reply = self.call("account", data)
            self.assertFalse(reply["ok"], data)
            self.assertTrue(reply["error"])
        self.assertEqual(self.commands(), [])
        self.assertTrue(self.marker.exists())

    def test_existing_user_is_refused(self):
        reply = self.call("account", {"username": "nobody2", "password": "lain-1998"})
        self.assertTrue(reply["ok"])  # nome livre
        self.marker.touch()
        import pwd
        existing = pwd.getpwuid(os.getuid()).pw_name
        if existing in ("root",):
            self.skipTest("rodando como root: o nome já é recusado por ser reservado")
        reply = self.call("account", {"username": existing, "password": "lain-1998"})
        self.assertFalse(reply["ok"])

    # ---- travas ---------------------------------------------------------
    def test_refuses_after_first_boot(self):
        self.marker.unlink()
        for action, data in (("system", {"keyboard": "br", "timezone": "America/Manaus"}),
                             ("account", {"username": "ana", "password": "lain-1998"})):
            reply = self.call(action, data)
            self.assertFalse(reply["ok"])
            self.assertIn("já foi concluído", reply["error"])
        self.assertEqual(self.commands(), [])

    def test_bad_usage_and_bad_json(self):
        self.assertFalse(self.call("reboot", {})["ok"])
        self.assertFalse(self.call("account", None, raw="isto não é json")["ok"])
        self.assertFalse(self.call("account", None, raw="[1, 2]")["ok"])

    def test_test_mode_is_ignored_under_sudo(self):
        # Com SUDO_UID definido (é assim que o sudo chama), as variáveis de teste
        # não valem: nada pode ser escrito na pasta indicada por elas.
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LAIN_FIRSTBOOT_ROOT": str(self.root),
            "LAIN_LIB_DIR": str(_paths.LIB),
            "LAIN_ZONEINFO": str(self.zoneinfo),
            "SUDO_UID": "1000",
        }
        proc = subprocess.run(
            [sys.executable, "-I", str(HELPER), "system"],
            input=json.dumps({"keyboard": "us", "timezone": "America/Manaus"}),
            capture_output=True, text=True, env=env, timeout=30, check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse((self.root / "etc/vconsole.conf").exists())
        self.assertFalse((self.root / "etc/localtime").exists())
        self.assertTrue(self.marker.exists())

if __name__ == "__main__":
    unittest.main()
