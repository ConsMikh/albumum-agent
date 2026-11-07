"""Альбомы: список, создание, чтение, свойства и формат, проверка формата, корзина."""

import re

from albumum_cli.commands import (
    add_confirm,
    add_full,
    add_request_id,
    connect,
    done,
    group,
    read_json,
    usage,
    write_json,
)

FORMAT_RE = re.compile(r"(\d+)[xх×](\d+)")
SHEETS = ["single", "spread"]
FORMAT_HELP = "имя формата из catalog formats (например square) или стороны ШxВ (1500x1000)"


def page_format(api, text: str) -> tuple[int, int]:
    """«1500x1000» — стороны страницы; иначе имя формата из `catalog formats` («square»)."""
    found = FORMAT_RE.fullmatch(text.strip().lower())
    if found:
        return int(found.group(1)), int(found.group(2))
    presets = (api.run("catalog.formats") or {}).get("items") or []
    wanted = text.strip().casefold()
    for preset in presets:
        if wanted in (
            str(preset.get("name", "")).casefold(),
            str(preset.get("title", "")).casefold(),
        ):
            return int(preset["page_w"]), int(preset["page_h"])
    names = ", ".join(str(p.get("name")) for p in presets) or "нет"
    raise usage(
        f"--format ждет ШxВ (например 1500x1000) или имя формата из catalog formats "
        f"({names}), получено: {text}"
    )


def publication_brief(album: dict) -> dict:
    """Публикация кратко: опубликован ли, есть ли пароль, отстает ли от правок. Адреса для
    зрителей агент не получает."""
    pub = album.get("publication")
    if not isinstance(pub, dict) or pub.get("published") is False:
        return {"published": False, "has_password": False, "behind": False}
    return {
        "published": True,
        "has_password": bool(pub.get("has_password")),
        "behind": bool(pub.get("behind")),
    }


def album_brief(album: dict) -> dict:
    """Строка альбома в кратком списке: номер, название, дата, число листов, публикация."""
    return {
        "id": album.get("id"),
        "title": album.get("title"),
        "event_date": album.get("event_date"),
        "page_count": album.get("page_count"),
        **publication_brief(album),
    }


def _list(args) -> int:
    answer = connect(args).run("albums.list") or {}
    if args.full:
        return done(answer)
    return done({"items": [album_brief(a) for a in answer.get("items", [])]})


def _create(args) -> int:
    api = connect(args)
    width, height = page_format(api, args.format)
    body = {
        "title": args.title,
        "event_date": args.date,
        "page_w": width,
        "page_h": height,
        "sheet": args.sheet,
    }
    return done(api.run("albums.create", json=body, idempotency_key=args.request_id))


def _get(args) -> int:
    album = connect(args).run("albums.get", path={"album_id": args.id})
    if not args.output:
        return done(album)
    file = write_json(args.output, album)
    return done({"file": file, "album_id": album.get("id"), "pages": len(album.get("pages", []))})


def _set(args) -> int:
    given = (args.title, args.date, args.description, args.format, args.sheet, args.style)
    if all(value is None for value in given):
        raise usage("Нечего менять: укажите хотя бы одно из --title, --date, --description, "
                    "--format, --sheet, --style")  # fmt: skip
    api = connect(args)
    body: dict = {}
    for field, value in (
        ("title", args.title),
        ("event_date", args.date),
        ("description", args.description),
    ):
        if value is not None:
            body[field] = value
    if args.format is not None:
        body["page_w"], body["page_h"] = page_format(api, args.format)
    if args.sheet is not None:
        body["sheet"] = args.sheet
    if args.style is not None:
        body["style"] = read_json(args.style)
    if args.confirm:
        body["confirm_format"] = True  # «да» человека на смену формата, затрагивающую страницы
    path = {"album_id": args.id}
    album = api.run("albums.update", path=path, json=body, confirm=args.confirm) or {}
    if args.full:
        return done(album)
    changed = [CHANGED.get(field, field) for field in body if field != "confirm_format"]
    return done(
        {
            "album_id": album.get("id", args.id),
            "changed": list(dict.fromkeys(changed)),
            "title": album.get("title"),
            "event_date": album.get("event_date"),
            "page_w": album.get("page_w"),
            "page_h": album.get("page_h"),
            "sheet": album.get("sheet"),
            "page_count": album.get("page_count"),
            "updated_at": album.get("updated_at"),
        }
    )


