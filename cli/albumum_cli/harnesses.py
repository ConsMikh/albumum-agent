"""Перечень харнессов (agent/harnesses.json) и подключение к ним скиллов набора.

Скиллы лежат в хранилище набора (`KIT_HOME`) и подключаются ссылками, на Windows — копиями с
меткой `KIT_MARK` (в ней версия набора). Общий каталог `SHARED_DIR` — всегда; собственный каталог
харнесса — только найденным харнессам, которые общий каталог не читают (`reads_shared: false`).
Устаревшее убирается во всех каталогах перечня: ссылка в хранилище на скилл, которого больше нет,
и копия с меткой, скилла которой больше нет. Чужие файлы и каталоги без метки не трогаются.

Поля записи перечня: `detect.bin`/`detect.dirs` — признаки харнесса на компьютере (бинарь в PATH
или каталог); `skills_dir` — собственный каталог (null — только общий); `windows_dir` — путь на
Windows, если он не тот же `skills_dir` под %USERPROFILE%; `sandbox_env` — переменные среды
харнесса; `network_hint` — что разрешить песочнице без сети; `manual` — ручное подключение;
`smoke` — неинтерактивный запуск, `{prompt}` заменяется поручением; `notes`, `source` — что
подтверждено и где."""

import json
import os
import re
import shutil
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from albumum_cli import __version__, versions
from albumum_cli.output import EXIT_OK, emit

KIT_MARK = ".albumum-kit"
SHARED_DIR = "~/.agents/skills"
KIT_HOME = "~/.local/share/albumum/skills"
REPO_FILE = Path(__file__).parents[2] / "harnesses.json"  # разработка: agent/harnesses.json


@dataclass(frozen=True)
class Harness:
    id: str
    title: str
    bins: tuple[str, ...]
    dirs: tuple[str, ...]
    skills_dir: str | None
    reads_shared: bool
    windows_dir: str | None
    sandbox_env: tuple[str, ...]
    network_hint: str | None
    manual: str
    smoke: str | None
    notes: str
    source: str = ""


def _read() -> dict:
    """Перечень из колеса (albumum_cli/harnesses.json), в разработке — из agent/."""
    packed = resources.files("albumum_cli") / "harnesses.json"
    text = packed.read_text("utf-8") if packed.is_file() else REPO_FILE.read_text("utf-8")
    return json.loads(text)


def load() -> list[Harness]:
    return [
        Harness(
            id=item["id"],
            title=item["title"],
            bins=tuple(item["detect"].get("bin") or ()),
            dirs=tuple(item["detect"].get("dirs") or ()),
            skills_dir=item.get("skills_dir"),
            reads_shared=bool(item["reads_shared"]),
            windows_dir=item.get("windows_dir"),
            sandbox_env=tuple(item.get("sandbox_env") or ()),
            network_hint=item.get("network_hint"),
            manual=item["manual"],
            smoke=item.get("smoke"),
            notes=item.get("notes", ""),
            source=item.get("source", ""),
        )
        for item in _read()["harnesses"]
    ]


def running_inside() -> Harness | None:
    """Харнесс, внутри которого запущена утилита: задана (непустая) переменная из `sandbox_env`."""
    return next((h for h in load() if any(os.environ.get(n) for n in h.sandbox_env)), None)


def expand(path: str, home: Path, windows: bool) -> Path:
    """`~` и `%USERPROFILE%` — домашний каталог; разделители `/` и `\\` равноправны."""
    for prefix in ("~", "%USERPROFILE%"):
        if path == prefix or path.startswith((prefix + "/", prefix + "\\")):
            parts = [p for p in re.split(r"[\\/]", path[len(prefix) :]) if p]
            return Path(home, *parts)
    return Path(path)


def default_kit_home(home: Path, windows: bool) -> Path:
    """Хранилище набора, куда его кладет установщик (на Windows — %LOCALAPPDATA%)."""
    if windows:
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else home / "AppData" / "Local"
        return base / "albumum" / "skills"
    return expand(KIT_HOME, home, windows)


def detect(h: Harness, home: Path, path_env: str) -> bool:
    if any(shutil.which(name, path=path_env) for name in h.bins):
        return True
    return any(expand(d, home, False).is_dir() for d in h.dirs)


def own_dir(h: Harness, home: Path, windows: bool) -> Path | None:
    if windows and h.windows_dir:
        return expand(h.windows_dir, home, windows)
    return expand(h.skills_dir, home, windows) if h.skills_dir else None


def _target_dir(h: Harness, home: Path, windows: bool) -> tuple[Path, bool]:
    """Каталог, откуда харнесс берет скиллы набора, и общий ли он."""
    own = own_dir(h, home, windows)
    if h.reads_shared or own is None:
        return expand(SHARED_DIR, home, windows), True
    return own, False


def _skills(kit_home: Path) -> list[str]:
    if not kit_home.is_dir():
        return []
    return sorted(
        p.name
        for p in kit_home.iterdir()
        if p.is_dir() and not p.is_symlink() and (p / "SKILL.md").is_file()
    )


