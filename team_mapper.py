#!/usr/bin/env python3
"""
Центральный маппер названий команд.

Стратегия (вариант 1 + 4):
  1. Точное совпадение (каноническое имя)
  2. Словарь алиасов (ручные варианты)
  3. Нормализация + триграммы (fuzzy fallback)

Используется evaluate_predictions.py, daily_results.py и fetch_live_scores.py.
"""

import unicodedata
import re
import json
from collections import defaultdict

# ─── Канонические имена ─────────────────────────────────────────────
# Ключ: каноническое имя (как в daily_results/SStats)
# Алиасы: все варианты, которые могут прийти из capper/других источников
# Включает весь TEAMS_RU + обратные маппинги + короткие имена capper

CANONICAL = {
    # ═══ АПЛ ═══
    'Арсенал': ['Arsenal'],
    'Астон Вилла': ['Aston Villa'],
    'Борнмут': ['Bournemouth'],
    'Брентфорд': ['Brentford'],
    'Брайтон': ['Brighton'],
    'Бёрнли': ['Burnley', 'Бернли'],
    'Челси': ['Chelsea'],
    'Кристал Пэлас': ['Crystal Palace'],
    'Эвертон': ['Everton'],
    'Фулхэм': ['Fulham'],
    'Ипсвич': ['Ipswich'],
    'Лидс': ['Leeds'],
    'Лестер': ['Leicester'],
    'Ливерпуль': ['Liverpool'],
    'Манчестер Сити': ['Manchester City'],
    'Манчестер Юнайтед': ['Manchester United', 'МЮ'],
    'Ньюкасл': ['Newcastle', 'Newcastle United'],
    'Ноттингем Форест': ['Nottingham Forest'],
    'Саутгемптон': ['Southampton'],
    'Сандерленд': ['Sunderland'],
    'Тоттенхэм': ['Tottenham', 'Tottenham Hotspur', 'Тотенхем', 'Тотенхэм'],
    'Вест Хэм': ['West Ham', 'West Ham United'],
    'Вулверхэмптон': ['Wolves', 'Wolverhampton Wanderers'],

    # ═══ Ла Лига ═══
    'Алавес': ['Alaves'],
    'Атлетик': ['Athletic Bilbao', 'Athletic Club', 'Атлетик Бильбао'],
    'Атлетико Мадрид': ['Atletico Madrid', 'Atlético Madrid', 'Атлетико', 'Атлетико М'],
    'Барселона': ['Barcelona'],
    'Сельта': ['Celta Vigo'],
    'Эльче': ['Elche'],
    'Эспаньол': ['Espanyol'],
    'Хетафе': ['Getafe'],
    'Жирона': ['Girona'],
    'Лас-Пальмас': ['Las Palmas'],
    'Леганес': ['Leganes'],
    'Леванте': ['Levante'],
    'Мальорка': ['Mallorca'],
    'Осасуна': ['Osasuna'],
    'Райо Вальекано': ['Rayo Vallecano', 'Райо'],
    'Бетис': ['Real Betis'],
    'Реал Мадрид': ['Real Madrid'],
    'Реал Сосьедад': ['Real Sociedad'],
    'Вальядолид': ['Real Valladolid'],
    'Севилья': ['Sevilla'],
    'Валенсия': ['Valencia'],
    'Вильярреал': ['Villarreal'],
    'Овьедо': ['Oviedo'],

    # ═══ Серия А ═══
    'Аталанта': ['Atalanta'],
    'Болонья': ['Bologna'],
    'Кальяри': ['Cagliari'],
    'Комо': ['Como'],
    'Кремонезе': ['Cremonese'],
    'Эмполи': ['Empoli'],
    'Фиорентина': ['Fiorentina'],
    'Дженоа': ['Genoa'],
    'Верона': ['Hellas Verona'],
    'Интер': ['Inter', 'Inter Milan'],
    'Ювентус': ['Juventus'],
    'Лацио': ['Lazio'],
    'Лечче': ['Lecce'],
    'Милан': ['AC Milan', 'Milan'],
    'Монца': ['Monza'],
    'Наполи': ['Napoli'],
    'Парма': ['Parma'],
    'Пиза': ['Pisa'],
    'Рома': ['AS Roma', 'Roma'],
    'Салернитана': ['Salernitana'],
    'Сассуоло': ['Sassuolo'],
    'Специя': ['Spezia'],
    'Торино': ['Torino'],
    'Удинезе': ['Udinese'],
    'Венеция': ['Venezia'],

    # ═══ Бундеслига ═══
    'Аугсбург': ['Augsburg'],
    'Байер': ['Bayer Leverkusen', 'Bayer 04 Leverkusen'],
    'Бавария': ['Bayern Munich', 'Bayern München'],
    'Боруссия Д': ['Borussia Dortmund'],
    'Боруссия М': ['Borussia Monchengladbach', 'Borussia Mönchengladbach'],
    'Айнтрахт': ['Eintracht Frankfurt'],
    'Фрайбург': ['SC Freiburg', 'Freiburg'],
    'Хайденхайм': ['1. FC Heidenheim 1846', 'Heidenheim'],
    'Хоффенхайм': ['1899 Hoffenheim', 'TSG Hoffenheim', 'Hoffenheim'],
    'Хольштайн': ['Holstein Kiel'],
    'Кёльн': ['1. FC Koln', '1. FC Köln', 'Köln', 'Кельн'],
    'Майнц': ['Mainz', '1. FSV Mainz 05'],
    'РБ Лейпциг': ['RB Leipzig'],
    'Санкт-Паули': ['FC St. Pauli', 'St. Pauli'],
    'Штутгарт': ['VfB Stuttgart', 'Stuttgart'],
    'Унион Берлин': ['Union Berlin'],
    'Вердер': ['Werder Bremen'],
    'Вольфсбург': ['VfL Wolfsburg', 'Wolfsburg'],
    'Гамбург': ['Hamburger SV', 'Hamburg'],

    # ═══ Лига 1 ═══
    'Анже': ['Angers'],
    'Осер': ['Auxerre'],
    'Брест': ['Brest', 'Stade Brestois 29'],
    'Гавр': ['Le Havre', 'Le Havre AC'],
    'Ланс': ['Lens'],
    'Лилль': ['Lille'],
    'Лорьян': ['Lorient'],
    'Лион': ['Lyon'],
    'Марсель': ['Marseille'],
    'Мец': ['Metz'],
    'Монако': ['AS Monaco', 'Monaco'],
    'Монпелье': ['Montpellier'],
    'Нант': ['Nantes', 'Nant'],
    'Ницца': ['Nice'],
    'ПСЖ': ['Paris Saint-Germain', 'PSG', 'Paris Saint Germain'],
    'Париж': ['Paris FC'],
    'Реймс': ['Reims', 'Stade de Reims'],
    'Ренн': ['Rennes', 'Stade Rennais'],
    'Страсбур': ['Strasbourg'],
    'Тулуза': ['Toulouse', 'Toulouz'],

    # ═══ РПЛ ═══
    'Акрон': ['Akron'],
    'Ахмат': ['Akhmat', 'Akhmat Grozny'],
    'ЦСКА': ['CSKA Moscow'],
    'Динамо': ['Dynamo Moscow', 'Dinamo Moscow', 'Dynamo'],
    'Динамо Мх': ['Dinamo Makhachkala', 'Dynamo Makhachkala'],
    'Факел': ['Fakel'],
    'Краснодар': ['FC Krasnodar', 'Krasnodar'],
    'Оренбург': ['FC Orenburg', 'Gazovik Orenburg', 'Orenburg'],
    'Ростов': ['FC Rostov', 'Rostov'],
    'Сочи': ['FC Sochi', 'Sochi'],
    'Химки': ['Khimki'],
    'Крылья Советов': ['Krylya Sovetov', 'Krylia Sovetov'],
    'Локомотив': ['Lokomotiv', 'Lokomotiv Moscow'],
    'Пари НН': ['Nizhny Novgorod', 'Paris NN'],
    'Рубин': ['Rubin', 'Rubin Kazan'],
    'Спартак': ['Spartak', 'Spartak Moscow'],
    'Зенит': ['Zenit', 'Zenit St. Petersburg'],
    'Балтика': ['Baltika', 'FC Baltika', 'FC Baltika Kaliningrad'],

    # ═══ НХЛ ═══
    'Анахайм Дакс': ['Anaheim Ducks'],
    'Бостон Брюинз': ['Boston Bruins'],
    'Баффало Сейбрз': ['Buffalo Sabres'],
    'Калгари Флэймз': ['Calgary Flames'],
    'Каролина Харрикейнз': ['Carolina Hurricanes'],
    'Чикаго Блэкхокс': ['Chicago Blackhawks'],
    'Колорадо Эвеланш': ['Colorado Avalanche'],
    'Коламбус Блю Джекетс': ['Columbus Blue Jackets'],
    'Даллас Старз': ['Dallas Stars'],
    'Детройт Ред Уингз': ['Detroit Red Wings'],
    'Эдмонтон Ойлерз': ['Edmonton Oilers'],
    'Флорида Пантерз': ['Florida Panthers'],
    'Лос-Анджелес Кингз': ['Los Angeles Kings'],
    'Миннесота Уайлд': ['Minnesota Wild'],
    'Монреаль Канадиенс': ['Montreal Canadiens'],
    'Нэшвилл Предаторз': ['Nashville Predators'],
    'Нью-Джерси Девилз': ['New Jersey Devils'],
    'Нью-Йорк Айлендерс': ['New York Islanders'],
    'Нью-Йорк Рейнджерс': ['New York Rangers'],
    'Оттава Сенаторз': ['Ottawa Senators'],
    'Филадельфия Флайерз': ['Philadelphia Flyers'],
    'Питтсбург Пингвинз': ['Pittsburgh Penguins'],
    'Сан-Хосе Шаркс': ['San Jose Sharks'],
    'Сиэтл Кракен': ['Seattle Kraken'],
    'Сент-Луис Блюз': ['St. Louis Blues'],
    'Тампа-Бэй Лайтнинг': ['Tampa Bay Lightning'],
    'Торонто Мэйпл Лифс': ['Toronto Maple Leafs'],
    'Юта': ['Utah Hockey Club'],
    'Ванкувер Кэнакс': ['Vancouver Canucks'],
    'Вегас Голден Найтс': ['Vegas Golden Knights'],
    'Вашингтон Кэпиталз': ['Washington Capitals'],
    'Виннипег Джетс': ['Winnipeg Jets'],

    # ═══ NBA ═══
    'Атланта Хокс': ['Atlanta Hawks'],
    'Бостон Селтикс': ['Boston Celtics'],
    'Бруклин Нетс': ['Brooklyn Nets'],
    'Шарлотт Хорнетс': ['Charlotte Hornets'],
    'Чикаго Буллз': ['Chicago Bulls'],
    'Кливленд Кавальерс': ['Cleveland Cavaliers'],
    'Даллас Маверикс': ['Dallas Mavericks'],
    'Денвер Наггетс': ['Denver Nuggets'],
    'Детройт Пистонс': ['Detroit Pistons'],
    'Голден Стэйт Уорриорз': ['Golden State Warriors'],
    'Хьюстон Рокетс': ['Houston Rockets'],
    'Индиана Пэйсерс': ['Indiana Pacers'],
    'ЛА Клипперс': ['LA Clippers'],
    'ЛА Лейкерс': ['Los Angeles Lakers'],
    'Мемфис Гриззлиз': ['Memphis Grizzlies'],
    'Майами Хит': ['Miami Heat'],
    'Милуоки Бакс': ['Milwaukee Bucks'],
    'Миннесота Тимбервулвз': ['Minnesota Timberwolves'],
    'Нью-Орлеан Пеликанс': ['New Orleans Pelicans'],
    'Нью-Йорк Никс': ['New York Knicks'],
    'Оклахома-Сити Тандер': ['Oklahoma City Thunder'],
    'Орландо Мэджик': ['Orlando Magic'],
    'Филадельфия 76ерс': ['Philadelphia 76ers', 'Philadelphia 76ers'],
    'Финикс Санз': ['Phoenix Suns'],
    'Портленд Трэйл Блэйзерс': ['Portland Trail Blazers', 'Portland Trail Blazers'],
    'Сакраменто Кингз': ['Sacramento Kings'],
    'Сан-Антонио Спёрс': ['San Antonio Spurs'],
    'Торонто Рэпторс': ['Toronto Raptors'],
    'Юта Джаз': ['Utah Jazz'],
    'Вашингтон Уизардс': ['Washington Wizards'],
}

