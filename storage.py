#!/usr/bin/env python3
"""
Хранилище матчей по датам (накопительно).

Формат файла:
{
  "matches_by_date": {
    "20260519": [{match}, ...],
    "20260520": [{match}, ...]
  },
  "updated_at": "2026-05-19T00:00:00"
}
"""

import os, json
from datetime import datetime, timezone, timedelta

UTC = timezone.utc
MOW = timedelta(hours=3)
MAX_DAYS = 3  # сегодня + вчера + завтра


def load_by_date(path):
    """Загрузить матчи по датам. Вернёт dict {date_str: [matches]}."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return data.get('matches_by_date', {})
    except:
        return {}


def save_by_date(path, matches_by_date):
    """Сохранить матчи по датам, удалив записи старше MAX_DAYS дней."""
    now = datetime.now(UTC) + MOW
    cutoff = (now - timedelta(days=MAX_DAYS)).strftime('%Y%m%d')
    cleaned = {k: v for k, v in matches_by_date.items() if k >= cutoff}

    with open(path, 'w', encoding='utf-8') as f:
        json.dump({
            'matches_by_date': cleaned,
            'updated_at': datetime.now(UTC).isoformat(),
        }, f, ensure_ascii=False, indent=2)


def add_date(path, date_str, matches):
    """Добавить/обновить матчи для одной даты, не трогая остальные."""
    by_date = load_by_date(path)
    if matches:
        by_date[date_str] = matches
    else:
        by_date.pop(date_str, None)
    save_by_date(path, by_date)


def get_matches_for_date(path, target_date):
    """Вернуть список матчей для target_date (строки 'dd.mm.yyyy' или 'YYYYmmdd')."""
    # Нормализуем формат
    target = target_date.replace('.', '')
    if len(target) == 8 and '.' not in target_date:
        pass  # уже YYYYmmdd
    elif len(target) == 8:
        # dd.mm.yyyy → YYYYmmdd
        target = target[4:] + target[2:4] + target[:2]

    by_date = load_by_date(path)
    return by_date.get(target, [])


def convert_old_to_new(old_data, date_str):
    """Преобразовать старый формат {date, matches} в новый {date_str: [matches]}."""
    matches = old_data.get('matches', [])
    if matches and date_str:
        return {date_str: matches}
    return {}
