#!/usr/bin/env python3
"""
Ежедневный дайджест результатов за прошедшие сутки.
Запуск: ежедневно в 9:00 МСК через sport_bot.py
Собирает: футбол (SStats) + хоккей (ESPN/NHL API + КХЛ) + баскетбол (ESPN NBA)
Отправляет в канал @zula_sport_news
"""

import json, requests, subprocess, os, sys, glob, re
from datetime import datetime, timedelta, timezone



# flashscore парсер для ВТБ, Euroleague, ЧМ по хоккею
sys.path.insert(0, '/root/.openclaw/workspace/odds')
import importlib
flashscore_other = importlib.import_module('flashscore_other')

sys.path.insert(0, '/opt')
from date_utils import normalize_date, format_date_display, today_storage, yesterday_storage
import tennis_names
import nhl_api
import balldontlie_api

# ─── КОНФИГУРАЦИЯ ───────────────────────────────────────────────────
SSTATS_KEY = open('/etc/sstats.key').read().strip()
BOT_TOKEN = "8431200157:AAF-vgf6D3AGokWMmOUgzUfffKlCwDz3uwQ"
CHANNEL_ID = "-1003928523816"

MOW = timedelta(hours=3)
UTC = timezone.utc


# ─── ТЕННИС: фильтрация турниров ────────────────────────────────────
# Grand Slams — отлавливаются через `major: true` в ESPN
# Masters 1000 / WTA 1000 — по ключевым словам в названии турнира
MASTERS_1000_KEYWORDS = [
    'indian wells',        # BNP Paribas Open
    'miami open',          # Miami Open
    'miami presented',
    'monte-carlo',         # Rolex Monte-Carlo Masters
    'madrid',              # Mutua Madrid Open
    'internazionali bnl',  # Internazionali BNL d'Italia (Rome)
    'italian open',
    'rolex rome',
    'canada',              # Canadian Open (Montreal/Toronto)
    'national bank open',
    'cincinnati',          # Cincinnati Open
    'shanghai',            # Shanghai Masters (ATP only)
    'paris masters',       # Rolex Paris Masters (ATP only)
    'paris rolex',
    'wuhan',               # Wuhan Open (WTA 1000)
    'beijing open',        # China Open (WTA 1000)
    'guadalajara',         # Guadalajara Open (WTA 1000)
    'dubai tennis',        # Dubai Championships (WTA 1000)
    'dubai duty free',
    'qatar totalenergies', # Qatar Open (WTA 1000)
]

TENNIS_GROUPINGS_ALLOWED = {'mens-singles', 'womens-singles'}

TENNIS_ROUND_EMOJI = {
    'final': 'Финал',
    'semifinal': '1/2',
    'quarterfinal': '1/4',
    'round 4': 'Раунд 4',
    'round 3': 'Раунд 3',
    'round 2': 'Раунд 2',
    'round 1': 'Раунд 1',
}

SSTATS_LEAGUES = {
    39:  ('АПЛ', '🏴󠁧󠁢󠁥󠁮󠁧󠁿'),
    140: ('Ла Лига', '🇪🇸'),
    135: ('Серия А', '🇮🇹'),
    78:  ('Бундеслига', '🇩🇪'),
    61:  ('Лига 1', '🇫🇷'),
    235: ('РПЛ', '🇷🇺'),
    2:   ('Лига Чемпионов', '⭐'),
    3:   ('Лига Европы', '🌙'),
    848: ('Лига Конференций', '💫'),
    1:   ('Чемпионат Мира', '🌍'),
    4:   ('Чемпионат Европы', '🏆'),
}

