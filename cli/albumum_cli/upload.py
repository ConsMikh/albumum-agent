"""Загрузка файлов в библиотеку: сбор путей, хэш, предпроверка пачками, загрузка новых, отчет."""

import hashlib
import os
from pathlib import Path

from albumum_cli.client import ApiClient, ApiError, exit_code
from albumum_cli.output import EXIT_ERROR, EXIT_OK, note

BATCH = 200  # файлов в одной предпроверке
_CHUNK = 1 << 20
SKIP = {"duplicate", "trashed"}  # уже в библиотеке или в корзине: не загружаются
RETRY_HINT = "повторите library upload — загруженные будут пропущены"


def _walk(root: Path) -> list[Path]:
    """Файлы каталога без скрытых; каталог, который не читается, остается в списке сам —
    `run` отклонит его как `unreadable`."""
    found: list[Path] = []

    def broken(error: OSError) -> None:
        found.append(Path(error.filename) if error.filename else root)

    for folder, dirs, files in os.walk(root, onerror=broken):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        found.extend(Path(folder) / name for name in files if not name.startswith("."))
    return sorted(found)


def collect(paths: list[Path]) -> list[Path]:
    """Файлы по списку: каталоги — рекурсивно, по порядку имен; скрытые файлы и каталоги внутри
    пропускаются; повторы убираются."""
    out: list[Path] = []
    for path in paths:
        if path.is_dir():
            out.extend(_walk(path))
        elif path.exists():
            out.append(path)
        else:
            raise ApiError(None, "not_found", f"Нет такого файла или каталога: {path}")
    return list(dict.fromkeys(out))


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _check_folder(client: ApiClient, folder_id: int) -> None:
    folders = client.run("folders.list") or {}
    if not any(item.get("id") == folder_id for item in folders.get("items", [])):
        raise ApiError(
            None,
            "folder_not_found",
            f"Каталога {folder_id} нет в библиотеке: albumum folders list покажет каталоги",
        )


def _fatal(error: ApiError) -> bool:
    """Ключ, темп, контракт: дальше загружать бессмысленно — загрузка прерывается."""
    return exit_code(error) != EXIT_ERROR


def _unreadable(path: Path, exc: OSError) -> dict:
    return {
        "file": str(path),
        "code": "unreadable",
        "reason": f"Не удалось прочитать файл: {exc.strerror or exc}",
    }


def _rejected(path: Path, error: ApiError) -> dict:
    item = {"file": str(path), "code": error.code, "reason": error.reason}
    if error.code == "network_error":
        item["hint"] = RETRY_HINT
    return item


def _upload(client: ApiClient, path: Path, digest: str, folder_id: int | None) -> dict:
    data = {"sha256": digest}
    if folder_id is not None:
        data["folder_id"] = str(folder_id)
    with path.open("rb") as handle:
        return client.run("library.upload", data=data, files={"file": (path.name, handle)})


class _Abort(Exception):
    def __init__(self, error: ApiError, rest: list[Path]):
        self.error = error
        self.rest = rest


def run(client: ApiClient, files: list[Path], folder_id: int | None) -> dict:
    """Предпроверка пачками по BATCH, загрузка новых по одному. Отчет:
    `{uploaded: [{file, id, kind, status}], skipped: [{file, status, media_id, reason}],
    rejected: [{file, code, reason}]}`; прервано (ключ, темп, контракт, сбой предпроверки) —
    еще `aborted: {code, reason, status, exit_code}` и `not_attempted: [файл…]`."""
    if folder_id is not None:
        _check_folder(client, folder_id)
    report: dict = {"uploaded": [], "skipped": [], "rejected": []}
    try:
        for start in range(0, len(files), BATCH):
            _batch(client, files[start : start + BATCH], files[start:], folder_id, report)
    except _Abort as abort:
        error = abort.error
        report["aborted"] = {
            "code": error.code,
            "reason": error.reason,
            "status": error.status,
            "exit_code": exit_code(error),
        }
        report["not_attempted"] = [str(p) for p in abort.rest]
    return report


def report_exit(report: dict) -> int:
    """Код выхода по отчету: прервано — код прервавшей ошибки, есть отклоненные — 1."""
    if "aborted" in report:
        return report["aborted"]["exit_code"]
    return EXIT_ERROR if report["rejected"] else EXIT_OK


def _batch(client, batch: list[Path], rest: list[Path], folder_id, report: dict) -> None:
    readable: list[tuple[Path, dict]] = []
    for path in batch:
        try:
            item = {"name": path.name, "size": path.stat().st_size, "sha256": sha256_of(path)}
        except OSError as exc:
            report["rejected"].append(_unreadable(path, exc))
            continue
        readable.append((path, item))
    if not readable:
        return
    try:
        answer = client.run("library.preflight", json={"items": [i for _, i in readable]}) or {}
        verdicts = answer.get("verdicts", [])
        if len(verdicts) != len(readable):
            raise ApiError(200, "invalid_answer", "Предпроверка ответила не на все файлы")
    except ApiError as error:
        raise _Abort(error, [p for p, _ in readable] + rest[len(batch) :]) from None
    for index, ((path, item), verdict) in enumerate(zip(readable, verdicts, strict=True)):
        status = verdict.get("status")
        if status in SKIP:
            report["skipped"].append(
                {
                    "file": str(path),
                    "status": status,
                    "media_id": verdict.get("media_id"),
                    "reason": verdict.get("reason"),
                }
            )
            continue
        if status != "new":
            report["rejected"].append(
                {"file": str(path), "code": status, "reason": verdict.get("reason")}
            )
            continue
        note(f"Загрузка {path}")
        try:
            media = _upload(client, path, item["sha256"], folder_id) or {}
        except OSError as exc:
            report["rejected"].append(_unreadable(path, exc))
            continue
        except ApiError as error:
            if _fatal(error):
                left = [p for p, _ in readable[index:]] + rest[len(batch) :]
                raise _Abort(error, left) from None
            if error.code in SKIP:  # успел появиться между предпроверкой и загрузкой
                report["skipped"].append(
                    {
                        "file": str(path),
                        "status": error.code,
                        "media_id": (error.body or {}).get("media_id"),
                        "reason": error.reason,
                    }
                )
            else:
                report["rejected"].append(_rejected(path, error))
            continue
        report["uploaded"].append(
            {
                "file": str(path),
                "id": media.get("id"),
                "kind": media.get("kind"),
                "status": media.get("status"),
            }
        )
