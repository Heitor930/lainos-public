"""‡ LainOS — instalador de um clique.

Uma tela só: mostra o disco que vai receber o sistema, avisa que tudo nele
será apagado e tem um único botão. Depois do clique não há mais perguntas:
o disco é apagado, o sistema é copiado e o boot é configurado. Usuário, senha,
teclado e fuso ficam para o primeiro início do sistema instalado.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

import lainui  # noqa: E402

from . import disks  # noqa: E402

APP_ID = "dev.lainos.Installer"
BACKEND = "/usr/lib/lainos/install-backend"
LOG_PATH = "/var/log/lainos-install.log"


def backend_command(disk_path: str) -> list[str]:
    """Comando do motor de instalação. LAIN_INSTALL_CMD existe para testes."""
    override = os.environ.get("LAIN_INSTALL_CMD")
    base = shlex.split(override) if override else ["sudo", "-n", BACKEND]
    return [*base, "--disk", disk_path, "--confirm", "APAGAR"]


def is_live() -> bool:
    return os.path.isdir("/run/archiso") or bool(os.environ.get("LAIN_INSTALL_CMD"))


class InstallerWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app)
        self.set_title("Instalar o LainOS")
        self.set_default_size(760, 640)
        self.set_size_request(380, 520)

        self.running = False
        self.selected: disks.Disk | None = None
        self.candidates: list[disks.Disk] = []
        self._inhibit_cookie = 0
        self._log_lines: list[str] = []

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.add_css_class("flat")
        header.set_show_title(False)
        toolbar.add_top_bar(header)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                               transition_duration=220)
        self.stack.add_named(self._page_choose(), "choose")
        self.stack.add_named(self._page_progress(), "progress")
        self.stack.add_named(self._page_done(), "done")
        self.stack.add_named(self._page_error(), "error")
        self.stack.add_named(self._page_message(), "message")
        toolbar.set_content(self.stack)
        self.set_content(toolbar)

        self.connect("close-request", self._on_close_request)

        if is_live():
            self.refresh_disks()
        else:
            self._show_message(
                "computer-symbolic",
                "O instalador roda na versão ao vivo",
                "Inicie o computador pelo pendrive do LainOS e abra o instalador por lá.",
            )

    # ---- construção das páginas ---------------------------------------
    def _column(self, spacing: int = 18) -> tuple[Gtk.Widget, Gtk.Box]:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
        box.set_valign(Gtk.Align.CENTER)
        clamp = Adw.Clamp(maximum_size=600, tightening_threshold=440)
        clamp.set_child(box)
        clamp.set_margin_top(12)
        clamp.set_margin_bottom(28)
        clamp.set_margin_start(18)
        clamp.set_margin_end(18)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(clamp)
        return scroller, box

    def _page_choose(self) -> Gtk.Widget:
        page, box = self._column()
        box.append(lainui.emblem(84))
        box.append(lainui.label("Instalar o LainOS", "lain-title"))
        box.append(lainui.label(
            "O sistema ocupa o disco inteiro. Usuário e senha você cria depois, "
            "no primeiro início.", "lain-subtitle"))

        self.disk_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.disk_list.add_css_class("boxed-list")
        self.disk_list.set_margin_top(8)
        box.append(self.disk_list)

        self.warning = lainui.label("", "lain-warning")
        box.append(self.warning)

        self.install_button = Gtk.Button(label="Apagar o disco e instalar")
        self.install_button.add_css_class("destructive-action")
        self.install_button.add_css_class("pill")
        self.install_button.add_css_class("lain-big-button")
        self.install_button.set_halign(Gtk.Align.CENTER)
        self.install_button.set_margin_top(6)
        self.install_button.connect("clicked", self._on_install_clicked)
        box.append(self.install_button)

        rescan = Gtk.Button(label="Procurar discos de novo")
        rescan.add_css_class("flat")
        rescan.set_halign(Gtk.Align.CENTER)
        rescan.connect("clicked", lambda *_: self.refresh_disks())
        box.append(rescan)
        return page

    def _page_progress(self) -> Gtk.Widget:
        page, box = self._column(16)
        box.append(lainui.emblem(84))
        box.append(lainui.label("Instalando", "lain-title"))
        self.progress_target = lainui.label("", "lain-subtitle")
        box.append(self.progress_target)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.add_css_class("lain-progress")
        self.progress_bar.set_margin_top(14)
        box.append(self.progress_bar)

        self.progress_message = lainui.label("Preparando", "dim-label")
        box.append(self.progress_message)
        box.append(lainui.label(
            "Leva alguns minutos. Não desligue o computador nem tire o pendrive.",
            "dim-label"))

        self.log_view = Gtk.Label(xalign=0, yalign=0, wrap=True, selectable=True)
        self.log_view.add_css_class("lain-log")
        expander = Gtk.Expander(label="Detalhes")
        expander.set_child(self.log_view)
        expander.set_margin_top(10)
        box.append(expander)
        return page

    def _page_done(self) -> Gtk.Widget:
        page, box = self._column()
        icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        icon.set_pixel_size(72)
        icon.add_css_class("success")
        box.append(icon)
        box.append(lainui.label("Instalação concluída", "lain-title"))
        box.append(lainui.label(
            "Reinicie e tire o pendrive quando a tela apagar. No primeiro início "
            "você escolhe o teclado e cria seu usuário e sua senha.", "lain-subtitle"))

        reboot = Gtk.Button(label="Reiniciar agora")
        reboot.add_css_class("suggested-action")
        reboot.add_css_class("pill")
        reboot.add_css_class("lain-big-button")
        reboot.set_halign(Gtk.Align.CENTER)
        reboot.set_margin_top(10)
        reboot.connect("clicked", self._on_reboot)
        box.append(reboot)

        stay = Gtk.Button(label="Continuar na versão ao vivo")
        stay.add_css_class("flat")
        stay.set_halign(Gtk.Align.CENTER)
        stay.connect("clicked", lambda *_: self.close())
        box.append(stay)
        return page

    def _page_error(self) -> Gtk.Widget:
        page, box = self._column()
        icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        icon.set_pixel_size(72)
        icon.add_css_class("error")
        box.append(icon)
        box.append(lainui.label("A instalação não terminou", "lain-title"))
        self.error_message = lainui.label("", "lain-subtitle")
        box.append(self.error_message)
        box.append(lainui.label(f"O registro completo fica em {LOG_PATH}.", "dim-label"))

        retry = Gtk.Button(label="Tentar de novo")
        retry.add_css_class("suggested-action")
        retry.add_css_class("pill")
        retry.set_halign(Gtk.Align.CENTER)
        retry.set_margin_top(10)
        retry.connect("clicked", lambda *_: self.refresh_disks())
        box.append(retry)
        return page

    def _page_message(self) -> Gtk.Widget:
        self.message_page = Adw.StatusPage()
        self.message_button = Gtk.Button(label="Procurar discos de novo")
        self.message_button.add_css_class("pill")
        self.message_button.set_halign(Gtk.Align.CENTER)
        self.message_button.connect("clicked", lambda *_: self.refresh_disks())
        self.message_page.set_child(self.message_button)
        return self.message_page

    def _show_message(self, icon: str, title: str, text: str, retry: bool = False) -> None:
        self.message_page.set_icon_name(icon)
        self.message_page.set_title(title)
        self.message_page.set_description(text)
        self.message_button.set_visible(retry)
        self.stack.set_visible_child_name("message")

    # ---- discos --------------------------------------------------------
    def refresh_disks(self) -> None:
        if self.running:
            return
        self.candidates = disks.list_disks()
        child = self.disk_list.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.disk_list.remove(child)
            child = following

        if not self.candidates:
            self.selected = None
            self._show_message(
                "drive-harddisk-symbolic",
                "Nenhum disco para instalar",
                "Não encontrei um disco interno com pelo menos 12 GB. Se o disco "
                "não aparece, confira nas configurações da BIOS/UEFI se o modo do "
                "controlador está em AHCI (e não em RAID/RST).",
                retry=True,
            )
            return

        group: Gtk.CheckButton | None = None
        many = len(self.candidates) > 1
        for disk in self.candidates:
            row = Adw.ActionRow(title=GLib.markup_escape_text(disk.title),
                                subtitle=GLib.markup_escape_text(disk.subtitle))
            size = Gtk.Label(label=disk.size_text)
            size.add_css_class("lain-disk-size")
            row.add_suffix(size)
            if many:
                check = Gtk.CheckButton()
                check.set_valign(Gtk.Align.CENTER)
                if group is None:
                    group = check
                else:
                    check.set_group(group)
                check.connect("toggled", self._on_disk_toggled, disk)
                row.add_prefix(check)
                row.set_activatable_widget(check)
            else:
                icon = Gtk.Image.new_from_icon_name("drive-harddisk-symbolic")
                icon.set_pixel_size(28)
                row.add_prefix(icon)
            self.disk_list.append(row)

        # Um disco só: já fica escolhido, é um clique. Mais de um: a pessoa
        # aponta qual, e só então o botão libera (nunca adivinhamos o disco).
        self._select(None if many else self.candidates[0])
        self.stack.set_visible_child_name("choose")

    def _on_disk_toggled(self, check: Gtk.CheckButton, disk: disks.Disk) -> None:
        if check.get_active():
            self._select(disk)

    def _select(self, disk: disks.Disk | None) -> None:
        self.selected = disk
        self.install_button.set_sensitive(disk is not None)
        if disk is None:
            self.warning.set_label("Escolha o disco que vai receber o sistema.")
            return
        self.warning.set_label(
            f"Tudo o que existe em {disk.title} ({disk.size_text}) será apagado: "
            "sistemas, programas e arquivos. Não dá para desfazer."
        )

    # ---- instalação ----------------------------------------------------
    def _on_install_clicked(self, _button: Gtk.Button) -> None:
        if self.running or self.selected is None:
            return
        disk = self.selected
        self.running = True
        self._log_lines = []
        self.log_view.set_label("")
        self.progress_bar.set_fraction(0.0)
        self.progress_message.set_label("Preparando")
        self.progress_target.set_label(f"{disk.title} · {disk.size_text} · {disk.path}")
        self.stack.set_visible_child_name("progress")

        app = self.get_application()
        if app is not None:
            self._inhibit_cookie = app.inhibit(
                self,
                Gtk.ApplicationInhibitFlags.SUSPEND | Gtk.ApplicationInhibitFlags.IDLE
                | Gtk.ApplicationInhibitFlags.LOGOUT,
                "Instalando o LainOS",
            )
        threading.Thread(target=self._worker, args=(disk,), daemon=True).start()

    def _worker(self, disk: disks.Disk) -> None:
        error = ""
        try:
            proc = subprocess.Popen(
                backend_command(disk.path),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, errors="replace",
            )
        except OSError as exc:
            GLib.idle_add(self._finished, 1, f"Não consegui iniciar o instalador ({exc}).")
            return
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            if line.startswith("@@ "):
                _, percent, message = (line.split(" ", 2) + ["", ""])[:3]
                try:
                    fraction = max(0.0, min(1.0, int(percent) / 100))
                except ValueError:
                    continue
                GLib.idle_add(self._progress, fraction, message)
            elif line.startswith("!! "):
                error = line[3:].strip()
                GLib.idle_add(self._append_log, line)
            elif line.strip():
                GLib.idle_add(self._append_log, line)
        code = proc.wait()
        GLib.idle_add(self._finished, code, error)

    def _progress(self, fraction: float, message: str) -> bool:
        self.progress_bar.set_fraction(fraction)
        self.progress_message.set_label(message)
        self._append_log(f"{int(fraction * 100):3d}%  {message}")
        return GLib.SOURCE_REMOVE

    def _append_log(self, line: str) -> bool:
        # as linhas de cópia chegam a cada 1%: mantém só a última delas
        if self._log_lines and "Copiando o sistema" in line and "Copiando o sistema" in self._log_lines[-1]:
            self._log_lines[-1] = line
        else:
            self._log_lines.append(line)
        self._log_lines = self._log_lines[-14:]
        self.log_view.set_label("\n".join(self._log_lines))
        return GLib.SOURCE_REMOVE

    def _finished(self, code: int, error: str) -> bool:
        self.running = False
        app = self.get_application()
        if app is not None and self._inhibit_cookie:
            app.uninhibit(self._inhibit_cookie)
            self._inhibit_cookie = 0
        if code == 0:
            self.progress_bar.set_fraction(1.0)
            self.stack.set_visible_child_name("done")
        else:
            self.error_message.set_label(
                error or "O instalador parou sem dizer o motivo (código %d)." % code
            )
            self.stack.set_visible_child_name("error")
        return GLib.SOURCE_REMOVE

    def _on_reboot(self, _button: Gtk.Button) -> None:
        command = shlex.split(os.environ.get("LAIN_REBOOT_CMD", "systemctl reboot"))
        try:
            subprocess.Popen(command)
        except OSError:
            pass

    def _on_close_request(self, _window) -> bool:
        # não deixa fechar no meio: um disco pela metade não inicia
        return self.running


class InstallerApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_startup(self):
        Adw.Application.do_startup(self)
        lainui.apply_theme()

    def do_activate(self):
        window = self.props.active_window
        if window is None:
            window = InstallerWindow(self)
        window.present()


def main() -> int:
    return InstallerApp().run(sys.argv)
