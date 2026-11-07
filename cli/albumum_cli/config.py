"""Конфигурация утилиты: адрес системы и ключ агента (~/.config/albumum/config.toml).

Порядок: флаг `--url` → `ALBUMUM_URL`, `ALBUMUM_TOKEN` → файл. Флага для ключа нет и не будет:
ключ задается только `albumum init` (скрытым вводом), переменной окружения или файлом."""

import json
import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

CONFIG_PATH = Path(os.environ.get("ALBUMUM_CONFIG", "~/.config/albumum/config.toml")).expanduser()


class ConfigError(Exception):
    """Конфигурация не читается."""


@dataclass
class Config:
    url: str | None
    token: str | None
    key_url: str | None = None  # адрес, для которого задан ключ: ключ годится только для него


def origin(url: str | None) -> tuple[str, str, int] | None:
    """Схема, хост и порт адреса — по ним сравнивается, для того ли адреса ключ."""
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
        port = parts.port or {"https": 443, "http": 80}.get(parts.scheme.lower())
    except ValueError:
        return None
    if not parts.hostname or port is None:
        return None
    return parts.scheme.lower(), parts.hostname.lower().rstrip("."), port


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


def load(url: str | None = None) -> Config:
    """`url` — значение флага `--url`; он важнее окружения, окружение важнее файла.

    Ключ привязан к адресу: ключ файла — к адресу файла, `ALBUMUM_TOKEN` — к `ALBUMUM_URL`
    (без него — тоже к адресу файла). `key_url` — этот адрес; совпадает ли он с итоговым
    `url`, проверяет команда, которой нужен ключ (`commands.connect`)."""
    stored = _read_file()
    env_url = os.environ.get("ALBUMUM_URL") or None
    env_token = os.environ.get("ALBUMUM_TOKEN") or None
    final = url or env_url or stored.get("url")
    if env_token:
        token, key_url = env_token, env_url or stored.get("url")
    else:
        token, key_url = stored.get("token") or None, stored.get("url")
    return Config(
        url=final.rstrip("/") if final else None,
        token=token,
        key_url=key_url.rstrip("/") if key_url else None,
    )


def stored() -> dict[str, str]:
    """Поля файла как есть, без окружения: ключ файла привязан к адресу файла."""
    return _read_file()


def save(*, url: str | None = None, token: str | None = None, drop_token: bool = False) -> None:
    """Обновляет переданные поля, остальные сохраняет; `drop_token` — стирает ключ.
    Файл доступен только владельцу."""
    values = _read_file()
    if drop_token:
        values.pop("token", None)
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
