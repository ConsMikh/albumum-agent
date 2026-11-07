"""Страницы (листы) альбома: добавление, чтение и запись документа, заготовка, корзина, порядок,
фон альбома, изображение листа.

Файл листа (`page get -o`) — `{album_id, page_id, revision, document}`: запись берет ревизию из
него и ничего не перечитывает; конфликт ревизии — 409 с тем, кто и когда менял (код выхода 2)."""

from pathlib import Path

from albumum_cli import client
from albumum_cli.client import ApiError
from albumum_cli.commands import (
    add_confirm,
    add_request_id,
    connect,
    done,
    group,
    id_list,
    read_json,
    usage,
    write_json,
)

RENDER_BUSY = "render_busy"


def _add(args) -> int:
    modes = [args.template is not None, args.document is not None, args.duplicate_of is not None]
    if sum(modes) > 1:
        raise usage("Выберите одно: --template, --document или --duplicate-of")
    if args.media is not None and args.template is None:
        raise usage("--media — только вместе с --template")
    body: dict = {}
    if args.template is not None:
        body["template"] = args.template
        if args.media is not None:
            body["media_ids"] = id_list(args.media)
    if args.document is not None:
        body["document"] = _document_of(read_json(args.document), args.document)
    if args.duplicate_of is not None:
        body["duplicate_of"] = args.duplicate_of
    if args.position is not None:
        body["position"] = args.position
    path = {"album_id": args.album}
    return done(
        connect(args).run("pages.add", path=path, json=body, idempotency_key=args.request_id)
    )


def _document_of(data, source: str) -> dict:
    """Документ верстки: сам файл или поле `document` файла листа (`page get -o`)."""
    if isinstance(data, dict) and "page_id" in data and isinstance(data.get("document"), dict):
        return data["document"]
    if not isinstance(data, dict):
        raise ApiError(None, "invalid_input", f"В {source} не объект документа верстки")
    return data


def _page_file(path: str, album_id: int, page_id: int) -> dict:
    """Файл листа; номер альбома и листа в нем — те же, что в команде."""
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("revision"), int):
        raise ApiError(
            None,
            "invalid_input",
            f"{path}: нужен файл листа с полями revision и document (albumum page get … -o)",
        )
    for field, wanted in (("album_id", album_id), ("page_id", page_id)):
        if field in data and data[field] != wanted:
            raise usage(f"Файл {path} — для {field} {data[field]}, а в команде {wanted}")
    return data


def _store(path: str, album_id: int, page_id: int, page: dict) -> dict:
    record = {
        "album_id": album_id,
        "page_id": page_id,
        "revision": page["revision"],
        "document": page["document"],
    }
    file = write_json(path, record)
    return {"file": file, "album_id": album_id, "page_id": page_id, "revision": page["revision"]}


def _get(args) -> int:
    album = connect(args).run("albums.get", path={"album_id": args.album}) or {}
    page = next((p for p in album.get("pages", []) if p.get("id") == args.page), None)
    if page is None:
        raise ApiError(None, "not_found", f"В альбоме {args.album} нет листа {args.page}")
    return done(_store(args.output, args.album, args.page, page))


def _hint(error: ApiError, path: str) -> str | None:
    """Следующий шаг после отказа записи листа."""
    if error.code == "revision_mismatch":
        revision = (error.body or {}).get("revision")
        return (
            f"файл {path} не изменен; правку на сервере не перезаписывайте: возьмите revision "
            f"{revision} и document из этого ответа (или перечитайте лист в новый файл: page get), "
            "перенесите в них свою правку и повторите page put"
        )
    if error.code == "invalid_document":
        return "исправьте все errors в документе и повторите page put"
    return None


