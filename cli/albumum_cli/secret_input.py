"""Ввод без следа: ключ (и пароль альбома) — скрытым вводом на терминале, иначе строкой stdin.
Аргументом команды секрет не передается: он остался бы в истории оболочки и в списке процессов."""

import getpass
import sys
import unicodedata


class InputError(Exception):
    """Ввод не получен."""


def ask(prompt: str, default: str | None = None) -> str:
    """Открытая строка (адрес системы): подсказка — в stderr, stdout остается под JSON.
    Пустой ввод — значение по умолчанию, если оно есть."""
    if sys.stdin.isatty():
        print(prompt, end="", file=sys.stderr, flush=True)
    value = sys.stdin.readline().strip() or (default or "")
    if not value:
        raise InputError(f"Пустой ввод: {prompt.strip().rstrip(':')}")
    return value


def read_secret(prompt: str) -> str:
    """`getpass` на терминале, иначе первая строка stdin; пусто — ошибка."""
    if sys.stdin.isatty():
        value = getpass.getpass(prompt, stream=sys.stderr)
    else:
        value = sys.stdin.readline()
    value = value.strip()
    if not value:
        raise InputError(f"Пустой ввод: {prompt.strip().rstrip(':')}")
    return value


def clean_key(value: str) -> str:
    """Ключ без невидимых символов вставки: пробелов, управляющих (Ctrl+V в скрытом вводе
    Windows дает \\x16) и форматирующих (BOM, нулевой ширины). В ключе таких символов нет."""
    return "".join(
        ch for ch in value if not ch.isspace() and unicodedata.category(ch) not in ("Cc", "Cf")
    )
