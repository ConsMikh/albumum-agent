"""Справочники: шрифты, заготовки листов, форматы альбома."""

from albumum_cli.commands import connect, done, group


def _fonts(args) -> int:
    return done(connect(args).run("catalog.fonts"))


def _templates(args) -> int:
    params = {"album": str(args.album), "kind": args.kind}
    return done(connect(args).run("catalog.templates", params=params))


def _formats(args) -> int:
    return done(connect(args).run("catalog.formats"))


def register(sub) -> None:
    catalog = group(sub, "catalog", "справочники: шрифты, заготовки, форматы")
    catalog.add_parser("fonts", help="шрифты и стиль нового альбома").set_defaults(handler=_fonts)

    p = catalog.add_parser("templates", help="заготовки, подходящие листу альбома")
    p.add_argument("album", type=int, metavar="АЛЬБОМ")
    p.add_argument("--kind", choices=["title", "sheet"], default="sheet")
    p.set_defaults(handler=_templates)

    catalog.add_parser("formats", help="форматы альбома").set_defaults(handler=_formats)