# ─── ПЕРЕВОД КОМАНД НА РУССКИЙ ──────────────────────────────────────
TEAMS_RU = {
    # ═══ АПЛ ═══
    'Arsenal': 'Арсенал', 'Aston Villa': 'Астон Вилла', 'Bournemouth': 'Борнмут',
    'Brentford': 'Брентфорд', 'Brighton': 'Брайтон', 'Burnley': 'Бёрнли',
    'Chelsea': 'Челси', 'Crystal Palace': 'Кристал Пэлас', 'Everton': 'Эвертон',
    'Fulham': 'Фулхэм', 'Ipswich': 'Ипсвич', 'Leeds': 'Лидс',
    'Leicester': 'Лестер', 'Liverpool': 'Ливерпуль', 'Manchester City': 'Манчестер Сити',
    'Manchester United': 'Манчестер Юнайтед', 'Newcastle': 'Ньюкасл', 'Newcastle United': 'Ньюкасл',
    'Nottingham Forest': 'Ноттингем Форест', 'Southampton': 'Саутгемптон',
    'Sunderland': 'Сандерленд', 'Tottenham': 'Тоттенхэм', 'West Ham': 'Вест Хэм',
    'Wolves': 'Вулверхэмптон',

    # ═══ Ла Лига ═══
    'Alaves': 'Алавес', 'Athletic Bilbao': 'Атлетик Бильбао', 'Athletic Club': 'Атлетик',
    'Atletico Madrid': 'Атлетико Мадрид', 'Barcelona': 'Барселона', 'Celta Vigo': 'Сельта',
    'Elche': 'Эльче', 'Espanyol': 'Эспаньол', 'Getafe': 'Хетафе',
    'Girona': 'Жирона', 'Las Palmas': 'Лас-Пальмас', 'Leganes': 'Леганес',
    'Levante': 'Леванте', 'Mallorca': 'Мальорка', 'Osasuna': 'Осасуна',
    'Oviedo': 'Овьедо', 'Rayo Vallecano': 'Райо Вальекано', 'Real Betis': 'Бетис',
    'Real Madrid': 'Реал Мадрид', 'Real Sociedad': 'Реал Сосьедад',
    'Sevilla': 'Севилья', 'Valencia': 'Валенсия', 'Villarreal': 'Вильярреал',
    'Real Oviedo': 'Реал Овьедо', 'Huesca': 'Уэска',

    # ═══ Серия А ═══
    'AC Milan': 'Милан', 'Atalanta': 'Аталанта', 'Bologna': 'Болонья',
    'Cagliari': 'Кальяри', 'Como': 'Комо', 'Cremonese': 'Кремонезе',
    'Empoli': 'Эмполи', 'Fiorentina': 'Фиорентина', 'Genoa': 'Дженоа',
    'Hellas Verona': 'Верона', 'Inter': 'Интер', 'Juventus': 'Ювентус',
    'Lazio': 'Лацио', 'Lecce': 'Лечче', 'Milan': 'Милан',
    'Monza': 'Монца', 'Napoli': 'Наполи', 'Parma': 'Парма',
    'Pisa': 'Пиза', 'Roma': 'Рома', 'AS Roma': 'Рома',
    'Salernitana': 'Салернитана', 'Sassuolo': 'Сассуоло', 'Spezia': 'Специя',
    'Torino': 'Торино', 'Udinese': 'Удинезе', 'Venezia': 'Венеция',

    # ═══ Бундеслига ═══
    '1. FC Köln': 'Кёльн', '1. FC Heidenheim': 'Хайденхайм', '1. FC Kaiserslautern': 'Кайзерслаутерн',
    '1. FC Nürnberg': 'Нюрнберг', '1. FSV Mainz 05': 'Майнц', 'Bayer Leverkusen': 'Байер',
    'Bayern München': 'Бавария', 'Borussia Dortmund': 'Боруссия Д', 'Borussia Mönchengladbach': 'Боруссия М',
    'Darmstadt 98': 'Дармштадт', 'Eintracht Frankfurt': 'Айнтрахт', 'FC Augsburg': 'Аугсбург',
    'FC Bayern München': 'Бавария', 'FC St. Pauli': 'Санкт-Паули', 'Freiburg': 'Фрайбург',
    'FSV Mainz 05': 'Майнц', 'Hamburger SV': 'Гамбург', 'Hannover 96': 'Ганновер',
    'Hertha BSC': 'Герта', 'Hoffenheim': 'Хоффенхайм', 'Holstein Kiel': 'Хольштайн Киль',
    'RB Leipzig': 'РБ Лейпциг', 'SC Freiburg': 'Фрайбург', 'TSG 1899 Hoffenheim': 'Хоффенхайм',
    'Union Berlin': 'Унион Берлин', 'VfB Stuttgart': 'Штутгарт', 'VfL Wolfsburg': 'Вольфсбург',
    'Werder Bremen': 'Вердер', '1. FC Köln': 'Кёльн', 'SV Darmstadt 98': 'Дармштадт',
    'VfL Bochum': 'Бохум', '1. FC Heidenheim': 'Хайденхайм',
    'Hannover 96': 'Ганновер',

    # ═══ Лига 1 ═══
    'Angers': 'Анже', 'Auxerre': 'Осер', 'Brest': 'Брест',
    'Clermont': 'Клермон', 'Lens': 'Ланс', 'Le Havre': 'Гавр',
    'Lille': 'Лилль', 'Lorient': 'Лорьян', 'Lyon': 'Лион',
    'Marseille': 'Марсель', 'Metz': 'Мец', 'Monaco': 'Монако',
    'Montpellier': 'Монпелье', 'Nantes': 'Нант', 'Nice': 'Ницца',
    'Nimes': 'Ним', 'Paris Saint Germain': 'ПСЖ', 'Paris FC': 'Париж',
    'Reims': 'Реймс', 'Rennes': 'Ренн', 'Stade Brestois 29': 'Брест',
    'Stade de Reims': 'Реймс', 'Stade Rennais': 'Ренн', 'Strasbourg': 'Страсбур',
    'Toulouse': 'Тулуза', 'Le Havre': 'Гавр', 'FC Paris': 'Париж',

    # ═══ РПЛ ═══
    'FC Orenburg': 'Оренбург', 'Orenburg': 'Оренбург', 'Krylia Sovetov': 'Крылья Советов',
    'Zenit': 'Зенит', 'FC Sochi': 'Сочи', 'Akhmat': 'Ахмат',
    'Dinamo Makhachkala': 'Динамо Мх', 'Lokomotiv': 'Локомотив', 'Lokomotiv Moscow': 'Локомотив',
    'Baltika': 'Балтика', 'Dynamo': 'Динамо', 'Dynamo Moscow': 'Динамо Москва',
    'Spartak Moscow': 'Спартак', 'CSKA Moscow': 'ЦСКА', 'Rubin': 'Рубин',
    'FC Rostov': 'Ростов', 'Rostov': 'Ростов', 'Akron': 'Акрон',
    'Nizhny Novgorod': 'Пари НН', 'FC Krasnodar': 'Краснодар', 'Krasnodar': 'Краснодар',
    'FC Akhmat': 'Ахмат',

    # ═══ НХЛ ═══
    'Anaheim Ducks': 'Анахайм Дакс', 'Arizona Coyotes': 'Аризона Койотис',
    'Boston Bruins': 'Бостон Брюинз', 'Buffalo Sabres': 'Баффало Сейбрз',
    'Calgary Flames': 'Калгари Флэймз', 'Carolina Hurricanes': 'Каролина Харрикейнз',
    'Chicago Blackhawks': 'Чикаго Блэкхокс', 'Colorado Avalanche': 'Колорадо Эвеланш',
    'Columbus Blue Jackets': 'Коламбус Блю Джекетс', 'Dallas Stars': 'Даллас Старз',
    'Detroit Red Wings': 'Детройт Ред Уингз', 'Edmonton Oilers': 'Эдмонтон Ойлерз',
    'Florida Panthers': 'Флорида Пантерз', 'Los Angeles Kings': 'Лос-Анджелес Кингз',
    'Minnesota Wild': 'Миннесота Уайлд', 'Montreal Canadiens': 'Монреаль Канадиенс',
    'Nashville Predators': 'Нэшвилл Предаторз', 'New Jersey Devils': 'Нью-Джерси Девилз',
    'New York Islanders': 'Нью-Йорк Айлендерс', 'New York Rangers': 'Нью-Йорк Рейнджерс',
    'Ottawa Senators': 'Оттава Сенаторз', 'Philadelphia Flyers': 'Филадельфия Флайерз',
    'Pittsburgh Penguins': 'Питтсбург Пингвинз', 'San Jose Sharks': 'Сан-Хосе Шаркс',
    'Seattle Kraken': 'Сиэтл Кракен', 'St. Louis Blues': 'Сент-Луис Блюз',
    'Tampa Bay Lightning': 'Тампа-Бэй Лайтнинг', 'Toronto Maple Leafs': 'Торонто Мэйпл Лифс',
    'Utah Hockey Club': 'Юта', 'Vancouver Canucks': 'Ванкувер Кэнакс',
    'Vegas Golden Knights': 'Вегас Голден Найтс', 'Washington Capitals': 'Вашингтон Кэпиталз',
    'Winnipeg Jets': 'Виннипег Джетс',

    # ═══ NBA ═══
    'Atlanta Hawks': 'Атланта Хокс', 'Boston Celtics': 'Бостон Селтикс',
    'Brooklyn Nets': 'Бруклин Нетс', 'Charlotte Hornets': 'Шарлотт Хорнетс',
    'Chicago Bulls': 'Чикаго Буллз', 'Cleveland Cavaliers': 'Кливленд Кавальерс',
    'Dallas Mavericks': 'Даллас Маверикс', 'Denver Nuggets': 'Денвер Наггетс',
    'Detroit Pistons': 'Детройт Пистонс', 'Golden State Warriors': 'Голден Стэйт Уорриорз',
    'Houston Rockets': 'Хьюстон Рокетс', 'Indiana Pacers': 'Индиана Пэйсерс',
    'LA Clippers': 'ЛА Клипперс', 'Los Angeles Lakers': 'ЛА Лейкерс',
    'Memphis Grizzlies': 'Мемфис Гриззлис', 'Miami Heat': 'Майами Хит',
    'Milwaukee Bucks': 'Милуоки Бакс', 'Minnesota Timberwolves': 'Миннесота Тимбервулвз',
    'New Orleans Pelicans': 'Нью-Орлеан Пеликанс', 'New York Knicks': 'Нью-Йорк Никс',
    'Oklahoma City Thunder': 'Оклахома-Сити Тандер', 'Orlando Magic': 'Орландо Мэджик',
    'Philadelphia 76ers': 'Филадельфия Сиксерс', 'Phoenix Suns': 'Финикс Санз',
    'Portland Trail Blazers': 'Портленд Трэйл Блэйзерс', 'Sacramento Kings': 'Сакраменто Кингз',
    'San Antonio Spurs': 'Сан-Антонио Спёрс', 'Toronto Raptors': 'Торонто Рэпторс',
    'Utah Jazz': 'Юта Джаз', 'Washington Wizards': 'Вашингтон Уизардс',
}