def _kit_link(entry: Path, kit_home: Path) -> str | None:
    """Имя скилла набора, на который ведет ссылка `entry`; None — не ссылка в хранилище."""
    if not entry.is_symlink():
        return None
    target = Path(os.readlink(entry))
    if not target.is_absolute():
        target = entry.parent / target
    target = Path(os.path.normpath(target))
    for root in {Path(os.path.normpath(kit_home)), Path(os.path.realpath(kit_home))}:
        if target.parent == root:
            return target.name
    return None


def _kit_copy(entry: Path) -> bool:
    return entry.is_dir() and not entry.is_symlink() and (entry / KIT_MARK).is_file()


def _version_of(entry: Path, kit_home: Path) -> str | None:
    """Версия набора из метки; не номер выпуска (прежний install.ps1 писал фразу) — None."""
    mark = entry / KIT_MARK if _kit_copy(entry) else kit_home / KIT_MARK
    try:
        text = mark.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text if versions.is_release(text) else None


def _remove(entry: Path) -> None:
    if entry.is_symlink():
        entry.unlink()
    elif entry.exists():
        shutil.rmtree(entry)


def _place(source: Path, target: Path, kit_home: Path, windows: bool, version: str) -> str | None:
    """Ссылка или копия скилла; отказ — текст причины."""
    exists = target.is_symlink() or target.exists()
    if exists:
        if not windows and _kit_link(target, kit_home) == source.name:
            return None
        if _kit_link(target, kit_home) is None and not _kit_copy(target):
            return f"{target} — не скилл набора, оставляю как есть"
    if not windows:
        _remove(target)
        os.symlink(source, target, target_is_directory=True)
        return None
    # Копия собирается рядом и встает на место целиком: оборванная копия не выглядит рабочей.
    partial = target.with_name(f".{target.name}.albumum-part")
    try:
        _remove(partial)
        shutil.copytree(source, partial, symlinks=False)
        (partial / KIT_MARK).write_text(version + "\n", encoding="utf-8")
        _remove(target)
        os.replace(partial, target)
    finally:
        _remove(partial)
    return None


def _drop_stale(directory: Path, skills: list[str], kit_home: Path) -> None:
    if not directory.is_dir():
        return
    for entry in directory.iterdir():
        name = _kit_link(entry, kit_home)
        if name is not None and (name not in skills or not entry.exists()):
            entry.unlink()
        elif name is None and _kit_copy(entry) and entry.name not in skills:
            shutil.rmtree(entry)


def link_all(
    home: Path, path_env: str, windows: bool, kit_home: Path, version: str = __version__
) -> dict:
    """Подключает скиллы набора: общий каталог — всегда, собственный — найденным харнессам,
    которые общий не читают; убирает устаревшее во всех каталогах перечня (только когда в
    хранилище есть скиллы: пустое хранилище не повод сносить рабочие копии).
    Итог: `linked` — найденные харнессы, в чей каталог легли все скиллы; `failed` — найденные,
    которым подключить не удалось, с причиной; `not_found` — названия ненайденных; `errors` —
    общие сбои; `shared_ok` — общий каталог подключен, иначе причина в `shared_problem`;
    `skills` — сколько скиллов в хранилище. `version` — версия набора для меток."""
    items = load()
    skills = _skills(kit_home)
    shared = expand(SHARED_DIR, home, windows)
    errors: list[str] = []
    found: list[tuple[Harness, Path, bool]] = []
    not_found = []
    for h in items:
        if detect(h, home, path_env):
            found.append((h, *_target_dir(h, home, windows)))
        else:
            not_found.append(h.title)
    problems: dict[Path, str] = {}
    if not skills:
        reason = f"в {kit_home} нет скиллов набора — запустите установку набора еще раз"
        problems = dict.fromkeys([shared, *(d for _, d, _ in found)], reason)
    else:
        if not windows:
            try:
                (kit_home / KIT_MARK).write_text(version + "\n", encoding="utf-8")
            except OSError as exc:
                errors.append(f"не удалось записать метку версии в {kit_home}: {exc}")
        targets = [shared, *dict.fromkeys(d for _, d, is_shared in found if not is_shared)]
        for directory in targets:
            try:
                directory.mkdir(parents=True, exist_ok=True)
                for name in skills:
                    reason = _place(kit_home / name, directory / name, kit_home, windows, version)
                    if reason:
                        problems.setdefault(directory, reason)
            except OSError as exc:
                problems.setdefault(directory, f"не удалось подключить скиллы в {directory}: {exc}")
        cleaned = {shared, *(d for h in items if (d := own_dir(h, home, windows)) is not None)}
        for directory in sorted(cleaned):
            try:
                _drop_stale(directory, skills, kit_home)
            except OSError as exc:
                errors.append(f"не удалось убрать устаревшее в {directory}: {exc}")
    linked, failed = [], []
    for h, directory, is_shared in found:
        item = {"id": h.id, "title": h.title, "dir": str(directory), "shared": is_shared}
        if directory in problems:
            failed.append({**item, "reason": problems[directory]})
        else:
            linked.append(item)
    return {
        "linked": linked,
        "failed": failed,
        "not_found": not_found,
        "errors": errors,
        "shared_ok": shared not in problems,
        "shared_problem": problems.get(shared),
        "skills": len(skills),
    }


