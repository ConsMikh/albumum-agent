"""Библиотека: список, карточка, загрузка, показ-версия, оригинал, корзина, каталог, дата."""

from pathlib import Path
from urllib.parse import urlsplit

from albumum_cli import upload
from albumum_cli.client import ApiError
from albumum_cli.commands import add_confirm, connect, done, group
from albumum_cli.output import emit


def folder_value(text: str) -> int | None:
    """Номер каталога или «none» — вне каталогов."""
    if text == "none":
        return None
    if text.isdigit():
        return int(text)
    raise ApiError(None, "usage", f"--folder ждет номер каталога или none, получено: {text}")


def _list(args) -> int:
    params: dict = {}
    for name, value in (
        ("kind", args.kind),
        ("folder", args.folder),
        ("date_from", args.date_from),
        ("date_to", args.date_to),
        ("limit", args.limit),
    ):
        if value is not None:
            params[name] = str(value)
    if args.folder is not None:
        folder_value(args.folder)
    if args.unused:
        params["used"] = "false"
    api = connect(args)
    page = api.run("library.list", params=params)
    if not args.all:
        return done(page)
    items = list(page.get("items", []))
    while page.get("next_cursor"):
        page = api.run("library.list", params={**params, "cursor": page["next_cursor"]})
        items.extend(page.get("items", []))
    return done({"items": items, "next_cursor": None, "total": page.get("total", len(items))})


def _get(args) -> int:
    return done(connect(args).run("library.get", path={"media_id": args.id}))


def _upload(args) -> int:
    files = upload.collect([Path(p) for p in args.paths])
    report = upload.run(connect(args), files, args.folder)
    emit(report)
    return upload.report_exit(report)


def _rendition_id(url: str) -> int:
    """Номер показ-версии — последний сегмент ее адреса из карточки."""
    last = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    if not last.isdigit():
        raise ApiError(200, "invalid_answer", f"Непонятный адрес показ-версии: {url}")
    return int(last)


def _image(args) -> int:
    """Показ-версия не шире `--width` (если такой нет — самая узкая)."""
    api = connect(args)
    card = api.run("library.get", path={"media_id": args.id}) or {}
    srcset = sorted(card.get("srcset") or [], key=lambda item: item["width"])
    if not srcset:
        raise ApiError(
            None, "no_rendition", f"У файла {args.id} нет показ-версий (видео или еще в обработке)"
        )
    fitting = [item for item in srcset if item["width"] <= args.width]
    chosen = fitting[-1] if fitting else srcset[0]
    saved = api.run(
        "library.rendition",
        path={"rendition_id": _rendition_id(chosen["url"])},
        save_to=Path(args.output),
    )
    return done({**saved, "width": chosen["width"]})


def _original(args) -> int:
    saved = connect(args).run(
        "library.original", path={"media_id": args.id}, save_to=Path(args.output)
    )
    return done(saved)


def _trash(args) -> int:
    return done(connect(args).run("library.trash", json={"ids": args.ids}, confirm=args.confirm))


def _move(args) -> int:
    body = {"ids": args.ids, "folder_id": folder_value(args.folder)}
    return done(connect(args).run("library.move", json=body, confirm=args.confirm))


def _taken_at(args) -> int:
    body = {"ids": args.ids, "taken_at": args.at}
    return done(connect(args).run("library.taken_at", json=body, confirm=args.confirm))


def _usage(args) -> int:
    return done(connect(args).run("library.usage"))


def _used_in(args) -> int:
    ids = ",".join(str(i) for i in args.ids)
    return done(connect(args).run("library.used_in", params={"ids": ids}))


def register(sub) -> None:
    lib = group(sub, "library", "библиотека файлов")

    p = lib.add_parser("list", help="файлы библиотеки (новые сверху)")
    p.add_argument("--kind", choices=["photo", "video"])
    p.add_argument("--folder", metavar="ID|none", help="каталог или none — вне каталогов")
    p.add_argument("--from", dest="date_from", metavar="ГГГГ-ММ-ДД", help="снято не раньше")
    p.add_argument("--to", dest="date_to", metavar="ГГГГ-ММ-ДД", help="снято не позже")
    p.add_argument("--unused", action="store_true", help="только не стоящие в альбомах")
    p.add_argument("--limit", type=int, metavar="N", help="файлов на страницу ответа (до 200)")
    p.add_argument("--all", action="store_true", help="все страницы ответа подряд")
    p.set_defaults(handler=_list)

    p = lib.add_parser("get", help="карточка файла")
    p.add_argument("id", type=int, metavar="ID")
    p.set_defaults(handler=_get)

    p = lib.add_parser("upload", help="загрузить файлы и папки: предпроверка, дубли пропускаются")
    p.add_argument("paths", nargs="+", metavar="ПУТЬ")
    p.add_argument("--folder", type=int, metavar="ID", help="каталог назначения")
    p.set_defaults(handler=_upload)

    p = lib.add_parser("image", help="показ-версия фото не шире --width — в файл")
    p.add_argument("id", type=int, metavar="ID")
    p.add_argument("--width", type=int, default=960, metavar="ПИКС")
    p.add_argument("-o", "--output", required=True, metavar="ФАЙЛ")
    p.set_defaults(handler=_image)

    p = lib.add_parser("original", help="оригинал файла — в файл")
    p.add_argument("id", type=int, metavar="ID")
    p.add_argument("-o", "--output", required=True, metavar="ФАЙЛ")
    p.set_defaults(handler=_original)

    p = lib.add_parser("trash", help="файлы в корзину")
    p.add_argument("ids", type=int, nargs="+", metavar="ID")
    add_confirm(p)
    p.set_defaults(handler=_trash)

    p = lib.add_parser("move", help="переложить файлы в каталог")
    p.add_argument("ids", type=int, nargs="+", metavar="ID")
    p.add_argument("--folder", required=True, metavar="ID|none", help="каталог или none")
    add_confirm(p)
    p.set_defaults(handler=_move)

    p = lib.add_parser("taken-at", help="задать дату съемки")
    p.add_argument("ids", type=int, nargs="+", metavar="ID")
    p.add_argument("--at", required=True, metavar="ДАТА", help="ГГГГ-ММ-ДДTЧЧ:ММ")
    add_confirm(p)
    p.set_defaults(handler=_taken_at)

    lib.add_parser("usage", help="занятый объем и лимиты").set_defaults(handler=_usage)

    p = lib.add_parser("used-in", help="где стоят файлы")
    p.add_argument("ids", type=int, nargs="+", metavar="ID")
    p.set_defaults(handler=_used_in)
