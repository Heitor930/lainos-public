"""Abre o assistente de primeiro início de verdade e percorre o fluxo inteiro:
teclado e fuso, conta com um erro de digitação corrigido, criação da conta
(em modo de teste, sem mexer no sistema) e a entrada na sessão por um greetd
de mentira.

Uso: firstboot_flow.py PASTA_DE_SAIDA
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ROOT = REPO / "airootfs"
LIB = ROOT / "usr/lib/lainos"
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
SANDBOX = OUT / "firstboot-root"
STATE = OUT / "firstboot-state.txt"
SOCKET = OUT / "greetd.sock"
ZONEINFO = OUT / "zoneinfo"

sys.path.insert(0, str(LIB))
sys.path.insert(0, str(REPO / "tests/unit"))

for path in (STATE, SOCKET, SANDBOX / "commands.log"):
    if path.exists() or path.is_socket():
        path.unlink()
(SANDBOX / "var/lib/lainos").mkdir(parents=True, exist_ok=True)
(SANDBOX / "var/lib/lainos/firstboot").touch()
(ZONEINFO / "America").mkdir(parents=True, exist_ok=True)
for zone in ("America/Sao_Paulo", "America/Manaus", "UTC"):
    (ZONEINFO / zone).write_bytes(b"TZif")
(ZONEINFO / "zone1970.tab").write_text(
    "BR\t-2332-04637\tAmerica/Sao_Paulo\nBR\t-0308-06001\tAmerica/Manaus\n", encoding="utf-8")

os.environ.update({
    "LAIN_SHARE_DIR": str(ROOT / "usr/share/lainos"),
    "LAIN_FIRSTBOOT_ROOT": str(SANDBOX),
    "LAIN_LIB_DIR": str(LIB),
    "LAIN_FIRSTBOOT_HELPER": f"{sys.executable} -I {LIB / 'firstboot-apply'}",
    "LAIN_FIRSTBOOT_STATE": str(STATE),
    "LAIN_KEYBOARD_CONF": str(ROOT / "etc/X11/xorg.conf.d/00-keyboard.conf"),
    "LAIN_ZONEINFO": str(ZONEINFO),
    "GREETD_SOCK": str(SOCKET),
})
os.environ.pop("SUDO_UID", None)

from test_greetd import FakeGreetd  # noqa: E402

PASSWORD = "lain-1998"
server = FakeGreetd(str(SOCKET), password=PASSWORD)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib  # noqa: E402

from firstboot import app as firstboot_app  # noqa: E402

problems: list[str] = []
pages: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        problems.append(message)


def shot(name: str) -> None:
    subprocess.run(["import", "-window", "root", str(OUT / f"firstboot-{name}.png")],
                   check=False, capture_output=True)


application = firstboot_app.FirstBootApp("system")


def window():
    return application.props.active_window


def step_system() -> bool:
    win = window()
    pages.append(win.stack.get_visible_child_name())
    shot("1-teclado-e-fuso")
    win.system_button.emit("clicked")
    GLib.timeout_add(1500, step_account_wrong)
    return False


def step_account_wrong() -> bool:
    win = window()
    pages.append(win.stack.get_visible_child_name())
    win.name_row.set_text("Ana Clara Souza")
    check(win.user_row.get_text() == "ana", f"usuário sugerido: {win.user_row.get_text()!r}")
    win.password_row.set_text("lain")
    win.confirm_row.set_text("lain")
    win.account_button.emit("clicked")
    GLib.timeout_add(700, step_account_right)
    return False


def step_account_right() -> bool:
    win = window()
    shot("2-senha-curta")
    check(win.stack.get_visible_child_name() == "account", "uma senha curta não pode avançar")
    check(not (SANDBOX / "commands.log").exists(), "nada pode ser criado com a senha recusada")
    win.password_row.set_text(PASSWORD)
    win.confirm_row.set_text(PASSWORD)
    win.host_row.set_text("navi")
    GLib.timeout_add(500, step_finish)
    return False


def step_finish() -> bool:
    shot("3-conta")
    window().account_button.emit("clicked")
    GLib.timeout_add(300, lambda: shot("4-criando") or False)
    return False


GLib.timeout_add(1800, step_system)
GLib.timeout_add(15000, application.quit)
application.run([])
server.close()

check(pages == ["system", "account"], f"páginas: {pages}")
state = STATE.read_text(encoding="utf-8").strip() if STATE.exists() else ""
check(state == "login", f"estado final: {state!r} (esperava 'login')")
check([m["type"] for m in server.log] == ["create_session", "post_auth_message_response", "start_session"],
      f"conversa com o greetd: {[m['type'] for m in server.log]}")
if server.log:
    check(server.log[0].get("username") == "ana", "o greetd recebeu outro usuário")
    check(server.log[-1].get("cmd") == ["lain-start-hyprland"], f"sessão pedida: {server.log[-1].get('cmd')}")
log = SANDBOX / "commands.log"
commands = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
check(len(commands) == 2 and commands[0].startswith("useradd ") and commands[0].endswith(" ana")
      and commands[1] == "chpasswd", f"comandos: {commands}")
check(PASSWORD not in "\n".join(commands), "a senha apareceu na linha de comando")
check((SANDBOX / "etc/hostname").read_text(encoding="utf-8") == "navi\n"
      if (SANDBOX / "etc/hostname").exists() else False, "nome do computador não gravado")
check(not (SANDBOX / "var/lib/lainos/firstboot").exists(), "a marca do primeiro início não foi removida")

if problems:
    print("primeiro início: FALHOU")
    for problem in problems:
        print("  -", problem)
    sys.exit(1)
print("primeiro início: ok", pages, "->", state)