# Сборный бо́льший словарь для неполных совпадений и имён с приставками
TEAMS_RU_EXTRA = {
    'Manchester City': 'Манчестер Сити', 'Manchester Utd': 'Манчестер Юнайтед',
    'Newcastle': 'Ньюкасл', 'Tottenham': 'Тоттенхэм',
    'Athletic Bilbao': 'Атлетик', 'Barcelona': 'Барселона',
    'Real Madrid': 'Реал Мадрид', 'Atletico': 'Атлетико',
    'Bayern': 'Бавария', 'Dortmund': 'Боруссия Д',
    'Leverkusen': 'Байер', 'Leipzig': 'РБ Лейпциг',
    'Gladbach': 'Боруссия М', 'Wolfsburg': 'Вольфсбург',
    'Stuttgart': 'Штутгарт', 'Augsburg': 'Аугсбург',
    'Frankfurt': 'Айнтрахт', 'Bremen': 'Вердер',
    'Mainz': 'Майнц', 'Freiburg': 'Фрайбург',
    'Hoffenheim': 'Хоффенхайм', 'Heidenheim': 'Хайденхайм',
    'Union Berlin': 'Унион Берлин', 'St. Pauli': 'Санкт-Паули',
    'Köln': 'Кёльн', 'Hamburg': 'Гамбург', 'Hamburger': 'Гамбург',
    'Kiel': 'Киль', 'Bochum': 'Бохум', 'Hannover': 'Ганновер',
    'Darmstadt': 'Дармштадт', 'Nürnberg': 'Нюрнберг',
    'Kaiserslautern': 'Кайзерслаутерн', 'Magdeburg': 'Магдебург',
    'Düsseldorf': 'Дюссельдорф', 'Elversberg': 'Эльферсберг',
    'Münster': 'Мюнстер', 'Braunschweig': 'Брауншвейг',
    'Dresden': 'Дрезден', 'Preußen Münster': 'Мюнстер',
    'Fortuna Düsseldorf': 'Дюссельдорф', 'Hertha BSC': 'Герта',
    'Greuther Fürth': 'Гройтер Фюрт', 'Eintracht Braunschweig': 'Брауншвейг',
    'Dynamo Dresden': 'Динамо Дрезден', 'SV Elversberg': 'Эльферсберг',
    'Hannover 96': 'Ганновер', 'Schalke': 'Шальке',
    'FC Schalke 04': 'Шальке',
    'Marseille': 'Марсель', 'Lyon': 'Лион', 'Monaco': 'Монако',
    'Lille': 'Лилль', 'Nice': 'Ницца', 'Rennes': 'Ренн',
    'Lens': 'Ланс', 'Strasbourg': 'Страсбур', 'Montpellier': 'Монпелье',
    'Toulouse': 'Тулуза', 'Nantes': 'Нант', 'Angers': 'Анже',
    'Reims': 'Реймс', 'Metz': 'Мец', 'Brest': 'Брест',
    'Auxerre': 'Осер', 'Lorient': 'Лорьян', 'Le Havre': 'Гавр',
    'Saint-Étienne': 'Сент-Этьен',
    'Paris Saint Germain': 'ПСЖ', 'Saint-Etienne': 'Сент-Этьен',
    'Clermont Foot': 'Клермон',
    'Montreal': 'Монреаль', 'Toronto': 'Торонто', 'Vancouver': 'Ванкувер',
    'Canadiens': 'Монреаль', 'Maple Leafs': 'Торонто', 'Canucks': 'Ванкувер',
    'Oilers': 'Эдмонтон', 'Flames': 'Калгари', 'Jets': 'Виннипег',
    'Senators': 'Оттава', 'Red Wings': 'Детройт', 'Penguins': 'Питтсбург',
    'Bruins': 'Бостон', 'Rangers': 'Рейнджерс', 'Islanders': 'Айлендерс',
    'Devils': 'Нью-Джерси', 'Flyers': 'Филадельфия', 'Capitals': 'Вашингтон',
    'Hurricanes': 'Каролина', 'Panthers': 'Флорида', 'Lightning': 'Тампа-Бэй',
    'Predators': 'Нэшвилл', 'Stars': 'Даллас', 'Blues': 'Сент-Луис',
    'Avalanche': 'Колорадо', 'Wild': 'Миннесота', 'Blackhawks': 'Чикаго',
    'Blue Jackets': 'Коламбус', 'Sabres': 'Баффало', 'Red Wings': 'Детройт',
    'Sharks': 'Сан-Хосе', 'Ducks': 'Анахайм', 'Kings': 'ЛА Кингз',
    'Coyotes': 'Аризона', 'Kraken': 'Сиэтл', 'Knights': 'Вегас',
    'Utah Hockey Club': 'Юта',
}


