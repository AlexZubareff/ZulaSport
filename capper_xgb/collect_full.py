#!/usr/bin/env python3
"""
Сбор исторических данных из SStats — полная версия.
Сохраняет инкрементально (не теряем прогресс при таймаутах).
"""

import os, sys, json, time, requests
from collections import Counter

SSTATS_KEY = ''
try:
    with open('/etc/sstats.key') as f:
        SSTATS_KEY = f.read().strip()
except:
    print('❌ Нет /etc/sstats.key')
    sys.exit(1)

SSTATS = 'https://api.sstats.net'
DATASET_PATH = '/opt/capper_xgb/dataset.json'

LEAGUES = {'rpl': 235, 'epl': 39, 'laliga': 140, 'seriea': 135, 'bundesliga': 78, 'ligue1': 61}
LEAGUE_NAMES = {235: 'РПЛ', 39: 'АПЛ', 140: 'Ла Лига', 135: 'Серия А', 78: 'Бундеслига', 61: 'Лига 1'}

def sq(endpoint, params=None, retries=3):
    """Запрос к SStats API.
    Возвращает data (список) для Games/list, полный ответ для glicko."""
    p = {'apikey': SSTATS_KEY}
    if params: p.update(params)
    for _ in range(retries):
        try:
            r = requests.get(f'{SSTATS}{endpoint}', params=p, timeout=30)
            d = r.json()
            if isinstance(d, dict) and d.get('status') == 'OK':
                return d.get('data', [])
            return d
        except:
            time.sleep(1)
    return None

def sq_raw(endpoint, params=None, retries=3):
    """Как sq, но без извлечения data — полный ответ."""
    p = {'apikey': SSTATS_KEY}
    if params: p.update(params)
    for _ in range(retries):
        try:
            r = requests.get(f'{SSTATS}{endpoint}', params=p, timeout=30)
            return r.json()
        except:
            time.sleep(1)
    return None

def process_game(game, league_id):
    """Возвращает фичи для одной игры или None."""
    gid = game.get('id')
    if not gid or game.get('statusName') != 'Finished':
        return None
    hr = game.get('homeResult')
    ar = game.get('awayResult')
    if hr is None or ar is None:
        return None

    home_name = game.get('homeTeam', {}).get('name', '?')
    away_name = game.get('awayTeam', {}).get('name', '?')
    date_str = game.get('date', '')[:10]

    # Кэфы
    odds_raw = game.get('odds', []) or []
    if isinstance(odds_raw, dict): odds_raw = list(odds_raw.values())
    odds, totals = None, {}
    for market in odds_raw:
        if not isinstance(market, dict): continue
        mo = market.get('odds', []) or []
        vals = {}
        for o in mo:
            n = str(o.get('name', '')).lower()
            v = o.get('value')
            if v is None: continue
            v = float(v)
            if n == 'home': vals['home'] = v
            elif n == 'away': vals['away'] = v
            elif n == 'draw': vals['draw'] = v
            elif n.startswith('over'):
                vals['over'] = v
                import re
                m = re.search(r'[\d.]+', o.get('name', ''))
                if m: vals['total_line'] = float(m.group())
                vals['type'] = 'total'
            elif n.startswith('under'):
                vals['under'] = v
                vals['type'] = 'total'
        if vals.get('type') == 'total' and 'over' in vals and 'under' in vals:
            tl = vals.get('total_line', 0)
            if tl in (2.5, 3.5) or not totals:
                totals = {'total_line': tl, 'over': vals['over'], 'under': vals['under']}
        elif len(vals) == 3 and 'home' in vals and 'away' in vals and 'draw' in vals:
            if odds is None: odds = vals

    # Glicko
    glicko = None
    resp = sq_raw('/Games/glicko/' + str(gid))
    if isinstance(resp, dict):
        gd = resp.get('data', {})
        if isinstance(gd, dict):
            g = gd.get('glicko', {})
            if isinstance(g, dict) and g.get('homeWinProbability'):
                hp = g['homeWinProbability']
                ap = g['awayWinProbability']
                glicko = {
                    'home_prob': hp, 'away_prob': ap,
                    'draw_prob': max(0, 1.0 - hp - ap),
                    'home_rating': g.get('homeRating', 0),
                    'away_rating': g.get('awayRating', 0),
                    'home_xg': g.get('homeXg', 0), 'away_xg': g.get('awayXg', 0),
                }

    if not odds and not glicko:
        return None

    total_line = totals.get('total_line', 2.5)
    total_goals = hr + ar
    return {
        'game_id': gid, 'league_id': league_id,
        'league_name': LEAGUE_NAMES.get(league_id, str(league_id)),
        'home': home_name, 'away': away_name, 'date': date_str, 'score': f'{hr}:{ar}',
        'actual_winner': 'home' if hr > ar else 'away' if ar > hr else 'draw',
        'actual_total': 'over' if total_goals > total_line else 'under',
        'total_line': total_line,
        'glicko_home_prob': glicko['home_prob'] if glicko else None,
        'glicko_draw_prob': glicko['draw_prob'] if glicko else None,
        'glicko_away_prob': glicko['away_prob'] if glicko else None,
        'glicko_home_rating': glicko['home_rating'] if glicko else None,
        'glicko_away_rating': glicko['away_rating'] if glicko else None,
        'glicko_home_xg': glicko['home_xg'] if glicko else None,
        'glicko_away_xg': glicko['away_xg'] if glicko else None,
        'odds_home': odds['home'] if odds else None,
        'odds_draw': odds['draw'] if odds else None,
        'odds_away': odds['away'] if odds else None,
        'odds_over': totals.get('over'), 'odds_under': totals.get('under'),
    }

