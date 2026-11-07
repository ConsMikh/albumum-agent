"""Ввод без следа: ключ (и пароль альбома) — скрытым вводом на терминале, иначе строкой stdin.
Аргументом команды секрет не передается: он остался бы в истории оболочки и в списке процессов."""

import getpass
import shutil
import subprocess
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


def read_secret(prompt: str, *, allow_empty: bool = False) -> str:
    """`getpass` на терминале, иначе первая строка stdin; пусто — ошибка (или "" с allow_empty)."""
    if sys.stdin.isatty():
        value = getpass.getpass(prompt, stream=sys.stderr)
    else:
        value = sys.stdin.readline()
    value = value.strip()
    if not value and not allow_empty:
        raise InputError(f"Пустой ввод: {prompt.strip().rstrip(':')}")
    return value


def clean_key(value: str) -> str:
    """Ключ без невидимых символов вставки: пробелов, управляющих (Ctrl+V в скрытом вводе
    Windows дает \\x16) и форматирующих (BOM, нулевой ширины). В ключе таких символов нет."""
    return "".join(
        ch for ch in value if not ch.isspace() and unicodedata.category(ch) not in ("Cc", "Cf")
    )


# Чтение буфера обмена: ключ берется оттуда, куда его положила кнопка «Копировать», — без вставки
# в скрытый ввод (на Windows она бывает не текстом, а символом Ctrl+V) и без аргумента команды.
CLIPBOARD_COMMANDS = (
    ("powershell", "-NoProfile", "-NonInteractive", "-Command", "Get-Clipboard -Raw"),
    ("pwsh", "-NoProfile", "-NonInteractive", "-Command", "Get-Clipboard -Raw"),
    ("pbpaste",),
    ("wl-paste", "--no-newline"),
    ("xclip", "-selection", "clipboard", "-o"),
    ("xsel", "--clipboard", "--output"),
)


def read_clipboard() -> str:
    """Текст буфера обмена первой найденной программой; не нашлось или пусто — ошибка ввода."""
    for command in CLIPBOARD_COMMANDS:
        program = shutil.which(command[0])
        if program is None:
            continue
        try:
            done = subprocess.run(
                [program, *command[1:]], capture_output=True, timeout=10, check=False
            )
        except (OSError, subprocess.SubprocessError):
            continue
        text = done.stdout.decode("utf-8", errors="replace").strip()
        if done.returncode == 0 and text:
            return text
    raise InputError(
        "Буфер обмена пуст или недоступен: нажмите «Копировать» в окне ключа и повторите "
        "albumum init, или вставьте ключ в скрытый ввод правой кнопкой мыши"
    )
