#!/usr/bin/env python3
"""
Обновление live-счетов матчей через ESPN API.

Запуск: каждые 15 минут днём (cron */15 10-20 * * *)
Результат: /tmp/live_scores_data.json — словарь ключ→матч с полями
  status: upcoming / live / finished
  score: X:Y или None

Зависимости: только requests (HTTP, 6 GET-запросов за запуск).
"""

import json, os, sys, requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from data_schemas import validate
from alert import report_success, report_failure, get_source_status
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '/opt')
from date_utils import today_storage, today_iso

# ─── MAP: лига → (ESPN sport_path, sport_type) ────────────────────
ESPN_PATHS = {
    'АПЛ':       ('soccer/eng.1', 'football'),
    'Ла Лига':   ('soccer/esp.1', 'football'),
    'Серия А':   ('soccer/ita.1', 'football'),
    'Бундеслига':('soccer/ger.1', 'football'),
    'Лига 1':    ('soccer/fra.1', 'football'),
    'РПЛ':       ('soccer/rus.1', 'football'),
    'НХЛ':       ('hockey/nhl', 'hockey'),
    'NBA':       ('basketball/nba', 'basketball'),
    'Лига чемпионов': ('soccer/uefa.champions', 'football'),
    'Лига Европы':    ('soccer/uefa.europa', 'football'),
    'Евролига':       ('basketball/uefa.euroleague', 'basketball'),
    'ATP':            ('tennis/atp', 'tennis'),
    'WTA':            ('tennis/wta', 'tennis'),
}

