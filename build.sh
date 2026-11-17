#!/usr/bin/env bash
# ‡ LainOS — monta a ISO.
#
#   ./build.sh                 monta a ISO em ./out
#   ./build.sh --fast          compressão leve (build bem mais rápido, ISO maior): para testar
#   ./build.sh --list-packages só confere a lista de pacotes contra os repositórios
#   ./build.sh -o PASTA        escolhe a pasta de saída
#   ./build.sh -w PASTA        escolhe a pasta de trabalho (precisa de ~15 GB livres)
#
# Precisa de um Arch Linux com root. Em qualquer outro sistema com Docker
# (Ubuntu, WSL, macOS), o script se reexecuta sozinho dentro de um contêiner
# Arch. No Windows com Docker Desktop, use o build.ps1. No GitHub, quem chama
# é o workflow .github/workflows/build-iso.yml.
#
# O que ele faz:
#   1. copia o perfil para uma pasta de trabalho e normaliza permissões, fins
#      de linha e links simbólicos (para o build dar igual vindo de Linux,
#      Windows ou de um .zip);
#   2. confere cada pacote de packages/iso.txt contra os repositórios e gera a
#      lista final (um nome errado para o build aqui, com uma mensagem clara,
#      em vez de falhar no meio do mkarchiso);
#   3. chama o mkarchiso;
#   4. deixa a ISO e o SHA-256 na pasta de saída.
set -Eeuo pipefail

SRC=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
OUT="$SRC/out"
WORK="${LAIN_WORK_DIR:-/var/tmp/lainos-build}"
WORK_SET=0
FAST=0
LIST_ONLY=0
IN_CONTAINER=0
IMAGE="${LAIN_BUILD_IMAGE:-archlinux:latest}"

moss=$'\033[38;2;138;154;91m'; red=$'\033[38;2;207;117;102m'; dim=$'\033[2m'; reset=$'\033[0m'
[[ -t 1 ]] || { moss=""; red=""; dim=""; reset=""; }
step() { printf '%s‡%s %s\n' "$moss" "$reset" "$*"; }
info() { printf '  %s%s%s\n' "$dim" "$*" "$reset"; }
warn() { printf '  %saviso:%s %s\n' "$red" "$reset" "$*" >&2; }
die()  { printf '%serro:%s %s\n' "$red" "$reset" "$*" >&2; exit 1; }

while (($#)); do
    case $1 in
        -o | --out)        OUT=$(mkdir -p "$2" && cd "$2" && pwd); shift 2 ;;
        -w | --work)       WORK=$2; WORK_SET=1; shift 2 ;;
        --fast)            FAST=1; shift ;;
        --list-packages)   LIST_ONLY=1; shift ;;
        --in-container)    IN_CONTAINER=1; shift ;;
        -h | --help)       sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)                 die "opção desconhecida: $1 (veja ./build.sh --help)" ;;
    esac
done

# ----------------------------------------------------------------------
# Fora do Arch: reexecuta dentro de um contêiner
# ----------------------------------------------------------------------
if ! command -v pacman >/dev/null 2>&1; then
    command -v docker >/dev/null 2>&1 ||
        die "este script precisa do Arch Linux ou do Docker. Instale o Docker e rode de novo."
    docker info >/dev/null 2>&1 ||
        die "o Docker não respondeu. Ele está aberto? No Linux, rode com sudo ou entre no grupo docker."
    step "sem pacman por aqui: usando um contêiner $IMAGE"
    mkdir -p "$OUT"
    # A pasta de trabalho fica fora do contêiner (num volume ou na pasta pedida):
    # o mkarchiso monta sistemas de arquivos nela e precisa de um disco de verdade.
    work_mount="lainos-work:/work"
    if ((WORK_SET)); then
        mkdir -p "$WORK"
        work_mount="$(cd "$WORK" && pwd):/work"
    fi
    args=(--in-container -o /out -w /work)
    if ((FAST)); then args+=(--fast); fi
    if ((LIST_ONLY)); then args+=(--list-packages); fi
    export MSYS_NO_PATHCONV=1   # Git Bash no Windows: não converter /src em C:\...
    exec docker run --rm --privileged \
        -v "$SRC":/src:ro -v "$OUT":/out -v "$work_mount" \
        -v lainos-pacman-cache:/var/cache/pacman/pkg \
        -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" -e LAIN_ZSTD_LEVEL \
        "$IMAGE" bash /src/build.sh "${args[@]}"
