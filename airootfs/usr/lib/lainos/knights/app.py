"""‡ Knights OSINT — interface gráfica (GTK4 / libadwaita).

Quatro ferramentas de reconhecimento sobre fontes abertas: nome de usuário em
sites públicos, inteligência de domínio, IP e leitor de metadados. Tudo roda
em segundo plano para a janela nunca travar.
"""
from __future__ import annotations

import sys
import threading
import webbrowser

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import engine  # noqa: E402

import lainui  # noqa: E402

APP_ID = "dev.lainos.Knights"

DISCLAIMER = (
    "Knights trabalha só com informação pública (perfis abertos, DNS, WHOIS, "
    "metadados de arquivos que você escolhe). Use para estudo, CTF e investigações "
    "autorizadas, sempre dentro da lei."
)


class Tool(Gtk.Box):
    """Base: um campo de entrada, um botão e uma área de resultados."""

    def __init__(self, title: str, subtitle: str, placeholder: str, button: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_vexpand(True)

        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        header.set_margin_top(20)
        header.set_margin_start(20)
        header.set_margin_end(20)
        h = Gtk.Label(xalign=0)
        h.set_markup(f'<span size="16000" weight="600">{GLib.markup_escape_text(title)}</span>')
        header.append(h)
        sub = Gtk.Label(label=subtitle, xalign=0, wrap=True)
        sub.add_css_class("dim-label")
        header.append(sub)
        self.append(header)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.set_margin_top(14)
        bar.set_margin_start(20)
        bar.set_margin_end(20)
        self.entry = Gtk.Entry(hexpand=True, placeholder_text=placeholder)
        self.entry.connect("activate", lambda *_: self.run())
        bar.append(self.entry)
        self.extra_widget(bar)
        self.run_btn = Gtk.Button(label=button)
        self.run_btn.add_css_class("suggested-action")
        self.run_btn.connect("clicked", lambda *_: self.run())
        bar.append(self.run_btn)
        self.append(bar)

        self.spinner = Gtk.Spinner()
        self.spinner.set_margin_top(6)
        self.append(self.spinner)

        self.results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.results.set_margin_top(14)
        self.results.set_margin_bottom(24)
        self.results.set_margin_start(20)
        self.results.set_margin_end(20)
        clamp = Adw.Clamp(maximum_size=720, child=self.results)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroller.set_child(clamp)
        self.append(scroller)

        self._placeholder()

    # ganchos que as subclasses sobrescrevem
    def extra_widget(self, bar: Gtk.Box) -> None:
        pass

    def run(self) -> None:
        raise NotImplementedError

    # ---- utilidades de UI ---------------------------------------------
    def _clear(self) -> None:
        child = self.results.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.results.remove(child)
            child = nxt

    def _placeholder(self) -> None:
        self._clear()
        lbl = Gtk.Label(label="Os resultados aparecem aqui.", wrap=True)
        lbl.add_css_class("dim-label")
        lbl.set_margin_top(40)
        self.results.append(lbl)

    def _busy(self, on: bool) -> None:
        self.run_btn.set_sensitive(not on)
        if on:
            self.spinner.start()
            self.spinner.set_visible(True)
        else:
            self.spinner.stop()
            self.spinner.set_visible(False)

    def _group(self, title: str = "") -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup()
        if title:
            group.set_title(title)
        self.results.append(group)
        return group

    def _row(self, group, title, subtitle="", link="") -> Adw.ActionRow:
        row = Adw.ActionRow(title=title)
        if subtitle:
            row.set_subtitle(subtitle)
            row.set_subtitle_selectable(True)
        if link:
            row.set_activatable(True)
            row.add_suffix(Gtk.Image.new_from_icon_name("adw-external-link-symbolic"))
            row.connect("activated", lambda *_: _open(link))
        group.add(row)
        return row

    def _error(self, text: str) -> None:
        self._clear()
        status = Adw.StatusPage(
            title="Nada a mostrar", description=text,
            icon_name="dialog-information-symbolic",
        )
        status.set_vexpand(False)
        self.results.append(status)

    def _run_thread(self, work, done) -> None:
        """Roda `work()` numa thread e entrega o resultado a `done(result)` na UI."""
        self._busy(True)
        self._clear()

        def worker():
            try:
                result = work()
                err = None
            except Exception as exc:  # noqa: BLE001
                result, err = None, exc
            GLib.idle_add(finish, result, err)

        def finish(result, err):
            self._busy(False)
            if err is not None:
                self._error(f"Algo deu errado: {err}")
            else:
                done(result)
            return False

        threading.Thread(target=worker, daemon=True).start()


class UsernameTool(Tool):
    def __init__(self):
        super().__init__(
            "Nome de usuário",
            "Procura o mesmo nome em sites públicos e mostra onde há um perfil.",
            "ex.: torvalds", "Buscar",
        )

    def run(self):
        name = self.entry.get_text().strip()
        if not engine.valid_username(name):
            self._error("Use um nome de usuário válido (letras, números, . _ -).")
            return
        sites = engine.load_sites()
        if not sites:
            self._error("Não encontrei a lista de sites (sites.json).")
            return

        self._busy(True)
        self._clear()
        found_group = self._group("Encontrados")
        other_group = self._group("Sem conta / erro")
        counters = {"found": 0, "other": 0}
        done = {"n": 0}
        total = len(sites)
        progress = Gtk.Label(label=f"consultando {total} sites…", xalign=0)
        progress.add_css_class("dim-label")
        self.results.append(progress)

        def on_hit(hit: engine.UserHit):
            if hit.state == "found":
                counters["found"] += 1
                self._row(found_group, hit.site, hit.url, link=hit.url)
            else:
                counters["other"] += 1
                label = "sem conta" if hit.state == "missing" else hit.detail
                self._row(other_group, hit.site, label)
            done["n"] += 1
            progress.set_label(
                f"{done['n']}/{total} · {counters['found']} encontrados"
                if done["n"] < total else f"{counters['found']} perfis encontrados de {total} sites"
            )
            if done["n"] >= total:
                self._busy(False)
            return False

        def worker(site):
            hit = engine.check_username(site, name)
            GLib.idle_add(on_hit, hit)

        for site in sites:
            threading.Thread(target=worker, args=(site,), daemon=True).start()


class DomainTool(Tool):
    def __init__(self):
        super().__init__(
            "Domínio",
            "Registros DNS e dados de WHOIS de um domínio.",
            "ex.: exemplo.com.br", "Consultar",
        )

    def run(self):
        domain = self.entry.get_text().strip()
        if not engine.valid_domain(domain.rstrip(".")):
            self._error("Digite um domínio válido, como exemplo.com.br.")
            return
        self._run_thread(lambda: engine.domain_report(domain), self._show)

    def _show(self, rep: engine.DomainReport):
        if rep.error:
            self._error(rep.error)
            return
        if not rep.records and not rep.whois:
            self._error("Sem resposta de DNS nem WHOIS. Verifique a conexão.")
            return
        if rep.records:
            g = self._group("DNS")
            for rtype, values in rep.records.items():
                self._row(g, rtype, "\n".join(values))
        if rep.whois:
            g = self._group("WHOIS")
            for key, value in rep.whois.items():
                self._row(g, key, value)


class IPTool(Tool):
    def __init__(self):
        super().__init__(
            "Endereço IP",
            "DNS reverso e localização aproximada de um IP (dado público, nível de cidade).",
            "ex.: 8.8.8.8", "Consultar",
        )

    def run(self):
        ip = self.entry.get_text().strip()
        if not engine.valid_ip(ip):
            self._error("Digite um endereço IP válido (IPv4 ou IPv6).")
            return
        self._run_thread(lambda: engine.ip_report(ip), self._show)

    def _show(self, rep: engine.IPReport):
        if rep.error and not rep.geo:
            self._error(rep.error)
            return
        g = self._group("IP")
        self._row(g, "DNS reverso", rep.reverse)
        if rep.geo:
            g2 = self._group("Localização aproximada")
            for key, value in rep.geo.items():
                self._row(g2, key, value)


class MetadataTool(Tool):
    def __init__(self):
        self._path = ""
        super().__init__(
            "Metadados de arquivo",
            "Lê os metadados ocultos (EXIF, autor, GPS…) de um arquivo seu. Ótimo "
            "para ver o que você está revelando antes de publicar.",
            "", "Analisar",
        )
        self.entry.set_visible(False)

    def extra_widget(self, bar: Gtk.Box):
        self.pick = Gtk.Button(label="Escolher arquivo…")
        self.pick.set_hexpand(True)
        self.pick.connect("clicked", self._choose)
        bar.append(self.pick)

    def _choose(self, *_):
        dialog = Gtk.FileDialog(title="Escolha um arquivo")
        dialog.open(self.get_root(), None, self._chosen)

    def _chosen(self, dialog, result):
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return
        if gfile:
            self._path = gfile.get_path() or ""
            self.pick.set_label(gfile.get_basename() or "arquivo")

    def run(self):
        if not self._path:
            self._error("Escolha um arquivo primeiro.")
            return
        self._run_thread(lambda: engine.file_metadata(self._path), self._show)

    def _show(self, data: dict[str, str]):
        if "_erro" in data:
            self._error(data["_erro"])
            return
        if "_vazio" in data:
            self._error(data["_vazio"])
            return
        g = self._group("Metadados")
        for key, value in data.items():
            if key == "_mapa":
                self._row(g, "Abrir local no mapa", value, link=value)
            else:
                self._row(g, key, value)


TOOLS = [
    ("Nome de usuário", "avatar-default-symbolic", UsernameTool),
    ("Domínio", "network-server-symbolic", DomainTool),
    ("Endereço IP", "network-wired-symbolic", IPTool),
    ("Metadados", "image-x-generic-symbolic", MetadataTool),
]


def _open(url: str) -> None:
    try:
        Gio.AppInfo.launch_default_for_uri(url, None)
    except GLib.Error:
        webbrowser.open(url)


class KnightsWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("Knights OSINT")
        self.set_default_size(960, 680)
        self.set_size_request(360, 480)

        split = Adw.NavigationSplitView()

        # ---- barra lateral ----
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar_header = Adw.HeaderBar()
        title = Adw.WindowTitle(title="Knights", subtitle="OSINT")
        sidebar_header.set_title_widget(title)
        sidebar_box.append(sidebar_header)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        listbox = Gtk.ListBox()
        listbox.add_css_class("navigation-sidebar")
        listbox.connect("row-selected", self._on_select)
        for name, icon, factory in TOOLS:
            self.stack.add_named(factory(), name)
            row = Adw.ActionRow(title=name)
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
            listbox.append(row)
        sidebar_box.append(listbox)

        tip = Gtk.Label(label=DISCLAIMER, wrap=True, xalign=0)
        tip.add_css_class("dim-label")
        tip.add_css_class("caption")
        tip.set_margin_start(12)
        tip.set_margin_end(12)
        tip.set_margin_bottom(12)
        tip.set_margin_top(12)
        tip.set_valign(Gtk.Align.END)
        tip.set_vexpand(True)
        sidebar_box.append(tip)

        sidebar = Adw.NavigationPage(title="Knights", child=sidebar_box)
        split.set_sidebar(sidebar)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content_header = Adw.HeaderBar()
        content_box.append(content_header)
        content_box.append(self.stack)
        self.stack.set_vexpand(True)
        content = Adw.NavigationPage(title="OSINT", child=content_box)
        split.set_content(content)

        self.set_content(split)
        listbox.select_row(listbox.get_row_at_index(0))

    def _on_select(self, _listbox, row):
        if row is not None:
            name = TOOLS[row.get_index()][0]
            self.stack.set_visible_child_name(name)


class KnightsApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_startup(self):
        Adw.Application.do_startup(self)
        # tema da distro aplicado pelo próprio app: fica igual mesmo fora da
        # sessão Hyprland (por exemplo, aberto com sudo ou em outra área de trabalho)
        lainui.apply_theme()

    def do_activate(self):
        win = self.get_active_window() or KnightsWindow(self)
        win.present()


def main() -> int:
    return KnightsApp().run(sys.argv)
