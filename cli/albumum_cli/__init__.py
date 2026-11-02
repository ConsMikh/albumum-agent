"""Утилита albumum — агентский интерфейс Albumum."""

# Версия набора: сборка зеркала подставляет сюда версию выпуска (scripts/build_agent_mirror.py);
# в разработке — следующая версия с -dev.
__version__ = "0.1.0"

# Версия контракта /api/system/version.agent_contract, которую понимает утилита.
# 0 — операций ещё нет; S4 поднимет до 1.
SUPPORTED_CONTRACT = 0
