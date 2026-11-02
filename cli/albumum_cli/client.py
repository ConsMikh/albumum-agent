"""HTTP-клиент системы Albumum."""

import re
from urllib.parse import urlsplit

import httpx

from albumum_cli import __version__

TIMEOUT = 30.0


class ApiError(Exception):
    """Система недоступна или ответила непонятно."""


class InvalidAnswer(ApiError):
    """Система ответила, но ответ не годится (в том числе недопустимая версия набора)."""


KIT_RE = re.compile(r"\d+\.\d+\.\d+(-rc\.\d+)?")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def check_url(url: str, token: str | None) -> None:
    """Ключ агента по открытому http:// не отправляется, кроме локального адреса."""
    parts = urlsplit(url)
    if token and parts.scheme == "http" and parts.hostname not in LOCAL_HOSTS:
        raise ApiError(
            f"Адрес {url} без шифрования (http://), а ключ агента задан: "
            "ключ не отправляется по открытому каналу. Используйте https://"
        )


def get_version(url: str, transport=None) -> dict:
    """GET /api/system/version — публичный путь: ключ агента на него не отправляется."""
    headers = {"User-Agent": f"albumum-cli/{__version__}"}
    try:
        with httpx.Client(timeout=TIMEOUT, transport=transport) as http:
            response = http.get(f"{url}/api/system/version", headers=headers)
    except httpx.HTTPError as exc:
        raise ApiError(f"Система {url} недоступна: {exc}") from None
    if response.status_code != 200:
        raise ApiError(f"Система {url} ответила кодом {response.status_code}")
    try:
        body = response.json()
        info = {
            "version": str(body["version"]),
            "agent_contract": int(body["agent_contract"]),
            "agent_kit": str(body["agent_kit"]).removeprefix("v"),
        }
    except (ValueError, KeyError, TypeError):
        raise InvalidAnswer(f"Система {url} ответила не так, как ждёт утилита") from None
    if not KIT_RE.fullmatch(info["agent_kit"]):
        raise InvalidAnswer(f"Система {url} назвала недопустимую версию набора агента")
    return info
