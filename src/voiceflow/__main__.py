"""Точка входа.

``python -m voiceflow`` запускает приложение, ``--check`` выводит сводку
окружения и завершается — этим удобно проверять установку на новой машине.
"""

from __future__ import annotations

import argparse
import sys

from voiceflow.streams import ensure_output_streams


def main(argv: list[str] | None = None) -> int:
    # Делается первым делом: в сборке без консоли потоков нет, и любая
    # библиотека, решившая напечатать прогресс, уронила бы приложение.
    replaced = ensure_output_streams()

    parser = argparse.ArgumentParser(
        prog="voiceflow",
        description="Локальный голосовой ввод с очисткой, переводом и вставкой текста",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="вывести сводку окружения и путей, затем выйти",
    )
    parser.add_argument(
        "--no-console-log",
        action="store_true",
        help="не дублировать лог в консоль",
    )
    args = parser.parse_args(argv)

    from voiceflow.app import build_context, environment_report

    context = build_context(console_logging=not args.no_console_log)
    if replaced:
        import logging

        logging.getLogger(__name__).debug(
            "Потоки вывода отсутствовали и заменены заглушками: %s", ", ".join(replaced)
        )

    if args.check:
        report = environment_report(context)
        width = max(len(key) for key in report)
        for key, value in report.items():
            print(f"{key.ljust(width)} : {value}")
        return 0

    from voiceflow.ui.runner import run_ui

    return run_ui(context)


if __name__ == "__main__":
    sys.exit(main())
