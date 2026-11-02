"""Точка входа утилиты albumum."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

from albumum_cli import SUPPORTED_CONTRACT, __version__, client, config, versions

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_MISMATCH = 2

CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10)
MIRROR_RAW = "https://raw.githubusercontent.com/ConsMikh/albumum-agent"


def err(message: str) -> None:
    print(message, file=sys.stderr)


def _version(args) -> int:
    cfg = config.load()
    if not cfg.url:
        err("Адрес системы не задан: albumum config set-url https://адрес-системы")
        return EXIT_ERROR
    try:
        client.check_url(cfg.url, cfg.token)
        info = client.get_version(cfg.url, transport=args.transport)
    except client.ApiError as exc:
        err(str(exc))
        return EXIT_ERROR
    print(
        json.dumps(
            {
                "cli": __version__,
                "url": cfg.url,
                "server": info["version"],
                "agent_contract": info["agent_contract"],
                "supported_contract": SUPPORTED_CONTRACT,
                "agent_kit": info["agent_kit"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    code = EXIT_OK
    if info["agent_contract"] > SUPPORTED_CONTRACT:
        err(
            f"Контракт системы ({info['agent_contract']}) новее, чем понимает утилита "
            f"({SUPPORTED_CONTRACT}): обновите набор командой albumum update. "
            "До обновления не выполняйте операций."
        )
        code = EXIT_MISMATCH
    if versions.is_older(__version__, info["agent_kit"]):
        err(
            f"Набор агента {__version__} устарел: система ждёт {info['agent_kit']}. "
            "Обновите набор командой albumum update."
        )
        code = EXIT_MISMATCH
    return code


def _set_url(args) -> int:
    url = args.url.strip().rstrip("/")
    if not url.startswith(("https://", "http://")):
        err("Адрес должен начинаться с https:// (или http:// для локальной проверки)")
        return EXIT_ERROR
    try:
        config.save(url=url)
    except config.ConfigError as exc:
        err(str(exc))
        return EXIT_ERROR
    err(f"Адрес сохранён в {config.CONFIG_PATH}")
    return EXIT_OK


def _expected_kit(args) -> str | None:
    """Версия набора, которую ждёт система; None — система не названа или недоступна."""
    cfg = config.load()
    if not cfg.url:
        err("Предупреждение: адрес системы не задан, ставлю последний выпуск зеркала")
        return None
    try:
        client.check_url(cfg.url, cfg.token)
        return client.get_version(cfg.url, transport=args.transport)["agent_kit"].removeprefix("v")
    except client.InvalidAnswer:
        raise
    except client.ApiError as exc:
        err(f"Предупреждение: {exc}. Ставлю последний выпуск зеркала")
        return None


def _update(args) -> int:
    """Ставит набор той версии, что ждёт система (agent_kit), его собственным установщиком;
    система недоступна — последний выпуск зеркала."""
    windows = os.name == "nt"
    name = "install.ps1" if windows else "install.sh"
    try:
        kit = _expected_kit(args)
    except client.InvalidAnswer as exc:
        err(f"{exc}. Обновление остановлено: обратитесь к администратору системы")
        return EXIT_ERROR
    ref = f"v{kit}" if kit else "main"
    try:
        with httpx.Client(transport=args.transport, follow_redirects=True, timeout=60) as http:
            response = http.get(f"{MIRROR_RAW}/{ref}/{name}")
    except httpx.HTTPError as exc:
        err(f"Зеркало с установщиком недоступно: {exc}")
        return EXIT_ERROR
    if response.status_code != 200:
        err(f"Зеркало ответило кодом {response.status_code}: выпуска {ref} нет или нет связи")
        return EXIT_ERROR
    # Ключ установщику не нужен и в его окружение не попадает.
    env = {k: v for k, v in os.environ.items() if k != "ALBUMUM_TOKEN"}
    content = response.content
    if windows and not content.startswith(b"\xef\xbb\xbf"):
        content = b"\xef\xbb\xbf" + content  # Windows PowerShell 5.1 читает файл без BOM как ANSI
    if windows:
        # Работающий albumum.exe держит файлы своей среды uv: установщик идёт в отдельном окне
        # и ждёт выхода этого процесса. Папка со скриптом остаётся во временном каталоге.
        script = Path(tempfile.mkdtemp(prefix="albumum-update-")) / name
        script.write_bytes(content)
        if kit:
            env["ALBUMUM_VERSION"] = kit
        env["ALBUMUM_WAIT_PID"] = str(os.getpid())
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
        try:
            subprocess.Popen(cmd, env=env, creationflags=CREATE_NEW_CONSOLE)
        except OSError as exc:
            err(f"Не удалось запустить установку: {exc}")
            return EXIT_ERROR
        err("Обновление идёт в отдельном окне: дождитесь «Готово» и откройте агента заново")
        return EXIT_OK
    with tempfile.TemporaryDirectory(prefix="albumum-update-") as temp:
        script = Path(temp) / name
        script.write_bytes(content)
        try:
            result = subprocess.run(
                ["sh", str(script), *(["--version", kit] if kit else [])],
                env=env,
                stdout=sys.stderr,
                check=False,
            )
        except OSError as exc:
            err(f"Не удалось запустить установку: {exc}")
            return EXIT_ERROR
    if result.returncode != 0:
        err(f"Установка набора завершилась с кодом {result.returncode}")
        return EXIT_ERROR
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="albumum", description="Агентский интерфейс Albumum")
    parser.add_argument("--version", action="version", version=f"albumum {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version", help="версии утилиты и системы, сверка контракта").set_defaults(
        handler=_version
    )
    cfg = sub.add_parser("config", help="настройки утилиты").add_subparsers(
        dest="config_command", required=True
    )
    set_url = cfg.add_parser("set-url", help="сохранить адрес системы")
    set_url.add_argument("url")
    set_url.set_defaults(handler=_set_url)
    sub.add_parser("update", help="переустановить набор из последнего выпуска").set_defaults(
        handler=_update
    )
    return parser


def main(argv: list[str] | None = None, transport=None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except (
        SystemExit
    ) as exc:  # --help и --version — 0; ошибка разбора — 1, а не 2 (2 = расхождение)
        return EXIT_OK if exc.code == 0 else EXIT_ERROR
    args.transport = transport
    try:
        return args.handler(args)
    except config.ConfigError as exc:
        err(str(exc))
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