# ─── Перевод команд EN→RU (копия из daily_results.py) ──────────────
TEAMS_RU = {
    # АПЛ
    'Arsenal': 'Арсенал', 'Aston Villa': 'Астон Вилла', 'Bournemouth': 'Борнмут',
    'Brentford': 'Брентфорд', 'Brighton': 'Брайтон', 'Burnley': 'Бёрнли',
    'Chelsea': 'Челси', 'Crystal Palace': 'Кристал Пэлас', 'Everton': 'Эвертон',
    'Fulham': 'Фулхэм', 'Ipswich': 'Ипсвич', 'Leeds': 'Лидс',
    'Leicester': 'Лестер', 'Liverpool': 'Ливерпуль', 'Manchester City': 'Манчестер Сити',
    'Manchester United': 'Манчестер Юнайтед', 'Newcastle': 'Ньюкасл',
    'Newcastle United': 'Ньюкасл', 'Nottingham Forest': 'Ноттингем Форест',
    'Southampton': 'Саутгемптон', 'Sunderland': 'Сандерленд',
    'Tottenham': 'Тоттенхэм', 'West Ham': 'Вест Хэм', 'Wolves': 'Вулверхэмптон',
    'Wolverhampton Wanderers': 'Вулверхэмптон',
    # Ла Лига
    'Alaves': 'Алавес', 'Athletic Bilbao': 'Атлетик Бильбао', 'Athletic Club': 'Атлетик',
    'Atletico Madrid': 'Атлетико Мадрид', 'Barcelona': 'Барселона', 'Celta Vigo': 'Сельта',
    'Elche': 'Эльче', 'Espanyol': 'Эспаньол', 'Getafe': 'Хетафе',
    'Girona': 'Жирона', 'Las Palmas': 'Лас-Пальмас', 'Leganes': 'Леганес',
    'Levante': 'Леванте', 'Mallorca': 'Мальорка', 'Osasuna': 'Осасуна',
    'Rayo Vallecano': 'Райо Вальекано', 'Real Betis': 'Бетис', 'Real Madrid': 'Реал Мадрид',
    'Real Sociedad': 'Реал Сосьедад', 'Real Valladolid': 'Вальядолид',
    'Sevilla': 'Севилья', 'Valencia': 'Валенсия', 'Villarreal': 'Вильярреал',
    'Oviedo': 'Овьедо',
    # Серия А
    'Atalanta': 'Аталанта', 'Bologna': 'Болонья', 'Cagliari': 'Кальяри',
    'Como': 'Комо', 'Cremonese': 'Кремонезе', 'Empoli': 'Эмполи',
    'Fiorentina': 'Фиорентина', 'Genoa': 'Дженоа', 'Hellas Verona': 'Верона',
    'Inter': 'Интер', 'Juventus': 'Ювентус', 'Lazio': 'Лацио',
    'Lecce': 'Лечче', 'AC Milan': 'Милан', 'Milan': 'Милан',
    'Monza': 'Монца', 'Napoli': 'Наполи', 'Parma': 'Парма',
    'Pisa': 'Пиза', 'AS Roma': 'Рома', 'Roma': 'Рома',
    'Salernitana': 'Салернитана', 'Sassuolo': 'Сассуоло', 'Spezia': 'Специя',
    'Torino': 'Торино', 'Udinese': 'Удинезе', 'Venezia': 'Венеция',
    # Бундеслига
    'Augsburg': 'Аугсбург', 'Bayer Leverkusen': 'Байер', 'Bayer 04 Leverkusen': 'Байер',
    'Bayern Munich': 'Бавария', 'Bayern München': 'Бавария',
    'Borussia Monchengladbach': 'Боруссия М', 'Borussia Mönchengladbach': 'Боруссия М',
    'Eintracht Frankfurt': 'Айнтрахт', 'SC Freiburg': 'Фрайбург', 'Freiburg': 'Фрайбург',
    '1. FC Heidenheim 1846': 'Хайденхайм', 'Heidenheim': 'Хайденхайм',
    '1899 Hoffenheim': 'Хоффенхайм', 'TSG Hoffenheim': 'Хоффенхайм', 'Hoffenheim': 'Хоффенхайм',
    'Holstein Kiel': 'Хольштайн', '1. FC Koln': 'Кёльн', '1. FC Köln': 'Кёльн',
    'Köln': 'Кёльн', 'Mainz': 'Майнц', '1. FSV Mainz 05': 'Майнц',
    'Borussia Dortmund': 'Боруссия Д', 'RB Leipzig': 'РБ Лейпциг',
    'FC St. Pauli': 'Санкт-Паули', 'St. Pauli': 'Санкт-Паули',
    'VfB Stuttgart': 'Штутгарт', 'Stuttgart': 'Штутгарт',
    'Union Berlin': 'Унион Берлин', 'Werder Bremen': 'Вердер',
    'VfL Wolfsburg': 'Вольфсбург', 'Wolfsburg': 'Вольфсбург',
    'Hamburger SV': 'Гамбург', 'Hamburg': 'Гамбург',
    # Лига 1
    'Angers': 'Анже', 'Auxerre': 'Осер', 'Brest': 'Брест',
    'Le Havre': 'Гавр', 'Le Havre AC': 'Гавр',
    'Lens': 'Ланс', 'Lille': 'Лилль', 'Lorient': 'Лорьян',
    'Lyon': 'Лион', 'Marseille': 'Марсель', 'Metz': 'Мец',
    'AS Monaco': 'Монако', 'Monaco': 'Монако', 'Montpellier': 'Монпелье',
    'Nantes': 'Нант', 'Nice': 'Ницца', 'Paris Saint-Germain': 'ПСЖ',
    'PSG': 'ПСЖ', 'Paris FC': 'Париж', 'Paris Saint Germain': 'ПСЖ',
    'Rennes': 'Ренн', 'Reims': 'Реймс', 'Strasbourg': 'Страсбур',
    'Toulouse': 'Тулуза', 'Stade Brestois 29': 'Брест', 'Stade de Reims': 'Реймс',
    'Stade Rennais': 'Ренн',
    # РПЛ
    'Akhmat': 'Ахмат', 'Akhmat Grozny': 'Ахмат', 'Akron': 'Акрон',
    'CSKA Moscow': 'ЦСКА', 'Dynamo Moscow': 'Динамо', 'Dinamo Moscow': 'Динамо', 'Dynamo': 'Динамо',
    'Dinamo Makhachkala': 'Динамо Мх', 'Fakel': 'Факел',
    'FC Krasnodar': 'Краснодар', 'FC Orenburg': 'Оренбург', 'Gazovik Orenburg': 'Оренбург', 'FC Rostov': 'Ростов',
    'FC Sochi': 'Сочи', 'Khimki': 'Химки', 'Krylya Sovetov': 'Крылья Советов', 'Krylia Sovetov': 'Крылья Советов',
    'Lokomotiv': 'Локомотив', 'Lokomotiv Moscow': 'Локомотив',
    'Nizhny Novgorod': 'Пари НН', 'Paris NN': 'Пари НН',
    'Rubin': 'Рубин', 'Rubin Kazan': 'Рубин', 'Spartak Moscow': 'Спартак',
    'Spartak': 'Спартак', 'Zenit': 'Зенит', 'Zenit St. Petersburg': 'Зенит',
    'Baltika': 'Балтика', 'FC Baltika': 'Балтика', 'FC Baltika Kaliningrad': 'Балтика', 'Dynamo Makhachkala': 'Динамо Мх',

    # ─── НХЛ ───────────────────────────────────────────────────────────
    'Anaheim Ducks': 'Анахайм Дакс', 'Boston Bruins': 'Бостон Брюинз',
    'Buffalo Sabres': 'Баффало Сейбрз', 'Calgary Flames': 'Калгари Флэймз',
    'Carolina Hurricanes': 'Каролина Харрикейнз', 'Chicago Blackhawks': 'Чикаго Блэкхокс',
    'Colorado Avalanche': 'Колорадо Эвеланш', 'Columbus Blue Jackets': 'Коламбус Блю Джекетс',
    'Dallas Stars': 'Даллас Старз', 'Detroit Red Wings': 'Детройт Ред Уингз',
    'Edmonton Oilers': 'Эдмонтон Ойлерз', 'Florida Panthers': 'Флорида Пантерз',
    'Los Angeles Kings': 'Лос-Анджелес Кингз', 'Minnesota Wild': 'Миннесота Уайлд',
    'Montreal Canadiens': 'Монреаль Канадиенс', 'Nashville Predators': 'Нэшвилл Предаторз',
    'New Jersey Devils': 'Нью-Джерси Девилз', 'New York Islanders': 'Нью-Йорк Айлендерс',
    'New York Rangers': 'Нью-Йорк Рейнджерс', 'Ottawa Senators': 'Оттава Сенаторз',
    'Philadelphia Flyers': 'Филадельфия Флайерз', 'Pittsburgh Penguins': 'Питтсбург Пингвинз',
    'San Jose Sharks': 'Сан-Хосе Шаркс', 'Seattle Kraken': 'Сиэтл Кракен',
    'St. Louis Blues': 'Сент-Луис Блюз', 'Tampa Bay Lightning': 'Тампа-Бэй Лайтнинг',
    'Toronto Maple Leafs': 'Торонто Мэйпл Лифс', 'Utah Hockey Club': 'Юта',
    'Vancouver Canucks': 'Ванкувер Кэнакс', 'Vegas Golden Knights': 'Вегас Голден Найтс',
    'Washington Capitals': 'Вашингтон Кэпиталз', 'Winnipeg Jets': 'Виннипег Джетс',

    # ─── NBA ───────────────────────────────────────────────────────────
    'Atlanta Hawks': 'Атланта Хокс', 'Boston Celtics': 'Бостон Селтикс',
    'Brooklyn Nets': 'Бруклин Нетс', 'Charlotte Hornets': 'Шарлотт Хорнетс',
    'Chicago Bulls': 'Чикаго Буллз', 'Cleveland Cavaliers': 'Кливленд Кавальерс',
    'Dallas Mavericks': 'Даллас Маверикс', 'Denver Nuggets': 'Денвер Наггетс',
    'Detroit Pistons': 'Детройт Пистонс', 'Golden State Warriors': 'Голден Стэйт Уорриорз',
    'Houston Rockets': 'Хьюстон Рокетс', 'Indiana Pacers': 'Индиана Пэйсерс',
    'LA Clippers': 'ЛА Клипперс', 'Los Angeles Lakers': 'ЛА Лейкерс',
    'Memphis Grizzlies': 'Мемфис Гриззлиз', 'Miami Heat': 'Майами Хит',
    'Milwaukee Bucks': 'Милуоки Бакс', 'Minnesota Timberwolves': 'Миннесота Тимбервулвз',
    'New Orleans Pelicans': 'Нью-Орлеан Пеликанс', 'New York Knicks': 'Нью-Йорк Никс',
    'Oklahoma City Thunder': 'Оклахома-Сити Тандер', 'Orlando Magic': 'Орландо Мэджик',
    'Philadelphia 76ers': 'Филадельфия 76ерс', 'Phoenix Suns': 'Финикс Санз',
    'Portland Trail Blazers': 'Портленд Трэйл Блэйзерс', 'Sacramento Kings': 'Сакраменто Кингз',
    'San Antonio Spurs': 'Сан-Антонио Спёрс', 'Toronto Raptors': 'Торонто Рэпторс',
    'Utah Jazz': 'Юта Джаз', 'Washington Wizards': 'Вашингтон Уизардс',
}

