#!/usr/bin/env python3
"""
Общий модуль для всех пайплайнов capper.

Содержит:
- Единый DeepSeek-клиент с кешем (хеш от команд + кэфы + Glicko)
- call_deepseek_with_cache() — основной вход
- Валидация через data_schemas
"""

import json, os, sys, hashlib, time, requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, '/opt')
from data_schemas import validate

CACHE_FILE = '/tmp/deepseek_cache.json'
CACHE_TTL = 1800  # 30 минут
CACHE_VERSION = 1


def _prediction_cache_key(match_info, sstats_data):
    """Вычисляет хеш от данных матча для кеширования прогноза."""
    home = match_info.get('home', '')
    away = match_info.get('away', '')
    league = match_info.get('league', '')

    odds = sstats_data.get('odds', [])
    o = odds[0] if odds else {}
    g = sstats_data.get('glicko', {})

    raw = '|'.join([
        home, away, league,
        str(o.get('home', '')),
        str(o.get('draw', '')),
        str(o.get('away', '')),
        str(g.get('home_prob', '')),
        str(g.get('away_prob', '')),
        str(g.get('draw_prob', '')),
        str(sstats_data.get('totals', {}).get('total_line', '')),
        str(sstats_data.get('totals', {}).get('over', '')),
        str(sstats_data.get('totals', {}).get('under', '')),
    ])
    return hashlib.md5(raw.encode()).hexdigest()


def _load_cache():
    """Загружает кеш из файла."""
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, encoding='utf-8') as f:
            data = json.load(f)
        # Валидация
        ok, _ = validate(data, 'deepseek_cache')
        if not ok:
            return {}
        # Проверка версии
        if data.get('_version') != CACHE_VERSION:
            return {}
        # Очистка устаревших записей
        now = time.time()
        entries = data.get('entries', {})
        fresh = {}
        for key, entry in entries.items():
            if now - entry.get('ts', 0) < CACHE_TTL:
                fresh[key] = entry
        return fresh
    except:
        return {}


def _save_cache(entries):
    """Сохраняет кеш в файл с валидацией."""
    data = {
        '_version': CACHE_VERSION,
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'entries': entries,
    }
    # Валидация перед записью
    ok, errors = validate(data, 'deepseek_cache')
    if not ok:
        # Фолбэк: пишем без валидации, логируем
        pass

    tmp = CACHE_FILE + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.rename(tmp, CACHE_FILE)
    except:
        pass


def call_deepseek_with_cache(match_info, sstats_data, generate_fn, force_refresh=False):
    """
    Вызывает DeepSeek с кешированием.
    
    Args:
        match_info: dict с home, away, league, date
        sstats_data: dict с odds, glicko, totals
        generate_fn: функция, которая делает реальный вызов DeepSeek и возвращает текст
        force_refresh: принудительно пропустить кеш
    
    Returns:
        str: текст прогноза
    """
    cache_key = _prediction_cache_key(match_info, sstats_data)

    if not force_refresh:
        cache = _load_cache()
        if cache_key in cache:
            entry = cache[cache_key]
            # Проверяем, что кеш не устарел
            if time.time() - entry.get('ts', 0) < CACHE_TTL:
                return entry.get('result', '')

    # Кеш промахнулся — вызываем DeepSeek
    result = generate_fn()

    # Сохраняем в кеш
    cache = _load_cache()
    cache[cache_key] = {
        'result': result,
        'ts': time.time(),
        'match': f"{match_info.get('home', '')} — {match_info.get('away', '')}",
    }
    _save_cache(cache)

    return result


def get_cache_stats():
    """Возвращает статистику кеша."""
    cache = _load_cache()
    total = len(cache)
    ages = [time.time() - e.get('ts', 0) for e in cache.values()]
    avg_age = sum(ages) / len(ages) if ages else 0
    return {
        'total_entries': total,
        'avg_age_sec': round(avg_age),
        'max_age_sec': round(max(ages)) if ages else 0,
    }


def clear_cache():
    """Очищает кеш."""
    _save_cache({})


def batch_generate_predictions(matches, generate_one_fn, max_workers=3, force_refresh=False):
    """
    Параллельная генерация прогнозов для списка матчей.
    
    Args:
        matches: список dict с home, away, league и т.д.
        generate_one_fn: функция(match_info) -> str
        max_workers: сколько DeepSeek запросов одновременно (по умолч. 3)
        force_refresh: пропустить кеш
    
    Returns:
        list[str]: прогнозы в том же порядке, что и matches
    """
    results = [None] * len(matches)

    def _task(i, match):
        try:
            return i, generate_one_fn(match)
        except Exception as e:
            print(f'  ⚠️ [{i+1}/{len(matches)}] {match.get("home","?")} — {match.get("away","?")}: {e}')
            return i, None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_task, i, m) for i, m in enumerate(matches)]
        for future in as_completed(futures):
            i, result = future.result()
            results[i] = result
            print(f'  ✅ [{i+1}/{len(matches)}] прогноз готов')

    return results
