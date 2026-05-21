#!/usr/bin/env python3
"""
Сбор исторических данных из SStats для обучения XGBoost.

Фичи: Glicko home/away/draw prob, Glicko рейтинги, xG, кэфы.
Таргеты: actual_winner (home/draw/away), actual_total (over/under).

Сохраняет: /opt/capper_xgb/dataset.csv и /opt/capper_xgb/dataset.json
"""

import os, sys, json, time, requests
from datetime import datetime, timezone

# ─── Пути ───────────────────────────────────────────────────────────
SSTATS_KEY = ''
try:
    with open('/etc/sstats.key') as f:
        SSTATS_KEY = f.read().strip()
except:
    print('❌ Нет /etc/sstats.key')
    sys.exit(1)

SSTATS = 'https://api.sstats.net'
OUT_DIR = '/opt/capper_xgb'
os.makedirs(OUT_DIR, exist_ok=True)

# БД
try:
    sys.path.insert(0, '/opt')
    import db
    _DB_AVAILABLE = True
except:
    _DB_AVAILABLE = False

# Лиги, которые мы капперим
LEAGUES = {
    'rpl': 235,
    'epl': 39,
    'laliga': 140,
    'seriea': 135,
    'bundesliga': 78,
    'ligue1': 61,
}

LEAGUE_NAMES = {
    235: 'РПЛ',
    39: 'АПЛ',
    140: 'Ла Лига',
    135: 'Серия А',
    78: 'Бундеслига',
    61: 'Лига 1',
}

# ─── API хелпер ─────────────────────────────────────────────────────

def sq(endpoint, params=None, retries=3):
    p = {'apikey': SSTATS_KEY}
    if params: p.update(params)
    for attempt in range(retries):
        try:
            r = requests.get(f'{SSTATS}{endpoint}', params=p, timeout=20)
            d = r.json()
            if isinstance(d, dict) and d.get('status') == 'OK':
                return d.get('data', [])
            return d
        except:
            if attempt < retries - 1:
                time.sleep(1)
    return None


def sq_raw(endpoint, params=None, retries=3):
    """Как sq(), но возвращает полный ответ, а не data."""
    p = {'apikey': SSTATS_KEY}
    if params: p.update(params)
    for attempt in range(retries):
        try:
            r = requests.get(f'{SSTATS}{endpoint}', params=p, timeout=20)
            return r.json()
        except:
            if attempt < retries - 1:
                time.sleep(1)
    return None


# ─── Сбор данных по одной игре ─────────────────────────────────────

def collect_game_data(game, league_id=None):
    """Собирает фичи для одной finished игры.
    Возвращает dict с фичами и таргетами или None."""
    game_id = game.get('id')
    if not game_id:
        return None

    # Статус
    status = game.get('statusName', '')
    if status not in ('Finished',):
        return None

    home_result = game.get('homeResult')
    away_result = game.get('awayResult')
    if home_result is None or away_result is None:
        return None

    if league_id is None:
        league_id = game.get('leagueId')
    home_name = game.get('homeTeam', {}).get('name', '?')
    away_name = game.get('awayTeam', {}).get('name', '?')
    date_str = game.get('date', '')[:10]

    # Берём кэфы из того же запроса — они уже есть в game['odds']
    odds_raw = game.get('odds', [])
    if isinstance(odds_raw, dict):
        odds_raw = list(odds_raw.values())

    odds = None
    totals = {}
    for market in (odds_raw if isinstance(odds_raw, list) else []):
        if not isinstance(market, dict): continue
        mo = market.get('odds', [])
        if not isinstance(mo, list): continue
        vals = {}
        for o in mo:
            n = str(o.get('name', '')).lower()
            v = o.get('value')
            if v is None: continue
            if n == 'home': vals['home'] = float(v)
            elif n == 'away': vals['away'] = float(v)
            elif n == 'draw': vals['draw'] = float(v)
            elif n.startswith('over'):
                vals['over'] = float(v)
                import re
                m = re.search(r'[\d.]+', o.get('name', ''))
                if m: vals['total_line'] = float(m.group())
                vals['type'] = 'total'
            elif n.startswith('under'):
                vals['under'] = float(v)
                vals['type'] = 'total'
        if 'type' in vals and 'over' in vals and 'under' in vals:
            tl = vals.get('total_line', 0)
            if tl in (2.5, 3.5) or not totals:
                totals = {'total_line': tl, 'over': vals['over'], 'under': vals['under']}
        elif len(vals) == 3 and 'home' in vals and 'away' in vals and 'draw' in vals:
            if odds is None:
                odds = {'home': vals['home'], 'draw': vals['draw'], 'away': vals['away']}

    # Glicko (отдельный запрос)
    glicko = None
    gl_raw = sq_raw('/Games/glicko/' + str(game_id))
    if isinstance(gl_raw, dict):
        gd = gl_raw.get('data', {})
        if isinstance(gd, dict):
            g = gd.get('glicko', {})
        else:
            g = gl_raw.get('glicko', {})
        if isinstance(g, dict) and g.get('homeWinProbability'):
            home_prob = g['homeWinProbability']
            away_prob = g['awayWinProbability']
            draw_prob = max(0, 1.0 - home_prob - away_prob)
            glicko = {
                'home_prob': home_prob,
                'away_prob': away_prob,
                'draw_prob': draw_prob,
                'home_rating': g.get('homeRating', 0),
                'away_rating': g.get('awayRating', 0),
                'home_xg': g.get('homeXg', 0),
                'away_xg': g.get('awayXg', 0),
            }

    if not odds and not glicko:
        return None  # бесполезно — нет ни кэфов, ни Glicko

    # Таргеты
    if home_result > away_result:
        actual_winner = 'home'
    elif away_result > home_result:
        actual_winner = 'away'
    else:
        actual_winner = 'draw'

    actual_total = 'over' if (home_result + away_result) > (totals.get('total_line', 2.5)) else 'under'
    total_line = totals.get('total_line', 2.5)

    return {
        'game_id': game_id,
        'league_id': league_id,
        'league_name': LEAGUE_NAMES.get(league_id, str(league_id)),
        'home': home_name,
        'away': away_name,
        'date': date_str,
        'score': f'{home_result}:{away_result}',
        'actual_winner': actual_winner,
        'actual_total': actual_total,
        'total_line': total_line,
        # Features
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
        'odds_over': totals.get('over'),
        'odds_under': totals.get('under'),
    }