# ─── ПУТИ ──────────────────────────────────────────────────────────
LIVE_PATH = '/tmp/live_scores_data.json'
MOW = timedelta(hours=3)
UTC = timezone.utc


import unicodedata


def _normalize(name):
    """Убрать диакритику для сравнения: Alavés → Alaves."""
    nfkd = unicodedata.normalize('NFKD', name)
    return nfkd.encode('ASCII', 'ignore').decode().lower().strip()


def ru(name):
    """EN → RU."""
    name_clean = name.strip()
    name_norm = _normalize(name_clean)
    
    # Точное совпадение (нормализованное)
    for eng, rus in TEAMS_RU.items():
        if _normalize(eng) == name_norm:
            return rus
    # Частичное совпадение
    for eng, rus in TEAMS_RU.items():
        eng_norm = _normalize(eng)
        if eng_norm in name_norm or name_norm in eng_norm:
            return rus
    return name_clean


def resolve_status(type_detail):
    """Определить статус матча по полю type.description из ESPN."""
    desc = (type_detail or '').lower()
    if desc in ('scheduled', 'postponed', 'canceled'):
        return 'upcoming'
    if desc in ('final', 'full time', 'finished', 'after extra time', 'after penalties'):
        return 'finished'
    # Всё остальное — live (First Half, Second Half, Half Time, In Progress, ...)
    if desc and desc != 'pre-game':
        return 'live'
    return 'upcoming'


