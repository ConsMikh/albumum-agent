"""Сравнение версий вида X.Y.Z (суффиксы -dev, -rc.N отбрасываются)."""

import re


def parse(version: str) -> tuple[int, ...]:
    numbers = re.match(r"\d+(?:\.\d+)*", version.removeprefix("v"))
    return tuple(int(part) for part in numbers.group().split(".")) if numbers else ()


def is_older(version: str, other: str) -> bool:
    """version строго старше other; непонятный номер не считается старым."""
    a, b = parse(version), parse(other)
    size = max(len(a), len(b))
    a, b = a + (0,) * (size - len(a)), b + (0,) * (size - len(b))
    return bool(a and b and a < b)
