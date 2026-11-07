"""Сравнение версий вида X.Y.Z (суффиксы -dev, -rc.N отбрасываются)."""

import re


def parse(version: str) -> tuple[int, ...]:
    numbers = re.match(r"\d+(?:\.\d+)*", version.removeprefix("v"))
    return tuple(int(part) for part in numbers.group().split(".")) if numbers else ()


RELEASE_RE = re.compile(r"\d+\.\d+\.\d+(-rc\.\d+)?")


def is_release(version: str) -> bool:
    """Номер выпуска X.Y.Z (или X.Y.Z-rc.N): по нему ставится набор и сверяются версии."""
    return bool(RELEASE_RE.fullmatch(version.removeprefix("v")))


def skipped(version: str) -> str:
    """Предупреждение о нечисловой версии системы (локальная сборка называет себя `local`)."""
    return f"Предупреждение: версия системы не числовая: {version} — сверка версий пропущена"


def is_older(version: str, other: str) -> bool:
    """version строго старше other; непонятный номер не считается старым."""
    a, b = parse(version), parse(other)
    size = max(len(a), len(b))
    a, b = a + (0,) * (size - len(a)), b + (0,) * (size - len(b))
    return bool(a and b and a < b)
