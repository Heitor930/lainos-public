"""Descobre em quais discos o LainOS pode ser instalado.

Fica separado da interface para poder ser testado sem tela: recebe a saída
do `lsblk -J` e devolve a lista de discos candidatos, já sem a mídia de
instalação, sem discos pequenos demais e com o disco mais provável primeiro.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

MIN_BYTES = 12 * 1024**3
LSBLK_COLUMNS = "NAME,PATH,SIZE,MODEL,VENDOR,TRAN,RM,HOTPLUG,RO,ROTA,TYPE,FSTYPE,LABEL,PKNAME"

FS_NAMES = {
    "ntfs": "Windows (NTFS)",
    "vfat": "FAT",
    "exfat": "exFAT",
    "ext4": "Linux (ext4)",
    "ext3": "Linux (ext3)",
    "btrfs": "Linux (btrfs)",
    "xfs": "Linux (xfs)",
    "crypto_LUKS": "criptografado",
    "swap": "swap",
    "apfs": "macOS (APFS)",
    "hfsplus": "macOS (HFS+)",
    "BitLocker": "Windows (BitLocker)",
    "LVM2_member": "LVM",
}


@dataclass
class Disk:
    path: str
    size: int
    model: str
    transport: str
    removable: bool
    contents: str
    rotational: bool = False

    @property
    def size_text(self) -> str:
        return human_size(self.size)

    @property
    def title(self) -> str:
        return self.model or "Disco sem nome"

    @property
    def kind(self) -> str:
        if self.transport == "usb":
            return "USB"
        if self.transport == "nvme" or "nvme" in self.path:
            return "SSD NVMe"
        if self.transport in ("sata", "ata"):
            return "HD SATA" if self.rotational else "SSD SATA"
        if self.transport == "mmc" or "mmcblk" in self.path:
            return "eMMC / cartão"
        if self.transport == "virtio" or "/vd" in self.path:
            return "disco virtual"
        return "disco"

    @property
    def subtitle(self) -> str:
        return f"{self.kind} · {self.path} · {self.contents}"


def human_size(size: int) -> str:
    """Tamanho como aparece na caixa do disco (base 1000)."""
    value = float(size)
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if value < 1000 or unit == "TB":
            if unit in ("B", "kB", "MB"):
                return f"{value:.0f} {unit}"
            text = f"{value:.1f}".rstrip("0").rstrip(".") if value < 100 else f"{value:.0f}"
            return f"{text.replace('.', ',')} {unit}"
        value /= 1000
    return f"{size} B"


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip() in ("1", "true", "True")


def _walk(node: dict):
    yield node
    for child in node.get("children") or []:
        yield from _walk(child)


def _contents(node: dict) -> str:
    parts = [n for n in _walk(node) if n is not node and n.get("type") == "part"]
    kinds: list[str] = []
    for n in list(_walk(node)):
        fstype = n.get("fstype")
        if not fstype:
            continue
        name = FS_NAMES.get(fstype, fstype)
        if name not in kinds:
            kinds.append(name)
    if not parts and not kinds:
        return "vazio"
    count = len(parts)
    head = "1 partição" if count == 1 else f"{count} partições"
    if not count:
        head = "sem partições"
    return f"{head}: {', '.join(kinds)}" if kinds else head


def lsblk_json() -> dict:
    try:
        raw = subprocess.run(
            ["lsblk", "-J", "-b", "-o", LSBLK_COLUMNS],
            capture_output=True, text=True, timeout=15, check=False,
        ).stdout
        return json.loads(raw)
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"blockdevices": []}


LIVE_MOUNTS = ("/run/archiso/bootmnt", "/run/archiso/img_dev")


def live_medium_sources() -> list[str]:
    """Dispositivos de onde a sessão ao vivo subiu (lista vazia se não der para saber).

    /run/archiso/bootmnt é a mídia de instalação; /run/archiso/img_dev aparece
    quando a ISO foi iniciada de dentro de um arquivo (pendrives multiboot).
    """
    sources: list[str] = []
    for mount in LIVE_MOUNTS:
        try:
            source = subprocess.run(
                ["findmnt", "-no", "SOURCE", mount],
                capture_output=True, text=True, timeout=5, check=False,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
        if source and source not in sources:
            sources.append(source)
    return sources


def list_disks(data: dict | None = None, live_source: str | list[str] | None = None,
               min_bytes: int = MIN_BYTES) -> list[Disk]:
    if data is None:
        data = lsblk_json()
    if live_source is None:
        live_source = live_medium_sources()
    live = {live_source} if isinstance(live_source, str) else set(live_source)
    live.discard("")

    disks: list[Disk] = []
    for node in data.get("blockdevices", []):
        if node.get("type") != "disk":
            continue
        name = node.get("name") or ""
        path = node.get("path") or f"/dev/{name}"
        if name.startswith(("zram", "ram", "loop", "fd", "sr")):
            continue
        if _truthy(node.get("ro")):
            continue
        try:
            size = int(node.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        if size < min_bytes:
            continue
        members = list(_walk(node))
        # a própria mídia de instalação: é ISO9660 ou é de onde a sessão ao vivo subiu
        if any(n.get("fstype") == "iso9660" for n in members):
            continue
        if any((n.get("path") or f"/dev/{n.get('name')}") in live for n in members):
            continue
        model = " ".join(
            part for part in ((node.get("vendor") or "").strip(), (node.get("model") or "").strip())
            if part and part.upper() not in ("ATA", "NVME")
        )
        disks.append(Disk(
            path=path,
            size=size,
            model=" ".join(model.split()),
            transport=(node.get("tran") or "").lower(),
            removable=_truthy(node.get("rm")) or _truthy(node.get("hotplug")),
            contents=_contents(node),
            rotational=_truthy(node.get("rota")),
        ))

    # internos primeiro; entre eles, SSD antes de HD; depois os maiores
    disks.sort(key=lambda d: (d.removable or d.transport == "usb", d.rotational, -d.size))
    return disks