# Поле тела -> что изменилось в кратком итоге `album set`.
CHANGED = {"event_date": "date", "page_w": "format", "page_h": "format"}


def _format_check(args) -> int:
    api = connect(args)
    width, height = page_format(api, args.format)
    params = {"page_w": str(width), "page_h": str(height), "sheet": args.sheet}
    return done(api.run("albums.format_check", path={"album_id": args.id}, params=params))


def _delete(args) -> int:
    path = {"album_id": args.id}
    return done(connect(args).run("albums.trash", path=path, confirm=args.confirm))


def register(sub) -> None:
    albums = group(sub, "albums", "альбомы")
    p = albums.add_parser(
        "list", help="альбомы автора: номер, название, дата, число листов, публикация"
    )
    add_full(p, "формат, описание, обложка, даты публикации")
    p.set_defaults(handler=_list)

    album = group(sub, "album", "один альбом")

    p = album.add_parser("create", help="создать альбом")
    p.add_argument("--title", required=True, metavar="НАЗВАНИЕ")
    p.add_argument(
        "--date",
        required=True,
        metavar="ГГГГ-ММ-ДД",
        help="дата события, обязательно (система не создает альбом без даты); автор не назвал — "
        "спросите или поставьте сегодняшнюю и скажите ему об этом",
    )
    p.add_argument("--format", required=True, metavar="ФОРМАТ", help=FORMAT_HELP)
    p.add_argument(
        "--sheet",
        required=True,
        choices=SHEETS,
        help="single — отдельные страницы, spread — развороты из двух страниц со сгибом",
    )
    add_request_id(p)
    p.set_defaults(handler=_create)

    p = album.add_parser("get", help="альбом целиком: свойства, стиль, листы и их ревизии")
    p.add_argument("id", type=int, metavar="ID", help="номер альбома (albums list)")
    p.add_argument("-o", "--output", metavar="ФАЙЛ", help="записать в файл, а не в stdout")
    p.set_defaults(handler=_get)

    p = album.add_parser("set", help="изменить свойства, стиль или формат")
    p.add_argument("id", type=int, metavar="ID", help="номер альбома (albums list)")
    p.add_argument("--title", metavar="НАЗВАНИЕ")
    p.add_argument("--date", metavar="ГГГГ-ММ-ДД")
    p.add_argument("--description", metavar="ТЕКСТ")
    p.add_argument("--format", metavar="ФОРМАТ", help=FORMAT_HELP)
    p.add_argument("--sheet", choices=SHEETS)
    p.add_argument("--style", metavar="ФАЙЛ", help="стиль альбома из файла JSON")
    add_confirm(p)
    add_full(p, "альбом целиком — стиль, листы с документами")
    p.set_defaults(handler=_set)

    p = album.add_parser("format-check", help="какие листы затронет смена формата")
    p.add_argument("id", type=int, metavar="ID", help="номер альбома (albums list)")
    p.add_argument("--format", required=True, metavar="ФОРМАТ", help=FORMAT_HELP)
    p.add_argument("--sheet", required=True, choices=SHEETS)
    p.set_defaults(handler=_format_check)

    p = album.add_parser("delete", help="альбом в корзину (только с подтверждением)")
    p.add_argument("id", type=int, metavar="ID", help="номер альбома (albums list)")
    add_confirm(p)
    p.set_defaults(handler=_delete)
