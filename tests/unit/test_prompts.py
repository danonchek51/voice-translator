"""Загрузка и редактирование инструкций."""

from __future__ import annotations

from pathlib import Path

import pytest

from voiceflow.core.llm.prompts import PromptError, PromptLibrary

SAMPLE = """---
id: sample
title: Пример
version: 2
includes: [_shared_rules]
placeholders: [text]
---
Обработай текст.

{text}
"""

SHARED = """---
id: _shared_rules
title: Общие правила
version: 1
---
Ничего не выдумывай.
"""


@pytest.fixture
def library(tmp_path: Path) -> PromptLibrary:
    factory = tmp_path / "factory"
    user = tmp_path / "user"
    factory.mkdir()
    user.mkdir()
    (factory / "sample.md").write_text(SAMPLE, encoding="utf-8")
    (factory / "_shared_rules.md").write_text(SHARED, encoding="utf-8")
    return PromptLibrary(factory_dir=factory, user_dir=user)


# --------------------------------------------------------------------------- #
# Разбор файла
# --------------------------------------------------------------------------- #


def test_header_is_parsed(library: PromptLibrary) -> None:
    prompt = library.load("sample")

    assert prompt.id == "sample"
    assert prompt.title == "Пример"
    assert prompt.version == 2
    assert prompt.includes == ("_shared_rules",)
    assert prompt.placeholders == ("text",)
    assert prompt.body.startswith("Обработай текст.")


def test_missing_prompt_is_reported(library: PromptLibrary) -> None:
    with pytest.raises(PromptError, match="не найдена"):
        library.load("нет-такой")


def test_file_without_header_still_loads(tmp_path: Path) -> None:
    factory = tmp_path / "factory"
    factory.mkdir()
    (factory / "plain.md").write_text("Просто текст инструкции", encoding="utf-8")
    library = PromptLibrary(factory_dir=factory, user_dir=tmp_path / "user")

    prompt = library.load("plain")

    assert prompt.body == "Просто текст инструкции"
    assert prompt.version == 1
    assert prompt.includes == ()


def test_broken_version_falls_back(tmp_path: Path) -> None:
    factory = tmp_path / "factory"
    factory.mkdir()
    (factory / "x.md").write_text("---\nversion: много\n---\nтело", encoding="utf-8")
    library = PromptLibrary(factory_dir=factory, user_dir=tmp_path / "user")

    assert library.load("x").version == 1


# --------------------------------------------------------------------------- #
# Сборка запроса
# --------------------------------------------------------------------------- #


def test_render_splits_rules_and_request(library: PromptLibrary) -> None:
    system, user = library.render("sample", text="исходный текст")

    assert "Ничего не выдумывай." in system
    assert "исходный текст" in user
    assert "{text}" not in user


def test_render_without_includes(tmp_path: Path) -> None:
    factory = tmp_path / "factory"
    factory.mkdir()
    (factory / "solo.md").write_text("---\nid: solo\n---\nСделай: {text}", encoding="utf-8")
    library = PromptLibrary(factory_dir=factory, user_dir=tmp_path / "user")

    system, user = library.render("solo", text="раз")

    assert system == ""
    assert user == "Сделай: раз"


# --------------------------------------------------------------------------- #
# Пользовательские правки
# --------------------------------------------------------------------------- #


def test_user_version_overrides_factory(library: PromptLibrary) -> None:
    library.save("sample", "---\nid: sample\ntitle: Моя версия\n---\nМой текст {text}")

    prompt = library.load("sample")

    assert prompt.title == "Моя версия"
    assert prompt.is_user_override is True
    assert library.is_modified("sample") is True


def test_factory_text_stays_available_after_edit(library: PromptLibrary) -> None:
    library.save("sample", "---\nid: sample\n---\nМой текст")

    assert "Обработай текст." in library.factory_text("sample")
    assert "Мой текст" in library.current_text("sample")


def test_reset_returns_factory_version(library: PromptLibrary) -> None:
    library.save("sample", "---\nid: sample\n---\nМой текст")

    assert library.reset("sample") is True

    assert library.is_modified("sample") is False
    assert library.load("sample").title == "Пример"


def test_reset_without_changes_reports_false(library: PromptLibrary) -> None:
    assert library.reset("sample") is False


def test_empty_prompt_is_rejected(library: PromptLibrary) -> None:
    with pytest.raises(PromptError, match="пустой"):
        library.save("sample", "---\nid: sample\n---\n   ")


def test_unmodified_prompts_are_not_copied_to_profile(
    library: PromptLibrary, tmp_path: Path
) -> None:
    """Иначе обновление приложения не донесёт новые формулировки."""
    library.load("sample")

    assert list((tmp_path / "user").iterdir()) == []


# --------------------------------------------------------------------------- #
# Список для настроек
# --------------------------------------------------------------------------- #


def test_available_lists_prompts_with_modification_flag(library: PromptLibrary) -> None:
    library.save("sample", "---\nid: sample\ntitle: Пример\n---\nтело")

    items = {info.id: info for info in library.available()}

    assert items["sample"].is_user_override is True
    # Служебные includes с «_» в списке настроек не показываем.
    assert "_shared_rules" not in items


def test_available_hides_underscore_includes(library: PromptLibrary) -> None:
    ids = {info.id for info in library.available()}

    assert "_shared_rules" not in ids
    assert "sample" in ids


def test_available_includes_user_only_prompts(library: PromptLibrary) -> None:
    library.save("мой", "---\nid: мой\ntitle: Мой\n---\nтело")

    assert any(info.id == "мой" for info in library.available())


# --------------------------------------------------------------------------- #
# Заводские файлы репозитория
# --------------------------------------------------------------------------- #


def test_repository_prompts_are_valid(tmp_path: Path) -> None:
    from voiceflow.core.text.modes import STEPS

    library = PromptLibrary(user_dir=tmp_path / "user")

    for step in STEPS:
        prompt = library.load(step.prompt_id)
        assert prompt.body.strip(), f"инструкция «{step.prompt_id}» пуста"
        assert "{text}" in prompt.body, f"в «{step.prompt_id}» нет подстановки текста"
        assert "_shared_rules" in prompt.includes


def test_repository_shared_rules_mention_protected_fragments(tmp_path: Path) -> None:
    """Без этого правила модель начнёт переводить метки."""
    library = PromptLibrary(user_dir=tmp_path / "user")

    body = library.load("_shared_rules").body

    assert "⟦T1⟧" in body
    assert "только итоговый текст" in body.lower()


def test_repository_prompts_render(tmp_path: Path) -> None:
    library = PromptLibrary(user_dir=tmp_path / "user")

    system, user = library.render("clean.ru", text="проверка")

    assert "Не добавляй ничего от себя" in system
    assert "проверка" in user
