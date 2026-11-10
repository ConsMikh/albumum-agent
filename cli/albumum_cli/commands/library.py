"""Библиотека: список, карточка, загрузка, показ-версия, оригинал, корзина, каталог, дата."""

import time
from pathlib import Path
from urllib.parse import urlsplit

from albumum_cli import upload
from albumum_cli.client import ApiClient, ApiError, exit_code
from albumum_cli.commands import (
    add_confirm,
    connect,
    done,
    group,
    match_extension,
    run_busy,
    usage,
)
from albumum_cli.output import EXIT_ERROR, EXIT_OK, EXIT_PARTIAL, emit

POLL_S = 2  # как часто спрашивать, готова ли версия (--wait)
WAIT_LIMIT_S = 300  # сколько ждать всего


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
    if args.derived:
        params["derived"] = "true"
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
    """Показ-версия не шире `--width` (если такой нет — самая узкая); у видео — обложка.
    Расширение `-o` приводится к формату ответа (WebP — `.webp`)."""
    api = connect(args)
    card = api.run("library.get", path={"media_id": args.id}) or {}
    srcset = sorted(card.get("srcset") or [], key=lambda item: item["width"])
    if not srcset:
        raise ApiError(
            None,
            "no_rendition",
            f"У файла {args.id} нет показ-версий: еще в обработке или обработка не удалась",
        )
    fitting = [item for item in srcset if item["width"] <= args.width]
    chosen = fitting[-1] if fitting else srcset[0]
    saved = api.run(
        "library.rendition",
        path={"rendition_id": _rendition_id(chosen["url"])},
        save_to=Path(args.output),
    )
    return done({**match_extension(saved), "width": chosen["width"]})


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
    p.add_argument("--derived", action="store_true", help="только файлы с версиями (обработанные)")
    p.add_argument("--limit", type=int, metavar="N", help="файлов на страницу ответа (до 200)")
    p.add_argument("--all", action="store_true", help="все страницы ответа подряд")
    p.set_defaults(handler=_list)

    p = lib.add_parser("get", help="карточка файла")
    p.add_argument("id", type=int, metavar="ID", help="номер файла библиотеки (library list)")
    p.set_defaults(handler=_get)

    p = lib.add_parser("upload", help="загрузить файлы и папки: предпроверка, дубли пропускаются")
    p.add_argument(
        "paths", nargs="+", metavar="ПУТЬ", help="файлы и папки; папки — рекурсивно, скрытые — мимо"
    )
    p.add_argument("--folder", type=int, metavar="ID", help="каталог назначения")
    p.set_defaults(handler=_upload)

    p = lib.add_parser(
        "image", help="показ-версия фото (у видео — обложка) не шире --width — в файл"
    )
    p.add_argument("id", type=int, metavar="ID", help="номер файла библиотеки (library list)")
    p.add_argument("--width", type=int, default=960, metavar="ПИКС")
    p.add_argument("-o", "--output", required=True, metavar="ФАЙЛ")
    p.set_defaults(handler=_image)

    p = lib.add_parser("original", help="оригинал файла — в файл")
    p.add_argument("id", type=int, metavar="ID", help="номер файла библиотеки (library list)")
    p.add_argument("-o", "--output", required=True, metavar="ФАЙЛ")
    p.set_defaults(handler=_original)

    p = lib.add_parser("trash", help="файлы в корзину")
    p.add_argument("ids", type=int, nargs="+", metavar="ID", help="номера файлов библиотеки")
    add_confirm(p)
    p.set_defaults(handler=_trash)

    p = lib.add_parser("move", help="переложить файлы в каталог")
    p.add_argument("ids", type=int, nargs="+", metavar="ID", help="номера файлов библиотеки")
    p.add_argument("--folder", required=True, metavar="ID|none", help="каталог или none")
    add_confirm(p)
    p.set_defaults(handler=_move)

    p = lib.add_parser("taken-at", help="задать дату съемки")
    p.add_argument("ids", type=int, nargs="+", metavar="ID", help="номера файлов библиотеки")
    p.add_argument(
        "--at",
        required=True,
        metavar="ДАТА",
        help="ГГГГ-ММ-ДДTЧЧ:ММ — в поясе автора (tz в library usage) или со смещением (+05:00, Z)",
    )
    add_confirm(p)
    p.set_defaults(handler=_taken_at)

    lib.add_parser("usage", help="занятый объем и лимиты").set_defaults(handler=_usage)

    p = lib.add_parser("used-in", help="где стоят файлы")
    p.add_argument("ids", type=int, nargs="+", metavar="ID", help="номера файлов библиотеки")
    p.set_defaults(handler=_used_in)

    register_versions(lib)


