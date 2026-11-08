"""Справочники: шрифты, заготовки листов, форматы альбома."""

from albumum_cli.commands import add_full, connect, done, group


def _live(answer: dict | None, args, kind: str | None = None) -> dict:
    """Записи справочника без убранных (с --all — все) и, если задан kind, только этого вида."""
    out = dict(answer or {})
    items = out.get("items", [])
    if not args.all:
        items = [i for i in items if not i.get("removed")]
    if kind:
        items = [i for i in items if i.get("kind") == kind]
    out["items"] = items
    return out


def _fonts(args) -> int:
    return done(_live(connect(args).run("catalog.fonts"), args))


def _decorations(args) -> int:
    return done(_live(connect(args).run("catalog.decorations"), args, args.kind))


def template_brief(item: dict, full: bool) -> dict:
    """Заготовка: имя, название, вид листа, «для титульной», число мест; документ — с --full."""
    out = {
        "name": item.get("name"),
        "title": item.get("title"),
        "sheet": item.get("sheet"),
        "for_title": item.get("sheet") == "title",
        "places": item.get("places"),
    }
    if full:
        out["fits"] = item.get("fits")
        out["document"] = item.get("document")
    return out


def _templates(args) -> int:
    params = {"album": str(args.album), "kind": args.kind}
    answer = connect(args).run("catalog.templates", params=params) or {}
    items = answer.get("items", [])
    if args.places is not None:
        items = [i for i in items if (i.get("places") or {}).get("media") == args.places]
    return done({"items": [template_brief(i, args.full) for i in items]})


def _formats(args) -> int:
    return done(connect(args).run("catalog.formats"))


def register(sub) -> None:
    catalog = group(sub, "catalog", "справочники: шрифты, украшения, заготовки, форматы")
    p = catalog.add_parser("fonts", help="шрифты (с начертаниями faces)")
    p.add_argument("--all", action="store_true", help="и убранные из набора (removed: true)")
    p.set_defaults(handler=_fonts)

    p = catalog.add_parser("decorations", help="рамки, стикеры и узоры набора")
    p.add_argument("--kind", choices=["frame", "sticker", "pattern"], help="только этот вид")
    p.add_argument("--all", action="store_true", help="и убранные из набора (removed: true)")
    p.set_defaults(handler=_decorations)

    p = catalog.add_parser("templates", help="заготовки, подходящие листу альбома")
    p.add_argument("album", type=int, metavar="АЛЬБОМ", help="номер альбома (albums list)")
    p.add_argument(
        "--kind",
        choices=["title", "sheet"],
        default="sheet",
        help="sheet — для листов (по умолчанию), title — для титульной (for_title у своих)",
    )
    p.add_argument("--places", type=int, metavar="N", help="только заготовки на N мест под фото")
    add_full(p, "с пропорциями (fits) и документом заготовки")
    p.set_defaults(handler=_templates)

    catalog.add_parser("formats", help="форматы альбома").set_defaults(handler=_formats)
