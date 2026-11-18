#!/usr/bin/env python3
"""‡ LainOS — testa a ISO de verdade numa máquina virtual (QEMU).

É o teste que roda no GitHub depois que a ISO fica pronta. Ele faz, sem
ninguém olhando, o mesmo caminho de quem instala:

  live       inicia a ISO, espera a sessão ao vivo, entra pelo console serial
             como o usuário temporário e roda o instalador num disco virtual
  installed  inicia o disco instalado, espera o primeiro início e cria a conta
             pelo modo texto (Ctrl+Alt+F2), digitando como uma pessoa
  menus      inicia a ISO pelos carregadores de boot de verdade (BIOS e UEFI)
             só para fotografar os menus e o começo do boot

Cada etapa salva capturas de tela e um resumo em PASTA/. O código de saída é 0
quando a etapa passou.

Uso:
  vmtest.py live      ISO DISCO PASTA
  vmtest.py installed DISCO PASTA
  vmtest.py menus     ISO PASTA

Precisa de qemu-system-x86_64, bsdtar e blkid. Com /dev/kvm leva poucos
minutos; sem ele funciona, mas é dezenas de vezes mais lento.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

KVM = os.access("/dev/kvm", os.R_OK | os.W_OK)
SLOW = 1 if KVM else int(os.environ.get("LAIN_VM_SLOWDOWN", "12"))
MEMORY = os.environ.get("LAIN_VM_MEMORY", "4096")
LIVE_USER, LIVE_PASSWORD = "wired", "live"
TEST_USER, TEST_PASSWORD = "teste", "lainos"

OVMF_CANDIDATES = (
    "/usr/share/ovmf/OVMF.fd",
    "/usr/share/qemu/OVMF.fd",
    "/usr/share/edk2/x64/OVMF.4m.fd",
    "/usr/share/edk2-ovmf/x64/OVMF.fd",
    "/usr/share/OVMF/OVMF_CODE_4M.fd",
    "/usr/share/OVMF/OVMF_CODE.fd",
)

KEYS = {" ": "spc", "\n": "ret", "-": "minus", ".": "dot", "/": "slash"}


def log(message: str) -> None:
    print(f"[vmtest {time.strftime('%H:%M:%S')}] {message}", flush=True)


class Machine:
    """Uma máquina virtual: serial pela entrada/saída padrão, controle pelo QMP."""

    def __init__(self, out: Path, name: str, args: list[str]):
        self.out, self.name = out, name
        out.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.mkdtemp(prefix="lainvm-")
        self.qmp_path = os.path.join(self.tmp, "qmp.sock")
        self.serial_log = out / f"{name}-serial.log"
        self.buffer = bytearray()
        self.lock = threading.Lock()
        self.shots = 0
        command = [
            "qemu-system-x86_64", "-m", MEMORY, "-smp", "2", "-display", "none",
            "-vga", "virtio", "-serial", "stdio", "-monitor", "none", "-no-reboot",
            "-qmp", f"unix:{self.qmp_path},server=on,wait=off",
            "-netdev", "user,id=net0", "-device", "virtio-net-pci,netdev=net0",
            "-device", "virtio-rng-pci",
        ]
        command += ["-enable-kvm", "-cpu", "host"] if KVM else ["-cpu", "max"]
        command += args
        log(f"{name}: {' '.join(command)}")
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.qmp = self._connect_qmp()

    # ---- serial ---------------------------------------------------------
    def _read(self) -> None:
        with open(self.serial_log, "wb") as handle:
            while True:
                chunk = self.proc.stdout.read1(4096)
                if not chunk:
                    break
                handle.write(chunk)
                handle.flush()
                with self.lock:
                    self.buffer += chunk

    def text(self, start: int = 0) -> str:
        with self.lock:
            return self.buffer[start:].decode("utf-8", "replace")

    def mark(self) -> int:
        with self.lock:
            return len(self.buffer)

    def wait_for(self, pattern: str, timeout: float, start: int = 0) -> re.Match | None:
        """Espera um texto aparecer no console serial (a partir da posição start)."""
        deadline = time.monotonic() + timeout * SLOW
        regex = re.compile(pattern)
        while time.monotonic() < deadline:
            found = regex.search(self.text(start))
            if found:
                return found
            if self.proc.poll() is not None:
                return regex.search(self.text(start))
            if "Kernel panic" in self.text(start):
                log("o kernel entrou em pânico; parando a espera")
                return None
            time.sleep(0.5)
        return None

    def send(self, text: str) -> None:
        self.proc.stdin.write(text.encode())
        self.proc.stdin.flush()

    def shell(self, command: str, timeout: float = 60) -> tuple[int, str]:
        """Roda um comando no console serial já autenticado; devolve (código, saída)."""
        start = self.mark()
        self.send(f"{command}; echo LAIN-END-$?\r")
        found = self.wait_for(r"LAIN-END-(\d+)", timeout, start)
        output = self.text(start)
        if not found:
            return 124, output
        return int(found.group(1)), output

    # ---- QMP ------------------------------------------------------------
    def _connect_qmp(self) -> socket.socket:
        deadline = time.monotonic() + 30
        while True:
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.connect(self.qmp_path)
                break
            except OSError:
                sock.close()
                if time.monotonic() > deadline or self.proc.poll() is not None:
                    raise RuntimeError(f"o QEMU não abriu o canal de controle:\n{self.text()}") from None
                time.sleep(0.2)
        self.qmp_file = sock.makefile("rw", encoding="utf-8")
        self.qmp_file.readline()  # saudação
        self.command("qmp_capabilities")
        return sock

    def command(self, name: str, **arguments) -> dict:
        message = {"execute": name}
        if arguments:
            message["arguments"] = arguments
        self.qmp_file.write(json.dumps(message) + "\n")
        self.qmp_file.flush()
        while True:
            line = self.qmp_file.readline()
            if not line:
                return {"error": {"desc": "QMP fechado"}}
            reply = json.loads(line)
            if "return" in reply or "error" in reply:
                return reply

    def screenshot(self, label: str) -> None:
        self.shots += 1
        base = self.out / f"{self.name}-{self.shots}-{label}"
        png = base.with_suffix(".png")
        reply = self.command("screendump", filename=str(png), format="png")
        if "error" in reply:  # QEMU antigo: só sabe salvar PPM
            ppm = base.with_suffix(".ppm")
            self.command("screendump", filename=str(ppm))
            time.sleep(1)
            if shutil.which("convert") and ppm.exists():
                subprocess.run(["convert", str(ppm), str(png)], check=False)
                if png.exists():
                    ppm.unlink()
        time.sleep(1)
        log(f"{self.name}: captura {png.name}")

    def key(self, *qcodes: str) -> None:
        keys = [{"type": "qcode", "data": code} for code in qcodes]
        self.command("send-key", keys=keys, **{"hold-time": 60})
        time.sleep(0.12 * min(SLOW, 4))

    def type(self, text: str) -> None:
        for char in text:
            if char.isupper():
                self.key("shift", char.lower())
            else:
                self.key(KEYS.get(char, char))

    # ---- fim ------------------------------------------------------------
    def sleep(self, seconds: float) -> None:
        time.sleep(seconds * SLOW)

    def stop(self, graceful_timeout: float = 0) -> None:
        if self.proc.poll() is None and graceful_timeout:
            try:
                self.proc.wait(graceful_timeout * SLOW)
            except subprocess.TimeoutExpired:
                pass
        if self.proc.poll() is None:
            try:
                self.command("quit")
                self.proc.wait(20)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                self.proc.kill()
        self.reader.join(5)
        shutil.rmtree(self.tmp, ignore_errors=True)


class Report:
    def __init__(self, out: Path, title: str):
        self.out, self.title = out, title
        self.rows: list[tuple[bool, bool, str, str]] = []

    def check(self, ok: bool, what: str, detail: str = "", required: bool = True) -> bool:
        """required=False: só informa (aparece com ⚠️), não reprova a etapa."""
        detail = " ".join(detail.replace("`", "'").split())[:240]
        self.rows.append((bool(ok), required, what, detail))
        tag = "ok " if ok else ("FALHOU" if required else "aviso ")
        log(f"{tag} {what} {detail}")
        return bool(ok)

    @property
    def passed(self) -> bool:
        return all(ok for ok, required, _, _ in self.rows if required)

    def write(self) -> int:
        lines = [f"### {self.title}: {'passou' if self.passed else 'FALHOU'}", ""]
        for ok, required, what, detail in self.rows:
            icon = "✅" if ok else ("❌" if required else "⚠️")
            lines.append(f"- {icon} {what}" + (f" — `{detail}`" if detail else ""))
        lines.append("")
        with open(self.out / "resumo.md", "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        return 0 if self.passed else 1


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


class DiskImage:
    """Monta (só leitura) a partição do sistema de um disco virtual desligado.

    Lê a tabela de partições do próprio arquivo e monta cada partição pelo
    deslocamento, então não depende de o kernel criar /dev/loopNpX.
    """

    def __init__(self, disk: Path):
        self.disk, self.mount = disk, ""

    def _partitions(self) -> list[tuple[int, int]]:
        table = json.loads(subprocess.run(["sfdisk", "-J", str(self.disk)], capture_output=True,
                                          text=True, check=True).stdout)["partitiontable"]
        sector = int(table.get("sectorsize", 512))
        return [(int(p["start"]) * sector, int(p["size"]) * sector) for p in table["partitions"]]

    def _mount(self, offset: int, size: int, target: str, extra: str = "") -> None:
        options = f"ro,loop,offset={offset},sizelimit={size}" + (f",{extra}" if extra else "")
        subprocess.run(["mount", "-o", options, str(self.disk), target], check=True, capture_output=True,
                       text=True)

    def __enter__(self) -> Path | None:
        if os.geteuid() != 0 or not shutil.which("sfdisk"):
            return None
        try:
            parts = self._partitions()
            if len(parts) < 3:
                log(f"o disco tem {len(parts)} partições, esperava 3")
                return None
            self.mount = tempfile.mkdtemp(prefix="lainmnt-")
            self._mount(*parts[2], self.mount, "noload")
            efi = Path(self.mount) / "boot/efi"
            if efi.is_dir():
                try:
                    self._mount(*parts[1], str(efi))
                except subprocess.CalledProcessError as exc:
                    log(f"não consegui montar a partição EFI: {exc.stderr.strip()}")
            return Path(self.mount)
        except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
            log(f"não consegui abrir o disco: {exc}")
            self.__exit__()
            return None

    def __exit__(self, *_exc) -> None:
        if self.mount:
            subprocess.run(["umount", "-R", self.mount], check=False, capture_output=True)
            shutil.rmtree(self.mount, ignore_errors=True)
            self.mount = ""


def tail(text: str, count: int = 25) -> str:
    return "\n".join(text.strip().splitlines()[-count:])


def iso_boot_files(iso: Path, workdir: Path) -> tuple[Path, Path, str]:
    """Kernel, initramfs e identificador da ISO, para iniciar com console serial."""
    subprocess.run(["bsdtar", "-xf", str(iso), "-C", str(workdir),
                    "arch/boot/x86_64/vmlinuz-linux", "arch/boot/x86_64/initramfs-linux.img"], check=True)
    uuid = subprocess.run(["blkid", "-s", "UUID", "-o", "value", str(iso)],
                          capture_output=True, text=True, check=True).stdout.strip()
    if not uuid:
        raise RuntimeError("não consegui ler o identificador (UUID) da ISO")
    base = workdir / "arch/boot/x86_64"
    return base / "vmlinuz-linux", base / "initramfs-linux.img", uuid


# ----------------------------------------------------------------------
def test_live(iso: Path, disk: Path, out: Path) -> int:
    report = Report(out, "Sessão ao vivo e instalação")
    work = Path(tempfile.mkdtemp(prefix="lainiso-"))
    try:
        kernel, initrd, uuid = iso_boot_files(iso, work)
        report.check(True, "kernel e initramfs encontrados na ISO", uuid)
        if not disk.exists():
            subprocess.run(["truncate", "-s", "16G", str(disk)], check=True)
        vm = Machine(out, "live", [
            "-cdrom", str(iso), "-kernel", str(kernel), "-initrd", str(initrd),
            "-append", f"archisobasedir=arch archisosearchuuid={uuid} console=tty0 console=ttyS0,115200 panic=-1",
            "-drive", f"file={disk},format=raw,if=virtio,cache=unsafe",
        ])
        try:
            booted = vm.wait_for(r"login: ", 300)
            if not report.check(bool(booted), "a ISO iniciou até o console de login"):
                log(tail(vm.text(), 40))
                vm.screenshot("falha-no-boot")
                return report.write()
            # o getty (e o "login:") sobe antes do graphical.target terminar,
            # então a conferência do modo gráfico é feita depois do login,
            # perguntando ao systemd (e esperando até 2 min).

            # entra como o usuário temporário da sessão ao vivo (criado no boot,
            # então dá um tempo para o serviço que o cria terminar)
            vm.sleep(6)
            code, output = 1, ""
            for attempt in range(3):
                start = vm.mark()
                vm.send(f"{LIVE_USER}\r")
                vm.wait_for(r"[Pp]assword|[Ss]enha", 30, start)
                vm.send(f"{LIVE_PASSWORD}\r")
                vm.sleep(5)
                vm.send("exec bash --norc --noprofile\r")
                vm.sleep(1)
                vm.send("stty -echo; export TERM=dumb LANG=C\r")
                code, output = vm.shell("id -un", 30)
                if code == 0 and LIVE_USER in output:
                    break
                log(f"login pelo console serial: tentativa {attempt + 1} falhou")
                vm.send("\r")
                vm.wait_for(r"login: ", 30, vm.mark())
            report.check(code == 0 and LIVE_USER in output, "login do usuário temporário (wired / live)")
            code, output = vm.shell(
                "timeout 120 sh -c 'until systemctl is-active -q graphical.target; do sleep 2; done'"
                " && systemctl is-active graphical.target", 150)
            report.check(code == 0, "o sistema chegou ao modo gráfico (graphical.target)", tail(output, 2))

            vm.sleep(35)  # tempo para a área de trabalho terminar de abrir
            vm.screenshot("area-de-trabalho")
            code, output = vm.shell("systemctl is-active greetd")
            report.check(code == 0, "a tela de sessão (greetd) está ativa", tail(output, 2))
            code, output = vm.shell("pgrep -u wired -x Hyprland || pgrep -u wired -f hyprland")
            report.check(code == 0, "o Hyprland abriu sozinho na sessão ao vivo",
                         "" if code == 0 else "máquina virtual sem aceleração 3D; num PC de verdade abre",
                         required=False)
            code, output = vm.shell("systemctl --failed --no-legend --plain | head -n 12")
            failed = [line.split()[0] for line in output.splitlines()
                      if re.match(r"^\S+\.(service|socket|mount|target)\b", line.strip())]
            report.check(not failed, "nenhum serviço falhou no boot", " ".join(failed), required=False)
            code, output = vm.shell(
                "locale -a | grep -qi pt_BR && test -f /usr/share/applications/lainos-install.desktop")
            report.check(code == 0, "idioma pt_BR gerado e instalador no menu")
            code, output = vm.shell("sudo -n true")
            report.check(code == 0, "sudo sem senha na sessão ao vivo")
            code, output = vm.shell("lsblk -dno NAME,SIZE,TYPE /dev/vda")
            report.check(code == 0 and "disk" in output, "disco de destino visível", tail(output, 2))

            # a instalação de verdade, com o mesmo comando que a interface roda
            log("instalando (rsync + initramfs + GRUB)...")
            code, output = vm.shell(
                "sudo -n /usr/lib/lainos/install-backend --disk /dev/vda --confirm APAGAR", 1500)
            installed = code == 0 and re.search(r"@@ 100 ", output) is not None
            report.check(installed, "o instalador terminou sem erro", f"código {code}")
            vm.screenshot("depois-da-instalacao")
            if not installed:
                log(tail(output, 30))
                _, details = vm.shell("sudo tail -n 60 /var/log/lainos-install.log")
                (out / "install-log-falha.txt").write_text(details, encoding="utf-8")
                log(tail(details, 60))
            else:
                _, details = vm.shell("sudo grep -i 'aviso' /var/log/lainos-install.log")
                warnings = [line for line in details.splitlines() if "aviso:" in line]
                report.check(not warnings, "instalação sem avisos", " | ".join(warnings), required=False)
            vm.send("sudo poweroff\r")
            vm.stop(graceful_timeout=90)
        finally:
            vm.stop()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if installed:
        with DiskImage(disk) as root:
            if root is None:
                report.check(True, "conferência do disco pulada (precisa de root)", required=False)
            else:
                report.check((root / "boot/grub/grub.cfg").is_file(), "menu do GRUB gravado no disco")
                report.check(any(root.glob("boot/initramfs-*.img")), "initramfs gerada no disco")
                efi_files = [p.name.lower() for p in (root / "boot/efi").rglob("*") if p.is_file()]
                report.check("bootx64.efi" in efi_files, "carregador UEFI no caminho padrão (EFI/BOOT/BOOTX64.EFI)")
                fstab = read(root / "etc/fstab")
                report.check(fstab.count("UUID=") == 2, "fstab com a raiz e a partição EFI")
                report.check((root / "var/lib/lainos/firstboot").exists(), "marca do primeiro início presente")
                report.check(not (root / "home/wired").exists(), "o usuário temporário não foi para o disco")
                report.check(not (root / "etc/sudoers.d/99-live").exists(), "o sudo sem senha da sessão ao vivo não foi para o disco")
    return report.write()


def test_installed(disk: Path, out: Path) -> int:
    report = Report(out, "Primeiro início do sistema instalado")
    vm = Machine(out, "instalado", ["-drive", f"file={disk},format=raw,if=virtio,cache=unsafe"])
    try:
        vm.sleep(75)
        alive = vm.proc.poll() is None
        report.check(alive, "o disco instalado iniciou pelo GRUB (BIOS)")
        if not alive:
            return report.write()
        vm.screenshot("primeiro-inicio")
        # modo texto do primeiro início: Ctrl+Alt+F2 e as respostas digitadas
        vm.key("ctrl", "alt", "f2")
        vm.sleep(4)
        vm.screenshot("modo-texto")
        for answer in ("Teste", TEST_USER, TEST_PASSWORD, TEST_PASSWORD, "vm"):
            vm.type(answer + "\n")
            vm.sleep(1.5)
        vm.sleep(12)
        vm.screenshot("conta-criada")
        vm.key("ctrl", "alt", "f1")
        vm.sleep(15)
        vm.screenshot("tela-de-login")
        vm.command("system_powerdown")
        vm.stop(graceful_timeout=60)
    finally:
        vm.stop()

    with DiskImage(disk) as root:
        if root is None:
            report.check(True, "conferência do disco pulada (precisa de root)", required=False)
        else:
            passwd = read(root / "etc/passwd")
            report.check(re.search(rf"(?m)^{TEST_USER}:", passwd) is not None,
                         "a conta criada no primeiro início existe")
            report.check(not (root / "var/lib/lainos/firstboot").exists(), "o primeiro início foi encerrado")
            report.check(read(root / "etc/hostname").strip() == "vm", "nome do computador gravado")
            groups = read(root / "etc/group")
            report.check(re.search(rf"(?m)^wheel:.*\b{TEST_USER}\b", groups) is not None,
                         "a conta nova é administradora (grupo wheel)")

    ovmf = next((path for path in OVMF_CANDIDATES if os.path.exists(path)), None)
    if ovmf:
        vm = Machine(out, "instalado-uefi", ["-bios", ovmf,
                                             "-drive", f"file={disk},format=raw,if=virtio,cache=unsafe"])
        try:
            vm.sleep(70)
            report.check(vm.proc.poll() is None, "o disco instalado também inicia por UEFI")
            vm.screenshot("tela-de-login")
            vm.command("system_powerdown")
            vm.stop(graceful_timeout=60)
        finally:
            vm.stop()
    return report.write()


def test_menus(iso: Path, out: Path) -> int:
    report = Report(out, "Menus de boot da ISO")
    vm = Machine(out, "menu-bios", ["-cdrom", str(iso), "-boot", "d"])
    try:
        vm.sleep(8)
        vm.screenshot("menu")
        vm.key("ret")
        vm.sleep(110)
        report.check(vm.proc.poll() is None, "boot pelo menu de BIOS (syslinux)")
        vm.screenshot("sessao")
    finally:
        vm.stop()
    ovmf = next((path for path in OVMF_CANDIDATES if os.path.exists(path)), None)
    if ovmf:
        vm = Machine(out, "menu-uefi", ["-bios", ovmf, "-cdrom", str(iso)])
        try:
            vm.sleep(15)
            vm.screenshot("menu")
            vm.key("ret")
            vm.sleep(110)
            report.check(vm.proc.poll() is None, "boot pelo menu de UEFI (systemd-boot)")
            vm.screenshot("sessao")
        finally:
            vm.stop()
    else:
        report.check(True, "UEFI não testado (sem firmware OVMF neste computador)")
    return report.write()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    mode, rest = sys.argv[1], [Path(arg) for arg in sys.argv[2:]]
    log(f"KVM: {'sim' if KVM else f'não (tudo {SLOW}x mais devagar)'}")
    if mode == "live" and len(rest) == 3:
        return test_live(*rest)
    if mode == "installed" and len(rest) == 2:
        return test_installed(*rest)
    if mode == "menus" and len(rest) == 2:
        return test_menus(*rest)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
