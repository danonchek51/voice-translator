# Собирает установщик Inno Setup поверх portable-сборки.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $Iscc) {
    Write-Host "Inno Setup 6 не найден." -ForegroundColor Red
    Write-Host "Скачайте его с https://jrsoftware.org/isdl.php или соберите только portable-архив:"
    Write-Host "  .\scripts\build_portable.ps1"
    exit 1
}

if (-not (Test-Path (Join-Path $Root "dist\VoiceFlow\VoiceFlow.exe"))) {
    Write-Host "Сначала собираю portable-версию..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "build_portable.ps1")
}

Write-Host "Собираю установщик..." -ForegroundColor Cyan
& $Iscc (Join-Path $PSScriptRoot "installer.iss")

$output = Join-Path $Root "installer_output"
Write-Host ""
Write-Host "Готово. Установщик в $output" -ForegroundColor Green
Write-Host "Билд не подписан: SmartScreen покажет предупреждение при первом запуске."
