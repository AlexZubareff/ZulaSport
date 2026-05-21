#!/usr/bin/env python3
"""
Загрузчик данных НХЛ через api-web.nhle.com.

Сохраняет:
  /opt/data/nhl/schedule.json    — предстоящие + последние результаты
  /opt/data/nhl/standings.json   — турнирная таблица
  /opt/data/nhl/teams.json       — список команд с логотипами
  /opt/data/nhl/player_stats.json — статистика игроков
  /tmp/live_scores_data.json     — live-обновления (дополнение)
"""

import json, os, sys, math
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import requests

sys.path.insert(0, '/opt')

# ─── Константы ─────────────────────────────────────────────────────
NHL_API = 'https://api-web.nhle.com'
MOW = timedelta(hours=3)
UTC = timezone.utc
DATA_DIR = '/opt/data/nhl'
LIVE_PATH = '/tmp/live_scores_data.json'

os.makedirs(DATA_DIR, exist_ok=True)

# ─── Перевод названий команд ───────────────────────────────────────
NHL_TEAMS_RU = {
    'Anaheim Ducks': 'Анахайм Дакс',
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

# Abbreviation → full name map (for team name lookup)
ABBREV_TO_FULL = {
    'ANA': 'Anaheim Ducks', 'ARI': 'Arizona Coyotes', 'BOS': 'Boston Bruins',
    'BUF': 'Buffalo Sabres', 'CGY': 'Calgary Flames', 'CAR': 'Carolina Hurricanes',
    'CHI': 'Chicago Blackhawks', 'COL': 'Colorado Avalanche', 'CBJ': 'Columbus Blue Jackets',
    'DAL': 'Dallas Stars', 'DET': 'Detroit Red Wings', 'EDM': 'Edmonton Oilers',
    'FLA': 'Florida Panthers', 'LAK': 'Los Angeles Kings', 'MIN': 'Minnesota Wild',
    'MTL': 'Montreal Canadiens', 'NSH': 'Nashville Predators', 'NJD': 'New Jersey Devils',
    'NYI': 'New York Islanders', 'NYR': 'New York Rangers', 'OTT': 'Ottawa Senators',
    'PHI': 'Philadelphia Flyers', 'PIT': 'Pittsburgh Penguins', 'SJS': 'San Jose Sharks',
    'SEA': 'Seattle Kraken', 'STL': 'St. Louis Blues', 'TBL': 'Tampa Bay Lightning',
    'TOR': 'Toronto Maple Leafs', 'UTA': 'Utah Hockey Club', 'VAN': 'Vancouver Canucks',
    'VGK': 'Vegas Golden Knights', 'WSH': 'Washington Capitals', 'WPG': 'Winnipeg Jets',
}


def ru(team_name):
    """Перевести название команды на русский."""
    if not team_name:
        return '?'
    # Убираем город от названия
    if team_name in NHL_TEAMS_RU:
        return NHL_TEAMS_RU[team_name]
    # Поиск по вхождению
    for eng, rus in NHL_TEAMS_RU.items():
        if eng.lower() in team_name.lower() or team_name.lower() in eng.lower():
            return rus
    return team_name


def _full_name(place_name, common_name):
    """Собрать полное имя команды из placeName + commonName.
    Иногда placeName включает commonName (Vegas Golden Knights), иногда нет (Boston → Bruins).
    """
    place = place_name.get('default', '') if isinstance(place_name, dict) else str(place_name or '')
    common = common_name.get('default', '') if isinstance(common_name, dict) else str(common_name or '')
    if not place and not common:
        return '?'
    if not common:
        return place
    if not place:
        return common
    if common in place:
        return place
    if place in common:
        return common
    return f'{place} {common}'


def _parse_odds(odds_list):
    """Преобразовать массив odds из API в структуру: {home, away, ml}.
    providerId: 3 = decimal (Pinnacle?), 6 = decimal, 7 = US, 8 = US, 10 = US
    Берём decimal котировки, если есть.
    """
    result = {'home_ml': None, 'away_ml': None, 'home_dec': None, 'away_dec': None}
    if not odds_list:
        return result
    for o in odds_list:
        pid = o.get('providerId')
        val = o.get('value', '')
        # Decimal odds
        if pid in (3, 6):
            try:
                dec = float(val)
            except:
                continue
            # Кому принадлежит? Определяем по sign (US odds)
            # По умолчанию первый home, второй away
            continue  # разберём отдельно
    # Парсим по позициям
    if len(odds_list) >= 2:
        # Берём decimal (providerId 3)
        dec_odds = [o for o in odds_list if o.get('providerId') in (3, 6)]
        us_odds = [o for o in odds_list if o.get('providerId') in (7, 8)]
        if dec_odds:
            try:
                result['home_dec'] = float(dec_odds[0]['value'])
            except: pass
            if len(dec_odds) > 1:
                try:
                    result['away_dec'] = float(dec_odds[1]['value'])
                except: pass
        elif us_odds:
            # US → Decimal конверсия
            for i, o in enumerate(us_odds[:2]):
                try:
                    val = float(o['value'])
                    if val > 0:
                        dec = 1 + val / 100
                    else:
                        dec = 1 - 100 / val
                    if i == 0:
                        result['home_dec'] = round(dec, 2)
                    else:
                        result['away_dec'] = round(dec, 2)
                except: pass
        if result['home_dec'] and result['away_dec']:
            result['home_ml'] = 1 / result['home_dec']
            result['away_ml'] = 1 / result['away_dec']
    return result


# ═══════════════════════════════════════════════════════════════════
#  DATA FETCHERS
# ═══════════════════════════════════════════════════════════════════

def fetch_schedule():
    """Загрузить расписание + результаты из /v1/schedule/now.
    Возвращает dict с предстоящими и завершёнными матчами.
    """
    url = f'{NHL_API}/v1/schedule/now'
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f'  ❌ Schedule API: {e}')
        return {'upcoming': [], 'finished': []}

    upcoming = []
    finished = []

    for day in data.get('gameWeek', []):
        for g in day.get('games', []):
            state = g.get('gameState', '')
            at = g.get('awayTeam', {})
            ht = g.get('homeTeam', {})
            away_place = at.get('placeName', {}) or {}
            away_common = at.get('commonName', {}) or {}
            home_place = ht.get('placeName', {}) or {}
            home_common = ht.get('commonName', {}) or {}

            away_full = _full_name(away_place, away_common)
            home_full = _full_name(home_place, home_common)

            # Время
            start_utc = g.get('startTimeUTC', '')
            try:
                dt = datetime.fromisoformat(start_utc.replace('Z', '+00:00'))
                time_msk = (dt + MOW).strftime('%H:%M')
                date_str = dt.strftime('%Y-%m-%d')
            except:
                dt = None
                time_msk = ''
                date_str = day.get('date', '')

            odds = _parse_odds(at.get('odds', []))

            # Статус серии (плей-офф)
            series = g.get('seriesStatus', {})
            series_info = {
                'round': series.get('round'),
                'series_abbrev': series.get('seriesAbbrev'),
                'game_of_series': series.get('gameNumberOfSeries'),
                'home_wins': series.get('topSeedWins') if series.get('topSeedTeamAbbrev') == at.get('abbrev') else series.get('bottomSeedWins'),
                'away_wins': series.get('bottomSeedWins') if series.get('topSeedTeamAbbrev') == at.get('abbrev') else series.get('topSeedWins'),
            } if series.get('seriesAbbrev') else {}

            match = {
                'game_id': g.get('id'),
                'away': away_full,
                'away_ru': ru(away_full),
                'away_abbrev': at.get('abbrev', ''),
                'away_logo': at.get('logo', ''),
                'away_id': at.get('id'),
                'home': home_full,
                'home_ru': ru(home_full),
                'home_abbrev': ht.get('abbrev', ''),
                'home_logo': ht.get('logo', ''),
                'home_id': ht.get('id'),
                'venue': g.get('venue', {}).get('default', ''),
                'start_time_utc': start_utc,
                'time': time_msk,
                'date': date_str,
                'game_state': state,
                'odds': odds,
                'series': series_info,
                'season': g.get('season'),
                'game_type': g.get('gameType'),  # 2 = regular, 3 = playoffs
            }

            if state in ('OFF', 'FINAL'):
                match['score'] = f"{at.get('score', 0)}:{ht.get('score', 0)}"
                match['away_score'] = at.get('score', 0)
                match['home_score'] = ht.get('score', 0)
                # Если OT/SO — есть periodDescriptor
                pd = g.get('periodDescriptor', {})
                match['period_type'] = pd.get('periodType', 'REG')  # REG, OT, SO
                finished.append(match)
            elif state == 'LIVE':
                match['score'] = f"{at.get('score', 0)}:{ht.get('score', 0)}"
                match['away_score'] = at.get('score', 0)
                match['home_score'] = ht.get('score', 0)
                pd = g.get('periodDescriptor', {})
                match['period'] = pd.get('number', 1)
                match['period_type'] = pd.get('periodType', 'REG')
                match['clock'] = g.get('clock', {})
                upcoming.append(match)  # live тоже в "upcoming" для обработки
            else:
                # FUT или PRE
                match['score'] = None
                match['away_score'] = None
                match['home_score'] = None
                upcoming.append(match)

    return {'upcoming': upcoming, 'finished': finished}


