"""Conferências do projeto inteiro: arquivos de configuração, links, pacotes e
referências entre os scripts. Pegam os erros bobos antes de um build de 40 minutos."""
import json
import os
import re
import shutil
import subprocess
import unittest

import _paths
from _paths import AIROOTFS, BIN, LIB, REPO

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

SKIP_DIRS = {".git", "out", "__pycache__", "work"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gz", ".ico", ".ttf", ".otf", ".iso", ".zip", ".pyc"}


def project_files():
    for base, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            yield os.path.join(base, name)


def text_files():
    for path in project_files():
        if os.path.splitext(path)[1].lower() in BINARY_SUFFIXES:
            continue
        yield path


def strip_jsonc(text: str) -> str:
    """Remove comentários // e /* */ sem mexer no que está dentro de aspas."""
    out, i, in_string = [], 0, False
    while i < len(text):
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < len(text):
                out.append(text[i + 1])
                i += 1
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
            out.append(ch)
        elif text.startswith("//", i):
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            i = text.index("*/", i) + 2
            continue
        else:
            out.append(ch)
        i += 1
    # vírgula sobrando antes de } ou ] é aceita por esses programas
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


class Repository(unittest.TestCase):
    def test_no_symlinks(self):
        # links de verdade quebram no Windows e em .zip; eles ficam em airootfs.links
        links = [p for p in project_files() if os.path.islink(p)]
        self.assertEqual(links, [])

    def test_unix_line_endings(self):
        bad = []
        for path in text_files():
            with open(path, "rb") as handle:
                if b"\r\n" in handle.read():
                    bad.append(os.path.relpath(path, REPO))
        self.assertEqual(bad, [])

    def test_scripts_have_a_shebang(self):
        scripts = sorted(BIN.iterdir()) + [LIB / n for n in
                                           ("install-backend", "firstboot-apply", "firstboot-console", "live-setup")]
        scripts += [REPO / "build.sh", AIROOTFS / "root/customize_airootfs.sh"]
        for script in scripts:
            with open(script, "rb") as handle:
                self.assertEqual(handle.read(2), b"#!", script)

    def test_no_anime_artwork_or_large_files(self):
        # nada de arquivos gigantes esquecidos (a ISO não entra no repositório)
        big = [os.path.relpath(p, REPO) for p in project_files() if os.path.getsize(p) > 8 * 1024 * 1024]
        self.assertEqual(big, [])


class ConfigFiles(unittest.TestCase):
    def test_json(self):
        for path in text_files():
            if path.endswith(".json"):
                with open(path, encoding="utf-8") as handle:
                    json.load(handle)

    def test_jsonc(self):
        for path in text_files():
            if path.endswith(".jsonc"):
                with open(path, encoding="utf-8") as handle:
                    try:
                        json.loads(strip_jsonc(handle.read()))
                    except ValueError as exc:
                        self.fail(f"{os.path.relpath(path, REPO)}: {exc}")

    @unittest.skipIf(tomllib is None, "precisa de Python 3.11 ou mais novo")
    def test_toml(self):
        for path in text_files():
            if path.endswith(".toml"):
                with open(path, "rb") as handle:
                    try:
                        tomllib.load(handle)
                    except tomllib.TOMLDecodeError as exc:
                        self.fail(f"{os.path.relpath(path, REPO)}: {exc}")

    def test_firefox_policies(self):
        with open(AIROOTFS / "etc/firefox/policies/policies.json", encoding="utf-8") as handle:
            policies = json.load(handle)["policies"]
        self.assertTrue(policies["DisableTelemetry"])
        homepage = policies["Homepage"]["URL"]
        self.assertTrue(homepage.startswith("file:///"))
        self.assertTrue((AIROOTFS / homepage[len("file:///"):]).is_file(), homepage)

    def test_greetd_runs_our_greeter(self):
        if tomllib is None:
            self.skipTest("precisa de Python 3.11 ou mais novo")
        with open(AIROOTFS / "etc/greetd/config.toml", "rb") as handle:
            config = tomllib.load(handle)
        self.assertEqual(config["default_session"]["command"], "lain-greeter")
        self.assertNotIn("initial_session", config, "a imagem não pode trazer login automático")

    def test_desktop_entries(self):
        folders = [AIROOTFS / "usr/share/applications", AIROOTFS / "usr/share/lainos/live",
                   AIROOTFS / "usr/share/wayland-sessions"]
        ours = {p.name for p in BIN.iterdir()}
        count = 0
        for folder in folders:
            for entry in sorted(folder.glob("*.desktop")):
                text = entry.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("[Desktop Entry]"), entry)
                self.assertRegex(text, r"(?m)^Name=.+", str(entry))
                found = re.search(r"(?m)^Exec=(\S+)", text)
                self.assertTrue(found, entry)
                command = os.path.basename(found.group(1))
                if command.startswith(("lain-", "lainos-", "knights-", "navi-", "hermes")):
                    self.assertIn(command, ours, f"{entry.name}: {command} não existe")
                count += 1
        self.assertGreaterEqual(count, 6)

    @unittest.skipUnless(shutil.which("visudo"), "sem visudo")
    def test_sudoers(self):
        path = AIROOTFS / "etc/sudoers.d/10-lainos"
        proc = subprocess.run(["visudo", "-cf", str(path)], capture_output=True, text=True, check=False)
        output = proc.stdout + proc.stderr
        # o visudo reclama do dono/modo do arquivo no repositório; só a sintaxe interessa aqui
        self.assertNotIn("syntax error", output, output)
        text = path.read_text(encoding="utf-8")
        self.assertIn("/usr/lib/lainos/firstboot-apply system", text)
        self.assertIn("/usr/lib/lainos/firstboot-apply account", text)
        self.assertNotRegex(text, r"(?m)^greeter.*NOPASSWD:\s*ALL")