# Сборка обратного индекса: alias → canonical
_ALIAS_TO_CANON = {}
for canon, aliases in CANONICAL.items():
    canon_lower = canon.lower().strip()
    _ALIAS_TO_CANON[canon_lower] = canon
    for alias in aliases:
        _ALIAS_TO_CANON[alias.lower().strip()] = canon


def _normalize(name):
    """Убрать диакритику, лишние пробелы, привести к lowercase."""
    if not name:
        return ''
    # remove diacritics
    nfkd = unicodedata.normalize('NFKD', name)
    ascii_str = nfkd.encode('ASCII', 'ignore').decode('ascii', errors='ignore')
    # lowercase, strip, collapse spaces
    result = re.sub(r'\s+', ' ', ascii_str.lower().strip())
    return result


def _trigram_similarity(a, b):
    """Jaccard similarity on character trigrams."""
    if not a or not b:
        return 0.0
    
    def _trigrams(s):
        # Remove spaces for trigrams
        s_clean = s.replace(' ', '')
        return {s_clean[i:i+3] for i in range(len(s_clean) - 2)}
    
    ta = _trigrams(a)
    tb = _trigrams(b)
    
    if not ta or not tb:
        return 0.0
    
    intersection = ta & tb
    union = ta | tb
    return len(intersection) / len(union)


