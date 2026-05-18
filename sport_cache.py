#!/usr/bin/env python3
"""
Спортивный кэш: единый файловый кэш для ESPN и SStats.
Доступен из любого процесса (sport_bot.py, daily_results.py, upcoming.py).
"""

import json
import os
import time
from datetime import datetime, timedelta

CACHE_FILE = '/tmp/sport_cache.json'
CACHE_TTL = {
    'espn': 300,       # 5 минут
    'sstats': 300,     # 5 минут
    'myscore': 7200,   # 2 часа (Flashscore — Playwright тяжёлый)
    'flashscore': 7200, # 2 часа (VTB/Евролига — Playwright)
    'rss': 180,        # 3 минуты (новости)
}

DEFAULT_TTL = 300

def _load():
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _save(data):
    os.makedirs(os.path.dirname(CACHE_FILE) or '.', exist_ok=True)
    with open(CACHE_FILE, 'w') as f:
        json.dump(data, f)

def get(cache_type, key):
    """Вернуть кэшированные данные или None"""
    ttl = CACHE_TTL.get(cache_type, DEFAULT_TTL)
    cache = _load()
    entry = cache.get(f'{cache_type}:{key}')
    if entry and time.time() - entry['ts'] < ttl:
        return entry['data']
    return None

def set(cache_type, key, data):
    """Сохранить данные в кэш"""
    cache = _load()
    cache[f'{cache_type}:{key}'] = {'ts': time.time(), 'data': data}
    _save(cache)

def clear(cache_type=None):
    """Очистить кэш (для отладки)"""
    if cache_type is None:
        _save({})
    else:
        cache = _load()
        keys = [k for k in cache if k.startswith(f'{cache_type}:')]
        for k in keys:
            del cache[k]
        _save(cache)

def get_or_fetch(cache_type, key, fetch_fn, *args, **kwargs):
    """Кэш + fetch: если есть свежий кэш — отдаём, иначе вызываем fetch_fn и сохраняем"""
    cached = get(cache_type, key)
    if cached is not None:
        return cached, True  # (data, from_cache)
    data = fetch_fn(*args, **kwargs)
    if data is not None:
        set(cache_type, key, data)
    return data, False  # (data, from_cache)