# Загружаем существующий датасет (чтобы не потерять прогресс)
all_games = []
existing_ids = set()
if os.path.exists(DATASET_PATH):
    try:
        with open(DATASET_PATH) as f:
            old = json.load(f)
        for g in old.get('games', []):
            gid = g.get('game_id')
            if gid and gid not in existing_ids:
                existing_ids.add(gid)
                all_games.append(g)
        print(f'📂 Загружено {len(all_games)} существующих записей')
    except: pass

total_seen = 0
total_ok = 0

for league_key, league_id in LEAGUES.items():
    print(f'📡 {league_key.upper()} (id={league_id})... ', end='', flush=True)
    games = sq('/Games/list', {'LeagueId': league_id, 'Year': 2025, 'take': 500})
    if not games or not isinstance(games, list):
        print(f'❌ пустой ответ')
        continue

    finished = [g for g in games if isinstance(g, dict) and g.get('statusName') == 'Finished']
    print(f'{len(finished)} finished', flush=True)

    for i, g in enumerate(finished):
        gid = g.get('id')
        if gid in existing_ids:
            continue  # уже есть
        total_seen += 1
        row = process_game(g, league_id)
        if row:
            total_ok += 1
            all_games.append(row)
            existing_ids.add(gid)

        # Сохраняем каждые 30 игр
        if total_ok > 0 and total_ok % 30 == 0:
            data = {'collected_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                    'total_games': total_seen, 'total_with_data': total_ok, 'games': all_games}
            with open(DATASET_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    time.sleep(0.3)

# Финальное сохранение
data = {'collected_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'total_games': total_seen, 'total_with_data': total_ok, 'games': all_games}
with open(DATASET_PATH, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

# CSV
fields = ['game_id','league_name','home','away','date','score','actual_winner','actual_total','total_line',
          'glicko_home_prob','glicko_draw_prob','glicko_away_prob','glicko_home_rating','glicko_away_rating',
          'glicko_home_xg','glicko_away_xg','odds_home','odds_draw','odds_away','odds_over','odds_under']
csv_path = '/opt/capper_xgb/dataset.csv'
with open(csv_path, 'w', encoding='utf-8') as f:
    f.write(','.join(fields) + '\n')
    for row in all_games:
        f.write(','.join(str(row.get(f, '')) for f in fields) + '\n')

print(f'\n✅ Итого: {total_ok} новых, {len(all_games)} всего')
leagues = Counter(r['league_name'] for r in all_games)
for l, c in sorted(leagues.items(), key=lambda x: -x[1]):
    glicko_count = sum(1 for r in all_games if r['league_name'] == l and r['glicko_home_prob'] is not None)
    odds_count = sum(1 for r in all_games if r['league_name'] == l and r['odds_home'] is not None)
    print(f'  {l}: {c} (Glicko: {glicko_count}, кэфы: {odds_count})')
