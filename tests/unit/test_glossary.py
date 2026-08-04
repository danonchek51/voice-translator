"""Пользовательский словарь замен."""

from __future__ import annotations

from pathlib import Path

from voiceflow.core.text.glossary import Glossary


def write(tmp_path: Path, body: str) -> Path:
    target = tmp_path / "glossary.toml"
    target.write_text(body, encoding="utf-8")
    return target


def test_missing_file_gives_empty_glossary(tmp_path: Path) -> None:
    glossary = Glossary.load(tmp_path / "нет.toml")

    assert glossary.is_empty
    assert glossary.apply("любой текст") == ("любой текст", 0)


def test_simple_replacement(tmp_path: Path) -> None:
    path = write(tmp_path, '[replacements]\n"курсор" = "Cursor"\n')

    result, count = Glossary.load(path).apply("открой курсор и работай")

    assert result == "открой Cursor и работай"
    assert count == 1


def test_case_is_ignored(tmp_path: Path) -> None:
    path = write(tmp_path, '[replacements]\n"питон" = "Python"\n')

    result, count = Glossary.load(path).apply("Питон и питон")

    assert result == "Python и Python"
    assert count == 2


def test_yo_is_matched(tmp_path: Path) -> None:
    path = write(tmp_path, '[replacements]\n"ёлка" = "tree"\n')

    result, _ = Glossary.load(path).apply("елка стоит")

    assert result == "tree стоит"


def test_multiword_replacement(tmp_path: Path) -> None:
    path = write(tmp_path, '[replacements]\n"пул реквест" = "pull request"\n')

    result, count = Glossary.load(path).apply("создай пул реквест сегодня")

    assert result == "создай pull request сегодня"
    assert count == 1


def test_longer_entry_wins(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        '[replacements]\n"пул" = "pool"\n"пул реквест" = "pull request"\n',
    )

    result, _ = Glossary.load(path).apply("сделай пул реквест")

    assert result == "сделай pull request"


def test_part_of_word_is_not_replaced(tmp_path: Path) -> None:
    path = write(tmp_path, '[replacements]\n"апи" = "API"\n')

    result, count = Glossary.load(path).apply("написал сапиенс")

    assert count == 0
    assert result == "написал сапиенс"


def test_broken_file_is_reported(tmp_path: Path) -> None:
    path = write(tmp_path, "это [не TOML\n")

    glossary = Glossary.load(path)

    assert glossary.is_empty
    assert glossary.notes


def test_missing_section_is_reported(tmp_path: Path) -> None:
    path = write(tmp_path, 'title = "не тот раздел"\n')

    glossary = Glossary.load(path)

    assert glossary.is_empty
    assert any("replacements" in note for note in glossary.notes)


def test_wrong_value_type_is_skipped(tmp_path: Path) -> None:
    path = write(tmp_path, '[replacements]\n"курсор" = 42\n"питон" = "Python"\n')

    glossary = Glossary.load(path)

    assert glossary.replacements == {"питон": "Python"}
    assert any("строкой" in note for note in glossary.notes)


def test_repository_template_is_valid() -> None:
    """Шаблон из репозитория должен читаться без замечаний."""
    from voiceflow import paths

    glossary = Glossary.load(paths.config_dir() / "glossary.example.toml")

    assert glossary.notes == []
    assert glossary.replacements["курсор"] == "Cursor"