def status(home: Path, path_env: str, windows: bool, kit_home: Path | None = None) -> list[dict]:
    """По каждому харнессу: найден ли, каталог, подключены ли все скиллы набора, версия набора."""
    kit_home = kit_home or default_kit_home(home, windows)
    skills = _skills(kit_home)
    rows = []
    for h in load():
        directory, is_shared = _target_dir(h, home, windows)
        entries = [directory / name for name in skills]
        ours = [
            e
            for e in entries
            if (_kit_link(e, kit_home) == e.name or _kit_copy(e)) and (e / "SKILL.md").is_file()
        ]
        linked = bool(skills) and len(ours) == len(entries)
        rows.append(
            {
                "id": h.id,
                "title": h.title,
                "found": detect(h, home, path_env),
                "dir": str(directory),
                "shared": is_shared,
                "reads_shared": h.reads_shared,
                "linked": linked,
                "kit_version": _version_of(ours[0], kit_home) if linked else None,
            }
        )
    return rows


def show(path: str, home: Path, windows: bool) -> str:
    """Путь для человека: домашний каталог — `~` (на Windows — %USERPROFILE%)."""
    try:
        rel = Path(path).relative_to(home)
    except ValueError:
        return path
    if windows:
        return "%USERPROFILE%\\" + str(rel).replace("/", "\\")
    return f"~/{rel.as_posix()}"


def summary(result: dict, home: Path, windows: bool) -> list[str]:
    """Итог подключения — как в итоге установщика (спец. 5.3). «Подключены» — только там, куда
    скиллы действительно легли."""
    shared = show(str(expand(SHARED_DIR, home, windows)), home, windows)
    lines = []
    if result["linked"]:
        lines.append("Скиллы подключены:")
        width = max(len(item["title"]) for item in result["linked"]) + 2
        for item in result["linked"]:
            where = show(item["dir"], home, windows)
            if item["shared"]:
                where += " (общий каталог)"
            lines.append(f"  {item['title']:<{width}}{where}")
    elif result.get("shared_ok"):
        lines.append(f"Скиллы подключены: {shared} (общий каталог); харнессы не найдены")
    # Сбои с одной причиной — одной строкой; общий каталог — первым и всегда (спец. 5.3 п. 2).
    failures: dict[str, list[str]] = {}
    if result.get("shared_problem"):
        failures[result["shared_problem"]] = [f"общий каталог {shared}"]
    for item in result.get("failed", []):
        failures.setdefault(item["reason"], []).append(item["title"])
    lines.extend(f"Не подключено: {', '.join(who)} — {why}" for why, who in failures.items())
    if result["not_found"]:
        lines.append("Не найдены на этом компьютере: " + ", ".join(result["not_found"]))
    lines.extend(f"Ошибка: {error}" for error in result.get("errors", []))
    if result.get("skills") and (result["linked"] or result.get("shared_ok")):
        lines.append(
            f"Другой харнесс? Укажите ему каталог {shared} — см. «Ручное подключение» в README."
        )
        lines.append("Перезапустите харнесс, чтобы он увидел скиллы.")
    return lines


def table(rows: list[dict], home: Path, windows: bool) -> list[str]:
    head = ("Харнесс", "Найден", "Каталог", "Скиллы", "Версия набора")
    body = [
        (
            row["title"],
            "да" if row["found"] else "нет",
            show(row["dir"], home, windows) + (" (общий)" if row["shared"] else ""),
            "подключены" if row["linked"] else "нет",
            row["kit_version"] or "—",
        )
        for row in rows
    ]
    widths = [max(len(r[i]) for r in (head, *body)) for i in range(len(head))]
    return [
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(r)).rstrip() for r in (head, *body)
    ]


def _command(args) -> int:
    windows = os.name == "nt"
    home = Path.home()
    path_env = os.environ.get("PATH", "")
    kit_home = default_kit_home(home, windows)
    if args.link:
        result = link_all(home, path_env, windows, kit_home)
        if args.json:
            emit(result)
        elif not args.plain:
            print("\n".join(summary(result, home, windows)))
        if not args.plain:
            return EXIT_OK
    rows = status(home, path_env, windows, kit_home)
    if args.json:
        emit(rows)
    elif args.plain:
        for row in rows:
            flags = (int(row["found"]), row["dir"], int(row["reads_shared"]))
            print("{}\t{}\t{}\t{}".format(row["id"], *flags))
    else:
        print("\n".join(table(rows, home, windows)))
        print("Подключить скиллы найденным харнессам: albumum harnesses --link")
    return EXIT_OK


def register(sub) -> None:
    parser = sub.add_parser(
        "harnesses", help="харнессы на этом компьютере и подключение к ним скиллов набора"
    )
    parser.add_argument("--link", action="store_true", help="подключить скиллы найденным харнессам")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--plain",
        action="store_true",
        help="для установщика: id, найден (1/0), каталог, читает общий (1/0) через табуляцию",
    )
    mode.add_argument("--json", action="store_true", help="ответ в JSON")
    parser.set_defaults(handler=_command)
