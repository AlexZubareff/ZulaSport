#!/usr/bin/env python3
"""
Загрузчик данных NBA через ESPN API.

Сохраняет:
  /opt/data/nba/schedule.json   — предстоящие + последние результаты + коэффициенты
  /opt/data/nba/odds.json       — отдельный файл с коэффициентами

Данные:
  - Расписание (предстоящие матчи, время)
  - Результаты (завершённые)
  - Коэффициенты DraftKings (moneyline, spread, over/under)
  - Статистика команд (ppg, fg%, rebounds, etc.)
  - Информация о сериях плей-офф

Использование:
    python3 fetch_nba_espn_data.py
    python3 fetch_nba_espn_data.py --date 20260520
    python3 fetch_nba_espn_data.py --days 3
"""

import json, os, sys
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import requests

sys.path.insert(0, '/opt')
from date_utils import normalize_date, format_date_display, tomorrow_storage

# ─── Константы ─────────────────────────────────────────────────────
ESPN_API = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'
MOW = timedelta(hours=3)
UTC = timezone.utc
DATA_DIR = '/opt/data/nba'

os.makedirs(DATA_DIR, exist_ok=True)

# ─── Перевод названий команд (русские) ────────────────────────────
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
    'Memphis Grizzlies': 'Мемфис Гриззлиз',
    'Miami Heat': 'Майами Хит',
    'Milwaukee Bucks': 'Милуоки Бакс',
    'Minnesota Timberwolves': 'Миннесота Тимбервулвз',
    'New Orleans Pelicans': 'Нью-Орлеан Пеликанс',
    'New York Knicks': 'Нью-Йорк Никс',
    'Oklahoma City Thunder': 'Оклахома-Сити Тандер',
    'Orlando Magic': 'Орландо Мэджик',
    'Philadelphia 76ers': 'Филадельфия 76ерс',
    'Phoenix Suns': 'Финикс Санз',
    'Portland Trail Blazers': 'Портленд Трэйл Блэйзерс',
    'Sacramento Kings': 'Сакраменто Кингз',
    'San Antonio Spurs': 'Сан-Антонио Спёрс',
    'Toronto Raptors': 'Торонто Рэпторс',
    'Utah Jazz': 'Юта Джаз',
    'Washington Wizards': 'Вашингтон Уизардс',
}


def ru(team_name):
    """Перевести название команды на русский."""
    if not team_name:
        return '?'
    if team_name in NBA_TEAMS_RU:
        return NBA_TEAMS_RU[team_name]
    # Поиск по частичному совпадению
    for eng, rus in NBA_TEAMS_RU.items():
        if team_name.lower() in eng.lower() or eng.lower() in team_name.lower():
            return rus
    return team_name


def us_to_decimal(us_odds):
    """Convert US odds to decimal. e.g. '-230' → 1.43, '+190' → 2.90"""
    try:
        val = float(us_odds)
        if val > 0:
            return round(1 + val / 100, 2)
        else:
            return round(1 - 100 / val, 2)
    except (ValueError, TypeError):
        return None


def _parse_odds(competition):
    """
    Парсинг коэффициентов из competition['odds'][0].

    Формат ESPN:
      odds[0].moneyline.home.close.odds — US odds for home
      odds[0].moneyline.away.close.odds — US odds for away
      odds[0].spread — spread value (e.g. -7.5)
      odds[0].overUnder — total (e.g. 217.5)
      odds[0].details — string like "OKC -7.5"
    """
    odds_list = competition.get('odds', [])
    if not odds_list:
        return {}

    odds_data = odds_list[0]
    result = {
        'home_dec': None,
        'away_dec': None,
        'home_ml_us': None,
        'away_ml_us': None,
        'spread': None,
        'over_under': None,
        'details': odds_data.get('details', ''),
        'provider': odds_data.get('provider', {}).get('name', ''),
    }

    # Moneyline
    moneyline = odds_data.get('moneyline', {})
    home_ml_odds = (moneyline.get('home') or {}).get('close', {}).get('odds', '')
    away_ml_odds = (moneyline.get('away') or {}).get('close', {}).get('odds', '')

    if home_ml_odds:
        result['home_dec'] = us_to_decimal(home_ml_odds)
        result['home_ml_us'] = home_ml_odds
    if away_ml_odds:
        result['away_dec'] = us_to_decimal(away_ml_odds)
        result['away_ml_us'] = away_ml_odds

    # Spread
    spread = odds_data.get('spread')
    if spread is not None:
        result['spread'] = spread

    # Over/Under
    ou = odds_data.get('overUnder')
    if ou is not None:
        result['over_under'] = ou

    return result


