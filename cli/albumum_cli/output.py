"""Вывод утилиты: результат и ошибки — JSON в stdout, сообщения — в stderr; коды выхода."""

import json
import sys

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_ACTION = 2  # нужно действие: подтверждение, конфликт ревизии, ошибки документа
EXIT_AUTH = 3  # ключ или права
EXIT_RATE = 4  # темп исчерпан после ожиданий
EXIT_CONTRACT = 5  # контракт не совпал


def emit(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def fail(error: str, code: str, status: int | None = None, **extra) -> None:
    emit({"error": error, "code": code, "status": status, **extra})


def note(text: str) -> None:
    print(text, file=sys.stderr)
