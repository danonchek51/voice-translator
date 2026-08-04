"""Страж коммита: не пускает в репозиторий модели, аудио и крупные файлы.

Полагаться на один ``.gitignore`` мало: достаточно одного ``git add -f``,
чтобы в историю навсегда попал гигабайтный файл. Этот скрипт вызывается
хуком pre-commit и проверяет то, что уже собрано к коммиту.
"""

from __future__ import annotations

import sys
from pathlib import Path

#: Больше этого размера в репозитории делать нечего.
MAX_BYTES = 10 * 1024 * 1024

#: Расширения моделей и аудио.
BLOCKED_SUFFIXES = {
    ".gguf",
    ".onnx",
    ".bin",
    ".pt",
    ".pth",
    ".ct2",
    ".wav",
    ".mp3",
    ".flac",
    ".ogg",
}

#: Единственное место, где короткие wav-файлы допустимы.
AUDIO_FIXTURES = Path("tests/fixtures/audio")

#: Файлы с пользовательскими данными и секретами.
BLOCKED_NAMES = {
    "settings.toml",
    "glossary.toml",
    "history.db",
    "secrets.toml",
    ".env",
}


def _is_allowed_fixture(path: Path) -> bool:
    try:
        path.relative_to(AUDIO_FIXTURES)
    except ValueError:
        return False
    return path.suffix.lower() == ".wav"


def check(paths: list[str]) -> list[str]:
    """Возвращает список причин, по которым коммит нужно остановить."""
    problems: list[str] = []

    for raw in paths:
        path = Path(raw.replace("\\", "/"))
        if not path.is_file():
            continue

        if path.name in BLOCKED_NAMES:
            problems.append(
                f"{path}: пользовательские данные и секреты в репозиторий не попадают"
            )
            continue

        suffix = path.suffix.lower()
        if suffix in BLOCKED_SUFFIXES and not _is_allowed_fixture(path):
            problems.append(
                f"{path}: модели и аудио хранятся вне репозитория "
                f"(исключение — короткие wav в {AUDIO_FIXTURES})"
            )
            continue

        size = path.stat().st_size
        if size > MAX_BYTES:
            problems.append(
                f"{path}: {size / 1024 / 1024:.1f} МБ — больше предела "
                f"{MAX_BYTES / 1024 / 1024:.0f} МБ"
            )

    return problems


def main(argv: list[str]) -> int:
    problems = check(argv[1:])
    if not problems:
        return 0

    print("Коммит остановлен:", file=sys.stderr)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    print(
        "\nЕсли файл нужен, положите его вне репозитория и добавьте ссылку "
        "в config/models.toml.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
