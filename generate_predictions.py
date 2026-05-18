#!/usr/bin/env python3
"""
Генератор прогнозов на матчи.
Читает /tmp/upcoming_matches.json (собран upcoming.py)
Фильтрует по prediction_leagues.json
Для каждого матча собирает коэффициенты через SStats API
Генерирует прогноз → predictions_data.json
"""

import json, os, sys, requests
from datetime import datetime

SSTATS_KEY = ''
try:
    with open('/etc/sstats.key') as f:
        SSTATS_KEY = f.read().strip()
except:
    pass

SSTATS = 'https://api.sstats.net'


# ─── Активные лиги для прогнозов ─────────────────────────────────────
def get_prediction_leagues():
    path = '/opt/prediction_leagues.json'
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return data.get('active', {})
    except:
        return {}


# ─── SStats API ──────────────────────────────────────────────────────
def fetch_game_data(game_id):
    """Собрать данные по матчу через SStats: инфо + коэффициенты."""
    result = {'game_id': game_id}

    try:
        r = requests.get(f'{SSTATS}/Games/list?apikey={SSTATS_KEY}&Id={game_id}', timeout=15)
        resp = r.json()
    except:
        return result

    # SStats: {'status': 'OK', 'count': 1, 'data': [...]}
    games = resp.get('data', []) if isinstance(resp, dict) else (resp if isinstance(resp, list) else [])
    if not games:
        return result

    game = games[0] if isinstance(games, list) else games
    if not game:
        return result

    result['home'] = game.get('homeTeam', {}).get('name', '?')
    result['away'] = game.get('awayTeam', {}).get('name', '?')
    result['date'] = game.get('date', '')

    # Коэффициенты: SStats возвращает [{marketId, marketName, odds: [{name, value}]}]
    odds_raw = game.get('odds', [])
    if isinstance(odds_raw, dict):
        odds_raw = list(odds_raw.values())
    elif not isinstance(odds_raw, list):
        odds_raw = []

    result['odds'] = []
    for market in odds_raw:
        if not isinstance(market, dict):
            continue
        market_odds = market.get('odds', [])
        if not isinstance(market_odds, list):
            continue
        # Ищем Home, Away, Draw в одном market
        vals = {}
        for o in market_odds:
            if isinstance(o, dict):
                name = str(o.get('name', '')).lower()
                val = o.get('value')
                if val is not None:
                    if name == 'home':
                        vals['home'] = float(val)
                    elif name in ('away', '2'):
                        vals['away'] = float(val)
                    elif name in ('draw', 'x'):
                        vals['draw'] = float(val)
        if len(vals) == 3:  # есть все три исхода
            result['odds'].append(vals)

    return result


# ─── Генерация прогноза ──────────────────────────────────────────────
def generate_prediction(data):
    """На основе коэффициентов сформировать прогноз."""
    odds = data.get('odds', [])
    if not odds:
        return None

    # Средние кэфы
    avg_home = sum(o['home'] for o in odds) / len(odds)
    avg_draw = sum(o['draw'] for o in odds) / len(odds)
    avg_away = sum(o['away'] for o in odds) / len(odds)

    # Вероятности (без маржи букмекера)
    margin = 1 / avg_home + 1 / avg_draw + 1 / avg_away
    prob_home = (1 / avg_home) / margin * 100
    prob_draw = (1 / avg_draw) / margin * 100
    prob_away = (1 / avg_away) / margin * 100

    # Кто фаворит?
    max_prob = max(prob_home, prob_draw, prob_away)
    if prob_home == max_prob:
        verdict = f'Победа {data["home"]}'
        confidence = 'высокая' if prob_home > 55 else ('средняя' if prob_home > 45 else 'низкая')
    elif prob_away == max_prob:
        verdict = f'Победа {data["away"]}'
        confidence = 'высокая' if prob_away > 55 else ('средняя' if prob_away > 45 else 'низкая')
    else:
        verdict = 'Ничья'
        confidence = 'средняя' if prob_draw > 30 else 'низкая'

    # Текст прогноза
    lines = []
    lines.append(f'💰 Коэффициенты ({len(odds)} букмекеров):')
    lines.append(f'   1: {avg_home:.2f} ({prob_home:.0f}%)')
    lines.append(f'   X: {avg_draw:.2f} ({prob_draw:.0f}%)')
    lines.append(f'   2: {avg_away:.2f} ({prob_away:.0f}%)')
    lines.append('')
    lines.append(f'🎯 {verdict}')
    lines.append(f'📊 Уверенность: {confidence}')

    return {
        'verdict': verdict,
        'analysis': '\n'.join(lines),
        'home': data['home'],
        'away': data['away'],
        'odds': {'home': round(avg_home, 2), 'draw': round(avg_draw, 2), 'away': round(avg_away, 2)},
        'confidence': confidence,
    }


# ─── MAIN ────────────────────────────────────────────────────────────
def main():
    upcoming_path = '/tmp/upcoming_matches.json'
    output_path = '/opt/predictions_data.json'

    if not os.path.exists(upcoming_path):
        print('❌ /tmp/upcoming_matches.json не найден. Сначала запусти upcoming.py')
        return

    with open(upcoming_path, encoding='utf-8') as f:
        upcoming = json.load(f)

    matches = upcoming.get('matches', [])
    if not matches:
        # Пустой результат
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump({'predictions': [], 'generated_at': datetime.now().isoformat()}, f, ensure_ascii=False)
        print('⚠️ Нет матчей для прогнозов')
        return

    pred_leagues = get_prediction_leagues()
    if not pred_leagues:
        print('⚠️ Нет активных лиг для прогнозов')
        return

    active_league_names = set(pred_leagues.keys())
    pred_matches = [m for m in matches if m.get('league') in active_league_names]
    print(f'📊 Матчей всего: {len(matches)}, для прогнозов: {len(pred_matches)}')

    predictions = []
    for m in pred_matches:
        gid = m.get('game_id')
        if not gid:
            continue
        print(f'  🔮 {m["home"]} — {m["away"]}...', end=' ')
        sys.stdout.flush()

        data = fetch_game_data(gid)
        if not data or not data.get('odds'):
            print('❌ нет коэффициентов')
            continue

        pred = generate_prediction(data)
        if pred:
            pred['game_id'] = gid
            pred['league'] = m['league']
            pred['time'] = m.get('time', '')
            pred['home'] = m['home']  # русское название из upcoming
            pred['away'] = m['away']
            pred['match_id'] = f'{m["league"]}:{m["home"]}—{m["away"]}'
            predictions.append(pred)
            print(f'✅ {pred["verdict"]}')
        else:
            print('⚠️ не удалось')

    output = {
        'predictions': predictions,
        'date': upcoming.get('date', ''),
        'generated_at': datetime.now().isoformat(),
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f'\n✅ Прогнозов: {len(predictions)} → {output_path}')


if __name__ == '__main__':
    main()
