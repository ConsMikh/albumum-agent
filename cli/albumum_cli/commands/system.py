"""Подключение: init, whoami, version, update, contract, schema, config set-url."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

from albumum_cli import SUPPORTED_CONTRACT, __version__, client, config, versions
from albumum_cli.client import ApiClient, ApiError
from albumum_cli.commands import NO_URL, connect
from albumum_cli.output import EXIT_CONTRACT, EXIT_ERROR, EXIT_OK, emit, fail, note
from albumum_cli.secret_input import ask, clean_key, read_clipboard, read_secret

CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10)
MIRROR_RAW = "https://raw.githubusercontent.com/ConsMikh/albumum-agent"
# Адрес по умолчанию в `albumum init`, если адрес еще не сохранен и не задан ALBUMUM_URL.
DEFAULT_URL = "https://albumum.fammix.org"


def _valid_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url.startswith(("https://", "http://")):
        raise ApiError(
            None,
            "invalid_url",
            "Адрес должен начинаться с https:// (или http:// для локальной проверки)",
        )
    return url


def _init(args) -> int:
    """Адрес и ключ (скрытым вводом) — проверка ключа операцией me.get — только потом файл."""
    url = args.url
    if not url:
        default = config.stored().get("url") or os.environ.get("ALBUMUM_URL") or DEFAULT_URL
        url = ask(f"Адрес системы [{default}]: ", default=default)
    url = _valid_url(url)
    typed = read_secret(
        "Ключ агента (ввод скрыт; просто Enter — взять из буфера обмена): ", allow_empty=True
    )
    token = clean_key(typed)
    if not token:
        token = clean_key(read_clipboard())
        note("Ключ взят из буфера обмена")
    client.check_key(token, strict=True, received=len(token))
    me = ApiClient(url, token, transport=args.transport).run("me.get")
    config.save(url=url, token=token)
    note(f"Ключ проверен и сохранен в {config.CONFIG_PATH}")
    me = me if isinstance(me, dict) else {}
    emit(
        {
            "url": url,
            "username": me.get("username"),
            "name": me.get("name"),
            "key": me.get("key"),
            "config": str(config.CONFIG_PATH),
        }
    )
    return EXIT_OK


def _whoami(args) -> int:
    emit(connect(args).run("me.get"))
    return EXIT_OK


def _contract(args) -> int:
    api = connect(args)
    found = api.contract()
    api.check_contract(write=False)
    if args.op:
        found = next((op for op in found.get("operations", []) if op.get("id") == args.op), None)
        if found is None:
            raise ApiError(
                None,
                "unknown_operation",
                f"Операции {args.op} нет в контракте: albumum contract покажет все",
            )
    emit(found)
    return EXIT_OK


def _schema(args) -> int:
    emit(connect(args).run("agent.layout_schema"))
    return EXIT_OK


def _version(args) -> int:
    cfg = config.load(url=args.url)
    if not cfg.url:
        raise ApiError(None, "no_url", NO_URL)
    info = client.get_version(cfg.url, transport=args.transport)
    emit(
        {
            "cli": __version__,
            "url": cfg.url,
            "server": info["version"],
            "agent_contract": info["agent_contract"],
            "supported_contract": SUPPORTED_CONTRACT,
            "agent_kit": info["agent_kit"],
        }
    )
    code = EXIT_OK
    if info["agent_contract"] != SUPPORTED_CONTRACT:
        note(
            f"Контракт системы ({info['agent_contract']}) не тот, что понимает утилита "
            f"({SUPPORTED_CONTRACT}): выполните `albumum update`. "
            "До обновления изменяющие команды не выполняются."
        )
        code = EXIT_CONTRACT
    if not versions.is_release(info["agent_kit"]):
        note(versions.skipped(info["agent_kit"]))
    elif versions.is_older(__version__, info["agent_kit"]):
        note(
            f"Предупреждение: набор агента {__version__} устарел, система ждет "
            f"{info['agent_kit']}: выполните `albumum update`."
        )
    return code


def _set_url(args) -> int:
    """Ключ файла привязан к его адресу: при смене origin ключ стирается, а не уходит дальше."""
    url = _valid_url(args.address)
    stored = config.stored()
    moved = bool(stored.get("token")) and config.origin(stored.get("url")) != config.origin(url)
    config.save(url=url, drop_token=moved)
    note(f"Адрес сохранен в {config.CONFIG_PATH}")
    if moved:
        note("Адрес изменен — ключ привязан к прежнему адресу и удален; выполните albumum init")
    return EXIT_OK


def _expected_kit(args) -> str | None:
    """Версия набора, которую ждет система; None — система не названа или недоступна."""
    cfg = config.load(url=args.url)
    if not cfg.url:
        note("Предупреждение: адрес системы не задан, ставлю последний выпуск зеркала")
        return None
    try:
        kit = client.get_version(cfg.url, transport=args.transport)["agent_kit"]
    except client.InvalidAnswer:
        raise
    except ApiError as exc:
        note(f"Предупреждение: {exc.reason}. Ставлю последний выпуск зеркала")
        return None
    # По версии строится адрес установщика в зеркале: только номер выпуска.
    if not versions.is_release(kit):
        raise client.InvalidAnswer(
            200, "invalid_answer", f"Система {cfg.url} назвала недопустимую версию набора агента"
        )
    return kit.removeprefix("v")


def _update(args) -> int:
    """Ставит набор той версии, что ждет система (agent_kit), его собственным установщиком;
    система недоступна — последний выпуск зеркала."""
    windows = os.name == "nt"
    name = "install.ps1" if windows else "install.sh"
    try:
        kit = _expected_kit(args)
    except client.InvalidAnswer as exc:
        fail(
            f"{exc.reason}. Обновление остановлено: обратитесь к администратору системы",
            exc.code,
            exc.status,
        )
        return EXIT_ERROR
    ref = f"v{kit}" if kit else "main"
    try:
        with httpx.Client(transport=args.transport, follow_redirects=True, timeout=60) as http:
            response = http.get(f"{MIRROR_RAW}/{ref}/{name}")
    except httpx.HTTPError as exc:
        fail(f"Зеркало с установщиком недоступно: {exc}", "network_error")
        return EXIT_ERROR
    if response.status_code != 200:
        fail(
            f"Зеркало ответило кодом {response.status_code}: выпуска {ref} нет или нет связи",
            "mirror_unavailable",
            response.status_code,
        )
        return EXIT_ERROR
    # Ключ установщику не нужен и в его окружение не попадает.
    env = {k: v for k, v in os.environ.items() if k != "ALBUMUM_TOKEN"}
    content = response.content
    if windows and not content.startswith(b"\xef\xbb\xbf"):
        content = b"\xef\xbb\xbf" + content  # Windows PowerShell 5.1 читает файл без BOM как ANSI
    if windows:
        # Работающий albumum.exe держит файлы своей среды uv: установщик идет в отдельном окне
        # и ждет выхода этого процесса. Папка со скриптом остается во временном каталоге.
        script = Path(tempfile.mkdtemp(prefix="albumum-update-")) / name
        script.write_bytes(content)
        if kit:
            env["ALBUMUM_VERSION"] = kit
        env["ALBUMUM_WAIT_PID"] = str(os.getpid())
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
        try:
            subprocess.Popen(cmd, env=env, creationflags=CREATE_NEW_CONSOLE)
        except OSError as exc:
            fail(f"Не удалось запустить установку: {exc}", "install_failed")
            return EXIT_ERROR
        note("Обновление идет в отдельном окне: дождитесь «Готово» и откройте агента заново")
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
            fail(f"Не удалось запустить установку: {exc}", "install_failed")
            return EXIT_ERROR
    if result.returncode != 0:
        fail(f"Установка набора завершилась с кодом {result.returncode}", "install_failed")
        return EXIT_ERROR
    return EXIT_OK


def register(sub) -> None:
    sub.add_parser(
        "init", help="подключить утилиту: адрес и ключ (скрытым вводом), проверка ключа"
    ).set_defaults(handler=_init)
    sub.add_parser("whoami", help="кто я: автор и ключ").set_defaults(handler=_whoami)
    sub.add_parser("version", help="версии утилиты и системы, сверка контракта").set_defaults(
        handler=_version
    )
    sub.add_parser("update", help="поставить набор той версии, что ждет система").set_defaults(
        handler=_update
    )
    contract = sub.add_parser("contract", help="контракт системы: операции, пределы, запреты")
    contract.add_argument("--op", metavar="ID", help="только одна операция")
    contract.set_defaults(handler=_contract)
    sub.add_parser("schema", help="JSON Schema документа верстки листа").set_defaults(
        handler=_schema
    )
    cfg = sub.add_parser("config", help="настройки утилиты").add_subparsers(
        dest="config_command", required=True
    )
    set_url = cfg.add_parser("set-url", help="сохранить адрес системы")
    set_url.add_argument("address", metavar="url")
    set_url.set_defaults(handler=_set_url)