def fetch_standings():
    """Загрузить турнирную таблицу."""
    url = f'{NHL_API}/v1/standings/now'
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f'  ❌ Standings API: {e}')
        return []

    standings = []
    for s in data.get('standings', []):
        # teamName / placeName / teamCommonName — могут быть dict или None
        def _dict_val(obj, key='default'):
            if isinstance(obj, dict):
                return obj.get(key, '')
            return str(obj or '')

        team_name_dict = s.get('teamName') or {}
        place_dict = s.get('placeName') or {}
        common_dict = s.get('teamCommonName') or {}
        abbrev_field = s.get('teamAbbrev') or ''

        place = _dict_val(place_dict)
        common = _dict_val(common_dict)
        full = f'{place} {common}'.strip() if place and common else (place or common or _dict_val(team_name_dict) or '?')
        if full == '?':
            continue

        abbrev = abbrev_field.get('default', '') if isinstance(abbrev_field, dict) else str(abbrev_field)

        entry = {
            'team': full,
            'team_ru': ru(full),
            'abbrev': abbrev,
            'logo': s.get('teamLogo', ''),
            'games_played': s.get('gamesPlayed', 0),
            'wins': s.get('wins', 0),
            'losses': s.get('losses', 0),
            'ot_losses': s.get('otLosses', 0),
            'points': s.get('points', 0),
            'point_pct': s.get('pointPctg', 0),
            'goal_for': s.get('goalFor', 0),
            'goal_against': s.get('goalAgainst', 0),
            'goal_diff': s.get('goalDifferential', 0),
            'conference': s.get('conferenceName', ''),
            'division': s.get('divisionName', ''),
            'conf_rank': s.get('conferenceSequence', 0),
            'div_rank': s.get('divisionSequence', 0),
            'home_wins': s.get('homeWins', 0),
            'home_losses': s.get('homeLosses', 0),
            'home_ot_losses': s.get('homeOtLosses', 0),
            'home_points': s.get('homePoints', 0),
            'road_wins': s.get('roadWins', 0),
            'road_losses': s.get('roadLosses', 0),
            'road_ot_losses': s.get('roadOtLosses', 0),
            'road_points': s.get('roadPoints', 0),
            'l10_wins': s.get('l10Wins', 0),
            'l10_losses': s.get('l10Losses', 0),
            'l10_ot_losses': s.get('l10OtLosses', 0),
            'l10_points': s.get('l10Points', 0),
            'l10_goals_for': s.get('l10GoalsFor', 0),
            'l10_goals_against': s.get('l10GoalsAgainst', 0),
            'streak_code': s.get('streakCode', ''),
            'streak_count': s.get('streakCount', 0),
            'regulation_wins': s.get('regulationWins', 0),
            'regulation_plus_ot_wins': s.get('regulationPlusOtWins', 0),
        }
        standings.append(entry)

    return standings