def ru(name):
    """Перевести название команды на русский."""
    # Ищем точное совпадение
    if name in TEAMS_RU:
        return TEAMS_RU[name]
    # Ищем по первому слову или по ключу
    name_lower = name.lower()
    for eng, rus in TEAMS_RU_EXTRA.items():
        if eng.lower() == name_lower:
            return rus
    # Поиск по вхождению
    for eng, rus in {**TEAMS_RU, **TEAMS_RU_EXTRA}.items():
        if eng.lower() in name_lower or name_lower in eng.lower():
            return rus
    # Если не нашли — возвращаем как есть
    return name


# ─── SStats ─────────────────────────────────────────────────────────
def fetch_sstats_league(lid, date_from, date_to):
    """Завершённые матчи лиги за период через SStats API (с кэшем 5 мин)."""
    import sport_cache
    cache_key = f'sstats_league_{lid}_{date_from.strftime("%Y%m%d")}'  
    cached = sport_cache.get('sstats', cache_key)
    if cached is not None:
        return cached, ''
    
    url = f'https://api.sstats.net/Games/list?apikey={SSTATS_KEY}&LeagueId={lid}&Year=2025&take=500'
    try:
        resp = requests.get(url, timeout=15)
        data = resp.json()
    except Exception as e:
        return [], str(e)

    games = data if isinstance(data, list) else data.get('data', data.get('Data', []))
    if isinstance(games, dict):
        games = [v for k, v in games.items() if isinstance(v, dict)]

    matches = []
    for g in games:
        if g.get('statusName') != 'Finished':
            continue
        d = g.get('date', '')
        if not d:
            continue
        try:
            dt = datetime.fromisoformat(d.replace('Z', '+00:00'))
            if date_from <= dt <= date_to:
                matches.append({
                    'home': ru(g.get('homeTeam', {}).get('name', '?')),
                    'away': ru(g.get('awayTeam', {}).get('name', '?')),
                    'score': f'{g.get("homeFTResult", g.get("homeResult", "?"))}:{g.get("awayFTResult", g.get("awayResult", "?"))}',
                    'date': dt,
                })
        except:
            continue
    return matches, ''


