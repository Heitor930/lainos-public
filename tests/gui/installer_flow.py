"""Abre o instalador de verdade (com discos e motor de mentira) e percorre o fluxo:
escolher o disco, clicar em instalar, acompanhar o progresso e chegar ao fim.

Uso: installer_flow.py PASTA_DE_SAIDA [ok|fail|one|none]
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ROOT = REPO / "airootfs"
OUT = Path(sys.argv[1])
MODE = sys.argv[2] if len(sys.argv) > 2 else "ok"
OUT.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "usr/lib/lainos"))
os.environ["LAIN_SHARE_DIR"] = str(ROOT / "usr/share/lainos")
os.environ["LAIN_INSTALL_CMD"] = str(HERE / "fake-backend.sh")
os.environ["LAIN_REBOOT_CMD"] = "true"
os.environ["FAKE_BACKEND_ARGS"] = str(OUT / f"backend-args-{MODE}.txt")
if MODE == "fail":
    os.environ["FAKE_FAIL"] = "1"

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib  # noqa: E402

from installer import app as installer_app  # noqa: E402
from installer import disks  # noqa: E402

GIB = 1024**3
DISKS = [
    {"name": "nvme0n1", "path": "/dev/nvme0n1", "size": 500107862016, "model": "Samsung SSD 970 EVO Plus 500GB",
     "tran": "nvme", "rm": False, "hotplug": False, "ro": False, "type": "disk",
     "children": [
         {"name": "nvme0n1p1", "path": "/dev/nvme0n1p1", "size": 104857600, "type": "part", "fstype": "vfat"},
         {"name": "nvme0n1p3", "path": "/dev/nvme0n1p3", "size": 499 * GIB, "type": "part", "fstype": "ntfs"}]},
    {"name": "sda", "path": "/dev/sda", "size": 1000204886016, "model": "WDC WD10EZEX-08WN4A0", "vendor": "ATA     ",
     "tran": "sata", "rota": True, "rm": False, "hotplug": False, "ro": False, "type": "disk",
     "children": [{"name": "sda1", "path": "/dev/sda1", "size": 931 * GIB, "type": "part", "fstype": "ext4"}]},
    {"name": "sdb", "path": "/dev/sdb", "size": 30752636928, "model": "Ultra Fit", "vendor": "SanDisk ",
     "tran": "usb", "rm": True, "hotplug": True, "ro": False, "type": "disk", "fstype": "iso9660"},
]
if MODE == "one":
    DISKS = DISKS[:1]
elif MODE == "none":
    DISKS = DISKS[2:]
real_list = disks.list_disks
disks.list_disks = lambda *args, **kwargs: real_list({"blockdevices": DISKS}, "")

problems: list[str] = []
pages: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        problems.append(message)


def shot(name: str) -> None:
    subprocess.run(["import", "-window", "root", str(OUT / f"installer-{MODE}-{name}.png")],
                   check=False, capture_output=True)


application = installer_app.InstallerApp()


def window():
    return application.props.active_window


def step_choose() -> bool:
    win = window()
    pages.append(win.stack.get_visible_child_name())
    shot("1-escolha")
    if MODE == "none":
        check(pages[-1] == "message", f"sem discos, esperava a página de aviso e veio {pages[-1]}")
        application.quit()
        return False
    check(pages[-1] == "choose", f"página inicial inesperada: {pages[-1]}")
    check([d.path for d in win.candidates] == [d["path"] for d in DISKS if d.get("fstype") != "iso9660"],
          "a lista de discos não bate")
    if MODE == "one":
        check(win.install_button.get_sensitive(), "com um disco só, o botão já devia estar liberado")
    else:
        check(not win.install_button.get_sensitive(),
              "com mais de um disco, o botão tem de ficar travado até a pessoa escolher")
        win._select(win.candidates[0])
        check(win.install_button.get_sensitive(), "o botão não liberou depois da escolha")
        shot("2-escolhido")
    # um clique só: o botão já diz o que faz ("Apagar o disco e instalar")
    win.install_button.emit("clicked")
    GLib.timeout_add(900, step_progress)
    return False


def step_progress() -> bool:
    pages.append(window().stack.get_visible_child_name())
    shot("3-progresso")
    GLib.timeout_add(3500, step_end)
    return False


def step_end() -> bool:
    pages.append(window().stack.get_visible_child_name())
    shot("4-fim")
    application.quit()
    return False


GLib.timeout_add(1500, step_choose)
GLib.timeout_add(20000, application.quit)
application.run([])

if MODE != "none":
    expected_end = "error" if MODE == "fail" else "done"
    check(pages[-1] == expected_end, f"o fluxo terminou em {pages[-1]!r}, esperava {expected_end!r} ({pages})")
    args_file = OUT / f"backend-args-{MODE}.txt"
    args = args_file.read_text(encoding="utf-8").strip() if args_file.exists() else ""
    check(args == "--disk /dev/nvme0n1 --confirm APAGAR", f"o motor foi chamado com: {args!r}")

if problems:
    print(f"instalador ({MODE}): FALHOU")
    for problem in problems:
        print("  -", problem)
    sys.exit(1)
print(f"instalador ({MODE}): ok {pages}")
