"""Загрузка моделей из командной строки.

Нужна там, где мастер первого запуска неудобен: на сервере сборки, при
подготовке офлайн-комплекта или когда графическая оболочка недоступна.
Логика та же, что и в мастере, — общий :class:`ModelManager`.
"""

from __future__ import annotations

import argparse
import sys

from voiceflow.app import build_context
from voiceflow.core.models import ModelManager, get_preset, list_presets
from voiceflow.core.models.manager import DownloadPlan


def _print_plan(plan: DownloadPlan) -> None:
    spec = get_preset(plan.preset)
    print(f"Пресет «{spec.title}»: {spec.summary}")
    for model in plan.installed:
        print(f"  [есть]    {model.title}")
    for model in plan.missing:
        print(f"  [скачать] {model.title} — {model.size_mb:.0f} МБ")
    for model in plan.manual:
        note = f" ({model.notes})" if model.notes else ""
        print(f"  [вручную] {model.title}{note}")
    print(f"Итого к загрузке: {plan.total_gb:.2f} ГБ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Загрузка моделей VoiceFlow")
    parser.add_argument(
        "--preset",
        choices=[spec.id for spec in list_presets()],
        default="standard",
        help="Пресет качества (по умолчанию standard)",
    )
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        metavar="ID",
        help="Загрузить конкретную модель из реестра; можно указать несколько раз",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Показать состав пресета и выйти, ничего не загружая",
    )
    args = parser.parse_args(argv)

    # Контекст нужен ради каталогов и журнала: пути к моделям берутся оттуда.
    build_context(console_logging=True)
    manager = ModelManager()
    plan = manager.download_plan(args.preset)

    _print_plan(plan)
    if args.list:
        return 0

    targets = args.model or [model.id for model in plan.missing]
    if not targets:
        print("Загружать нечего.")
        return 0

    failed: list[str] = []
    for model_id in targets:
        spec = manager.catalog.by_id(model_id)
        if spec is None:
            print(f"Неизвестная модель: {model_id}", file=sys.stderr)
            failed.append(model_id)
            continue
        if not spec.url:
            print(f"Пропускаю {model_id}: ссылки нет, требуется ручная установка")
            continue

        print(f"Загружаю {spec.title}...")
        try:
            manager.download(
                model_id,
                progress=lambda mid, value: print(f"  {mid}: {value:.0%}", end="\r"),
            )
        except Exception as exc:
            print()
            print(f"Не удалось загрузить {model_id}: {exc}", file=sys.stderr)
            failed.append(model_id)
            continue
        print()
        print(f"Готово: {spec.title}")

    if failed:
        print(f"С ошибками: {', '.join(failed)}", file=sys.stderr)
        return 1

    print("Все модели на месте.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
