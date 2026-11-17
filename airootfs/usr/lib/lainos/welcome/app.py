"""‡ LainOS — app de boas-vindas e central de instalação.

Primeira coisa que a pessoa vê, tanto na ISO ao vivo quanto no primeiro login
do sistema instalado. Mostra as informações do computador, o botão de
instalar (quando na ISO) e os "bundles": jogos, arsenal de pentest, servidor,
desenvolvimento, drivers, anonimato e o Hermes Agent.
"""
from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import bundles, sysinfo  # noqa: E402

import lainui  # noqa: E402

APP_ID = "dev.lainos.Welcome"

# Agrupamento das categorias dos bundles em páginas, na ordem de exibição.
CATEGORY_PAGES = [
    ("uso", "Programas", "Conjuntos prontos para o dia a dia."),
    ("arsenal", "Arsenal de segurança",
     "Ferramentas de pentest para estudo, CTF e testes autorizados. "
     "Use somente em sistemas seus ou com permissão por escrito."),
    ("sistema", "Sistema e drivers", "Ajustes de hardware."),
]


class WelcomeWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, live: bool):
        super().__init__(application=app)
        self.live = live
        self.set_title("LainOS")
        self.set_default_size(1000, 680)
        self.set_size_request(380, 480)

        self._bundle_rows: list[tuple[bundles.Bundle, Gtk.Widget]] = []

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.add_css_class("flat")
        toolbar.add_top_bar(header)

        self.view_stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self.view_stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)

        self.view_stack.add_titled_with_icon(
            self._page_home(), "home", "Início", "go-home-symbolic"
        )
        for category, title, subtitle in CATEGORY_PAGES:
            page = self._page_bundles(category, subtitle)
            if page is not None:
                icon = {
                    "uso": "view-grid-symbolic",
                    "arsenal": "security-high-symbolic",
                    "sistema": "preferences-system-symbolic",
                }.get(category, "view-grid-symbolic")
                self.view_stack.add_titled_with_icon(page, category, title, icon)
        self.view_stack.add_titled_with_icon(
            self._page_about(), "about", "Sobre", "help-about-symbolic"
        )

        toolbar.set_content(self.view_stack)

        # Barra de troca de página embaixo, para telas estreitas
        bottom = Adw.ViewSwitcherBar(stack=self.view_stack)
        breakpoint_ = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse("max-width: 620px")
        )
        breakpoint_.add_setter(switcher, "visible", False)
        breakpoint_.add_setter(bottom, "reveal", True)
        self.add_breakpoint(breakpoint_)
        toolbar.add_bottom_bar(bottom)

        self.set_content(toolbar)

    # ---- páginas -------------------------------------------------------
    def _scroller(self, child: Gtk.Widget) -> Gtk.ScrolledWindow:
        clamp = Adw.Clamp(maximum_size=760, tightening_threshold=560)
        clamp.set_child(child)
        clamp.set_margin_top(24)
        clamp.set_margin_bottom(32)
        clamp.set_margin_start(12)
        clamp.set_margin_end(12)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(clamp)
        scroller.set_vexpand(True)
        return scroller

    def _page_home(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)

        # Cabeçalho com emblema e nome
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        hero.set_margin_top(8)
        logo = lainui.emblem(96)
        hero.append(logo)
        title = Gtk.Label()
        title.set_markup('<span size="26000" weight="300" letter_spacing="4000">LAIN</span>'
                         '<span size="26000" weight="300" letter_spacing="4000" foreground="#a9bb74"> OS</span>')
        hero.append(title)
        tagline = Gtk.Label(label="‡ stay wired")
        tagline.add_css_class("dim-label")
        hero.append(tagline)
        box.append(hero)

        if self.live:
            box.append(self._install_banner())

        # Informações do sistema
        info_group = Adw.PreferencesGroup(title="Este computador")
        for key, value in sysinfo.summary():
            row = Adw.ActionRow(title=key, subtitle=value)
            row.add_css_class("property")
            row.set_subtitle_selectable(True)
            info_group.add(row)
        box.append(info_group)

        # Hermes
        hermes_group = Adw.PreferencesGroup(
            title="Hermes Agent",
            description="Seu agente de IA pessoal (Nous Research). Já vem integrado: é "
            "baixado em segundo plano no primeiro login, e o provedor e o modelo "
            "você configura no primeiro uso.",
        )
        hermes_row = Adw.ActionRow(
            title="Abrir o Hermes",
            subtitle="Configurar e começar a usar (SUPER + H)",
        )
        hermes_row.add_prefix(self._icon("utilities-terminal-symbolic"))
        hermes_btn = Gtk.Button(label="Abrir")
        hermes_btn.add_css_class("suggested-action")
        hermes_btn.set_valign(Gtk.Align.CENTER)
        hermes_btn.connect("clicked", lambda *_: bundles.run_detached(
            ["kitty", "--class", "hermes", "-e", "hermes"]))
        hermes_row.add_suffix(hermes_btn)
        hermes_row.set_activatable_widget(hermes_btn)
        hermes_group.add(hermes_row)
        box.append(hermes_group)

        # Atalhos rápidos
        quick = Adw.PreferencesGroup(title="Primeiros passos")
        for title_, subtitle_, icon_, argv, term in [
            ("Trocar o papel de parede", "Escolha entre os temas ou use uma imagem sua",
             "preferences-desktop-wallpaper-symbolic", ["lain-wallpaper", "pick"], False),
            ("Ver os atalhos de teclado", "A cola completa (SUPER + F1)",
             "preferences-desktop-keyboard-symbolic", ["lain-keys"], False),
            ("Navegar anônimo pelo Tor", "Abre o Navi Ghost (Firefox endurecido)",
             "security-high-symbolic", ["navi-ghost"], False),
        ]:
            row = Adw.ActionRow(title=title_, subtitle=subtitle_)
            row.add_prefix(self._icon(icon_))
            row.set_activatable(True)
            row.connect("activated", lambda _r, a=argv, t=term: bundles.run_detached(a, in_terminal=t))
            row.add_suffix(self._icon("go-next-symbolic"))
            quick.add(row)
        box.append(quick)

        return self._scroller(box)

    def _install_banner(self) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.add_css_class("card")
        card.set_margin_top(4)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        inner.set_margin_top(18)
        inner.set_margin_bottom(18)
        inner.set_margin_start(18)
        inner.set_margin_end(18)
        heading = Gtk.Label(xalign=0)
        heading.set_markup('<span size="15000" weight="600">Você está na versão ao vivo</span>')
        inner.append(heading)
        desc = Gtk.Label(
            label="Experimente à vontade: nada é gravado no disco. Quando quiser, "
            "instale: um clique, o disco inteiro é apagado e o sistema é copiado. "
            "Usuário e senha você cria no primeiro início. "
            "(Se a tela bloquear aqui, a senha é: live)",
            xalign=0, wrap=True,
        )
        desc.add_css_class("dim-label")
        inner.append(desc)
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_row.set_margin_top(8)
        install = Gtk.Button(label="Instalar o LainOS")
        install.add_css_class("suggested-action")
        install.add_css_class("pill")
        install.connect("clicked", lambda *_: bundles.run_detached(["lain-install"]))
        btn_row.append(install)
        inner.append(btn_row)
        card.append(inner)
        return card

    def _page_bundles(self, category: str, subtitle: str) -> Gtk.Widget | None:
        items = [b for b in bundles.list_bundles() if b.category == category]
        if not items:
            if category == "uso":  # lain-bundle indisponível: mostra aviso em vez de página vazia
                return self._page_unavailable()
            return None

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        if subtitle:
            note = Gtk.Label(label=subtitle, xalign=0, wrap=True)
            note.add_css_class("dim-label")
            note.set_margin_start(4)
            note.set_margin_end(4)
            box.append(note)

        group = Adw.PreferencesGroup()
        for bundle in items:
            row = Adw.ActionRow(title=bundle.name, subtitle=bundle.desc)
            row.set_subtitle_lines(3)
            if bundle.installed:
                tag = Gtk.Label(label="instalado")
                tag.add_css_class("success")
                tag.add_css_class("caption-heading")
                tag.set_valign(Gtk.Align.CENTER)
                row.add_suffix(tag)
            else:
                btn = Gtk.Button(label="Instalar")
                btn.add_css_class("pill")
                btn.set_valign(Gtk.Align.CENTER)
                btn.connect("clicked", self._on_install, bundle)
                row.add_suffix(btn)
                self._bundle_rows.append((bundle, btn))
            group.add(row)
        box.append(group)
        return self._scroller(box)

    def _page_unavailable(self) -> Gtk.Widget:
        status = Adw.StatusPage(
            title="Pacotes indisponíveis",
            description="A ferramenta lain-bundle não foi encontrada neste sistema.",
            icon_name="dialog-warning-symbolic",
        )
        return status

    def _page_about(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        group = Adw.PreferencesGroup(
            title="LainOS",
            description="Distribuição Linux baseada em Arch, com Hyprland. Feita para "
            "programadores, pentest e quem curte a atmosfera de Serial Experiments Lain. "
            "A identidade visual é original; coloque suas próprias artes com o comando lain-style.",
        )
        for title_, value_ in [
            ("Base", "Arch Linux (rolling release)"),
            ("Área de trabalho", "Hyprland (Wayland)"),
            ("Repositórios", "Arch oficial + BlackArch (opcional)"),
        ]:
            group.add(Adw.ActionRow(title=title_, subtitle=value_, css_classes=["property"]))
        box.append(group)

        links = Adw.PreferencesGroup(title="Ajuda")
        for title_, subtitle_, argv, term in [
            ("Manual no terminal", "man lainos", ["man", "lainos"], True),
            ("Atualizar o sistema", "lain-update", ["lain-update"], True),
        ]:
            row = Adw.ActionRow(title=title_, subtitle=subtitle_, activatable=True)
            row.add_suffix(self._icon("go-next-symbolic"))
            row.connect("activated", lambda _r, a=argv, t=term: bundles.run_detached(a, in_terminal=t))
            links.add(row)
        box.append(links)
        return self._scroller(box)

    # ---- helpers -------------------------------------------------------
    def _icon(self, name: str) -> Gtk.Image:
        img = Gtk.Image.new_from_icon_name(name)
        img.add_css_class("dim-label")
        return img

    def _on_install(self, button: Gtk.Button, bundle: bundles.Bundle) -> None:
        if bundles.install([bundle.id]):
            button.set_label("Instalando…")
            button.set_sensitive(False)
            toast = f"Instalando {bundle.name} numa janela de terminal."
        else:
            toast = "Não consegui abrir o instalador. Rode no terminal: lain-bundle install " + bundle.id
        self._toast(toast)

    def _toast(self, text: str) -> None:
        # Adw.ApplicationWindow não tem ToastOverlay embutido; usa notificação do sistema
        try:
            app = self.get_application()
            notif = Gio.Notification.new("LainOS")
            notif.set_body(text)
            app.send_notification(None, notif)
        except Exception:
            print(text, file=sys.stderr)


class WelcomeApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.live = sysinfo.is_live()
        self.add_main_option(
            "live", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
            "Forçar o modo ISO ao vivo", None,
        )

    def do_command_line(self, command_line):
        options = command_line.get_options_dict().end().unpack()
        if "live" in options:
            self.live = True
        self.activate()
        return 0

    def do_startup(self):
        Adw.Application.do_startup(self)
        # tema da distro aplicado pelo próprio app: fica igual mesmo fora da
        # sessão Hyprland (por exemplo, aberto com sudo ou em outra área de trabalho)
        lainui.apply_theme()

    def do_activate(self):
        win = self.get_active_window()
        if not win:
            win = WelcomeWindow(self, self.live)
        win.present()


def main() -> int:
    return WelcomeApp().run(sys.argv)
