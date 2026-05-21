#!/usr/bin/env python3
"""
Синхронизация daily_results_data.json → matches (БД).

Запуск: после daily_results.py (по крону).
Читает результаты из JSON и обновляет таблицу matches:
  - Находит матч по (league, home, away) на указанную дату
  - Если найден → обновляет score, status='finished'
  - Если не найден → создаёт новую запись
"""

import os, sys, json

sys.path.insert(0, '/opt')
from date_utils import normalize_date, format_date_iso, yesterday_iso
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/opt')

RESULTS_PATH = '/tmp/daily_results_data.json'

try:
    from db import save_match, execute, MOW
    HAS_DB = True
except:
    HAS_DB = False


def get_match_date(daily_date_str, now_msk, now_utc):
    """Определить дату матча. Приоритет: date из JSON → yesterday → today."""
    if daily_date_str:
        try:
            return format_date_iso(daily_date_str)
        except:
            pass
    # Если не указана — yesterday
    return yesterday_iso()


def sync():
    if not HAS_DB:
        print('  ❌ Нет подключения к БД')
        return 0
    
    if not os.path.exists(RESULTS_PATH):
        print(f'  ❌ {RESULTS_PATH} не найден')
        return 0
    
    with open(RESULTS_PATH, encoding='utf-8') as f:
        data = json.load(f)
    
    daily_date = data.get('date', '')
    results = data.get('results', [])
    
    now = datetime.now(timezone.utc)
    now_msk = now + timedelta(hours=3)
    
    updated = 0
    created = 0
    errors = 0
    
    for r in results:
        league = r.get('league', '')
        home = r.get('home', '')
        away = r.get('away', '')
        score = r.get('score', '')
        
        if not league or not home or not away or not score:
            continue
        
        # Определяем дату матча
        match_date = get_match_date(daily_date, now_msk, now)
        
        # Извлекаем время из результата, если есть
        match_time = r.get('time', '')
        
        try:
            # Пробуем найти существующий матч
            existing = execute(
                "SELECT id, status, score FROM matches WHERE league = %s AND home = %s AND away = %s AND match_date = %s",
                (league, home, away, match_date)
            )
            
            if existing:
                # Обновляем счёт и статус
                execute(
                    "UPDATE matches SET score = %s, status = 'finished', updated_at = NOW() WHERE id = %s",
                    (score, existing[0]['id'])
                )
                updated += 1
            else:
                # Создаём новый
                save_match({
                    'league': league,
                    'home': home,
                    'away': away,
                    'match_date': match_date,
                    'match_time': match_time,
                    'source': 'sstats',
                    'score': score,
                    'status': 'finished',
                    'channel': '', 'tournament': league,
                    'game_id': r.get('game_id'), 'espn_id': None,
                })
                created += 1
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f'  ⚠️ {league} {home}-{away}: {e}')
    
    print(f'  Обновлено: {updated}, создано: {created}, ошибок: {errors}')
    return updated + created


if __name__ == '__main__':
    sync()
