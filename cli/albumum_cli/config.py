"""Конфигурация утилиты: адрес системы и ключ агента (~/.config/albumum/config.toml)."""

import json
import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("ALBUMUM_CONFIG", "~/.config/albumum/config.toml")).expanduser()


class ConfigError(Exception):
    """Конфигурация не читается."""


@dataclass
class Config:
    url: str | None
    token: str | None


def _read_file() -> dict:
    try:
        text = CONFIG_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ConfigError(f"Не удалось прочитать {CONFIG_PATH}: {exc.strerror}") from None
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Файл {CONFIG_PATH} — не TOML: {exc}") from None
    return {k: v for k, v in data.items() if isinstance(v, str)}


def load() -> Config:
    """Переменные окружения важнее файла."""
    stored = _read_file()
    url = os.environ.get("ALBUMUM_URL") or stored.get("url")
    token = os.environ.get("ALBUMUM_TOKEN") or stored.get("token")
    return Config(url=url.rstrip("/") if url else None, token=token or None)


def save(*, url: str | None = None, token: str | None = None) -> None:
    """Обновляет переданные поля, остальные сохраняет. Файл доступен только владельцу."""
    values = _read_file()
    if url is not None:
        values["url"] = url.rstrip("/")
    if token is not None:
        values["token"] = token
    body = "".join(f"{k} = {json.dumps(v, ensure_ascii=False)}\n" for k, v in values.items())
    try:
        CONFIG_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if sys.platform != "win32":
            CONFIG_PATH.parent.chmod(0o700)
        fd = os.open(CONFIG_PATH, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            if sys.platform != "win32":
                os.fchmod(handle.fileno(), 0o600)
            handle.write(body)
    except OSError as exc:
        reason = exc.strerror or exc.__class__.__name__
        raise ConfigError(f"Не удалось записать {CONFIG_PATH}: {reason}") from None
