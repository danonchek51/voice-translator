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
# Движок распознавания и детектор голосовой команды входят в сборку: без них
# приложение запустится, но не будет ни распознавать речь, ни слышать фразу
# запуска. Модели по-прежнему загружаются отдельно.
uv sync --group dev --extra asr --extra wake-vosk
uv pip install pyinstaller

# В portable-режиме настройки, история и модели лежат в userdata рядом с
# исполняемым файлом. Пересборка не должна их уничтожать: там могут быть
# гигабайты загруженных моделей.
$UserData = Join-Path $DistDir "userdata"
$Stash = Join-Path $Root "dist\userdata-stash"
$stashed = $false
if (Test-Path $UserData) {
    if (Test-Path $Stash) { Remove-Item -Recurse -Force $Stash }
    Write-Host "Сохраняю userdata на время сборки..." -ForegroundColor Cyan
    Move-Item $UserData $Stash
    $stashed = $true
}

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
    --collect-all vosk `
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
# Архив собирается до возврата userdata: модели и личные данные в него не идут.
# Force обязателен: без него повторная сборка падает на существующем файле.
Compress-Archive -Path (Join-Path $DistDir "*") -DestinationPath $Archive -Force

if ($stashed) {
    Write-Host "Возвращаю userdata..." -ForegroundColor Cyan
    Move-Item $Stash $UserData
}

$size = (Get-Item $Archive).Length / 1MB
Write-Host ""
Write-Host ("Готово: {0} ({1:N0} МБ)" -f $Archive, $size) -ForegroundColor Green
Write-Host "Модели в архив не входят — их загрузит мастер первого запуска."
