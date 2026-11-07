"""Публикация альбома: состояние, публикация, смена адреса, снятие, пароль, опубликованная версия.

Пароль публикации аргументом команды не передается — только скрытым вводом или строкой stdin."""

from albumum_cli.commands import add_confirm, connect, done, group, write_json
from albumum_cli.secret_input import read_secret


def _path(args) -> dict:
    return {"album_id": args.album}


def _status(args) -> int:
    return done(connect(args).run("publication.state", path=_path(args)))


def _publish(args) -> int:
    # «Да» человека на предпросмотр включает и незаполненные места (`confirm_places`).
    body = {"confirm_places": bool(args.confirm)}
    return done(
        connect(args).run("publication.publish", path=_path(args), json=body, confirm=args.confirm)
    )


def _revoke(args) -> int:
    return done(connect(args).run("publication.revoke", path=_path(args), confirm=args.confirm))


def _withdraw(args) -> int:
    return done(connect(args).run("publication.withdraw", path=_path(args), confirm=args.confirm))


def _password_set(args) -> int:
    api = connect(args)
    body = {"password": read_secret("Пароль альбома (ввод скрыт): ")}
    return done(api.run("publication.password", path=_path(args), json=body, confirm=args.confirm))


def _password_clear(args) -> int:
    body = {"password": None}
    return done(
        connect(args).run("publication.password", path=_path(args), json=body, confirm=args.confirm)
    )


def _album(args) -> int:
    album = connect(args).run("publication.album", path=_path(args)) or {}
    file = write_json(args.output, album)
    return done({"file": file, "album_id": args.album, "version": album.get("version")})


def _with_album(parser, *, confirm: bool = False):
    parser.add_argument("album", type=int, metavar="ID")
    if confirm:
        add_confirm(parser)
    return parser


def register(sub) -> None:
    pub = group(sub, "publication", "публикация альбома")
    _with_album(pub.add_parser("status", help="состояние и готовность к публикации")).set_defaults(
        handler=_status
    )
    _with_album(
        pub.add_parser("publish", help="опубликовать или обновить публикацию"), confirm=True
    ).set_defaults(handler=_publish)
    _with_album(
        pub.add_parser("revoke", help="сменить адрес публикации (прежний перестанет работать)"),
        confirm=True,
    ).set_defaults(handler=_revoke)
    _with_album(pub.add_parser("withdraw", help="снять публикацию"), confirm=True).set_defaults(
        handler=_withdraw
    )

    password = pub.add_parser("password", help="пароль публикации").add_subparsers(
        dest="password_command", required=True
    )
    _with_album(
        password.add_parser("set", help="задать пароль (скрытым вводом или из stdin)"),
        confirm=True,
    ).set_defaults(handler=_password_set)
    _with_album(password.add_parser("clear", help="снять пароль"), confirm=True).set_defaults(
        handler=_password_clear
    )

    p = _with_album(pub.add_parser("album", help="опубликованная версия альбома — в файл"))
    p.add_argument("-o", "--output", required=True, metavar="ФАЙЛ")
    p.set_defaults(handler=_album)
