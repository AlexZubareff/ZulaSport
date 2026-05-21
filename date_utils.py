#!/usr/bin/env python3
"""
Единый модуль нормализации дат для пайплайна Zula Sport.

Поддерживаемые входные форматы:
  - dd.mm.yyyy   (например: 20.05.2026)
  - YYYY-MM-DD   (например: 2026-05-20)
  - YYYYmmdd     (например: 20260520)
  - dd.mm        (например: 20.05 — дополняется текущим годом)
  - datetime     (любой объект datetime)
  - int          (YYYYmmdd, например 20260520)
"""

import re
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
MOW = timedelta(hours=3)


# ─── Распознавание форматов ───────────────────────────────────────

_RE_DDMMYYYY = re.compile(r'^(\d{2})[.](\d{2})[.](\d{4})$')
_RE_YYYYMMDD_DASH = re.compile(r'^(\d{4})[-](\d{2})[-](\d{2})$')
_RE_YYYYMMDD = re.compile(r'^(\d{4})(\d{2})(\d{2})$')
_RE_DDMM = re.compile(r'^(\d{2})[.](\d{2})$')


def _parse(date_str) -> tuple[int, int, int]:
    """
    Распарсить дату из любого формата.
    Возвращает (year, month, day).
    """
    if date_str is None:
        raise ValueError(f'date_str is None')

    if isinstance(date_str, datetime):
        return (date_str.year, date_str.month, date_str.day)

    if isinstance(date_str, int):
        s = str(date_str)
        if len(s) == 8:
            m = _RE_YYYYMMDD.match(s)
            if m:
                y, mon, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                _validate_ymd(y, mon, d, str(date_str))
                return (y, mon, d)

    s = str(date_str).strip()

    # dd.mm.yyyy
    m = _RE_DDMMYYYY.match(s)
    if m:
        y, mon, d = int(m.group(3)), int(m.group(2)), int(m.group(1))
        _validate_ymd(y, mon, d, s)
        return (y, mon, d)

    # YYYY-MM-DD
    m = _RE_YYYYMMDD_DASH.match(s)
    if m:
        y, mon, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        _validate_ymd(y, mon, d, s)
        return (y, mon, d)

    # YYYYmmdd
    m = _RE_YYYYMMDD.match(s)
    if m:
        y, mon, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        _validate_ymd(y, mon, d, s)
        return (y, mon, d)

    # dd.mm (без года)
    m = _RE_DDMM.match(s)
    if m:
        now = datetime.now(UTC)
        y = now.year
        mon, d = int(m.group(2)), int(m.group(1))
        _validate_ymd(y, mon, d, s)
        return (y, mon, d)

    raise ValueError(f'Невозможно распарсить дату: {date_str!r}')


def _validate_ymd(year: int, month: int, day: int, raw: str):
    """Проверить, что год/месяц/день в допустимых пределах."""
    if not (1900 <= year <= 2200):
        raise ValueError(f'Год вне допустимого диапазона (1900-2200): {year} в {raw!r}')
    if not (1 <= month <= 12):
        raise ValueError(f'Месяц вне диапазона (1-12): {month} в {raw!r}')
    if not (1 <= day <= 31):
        raise ValueError(f'День вне диапазона (1-31): {day} в {raw!r}')
    # Дополнительная проверка через datetime (учёт количества дней в месяце)
    try:
        datetime(year, month, day)
    except ValueError as e:
        raise ValueError(f'Некорректная дата {raw!r}: {e}')


# ─── Основные функции ──────────────────────────────────────────────

def normalize_date(date_str) -> str:
    """Принимает любой формат, возвращает YYYYmmdd."""
    y, m, d = _parse(date_str)
    return f'{y:04d}{m:02d}{d:02d}'


def format_date_display(date_str) -> str:
    """Принимает любой формат, возвращает dd.mm.yyyy."""
    y, m, d = _parse(date_str)
    return f'{d:02d}.{m:02d}.{y:04d}'


def format_date_iso(date_str) -> str:
    """Принимает любой формат, возвращает YYYY-MM-DD."""
    y, m, d = _parse(date_str)
    return f'{y:04d}-{m:02d}-{d:02d}'


def format_date_storage(date_str) -> str:
    """Принимает любой формат, возвращает YYYYmmdd (алиас normalize_date)."""
    return normalize_date(date_str)


def today_storage() -> str:
    """Сегодня в формате YYYYmmdd (МСК)."""
    now = datetime.now(UTC) + MOW
    return now.strftime('%Y%m%d')


def today_display() -> str:
    """Сегодня в формате dd.mm.yyyy (МСК)."""
    now = datetime.now(UTC) + MOW
    return now.strftime('%d.%m.%Y')


def today_iso() -> str:
    """Сегодня в формате YYYY-MM-DD (МСК)."""
    now = datetime.now(UTC) + MOW
    return now.strftime('%Y-%m-%d')


def tomorrow_storage() -> str:
    """Завтра в формате YYYYmmdd (МСК)."""
    now = datetime.now(UTC) + MOW + timedelta(days=1)
    return now.strftime('%Y%m%d')


def tomorrow_display() -> str:
    """Завтра в формате dd.mm.yyyy (МСК)."""
    now = datetime.now(UTC) + MOW + timedelta(days=1)
    return now.strftime('%d.%m.%Y')


def tomorrow_iso() -> str:
    """Завтра в формате YYYY-MM-DD (МСК)."""
    now = datetime.now(UTC) + MOW + timedelta(days=1)
    return now.strftime('%Y-%m-%d')


def yesterday_storage() -> str:
    """Вчера в формате YYYYmmdd (МСК)."""
    now = datetime.now(UTC) + MOW - timedelta(days=1)
    return now.strftime('%Y%m%d')


def yesterday_iso() -> str:
    """Вчера в формате YYYY-MM-DD (МСК)."""
    now = datetime.now(UTC) + MOW - timedelta(days=1)
    return now.strftime('%Y-%m-%d')


def date_valid(date_str) -> bool:
    """Проверка, что дата корректна."""
    try:
        _parse(date_str)
        return True
    except (ValueError, TypeError):
        return False


# ─── Тесты ──────────────────────────────────────────────────────────

if __name__ == '__main__':
    # Тесты распознавания форматов
    assert normalize_date('20.05.2026') == '20260520'
    assert normalize_date('2026-05-20') == '20260520'
    assert normalize_date('20260520') == '20260520'
    assert normalize_date(20260520) == '20260520'

    assert format_date_display('20260520') == '20.05.2026'
    assert format_date_display('2026-05-20') == '20.05.2026'
    assert format_date_display('20.05.2026') == '20.05.2026'

    assert format_date_iso('20260520') == '2026-05-20'
    assert format_date_iso('20.05.2026') == '2026-05-20'
    assert format_date_iso('2026-05-20') == '2026-05-20'

    assert date_valid('20.05.2026') == True
    assert date_valid('2026-13-01') == False  # месяц > 12
    assert date_valid('not_a_date') == False
    assert date_valid(None) == False

    today = today_storage()
    assert len(today) == 8

    print('✅ Все тесты date_utils пройдены')
