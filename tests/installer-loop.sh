#!/usr/bin/env bash
# ‡ LainOS — testa o motor do instalador num disco de mentira (arquivo + loop).
#
# Confere a parte que apaga e prepara o disco: tabela de partições, formatação,
# cópia do sistema, fstab e as marcas do primeiro início. As etapas que rodam
# dentro do sistema instalado (initramfs e GRUB) precisam de um Arch de verdade
# e são testadas no GitHub, pelo tests/ci-install-test.sh.
#
# Precisa de root e de dispositivos de loop. Não toca em nenhum disco real:
# o motor só aceita um dispositivo de loop quando recebe --allow-loop.
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO=$(dirname "$HERE")
BACKEND="$REPO/airootfs/usr/lib/lainos/install-backend"

fail() { printf 'FALHOU: %s\n' "$*" >&2; exit 1; }
skip() { printf 'PULADO: %s\n' "$*"; exit 77; }

((EUID == 0)) || skip "precisa de root"
for tool in losetup sfdisk mkfs.fat mkfs.ext4 rsync lsblk blkid wipefs; do
    command -v "$tool" >/dev/null 2>&1 || skip "falta $tool"
done

TMP=$(mktemp -d)
LOOP=""
cleanup() {
    mountpoint -q "$TMP/check" 2>/dev/null && umount "$TMP/check"
    mountpoint -q "$TMP/target" 2>/dev/null && umount -R "$TMP/target"
    [[ -n $LOOP ]] && losetup -d "$LOOP" 2>/dev/null
    rm -rf "$TMP"
}
trap cleanup EXIT

truncate -s 2G "$TMP/disk.img"
LOOP=$(losetup --find --show --partscan "$TMP/disk.img" 2>/dev/null) || skip "sem dispositivos de loop aqui"
export LAIN_INSTALL_LOG="$TMP/install.log"

# Um "sistema" pequeno para copiar, com o que o motor procura
src="$TMP/source"
mkdir -p "$src"/{etc/mkinitcpio.conf.d,usr/bin,usr/lib/modules/6.1.0-test,var/lib,boot,home}
echo 'HOOKS=(base udev archiso)' >"$src/etc/mkinitcpio.conf.d/archiso.conf"
# shellcheck disable=SC2016  # o $ faz parte do hash de mentira
printf 'root:$6$abc$def:19000::::::\nbin:!*:19000::::::\n' >"$src/etc/shadow"
echo "kernel de mentira" >"$src/usr/lib/modules/6.1.0-test/vmlinuz"
echo "linux" >"$src/usr/lib/modules/6.1.0-test/pkgbase"
echo "olá" >"$src/usr/bin/arquivo"
ln -s arquivo "$src/usr/bin/link"

run_backend() { bash "$BACKEND" "$@" >"$TMP/out.txt" 2>&1; }

# ---- recusas: nada pode ser alterado nestes casos --------------------
run_backend --disk "$LOOP" --allow-loop --min-bytes 1 --source "$src" && fail "aceitou sem confirmação"
grep -q '^!! Confirmação ausente' "$TMP/out.txt" || fail "mensagem errada sem confirmação"
run_backend --disk "$LOOP" --confirm apagar --allow-loop --min-bytes 1 --source "$src" && fail "aceitou confirmação errada"
run_backend --disk /dev/nao-existe --confirm APAGAR && fail "aceitou um disco que não existe"
run_backend --disk "$LOOP" --confirm APAGAR --skip-chroot --min-bytes 1 --source "$src" &&
    fail "aceitou um loop sem --allow-loop"
grep -q 'não é um disco inteiro' "$TMP/out.txt" || fail "mensagem errada para um dispositivo que não é disco"
run_backend --disk "$LOOP" --confirm APAGAR --allow-loop --skip-chroot --source "$src" &&
    fail "aceitou um disco menor que 12 GB"
grep -q 'pequeno demais' "$TMP/out.txt" || fail "mensagem errada para disco pequeno"
[[ -z $(lsblk -lno NAME,TYPE "$LOOP" | awk '$2 == "part"') ]] || fail "uma recusa mexeu no disco"

