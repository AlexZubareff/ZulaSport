#!/usr/bin/env python3
"""
Сбор логотипов команд из ESPN.
Создаёт файл /opt/team_logos.json с маппингом русских названий → URL логотипа.
Однократный запуск (обновляется при изменении состава лиг).
"""

import sys, json, re, urllib.request
from time import sleep

sys.path.insert(0, '/opt')
import upcoming as _up
import nhl_api as _nhl
import balldontlie_api as _nba

# Собираем все маппинги названий команд (EN→RU)
_ALL_TEAMS_RU = {}
_ALL_TEAMS_RU.update(_up.TEAMS_RU)
_ALL_TEAMS_RU.update(_nhl.NHL_TEAMS_RU)
_ALL_TEAMS_RU.update(_nba.NBA_TEAMS_RU)

# Добавляем TEAMS_RU_EXTRA если есть
if hasattr(_up, 'TEAMS_RU_EXTRA'):
    _ALL_TEAMS_RU.update(_up.TEAMS_RU_EXTRA)

# Обратный маппинг: русское → английское
_RU_TO_EN = {v: k for k, v in _ALL_TEAMS_RU.items()}

OUTPUT = '/opt/team_logos.json'

# Лиги для сбора логотипов
LEAGUES = [
    ('soccer', 'eng.1', 'АПЛ'),
    ('soccer', 'esp.1', 'Ла Лига'),
    ('soccer', 'ita.1', 'Серия А'),
    ('soccer', 'ger.1', 'Бундеслига'),
    ('soccer', 'fra.1', 'Лига 1'),
    ('hockey', 'nhl', 'НХЛ'),
    ('basketball', 'nba', 'NBA'),
]

_err_count = 0
_SUCCEEDED = set()

def logo_url(sport, team):
    """Сформировать URL логотипа команды ESPN."""
    tid = team.get('id', '')
    abbr = team.get('abbreviation', '').lower()
    name = team.get('displayName', '?')

    if sport == 'soccer':
        url = f'https://a.espncdn.com/i/teamlogos/soccer/500/{tid}.png'
    elif sport == 'hockey':
        url = f'https://a.espncdn.com/i/teamlogos/nhl/500/scoreboard/{abbr}.png'
    elif sport == 'basketball':
        url = f'https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/{abbr}.png'
    else:
        return ''

    # Проверяем, что логотип существует
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=5)
        if resp.status == 200:
            return url
    except:
        pass
    return ''


def ru_name(en_name):
    """Английское название → русское через маппинг."""
    if en_name in _ALL_TEAMS_RU:
        return _ALL_TEAMS_RU[en_name]
    # Пробуем по частям
    for eng, rus in _ALL_TEAMS_RU.items():
        if eng.lower() in en_name.lower() or en_name.lower() in eng.lower():
            return rus
    return en_name


def build():
    result = {}
    total = 0

    for sport, league_path, league_label in LEAGUES:
        path = f'{sport}/{league_path}' if league_path else sport
        url = f'https://site.api.espn.com/apis/site/v2/sports/{path}/teams'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read().decode())
        except Exception as e:
            print(f'❌ {league_label}: {e}')
            continue

        teams = data.get('sports', [{}])[0].get('leagues', [{}])[0].get('teams', [])
        found = 0
        for t in teams:
            team = t.get('team', {})
            en_name = team.get('displayName', '')
            if not en_name:
                continue

            logo = logo_url(sport, team)
            if not logo:
                continue

            ru = ru_name(en_name)
            total += 1
            found += 1

            # Сохраняем по английскому и русскому названию
            result[en_name] = {'url': logo, 'ru': ru}
            result[ru] = {'url': logo, 'ru': ru}

            # Также сохраняем краткие варианты
            for variant in [en_name.split()[-1], ru.split()[-1]]:
                if len(variant) > 3 and variant not in result:
                    result[variant] = {'url': logo, 'ru': ru}

        print(f'  {league_label:12} {found}/{len(teams)}')

    # Сохраняем
    output = {
        '_meta': {'total': total, 'source': 'ESPN CDN'},
        'teams': result,
    }
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f'\n✅ Сохранено: {total} команд в {OUTPUT}')
    print(f'   Размер: {len(json.dumps(output, ensure_ascii=False))} bytes')


if __name__ == '__main__':
    build()
