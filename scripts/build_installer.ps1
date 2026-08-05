# Собирает установщик Inno Setup поверх portable-сборки.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# Ищем любую установленную версию: жёсткая привязка к шестой оставляла
# сборку без установщика после обновления Inno Setup.
$Iscc = @("${env:ProgramFiles(x86)}", "$env:ProgramFiles") |
    Where-Object { $_ -and (Test-Path $_) } |
    ForEach-Object { Get-ChildItem $_ -Filter "Inno Setup*" -Directory -ErrorAction SilentlyContinue } |
    Sort-Object Name -Descending |
    ForEach-Object { Join-Path $_.FullName "ISCC.exe" } |
    Where-Object { Test-Path $_ } |
    Select-Object -First 1

if (-not $Iscc) {
    Write-Host "Inno Setup не найден." -ForegroundColor Red
    Write-Host "Скачайте его с https://jrsoftware.org/isdl.php или соберите только архив:"
    Write-Host "  .\scripts\build_portable.ps1"
    exit 1
}
Write-Host "Компилятор: $Iscc" -ForegroundColor DarkGray

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
