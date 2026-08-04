# Собирает portable-версию: PyInstaller в режиме onedir плюс файл-маркер.
#
# Режим onedir выбран намеренно: onefile распаковывает себя во временную папку
# при каждом запуске и заметно чаще вызывает подозрения антивируса.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Name = "VoiceFlow"
$DistDir = Join-Path $Root "dist\$Name"
$Archive = Join-Path $Root "dist\$Name-portable.zip"

Write-Host "Готовлю окружение сборки..." -ForegroundColor Cyan
# Движок распознавания входит в сборку: без него приложение запустится,
# но распознавать речь не сможет. Модели по-прежнему загружаются отдельно.
uv sync --group dev --extra asr
uv pip install pyinstaller

if (Test-Path $DistDir) { Remove-Item -Recurse -Force $DistDir }
if (Test-Path $Archive) { Remove-Item -Force $Archive }

Write-Host "Собираю $Name..." -ForegroundColor Cyan
uv run pyinstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name $Name `
    --paths src `
    --add-data "config;config" `
    --collect-submodules voiceflow `
    --collect-all onnx_asr `
    --exclude-module tkinter `
    --exclude-module pytest `
    src\voiceflow\__main__.py

if (-not (Test-Path $DistDir)) {
    Write-Host "Сборка не создала $DistDir" -ForegroundColor Red
    exit 1
}

# Маркер переключает все пути на подпапку userdata рядом с исполняемым файлом.
Set-Content -Path (Join-Path $DistDir "portable.txt") -Encoding UTF8 -Value @"
Portable-режим VoiceFlow.
Пока этот файл лежит рядом с VoiceFlow.exe, настройки, история, журналы
и модели хранятся в подпапке userdata, а не в профиле пользователя.
"@

Copy-Item (Join-Path $Root "README.md") $DistDir -Force
Copy-Item (Join-Path $Root "LICENSE") $DistDir -Force

Write-Host "Упаковываю архив..." -ForegroundColor Cyan
Compress-Archive -Path (Join-Path $DistDir "*") -DestinationPath $Archive

$size = (Get-Item $Archive).Length / 1MB
Write-Host ""
Write-Host ("Готово: {0} ({1:N0} МБ)" -f $Archive, $size) -ForegroundColor Green
Write-Host "Модели в архив не входят — их загрузит мастер первого запуска."