# ═══════════════════════════════════════════════════════════════════
#  Основной загрузчик
# ═══════════════════════════════════════════════════════════════════

def fetch_espn_scoreboard(date_str=None):
    """
    Загрузить данные из ESPN scoreboard.

    Если date_str — дата в формате YYYYMMDD (или YYYY-MM-DD).
    Без аргумента — текущий день (сегодня + завтра).
    """
    clean_date = normalize_date(date_str) if date_str else None
    url = f'{ESPN_API}/scoreboard'
    if clean_date:
        url += f'?dates={clean_date}'

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f'  ❌ ESPN API ({url}): {e}')
        return None


def parse_scoreboard(data) -> dict:
    """
    Преобразовать ответ ESPN scoreboard в единый формат.

    Возвращает:
    {
        'upcoming': [...],
        'finished': [...],
        'teams_info': {team.name: {...}},
        'date': '2026-05-20',
    }
    """
    if not data:
        return {'upcoming': [], 'finished': [], 'teams_info': {}, 'date': ''}

    events = data.get('events', [])
    raw_day = data.get('day', {})
    day = raw_day.get('date', datetime.now().strftime('%Y-%m-%d')) if isinstance(raw_day, dict) else raw_day
    season = data.get('season', {})
    is_playoff = season.get('type', 2) in (3, 4) or season.get('slug', '') in ('post-season',)

    upcoming = []
    finished = []
    teams_info = {}

    for event in events:
        comp = event.get('competitions', [{}])[0]
        status = comp.get('status', {}).get('type', {})
        state = status.get('name', '')
        state_desc = status.get('description', '')
        start_utc = event.get('date', '')

        # Время
        try:
            dt = datetime.fromisoformat(start_utc.replace('Z', '+00:00'))
            time_msk = (dt + MOW).strftime('%H:%M')
            date_str = dt.strftime('%Y-%m-%d')
        except:
            dt = None
            time_msk = ''
            date_str = day or ''

        # Команды
        competitors = comp.get('competitors', [])
        home_comp = next((c for c in competitors if c.get('homeAway') == 'home'), {})
        away_comp = next((c for c in competitors if c.get('homeAway') == 'away'), {})

        home_team = home_comp.get('team', {})
        away_team = away_comp.get('team', {})

        home_name = home_team.get('displayName', '')
        away_name = away_team.get('displayName', '')
        home_abbrev = home_team.get('abbreviation', '')
        away_abbrev = away_team.get('abbreviation', '')

        # Логотипы
        home_logo = ''
        away_logo = ''
        logos = home_team.get('logos', [])
        if logos:
            home_logo = logos[0].get('href', '')
        logos = away_team.get('logos', [])
        if logos:
            away_logo = logos[0].get('href', '')

        # Статистика команды (сезонные средние)
        home_stats = {}
        away_stats = {}
        for comp_data in competitors:
            team_name = comp_data.get('team', {}).get('displayName', '')
            stats_list = comp_data.get('statistics', [])
            stats_dict = {}
            for s in stats_list:
                key = s.get('name', '')
                dv = s.get('displayValue', '')
                try:
                    stats_dict[key] = float(dv) if '.' in dv else int(dv)
                except:
                    stats_dict[key] = dv
            if comp_data.get('homeAway') == 'home':
                home_stats = stats_dict
            else:
                away_stats = stats_dict

            # Records
            records = comp_data.get('records', [])
            for r in records:
                rtype = r.get('type', '')
                summary = r.get('summary', '')
                if rtype == 'total':
                    parts = summary.split('-')
                    if len(parts) >= 2:
                        stats_dict['wins'] = int(parts[0])
                        stats_dict['losses'] = int(parts[1])
                elif rtype == 'home':
                    parts = summary.split('-')
                    if len(parts) >= 2:
                        stats_dict['homeWins'] = int(parts[0])
                        stats_dict['homeLosses'] = int(parts[1])
                elif rtype == 'road':
                    parts = summary.split('-')
                    if len(parts) >= 2:
                        stats_dict['roadWins'] = int(parts[0])
                        stats_dict['roadLosses'] = int(parts[1])

            # Сохраняем в teams_info
            if team_name and team_name not in teams_info:
                teams_info[team_name] = {
                    'displayName': team_name,
                    'abbreviation': comp_data.get('team', {}).get('abbreviation', ''),
                    'logo': (comp_data.get('team', {}).get('logos') or [{}])[0].get('href', '') if comp_data.get('team', {}).get('logos') else '',
                }
            if team_name:
                for key, val in stats_dict.items():
                    teams_info.setdefault(team_name, {})[key] = val

        # Очки
        home_score = home_comp.get('score')
        away_score = away_comp.get('score')

        # Серия плей-офф
        series = comp.get('series', {})
        series_info = {}
        if series and series.get('type') == 'playoff':
            sc = series.get('summary', '')
            competitors_series = series.get('competitors', [])
            home_series_wins = 0
            away_series_wins = 0
            for cs in competitors_series:
                cs_id = cs.get('id', '')
                cs_wins = cs.get('wins', 0)
                if cs_id == home_comp.get('id', ''):
                    home_series_wins = cs_wins
                elif cs_id == away_comp.get('id', ''):
                    away_series_wins = cs_wins

            series_info = {
                'type': 'playoff',
                'summary': sc,
                'total_games': series.get('totalCompetitions', 7),
                'home_wins': home_series_wins,
                'away_wins': away_series_wins,
            }

        # Odds
        odds = _parse_odds(comp)

        match = {
            'game_id': event.get('id', ''),
            'uid': event.get('uid', ''),
            'name': event.get('name', ''),
            'shortName': event.get('shortName', ''),
            'home': home_name,
            'home_ru': ru(home_name),
            'home_abbrev': home_abbrev,
            'home_logo': home_logo,
            'away': away_name,
            'away_ru': ru(away_name),
            'away_abbrev': away_abbrev,
            'away_logo': away_logo,
            'start_time_utc': start_utc,
            'time': time_msk,
            'date': date_str,
            'is_playoff': is_playoff,
            'series': series_info,
            'odds': odds,
            'venue': comp.get('venue', {}).get('fullName', ''),
            'status': state,
            'status_desc': state_desc,
        }

        # Счёт если завершён
        if state == 'STATUS_FINAL':
            match['home_score'] = int(home_score) if home_score is not None else None
            match['away_score'] = int(away_score) if away_score is not None else None
            match['score'] = f"{home_score}:{away_score}" if home_score is not None and away_score is not None else None
            finished.append(match)
        elif state in ('STATUS_SCHEDULED', 'STATUS_PRE', 'STATUS_DELAYED'):
            upcoming.append(match)
        elif state == 'STATUS_IN_PROGRESS':
            match['home_score'] = int(home_score) if home_score is not None else None
            match['away_score'] = int(away_score) if away_score is not None else None
            match['score'] = f"{home_score}:{away_score}" if home_score is not None and away_score is not None else None
            upcoming.append(match)
        else:
            match['home_score'] = int(home_score) if home_score is not None else None
            match['away_score'] = int(away_score) if away_score is not None else None
            match['score'] = f"{home_score}:{away_score}" if home_score is not None and away_score is not None else None
            finished.append(match)

    return {
        'upcoming': upcoming,
        'finished': finished,
        'teams_info': teams_info,
        'date': day,
        'season': season,
    }