def _crop_op(args) -> dict | None:
    if args.crop and args.aspect:
        raise usage("--crop и --aspect вместе не задаются: нужна либо рамка, либо пропорция")
    if args.aspect:
        return {"op": "crop", "aspect": args.aspect}
    if not args.crop:
        return None
    parts = args.crop.split(",")
    try:
        x, y, w, h = (float(p) for p in parts)
        if len(parts) != 4:
            raise ValueError
    except ValueError:
        raise usage(f"--crop ждет четыре доли холста X,Y,W,H, получено: {args.crop}") from None
    return {"op": "crop", "x": x, "y": y, "w": w, "h": h}


def recipe(args) -> list[dict]:
    """Рецепт фото из флагов — всегда в порядке отражение, поворот, обрезка, как бы ни шли флаги."""
    flips = args.flip or []
    if len(set(flips)) != len(flips):
        raise usage("--flip: каждая ось (h, v) отражается один раз")
    ops: list[dict] = [{"op": "flip", "axis": axis} for axis in sorted(flips)]
    if args.rotate is not None:
        ops.append({"op": "rotate", "angle": args.rotate})
    crop = _crop_op(args)
    if crop:
        ops.append(crop)
    if not ops:
        raise usage("Нужна хотя бы одна операция: --flip, --rotate, --crop или --aspect")
    return ops


def _version_row(api: ApiClient, media_id: int, version: int) -> dict:
    card = api.run("library.get", path={"media_id": media_id}) or {}
    found = next((v for v in card.get("versions") or [] if v.get("id") == version), None)
    if found is None:
        return {"id": version, "status": "failed", "error": "Версия пропала из карточки"}
    return found


def _wait_all(api: ApiClient, items: list[dict], failed: list[dict]) -> None:
    """Опрашивает все созданные версии вместе до `ready` или `failed`; общий предел — WAIT_LIMIT_S.
    Не дождавшиеся остаются в `items` с `pending`; `failed` переезжают в `failed`."""
    deadline = time.monotonic() + WAIT_LIMIT_S
    waiting = [i for i in items if i.get("status") == "processing"]
    while waiting:
        for item in list(waiting):
            try:
                row = _version_row(api, item["media_id"], item["version"])
            except ApiError as error:
                if exit_code(error) != EXIT_ERROR:
                    raise
                items.remove(item)
                waiting.remove(item)
                failed.append(
                    {
                        "media_id": item["media_id"],
                        "version": item["version"],
                        "error": {"code": error.code, "reason": error.reason},
                    }
                )
                continue
            if row.get("status") == "ready":
                item["status"] = "ready"
            elif row.get("status") == "failed":
                items.remove(item)
                failed.append(
                    {
                        "media_id": item["media_id"],
                        "version": item["version"],
                        "error": {"code": "failed", "reason": row.get("error") or ""},
                    }
                )
            else:
                continue
            waiting.remove(item)
        if not waiting:
            return
        if time.monotonic() + POLL_S > deadline:
            for item in waiting:
                item["pending"] = True
            return
        time.sleep(POLL_S)


def _create(api: ApiClient, ids: list[int], ops: list[dict], args) -> int:
    items: list[dict] = []
    failed: list[dict] = []
    aborted = None
    not_attempted: list[int] = []
    for index, media_id in enumerate(ids):
        body: dict = {"operations": ops}
        if args.source is not None:
            body["source"] = args.source
        try:
            made = api.run("library.version_create", path={"media_id": media_id}, json=body) or {}
            items.append(
                {"media_id": media_id, "version": made.get("id"), "status": made.get("status")}
            )
        except ApiError as error:
            if exit_code(error) != EXIT_ERROR:  # ключ, темп, контракт: остальные не пробуем
                aborted = {
                    "code": error.code,
                    "reason": error.reason,
                    "status": error.status,
                    "exit_code": exit_code(error),
                }
                not_attempted = ids[index:]
                break
            failed.append(
                {
                    "media_id": media_id,
                    "error": {"code": error.code, "reason": error.reason, **error.details()},
                }
            )
    if args.wait and aborted is None:
        try:
            _wait_all(api, items, failed)
        except ApiError as error:
            aborted = {
                "code": error.code,
                "reason": error.reason,
                "status": error.status,
                "exit_code": exit_code(error),
            }
    report: dict = {"items": items, "failed": failed}
    if aborted:
        report["aborted"] = aborted
        report["not_attempted"] = not_attempted
    emit(report)
    if aborted:
        return aborted["exit_code"]
    if not failed and not any(i.get("pending") for i in items):
        return EXIT_OK
    return EXIT_PARTIAL if items else EXIT_ERROR


