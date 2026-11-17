"""‡ LainOS — assistente de primeiro início.

Aparece uma única vez, no lugar da tela de login, no primeiro início depois
da instalação. Dois passos: (1) teclado e fuso horário, (2) nome, usuário,
senha e nome do computador. Ao concluir, já entra na área de trabalho.

Roda sem privilégios, como o usuário da tela de login. Quem aplica as
mudanças é /usr/lib/lainos/firstboot-apply, chamado pelo sudo.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

import lainui  # noqa: E402

from . import greetd, rules  # noqa: E402

APP_ID = "dev.lainos.FirstBoot"
HELPER = "/usr/lib/lainos/firstboot-apply"
SESSION_COMMAND = ["lain-start-hyprland"]
SESSION_ENV = [
    "XDG_SESSION_TYPE=wayland",
    "XDG_SESSION_DESKTOP=Hyprland",
    "XDG_CURRENT_DESKTOP=Hyprland",
]
BACKGROUND_CANDIDATES = (
    "/var/lib/lainos/login.jpg",
    str(lainui.SHARE / "login.jpg"),
)

CSS = """
.lain-firstboot-card {
    background-color: alpha(#0d0f0d, 0.92);
    border: 1px solid alpha(#e8eae4, 0.10);
    border-radius: 20px;
    padding: 30px 34px;
    box-shadow: 0 24px 80px alpha(black, 0.6);
}
.lain-firstboot-shade { background-color: alpha(#080908, 0.45); }
"""


def state_file() -> Path:
    override = os.environ.get("LAIN_FIRSTBOOT_STATE")
    if override:
        return Path(override)
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/lain-firstboot-{os.getuid()}"
    return Path(runtime) / "lain-firstboot.state"


def write_state(value: str) -> None:
    """Avisa o lain-greeter do que fazer quando esta janela fechar."""
    target = state_file()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value + "\n", encoding="utf-8")
    except OSError:
        pass


def helper_command(action: str) -> list[str]:
    override = os.environ.get("LAIN_FIRSTBOOT_HELPER")
    base = shlex.split(override) if override else ["sudo", "-n", HELPER]
    return [*base, action]


def call_helper(action: str, data: dict) -> tuple[bool, dict]:
    try:
        proc = subprocess.run(
            helper_command(action), input=json.dumps(data), text=True,
            capture_output=True, timeout=120, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, {"error": f"Não consegui aplicar as mudanças ({type(exc).__name__})."}
    try:
        answer = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        detail = (proc.stderr or "").strip().splitlines()
        return False, {"error": detail[-1] if detail else "O sistema não respondeu."}
    return bool(answer.get("ok")), answer


def current_timezone() -> str:
    try:
        target = os.path.realpath("/etc/localtime")
    except OSError:
        return rules.DEFAULT_TIMEZONE
    prefix = str(rules.ZONEINFO) + "/"
    if target.startswith(prefix) and rules.timezone_ok(target[len(prefix):]):
        return target[len(prefix):]
    return rules.DEFAULT_TIMEZONE


class FirstBootWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, start_step: str):
        super().__init__(application=app)
        self.set_title("Primeiro início")
        self.set_default_size(1100, 760)
        self.busy = False
        self._username_edited = False
        self._setting_username = False

        overlay = Gtk.Overlay()
        background = None
        for candidate in BACKGROUND_CANDIDATES:
            if os.path.isfile(candidate):
                background = Gtk.Picture.new_for_filename(candidate)
                background.set_content_fit(Gtk.ContentFit.COVER)
                break
        if background is None:
            background = Gtk.Box()
        overlay.set_child(background)
        shade = Gtk.Box()
        shade.add_css_class("lain-firstboot-shade")
        overlay.add_overlay(shade)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT,
                               transition_duration=260, vhomogeneous=False,
                               interpolate_size=True)
        self.stack.add_named(self._page_system(), "system")
        self.stack.add_named(self._page_account(), "account")
        self.stack.add_named(self._page_working(), "working")

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.add_css_class("lain-firstboot-card")
        card.append(self.stack)
        clamp = Adw.Clamp(maximum_size=560, tightening_threshold=420)
        clamp.set_child(card)
        clamp.set_valign(Gtk.Align.CENTER)
        clamp.set_margin_top(18)
        clamp.set_margin_bottom(18)
        clamp.set_margin_start(14)
        clamp.set_margin_end(14)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(clamp)
        overlay.add_overlay(scroller)
        self.set_content(overlay)

        self.stack.set_visible_child_name("account" if start_step == "account" else "system")
        if start_step == "account":
            GLib.idle_add(self.name_row.grab_focus)

    # ---- passo 1: teclado e fuso ---------------------------------------
    def _page_system(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.append(lainui.emblem(72))
        box.append(lainui.label("PRIMEIRO INÍCIO · 1 DE 2", "lain-step"))
        box.append(lainui.label("Bem-vindo ao LainOS", "lain-title"))
        box.append(lainui.label("Dois passos rápidos e o sistema é seu.", "lain-subtitle"))

        group = Adw.PreferencesGroup()
        group.set_margin_top(8)

        self.keyboard_row = Adw.ComboRow(title="Teclado")
        self.keyboard_row.set_model(Gtk.StringList.new([k.label for k in rules.KEYBOARDS]))
        self.initial_keyboard = rules.current_keyboard()
        self.keyboard_row.set_selected(rules.KEYBOARDS.index(self.initial_keyboard))
        group.add(self.keyboard_row)

        self.timezones = rules.list_timezones()
        self.timezone_row = Adw.ComboRow(title="Fuso horário")
        self.timezone_row.set_model(Gtk.StringList.new(self.timezones))
        self.timezone_row.set_expression(
            Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        self.timezone_row.set_enable_search(True)
        zone = current_timezone()
        if zone not in self.timezones:
            zone = rules.DEFAULT_TIMEZONE
        self.timezone_row.set_selected(self.timezones.index(zone))
        group.add(self.timezone_row)
        box.append(group)

        box.append(lainui.label(
            "Se você trocar o teclado, a tela pisca por um instante para aplicar.",
            "dim-label"))

        self.system_error = lainui.label("", "lain-warning")
        self.system_error.set_visible(False)
        box.append(self.system_error)

        self.system_button = Gtk.Button(label="Continuar")
        self.system_button.add_css_class("suggested-action")
        self.system_button.add_css_class("pill")
        self.system_button.add_css_class("lain-big-button")
        self.system_button.set_halign(Gtk.Align.CENTER)
        self.system_button.set_margin_top(4)
        self.system_button.connect("clicked", self._on_system_next)
        box.append(self.system_button)

        power = Gtk.Button(label="Desligar o computador")
        power.add_css_class("flat")
        power.set_halign(Gtk.Align.CENTER)
        power.connect("clicked", self._on_poweroff)
        box.append(power)
        return box

    def _on_system_next(self, _button: Gtk.Button) -> None:
        if self.busy:
            return
        keyboard = rules.KEYBOARDS[self.keyboard_row.get_selected()]
        timezone = self.timezones[self.timezone_row.get_selected()]
        self._set_busy(True)
        self.system_error.set_visible(False)

        def work() -> None:
            ok, answer = call_helper("system", {"keyboard": keyboard.id, "timezone": timezone})
            GLib.idle_add(self._system_done, ok, answer, keyboard)

        threading.Thread(target=work, daemon=True).start()

    def _system_done(self, ok: bool, answer: dict, keyboard: rules.Keyboard) -> bool:
        self._set_busy(False)
        if not ok:
            self.system_error.set_label(answer.get("error") or "Não consegui aplicar.")
            self.system_error.set_visible(True)
            return GLib.SOURCE_REMOVE
        if keyboard.id != self.initial_keyboard.id:
            # O teclado só troca quando a tela reinicia: o lain-greeter reabre
            # o assistente direto no passo 2, já com o teclado novo.
            write_state("restart-account")
            self.get_application().quit()
            return GLib.SOURCE_REMOVE
        self.stack.set_visible_child_name("account")
        self.name_row.grab_focus()
        return GLib.SOURCE_REMOVE

    # ---- passo 2: conta ------------------------------------------------
    def _page_account(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.append(lainui.label("PRIMEIRO INÍCIO · 2 DE 2", "lain-step"))
        box.append(lainui.label("Crie sua conta", "lain-title"))
        box.append(lainui.label(
            "Esta conta administra o computador. A senha é pedida ao entrar e "
            "ao instalar programas.", "lain-subtitle"))

        group = Adw.PreferencesGroup()
        group.set_margin_top(8)
        self.name_row = Adw.EntryRow(title="Seu nome")
        self.name_row.connect("changed", self._on_name_changed)
        group.add(self.name_row)

        self.user_row = Adw.EntryRow(title="Nome de usuário")
        self.user_row.set_input_purpose(Gtk.InputPurpose.FREE_FORM)
        self.user_row.connect("changed", self._on_user_changed)
        group.add(self.user_row)

        self.password_row = Adw.PasswordEntryRow(title="Senha")
        group.add(self.password_row)
        self.confirm_row = Adw.PasswordEntryRow(title="Repita a senha")
        group.add(self.confirm_row)

        self.host_row = Adw.EntryRow(title="Nome do computador")
        self.host_row.set_text(rules.DEFAULT_HOSTNAME)
        group.add(self.host_row)
        box.append(group)

        for row in (self.name_row, self.user_row, self.password_row,
                    self.confirm_row, self.host_row):
            row.connect("entry-activated", self._on_account_finish)
            # o aviso de erro some assim que a pessoa volta a digitar
            row.connect("changed", lambda *_: self.account_error.set_visible(False))

        self.account_error = lainui.label("", "lain-warning")
        self.account_error.set_visible(False)
        box.append(self.account_error)

        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        buttons.set_margin_top(4)
        back = Gtk.Button(label="Voltar")
        back.add_css_class("pill")
        back.connect("clicked", lambda *_: self.stack.set_visible_child_name("system"))
        buttons.append(back)
        self.account_button = Gtk.Button(label="Concluir")
        self.account_button.add_css_class("suggested-action")
        self.account_button.add_css_class("pill")
        self.account_button.add_css_class("lain-big-button")
        self.account_button.connect("clicked", self._on_account_finish)
        buttons.append(self.account_button)
        box.append(buttons)
        return box

    def _on_name_changed(self, row: Adw.EntryRow) -> None:
        if self._username_edited:
            return
        self._setting_username = True
        self.user_row.set_text(rules.suggest_username(row.get_text()))
        self._setting_username = False

    def _on_user_changed(self, row: Adw.EntryRow) -> None:
        if not self._setting_username:
            self._username_edited = bool(row.get_text())

    def _account_fields(self) -> dict:
        return {
            "fullname": rules.clean_full_name(self.name_row.get_text()),
            "username": self.user_row.get_text().strip(),
            "password": self.password_row.get_text(),
            "hostname": self.host_row.get_text().strip().lower() or rules.DEFAULT_HOSTNAME,
        }

    def _on_account_finish(self, *_args) -> None:
        if self.busy:
            return
        fields = self._account_fields()
        error = (
            rules.username_error(fields["username"])
            or rules.password_error(fields["password"], self.confirm_row.get_text())
            or rules.hostname_error(fields["hostname"])
        )
        if error:
            self.account_error.set_label(error)
            self.account_error.set_visible(True)
            return
        self.account_error.set_visible(False)
        self._set_busy(True)
        self.working_title.set_label("Criando sua conta")
        self.stack.set_visible_child_name("working")

        def work() -> None:
            ok, answer = call_helper("account", fields)
            GLib.idle_add(self._account_done, ok, answer, fields)

        threading.Thread(target=work, daemon=True).start()

    def _account_done(self, ok: bool, answer: dict, fields: dict) -> bool:
        if not ok:
            self._set_busy(False)
            self.account_error.set_label(answer.get("error") or "Não consegui criar a conta.")
            self.account_error.set_visible(True)
            self.stack.set_visible_child_name("account")
            return GLib.SOURCE_REMOVE
        self.working_title.set_label("Tudo pronto. Entrando…")

        def enter() -> None:
            state = "done"
            if greetd.available():
                try:
                    greetd.login(fields["username"], fields["password"],
                                 SESSION_COMMAND, env=SESSION_ENV)
                    state = "login"
                except (greetd.GreetdError, OSError, ValueError):
                    state = "done"  # cai na tela de login normal
            GLib.idle_add(self._leave, state)

        threading.Thread(target=enter, daemon=True).start()
        return GLib.SOURCE_REMOVE

    def _leave(self, state: str) -> bool:
        write_state(state)
        self.get_application().quit()
        return GLib.SOURCE_REMOVE

    # ---- espera --------------------------------------------------------
    def _page_working(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.set_margin_top(40)
        box.set_margin_bottom(40)
        box.append(lainui.emblem(72))
        self.working_title = lainui.label("Criando sua conta", "lain-title")
        box.append(self.working_title)
        spinner = Gtk.Spinner(spinning=True)
        spinner.set_size_request(36, 36)
        spinner.set_halign(Gtk.Align.CENTER)
        box.append(spinner)
        return box

    # ---- utilidades ----------------------------------------------------
    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.system_button.set_sensitive(not busy)
        self.account_button.set_sensitive(not busy)

    def _on_poweroff(self, _button: Gtk.Button) -> None:
        command = shlex.split(os.environ.get("LAIN_POWEROFF_CMD", "systemctl poweroff"))
        try:
            subprocess.Popen(command)
        except OSError:
            pass


class FirstBootApp(Adw.Application):
    def __init__(self, start_step: str):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.start_step = start_step

    def do_startup(self):
        Adw.Application.do_startup(self)
        lainui.apply_theme()
        display = Gdk.Display.get_default()
        if display is not None:
            provider = Gtk.CssProvider()
            provider.load_from_string(CSS)
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2,
            )

    def do_activate(self):
        window = self.props.active_window
        if window is None:
            window = FirstBootWindow(self, self.start_step)
        window.present()


def main() -> int:
    start_step = "system"
    args = sys.argv[1:]
    if "--step" in args:
        index = args.index("--step")
        if index + 1 < len(args) and args[index + 1] == "account":
            start_step = "account"
    # limpa um estado antigo: se a janela cair, o lain-greeter não pode ler lixo
    try:
        state_file().unlink()
    except OSError:
        pass
    return FirstBootApp(start_step).run([sys.argv[0]])
