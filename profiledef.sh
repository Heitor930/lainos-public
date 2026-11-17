#!/usr/bin/env bash
# ‡ LainOS — perfil do archiso: diz ao mkarchiso como montar a ISO.
# Os pacotes ficam em packages/*.txt; o build.sh confere os nomes contra os
# repositórios e gera o packages.x86_64 que o mkarchiso lê.
# shellcheck disable=SC2034,SC2154

iso_name="lainos"
iso_label="LAIN_$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y%m)"
iso_publisher="LainOS"
iso_application="LainOS ao vivo e instalador"
iso_version="$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y.%m.%d)"
install_dir="arch"
buildmodes=('iso')
bootmodes=('bios.syslinux'
           'uefi.systemd-boot')
arch="x86_64"
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
airootfs_image_tool_options=('-comp' 'zstd' '-Xcompression-level' "${LAIN_ZSTD_LEVEL:-19}" '-b' '1M')
bootstrap_tarball_compression=('zstd' '-c' '-T0' '--long' '-19')

# Permissões dentro da imagem. O mkarchiso copia o airootfs sem preservar dono
# nem modo, então tudo o que precisa ser executável (ou restrito) entra aqui.
# A lista dos executáveis é montada a partir das pastas, para nunca ficar
# desatualizada quando um script novo aparece.
file_permissions=(
  ["/root"]="0:0:750"
  ["/etc/sudoers.d"]="0:0:750"
  ["/etc/sudoers.d/10-lainos"]="0:0:440"
  ["/etc/polkit-1/rules.d/49-lainos.rules"]="0:0:644"
  ["/root/customize_airootfs.sh"]="0:0:755"
)
_lain_profile="${profile:-$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")}"
for _lain_file in "${_lain_profile}"/airootfs/usr/local/bin/* \
                "${_lain_profile}"/airootfs/usr/lib/lainos/install-backend \
                "${_lain_profile}"/airootfs/usr/lib/lainos/firstboot-apply \
                "${_lain_profile}"/airootfs/usr/lib/lainos/firstboot-console \
                "${_lain_profile}"/airootfs/usr/lib/lainos/live-setup; do
  [[ -f "${_lain_file}" ]] || continue
  file_permissions["${_lain_file#"${_lain_profile}"/airootfs}"]="0:0:755"
done
unset _lain_profile _lain_file