# ─── ESPN ────────────────────────────────────────────────────────────
def fetch_espn(sport_path, date_str):
    """Завершённые матчи через ESPN API."""
    import sport_cache
    url = f'https://site.api.espn.com/apis/site/v2/sports/{sport_path}/scoreboard?dates={date_str}'
    try:
        resp = requests.get(url, timeout=15)
        data = resp.json()
    except Exception as e:
        return [], str(e)

    matches = []
    for e in data.get('events', []):
        comp = e.get('competitions', [{}])[0]
        status = comp.get('status', {}).get('type', {}).get('description', '')
        if status not in ('Final', 'Окончен', 'Finished'):
            continue
        teams = comp.get('competitors', [])
        if len(teams) < 2:
            continue
        matches.append({
            'home': ru(teams[0].get('team', {}).get('displayName', '?')),
            'away': ru(teams[1].get('team', {}).get('displayName', '?')),
            'score': f'{teams[0].get("score", "?")}:{teams[1].get("score", "?")}',
        })
    sport_cache.set("espn", f'espn_{sport_path}_{date_str}', matches)
    return matches, ''


# ─── ТЕННИС (ESPN ATP/WTA) ───────────────────────────────────────────
def matches_tournament(event):
    """Проверить, подходит ли турнир (Grand Slam или Masters/1000)."""
    if event.get('major', False):
        return True, '🏆 Grand Slam'
    name = event.get('name', '').lower()
    for kw in MASTERS_1000_KEYWORDS:
        if kw in name:
            return True, '🎯 Masters 1000'
    return False, None


def is_main_draw(round_name):
    """Проверить, что раунд из основной сетки (не квалификация)."""
    if not round_name:
        return False
    return 'qualifying' not in round_name.lower()


def short_round(round_name):
    """Сократить название раунда для компактного вывода."""
    if not round_name:
        return ''
    rn = round_name.lower().strip()
    for key, emoji in TENNIS_ROUND_EMOJI.items():
        if key in rn:
            return emoji
    return round_name[:12]


def fetch_tennis(date_str):
    """
    Завершённые матчи ATP + WTA за дату.
    Фильтр: только Grand Slams + Masters 1000, только основная сетка одиночек.
    Возвращает список словарей:
      {tournament, tier, gender, round, player1, player2, score, sets}
    """
    matches = []
    import sport_cache as _scache
    
    # ESPN ATP endpoint содержит ВСЕ grouping (mens-singles + womens-singles)
    # Так что хватает одного запроса
    url = 'https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard?dates=' + date_str
    try:
        resp = requests.get(url, timeout=15)
        raw = resp.json()
    except Exception as e:
        return []

    GENDER_MAP = {'mens-singles': 'Мужчины', 'womens-singles': 'Женщины'}

    for ev in raw.get('events', []):
        is_target, tier = matches_tournament(ev)
        if not is_target:
            continue
        tname = ev.get('name', '?')

        for grp in ev.get('groupings', []):
            gslug = grp.get('grouping', {}).get('slug', '')
            if gslug not in TENNIS_GROUPINGS_ALLOWED:
                continue
            gender = GENDER_MAP.get(gslug, gslug)

            for comp in grp.get('competitions', []):
                st = comp.get('status', {}).get('type', {}).get('state', '')
                if st != 'post':
                    continue

                rnd = comp.get('round', {}).get('displayName', '')
                if not is_main_draw(rnd):
                    continue

                # Фильтр по дате матча — только за указанную дату
                mdate = comp.get('date', '')
                if mdate:
                    mday = normalize_date(mdate[:10])
                    if mday != date_str:
                        continue

                comps = comp.get('competitors', [])
                if len(comps) < 2:
                    continue

                p1 = tennis_names.ru_name(comps[0].get('athlete', {}).get('displayName', '?'))
                p2 = tennis_names.ru_name(comps[1].get('athlete', {}).get('displayName', '?'))
                w1 = comps[0].get('winner', False)
                w2 = comps[1].get('winner', False)

                # Структурированные сеты: (s1_str, s2_str, p1_won_set)
                sets_structured = []
                ls1 = comps[0].get('linescores', [])
                ls2 = comps[1].get('linescores', [])

                for s1, s2 in zip(ls1, ls2):
                    try:
                        s1v = int(float(s1.get('value', 0)))
                        s2v = int(float(s2.get('value', 0)))
                        p1_won = s1.get('winner', False)
                        sets_structured.append((str(s1v), str(s2v), bool(p1_won)))
                    except (ValueError, TypeError):
                        continue

                # Текст счёта (для кэша/тестов)
                if sets_structured:
                    score_text = ' '.join(f'{a}-{b}' for a, b, _ in sets_structured)
                else:
                    score_text = ''

                # ret / w/o из notes
                notes = [n.get('text', '') for n in comp.get('notes', [])]
                nt = notes[0] if notes else ''
                has_ret = 'ret' in nt.lower() if nt else False
                has_wo = 'w/o' in nt.lower() if nt else False

                if has_ret:
                    score_text += ' ret.'
                elif has_wo and not score_text:
                    score_text = 'w/o'

                matches.append({
                    'tournament': tname,
                    'tier': tier,
                    'gender': gender,
                    'round': short_round(rnd),
                    'player1': p1,
                    'player2': p2,
                    'winner1': w1,
                    'winner2': w2,
                    'score': score_text,
                    'sets': sets_structured,
                    'has_ret': has_ret,
                    'has_wo': has_wo,
                })

    _scache.set('espn', f'tennis_{date_str}', matches)
    return matches


