"""Группы команд утилиты. Каждая операция контракта, кроме служебных (`SERVICE`), получает
команду; `COVERED` — какая команда покрывает операцию. Адреса операций — только из контракта
(`ApiClient.run`), своих путей у команд нет."""

import json
import os
from pathlib import Path

from albumum_cli import client, config
from albumum_cli.client import ApiClient, ApiError
from albumum_cli.output import EXIT_OK, emit, note

COVERED: dict[str, str] = {
    "me.get": "whoami",
    "system.version": "version",
    "agent.contract": "contract",
    "agent.layout_schema": "schema",
    # Библиотека и каталоги
    "library.list": "library list",
    "library.get": "library get",
    "library.preflight": "library upload",
    "library.upload": "library upload",
    "library.usage": "library usage",
    "library.used_in": "library used-in",
    "library.trash": "library trash",
    "library.move": "library move",
    "library.taken_at": "library taken-at",
    "library.version_create": "library process",
    "library.version_current": "library current",
    "library.version_trash": "library version-trash",
    "library.version_file": "library version-file",
    "library.poster": "library poster",
    "library.rendition": "library image",
    "library.original": "library original",
    "folders.list": "folders list",
    "folders.create": "folders create",
    "folders.rename": "folders rename",
    "folders.delete": "folders delete",
    # Корзина
    "trash.list": "trash list",
    "trash.restore": "trash restore",
    "trash.purge": "trash purge",
    # Альбомы и справочники
    "albums.list": "albums list",
    "albums.create": "album create",
    "albums.get": "album get",
    "albums.format_check": "album format-check",
    "albums.update": "album set",
    "albums.trash": "album delete",
    "catalog.templates": "catalog templates",
    "catalog.fonts": "catalog fonts",
    "catalog.decorations": "catalog decorations",
    "catalog.formats": "catalog formats",
    # Страницы
    "pages.add": "pages add",
    "pages.order": "pages order",
    "pages.album_background": "pages background",
    "pages.background_copy": "pages background-copy",
    "pages.write": "page put",
    "pages.template": "page template",
    "pages.trash": "page delete",
    "pages.trash_many": "pages trash",
    "pages.image": "page image",
    # Публикация
    "publication.state": "publication status",
    "publication.publish": "publication publish",
    "publication.withdraw": "publication withdraw",
    "publication.revoke": "publication revoke",
    "publication.password": "publication password set",
    "publication.album": "publication album",
}

# Операции без своей команды: журнал изменений и файлы опубликованной версии (адреса файлов
# приходят в ответе `publication album`).
SERVICE = {
    "system.changelog",
    "publication.file",
}


def register(sub) -> None:
    from albumum_cli.commands import (
        albums,
        catalog,
        examples,
        folders,
        library,
        pages,
        publication,
        raw,
        system,
        trash,
    )

    system.register(sub)
    library.register(sub)
    folders.register(sub)
    trash.register(sub)
    albums.register(sub)
    catalog.register(sub)
    pages.register(sub)
    publication.register(sub)
    raw.register(sub)
    examples.attach(sub)


def group(sub, name: str, help_text: str):
    """Группа подкоманд (`library list`, `album get` …)."""
    return sub.add_parser(name, help=help_text).add_subparsers(
        dest=f"{name}_command", required=True
    )


def usage(message: str) -> ApiError:
    """Ошибка в аргументах, найденная до сети (код выхода 1)."""
    return ApiError(None, "usage", message)


def done(result) -> int:
    emit(result if result is not None else {"ok": True})
    return EXIT_OK