fi

((EUID == 0)) || die "rode como root (sudo ./build.sh): o mkarchiso monta sistemas de arquivos."

# ----------------------------------------------------------------------
# Ferramentas de build
# ----------------------------------------------------------------------
step "preparando as ferramentas de build"
if ((IN_CONTAINER)); then
    # A imagem oficial vem sem o chaveiro pronto
    if [[ ! -s /etc/pacman.d/gnupg/trustdb.gpg ]]; then
        pacman-key --init >/dev/null 2>&1
        pacman-key --populate archlinux >/dev/null 2>&1
    fi
fi

# O pacman baixa os arquivos num processo isolado, e esse isolamento não
# funciona em alguns contêineres. Se a primeira tentativa falhar dentro de um
# contêiner, tenta de novo sem ele (a conferência de assinaturas continua igual).
pacman_retry() {
    if pacman "$@"; then return 0; fi
    ((IN_CONTAINER)) || return 1
    if grep -q '^DisableSandbox' /etc/pacman.conf; then return 1; fi
    warn "o pacman falhou; tentando de novo sem o isolamento de download"
    sed -i 's/^\[options\]/[options]\nDisableSandbox/' /etc/pacman.conf
    pacman "$@"
}

pacman_retry -Sy --noconfirm --needed archlinux-keyring >/dev/null ||
    die "não consegui falar com os repositórios do Arch (sem internet?)."
if ! pacman -Qq archiso >/dev/null 2>&1; then
    info "instalando o archiso"
    # -Syu: num sistema de lançamento contínuo, instalar sem atualizar quebra dependências
    pacman -Syu --noconfirm --needed archiso
fi
command -v mkarchiso >/dev/null 2>&1 || die "o mkarchiso não foi instalado."
info "archiso $(pacman -Q archiso | awk '{print $2}')"

# ----------------------------------------------------------------------
# Cópia de trabalho do perfil
# ----------------------------------------------------------------------
PROFILE="$WORK/profile"
step "copiando o perfil para $PROFILE"
rm -rf "$PROFILE"
mkdir -p "$PROFILE" "$OUT"
for item in airootfs efiboot syslinux profiledef.sh pacman.conf; do
    [[ -e $SRC/$item ]] || die "falta $item no projeto."
    cp -a "$SRC/$item" "$PROFILE/"
done

# Fins de linha: um checkout no Windows pode ter trocado LF por CRLF
while IFS= read -r -d '' file; do
    if grep -Iq . "$file" 2>/dev/null && grep -q $'\r$' "$file"; then
        sed -i 's/\r$//' "$file"
    fi
done < <(find "$PROFILE" -type f -size -2M -print0)