# ─── КХЛ ─────────────────────────────────────────────────────────────
def fetch_khl(date_from=None, date_to=None):
    """Завершённые матчи КХЛ через имеющийся парсер.
    date_from/date_to — datetime (UTC), матчи фильтруются по дате.
    """
    try:
        subprocess.run(
            ['python3', '/root/.openclaw/workspace/khl_parser.py'],
            capture_output=True, text=True, timeout=60
        )
    except:
        pass

    files = sorted(glob.glob('/tmp/khl*.json'))
    if not files:
        return []

    try:
        with open(files[0]) as f:
            data = json.load(f)
    except:
        return []

    if isinstance(data, dict):
        data = list(data.values()) if all(isinstance(v, list) for v in data.values()) else []

    matches = []
    for m in data:
        if not isinstance(m, dict):
            continue
        score = m.get('score', '-:-')
        if score == '-:-' or m.get('state') in ('scheduled', ''):
            continue

        # Фильтр по дате
        if date_from and date_to:
            try:
                mdate = datetime.strptime(m.get('date', ''), '%d.%m.%Y').replace(tzinfo=UTC)
                if not (date_from <= mdate < date_to):
                    continue
            except (ValueError, TypeError):
                continue

        matches.append({
            'home': m.get('team1', '?'),
            'away': m.get('team2', '?'),
            'score': score,
        })
    return matches


# ─── ОТПРАВКА ───────────────────────────────────────────────────────
def send_telegram(text):
    banner_path = '/opt/banner.jpg'
    targets = [CHANNEL_ID, '-1003708361475']
    try:
        compact = text.replace('  ', ' ').replace('\n\n\n', '\n\n').replace('\n\n\n', '\n\n')
        caption = compact
    except:
        caption = text

    for chat_id in targets:
        try:
            with open(banner_path, 'rb') as f:
                url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto'
                files = {'photo': f}
                payload = {'chat_id': chat_id, 'caption': caption, 'parse_mode': 'HTML'}
                resp = requests.post(url, files=files, data=payload, timeout=20)

                if resp.status_code == 200:
                    print(f'✅ Пост с баннером отправлен в {chat_id}')
                else:
                    err = resp.json().get('description', '')
                    if 'caption' in err and len(caption) > 1024:
                        caption = caption[:1020]
                        last_nl = caption.rfind('\n')
                        if last_nl > 100:
                            caption = caption[:last_nl] + '\n...'
                        payload['caption'] = caption
                        f.seek(0)
                        resp = requests.post(url, files={'photo': f}, data=payload, timeout=20)
                        if resp.status_code == 200:
                            print(f'✅ Пост (обрезан) отправлен в {chat_id}')
        except Exception as e:
            print(f'❌ Ошибка отправки в {chat_id}: {e}')


# ─── ФОРМИРОВАНИЕ ПОСТА ─────────────────────────────────────────────
MAX_PER_LEAGUE = 10

def build_section(sec_lines, emoji, name, matches, hidden_store, sport_key):
    """Построить одну лигу/секцию с обрезкой до MAX_PER_LEAGUE."""
    if not matches:
        return
    sec_lines.append(f'\n{emoji} <b>{name}</b>:')
    total = len(matches)
    show = matches[:MAX_PER_LEAGUE]
    for m in show:
        line = f'  {m["home"]} — {m["away"]} {m["score"]}'
        # Для НХЛ добавляем броски в створ
        if 'home_sog' in m and m['home_sog'] is not None:
            line += f' (броски {m["away_sog"]}-{m["home_sog"]})'
        sec_lines.append(line)
    if total > MAX_PER_LEAGUE:
        sec_lines.append(f'  {MAX_PER_LEAGUE} из {total} матчей')
        # Сохраняем полные данные
        hidden_store.setdefault(sport_key, []).append({
            'emoji': emoji,
            'name': name,
            'matches': matches,
        })