# ═══════════════════════════════════════════════════════════════════
#  Обновление / объединение с существующими данными
# ═══════════════════════════════════════════════════════════════════

def _merge_schedule(existing, new_data):
    """Объединить существующее расписание с новыми данными."""
    existing_upcoming = existing.get('upcoming', [])
    existing_finished = existing.get('finished', [])
    existing_teams = existing.get('teams_info', {})

    new_upcoming = new_data.get('upcoming', [])
    new_finished = new_data.get('finished', [])
    new_teams = new_data.get('teams_info', {})

    # Собираем game_id из новых данных для дедупликации
    new_ids = set()
    for m in new_upcoming:
        if m.get('game_id'):
            new_ids.add(m['game_id'])
    for m in new_finished:
        if m.get('game_id'):
            new_ids.add(m['game_id'])

    # Объединяем upcoming: новые + старые, которых нет в новых
    old_upcoming = [m for m in existing_upcoming
                    if m.get('game_id') not in new_ids
                    and m.get('game_id')]
    merged_upcoming = new_upcoming + old_upcoming

    # Finished: то же самое
    old_finished = [m for m in existing_finished
                    if m.get('game_id') not in new_ids
                    and m.get('game_id')]
    merged_finished = new_finished + old_finished

    # teams_info: объединяем
    merged_teams = {**existing_teams, **new_teams}

    return {
        'upcoming': merged_upcoming,
        'finished': merged_finished,
        'teams_info': merged_teams,
        'date': new_data.get('date', existing.get('date', '')),
        'season': new_data.get('season', existing.get('season', {})),
    }


# ═══════════════════════════════════════════════════════════════════
#  Save
# ═══════════════════════════════════════════════════════════════════