def read_json(path: str):
    """JSON из файла; метка порядка байтов (BOM) в начале допустима: так пишет PowerShell 5.1."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ApiError(None, "invalid_input", f"Не удалось прочитать {path}: {exc}") from None
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ApiError(None, "invalid_input", f"Файл {path} — не JSON: {exc}") from None


def write_json(path: str, data) -> str:
    """Файл — во временный рядом, затем на место: прерванная запись не портит прежний файл.
    Возвращает абсолютный путь: относительный считается от текущей папки процесса, и агент
    должен видеть, куда на самом деле лег файл."""
    target = Path(path).absolute()
    partial = target.with_name(target.name + ".part")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        partial.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(partial, target)
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise ApiError(None, "write_failed", f"Не удалось записать {target}: {exc}") from None
    return str(target)


# Расширения файла по формату ответа: первое — то, на которое меняется неверное.
EXTENSIONS = {
    "image/jpeg": (".jpg", ".jpeg"),
    "image/png": (".png",),
    "image/webp": (".webp",),
    "image/avif": (".avif",),
}


def match_extension(saved: dict) -> dict:
    """Расширение записанного файла — по формату ответа (`content_type`): `175.jpg` с WebP внутри
    становится `175.webp`. В ответе — фактический путь, предупреждение — в stderr."""
    ctype = str(saved.get("content_type") or "").split(";")[0].strip().lower()
    good = EXTENSIONS.get(ctype)
    path = Path(saved["file"])
    if not good or path.suffix.lower() in good:
        return saved
    target = (
        path.with_name(path.stem + good[0]) if path.suffix else path.with_name(path.name + good[0])
    )
    existed = target.exists()
    try:
        os.replace(path, target)
    except OSError as exc:
        raise ApiError(None, "write_failed", f"Не удалось переименовать {path}: {exc}") from None
    message = f"Предупреждение: формат ответа {ctype}, файл записан как {target}, а не {path}"
    if existed:
        message += f"; прежний {target} перезаписан"
    note(message)
    return {**saved, "file": str(target)}


def id_list(text: str) -> list[int | None]:
    """«3,-,4» — номера файлов по местам; «-» — место остается пустым."""
    out: list[int | None] = []
    for part in text.split(","):
        part = part.strip()
        if part == "-":
            out.append(None)
        elif part.isdigit():
            out.append(int(part))
        else:
            raise usage(f"--media ждет номера через запятую («-» — пустое место), получено: {text}")
    return out


NO_URL = (
    "Адрес системы и ключ не заданы: попросите человека выполнить albumum init в своем окне "
    "терминала (спросит адрес и ключ скрытым вводом)"
)


def add_confirm(parser) -> None:
    parser.add_argument(
        "--confirm",
        metavar="ЖЕТОН",
        help="жетон из предпросмотра — только после явного «да» человека",
    )


def add_full(parser, what: str) -> None:
    parser.add_argument("--full", action="store_true", help=f"полный ответ системы: {what}")


def add_request_id(parser) -> None:
    parser.add_argument(
        "--request-id",
        metavar="ID",
        help="ключ повтора из прошлого сбоя: повтор не создаст дубль",
    )


def connect(args) -> ApiClient:
    """Клиент по настройкам: адрес обязателен, ключ — тоже (задается `albumum init`)."""
    cfg = config.load(url=getattr(args, "url", None))
    if not cfg.url:
        raise ApiError(
            None,
            "no_url",
            NO_URL,
        )
    if not cfg.token:
        raise ApiError(
            None,
            "no_key",
            "Ключ агента не задан: попросите человека выполнить albumum init в своем терминале",
        )
    key_origin = config.origin(cfg.key_url)
    if key_origin is None or key_origin != config.origin(cfg.url):
        # Ключ не уходит на адрес, для которого его не задавали (флаг или окружение).
        raise ApiError(
            None,
            "url_mismatch",
            f"Ключ сохранен для {cfg.key_url or 'другого адреса'}, а запрос — на {cfg.url}: "
            "ключ на другой адрес не отправляется. Агенту: не передавайте --url и не задавайте "
            "ALBUMUM_URL; нужен другой адрес — попросите человека выполнить albumum init",
        )
    return ApiClient(cfg.url, cfg.token, transport=args.transport)


def run_busy(api: ApiClient, op: str, busy_code: str, **kwargs):
    """`api.run` с ожиданием занятости: 503 с кодом `busy_code` (render_busy, poster_busy) —
    ждет Retry-After из ответа и повторяет, до `client.RATE_WAITS` раз."""
    waits = 0
    while True:
        try:
            return api.run(op, **kwargs)
        except ApiError as error:
            if error.code != busy_code or waits >= client.RATE_WAITS:
                raise
            waits += 1
            client.sleep(_retry_after(error))


def _retry_after(error: ApiError) -> float:
    try:
        seconds = float((error.body or {}).get("retry_after"))
    except (TypeError, ValueError):
        seconds = 5.0
    return max(0.0, min(seconds, client.MAX_WAIT_S))
