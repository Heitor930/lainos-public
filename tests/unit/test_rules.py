"""Validação do que a pessoa digita no primeiro início."""
import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401
from firstboot import rules


class Username(unittest.TestCase):
    def test_suggestion_from_full_name(self):
        self.assertEqual(rules.suggest_username("Ana Clara Souza"), "ana")
        self.assertEqual(rules.suggest_username("João Pedro"), "joao")
        self.assertEqual(rules.suggest_username("  Érica  "), "erica")
        self.assertEqual(rules.suggest_username("3PO Droid"), "po")
        self.assertEqual(rules.suggest_username(""), "")
        self.assertEqual(rules.suggest_username("玲音"), "")

    def test_valid(self):
        for name in ("ana", "lain_iwakura", "user-1", "_svc", "a" * 32):
            self.assertEqual(rules.username_error(name), "", name)

    def test_invalid(self):
        for name in ("", "Ana", "1abc", "-abc", "joão", "a b", "a" * 33, "ana;rm", "ana\n", "a:b", "$(id)"):
            self.assertTrue(rules.username_error(name), name)

    def test_reserved(self):
        for name in ("root", "greeter", "wired", "tor", "nobody"):
            self.assertIn("reservado", rules.username_error(name), name)


class Password(unittest.TestCase):
    def test_rules(self):
        self.assertTrue(rules.password_error(""))
        self.assertTrue(rules.password_error("12345"))
        self.assertEqual(rules.password_error("123456"), "")
        self.assertEqual(rules.password_error("çã ok: 1234"), "")
        self.assertTrue(rules.password_error("abc\ndef"))
        self.assertTrue(rules.password_error("x" * 257))

    def test_confirmation(self):
        self.assertEqual(rules.password_error("lain-1998", "lain-1998"), "")
        self.assertTrue(rules.password_error("lain-1998", "lain-1999"))


class Hostname(unittest.TestCase):
    def test_rules(self):
        for name in ("navi", "lainos", "pc-da-ana", "a", "x" * 63):
            self.assertEqual(rules.hostname_error(name), "", name)
        for name in ("", "-navi", "navi-", "Navi", "meu pc", "a.b", "x" * 64, "navi;id"):
            self.assertTrue(rules.hostname_error(name), name)


class FullName(unittest.TestCase):
    def test_cleaning(self):
        self.assertEqual(rules.clean_full_name("  Ana   Clara  "), "Ana Clara")
        self.assertEqual(rules.clean_full_name("Ana:x:0:0\nroot"), "Ana x 0 0 root")
        self.assertEqual(rules.clean_full_name("Souza, Ana"), "Souza Ana")
        self.assertEqual(len(rules.clean_full_name("x" * 200)), 64)


class Keyboards(unittest.TestCase):
    def test_ids_are_unique_and_safe(self):
        ids = [k.id for k in rules.KEYBOARDS]
        self.assertEqual(len(ids), len(set(ids)))
        for keyboard in rules.KEYBOARDS:
            for value in (keyboard.layout, keyboard.variant, keyboard.console):
                self.assertRegex(value, r"^[a-z0-9_-]*$")
        self.assertEqual(rules.KEYBOARDS[0].id, "br")

    def test_lookup(self):
        self.assertEqual(rules.keyboard_by_id("us-intl").variant, "intl")
        self.assertIsNone(rules.keyboard_by_id("klingon"))

    def test_current_keyboard_reads_the_shared_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "00-keyboard.conf"
            conf.write_text('Option "XkbLayout" "us"\nOption "XkbVariant" "intl"\n', encoding="utf-8")
            old = rules.KEYBOARD_CONF
            rules.KEYBOARD_CONF = conf
            try:
                self.assertEqual(rules.current_keyboard().id, "us-intl")
                conf.write_text('Option "XkbLayout" "xx"\n', encoding="utf-8")
                self.assertEqual(rules.current_keyboard().id, "br")
            finally:
                rules.KEYBOARD_CONF = old

    def test_shipped_default_is_abnt2(self):
        old = rules.KEYBOARD_CONF
        rules.KEYBOARD_CONF = _paths.AIROOTFS / "etc/X11/xorg.conf.d/00-keyboard.conf"
        try:
            self.assertEqual(rules.current_keyboard().id, "br")
        finally:
            rules.KEYBOARD_CONF = old


class Timezones(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        zoneinfo = Path(self.tmp.name)
        (zoneinfo / "America").mkdir()
        (zoneinfo / "America/Sao_Paulo").write_bytes(b"TZif")
        (zoneinfo / "America/Manaus").write_bytes(b"TZif")
        (zoneinfo / "UTC").write_bytes(b"TZif")
        (zoneinfo / "zone1970.tab").write_text(
            "# comentário\nBR\t-2332-04637\tAmerica/Sao_Paulo\tBrazil\nBR\t-0308-06001\tAmerica/Manaus\n",
            encoding="utf-8")
        self.old = rules.ZONEINFO
        rules.ZONEINFO = zoneinfo

    def tearDown(self):
        rules.ZONEINFO = self.old
        self.tmp.cleanup()

    def test_list(self):
        self.assertEqual(rules.list_timezones(), ["America/Manaus", "America/Sao_Paulo", "UTC"])

    def test_validation(self):
        self.assertTrue(rules.timezone_ok("America/Sao_Paulo"))
        self.assertTrue(rules.timezone_ok("UTC"))
        for name in ("", "America", "America/Nada", "../etc/passwd", "/etc/passwd", "America/../UTC",
                     "zone1970.tab", "America/Sao Paulo"):
            self.assertFalse(rules.timezone_ok(name), name)


if __name__ == "__main__":
    unittest.main()