# Permissões: tudo 644/755 (os executáveis são marcados no profiledef.sh)
chown -R 0:0 "$PROFILE"
find "$PROFILE" -type d -exec chmod 755 {} +
find "$PROFILE" -type f -exec chmod 644 {} +
chmod 755 "$PROFILE"/airootfs/usr/local/bin/* "$PROFILE/airootfs/root/customize_airootfs.sh"

# Links simbólicos descritos em airootfs.links
links=0
while IFS=$'\t' read -r link target; do
    [[ -z $link || $link == \#* ]] && continue
    [[ -n $target ]] || die "linha inválida em airootfs.links: $link"
    mkdir -p "$PROFILE/airootfs/$(dirname "$link")"
    ln -sfn "$target" "$PROFILE/airootfs/$link"
    links=$((links + 1))
done < <(sed 's/\r$//' "$SRC/airootfs.links")
info "$links links simbólicos criados"

if grep -q '^DisableSandbox' /etc/pacman.conf 2>/dev/null; then
    sed -i 's/^\[options\]/[options]\nDisableSandbox/' "$PROFILE/pacman.conf"
fi

if ((FAST)); then
    export LAIN_ZSTD_LEVEL=6
    info "modo rápido: compressão zstd nível 6"
fi

# ----------------------------------------------------------------------
# Lista de pacotes conferida contra os repositórios
# ----------------------------------------------------------------------
step "conferindo a lista de pacotes"
pacman --config "$PROFILE/pacman.conf" -Sy --noconfirm >/dev/null
declare -A KNOWN=()
while IFS= read -r name; do KNOWN["$name"]=1; done < <(
    pacman --config "$PROFILE/pacman.conf" -Slq
    pacman --config "$PROFILE/pacman.conf" -Sgq
)
((${#KNOWN[@]} > 1000)) || die "não consegui ler os repositórios (sem internet?)."

exists() {
    [[ -n ${KNOWN[$1]:-} ]] && return 0
    # nomes "virtuais" (fornecidos por outro pacote) não aparecem na listagem
    pacman --config "$PROFILE/pacman.conf" -Sp "$1" >/dev/null 2>&1
}

final=()
skipped=()
missing=()
while IFS= read -r line; do
    line=${line%%#*}
    line=${line//[[:space:]]/}
    [[ -n $line ]] || continue
    optional=0
    if [[ $line == \?* ]]; then optional=1; line=${line#\?}; fi
    chosen=""
    IFS='|' read -r -a candidates <<<"$line"
    for candidate in "${candidates[@]}"; do
        if exists "$candidate"; then chosen=$candidate; break; fi
    done
    if [[ -n $chosen ]]; then
        final+=("$chosen")
        if [[ $chosen != "${candidates[0]}" ]]; then
            info "usando $chosen no lugar de ${candidates[0]}"
        fi
    elif ((optional)); then
        skipped+=("$line")
    else
        missing+=("$line")
    fi
done <"$SRC/packages/iso.txt"

if ((${#skipped[@]})); then
    warn "opcionais fora dos repositórios (pulados): ${skipped[*]}"
fi
if ((${#missing[@]})); then
    die "pacotes obrigatórios que não existem nos repositórios: ${missing[*]}
      Corrija o nome em packages/iso.txt (ou marque com ? se for opcional)."
fi
printf '%s\n' "${final[@]}" | sort -u >"$PROFILE/packages.x86_64"
info "$(wc -l <"$PROFILE/packages.x86_64") pacotes na ISO"
cp "$PROFILE/packages.x86_64" "$OUT/packages-resolved.txt"

if ((LIST_ONLY)); then
    step "lista conferida: $OUT/packages-resolved.txt"
    exit 0
fi

# ----------------------------------------------------------------------
# mkarchiso
# ----------------------------------------------------------------------
if ! grep -q 'customize_airootfs.sh' "$(command -v mkarchiso)"; then
    warn "esta versão do mkarchiso não roda mais o customize_airootfs.sh;"
    warn "o idioma é gerado no início da sessão ao vivo e pelo instalador."
fi
free_kb=$(df -Pk "$WORK" | awk 'NR == 2 {print $4}')
if ((free_kb < 14 * 1024 * 1024)); then
    warn "pouco espaço em $WORK ($((free_kb / 1024 / 1024)) GB livres; o ideal é 15 GB)."
fi

step "montando a ISO (leva de 15 a 40 minutos)"
rm -rf "$WORK/work"
mkarchiso -v -w "$WORK/work" -o "$OUT" "$PROFILE"

iso=$(find "$OUT" -maxdepth 1 -name 'lainos-*.iso' -newer "$PROFILE/packages.x86_64" | sort | tail -n1)
[[ -n $iso ]] || die "o mkarchiso terminou, mas a ISO não apareceu em $OUT."
(cd "$OUT" && sha256sum "$(basename "$iso")" >"$(basename "$iso").sha256")
rm -rf "$WORK/work"

if [[ -n ${HOST_UID:-} ]]; then
    chown -R "$HOST_UID:${HOST_GID:-$HOST_UID}" "$OUT" 2>/dev/null || true
fi

step "pronto"
info "ISO:     $iso ($(du -h "$iso" | cut -f1))"
info "SHA-256: $(cut -d' ' -f1 <"$iso.sha256")"