def resolve(name, candidates=None):
    """
    Привести имя команды к каноническому виду.
    
    1. Точное совпадение по словарю алиасов
    2. Нормализованное совпадение (без диакритики)
    3. Триграммы среди кандидатов (если переданы)
    
    Аргументы:
        name: str — имя для маппинга
        candidates: list[str] — возможные целевые имена (для fuzzy fallback)
    
    Возвращает:
        (str, str) — (каноническое имя, метод: 'exact'|'alias'|'norm'|'trigram'|'raw')
    """
    if not name:
        return name, 'empty'
    
    name_stripped = name.strip()
    name_lower = name_stripped.lower()
    
    # 1. Точное совпадение (каноническое имя)
    canon = _ALIAS_TO_CANON.get(name_lower)
    if canon:
        return canon, 'alias'
    
    # 2. Нормализованное (без диакритики)
    norm = _normalize(name_stripped)
    canon = _ALIAS_TO_CANON.get(norm)
    if canon:
        return canon, 'norm'
    
    # 3. Нормализованный поиск по частичному вхождению в алиасы
    # Только для имён длиннее 3 символов, чтобы избежать ложных срабатываний
    if len(norm) > 3:
        for alias_key, canon_name in _ALIAS_TO_CANON.items():
            # Check if one is a (non-trivial) substring of the other
            if (len(norm) >= 4 and norm in alias_key) or (len(alias_key) >= 4 and alias_key in norm):
                # Extra guard: must share at least first 3 chars
                if norm[:3] == alias_key[:3]:
                    return canon_name, 'substr'
    
    # 4. Триграммы среди кандидатов (со старшим порогом для коротких имён)
    if candidates:
        best_score = 0.0
        best_candidate = None
        for c in candidates:
            score = _trigram_similarity(norm, _normalize(c))
            if score > best_score:
                best_score = score
                best_candidate = c
        
        threshold = 0.7 if len(norm) <= 4 else 0.5
        if best_score >= threshold and len(norm) > 1:
            # Try to find through the canonical dict
            canon_candidate = _ALIAS_TO_CANON.get(_normalize(best_candidate))
            if canon_candidate:
                return canon_candidate, 'trigram'
            return best_candidate, 'trigram'
    
    return name_stripped, 'raw'


