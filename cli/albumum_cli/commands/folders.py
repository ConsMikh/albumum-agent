"""Каталоги библиотеки."""

from albumum_cli.commands import add_confirm, connect, done, group


def _list(args) -> int:
    return done(connect(args).run("folders.list"))


def _create(args) -> int:
    return done(connect(args).run("folders.create", json={"name": args.name}))


def _rename(args) -> int:
    path = {"folder_id": args.id}
    return done(connect(args).run("folders.rename", path=path, json={"name": args.name}))


def _delete(args) -> int:
    path = {"folder_id": args.id}
    return done(connect(args).run("folders.delete", path=path, confirm=args.confirm))


def register(sub) -> None:
    folders = group(sub, "folders", "каталоги библиотеки")
    folders.add_parser("list", help="каталоги и число файлов").set_defaults(handler=_list)

    p = folders.add_parser("create", help="создать каталог")
    p.add_argument("name", metavar="ИМЯ")
    p.set_defaults(handler=_create)

    p = folders.add_parser("rename", help="переименовать каталог")
    p.add_argument("id", type=int, metavar="ID")
    p.add_argument("name", metavar="ИМЯ")
    p.set_defaults(handler=_rename)

    p = folders.add_parser("delete", help="удалить каталог (файлы остаются в библиотеке)")
    p.add_argument("id", type=int, metavar="ID")
    add_confirm(p)
    p.set_defaults(handler=_delete)
