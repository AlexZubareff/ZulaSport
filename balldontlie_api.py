#!/usr/bin/env python3
"""
BALLDONTLIE NBA API.
Требуется API-ключ (бесплатно на app.balldontlie.io).
"""

import requests
from datetime import datetime, timezone, timedelta

API_KEY = open('/etc/balldontlie.key').read().strip()
BASE = 'https://api.balldontlie.io/v1'

MOW = timedelta(hours=3)

# ─── ПЕРЕВОД КОМАНД NBA ────────────────────────────────────────────

NBA_TEAMS_RU = {
    'Atlanta Hawks': 'Атланта Хокс',
    'Boston Celtics': 'Бостон Селтикс',
    'Brooklyn Nets': 'Бруклин Нетс',
    'Charlotte Hornets': 'Шарлотт Хорнетс',
    'Chicago Bulls': 'Чикаго Буллз',
    'Cleveland Cavaliers': 'Кливленд Кавальерс',
    'Dallas Mavericks': 'Даллас Маверикс',
    'Denver Nuggets': 'Денвер Наггетс',
    'Detroit Pistons': 'Детройт Пистонс',
    'Golden State Warriors': 'Голден Стэйт Уорриорз',
    'Houston Rockets': 'Хьюстон Рокетс',
    'Indiana Pacers': 'Индиана Пэйсерс',
    'LA Clippers': 'ЛА Клипперс',
    'Los Angeles Lakers': 'ЛА Лейкерс',
    'Memphis Grizzlies': 'Мемфис Гриззлис',
    'Miami Heat': 'Майами Хит',
    'Milwaukee Bucks': 'Милуоки Бакс',
    'Minnesota Timberwolves': 'Миннесота Тимбервулвз',
    'New Orleans Pelicans': 'Нью-Орлеан Пеликанс',
    'New York Knicks': 'Нью-Йорк Никс',
    'Oklahoma City Thunder': 'Оклахома-Сити Тандер',
    'Orlando Magic': 'Орландо Мэджик',
    'Philadelphia 76ers': 'Филадельфия Сиксерс',
    'Phoenix Suns': 'Финикс Санз',
    'Portland Trail Blazers': 'Портленд Трэйл Блэйзерс',
    'Sacramento Kings': 'Сакраменто Кингз',
    'San Antonio Spurs': 'Сан-Антонио Спёрс',
    'Toronto Raptors': 'Торонто Рэпторс',
    'Utah Jazz': 'Юта Джаз',
    'Washington Wizards': 'Вашингтон Уизардс',
}


def ru(name):
    if name in NBA_TEAMS_RU:
        return NBA_TEAMS_RU[name]
    return name


def _req(endpoint, params=None):
    headers = {'Authorization': API_KEY}
    try:
        r = requests.get(f'{BASE}{endpoint}', params=params, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return {'data': []}


def fetch_nba_results(date_str):
    """Завершённые матчи NBA за дату (YYYYMMDD)."""
    date_iso = f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}'
    data = _req('/games', {'per_page': 50, 'dates[]': date_iso})
    matches = []
    for g in data.get('data', []):
        if g.get('status') != 'Final':
            continue
        ht = g.get('home_team', {})
        vt = g.get('visitor_team', {})
        matches.append({
            'home': ru(ht.get('full_name', '?')),
            'away': ru(vt.get('full_name', '?')),
            'score': f'{g["visitor_team_score"]}:{g["home_team_score"]}',
            'home_score': g.get('home_team_score', 0),
            'away_score': g.get('visitor_team_score', 0),
        })
    return matches


def fetch_nba_upcoming(date_str):
    """Предстоящие матчи NBA на дату (YYYYMMDD)."""
    date_iso = f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}'
    data = _req('/games', {'per_page': 50, 'dates[]': date_iso})
    matches = []
    for g in data.get('data', []):
        if g.get('status') == 'Final':
            continue
        ht = g.get('home_team', {})
        vt = g.get('visitor_team', {})
        # Время из datetime (UTC → MSK)
        tm = ''
        dt_raw = g.get('datetime', '')
        if dt_raw:
            try:
                dt = datetime.fromisoformat(dt_raw.replace('Z', '+00:00'))
                tm = (dt + MOW).strftime('%H:%M')
            except:
                pass
        matches.append({
            'home': ru(ht.get('full_name', '?')),
            'away': ru(vt.get('full_name', '?')),
            'time': tm,
        })
    return matches


if __name__ == '__main__':
    from datetime import datetime, timezone, timedelta
    y = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y%m%d')
    t = (datetime.now(timezone.utc) + timedelta(days=1)).strftime('%Y%m%d')
    print(f'Results ({y}):')
    for m in fetch_nba_results(y):
        print(f'  {m["away"]} — {m["home"]} {m["score"]}')
    print(f'\nUpcoming ({t}):')
    for m in fetch_nba_upcoming(t):
        print(f'  {m["time"]}  {m["away"]} — {m["home"]}')
