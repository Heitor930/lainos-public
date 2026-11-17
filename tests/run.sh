#!/usr/bin/env bash
# ‡ LainOS — roda todos os testes que não precisam montar a ISO.
#
#   tests/run.sh            roda tudo o que der neste computador
#   tests/run.sh --strict   falha se alguma etapa tiver de ser pulada (usado no GitHub)
#
# Etapas:
#   1. shellcheck e sintaxe de todos os scripts de shell
#   2. sintaxe de todo o código Python
#   3. testes de unidade (discos, validações, greetd, primeiro início, projeto)
#   4. build.sh de ponta a ponta com pacman e mkarchiso de mentira   (root)
#   5. motor do instalador num disco de mentira                       (root + loop)
#   6. instalador e primeiro início numa tela virtual                 (GTK + xvfb)
set -uo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO=$(dirname "$HERE")
cd "$REPO" || exit 1

STRICT=0
[[ ${1:-} == --strict ]] && STRICT=1

if [[ -t 1 ]]; then
    moss=$'\033[38;2;138;154;91m'; red=$'\033[38;2;207;117;102m'; dim=$'\033[2m'; reset=$'\033[0m'
else
    moss=""; red=""; dim=""; reset=""
fi
failed=()
skipped=()
stage() { printf '\n%s‡%s %s\n' "$moss" "$reset" "$1"; }
ok()    { printf '  %sok%s %s\n' "$moss" "$reset" "$1"; }
bad()   { printf '  %sFALHOU%s %s\n' "$red" "$reset" "$1"; failed+=("$1"); }
skip()  { printf '  %spulado: %s%s\n' "$dim" "$1" "$reset"; skipped+=("$1"); }

PY=${LAIN_PYTHON:-python3}
as_root() {
    if ((EUID == 0)); then "$@"; elif sudo -n true 2>/dev/null; then sudo -n env "PATH=$PATH" "$@"; else return 77; fi
}

# ---- 1. shell ---------------------------------------------------------
stage "scripts de shell"
shell_files=()
while IFS= read -r -d '' file; do
    if head -n1 "$file" | grep -Eq '^#!.*\b(ba)?sh\b'; then shell_files+=("$file"); fi
done < <(find . \( -path ./.git -o -path ./out -o -path ./tests/out \) -prune -o -type f -print0)
shell_files+=(profiledef.sh)
for file in "${shell_files[@]}" airootfs/usr/share/lainos/bundles/*.conf airootfs/etc/skel/.zshrc; do
    case $file in
        *.zshrc) command -v zsh >/dev/null 2>&1 && { zsh -n "$file" || bad "sintaxe: $file"; } ;;
        *)       bash -n "$file" || bad "sintaxe: $file" ;;
    esac
done
if command -v shellcheck >/dev/null 2>&1; then
    if shellcheck -x -e SC1091 "${shell_files[@]}"; then ok "shellcheck em ${#shell_files[@]} scripts"; else bad "shellcheck"; fi
else
    skip "shellcheck não instalado"
fi

# ---- 2. python --------------------------------------------------------
stage "código Python"
py_files=()
while IFS= read -r -d '' file; do py_files+=("$file"); done < <(
    find airootfs branding tests -name '*.py' -not -path '*/__pycache__/*' -print0)
py_files+=(airootfs/usr/lib/lainos/firstboot-apply)
if "$PY" - "${py_files[@]}" <<'PYCHECK'
import ast, sys
bad = 0
for path in sys.argv[1:]:
    try:
        with open(path, encoding="utf-8") as handle:
            ast.parse(handle.read(), path)
    except SyntaxError as exc:
        print(f"  {path}: {exc}")
        bad = 1
sys.exit(bad)
PYCHECK
then ok "sintaxe de ${#py_files[@]} arquivos"; else bad "sintaxe Python"; fi

# ---- 3. unidade -------------------------------------------------------
stage "testes de unidade"
if (cd tests/unit && PYTHONDONTWRITEBYTECODE=1 "$PY" -m unittest 2>&1 | tail -n 25; exit "${PIPESTATUS[0]}"); then
    ok "testes de unidade"
else
    bad "testes de unidade"
fi

# ---- 4 a 6: etapas que dependem do ambiente ---------------------------
optional() {  # optional "nome" comando...
    local name=$1 code
    shift
    stage "$name"
    "$@"
    code=$?
    case $code in
        0)  ok "$name" ;;
        77) skip "$name (precisa de root ou de ferramentas que não estão aqui)" ;;
        *)  bad "$name" ;;
    esac
}
optional "build.sh com repositório de mentira" as_root bash tests/build-dry-run.sh
optional "motor do instalador em disco de mentira" as_root bash tests/installer-loop.sh
optional "instalador e primeiro início em tela virtual" bash tests/gui-smoke.sh

# ---- resumo -----------------------------------------------------------
printf '\n'
if ((${#failed[@]})); then
    printf '%s%d etapa(s) falharam:%s %s\n' "$red" "${#failed[@]}" "$reset" "${failed[*]}"
    exit 1
fi
if ((${#skipped[@]})); then
    printf '%sTudo o que rodou passou; %d etapa(s) puladas.%s\n' "$dim" "${#skipped[@]}" "$reset"
    ((STRICT)) && exit 1
    exit 0
fi
printf '%sTodos os testes passaram.%s\n' "$moss" "$reset"
