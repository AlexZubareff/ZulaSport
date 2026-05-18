#!/usr/bin/env python3
"""
NHL API — бесплатно, без ключа.
Документация: https://api-web.nhle.com/
"""

import requests
from datetime import datetime, timezone, timedelta

MOW = timedelta(hours=3)

# ─── ПЕРЕВОД НАЗВАНИЙ КОМАНД ───────────────────────────────────────

NHL_TEAMS_RU = {
    'Anaheim Ducks': 'Анахайм Дакс',
    'Arizona Coyotes': 'Аризона Койотис',
    'Boston Bruins': 'Бостон Брюинз',
    'Buffalo Sabres': 'Баффало Сейбрз',
    'Calgary Flames': 'Калгари Флэймз',
    'Carolina Hurricanes': 'Каролина Харрикейнз',
    'Chicago Blackhawks': 'Чикаго Блэкхокс',
    'Colorado Avalanche': 'Колорадо Эвеланш',
    'Columbus Blue Jackets': 'Коламбус Блю Джекетс',
    'Dallas Stars': 'Даллас Старз',
    'Detroit Red Wings': 'Детройт Ред Уингз',
    'Edmonton Oilers': 'Эдмонтон Ойлерз',
    'Florida Panthers': 'Флорида Пантерз',
    'Los Angeles Kings': 'Лос-Анджелес Кингз',
    'Minnesota Wild': 'Миннесота Уайлд',
    'Montreal Canadiens': 'Монреаль Канадиенс',
    'Montréal Canadiens': 'Монреаль Канадиенс',
    'Nashville Predators': 'Нэшвилл Предаторз',
    'New Jersey Devils': 'Нью-Джерси Девилз',
    'New York Islanders': 'Нью-Йорк Айлендерс',
    'New York Rangers': 'Нью-Йорк Рейнджерс',
    'Ottawa Senators': 'Оттава Сенаторз',
    'Philadelphia Flyers': 'Филадельфия Флайерз',
    'Pittsburgh Penguins': 'Питтсбург Пингвинз',
    'San Jose Sharks': 'Сан-Хосе Шаркс',
    'Seattle Kraken': 'Сиэтл Кракен',
    'St. Louis Blues': 'Сент-Луис Блюз',
    'Tampa Bay Lightning': 'Тампа-Бэй Лайтнинг',
    'Toronto Maple Leafs': 'Торонто Мэйпл Лифс',
    'Utah Hockey Club': 'Юта',
    'Vancouver Canucks': 'Ванкувер Кэнакс',
    'Vegas Golden Knights': 'Вегас Голден Найтс',
    'Washington Capitals': 'Вашингтон Кэпиталз',
    'Winnipeg Jets': 'Виннипег Джетс',
}


def ru(name):
    if name in NHL_TEAMS_RU:
        return NHL_TEAMS_RU[name]
    for eng, rus in NHL_TEAMS_RU.items():
        if eng.lower() in name.lower() or name.lower() in eng.lower():
            return rus
    return name


def fetch_nhl_results(date_str):
    """Завершённые матчи НХЛ за дату (YYYYMMDD)."""
    date_iso = f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}'
    url = f'https://api-web.nhle.com/v1/scoreboard/{date_iso}'
    try:
        resp = requests.get(url, timeout=15)
        data = resp.json()
    except:
        return []

    matches = []
    finished_states = {'OFF', 'FINAL'}

    for gbd in data.get('gamesByDate', []):
        # Только матчи за запрошенную дату
        if gbd.get('date') != date_iso:
            continue
        for g in gbd.get('games', []):
            if g.get('gameState') not in finished_states:
                continue

            ht = g.get('homeTeam', {})
            at = g.get('awayTeam', {})
            home_score = ht.get('score', 0)
            away_score = at.get('score', 0)

            if home_score is None or away_score is None:
                continue

            matches.append({
                'home': ru(ht.get('name', {}).get('default', '?')),
                'away': ru(at.get('name', {}).get('default', '?')),
                'score': f'{away_score}:{home_score}',
                'home_score': home_score,
                'away_score': away_score,
                'home_sog': ht.get('sog'),
                'away_sog': at.get('sog'),
                'game_id': g.get('id'),
            })

    return matches


def fetch_nhl_upcoming(date_str):
    """Предстоящие матчи НХЛ на дату (YYYYMMDD)."""
    date_iso = f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}'
    url = f'https://api-web.nhle.com/v1/scoreboard/{date_iso}'
    try:
        resp = requests.get(url, timeout=15)
        data = resp.json()
    except:
        return []

    matches = []
    for gbd in data.get('gamesByDate', []):
        if gbd.get('date') != date_iso:
            continue
        for g in gbd.get('games', []):
            if g.get('gameState') not in ('FUT',):
                continue

            ht = g.get('homeTeam', {})
            at = g.get('awayTeam', {})

            # Время в МСК
            try:
                dt = datetime.fromisoformat(g.get('startTimeUTC', '').replace('Z', '+00:00'))
                time_msk = (dt + MOW).strftime('%H:%M')
            except:
                time_msk = ''

            matches.append({
                'home': ru(ht.get('name', {}).get('default', '?')),
                'away': ru(at.get('name', {}).get('default', '?')),
                'time': time_msk,
            })

    return matches


def get_game_stats(game_id):
    """Детальная статистика матча (броски, вратари, PIM, блоки)."""
    url = f'https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore'
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
    except:
        return {}

    pgs = data.get('playerByGameStats', {})
    home_team = data.get('homeTeam', {})
    away_team = data.get('awayTeam', {})

    stats = {
        'home_sog': home_team.get('sog', 0),
        'away_sog': away_team.get('sog', 0),
    }

    # Goalies
    goalies = []
    for side_key, label in [('homeTeam', 'home'), ('awayTeam', 'away')]:
        for g in pgs.get(side_key, {}).get('goalies', []):
            if g.get('toi', '00:00') != '00:00':
                goalies.append({
                    'side': label,
                    'name': g.get('name', {}).get('default', '?'),
                    'saves': g.get('saves', 0),
                    'shots': g.get('shotsAgainst', g.get('saveShotsAgainst', 0)),
                    'toi': g.get('toi', '00:00'),
                })
    stats['goalies'] = goalies

    return stats


if __name__ == '__main__':
    from datetime import datetime, timezone, timedelta
    y = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y%m%d')
    t = (datetime.now(timezone.utc) + timedelta(days=1)).strftime('%Y%m%d')

    print(f'Results ({y}):')
    for m in fetch_nhl_results(y)[:5]:
        extra = ''
        if m['home_sog'] is not None:
            extra = f' (броски {m["away_sog"]}-{m["home_sog"]})'
        print(f'  {m["away"]} — {m["home"]} {m["score"]}{extra}')

    print(f'\nUpcoming ({t}):')
    for m in fetch_nhl_upcoming(t)[:5]:
        print(f'  {m["time"]}  {m["away"]} — {m["home"]}')