# ═══════════════════ Основной сбор ═══════════════════════════════════

def collect_all():
    all_games = []
    total_games = 0
    total_with_data = 0

    for league_key, league_id in LEAGUES.items():
        print(f'📡 {league_key.upper()} (id={league_id})... ', end='', flush=True)
        games = sq('/Games/list', {'LeagueId': league_id, 'Year': 2025, 'take': 500})
        if not games:
            print('❌ нет данных')
            continue

        finished = [g for g in games if isinstance(g, dict) and g.get('statusName') == 'Finished']
        print(f'{len(finished)} finished из {len(games)}', flush=True)

        for i, g in enumerate(finished):
            total_games += 1
            row = collect_game_data(g, league_id=league_id)
            if row:
                total_with_data += 1
                all_games.append(row)

            # Прогресс каждые 50 игр
            if (i + 1) % 50 == 0:
                print(f'    {i+1}/{len(finished)}... ', end='', flush=True)

        # Задержка между лигами
        time.sleep(0.5)

    # Сохраняем
    out_path = os.path.join(OUT_DIR, 'dataset.json')
    data = {
        'collected_at': datetime.now(timezone.utc).isoformat(),
        'total_games': total_games,
        'total_with_data': total_with_data,
        'games': all_games,
    }
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f'\n✅ Сохранено: {out_path}')
    print(f'   Всего игр: {total_games}')
    print(f'   С данными: {total_with_data} ({total_with_data/max(total_games,1)*100:.1f}%)')

    # Статистика по лигам
    from collections import Counter
    leagues = Counter(r['league_name'] for r in all_games)
    print(f'\n📊 По лигам:')
    for league, count in sorted(leagues.items(), key=lambda x: -x[1]):
        print(f'  {league}: {count}')

    # Сохраняем CSV для удобства
    csv_path = os.path.join(OUT_DIR, 'dataset.csv')
    fields = [
        'game_id', 'league_name', 'home', 'away', 'date', 'score',
        'actual_winner', 'actual_total', 'total_line',
        'glicko_home_prob', 'glicko_draw_prob', 'glicko_away_prob',
        'glicko_home_rating', 'glicko_away_rating',
        'glicko_home_xg', 'glicko_away_xg',
        'odds_home', 'odds_draw', 'odds_away',
        'odds_over', 'odds_under',
    ]
    with open(csv_path, 'w', encoding='utf-8') as f:
        f.write(','.join(fields) + '\n')
        for row in all_games:
            vals = [str(row.get(f, '')) for f in fields]
            f.write(','.join(vals) + '\n')
    print(f'✅ CSV: {csv_path}')

    # БД
    if _DB_AVAILABLE:
        saved = 0
        for row in all_games:
            sample = {
                'source': 'sstats',
                'league': row.get('league_name', ''),
                'home': row.get('home', ''),
                'away': row.get('away', ''),
                'match_date': (row.get('date') or '')[:10],
                'score': row.get('score', ''),
                'actual_winner': row.get('actual_winner', ''),
                'actual_total': row.get('actual_total', ''),
                'total_line': row.get('total_line', 2.5),
                'glicko_home_prob': row.get('glicko_home_prob'),
                'glicko_draw_prob': row.get('glicko_draw_prob'),
                'glicko_away_prob': row.get('glicko_away_prob'),
                'glicko_home_rating': row.get('glicko_home_rating'),
                'glicko_away_rating': row.get('glicko_away_rating'),
                'glicko_home_xg': row.get('glicko_home_xg'),
                'glicko_away_xg': row.get('glicko_away_xg'),
                'odds_home': row.get('odds_home'),
                'odds_draw': row.get('odds_draw'),
                'odds_away': row.get('odds_away'),
                'odds_over': row.get('odds_over'),
                'odds_under': row.get('odds_under'),
            }
            try:
                db.save_training_sample(sample)
                saved += 1
            except:
                pass
        print(f'✅ БД: {saved} сэмплов')


if __name__ == '__main__':
    collect_all()