def fetch_teams():
    """Собрать список всех команд НХЛ с логотипами.
    Используем standings и schedule как источники team info.
    """
    teams = {}
    # Из standings
    try:
        standings = fetch_standings()
        for s in standings:
            abbrev = s['abbrev']
            if abbrev not in teams:
                teams[abbrev] = {
                    'abbrev': abbrev,
                    'name': s['team'],
                    'name_ru': s['team_ru'],
                    'logo': s.get('logo', ''),
                    'conference': s.get('conference', ''),
                    'division': s.get('division', ''),
                }
    except Exception as e:
        print(f'  ⚠️ Teams from standings: {e}')

    # Из schedule (дополняем недостающие логотипы)
    try:
        sched = fetch_schedule()
        for g in sched['upcoming'] + sched['finished']:
            for side in ('away', 'home'):
                abbrev = g.get(f'{side}_abbrev')
                name = g.get(side)
                logo = g.get(f'{side}_logo')
                if abbrev and abbrev not in teams:
                    teams[abbrev] = {
                        'abbrev': abbrev,
                        'name': name,
                        'name_ru': g.get(f'{side}_ru', ru(name)),
                        'logo': logo,
                    }
    except:
        pass

    return list(teams.values())


def fetch_player_stats(limit_teams=5):
    """Собрать статистику игроков топ-команд (первых limit_teams по standings).
    Используем /v1/club-stats/{team}/now.
    """
    standings = fetch_standings()
    top = [s['abbrev'] for s in standings[:limit_teams]]
    all_players = []

    for abbrev in top:
        url = f'{NHL_API}/v1/club-stats/{abbrev}/now'
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except:
            continue

        # Skaters
        for sk in data.get('skaters', []):
            try:
                player = {
                    'player_id': sk.get('playerId'),
                    'name': f"{sk.get('firstName', {}).get('default', '')} {sk.get('lastName', {}).get('default', '')}",
                    'team': abbrev,
                    'position': sk.get('position', ''),
                    'games_played': sk.get('gamesPlayed', 0),
                    'goals': sk.get('goals', 0),
                    'assists': sk.get('assists', 0),
                    'points': sk.get('points', 0),
                    'plus_minus': sk.get('plusMinus', 0),
                    'penalty_minutes': sk.get('penaltyMinutes', 0),
                    'power_play_goals': sk.get('powerPlayGoals', 0),
                    'shots': sk.get('shots', 0),
                    'faceoff_win_pct': sk.get('faceoffWinningPctg', 0),
                    'toi_per_game': sk.get('avgTimeOnIcePerGame', ''),
                }
                all_players.append(player)
            except:
                continue

        # Goalies
        for gk in data.get('goalies', []):
            try:
                player = {
                    'player_id': gk.get('playerId'),
                    'name': f"{gk.get('firstName', {}).get('default', '')} {gk.get('lastName', {}).get('default', '')}",
                    'team': abbrev,
                    'position': 'G',
                    'games_played': gk.get('gamesPlayed', 0),
                    'wins': gk.get('wins', 0),
                    'losses': gk.get('losses', 0),
                    'goals_against_avg': gk.get('goalsAgainstAverage', 0),
                    'save_pct': gk.get('savePctg', 0),
                    'shutouts': gk.get('shutouts', 0),
                }
                all_players.append(player)
            except:
                continue

    return all_players


