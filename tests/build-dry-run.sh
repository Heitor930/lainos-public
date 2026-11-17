#!/usr/bin/env bash
# ‡ LainOS — testa o build.sh de ponta a ponta com um pacman e um mkarchiso
# de mentira (sem internet e em segundos). Precisa de root, como o build de verdade.
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO=$(dirname "$HERE")
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { printf 'FALHOU: %s\n' "$*" >&2; exit 1; }
((EUID == 0)) || fail "rode como root (sudo tests/build-dry-run.sh)"

# Uma cópia "suja" do projeto: fins de linha do Windows e scripts sem permissão,
# como chegaria de um checkout no Windows ou de um .zip.
cp -r "$REPO" "$TMP/src"
rm -rf "$TMP/src/.git" "$TMP/src/out"
sed -i 's/$/\r/' "$TMP/src/airootfs/usr/local/bin/lain-greeter" "$TMP/src/airootfs/etc/greetd/config.toml" \
    "$TMP/src/airootfs.links" "$TMP/src/packages/iso.txt"
chmod -R a-x "$TMP/src/airootfs/usr/local/bin"

# Repositório de mentira: tudo o que a lista pede, menos alguns nomes de propósito.
export FAKE_REPO="$TMP/repo.txt" FAKE_PROVIDES="$TMP/provides.txt" FAKE_PACMAN_LOG="$TMP/pacman.log"
sed -e 's/#.*//' -e 's/[[:space:]]//g' -e 's/^?//' "$REPO/packages/iso.txt" | tr '|' '\n' | grep . |
    grep -vxE 'rofi|plymouth|tealdeer|7zip' >"$FAKE_REPO"
for n in $(seq 1 1200); do echo "pacote-de-enchimento-$n"; done >>"$FAKE_REPO"
echo tldr >"$FAKE_PROVIDES"      # existe só como nome "virtual"
export PATH="$HERE/fake:$PATH"

run_build() { bash "$TMP/src/build.sh" -o "$TMP/out" -w "$TMP/work" "$@" >"$TMP/build.log" 2>&1; }

# 1) só a lista de pacotes
run_build --list-packages || { cat "$TMP/build.log"; fail "build.sh --list-packages"; }
resolved="$TMP/out/packages-resolved.txt"
[[ -s $resolved ]] || fail "packages-resolved.txt não foi criado"
grep -qx rofi-wayland "$resolved" || fail "a alternativa (rofi|rofi-wayland) não foi usada"
grep -qx p7zip "$resolved"        || fail "a alternativa (7zip|p7zip) não foi usada"
grep -qx tldr "$resolved"         || fail "o nome virtual (tldr) não foi aceito"
grep -qx plymouth "$resolved"     && fail "um opcional ausente entrou na lista"
grep -qx hyprland "$resolved"     || fail "hyprland sumiu da lista"
grep -q 'plymouth' "$TMP/build.log" || fail "o opcional pulado não foi avisado"
[[ $(sort "$resolved" | uniq -d | wc -l) == 0 ]] || fail "pacote repetido na lista final"
compgen -G "$TMP/out/*.iso" >/dev/null && fail "--list-packages não devia montar a ISO"

# 2) build completo (com o mkarchiso de mentira conferindo o perfil preparado)
run_build --fast || { cat "$TMP/build.log"; fail "build.sh --fast"; }
iso=$(compgen -G "$TMP/out/lainos-*.iso" | head -n1)
[[ -n $iso && -s $iso.sha256 ]] || fail "a ISO ou o SHA-256 não apareceram"
grep -q 'mkarchiso falso: ok (6)' "$TMP/build.log" || { cat "$TMP/build.log"; fail "o modo --fast não chegou ao mkarchiso"; }
[[ ! -e $TMP/work/work ]] || fail "a pasta de trabalho não foi limpa"

# 3) um pacote obrigatório que não existe tem de parar o build com uma mensagem clara
grep -vx hyprland "$FAKE_REPO" >"$TMP/repo2.txt"
FAKE_REPO="$TMP/repo2.txt" run_build --list-packages && fail "o build devia parar sem o hyprland"
grep -q 'hyprland' "$TMP/build.log" || fail "a mensagem não diz qual pacote faltou"

echo "build.sh: ok (lista de pacotes, build completo e pacote ausente)"
