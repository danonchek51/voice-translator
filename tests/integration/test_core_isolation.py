"""Машинная проверка архитектурных границ.

Ядро обязано оставаться платформонезависимым и офлайновым. Эти тесты ловят
нарушение раньше, чем оно попадёт в релиз и сломает перенос на macOS.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "voiceflow"
CORE = SRC / "core"

#: Платформозависимые модули. Им место только в voiceflow.platform.
FORBIDDEN_IN_CORE = (
    "win32api",
    "win32clipboard",
    "win32con",
    "win32gui",
    "win32process",
    "winreg",
    "ctypes.wintypes",
    "pywintypes",
    "PySide6",
    "PyQt5",
    "PyQt6",
    "pynput",
)

#: Сетевые библиотеки. Разрешены только там, где сеть — сознательное решение.
NETWORK_MODULES = ("httpx", "requests", "urllib.request", "aiohttp", "socket")

#: Модуль ядра -> причина, по которой ему разрешена сеть.
NETWORK_ALLOWLIST = {
    "core/llm/openai_compat.py": "обращение к локальному llama-server по петлевому адресу",
    "core/models/manager.py": "загрузка моделей, запускается вручную из настроек",
}


def iter_python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                found.add(node.module)
    return found


def matches(module: str, prefixes: tuple[str, ...]) -> str | None:
    for prefix in prefixes:
        if module == prefix or module.startswith(prefix + "."):
            return prefix
    return None


@pytest.mark.parametrize("path", iter_python_files(CORE), ids=lambda p: p.name)
def test_core_has_no_platform_imports(path: Path) -> None:
    violations = {
        module: hit
        for module in imported_modules(path)
        if (hit := matches(module, FORBIDDEN_IN_CORE))
    }
    assert not violations, (
        f"{path.relative_to(SRC)} импортирует платформозависимое: {sorted(violations)}. "
        "Платформенный код живёт в voiceflow/platform и подключается через интерфейсы."
    )


@pytest.mark.parametrize("path", iter_python_files(CORE), ids=lambda p: p.name)
def test_core_network_access_is_allowlisted(path: Path) -> None:
    relative = path.relative_to(SRC).as_posix()
    if relative in NETWORK_ALLOWLIST:
        return

    violations = {
        module for module in imported_modules(path) if matches(module, NETWORK_MODULES)
    }
    assert not violations, (
        f"{relative} импортирует сетевое: {sorted(violations)}. "
        "Основной режим работает без интернета; добавьте модуль в NETWORK_ALLOWLIST "
        "и объясните причину, если сеть действительно нужна."
    )


def test_core_does_not_import_ui() -> None:
    offenders = [
        path.relative_to(SRC).as_posix()
        for path in iter_python_files(CORE)
        if any(module.startswith("voiceflow.ui") for module in imported_modules(path))
    ]
    assert not offenders, (
        f"Ядро не должно знать про интерфейс: {offenders}. Общение идёт через EventBus."
    )


def test_core_does_not_import_platform_package() -> None:
    """Ядро работает с интерфейсами из platform.base, но не с реализациями."""
    offenders: list[str] = []
    for path in iter_python_files(CORE):
        for module in imported_modules(path):
            if module.startswith("voiceflow.platform.") and not module.startswith(
                "voiceflow.platform.base"
            ):
                offenders.append(f"{path.relative_to(SRC).as_posix()} -> {module}")
    assert not offenders, (
        f"Ядро должно зависеть только от voiceflow.platform.base: {offenders}"
    )


def test_paths_module_has_no_hardcoded_drive_letters() -> None:
    source = (SRC / "paths.py").read_text(encoding="utf-8")
    assert "C:\\" not in source and "C:/" not in source, (
        "В paths.py не должно быть жёстко прописанных путей Windows"
    )