def _process(args) -> int:
    ops = recipe(args)
    return _create(connect(args), args.ids, ops, args)


def _trim(args) -> int:
    ops = [{"op": "trim", "start": args.start, "end": args.end}]
    return _create(connect(args), [args.id], ops, args)


def _current(args) -> int:
    body = {"version_id": args.version}
    return done(connect(args).run("library.version_current", path={"media_id": args.id}, json=body))


def _version_trash(args) -> int:
    return done(
        connect(args).run(
            "library.version_trash", json={"ids": args.versions}, confirm=args.confirm
        )
    )


def _version_file(args) -> int:
    saved = connect(args).run(
        "library.version_file", path={"version_id": args.version}, save_to=Path(args.output)
    )
    return done(match_extension(saved))


POSTER_BUSY = "poster_busy"


def _poster(args) -> int:
    """Кадр-обложка; занято (503 poster_busy) — ждет Retry-After, до трех раз."""
    body = {"frame_s": args.at}
    path = {"version_id": args.version}
    return done(run_busy(connect(args), "library.poster", POSTER_BUSY, path=path, json=body))


def _add_wait(p) -> None:
    p.add_argument(
        "--source",
        type=int,
        metavar="ВЕРСИЯ",
        help="от какой версии считать, если оригинала нет (по умолчанию — действующая)",
    )
    p.add_argument(
        "--wait",
        action="store_true",
        help=f"ждать готовности версии (до {WAIT_LIMIT_S} с); без него версия готовится в фоне",
    )


def register_versions(lib) -> None:
    p = lib.add_parser("process", help="новая версия фото по рецепту: отражение, поворот, обрезка")
    p.add_argument("ids", type=int, nargs="+", metavar="ID", help="номера файлов (library list)")
    p.add_argument(
        "--flip", action="append", choices=["h", "v"], help="отразить по оси; можно дважды (h и v)"
    )
    p.add_argument("--rotate", type=float, metavar="ГРАДУСЫ", help="поворот по часовой, −180…180")
    p.add_argument("--crop", metavar="X,Y,W,H", help="рамка долями повернутого холста (0…1)")
    p.add_argument("--aspect", metavar="Ш:В", help="наибольшая рамка пропорции по центру: 3:2")
    _add_wait(p)
    p.set_defaults(handler=_process)

    p = lib.add_parser("trim", help="фрагмент видео новой версией")
    p.add_argument("id", type=int, metavar="ID", help="номер видеофайла (library list)")
    p.add_argument("--start", type=float, required=True, metavar="С", help="начало, секунды")
    p.add_argument("--end", type=float, required=True, metavar="С", help="конец, секунды")
    _add_wait(p)
    p.set_defaults(handler=_trim)

    p = lib.add_parser("current", help="сделать версию действующей")
    p.add_argument("id", type=int, metavar="ID", help="номер файла (library list)")
    p.add_argument("version", type=int, metavar="ВЕРСИЯ", help="номер версии из library get")
    p.set_defaults(handler=_current)

    p = lib.add_parser("version-trash", help="версии в корзину версий (готовые; failed — насовсем)")
    p.add_argument("versions", type=int, nargs="+", metavar="ВЕРСИЯ", help="номера версий")
    add_confirm(p)
    p.set_defaults(handler=_version_trash)

    p = lib.add_parser("version-file", help="файл версии — в файл")
    p.add_argument("version", type=int, metavar="ВЕРСИЯ", help="номер версии из library get")
    p.add_argument("-o", "--output", required=True, metavar="ФАЙЛ")
    p.set_defaults(handler=_version_file)

    p = lib.add_parser("poster", help="кадр-обложка видеоверсии (строится один раз)")
    p.add_argument("version", type=int, metavar="ВЕРСИЯ", help="номер версии видео из library get")
    p.add_argument("--at", type=float, required=True, metavar="С", help="момент кадра, секунды")
    p.set_defaults(handler=_poster)