def _write(args, op: str, source: str, body: dict) -> int:
    """Одна запись листа (ревизия — из файла); после успеха файл получает ревизию и документ
    сервера."""
    path = {"album_id": args.album, "page_id": args.page}
    try:
        page = connect(args).run(op, path=path, json=body)
    except ApiError as error:
        hint = _hint(error, source)
        if hint and error.status is not None:
            error.body = {**(error.body or {}), "hint": hint}
        raise
    try:
        return done(_store(source, args.album, args.page, page))
    except ApiError as error:
        revision = page.get("revision")
        raise ApiError(
            None,
            error.code,
            error.reason,
            {
                "saved_revision": revision,
                "hint": f"на сервере записано, ревизия {revision}; обновите файл через page get",
            },
        ) from None


def _put(args) -> int:
    data = _page_file(args.file, args.album, args.page)
    if not isinstance(data.get("document"), dict):
        raise ApiError(None, "invalid_input", f"{args.file}: нет объекта document")
    body = {"revision": data["revision"], "document": data["document"]}
    return _write(args, "pages.write", args.file, body)


def _template(args) -> int:
    data = _page_file(args.source, args.album, args.page)
    body: dict = {"template": args.name, "revision": data["revision"]}
    if args.media is not None:
        body["media_ids"] = id_list(args.media)
    return _write(args, "pages.template", args.source, body)


def _delete(args) -> int:
    path = {"album_id": args.album, "page_id": args.page}
    return done(connect(args).run("pages.trash", path=path, confirm=args.confirm))


def _trash(args) -> int:
    path = {"album_id": args.album}
    body = {"page_ids": args.pages}
    return done(connect(args).run("pages.trash_many", path=path, json=body, confirm=args.confirm))


def _order(args) -> int:
    path = {"album_id": args.album}
    return done(connect(args).run("pages.order", path=path, json={"page_ids": args.pages}))


def _own_background(document: dict) -> bool:
    """Свой фон листа — как у редактора: признак `own`, иначе цвет или фото."""
    bg = document.get("background") or {}
    own = bg.get("own")
    return own if isinstance(own, bool) else bool(bg.get("color") or bg.get("media"))


def _background(args) -> int:
    """Листы и ревизии — из файла `album get -o`; без перечня — все листы со своим фоном."""
    album = read_json(args.source)
    if not isinstance(album, dict) or album.get("id") != args.album:
        raise usage(f"Файл {args.source} — не альбом {args.album} (albumum album get … -o)")
    pages = {p["id"]: p for p in album.get("pages", [])}
    if args.pages:
        missing = [i for i in args.pages if i not in pages]
        if missing:
            raise usage(f"Листов {missing} нет в файле {args.source}")
        chosen = [pages[i] for i in args.pages]
    else:
        chosen = [p for p in pages.values() if _own_background(p.get("document") or {})]
    if not chosen:
        raise ApiError(None, "nothing_to_do", "В файле нет листов со своим фоном")
    body = {"pages": [{"id": p["id"], "revision": p["revision"]} for p in chosen]}
    path = {"album_id": args.album}
    return done(
        connect(args).run("pages.album_background", path=path, json=body, confirm=args.confirm)
    )


def _image(args) -> int:
    """Изображение сохраненного листа; занято (503 render_busy) — ждет Retry-After, до трех раз."""
    api = connect(args)
    params = {"width": str(args.width), "format": args.format}
    path = {"album_id": args.album, "page_id": args.page}
    waits = 0
    while True:
        try:
            saved = api.run("pages.image", path=path, params=params, save_to=Path(args.output))
            break
        except ApiError as error:
            if error.code != RENDER_BUSY or waits >= client.RATE_WAITS:
                raise
            waits += 1
            client.sleep(_retry_after(error))
    size = saved.get("x-albumum-image-size") or ""
    width, _, height = size.partition("x")
    return done(
        {
            "file": saved["file"],
            "size": size,
            "width": int(width) if width.isdigit() else None,
            "height": int(height) if height.isdigit() else None,
        }
    )


