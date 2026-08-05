# Собирает оба архива релиза.
#
# Полный архив нужен ради простого сценария: скачал с GitHub, распаковал,
# запустил — и всё работает. Докачивать модели вручную, не понимая, откуда
# их брать, человек не должен.
#
# Лёгкий архив остаётся для тех, кому важен размер загрузки: мастер первого
# запуска скачает то, что подойдёт именно их машине.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Name = "VoiceFlow"
$DistDir = Join-Path $Root "dist\$Name"
$Slim = Join-Path $Root "dist\$Name-portable.zip"
$Full = Join-Path $Root "dist\$Name-full.zip"
$Bundled = Join-Path $Root "dist\bundled-models"
$Staging = Join-Path $Root "dist\staging"

# Что кладём в полный архив. Языковая модель весит два с половиной гигабайта
# и нужна не всем, поэтому её по-прежнему загружает мастер.
$BaseModels = @(
    "silero-vad",
    "gigaam-v3-e2e-ctc",
    "gigaam-v3-e2e-rnnt",
    "vosk-small-ru",
    "llama-server"
)

Write-Host "== Шаг 1. Сборка приложения ==" -ForegroundColor Cyan
& (Join-Path $PSScriptRoot "build_portable.ps1")
if ($LASTEXITCODE -ne 0) { throw "Сборка приложения не удалась" }

Write-Host ""
Write-Host "== Шаг 2. Загрузка базовых моделей ==" -ForegroundColor Cyan
# Модели кладём в отдельный профиль, а не в userdata сборки: там лежат
# настройки и история разработчика, им в релизе не место.
$env:VOICEFLOW_HOME = $Bundled
foreach ($model in $BaseModels) {
    Write-Host "  $model" -ForegroundColor DarkGray
    uv run --no-sync python scripts\download_models.py --model $model
    if ($LASTEXITCODE -ne 0) { throw "Не удалось загрузить $model" }
}
Remove-Item Env:\VOICEFLOW_HOME

Write-Host ""
Write-Host "== Шаг 3. Полный архив ==" -ForegroundColor Cyan
if (Test-Path $Staging) { Remove-Item -Recurse -Force $Staging }
New-Item -ItemType Directory -Path $Staging | Out-Null

# Копируем сборку без userdata: личные данные в релиз не попадают.
Get-ChildItem $DistDir -Exclude "userdata" | Copy-Item -Destination $Staging -Recurse -Force

$modelsSource = Join-Path $Bundled "models"
$modelsTarget = Join-Path $Staging "userdata\models"
New-Item -ItemType Directory -Path (Split-Path $modelsTarget) -Force | Out-Null
Copy-Item $modelsSource $modelsTarget -Recurse -Force

if (Test-Path $Full) { Remove-Item -Force $Full }
Compress-Archive -Path (Join-Path $Staging "*") -DestinationPath $Full -Force
Remove-Item -Recurse -Force $Staging

$slimSize = (Get-Item $Slim).Length / 1MB
$fullSize = (Get-Item $Full).Length / 1MB
$modelsSize = (Get-ChildItem -Recurse -File $modelsSource | Measure-Object Length -Sum).Sum / 1MB

Write-Host ""
Write-Host ("Лёгкий архив:  {0} ({1:N0} МБ) — модели загрузит мастер" -f $Slim, $slimSize) -ForegroundColor Green
Write-Host ("Полный архив:  {0} ({1:N0} МБ) — работает сразу после распаковки" -f $Full, $fullSize) -ForegroundColor Green
Write-Host ("Моделей внутри: {0:N0} МБ" -f $modelsSize)
Write-Host "Языковая модель в полный архив не входит: она весит 2.3 ГБ и нужна не всем."