def save_data(date_str=None):
    """Полный цикл загрузки и сохранения данных NBA."""
    print('🏀 Загрузка данных из ESPN...')

    data = fetch_espn_scoreboard(date_str)
    if not data:
        print('  ❌ Не удалось загрузить данные')
        return None

    parsed = parse_scoreboard(data)
    print(f'  📅 Дата: {parsed["date"]}')
    print(f'  🆕 Предстоящих: {len(parsed["upcoming"])}')
    print(f'  ✅ Завершённых: {len(parsed["finished"])}')
    print(f'  📊 Команд в статистике: {len(parsed["teams_info"])}')

    # Если нет конкретной даты — догружаем завтрашний день
    if not date_str:
        tomorrow = tomorrow_storage()
        print(f'  ➕ Догружаю завтра ({tomorrow})...')
        tomorrow_data = fetch_espn_scoreboard(tomorrow)
        if tomorrow_data:
            tomorrow_parsed = parse_scoreboard(tomorrow_data)
            tomorrow_key = tomorrow_parsed.get('date', tomorrow)
            existing_keys = {m.get('game_id') for m in parsed['upcoming']}
            for m in tomorrow_parsed['upcoming']:
                if m.get('game_id') not in existing_keys:
                    parsed['upcoming'].append(m)
                    existing_keys.add(m.get('game_id'))
            for name, info in tomorrow_parsed.get('teams_info', {}).items():
                if name not in parsed['teams_info']:
                    parsed['teams_info'][name] = info
            print(f'    → всего предстоящих: {len(parsed["upcoming"])}')

    # Пытаемся загрузить исторические данные
    schedule_path = f'{DATA_DIR}/schedule.json'
    existing = {}
    if os.path.exists(schedule_path):
        try:
            with open(schedule_path, encoding='utf-8') as f:
                existing = json.load(f)
            print(f'  📂 Загружен существующий кеш: '
                  f'{len(existing.get("upcoming",[]))} upcoming, '
                  f'{len(existing.get("finished",[]))} finished')
        except:
            pass

    merged = _merge_schedule(existing, parsed)

    # Сохраняем
    with open(schedule_path, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f'  ✅ Расписание: {len(merged["upcoming"])} upcoming, {len(merged["finished"])} finished')

    # Отдельный odds-файл
    odds_path = f'{DATA_DIR}/odds.json'
    all_odds = []
    for m in merged['upcoming']:
        if m.get('odds'):
            all_odds.append({
                'game_id': m['game_id'],
                'home': m['home'],
                'away': m['away'],
                'odds': m['odds'],
                'series': m.get('series', {}),
                'time': m['time'],
                'date': m['date'],
            })
    if all_odds:
        with open(odds_path, 'w', encoding='utf-8') as f:
            json.dump({'odds': all_odds, 'updated_at': datetime.now().isoformat()},
                      f, ensure_ascii=False, indent=2)
        print(f'  ✅ Коэффициенты: {len(all_odds)} матчей')

    # Статистика команд
    stats_path = f'{DATA_DIR}/teams_stats.json'
    with open(stats_path, 'w', encoding='utf-8') as f:
        json.dump(merged.get('teams_info', {}), f, ensure_ascii=False, indent=2)
    print(f'  ✅ Статистика команд: {len(merged.get("teams_info",{}))} записей')

    return {
        'upcoming': len(merged['upcoming']),
        'finished': len(merged['finished']),
        'teams_info': len(merged.get('teams_info', {})),
    }


def fetch_schedule():
    """API для capper_pipeline_nba.py — вернуть schedule.json."""
    sched_path = f'{DATA_DIR}/schedule.json'
    if not os.path.exists(sched_path):
        # Попробуем загрузить
        save_data()

    try:
        with open(sched_path, encoding='utf-8') as f:
            return json.load(f)
    except:
        return {'upcoming': [], 'finished': [], 'teams_info': {}}


# ═══════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import sys

    date_arg = None
    days_arg = 1
    for a in sys.argv[1:]:
        if a.startswith('--date='):
            date_arg = a.split('=', 1)[1].strip()
        elif a.startswith('--days='):
            days_arg = int(a.split('=', 1)[1].strip())
        elif a.startswith('--date'):
            idx = sys.argv.index(a)
            if idx + 1 < len(sys.argv):
                date_arg = sys.argv[idx + 1]

    print(f'🏀 NBA Data Fetch — {format_date_display(datetime.now())} МСК')
    print(f'   Дата: {date_arg or "сегодня"}')

    r = save_data(date_str=date_arg)

    if r:
        print(f'\n✅ Итого: {r}')
    else:
        print('\n❌ Ошибка загрузки')
        sys.exit(1)
