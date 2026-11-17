"""Regras do primeiro início: teclados oferecidos, fusos e validação dos campos.

Usado dos dois lados: pela tela (para avisar a pessoa na hora) e pelo
programa que aplica as mudanças como root (que confere tudo de novo e não
confia no que a tela mandou).
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

ZONEINFO = Path(os.environ.get("LAIN_ZONEINFO", "/usr/share/zoneinfo"))
KEYBOARD_CONF = Path(os.environ.get("LAIN_KEYBOARD_CONF", "/etc/X11/xorg.conf.d/00-keyboard.conf"))
DEFAULT_TIMEZONE = "America/Sao_Paulo"
DEFAULT_HOSTNAME = "lainos"
MIN_PASSWORD = 6


@dataclass(frozen=True)
class Keyboard:
    id: str
    label: str
    layout: str
    variant: str
    console: str  # mapa de teclas do console de texto (vconsole)


KEYBOARDS: list[Keyboard] = [
    Keyboard("br", "Português (Brasil, ABNT2)", "br", "", "br-abnt2"),
    Keyboard("us-intl", "Inglês (EUA, internacional com acentos)", "us", "intl", "us-acentos"),
    Keyboard("us", "Inglês (EUA)", "us", "", "us"),
    Keyboard("pt", "Português (Portugal)", "pt", "", "pt-latin1"),
    Keyboard("latam", "Espanhol (América Latina)", "latam", "", "la-latin1"),
    Keyboard("es", "Espanhol (Espanha)", "es", "", "es"),
    Keyboard("gb", "Inglês (Reino Unido)", "gb", "", "uk"),
    Keyboard("fr", "Francês", "fr", "", "fr"),
    Keyboard("de", "Alemão", "de", "", "de"),
    Keyboard("it", "Italiano", "it", "", "it"),
    Keyboard("jp", "Japonês", "jp", "", "jp106"),
]


def keyboard_by_id(keyboard_id: str) -> Keyboard | None:
    for keyboard in KEYBOARDS:
        if keyboard.id == keyboard_id:
            return keyboard
    return None


def current_keyboard() -> Keyboard:
    """O teclado em uso agora, lido do arquivo que a tela de login também lê."""
    layout, variant = "br", ""
    try:
        text = KEYBOARD_CONF.read_text(encoding="utf-8")
    except OSError:
        text = ""
    found = re.search(r'Option\s+"XkbLayout"\s+"([^"]*)"', text)
    if found:
        layout = found.group(1)
    found = re.search(r'Option\s+"XkbVariant"\s+"([^"]*)"', text)
    if found:
        variant = found.group(1)
    for keyboard in KEYBOARDS:
        if keyboard.layout == layout and keyboard.variant == variant:
            return keyboard
    return KEYBOARDS[0]


# ---- fuso horário ------------------------------------------------------
def list_timezones() -> list[str]:
    zones: set[str] = set()
    for table in ("zone1970.tab", "zone.tab"):
        try:
            lines = (ZONEINFO / table).read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                zones.add(parts[2].strip())
        if zones:
            break
    zones.add("UTC")
    zones.add(DEFAULT_TIMEZONE)
    return sorted(zones)


def timezone_ok(name: str) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+){0,2}", name or ""):
        return False
    return (ZONEINFO / name).is_file()


# ---- conta -------------------------------------------------------------
USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
HOSTNAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
RESERVED_USERS = {
    "root", "greeter", "wired", "bin", "daemon", "mail", "ftp", "http", "nobody",
    "dbus", "tor", "git", "sys", "adm", "wheel", "users", "polkitd", "avahi",
    "systemd", "admin", "administrator", "guest", "live", "sshd", "uuidd", "rtkit",
}


def suggest_username(full_name: str) -> str:
    """Primeiro nome, sem acentos, pronto para ser um nome de usuário."""
    plain = unicodedata.normalize("NFKD", full_name).encode("ascii", "ignore").decode()
    first = plain.strip().split(" ")[0].lower() if plain.strip() else ""
    cleaned = re.sub(r"[^a-z0-9_-]", "", first)
    cleaned = cleaned.lstrip("0123456789-")
    return cleaned[:32]


def clean_full_name(full_name: str) -> str:
    # o campo de comentário do /etc/passwd não aceita ":" nem quebras de linha
    text = re.sub(r"[\x00-\x1f\x7f:,]", " ", full_name or "")
    return " ".join(text.split())[:64]


def username_error(name: str) -> str:
    if not name:
        return "Escolha um nome de usuário."
    if not USERNAME_RE.fullmatch(name):
        return ("O nome de usuário usa só letras minúsculas, números, - e _, "
                "e começa com uma letra.")
    if name in RESERVED_USERS:
        return f"O nome “{name}” é reservado pelo sistema. Escolha outro."
    return ""


def password_error(password: str, confirm: str | None = None) -> str:
    if not password:
        return "Crie uma senha."
    if len(password) < MIN_PASSWORD:
        return f"A senha precisa de pelo menos {MIN_PASSWORD} caracteres."
    if len(password) > 256 or any(ch in password for ch in "\n\r\x00"):
        return "A senha tem um caractere que o sistema não aceita."
    if confirm is not None and password != confirm:
        return "As duas senhas não são iguais."
    return ""


def hostname_error(name: str) -> str:
    if not name:
        return "Dê um nome ao computador."
    if not HOSTNAME_RE.fullmatch(name):
        return ("O nome do computador usa só letras minúsculas, números e hífen, "
                "sem começar ou terminar com hífen.")
    return ""
