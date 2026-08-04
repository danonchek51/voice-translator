# Разворачивает окружение разработки VoiceFlow.
# Прав администратора не требует и системный Python не трогает.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv не найден. Установите его одной командой:" -ForegroundColor Yellow
    Write-Host '  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
    exit 1
}

# Python 3.12, а не системный 3.13: часть ML-колёс под 3.13 ещё не собрана.
Write-Host "Ставлю Python 3.12..." -ForegroundColor Cyan
uv python install 3.12

Write-Host "Синхронизирую зависимости..." -ForegroundColor Cyan
uv sync --group dev

$extras = $args
if ($extras.Count -gt 0) {
    foreach ($extra in $extras) {
        Write-Host "Ставлю дополнение: $extra" -ForegroundColor Cyan
        uv sync --extra $extra
    }
} else {
    Write-Host ""
    Write-Host "Дополнения не ставились. Доступны:" -ForegroundColor Yellow
    Write-Host "  asr        GigaAM и Silero VAD на onnxruntime (CPU)"
    Write-Host "  asr-gpu    то же, но сборка под CUDA"
    Write-Host "  whisper    faster-whisper для смешанной речи"
    Write-Host "  wake-vosk  голосовая активация на Vosk"
    Write-Host "  translate  локальный перевод Opus-MT"
    Write-Host "Пример: .\scripts\install.ps1 asr whisper"
}

Write-Host ""
Write-Host "Проверяю библиотеки CUDA..." -ForegroundColor Cyan
$cudaFound = $false
foreach ($dll in @("cublas64_12.dll", "cudnn64_9.dll")) {
    $found = $false
    foreach ($dir in ($env:PATH -split ';' | Where-Object { $_ })) {
        if (Test-Path (Join-Path $dir $dll) -ErrorAction SilentlyContinue) {
            $found = $true
            break
        }
    }
    if ($found) {
        Write-Host "  $dll — найдена"
        $cudaFound = $true
    } else {
        Write-Host "  $dll — не найдена"
    }
}
if (-not $cudaFound) {
    Write-Host "Режим GPU работать не будет, приложение откатится на процессор." -ForegroundColor Yellow
    Write-Host "Для GPU нужны CUDA 12 и cuDNN 9 либо пакеты nvidia-cublas-cu12 и nvidia-cudnn-cu12."
}

Write-Host ""
Write-Host "Готово." -ForegroundColor Green
Write-Host "Проверка окружения: uv run python -m voiceflow --check"
Write-Host "Запуск:             uv run python -m voiceflow"
Write-Host "Загрузка моделей:   uv run python scripts\download_models.py --preset light"
