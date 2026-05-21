#!/usr/bin/env python3
"""
Миграция матчей из JSON-файлов в таблицу matches.
"""

import os, json, sys
sys.path.insert(0, '/opt')

from db import save_match, execute, get_conn
from datetime import datetime, timezone

TV_PATH = '/tmp/tv_channels_data.json'
RESULTS_PATH = '/tmp/daily_results_data.json'
LIVE_PATH = '/tmp/live_scores_data.json'


def migrate_matches():
    """Перенести матчи из TV, результатов и live в БД."""
    count = 0
    
    # 1. TV каналы (расписание)
    if os.path.exists(TV_PATH):
        try:
            with open(TV_PATH, encoding='utf-8') as f:
                data = json.load(f)
            by_date = data.get('matches_by_date', {})
            for date_str, matches in by_date.items():
                for m in matches:
                    if not isinstance(m, dict):
                        continue
                    try:
                        dt = datetime.strptime(date_str, '%Y%m%d').strftime('%Y-%m-%d')
                    except:
                        dt = date_str
                    save_match({
                        'league': m.get('league', m.get('sport', '?')),
                        'home': m.get('home', '?'),
                        'away': m.get('away', '?'),
                        'match_date': dt,
                        'match_time': m.get('time', ''),
                        'source': 'tv',
                        'channel': m.get('channel', ''),
                        'tournament': m.get('tournament', ''),
                        'status': 'scheduled',
                        'score': None,
                        'game_id': None, 'espn_id': None,
                    })
                    count += 1
        except Exception as e:
            print(f'  ❌ TV: {e}')
    
    # 2. Daily results
    if os.path.exists(RESULTS_PATH):
        try:
            with open(RESULTS_PATH, encoding='utf-8') as f:
                data = json.load(f)
            for r in data.get('results', []):
                if not isinstance(r, dict):
                    continue
                # Дата из файла (если есть) или сегодня
                mtime = os.path.getmtime(RESULTS_PATH)
                dt = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')
                save_match({
                    'league': r.get('league', ''),
                    'home': r.get('home', ''),
                    'away': r.get('away', ''),
                    'match_date': r.get('date', dt),
                    'match_time': r.get('time', ''),
                    'source': 'sstats',
                    'channel': '', 'tournament': '',
                    'status': 'finished',
                    'score': r.get('score', ''),
                    'game_id': r.get('game_id'), 'espn_id': None,
                })
                count += 1
        except Exception as e:
            print(f'  ❌ Results: {e}')
    
    print(f'✅ Матчей в БД: {count}')
    
    # Вывести статистику
    statuses = execute("SELECT status, COUNT(*) AS c FROM matches GROUP BY status ORDER BY status")
    for s in statuses:
        print(f'   {s["status"]}: {s["c"]}')
    
    # По датам
    dates = execute("SELECT match_date, COUNT(*) AS c FROM matches GROUP BY match_date ORDER BY match_date DESC LIMIT 5")
    if dates:
        print(f'   Последние даты:')
        for d in dates:
            print(f'     {d["match_date"]}: {d["c"]} матчей')


if __name__ == '__main__':
    migrate_matches()