# ---- instalação (sem as etapas de dentro do sistema) -----------------
# Um disco "usado": com outra tabela de partições e um sistema de arquivos antigo
printf 'label: dos\n,500M,L\n,,L\n' | sfdisk -q "$LOOP" >/dev/null 2>&1 || true
run_backend --disk "$LOOP" --confirm APAGAR --allow-loop --min-bytes $((1024 * 1024 * 1024)) \
    --source "$src" --target "$TMP/target" --skip-chroot ||
    { cat "$TMP/out.txt" "$TMP/install.log"; fail "a instalação de teste falhou"; }

grep -q '^@@ 100 ' "$TMP/out.txt" || fail "não chegou a 100%"
last=-1
while read -r _ pct _; do
    ((pct >= last)) || fail "o progresso andou para trás ($last -> $pct)"
    last=$pct
done < <(grep '^@@ ' "$TMP/out.txt")
mountpoint -q "$TMP/target" && fail "o disco ficou montado depois da instalação"

mapfile -t parts < <(lsblk -lnpo NAME,TYPE "$LOOP" | awk '$2 == "part" {print $1}')
((${#parts[@]} == 3)) || fail "esperava 3 partições, achei ${#parts[@]}"
table=$(sfdisk -d "$LOOP")
grep -q 'label: gpt' <<<"$table" || fail "a tabela não é GPT"
grep -qi '21686148-6449-6E6F-744E-656564454649' <<<"$table" || fail "falta a partição de boot da BIOS"
grep -qi 'C12A7328-F81F-11D2-BA4B-00A0C93EC93B' <<<"$table" || fail "falta a partição EFI"
[[ $(blkid -s TYPE -o value "${parts[1]}") == vfat ]] || fail "a partição EFI não é FAT"
[[ $(blkid -s TYPE -o value "${parts[2]}") == ext4 ]] || fail "a partição do sistema não é ext4"
[[ $(blkid -s LABEL -o value "${parts[2]}") == lainos ]] || fail "rótulo errado na partição do sistema"
efi_bytes=$(blockdev --getsize64 "${parts[1]}")
((efi_bytes == 512 * 1024 * 1024)) || fail "a partição EFI tem $efi_bytes bytes"

mkdir -p "$TMP/check"
mount -o ro "${parts[2]}" "$TMP/check"
c="$TMP/check"
[[ $(cat "$c/usr/bin/arquivo") == "olá" ]] || fail "arquivo não copiado"
[[ -L $c/usr/bin/link ]] || fail "link simbólico não copiado"
[[ $(cat "$c/boot/vmlinuz-linux") == "kernel de mentira" ]] || fail "o kernel não voltou para /boot"
[[ ! -e $c/etc/mkinitcpio.conf.d/archiso.conf ]] || fail "a configuração de initramfs da ISO ficou no disco"
grep -q '^HOOKS=(base udev autodetect' "$c/etc/mkinitcpio.conf.d/lainos.conf" || fail "HOOKS do sistema instalado"
grep -q "^UUID=$(blkid -s UUID -o value "${parts[2]}") */ *ext4" "$c/etc/fstab" || fail "fstab sem a raiz"
grep -q "^UUID=$(blkid -s UUID -o value "${parts[1]}") */boot/efi *vfat" "$c/etc/fstab" || fail "fstab sem a partição EFI"
grep -q '^root:!:' "$c/etc/shadow" || fail "a conta root não foi travada"
grep -q '^bin:!\*:' "$c/etc/shadow" || fail "outra conta foi alterada no shadow"
[[ -e $c/var/lib/lainos/firstboot ]] || fail "falta a marca do primeiro início"
[[ $(readlink "$c/etc/systemd/system/systemd-firstboot.service") == /dev/null ]] || fail "systemd-firstboot não foi desligado"
[[ -s $c/var/log/lainos-install.log ]] || fail "o registro da instalação não foi copiado"
[[ ! -e $c/home/wired ]] || fail "o usuário temporário foi parar no disco"
umount "$TMP/check"

echo "instalador: ok (recusas, particionamento, cópia e ajustes do sistema)"