def fetch_league(path, date_str, sport_type='football'):
    """Завершённые матчи лиги за дату через ESPN API.
    Возвращает (matches, league_name) — matches с competition_id.
    """
    url = f'https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={date_str}'
    try:
        resp = requests.get(url, timeout=15)
        data = resp.json()
    except Exception as e:
        print(f'  ❌ ESPN error: {e}')
        return [], None

    # Определяем название лиги из пути
    league_map = {v[0]: k for k, v in ESPN_PATHS.items()}
    league_name = league_map.get(path, '')

    matches = []
    for e in data.get('events', []):
        comp = e.get('competitions', [{}])[0]
        status = comp.get('status', {}).get('type', {})
        type_detail = status.get('description', '')
        state = status.get('state', '')

        teams = comp.get('competitors', [])
        if len(teams) < 2:
            continue

        home_name = ru(teams[0].get('team', {}).get('displayName', '?'))
        away_name = ru(teams[1].get('team', {}).get('displayName', '?'))

        # Счёт (только для live/finished — ESPN показывает 0:0 для upcoming)
        status_str = resolve_status(type_detail)
        home_score = teams[0].get('score')
        away_score = teams[1].get('score')
        if status_str != 'upcoming' and home_score is not None and away_score is not None:
            score = f'{home_score}:{away_score}'
        else:
            score = None

        # Время начала матча (конвертируем из UTC в МСК)
        match_time_iso = comp.get('date', e.get('date', ''))
        try:
            match_dt = datetime.fromisoformat(match_time_iso.replace('Z', '+00:00')).replace(tzinfo=UTC)
            match_dt_msk = match_dt + MOW
            match_time_str = match_dt_msk.strftime('%H:%M')
        except:
            match_time_str = ''

        matches.append({
            'home': home_name,
            'away': away_name,
            'score': score,
            'status': status_str,
            'status_detail': type_detail,
            'match_time': match_time_str,
            'competition_id': comp.get('id'),
            'sport_path': path,
            'sport': sport_type,
        })

    return matches, league_name


