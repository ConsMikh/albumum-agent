"""Точка входа утилиты albumum. Результат и ошибки — JSON в stdout, сообщения — в stderr.

Коды выхода (output.py): 0 — готово; 1 — ошибка; 2 — нужно действие (подтверждение, конфликт
ревизии, ошибки документа); 3 — ключ или права; 4 — темп исчерпан; 5 — контракт не совпал;
6 — частично: главное сделано, часть элементов отклонена (library upload с rejected при
загруженных или уже имевшихся файлах)."""

import argparse
import sys

import httpx

from albumum_cli import __version__, commands, config
from albumum_cli.client import ApiError, exit_code
from albumum_cli.output import (
    EXIT_ACTION,
    EXIT_AUTH,
    EXIT_CONTRACT,
    EXIT_ERROR,
    EXIT_OK,
    EXIT_PARTIAL,
    EXIT_RATE,
    emit,
    fail,
)
from albumum_cli.secret_input import InputError

__all__ = [
    "EXIT_ACTION",
    "EXIT_AUTH",
    "EXIT_CONTRACT",
    "EXIT_ERROR",
    "EXIT_OK",
    "EXIT_PARTIAL",
    "EXIT_RATE",
    "build_parser",
    "main",
]

CONFIRM_HINT = "покажите summary человеку; после «да» повторите команду с --confirm"
# Следующий шаг после отказа, если команда не назвала свой.
HINTS = {
    "confirmation_mismatch": "последствия изменились: покажите человеку новый preview и спросите "
    "снова; после «да» — --confirm с новым confirm_token",
    "idempotency_in_progress": "подождите несколько секунд и повторите с тем же --request-id",
    "idempotency_mismatch": "сначала проверьте чтением (albums list / album get), "
    "создан ли объект; "
    "только если нет — новый запрос с новым --request-id",
}


class UsageError(Exception):
    """Ошибка разбора командной строки."""


class Parser(argparse.ArgumentParser):
    """Ошибка разбора — исключение, а не выход с кодом 2 (код 2 — «нужно действие»)."""

    def error(self, message):
        raise UsageError(f"{self.prog}: {message}")


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog="albumum", description="Агентский интерфейс Albumum")
    parser.add_argument("--version", action="version", version=f"albumum {__version__}")
    parser.add_argument("--url", metavar="АДРЕС", help="адрес системы вместо настроенного")
    sub = parser.add_subparsers(dest="command", required=True)
    commands.register(sub)
    return parser


def report(error: ApiError) -> int:
    if error.status == 428 and error.code == "confirmation_required":
        body = error.body or {}
        emit(
            {
                "confirmation_required": True,
                "preview": body.get("preview"),
                "confirm_token": body.get("confirm_token"),
                "expires_in": body.get("expires_in"),
                "hint": CONFIRM_HINT,
            }
        )
        return EXIT_ACTION
    details = error.details()
    if error.code in HINTS:
        details.setdefault("hint", HINTS[error.code])
    fail(error.reason, error.code, error.status, **details)
    return exit_code(error)


def main(argv: list[str] | None = None, transport=None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except UsageError as exc:
        fail(str(exc), "usage")
        return EXIT_ERROR
    except SystemExit as exc:  # --help и --version
        return EXIT_OK if exc.code in (0, None) else EXIT_ERROR
    args.transport = transport
    try:
        return args.handler(args)
    except ApiError as exc:
        return report(exc)
    except config.ConfigError as exc:
        fail(str(exc), "config_error")
    except InputError as exc:
        fail(str(exc), "empty_input")
    except httpx.HTTPError as exc:  # последний рубеж: сбой связи вне обработки клиента
        fail(f"Нет связи с системой: {exc}", "network_error")
    except KeyboardInterrupt:
        fail("Прервано", "interrupted")
    return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
