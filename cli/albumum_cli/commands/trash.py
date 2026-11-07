"""Корзина: список, возврат, удаление навсегда."""

import re

from albumum_cli.commands import add_confirm, connect, done, group, usage

REF_RE = re.compile(r"([a-z_]+):(\d+)")


def refs(values: list[str]) -> list[dict]:
    """«media:5» → {"type": "media", "id": 5}; виды — как в `trash list`."""
    out = []
    for value in values:
        found = REF_RE.fullmatch(value)
        if not found:
            raise usage(f"Ждется ТИП:ID (например media:5, page:12), получено: {value}")
        out.append({"type": found.group(1), "id": int(found.group(2))})
    return out


def _list(args) -> int:
    return done(connect(args).run("trash.list"))


def _restore(args) -> int:
    body = {"items": refs(args.refs)}
    return done(connect(args).run("trash.restore", json=body))


def _purge(args) -> int:
    # Согласие на окончательное удаление (`confirm: true`) — часть запроса; решает жетон.
    body = {"items": refs(args.refs), "confirm": True}
    return done(connect(args).run("trash.purge", json=body, confirm=args.confirm))


def register(sub) -> None:
    trash = group(sub, "trash", "корзина")
    trash.add_parser("list", help="содержимое корзины").set_defaults(handler=_list)

    p = trash.add_parser("restore", help="вернуть из корзины")
    p.add_argument("refs", nargs="+", metavar="ТИП:ID")
    p.set_defaults(handler=_restore)

    p = trash.add_parser("purge", help="удалить из корзины навсегда (только с подтверждением)")
    p.add_argument("refs", nargs="+", metavar="ТИП:ID")
    add_confirm(p)
    p.set_defaults(handler=_purge)