class Links(unittest.TestCase):
    def rows(self):
        with open(REPO / "airootfs.links", encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                yield number, line

    def test_format(self):
        seen = set()
        for number, line in self.rows():
            parts = line.split("\t")
            self.assertEqual(len(parts), 2, f"linha {number}: use um TAB entre o link e o destino")
            link, target = parts
            self.assertFalse(link.startswith("/"), f"linha {number}")
            self.assertNotIn("..", link.split("/"), f"linha {number}")
            self.assertTrue(target.strip(), f"linha {number}")
            self.assertNotIn(link, seen, f"linha {number}: link repetido")
            seen.add(link)
            self.assertFalse((AIROOTFS / link).exists(), f"linha {number}: {link} já existe como arquivo")
        self.assertGreaterEqual(len(seen), 10)

    def test_our_own_units_exist(self):
        for number, line in self.rows():
            target = line.split("\t")[1]
            if target.startswith("/etc/"):
                self.assertTrue((AIROOTFS / target.lstrip("/")).is_file(), f"linha {number}: {target}")

    def test_login_screen_and_services_are_enabled(self):
        links = dict(line.split("\t") for _, line in self.rows())
        self.assertEqual(links["etc/systemd/system/display-manager.service"],
                         "/usr/lib/systemd/system/greetd.service")
        self.assertEqual(links["etc/systemd/system/default.target"], "/usr/lib/systemd/system/graphical.target")
        wanted = "etc/systemd/system/multi-user.target.wants/"
        for unit in ("NetworkManager.service", "lain-live-setup.service", "lain-firstboot-console.service"):
            self.assertIn(wanted + unit, links)


class Packages(unittest.TestCase):
    def entries(self):
        with open(REPO / "packages/iso.txt", encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                line = line.split("#", 1)[0].strip()
                if line:
                    yield number, line

    def test_syntax(self):
        pattern = re.compile(r"\??[a-z0-9@._+-]+(\|[a-z0-9@._+-]+)*")
        names = []
        for number, line in self.entries():
            self.assertTrue(pattern.fullmatch(line), f"packages/iso.txt linha {number}: {line!r}")
            names.append(line.lstrip("?").split("|")[0])
        repeated = sorted({n for n in names if names.count(n) > 1})
        self.assertEqual(repeated, [])

    def test_what_the_installer_and_apps_need(self):
        required = {line for _, line in self.entries() if not line.startswith("?")}
        firsts = {line.split("|")[0] for line in required}
        for name in ("base", "linux", "linux-firmware", "mkinitcpio", "mkinitcpio-archiso", "syslinux",
                     "grub", "efibootmgr", "arch-install-scripts", "rsync", "dosfstools", "e2fsprogs",
                     "sudo", "greetd", "greetd-regreet", "cage", "hyprland", "kitty", "networkmanager",
                     "python", "python-gobject", "gtk4", "libadwaita", "tor", "firefox", "zsh"):
            self.assertIn(name, firsts, f"{name} precisa ser obrigatório em packages/iso.txt")


class Profile(unittest.TestCase):
    def permissions(self):
        script = (
            'declare -A file_permissions; profile="$1"; source "$1/profiledef.sh"; '
            'for k in "${!file_permissions[@]}"; do printf "%s %s\\n" "$k" "${file_permissions[$k]}"; done; '
            'printf "BOOTMODES %s\\n" "${bootmodes[*]}"; printf "ISONAME %s\\n" "$iso_name"; '
            'printf "LABEL %s\\n" "$iso_label"'
        )
        proc = subprocess.run(["bash", "-c", script, "profiledef", str(REPO)],
                              capture_output=True, text=True, check=True)
        return dict(line.split(" ", 1) for line in proc.stdout.splitlines())

    def test_every_script_becomes_executable(self):
        values = self.permissions()
        for script in sorted(BIN.iterdir()):
            self.assertEqual(values.get(f"/usr/local/bin/{script.name}"), "0:0:755", script.name)
        for name in ("install-backend", "firstboot-apply", "firstboot-console", "live-setup"):
            self.assertEqual(values.get(f"/usr/lib/lainos/{name}"), "0:0:755", name)
        self.assertEqual(values.get("/etc/sudoers.d/10-lainos"), "0:0:440")
        self.assertEqual(values.get("/root/customize_airootfs.sh"), "0:0:755")

    def test_boot_modes_and_name(self):
        values = self.permissions()
        self.assertEqual(values["BOOTMODES"], "bios.syslinux uefi.systemd-boot")
        self.assertEqual(values["ISONAME"], "lainos")
        self.assertRegex(values["LABEL"], r"^LAIN_\d{6}$")
        self.assertLessEqual(len(values["LABEL"]), 32)

    def test_boot_entries_find_the_iso(self):
        entries = sorted((REPO / "efiboot/loader/entries").glob("*.conf"))
        self.assertGreaterEqual(len(entries), 2)
        for entry in entries + [REPO / "syslinux/archiso_sys-linux.cfg"]:
            text = entry.read_text(encoding="utf-8")
            self.assertIn("archisobasedir=%INSTALL_DIR%", text, entry.name)
            self.assertIn("archisosearchuuid=%ARCHISO_UUID%", text, entry.name)
            self.assertIn("vmlinuz-linux", text, entry.name)
            self.assertIn("initramfs-linux.img", text, entry.name)
            self.assertTrue(text.isascii(), f"{entry.name}: os menus de boot só aceitam ASCII")

    def test_live_initramfs_has_the_archiso_hook(self):
        text = (AIROOTFS / "etc/mkinitcpio.conf.d/archiso.conf").read_text(encoding="utf-8")
        self.assertRegex(text, r"HOOKS=\(.*\barchiso\b.*\)")


class CrossReferences(unittest.TestCase):
    """Todo comando lain-* citado em alguma configuração precisa existir."""

    NOT_COMMANDS = {
        # nomes de serviço, arquivos de estado e sufixos que só parecem comandos
        "lain-live-setup", "lain-live-keyring", "lain-firstboot-console", "lain-firstboot", "lain-new",
        "lain-bios", "lain-efi", "lain-root", "lain-title", "lain-subtitle", "lain-step", "lain-warning",
        "lain-disk-size", "lain-big-button", "lain-progress", "lain-log", "lain-work", "lain-float", "lain-",
    }

    def test_referenced_commands_exist(self):
        ours = {p.name for p in BIN.iterdir()}
        missing = {}
        for base, dirs, files in os.walk(AIROOTFS):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                path = os.path.join(base, name)
                if os.path.splitext(path)[1].lower() in BINARY_SUFFIXES:
                    continue
                try:
                    with open(path, encoding="utf-8") as handle:
                        text = handle.read()
                except UnicodeDecodeError:
                    continue
                for word in set(re.findall(r"(?<![\w./-])lain-[a-z][a-z0-9-]*", text)):
                    word = word.rstrip("-")
                    if word in ours or word in self.NOT_COMMANDS:
                        continue
                    # classes de CSS (.lain-x) e nomes com ponto depois (lain-x.service) não são comandos
                    if re.search(rf"\.{re.escape(word)}\b|{re.escape(word)}\.(service|conf|css|\$\$)", text):
                        continue
                    missing.setdefault(word, []).append(os.path.relpath(path, AIROOTFS))
        self.assertEqual(missing, {})

    def test_bundles_are_complete(self):
        bundles = sorted((AIROOTFS / "usr/share/lainos/bundles").glob("*.conf"))
        self.assertGreaterEqual(len(bundles), 5)
        for bundle in bundles:
            text = bundle.read_text(encoding="utf-8")
            for key in ("NAME=", "DESC=", "CATEGORY="):
                self.assertRegex(text, rf"(?m)^{key}", f"{bundle.name}: falta {key}")
            subprocess.run(["bash", "-n", str(bundle)], check=True)

    def test_python_packages_have_entry_points(self):
        for package in ("installer", "firstboot", "welcome", "knights"):
            self.assertTrue((LIB / package / "__main__.py").is_file(), package)
            self.assertTrue((LIB / package / "__init__.py").is_file(), package)


if __name__ == "__main__":
    unittest.main()
