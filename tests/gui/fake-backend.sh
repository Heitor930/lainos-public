#!/usr/bin/env bash
# Motor de instalação de mentira: fala o mesmo protocolo do install-backend
# (linhas "@@ <porcento> <mensagem>" e "!! <erro>"), sem tocar em disco nenhum.
printf '%s\n' "$*" >"${FAKE_BACKEND_ARGS:-/dev/null}"
echo "@@ 1 Preparando o disco"; sleep 0.2
echo "@@ 3 Apagando e particionando o disco"; sleep 0.2
for pct in 10 35 62 100; do
    echo "@@ $((8 + pct * 60 / 100)) Copiando o sistema para o disco (${pct}%)"; sleep 0.3
done
if [[ ${FAKE_FAIL:-0} == 1 ]]; then
    echo "!! A cópia do sistema falhou (rsync 12). O disco pode estar com defeito."
    exit 1
fi
echo "@@ 86 Instalando o carregador de boot"; sleep 0.2
echo "@@ 100 Instalação concluída"
