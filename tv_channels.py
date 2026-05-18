#!/usr/bin/env python3
"""
TV channels lookup for sports broadcasts.

Returns which channels broadcast a given league/event, prioritising
Russian channels first, then international.

All data is static mapping (broadcast rights change by season, not by match).

Usage:
    channels = get_broadcast('АПЛ')
    # → ['Sky Sports', 'TNT Sports']

    channels = tennis_broadcast('Wimbledon')
    # → ['Okko Спорт']
"""

import re
from datetime import datetime, timezone

UTC = timezone.utc

# ─── РОССИЙСКИЕ ВЕЩАТЕЛИ ПО ЛИГАМ (сезон 2025-2026) ───────────────
_RU_CHANNELS = {
    # Футбол
    'Ла Лига': ['Матч ТВ'],
    'Бундеслига': ['Okko Спорт'],
    'Лига 1': ['Okko Спорт'],
    'РПЛ': ['Матч ТВ', 'Матч! Футбол 1', 'Матч! Футбол 2'],
    'Лига Чемпионов': ['Okko Спорт'],
    'Лига Европы': ['Okko Спорт'],
    'Лига Конференций': ['Okko Спорт'],
    'Чемпионат Мира': ['Матч ТВ', 'Okko Спорт'],
    'Чемпионат Европы': ['Матч ТВ', 'Okko Спорт'],

    # Хоккей
    'КХЛ': ['Матч ТВ', 'КХЛ ТВ'],
    'ЧМ по хоккею': ['Матч ТВ'],

    # Баскетбол
    'Лига ВТБ': ['Матч ТВ', 'VK Видео'],
    'Euroleague': ['Матч ТВ', 'Okko Спорт'],
}

# Зарубежные вещатели для лиг без РФ-трансляций
_INTL_CHANNELS = {
    # Футбол (с 2022 нет официальных РФ-трансляций)
    'АПЛ': ['Sky Sports', 'TNT Sports'],
    'Серия А': ['DAZN', 'Sky Sport'],

    # Хоккей (с 2022 нет официальных РФ-трансляций)
    'НХЛ': ['ESPN', 'TNT', 'NHL Network'],

    # Баскетбол (с 2022 нет официальных РФ-трансляций)
    'NBA': ['ESPN', 'TNT', 'NBA TV'],
}

# Теннисные турниры
_RU_TENNIS = {
    'indian wells': ['Okko Спорт'],
    'miami': ['Okko Спорт'],
    'monte-carlo': ['Okko Спорт'],
    'madrid': ['Okko Спорт'],
    'internazionali': ['Okko Спорт'],
    'rome': ['Okko Спорт'],
    'canada': ['Okko Спорт'],
    'cincinnati': ['Okko Спорт'],
    'shanghai': ['Okko Спорт'],
    'paris masters': ['Okko Спорт'],
    'wuhan': ['Okko Спорт'],
    'beijing': ['Okko Спорт'],
    'australian open': ['Okko Спорт'],
    'roland garros': ['Okko Спорт'],
    'wimbledon': ['Okko Спорт'],
    'us open': ['Okko Спорт'],
}


def get_broadcast(league_name, match_data=None):
    """Получить каналы для матча. Приоритет: РФ -> зарубежные.
    Максимум 3 канала.

    Параметры:
        league_name: str - 'АПЛ', 'НХЛ', 'NBA', 'ЧМ по хоккею' и т.д.
        match_data: dict (опционально) - {'tournament': ...} для тенниса

    Возвращает:
        [str, ...] - от 0 до 3 каналов
    """
    result = []

    # 1. РФ-каналы
    if league_name in _RU_CHANNELS:
        result.extend(_RU_CHANNELS[league_name])

    # 2. Зарубежные (если РФ нет)
    if not result and league_name in _INTL_CHANNELS:
        result.extend(_INTL_CHANNELS[league_name])

    # 3. Теннис - по турниру
    if not result and match_data and 'tournament' in match_data:
        tn = match_data['tournament'].lower()
        for kw, channels in _RU_TENNIS.items():
            if kw in tn:
                result.extend(channels)
                break

    return result[:3]


def tennis_broadcast(tournament_name):
    """Каналы для теннисного турнира по названию."""
    return get_broadcast('Теннис', {'tournament': tournament_name})


# ─── ТЕСТ ───────────────────────────────────────────────────────────
if __name__ == '__main__':
    print('=== TV Channels ===')
    test = ['АПЛ', 'Ла Лига', 'Серия А', 'Бундеслига', 'Лига 1', 'РПЛ',
            'Лига Чемпионов', 'Лига Европы', 'Лига Конференций',
            'Чемпионат Мира', 'Чемпионат Европы',
            'НХЛ', 'КХЛ', 'ЧМ по хоккею',
            'NBA', 'Лига ВТБ', 'Euroleague']

    for league in test:
        ch = get_broadcast(league)
        if ch:
            icon = '🇷🇺' if league in _RU_CHANNELS else '🌍'
            print(f'  {icon} {league}: {" | ".join(ch)}')
        else:
            print(f'  ❌ {league}: нет данных')

    print()
    print('=== Теннис ===')
    for tn in ['Internazionali BNL', 'Australian Open', 'Wimbledon', 'Roland Garros']:
        ch = tennis_broadcast(tn)
        print(f'  🎾 {tn}: {" | ".join(ch) if ch else "нет"}')
