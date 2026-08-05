"""Загрузка и редактирование инструкций.

Инструкции — это файлы Markdown с небольшим заголовком, а не строки в коде.
Пользователь видит их целиком, правит и возвращает заводскую версию одной
кнопкой.

Заводские файлы лежат в ``config/prompts`` и никогда не перезаписываются.
Правки пользователя сохраняются отдельно и перекрывают заводские по имени.
Неизменённые инструкции в профиле не создаются, поэтому обновление приложения
приносит новые формулировки всем, кто их не трогал.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from voiceflow import paths

logger = logging.getLogger(__name__)

FRONT_MATTER_SEPARATOR = "---"
PROMPT_SUFFIX = ".md"

#: Общий блок правил, подмешиваемый во все инструкции.
SHARED_RULES_ID = "_shared_rules"


class PromptError(RuntimeError):
    """Инструкция не найдена или не разобрана."""


@dataclass(frozen=True, slots=True)
class Prompt:
    """Разобранная инструкция."""

    id: str
    title: str
    version: int
    body: str
    includes: tuple[str, ...] = ()
    placeholders: tuple[str, ...] = ()
    source: Path | None = None
    is_user_override: bool = False


@dataclass(frozen=True, slots=True)
class PromptInfo:
    """Краткое описание для списка в настройках."""

    id: str
    title: str
    is_user_override: bool
    used_by: tuple[str, ...] = field(default_factory=tuple)


class PromptLibrary:
    """Доступ к заводским и пользовательским инструкциям."""

    def __init__(
        self,
        factory_dir: Path | None = None,
        user_dir: Path | None = None,
    ) -> None:
        self._factory_dir = factory_dir or (paths.config_dir() / "prompts")
        self._user_dir = user_dir or paths.user_prompts_dir()

    # ------------------------------------------------------------------ #
    # Чтение
    # ------------------------------------------------------------------ #

    def load(self, prompt_id: str) -> Prompt:
        """Читает инструкцию, отдавая предпочтение пользовательской версии."""
        user_path = self._user_path(prompt_id)
        if user_path.is_file():
            return self._parse(user_path, prompt_id, is_user_override=True)

        factory_path = self._factory_path(prompt_id)
        if factory_path.is_file():
            return self._parse(factory_path, prompt_id, is_user_override=False)

        raise PromptError(f"Инструкция «{prompt_id}» не найдена")

    def render(self, prompt_id: str, **values: str) -> tuple[str, str]:
        """Собирает пару «системная часть, запрос».

        Общие правила уходят в системное сообщение: так модель воспринимает их
        как ограничения, а не как часть текста для обработки.
        """
        prompt = self.load(prompt_id)
        system_parts = [self.load(include).body for include in prompt.includes]
        system = "\n\n".join(part for part in system_parts if part)

        user = prompt.body
        for key, value in values.items():
            user = user.replace("{" + key + "}", value)
        return system, user

    def available(self) -> list[PromptInfo]:
        """Список инструкций для вкладки настроек."""
        from voiceflow.core.text.modes import STEPS

        used_by: dict[str, list[str]] = {}
        for step in STEPS:
            if step.prompt_id:
                used_by.setdefault(step.prompt_id, []).append(step.title)

        ids: set[str] = set()
        for directory in (self._factory_dir, self._user_dir):
            if directory.is_dir():
                ids.update(item.stem for item in directory.glob(f"*{PROMPT_SUFFIX}"))

        result: list[PromptInfo] = []
        for prompt_id in sorted(ids):
            if prompt_id.startswith("_"):
                continue
            try:
                prompt = self.load(prompt_id)
            except PromptError:
                continue
            result.append(
                PromptInfo(
                    id=prompt_id,
                    title=prompt.title,
                    is_user_override=prompt.is_user_override,
                    used_by=tuple(used_by.get(prompt_id, ())),
                )
            )
        return result

    def factory_text(self, prompt_id: str) -> str:
        """Исходный текст заводской версии — для сравнения и сброса."""
        path = self._factory_path(prompt_id)
        if not path.is_file():
            raise PromptError(f"Заводская инструкция «{prompt_id}» не найдена")
        return path.read_text(encoding="utf-8")

    def current_text(self, prompt_id: str) -> str:
        """Текст, который сейчас используется."""
        user_path = self._user_path(prompt_id)
        if user_path.is_file():
            return user_path.read_text(encoding="utf-8")
        return self.factory_text(prompt_id)

    def is_modified(self, prompt_id: str) -> bool:
        return self._user_path(prompt_id).is_file()

    # ------------------------------------------------------------------ #
    # Изменение
    # ------------------------------------------------------------------ #

    def save(self, prompt_id: str, text: str) -> Prompt:
        """Сохраняет пользовательскую версию, проверив, что она разбирается."""
        parsed = _parse_text(text, prompt_id)
        if not parsed.body.strip():
            raise PromptError("Инструкция не может быть пустой")

        path = self._user_path(prompt_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".md.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        logger.info("Инструкция «%s» сохранена", prompt_id)
        return self.load(prompt_id)

    def reset(self, prompt_id: str) -> bool:
        """Удаляет пользовательскую версию. ``False`` — её и не было."""
        path = self._user_path(prompt_id)
        if not path.is_file():
            return False
        path.unlink()
        logger.info("Инструкция «%s» возвращена к заводской", prompt_id)
        return True

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _factory_path(self, prompt_id: str) -> Path:
        return self._factory_dir / f"{prompt_id}{PROMPT_SUFFIX}"

    def _user_path(self, prompt_id: str) -> Path:
        return self._user_dir / f"{prompt_id}{PROMPT_SUFFIX}"

    def _parse(self, path: Path, prompt_id: str, *, is_user_override: bool) -> Prompt:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PromptError(f"Не удалось прочитать «{prompt_id}»: {exc}") from exc
        parsed = _parse_text(text, prompt_id)
        return Prompt(
            id=parsed.id,
            title=parsed.title,
            version=parsed.version,
            body=parsed.body,
            includes=parsed.includes,
            placeholders=parsed.placeholders,
            source=path,
            is_user_override=is_user_override,
        )


def _parse_text(text: str, prompt_id: str) -> Prompt:
    """Разбирает файл инструкции: заголовок и тело.

    Заголовок — намеренно узкое подмножество YAML: ``ключ: значение`` и
    ``ключ: [a, b]``. Полноценный разбор YAML сюда тянуть не нужно, а лишняя
    зависимость усложнила бы сборку.
    """
    header: dict[str, str] = {}
    body = text

    stripped = text.lstrip()
    if stripped.startswith(FRONT_MATTER_SEPARATOR):
        lines = stripped.splitlines()
        closing = None
        for index in range(1, len(lines)):
            if lines[index].strip() == FRONT_MATTER_SEPARATOR:
                closing = index
                break
        if closing is not None:
            for line in lines[1:closing]:
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                key, separator, value = line.partition(":")
                if not separator:
                    continue
                header[key.strip()] = value.strip()
            body = "\n".join(lines[closing + 1 :])

    return Prompt(
        id=header.get("id", prompt_id),
        title=header.get("title", prompt_id),
        version=_parse_int(header.get("version"), default=1),
        body=body.strip(),
        includes=_parse_list(header.get("includes")),
        placeholders=_parse_list(header.get("placeholders")),
    )


def _parse_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _parse_list(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    cleaned = value.strip()
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1]
    items = [item.strip().strip("\"'") for item in cleaned.split(",")]
    return tuple(item for item in items if item)