def _fetch_live_stats(competition_id, sport_path):
    """Получить детальную статистику для live-матча из ESPN boxscore."""
    url = f'https://site.api.espn.com/apis/site/v2/sports/{sport_path}/summary?event={competition_id}'
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
    except:
        return None

    bs = data.get('boxscore', {})
    if not isinstance(bs, dict):
        return None

    teams_stats = {}
    for t in bs.get('teams', []):
        name = t.get('team', {}).get('displayName', '?')
        stats_list = {}
        for s in t.get('statistics', []):
            stats_list[s.get('name')] = s.get('displayValue')
        teams_stats[ru(name)] = stats_list

    return teams_stats


# ─── Карта flashscore-лиг ──────────────────────────────────────────
FLASHSCORE_LEAGUES = {
    'world-cup-hockey': ('ЧМ по хоккею', '🏒', 'hockey'),
    'khl':              ('КХЛ',          '🏒', 'hockey'),
    'vtb':              ('Лига ВТБ',     '🏀', 'basketball'),
    'euroleague':       ('Евролига',     '🏀', 'basketball'),
}


def _fetch_flashscore_league(league_key, all_matches, now):
    """Универсальный сбор live+upcoming+finished для flashscore-лиги.
    Добавляет только те матчи, которых ещё нет в all_matches (fallback).
    """
    import re as _re
    def _clean_time(t):
        if not t:
            return ''
        # Убираем текст после времени: "19.05. 18:20\nПосле\nбул." → "19.05. 18:20"
        t = t.split('\n')[0].strip()
        return t

    info = FLASHSCORE_LEAGUES.get(league_key)
    if not info:
        return 0, 0
    league_name, emoji, sport = info

    added_live = 0
    added_finished = 0

    try:
        sys.path.insert(0, '/root/.openclaw/workspace/odds')
        from flashscore_other import fetch_upcoming_live, fetch_results

        # 1. Предстоящие + live (основная страница)
        fs_live, _ = fetch_upcoming_live(league_key)
        for m in fs_live:
            if not isinstance(m, dict):
                continue
            key = f'{league_name}||{m["home"]}||{m["away"]}'
            if key in all_matches:
                continue  # уже есть из ESPN

            # Используем статус из flashscore, если есть
            fs_status = m.get('status', '')
            score = m.get('score', '')
            has_score = bool(score and score not in ('-', '-:-', ''))

            if fs_status in ('live', 'finished'):
                status = fs_status
            elif has_score:
                mt = m.get('time', '')
                if not mt:
                    status = 'live'
                else:
                    status = 'finished'
            else:
                status = 'upcoming'

            _time = _clean_time(m.get('time', ''))
            all_matches[key] = {
                'league': league_name,
                'home': m['home'],
                'away': m['away'],
                'score': score if has_score else '',
                'status': status,
                'status_detail': '',
                'match_time': _time,
                'sport': sport,
                'updated_at': now.isoformat(),
            }
            added_live += 1

        # 2. Завершённые (результаты)
        fs_finished, _ = fetch_results(league_key)
        for m in fs_finished:
            if not isinstance(m, dict):
                continue
            key = f'{league_name}||{m["home"]}||{m["away"]}'
            if key in all_matches:
                existing = all_matches[key]
                if existing['status'] == 'live':
                    continue  # не перезаписываем live
                if existing['status'] == 'finished':
                    continue  # уже завершён
                # Результат из устаревшего upcoming — обновляем (score есть, статус finished)
                existing['score'] = m.get('score', '')
                existing['status'] = 'finished'
                existing['status_detail'] = 'final'
                existing['match_time'] = _clean_time(m.get('time', ''))
                existing['updated_at'] = now.isoformat()
                added_finished += 1
                continue

            _time = _clean_time(m.get('time', ''))
            all_matches[key] = {
                'league': league_name,
                'home': m['home'],
                'away': m['away'],
                'score': m.get('score', ''),
                'status': 'finished',
                'status_detail': 'final',
                'match_time': _time,
                'sport': sport,
                'updated_at': now.isoformat(),
            }
            added_finished += 1

        print(f'  {emoji} {league_name}: {len(fs_live)} pre+live, {len(fs_finished)} finished (+{added_live}+{added_finished} новых)')

    except Exception as e:
        print(f'  ⚠️ flashscore {league_name}: {e}')

    return added_live, added_finished