def resolve_match(home, away, candidates_pool=None):
    """
    Привести home/away к каноническим именам.
    
    candidates_pool — список всех известных имён команд (из daily_results или live_scores).
    Если передан, используется для триграммного fallback.
    """
    resolved_home, method_h = resolve(home, candidates_pool)
    resolved_away, method_a = resolve(away, candidates_pool)
    return resolved_home, resolved_away


def all_canonical():
    """Вернуть все канонические имена."""
    return sorted(CANONICAL.keys())


def build_lookup(candidates_list):
    """
    Построить словарь (canonical → True) из списка имён.
    Используется evaluate_predictions.py для ускорения матчинга.
    """
    result = {}
    for c in candidates_list:
        canon, _ = resolve(c)
        result[canon] = True
    return result


if __name__ == '__main__':
    # Тест
    test_cases = [
        ('Атлетико', 'Атлетико Мадрид'),
        ('Атлетико М', 'Атлетико Мадрид'),
        ('Atletico Madrid', 'Атлетико Мадрид'),
        ('Тоттенхэм', 'Тоттенхэм'),
        ('Manchester City', 'Манчестер Сити'),
        ('МЮ', 'Манчестер Юнайтед'),
        ('Arsenal', 'Арсенал'),
        ('Байер', 'Байер'),
        ('Bournemouth', 'Борнмут'),
        ('Челси', 'Челси'),
    ]
    
    print('=== Тест маппера ===')
    for inp, expected in test_cases:
        result, method = resolve(inp)
        status = '✅' if result == expected else '❌'
        print(f'  {status} {inp:25s} → {result:25s} (ожидалось: {expected:25s}) метод={method}')
    
    # Тест с кандидатами
    dr_candidates = [
        'Атлетико Мадрид', 'Борнмут', 'Манчестер Сити', 
        'Тоттенхэм', 'Тулуза', 'Нант', 'Челси', 'Бёрнли'
    ]
    print('\n=== Тест с кандидатами (триграммы) ===')
    for inp in ['Бернли', 'Тулуз', 'Тотенхем', 'МС', 'Челси']:
        result, method = resolve(inp, dr_candidates)
        print(f'  {inp:15s} → {result:25s} метод={method}')
