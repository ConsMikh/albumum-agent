"""Ввод без следа: ключ (и пароль альбома) — скрытым вводом на терминале, иначе строкой stdin.
Аргументом команды секрет не передается: он остался бы в истории оболочки и в списке процессов."""

import getpass
import sys


class InputError(Exception):
    """Ввод не получен."""


def ask(prompt: str) -> str:
    """Открытая строка (адрес системы): подсказка — в stderr, stdout остается под JSON."""
    if sys.stdin.isatty():
        print(prompt, end="", file=sys.stderr, flush=True)
    value = sys.stdin.readline().strip()
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