def main():
    now = datetime.now(UTC)
    now_msk = now + MOW  # MSK — для определения «сегодня»
    date_str = today_storage()
    print(f'📡 Fetching live scores for {date_str}')

    all_matches = {}
    live_matches_for_stats = []  # (key, competition_id, sport_path)

    # ═══ ThreadPool 6 workers для ESPN ═══
    _espn_results = []
    _espn_lock = __import__('threading').Lock()

    def _fetch_one_league(league_name, path, sport_type):
        """Загрузить одну лигу из ESPN (для ThreadPool)."""
        try:
            matches, _ = fetch_league(path, date_str, sport_type)
            return league_name, matches, None
        except Exception as e:
            return league_name, [], str(e)

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(_fetch_one_league, name, path, st): name
            for name, (path, st) in ESPN_PATHS.items()
        }
        for future in as_completed(futures):
            league_name = futures[future]
            try:
                _, matches, error = future.result()
                if error:
                    print(f'  ⚠️ {league_name}: {error}')
                    report_failure(f'espn_{league_name}', error)
                else:
                    print(f'  ✅ {league_name}: {len(matches)} матчей (thread)')
                    report_success(f'espn_{league_name}')
                    _espn_results.append((league_name, matches))
            except Exception as e:
                print(f'  ❌ {league_name}: {e}')
                report_failure(f'espn_{league_name}', str(e))

    # Объединяем результаты из всех потоков
    for league_name, matches in _espn_results:
        for m in matches:
            key = f'{league_name}||{m["home"]}||{m["away"]}'
            all_matches[key] = {
                'league': league_name,
                'home': m['home'],
                'away': m['away'],
                'score': m['score'],
                'status': m['status'],
                'status_detail': m.get('status_detail', ''),
                'match_time': m.get('match_time', ''),
                'sport': m.get('sport', 'football'),
                'updated_at': now.isoformat(),
            }
            if m['status'] == 'live' and m.get('competition_id'):
                live_matches_for_stats.append((key, m['competition_id'], m['sport_path']))

    # ── Статистика для live-матчей ──
    if live_matches_for_stats:
        print(f'\n📊 Fetching live stats for {len(live_matches_for_stats)} матчей...')
        for key, comp_id, sport_path in live_matches_for_stats:
            stats = _fetch_live_stats(comp_id, sport_path)
            if stats:
                all_matches[key]['stats'] = stats
                print(f'  ✅ {key}: {len(stats)} команд')
            else:
                print(f'  ⚠️ {key}: нет статистики')

    # ── NHL API (дополнительный источник для НХЛ) ──
    try:
        from fetch_nhl_data import fetch_schedule
        from nhl_api import ru as nhl_ru
        nhl_data = fetch_schedule()
        for match in nhl_data.get('upcoming', []) + nhl_data.get('finished', []):
            home_ru = match.get('home_ru', '') or nhl_ru(match.get('home', ''))
            away_ru = match.get('away_ru', '') or nhl_ru(match.get('away', ''))
            key = f'НХЛ||{home_ru}||{away_ru}'
            state = match.get('game_state', '')
            if state == 'FUT':
                status = 'upcoming'
            elif state == 'LIVE':
                status = 'live'
            elif state in ('OFF', 'FINAL'):
                status = 'finished'
            else:
                status = 'upcoming'
            score = match.get('score', '')
            if not score and match.get('home_score') is not None:
                score = f"{match.get('home_score', '?')}:{match.get('away_score', '?')}"
            all_matches[key] = {
                'league': 'НХЛ',
                'home': home_ru,
                'away': away_ru,
                'score': score or '',
                'status': status,
                'status_detail': state,
                'match_time': match.get('time', ''),
                'sport': 'hockey',
                'updated_at': now.isoformat(),
            }
        print(f'  🏒 NHL API: {len(nhl_data.get("upcoming",[]))} предстоящих, {len(nhl_data.get("finished",[]))} завершённых')
    except Exception as e:
        print(f'  ⚠️ NHL API: {e}')

    # ── Flashscore для лиг (fallback к ESPN) + DB ──
    try:
        sys.path.insert(0, '/opt')
        import db as _db
        today_msk = today_iso()
        db_matches = _db.execute(
            "SELECT * FROM matches WHERE match_date = %s AND status = 'scheduled' ORDER BY match_time",
            (today_msk,)
        )

        # Flashscore: ЧМ, КХЛ, ВТБ, Евролига (пропускает матчи уже из ESPN)
        for league_key in FLASHSCORE_LEAGUES:
            _fetch_flashscore_league(league_key, all_matches, now)

        # DB — заполняем оставшиеся как upcoming
        for m in db_matches:
            key = f'{m["league"]}||{m["home"]}||{m["away"]}'
            if key not in all_matches:
                all_matches[key] = {
                    'league': m['league'],
                    'home': m['home'],
                    'away': m['away'],
                    'score': '',
                    'status': 'upcoming',
                    'status_detail': '',
                    'match_time': m.get('match_time', ''),
                    'sport': 'hockey' if 'хоккей' in str(m.get('league', '')).lower()
                             else 'basketball' if 'втб' in str(m.get('league', '')).lower() or 'евролиг' in str(m.get('league', '')).lower()
                             else 'tennis' if m.get('league') in ('ATP', 'WTA')
                             else 'football',
                    'updated_at': now.isoformat(),
                }
        if db_matches:
            print(f'  📋 +{len(db_matches)} матчей из расписания')
    except Exception as e:
        print(f'  ⚠️ Ошибка загрузки из БД: {e}')

    # ── Детекция финишировавших матчей ──
    # Сравниваем с предыдущим состоянием, чтобы не триггерить повторно
    finished_keys = []
    prev_matches = {}
    if os.path.exists(LIVE_PATH):
        try:
            with open(LIVE_PATH, encoding='utf-8') as f:
                prev_data = json.load(f)
            prev_matches = prev_data.get('matches', {})
        except:
            pass

    for key, match in all_matches.items():
        if match['status'] == 'finished':
            prev = prev_matches.get(key, {})
            prev_status = prev.get('status', '')
            # Матч только что завершился (был live или upcoming — стал finished)
            if prev_status in ('live', 'upcoming', ''):
                finished_keys.append(key)

    if finished_keys:
        print(f'\n🏁 Финишировало матчей: {len(finished_keys)}')
        try:
            import subprocess
            for key in finished_keys:
                match = all_matches[key]
                print(f'  ✅ {match["home"]} — {match["away"]} ({match["score"]})')
            # Запускаем evaluate в фоне
            subprocess.Popen(
                ['python3', '/opt/evaluate_predictions.py'],
                cwd='/opt',
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # Триггерим регенерацию расписания (с debounce)
            try:
                from capper_common import trigger_generate
                trigger_generate('schedule')
            except Exception as tge:
                print(f'  ⚠️ trigger_generate: {tge}')
        except Exception as e:
            print(f'  ⚠️ Ошибка запуска evaluate: {e}')
    else:
        print()

    output = {
        'updated_at': now.isoformat(),
        'matches': all_matches,
    }

    # Валидация перед записью
    ok, errs = validate(output, 'live_scores')
    if not ok:
        print(f'  ❌ live_scores не прошёл валидацию: {errs}')
        # Не пишем битые данные — сайт покажет предыдущую версию
        import shutil
        if os.path.exists(LIVE_PATH):
            shutil.copy2(LIVE_PATH, '/var/www/sport/live_scores.json')
        return []

    # Атомарная запись: пишем в .tmp, потом переименовываем
    tmp_path = LIVE_PATH + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    os.rename(tmp_path, LIVE_PATH)

    # Копируем в web-root для клиентского JS
    try:
        import shutil
        shutil.copy2(LIVE_PATH, '/var/www/sport/live_scores.json')
    except:
        pass

    # Print summary
    statuses = {}
    stats_count = 0
    for m in all_matches.values():
        s = m['status']
        statuses[s] = statuses.get(s, 0) + 1
        if 'stats' in m:
            stats_count += 1
    live_count = statuses.get('live', 0)
    upcoming_count = statuses.get('upcoming', 0)
    print(f'\n✅ Сохранено: {len(all_matches)} матчей ({stats_count} со статистикой)')
    for s, c in statuses.items():
        print(f'  {s}: {c}')

    # ── Само-расписание ──
    _schedule_next(live_count, upcoming_count, all_matches)


SCHEDULED_FLAG = '/tmp/.fetch_live_scores_scheduled'


def _schedule_next(live_count, upcoming_count, all_matches):
    """Спланировать следующий запуск.
    - Если есть live → через 5 мин
    - Если live нет, но есть upcoming → в момент старта первого матча
    - Если ничего нет → не планируем
    """
    import subprocess
    now = datetime.now(UTC)

    if live_count > 0:
        # Есть live — планируем через 5 минут
        cmd = f'cd /opt && python3 fetch_live_scores.py'
        echo = subprocess.run(
            ['at', 'now', '+', '5', 'minutes'],
            input=cmd,
            capture_output=True,
            text=True,
            timeout=10
        )
        with open(SCHEDULED_FLAG, 'w') as f:
            f.write(str(int(now.timestamp())))
        print(f'  🕐 Следующий запуск через 5 минут (live: {live_count})')
        return

    # Нет live — ищем ближайший upcoming
    earliest_start = None
    for m in all_matches.values():
        if m.get('status') != 'upcoming':
            continue
        mt = m.get('match_time', '')
        if not mt:
            continue
        try:
            hour, minute = mt.split(':')
            match_dt = now.replace(hour=int(hour), minute=int(minute), second=0)
            if match_dt < now:
                match_dt += timedelta(days=1)
            if earliest_start is None or match_dt < earliest_start:
                earliest_start = match_dt
        except:
            pass

    if earliest_start:
        # Планируем за 5 минут до начала первого матча
        schedule_at = earliest_start - timedelta(minutes=5)
        if schedule_at > now:
            delay_min = int((schedule_at - now).total_seconds() / 60)
            if delay_min > 0:
                cmd = f'cd /opt && python3 fetch_live_scores.py'
                echo = subprocess.run(
                    ['at', 'now', '+', str(delay_min), 'minutes'],
                    input=cmd,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                with open(SCHEDULED_FLAG, 'w') as f:
                    f.write(str(int(now.timestamp())))
                print(f'  🕐 Следующий запуск через {delay_min} мин (до начала матча)')
                return

    # Ничего не осталось — удаляем флаг
    if os.path.exists(SCHEDULED_FLAG):
        os.remove(SCHEDULED_FLAG)
    print(f'  💤 Нет матчей на сегодня. До завтра.')


if __name__ == '__main__':
    try:
        main()
        report_success('fetch_live_scores')
    except Exception as e:
        report_failure('fetch_live_scores', str(e))
        raise
