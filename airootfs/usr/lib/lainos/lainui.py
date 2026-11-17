"""‡ LainOS — pedaços de interface compartilhados pelos apps da distro.

O instalador e o assistente de primeiro início rodam fora de uma sessão de
usuário comum (um como usuário ao vivo, o outro dentro da tela de login), então
carregam o tema por conta própria em vez de depender de ~/.config/gtk-4.0.
"""
from __future__ import annotations

import os
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

SHARE = Path(os.environ.get("LAIN_SHARE_DIR", "/usr/share/lainos"))
THEME_CSS = SHARE / "theme" / "gtk.css"
EMBLEM = SHARE / "logo" / "emblem-256.png"

EXTRA_CSS = """
.lain-title { font-size: 26pt; font-weight: 300; letter-spacing: 1px; }
.lain-subtitle { font-size: 12pt; opacity: 0.72; }
.lain-step { font-size: 10pt; letter-spacing: 3px; opacity: 0.55; }
.lain-warning { color: @warning_color; }
.lain-disk-size { font-size: 15pt; font-weight: 600; }
.lain-big-button { padding: 14px 34px; font-size: 12pt; font-weight: 600; }
.lain-progress trough, .lain-progress progress { min-height: 8px; border-radius: 4px; }
.lain-log { font-family: "JetBrainsMono Nerd Font", monospace; font-size: 9pt; opacity: 0.8; }
"""


def apply_theme() -> None:
    """Força o esquema escuro e aplica as cores da distro nesta aplicação."""
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
    display = Gdk.Display.get_default()
    if display is None:
        return
    if THEME_CSS.is_file():
        theme = Gtk.CssProvider()
        theme.load_from_path(str(THEME_CSS))
        Gtk.StyleContext.add_provider_for_display(
            display, theme, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )
    extra = Gtk.CssProvider()
    extra.load_from_string(EXTRA_CSS)
    Gtk.StyleContext.add_provider_for_display(
        display, extra, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1
    )


def emblem(size: int = 96) -> Gtk.Widget:
    """O emblema da distro; cai para um ícone genérico se o arquivo faltar."""
    if EMBLEM.is_file():
        image = Gtk.Image.new_from_file(str(EMBLEM))
    else:
        image = Gtk.Image.new_from_icon_name("computer-symbolic")
    image.set_pixel_size(size)
    image.set_halign(Gtk.Align.CENTER)
    return image


def label(text: str, *classes: str, wrap: bool = True, center: bool = True) -> Gtk.Label:
    widget = Gtk.Label(label=text)
    widget.set_wrap(wrap)
    if center:
        # ocupa a largura toda e centraliza o texto: só quebra linha quando precisa
        widget.set_justify(Gtk.Justification.CENTER)
        widget.set_halign(Gtk.Align.FILL)
        widget.set_xalign(0.5)
    else:
        widget.set_xalign(0)
        widget.set_halign(Gtk.Align.FILL)
    for css in classes:
        widget.add_css_class(css)
    return widget