def fetch_game_center(game_id):
    """Получить детали матча: счёт, статистику, вратарей.
    Возвращает dict или None.
    """
    url = f'{NHL_API}/v1/gamecenter/{game_id}/boxscore'
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except:
        return None

    result = {
        'game_id': game_id,
        'game_state': data.get('gameState', ''),
        'home_team': data.get('homeTeam', {}).get('name', {}).get('default', ''),
        'away_team': data.get('awayTeam', {}).get('name', {}).get('default', ''),
        'home_score': data.get('homeTeam', {}).get('score'),
        'away_score': data.get('awayTeam', {}).get('score'),
        'period': data.get('periodDescriptor', {}).get('number'),
        'period_type': data.get('periodDescriptor', {}).get('periodType'),
        'clock': data.get('clock', {}),
    }

    # Player stats
    pgs = data.get('playerByGameStats', {})
    for side_key, label in [('homeTeam', 'home'), ('awayTeam', 'away')]:
        side = pgs.get(side_key, {})
        goalies = []
        for g in side.get('goalies', []):
            goalies.append({
                'name': g.get('name', {}).get('default', ''),
                'saves': g.get('saves', 0),
                'shots_against': g.get('shotsAgainst', g.get('saveShotsAgainst', 0)),
                'toi': g.get('toi', '00:00'),
            })
        result[f'{label}_goalies'] = goalies

    # Team stats (shots, PIM, etc.)
    ht = data.get('homeTeam', {})
    at = data.get('awayTeam', {})
    result['home_sog'] = ht.get('sog', 0)
    result['away_sog'] = at.get('sog', 0)
    result['home_pim'] = ht.get('pim', 0)
    result['away_pim'] = at.get('pim', 0)

    return result


