#!/usr/bin/env bash
# ‡ LainOS — ajustes feitos UMA vez, na hora de montar a ISO (dentro da imagem).
#
# Aqui só entra o que vale tanto para a sessão ao vivo quanto para o sistema
# instalado, porque a mesma imagem serve aos dois. O que é só da sessão ao vivo
# (usuário temporário, entrada automática) é feito no início dela por
# /usr/lib/lainos/live-setup, e não fica gravado na imagem.
set -e -u

# Idiomas (o /etc/locale.gen da distro já lista pt_BR e en_US)
locale-gen

# Tela de login: a imagem fica num caminho que o lain-style pode trocar depois
install -d -m 0755 /var/lib/lainos
if [ -f /usr/share/lainos/login.jpg ] && [ ! -f /var/lib/lainos/login.jpg ]; then
    install -Dm644 /usr/share/lainos/login.jpg /var/lib/lainos/login.jpg
fi

# Animação de inicialização com o emblema da distro
if command -v plymouth-set-default-theme >/dev/null 2>&1 && [ -d /usr/share/plymouth/themes/lainos ]; then
    plymouth-set-default-theme lainos || true
fi

# Cache de fontes e de ícones (os ícones da distro não vêm de um pacote)
fc-cache -f >/dev/null 2>&1 || true
gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true

# Banco de páginas de manual (para o `man lainos` aparecer na busca)
mandb -q >/dev/null 2>&1 || true
