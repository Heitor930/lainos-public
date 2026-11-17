# ‡ LainOS — monta a ISO no Windows, usando o Docker Desktop.
#
#   .\build.ps1          monta a ISO em .\out
#   .\build.ps1 -Fast    compressão leve (build bem mais rápido, ISO maior)
#
# Precisa do Docker Desktop aberto e de uns 20 GB livres. Leva de 20 a 60 minutos.
# Se o PowerShell recusar o script, rode antes (só nesta janela):
#   Set-ExecutionPolicy -Scope Process Bypass
param([switch]$Fast)

$ErrorActionPreference = "Continue"   # os erros são conferidos pelo código de saída
$src = $PSScriptRoot
$out = Join-Path $src "out"
New-Item -ItemType Directory -Force -Path $out | Out-Null

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "O Docker nao respondeu. Abra o Docker Desktop, espere ele iniciar e rode de novo." -ForegroundColor Red
    exit 1
}

$buildArgs = @("--in-container", "-o", "/out", "-w", "/work")
if ($Fast) { $buildArgs += "--fast" }

docker run --rm --privileged `
    -v "${src}:/src:ro" `
    -v "${out}:/out" `
    -v "lainos-work:/work" `
    -v "lainos-pacman-cache:/var/cache/pacman/pkg" `
    archlinux:latest bash /src/build.sh @buildArgs

if ($LASTEXITCODE -ne 0) {
    Write-Host "O build falhou. A mensagem de erro esta logo acima." -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "Pronto. A ISO esta em $out" -ForegroundColor Green