def build_tennis_section(tennis, hidden_store):
    """Построить теннисную секцию с обрезкой до 10 на раунд."""
    if not tennis:
        return None

    tree = {}
    for t in tennis:
        key = (t['tournament'], t['tier'])
        tree.setdefault(key, {})
        tree[key].setdefault(t['gender'], {})
        tree[key][t['gender']].setdefault(t['round'], []).append(t)

    gender_emoji = {'Мужчины': '👨', 'Женщины': '👩'}
    has_truncation = False
    tennis_lines = ['\n🎾 <b>Теннис</b>']

    for (tname, tier), genders in tree.items():
        tennis_lines.append(f'\n🏆 <b>{tname}</b> ({tier})')
        for gender, rounds in genders.items():
            emoji = gender_emoji.get(gender, '')
            tennis_lines.append(f'\n<b>{emoji} {gender}</b>')
            for rnd_name, ms in rounds.items():
                tennis_lines.append(f'<b>{rnd_name}</b>' if rnd_name else '')
                total = len(ms)
                show = ms[:MAX_PER_LEAGUE]
                for m in show:
                    score_str = ' '.join(f'{s1}-{s2}' for s1, s2, _ in m['sets']) if m['sets'] else m['score']
                    if m['winner1']:
                        tennis_lines.append(f'  <b>{m["player1"]}</b> — {m["player2"]} {score_str}')
                    else:
                        tennis_lines.append(f'  {m["player1"]} — <b>{m["player2"]}</b> {score_str}')
                if total > MAX_PER_LEAGUE:
                    tennis_lines.append(f'  {MAX_PER_LEAGUE} из {total} матчей')
                    has_truncation = True

    if len(tennis_lines) <= 1:
        return None

    tennis_lines.append('')
    result_text = '\n'.join(tennis_lines)

    if has_truncation:
        tennis_full_html = format_tennis_full(tree, gender_emoji)
        hidden_store.setdefault('tennis', []).append({
            'html': tennis_full_html,
        })

    return result_text


def build_post(football, hockey, basketball, tennis=None, hidden_store=None):
    lines = ['<b>РЕЗУЛЬТАТЫ</b>',
             (datetime.now(UTC) - timedelta(days=1)).strftime('%d.%m.%Y'), '']

    if hidden_store is None:
        hidden_store = {}

    sections = []

    if football:
        sec = []
        for name, emoji, matches in football:
            build_section(sec, emoji, name, matches, hidden_store, 'football')
        sec.append('')
        if any(l.startswith('  ') for l in sec):
            sections.append('\n'.join(sec))

    if hockey:
        sec = []
        for name, emoji, matches in hockey:
            build_section(sec, '🏒', name, matches, hidden_store, 'hockey')
        sec.append('')
        if any(l.startswith('  ') for l in sec):
            sections.append('\n'.join(sec))

    if basketball:
        sec = []
        for name, emoji, matches in basketball:
            build_section(sec, emoji, name, matches, hidden_store, 'basketball')
        sec.append('')
        if any(l.startswith('  ') for l in sec):
            sections.append('\n'.join(sec))

    tennis_section = build_tennis_section(tennis, hidden_store)
    if tennis_section:
        sections.append(tennis_section)

    if not sections:
        return '<b>РЕЗУЛЬТАТЫ</b>\n\nЗа прошедшие сутки завершённых матчей нет'

    return '\n'.join(lines + sections)


# ─── MAIN ────────────────────────────────────────────────────────────
def format_tennis_full(tree, gender_emoji):
    lines = []
    for (tname, tier), genders in tree.items():
        lines.append(f'<b>{tname}</b> ({tier})')
        for gender, rounds in genders.items():
            emoji = gender_emoji.get(gender, '')
            lines.append(f'<b>{emoji} {gender}</b>')
            for rnd_name, ms in rounds.items():
                lines.append(f'<b>{rnd_name}</b>' if rnd_name else '')
                for m in ms:
                    score_str = ' '.join(f'{s1}-{s2}' for s1, s2, _ in m['sets']) if m['sets'] else m['score']
                    if m['winner1']:
                        lines.append(f'  <b>{m["player1"]}</b> — {m["player2"]} {score_str}')
                    else:
                        lines.append(f'  {m["player1"]} — <b>{m["player2"]}</b> {score_str}')
    return '\n'.join(lines)


