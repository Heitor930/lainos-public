"""Lê os bundles do lain-bundle e dispara a instalação num terminal.

Mantém a lista de pacotes numa fonte só (os .conf em /usr/share/lainos/
bundles), então o app de boas-vindas e a linha de comando nunca divergem.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass

BUNDLE_CMD = "lain-bundle"


@dataclass
class Bundle:
    id: str
    category: str
    name: str
    desc: str
    installed: bool


def list_bundles() -> list[Bundle]:
    exe = shutil.which(BUNDLE_CMD)
    if not exe:
        return []
    try:
        out = subprocess.run(
            [exe, "list"], capture_output=True, text=True, timeout=15, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    bundles = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) == 5:
            bid, category, name, desc, state = parts
            bundles.append(Bundle(bid, category, name, desc, state.strip() == "instalado"))
    return bundles


def _terminal_prefix() -> list[str]:
    """Como abrir uma janela de terminal, tentando o kitty e depois alternativas."""
    kitty = shutil.which("kitty")
    if kitty:
        return [kitty, "--class", "lain-float", "-e"]
    for term, flag in (("foot", "-e"), ("alacritty", "-e"), ("xterm", "-e")):
        exe = shutil.which(term)
        if exe:
            return [exe, flag]
    return []


def install(bundle_ids: list[str]) -> bool:
    """Abre um terminal que roda `lain-bundle install …` (ele pede a senha com sudo)."""
    exe = shutil.which(BUNDLE_CMD)
    term = _terminal_prefix()
    if not exe or not term or not bundle_ids:
        return False
    inner = f"{shlex.quote(exe)} install {' '.join(shlex.quote(b) for b in bundle_ids)}"
    # pausa no fim para a pessoa ler o resultado antes da janela fechar
    script = f"{inner}; echo; read -n1 -r -p 'Pressione uma tecla para fechar…'"
    try:
        subprocess.Popen(
            term + ["bash", "-lc", script],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return True


def run_detached(argv: list[str], *, in_terminal: bool = False) -> bool:
    exe = shutil.which(argv[0])
    if not exe:
        return False
    cmd = [exe] + argv[1:]
    if in_terminal:
        term = _terminal_prefix()
        if not term:
            return False
        cmd = term + cmd
    try:
        subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.DEVNULL)
    except OSError:
        return False
    return True


def is_live() -> bool:
    return os.path.isdir("/run/archiso")