def fetch_live_updates():
    """Собрать live-обновления для NHL и добавить их в /tmp/live_scores_data.json."""
    sched = fetch_schedule()
    live_matches = [m for m in sched.get('upcoming', []) if m.get('game_state') == 'LIVE']

    if not live_matches:
        # Может ни одного live, просто обновляем upcoming/finished
        pass

    # Формируем обновления в формате live_scores_data.json
    updates = {}
    for m in sched['upcoming'] + sched['finished']:
        key = f"НХЛ||{m.get('home_ru', '?')}||{m.get('away_ru', '?')}"
        state = m.get('game_state', '')
        if state == 'FUT':
            status = 'upcoming'
            score = None
        elif state == 'LIVE':
            status = 'live'
            score = m.get('score')
        else:
            status = 'finished'
            score = m.get('score')

        updates[key] = {
            'home': m.get('home_ru', '?'),
            'away': m.get('away_ru', '?'),
            'score': score,
            'status': status,
            'league': 'НХЛ',
            'source': 'nhl_api',
        }

    return updates


# ═══════════════════════════════════════════════════════════════════
#  SAVE
# ═══════════════════════════════════════════════════════════════════

def save_data():
    """Полный цикл загрузки и сохранения всех данных НХЛ."""
    print('🏒 Загрузка расписания...')
    sched = fetch_schedule()
    with open(f'{DATA_DIR}/schedule.json', 'w', encoding='utf-8') as f:
        json.dump(sched, f, ensure_ascii=False, indent=2)
    print(f'  ✅ Расписание: {len(sched["upcoming"])} предстоящих, {len(sched["finished"])} завершённых')

    print('🏒 Загрузка таблицы...')
    standings = fetch_standings()
    with open(f'{DATA_DIR}/standings.json', 'w', encoding='utf-8') as f:
        json.dump(standings, f, ensure_ascii=False, indent=2)
    print(f'  ✅ Таблица: {len(standings)} команд')

    print('🏒 Загрузка команд...')
    teams = fetch_teams()
    with open(f'{DATA_DIR}/teams.json', 'w', encoding='utf-8') as f:
        json.dump(teams, f, ensure_ascii=False, indent=2)
    print(f'  ✅ Команды: {len(teams)}')

    print('🏒 Загрузка игроков...')
    players = fetch_player_stats(limit_teams=5)
    with open(f'{DATA_DIR}/player_stats.json', 'w', encoding='utf-8') as f:
        json.dump(players, f, ensure_ascii=False, indent=2)
    print(f'  ✅ Игроки: {len(players)}')

    # Live updates в /tmp/live_scores_data.json
    print('🏒 Live-обновления...')
    updates = fetch_live_updates()
    existing = {}
    if os.path.exists(LIVE_PATH):
        try:
            with open(LIVE_PATH, encoding='utf-8') as f:
                existing = json.load(f)
        except:
            pass
    existing.update(updates)
    with open(LIVE_PATH, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    print(f'  ✅ Live: {len(updates)} обновлений')

    return {
        'upcoming': len(sched['upcoming']),
        'finished': len(sched['finished']),
        'standings': len(standings),
        'teams': len(teams),
        'players': len(players),
        'live': len(updates),
    }


# ═══════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print(f'🏒 NHL Data Fetch — {datetime.now().strftime("%d.%m.%Y %H:%M")} МСК')
    print(f'   Путь: {NHL_API}')
    r = save_data()
    print(f'\n✅ Итого: {r}')
