"""`albumum call МЕТОД ПУТЬ` — запасной путь к операции контракта, у которой нет своей команды.

Запрос, которого нет в контракте или который запрещен агенту, отклоняется до сети (код 3)."""

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

from albumum_cli.client import ApiError, check_request_id
from albumum_cli.commands import add_confirm, add_request_id, connect
from albumum_cli.output import EXIT_OK, emit

# Запрещено агенту всегда, до контракта и до сети (спец. S4, раздел 5).
FORBIDDEN_PREFIXES = ("/api/me/keys", "/api/admin/", "/api/docs", "/api/openapi.json")


def _refuse(method: str, path: str, why: str) -> ApiError:
    return ApiError(None, "forbidden_operation", f"{method} {path}: {why}")


def _template_re(template: str) -> re.Pattern:
    pattern = re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>[^/]+)", re.escape(template))
    return re.compile(pattern)


def match(contract: dict, method: str, path: str) -> tuple[dict, dict] | None:
    """Операция контракта и параметры пути для запроса; None — такого запроса в контракте нет."""
    for operation in contract.get("operations", []):
        if operation.get("method") != method:
            continue
        found = _template_re(operation["path"]).fullmatch(path)
        if found:
            return operation, {k: unquote(v) for k, v in found.groupdict().items()}
    return None


def _body(source: str | None):
    if source is None:
        return None
    try:
        text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    except OSError as exc:
        raise ApiError(None, "invalid_input", f"Не удалось прочитать {source}: {exc}") from None
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ApiError(None, "invalid_input", f"Тело запроса — не JSON: {exc}") from None


def _query(pairs: list[str]) -> list[tuple[str, str]]:
    params = []
    for pair in pairs:
        name, sep, value = pair.partition("=")
        if not sep or not name:
            raise ApiError(None, "usage", f"--query ждет К=З, получено: {pair}")
        params.append((name, value))
    return params


def _call(args) -> int:
    method = args.method.upper()
    path = args.path
    segments = path.split("/")
    if not path.startswith("/api/") or "?" in path or "#" in path or {".", ".."} & set(segments):
        raise _refuse(method, path, "утилита ходит только на пути /api/… (параметры — --query)")
    if any(path.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
        raise _refuse(method, path, "запрещено агенту")
    check_request_id(args.request_id)
    api = connect(args)
    contract = api.contract()
    for item in contract.get("forbidden", []):
        if item.get("method") == method and _template_re(item["path"]).fullmatch(path):
            raise _refuse(method, path, item.get("why") or "запрещено агенту")
    found = match(contract, method, path)
    if found is None:
        raise _refuse(method, path, "такого запроса нет в контракте")
    operation, values = found
    result = api.run(
        operation["id"],
        path=values,
        params=_query(args.query) or None,
        json=_body(args.json),
        confirm=args.confirm,
        idempotency_key=args.request_id,
    )
    emit(result if result is not None else {"ok": True})
    return EXIT_OK


def register(sub) -> None:
    call = sub.add_parser("call", help="запасной путь: запрос операции контракта как есть")
    call.add_argument("method", metavar="МЕТОД")
    call.add_argument("path", metavar="ПУТЬ")
    call.add_argument("--json", metavar="ФАЙЛ", help="тело запроса из файла JSON или «-» (stdin)")
    call.add_argument("--query", metavar="К=З", action="append", default=[])
    add_confirm(call)
    add_request_id(call)
    call.set_defaults(handler=_call)