def _retry_after(error: ApiError) -> float:
    try:
        seconds = float((error.body or {}).get("retry_after"))
    except (TypeError, ValueError):
        seconds = 5.0
    return max(0.0, min(seconds, client.MAX_WAIT_S))


def register(sub) -> None:
    pages = group(sub, "pages", "листы альбома")

    p = pages.add_parser("add", help="добавить лист: пустой, из заготовки, из файла или дубль")
    p.add_argument("album", type=int, metavar="АЛЬБОМ")
    p.add_argument("--template", metavar="ИМЯ", help="заготовка (catalog templates)")
    p.add_argument("--media", metavar="ID,…", help="файлы по местам заготовки; «-» — пусто")
    p.add_argument("--document", metavar="ФАЙЛ", help="готовая верстка из файла JSON")
    p.add_argument("--duplicate-of", type=int, metavar="ЛИСТ", help="копия листа")
    p.add_argument("--position", type=int, metavar="N", help="место в альбоме")
    add_request_id(p)
    p.set_defaults(handler=_add)

    p = pages.add_parser("trash", help="листы в корзину одним запросом")
    p.add_argument("album", type=int, metavar="АЛЬБОМ")
    p.add_argument("pages", type=int, nargs="+", metavar="ЛИСТ")
    add_confirm(p)
    p.set_defaults(handler=_trash)

    p = pages.add_parser("order", help="новый порядок листов")
    p.add_argument("album", type=int, metavar="АЛЬБОМ")
    p.add_argument("pages", type=int, nargs="+", metavar="ЛИСТ")
    p.set_defaults(handler=_order)

    p = pages.add_parser("background", help="вернуть листам фон альбома")
    p.add_argument("album", type=int, metavar="АЛЬБОМ")
    p.add_argument("pages", type=int, nargs="*", metavar="ЛИСТ", help="по умолчанию — все свои")
    p.add_argument("--from", dest="source", required=True, metavar="ФАЙЛ", help="album get -o")
    add_confirm(p)
    p.set_defaults(handler=_background)

    page = group(sub, "page", "один лист альбома")

    p = page.add_parser("get", help="лист в файл: ревизия и документ верстки")
    p.add_argument("album", type=int, metavar="АЛЬБОМ")
    p.add_argument("page", type=int, metavar="ЛИСТ")
    p.add_argument("-o", "--output", required=True, metavar="ФАЙЛ")
    p.set_defaults(handler=_get)

    p = page.add_parser("put", help="записать лист из файла (ревизия — из файла)")
    p.add_argument("album", type=int, metavar="АЛЬБОМ")
    p.add_argument("page", type=int, metavar="ЛИСТ")
    p.add_argument("file", metavar="ФАЙЛ")
    p.set_defaults(handler=_put)

    p = page.add_parser("template", help="применить заготовку к листу")
    p.add_argument("album", type=int, metavar="АЛЬБОМ")
    p.add_argument("page", type=int, metavar="ЛИСТ")
    p.add_argument("name", metavar="ИМЯ")
    p.add_argument("--from", dest="source", required=True, metavar="ФАЙЛ", help="page get -o")
    p.add_argument("--media", metavar="ID,…", help="файлы по местам заготовки; «-» — пусто")
    p.set_defaults(handler=_template)

    p = page.add_parser("delete", help="лист в корзину")
    p.add_argument("album", type=int, metavar="АЛЬБОМ")
    p.add_argument("page", type=int, metavar="ЛИСТ")
    add_confirm(p)
    p.set_defaults(handler=_delete)

    p = page.add_parser("image", help="изображение сохраненного листа — в файл")
    p.add_argument("album", type=int, metavar="АЛЬБОМ")
    p.add_argument("page", type=int, metavar="ЛИСТ")
    p.add_argument("--width", type=int, default=1280, metavar="ПИКС")
    p.add_argument("--format", choices=["jpeg", "png"], default="jpeg")
    p.add_argument("-o", "--output", required=True, metavar="ФАЙЛ")
    p.set_defaults(handler=_image)