def main():
    now = datetime.now(UTC)

    # Последние 24 часа (всегда, независимо от времени запуска)
    date_to = now
    date_from = now - timedelta(hours=24)
    # Для даты файла и API (ESPN/NHL) используем МСК
    now_msk = now + MOW
    yesterday_msk = now_msk - timedelta(days=1)
    date_str = yesterday_storage()
    date_str_today = today_storage()

    print(f'📅 Период: {date_from.isoformat()} — {date_to.isoformat()}')

    # ── Футбол ──
    football_leagues = []
    for lid, (name, emoji) in SSTATS_LEAGUES.items():
        matches, err = fetch_sstats_league(lid, date_from, date_to)
        print(f'{"⚠️" if err else "✅"} {emoji} {name}: {len(matches)}')
        football_leagues.append((name, emoji, matches))

    # ── Хоккей ──
    hockey_leagues = []
    nhl = nhl_api.fetch_nhl_results(date_str)
    print(f'✅ 🏒 НХЛ: {len(nhl)}')
    hockey_leagues.append(('НХЛ', '🏒', nhl))

    khl = fetch_khl(date_from=date_from, date_to=date_to)
    print(f'✅ 🏒 КХЛ: {len(khl)}')
    hockey_leagues.append(('КХЛ', '🏒', khl))
    
    # ЧМ по хоккею
    try:
        whc, _ = flashscore_other.fetch_results('world-cup-hockey', date_from, date_to)
        print(f'✅ 🏒 ЧМ по хоккею: {len(whc)}')
    except:
        whc = []
        print('⚠️ 🏒 ЧМ по хоккею: ошибка Playwright, пропускаем')
    hockey_leagues.append(('ЧМ по хоккею', '🏒', whc))

    # ── Баскетбол ──
    basketball_leagues = []
    nba = balldontlie_api.fetch_nba_results(date_str)
    print(f'✅ 🏀 NBA: {len(nba)}')
    basketball_leagues.append(('NBA', '🏀', nba))
    
    # Лига ВТБ
    try:
        vtb, _ = flashscore_other.fetch_results('vtb', date_from, date_to)
        print(f'✅ 🏀 Лига ВТБ: {len(vtb)}')
    except:
        vtb = []
        print('⚠️ 🏀 Лига ВТБ: ошибка Playwright, пропускаем')
    basketball_leagues.append(('Лига ВТБ', '🏀', vtb))
    
    # Euroleague
    try:
        euro, _ = flashscore_other.fetch_results('euroleague', date_from, date_to)
        print(f'✅ 🏀 Euroleague: {len(euro)}')
    except:
        euro = []
        print('⚠️ 🏀 Euroleague: ошибка Playwright, пропускаем')
    basketball_leagues.append(('Euroleague', '🏀', euro))

    # ── Теннис ──
    tennis = fetch_tennis(date_str) + fetch_tennis(date_str_today)
    print(f'✅ 🎾 Теннис: {len(tennis)} матчей')

    # ── Сохраняем результаты в JSON (для сайта) ──
    try:
        results_data = []
        for league_list, sport in [(football_leagues, 'football'), (hockey_leagues, 'hockey'), (basketball_leagues, 'basketball')]:
            for name, emoji, matches in league_list:
                for m in matches:
                    results_data.append({
                        'sport': sport,
                        'league': name,
                        'home': m.get('home', m.get('team1', '?')),
                        'away': m.get('away', m.get('team2', '?')),
                        'score': m.get('score', '-:-'),
                    })
        for t in tennis:
            p1 = t.get('player1', '?')
            p2 = t.get('player2', '?')
            score = ' '.join(f'{s1}-{s2}' for s1, s2, _ in t.get('sets', [])) if t.get('sets') else t.get('score', '')
            results_data.append({
                'sport': 'tennis',
                'league': t.get('tournament', 'Теннис'),
                'home': p1, 'away': p2,
                'score': score or '-:-',
            })
        with open('/tmp/daily_results_data.json', 'w', encoding='utf-8') as f:
            json.dump({'date': yesterday_msk.strftime('%d.%m.%Y'), 'results': results_data, 'generated_at': now.isoformat()}, f, ensure_ascii=False)
    except Exception as e:
        print(f'⚠️ Ошибка сохранения результатов: {e}')

    # ── Пост ──
    hidden_store = {}
    post = build_post(football_leagues, hockey_leagues, basketball_leagues, tennis, hidden_store=hidden_store)
    print('\n' + '=' * 50)
    print(post[:600])
    print('=' * 50)
    msg_result = send_telegram(post)

    # Если были обрезанные секции — отправляем кнопку "Показать все"
    if hidden_store:
        try:
            # Строим полный HTML для всех обрезанных секций
            expand_sections = []
            for sport_key in ('football', 'hockey', 'basketball'):
                for item in hidden_store.get(sport_key, []):
                    lines = [f'\n{item["emoji"]} <b>{item["name"]}</b>:']
                    for m in item['matches']:
                        lines.append(f'  {m["home"]} — {m["away"]} {m["score"]}')
                    expand_sections.append('\n'.join(lines))

            for item in hidden_store.get('tennis', []):
                if item.get('html'):
                    expand_sections.append(f'\n🎾 <b>Теннис</b>\n\n{item["html"]}')

            if expand_sections:
                full_html = '\n'.join(expand_sections)
                expand_data = {
                    'ts': datetime.now(UTC).isoformat(),
                    'html': full_html,
                }
                with open('/tmp/sport_expand.json', 'w') as _ef:
                    json.dump(expand_data, _ef, ensure_ascii=False)

                url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
                payload = {
                    'chat_id': CHANNEL_ID,
                    'text': f'📋 <b>Полные результаты</b>\n\nНажмите кнопку, чтобы показать все матчи в лигах с более чем {MAX_PER_LEAGUE} результатами.',
                    'parse_mode': 'HTML',
                    'reply_markup': json.dumps({
                        'inline_keyboard': [[
                            {'text': '📋 Показать всё', 'callback_data': 'expand_all'}
                        ]]
                    }),
                }
                r = requests.post(url, data=payload, timeout=15)
                if r.status_code == 200:
                    print('✅ Кнопка "Показать всё" отправлена')
        except Exception as e:
            print(f'❌ Ошибка кнопки: {e}')


if __name__ == '__main__':
    main()
