"""Informações do sistema mostradas na aba inicial das boas-vindas."""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _os_release() -> dict[str, str]:
    data = {}
    for line in _read("/etc/os-release").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            data[key] = value.strip().strip('"')
    return data


def distro_name() -> str:
    rel = _os_release()
    return rel.get("PRETTY_NAME") or rel.get("NAME") or "LainOS"


def kernel() -> str:
    return platform.release()


def cpu() -> str:
    for line in _read("/proc/cpuinfo").splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return platform.processor() or "desconhecido"


def gpu() -> str:
    exe = shutil.which("lspci")
    if not exe:
        return "desconhecido"
    try:
        out = subprocess.run(
            [exe, "-mm"], capture_output=True, text=True, timeout=5, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "desconhecido"
    cards = []
    for line in out.splitlines():
        if re.search(r'"(VGA|3D|Display)', line):
            fields = re.findall(r'"([^"]*)"', line)
            # campos: slot, classe, fornecedor, dispositivo, ...
            if len(fields) >= 4:
                vendor = fields[2].split(" ")[0]
                device = fields[3]
                cards.append(f"{vendor} {device}")
    return " · ".join(cards) if cards else "desconhecido"


def memory() -> str:
    total = 0
    for line in _read("/proc/meminfo").splitlines():
        if line.startswith("MemTotal:"):
            total = int(line.split()[1]) * 1024
            break
    if not total:
        return "desconhecido"
    return f"{total / 1024**3:.1f} GiB"


def disk() -> str:
    try:
        usage = shutil.disk_usage("/")
    except OSError:
        return "desconhecido"
    return f"{usage.used / 1024**3:.0f} GiB usados de {usage.total / 1024**3:.0f} GiB"


def hostname() -> str:
    return platform.node() or _read("/etc/hostname").strip() or "lainos"


def desktop() -> str:
    exe = shutil.which("Hyprland") or shutil.which("hyprland")
    version = ""
    if exe:
        try:
            out = subprocess.run(
                ["hyprctl", "version"], capture_output=True, text=True, timeout=4, check=False
            ).stdout
            m = re.search(r"v?(\d+\.\d+\.\d+)", out)
            if m:
                version = " " + m.group(1)
        except (OSError, subprocess.SubprocessError):
            pass
    return f"Hyprland{version}"


def summary() -> list[tuple[str, str]]:
    return [
        ("Distro", distro_name()),
        ("Kernel", kernel()),
        ("Área de trabalho", desktop()),
        ("Máquina", hostname()),
        ("CPU", cpu()),
        ("Vídeo", gpu()),
        ("Memória", memory()),
        ("Disco", disk()),
    ]


def is_live() -> bool:
    return os.path.isdir("/run/archiso")
