#!/usr/bin/env bash
# ‡ LainOS — abre o instalador e o assistente de primeiro início numa tela
# virtual e percorre os fluxos de verdade (com disco, motor e greetd de mentira).
# As capturas de tela ficam em tests/out/gui/.
#
# Precisa de: xvfb-run, Python com GTK 4 e libadwaita (python3-gi, gir1.2-gtk-4.0,
# gir1.2-adw-1 no Ubuntu) e, para as capturas, o ImageMagick.
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
OUT="$HERE/out/gui"

PY=${LAIN_PYTHON:-}
if [[ -z $PY ]]; then
    for candidate in python3 python3.13 python3.12 python3.11; do
        if command -v "$candidate" >/dev/null 2>&1 &&
            "$candidate" -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")' 2>/dev/null; then
            PY=$candidate
            break
        fi
    done
fi
[[ -n $PY ]] || { echo "PULADO: nenhum Python com GTK 4 e libadwaita"; exit 77; }
command -v xvfb-run >/dev/null 2>&1 || { echo "PULADO: falta o xvfb-run"; exit 77; }

rm -rf "$OUT"
mkdir -p "$OUT"
export GDK_BACKEND=x11 GSK_RENDERER=cairo NO_AT_BRIDGE=1 LIBGL_ALWAYS_SOFTWARE=1
status=0
run() {
    if ! xvfb-run -a -s "-screen 0 1100x760x24" "$PY" "$@" 2>"$OUT/stderr.log"; then
        status=1
        grep -v 'Gtk-WARNING\|Adwaita-WARNING\|^$' "$OUT/stderr.log" | tail -n 20 >&2 || true
    fi
}
run "$HERE/gui/installer_flow.py" "$OUT" ok
run "$HERE/gui/installer_flow.py" "$OUT" one
run "$HERE/gui/installer_flow.py" "$OUT" fail
run "$HERE/gui/installer_flow.py" "$OUT" none
run "$HERE/gui/firstboot_flow.py" "$OUT"
rm -rf "$OUT/firstboot-root" "$OUT/zoneinfo" "$OUT/greetd.sock" "$OUT/stderr.log"
exit "$status"
