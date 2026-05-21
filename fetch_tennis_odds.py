#!/usr/bin/env python3
"""
Получение теннисных коэффициентов через The Odds API.

Регистрация:
  - Бесплатный Starter: 500 запросов/мес
  - API-ключ: https://the-odds-api.com/#get-access (нужна реальная почта)

Эндпоинты:
  GET /v4/sports/ → список доступных видов спорта
  GET /v4/sports/upcoming/odds/?regions=uk&markets=h2h&apiKey={KEY} → предстоящие матчи

Результат: /opt/data/tennis/odds/upcoming_odds.json

Запуск:
  python3 fetch_tennis_odds.py               # через API (если есть ключ)
  python3 fetch_tennis_odds.py --mock        # тест с заглушкой
  python3 fetch_tennis_odds.py --status      # проверить статус API
"""

import os, sys, json, re
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from collections import defaultdict
import requests

# ─── Путь к файлам ─────────────────────────────────────────────────
ODDS_DIR = '/opt/data/tennis/odds'
ODDS_FILE = os.path.join(ODDS_DIR, 'upcoming_odds.json')
API_KEY_FILE = '/etc/odds_api.key'

# ─── Ключ ───────────────────────────────────────────────────────────
ODDS_API_KEY = os.environ.get('ODDS_API_KEY', '')
if not ODDS_API_KEY:
    try:
        with open(API_KEY_FILE) as f:
            ODDS_API_KEY = f.read().strip()
    except:
        pass

BASE = 'https://api.the-odds-api.com'
MOW = timedelta(hours=3)
UTC = timezone.utc


# ─── Популярные теннисные турниры (для фильтрации) ────────────────
ATP_TOURNAMENTS = [
    'tennis_atp_aus_open_singles',
    'tennis_atp_french_open',
    'tennis_atp_wimbledon',
    'tennis_atp_us_open',
    'tennis_atp_indian_wells',
    'tennis_atp_miami_open',
    'tennis_atp_monte_carlo_masters',
    'tennis_atp_madrid_open',
    'tennis_atp_italian_open',
    'tennis_atp_canadian_open',
    'tennis_atp_cincinnati_open',
    'tennis_atp_shanghai_masters',
    'tennis_atp_paris_masters',
    'tennis_atp_barcelona_open',
    'tennis_atp_hamburg_open',
    'tennis_atp_munich',
    'tennis_atp_dubai',
    'tennis_atp_qatar_open',
    'tennis_atp_china_open',
]

WTA_TOURNAMENTS = [
    'tennis_wta_aus_open_singles',
    'tennis_wta_french_open',
    'tennis_wta_wimbledon',
    'tennis_wta_us_open',
    'tennis_wta_indian_wells',
    'tennis_wta_miami_open',
    'tennis_wta_madrid_open',
    'tennis_wta_italian_open',
    'tennis_wta_canadian_open',
    'tennis_wta_cincinnati_open',
    'tennis_wta_dubai',
    'tennis_wta_qatar_open',
    'tennis_wta_china_open',
    'tennis_wta_wuhan_open',
    'tennis_wta_charleston_open',
    'tennis_wta_stuttgart_open',
    'tennis_wta_strasbourg',
]

ALL_TENNIS_KEYS = ATP_TOURNAMENTS + WTA_TOURNAMENTS


def _get_api_key():
    """Получить API-ключ."""
    return ODDS_API_KEY


def fetch_sports() -> List[Dict]:
    """Получить список доступных видов спорта (не расходует квоту)."""
    key = _get_api_key()
    if not key:
        return []
    try:
        resp = requests.get(f'{BASE}/v4/sports/', params={'apiKey': key}, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f'  ❌ Ошибка {resp.status_code}: {resp.text[:200]}')
            return []
    except Exception as e:
        print(f'  ❌ {e}')
        return []


def fetch_tennis_odds(sport_key='upcoming', regions='uk,eu', markets='h2h') -> List[Dict]:
    """Получить коэффициенты для тенниса.
    sport_key: 'upcoming' (все), 'tennis_atp_french_open', etc.
    """
    key = _get_api_key()
    if not key:
        print('  ⚠️ Нет API-ключа The Odds API')
        return []

    url = f'{BASE}/v4/sports/{sport_key}/odds/'
    params = {
        'apiKey': key,
        'regions': regions,
        'markets': markets,
    }
    try:
        resp = requests.get(url, params=params, timeout=20)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 404:
            # Турнир не активен
            return []
        else:
            print(f'  ⚠️ {sport_key}: HTTP {resp.status_code}')
            return []
    except Exception as e:
        print(f'  ⚠️ {sport_key}: {e}')
        return []


def parse_tennis_matches(odds_data: List[Dict], tour_tag='ATP') -> List[Dict]:
    """Распарсить данные из Odds API в единый формат."""
    matches = []
    for event in odds_data:
        match_id = event.get('id', '')
        home_team = event.get('home_team', '')
        away_team = event.get('away_team', '')
        commence_time = event.get('commence_time', '')
        sport_key = event.get('sport_key', '')
        sport_title = event.get('sport_title', '')

        # Определяем тур: ATP или WTA
        if 'atp' in str(sport_key).lower():
            tour = 'ATP'
        elif 'wta' in str(sport_key).lower():
            tour = 'WTA'
        else:
            tour = tour_tag

        # Преобразуем время
        try:
            dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
            dt_msk = dt + MOW
            match_time = dt_msk.strftime('%H:%M')
            match_date = dt_msk.strftime('%d.%m.%Y')
        except:
            match_time = ''
            match_date = ''

        # Коэффициенты
        odds_home = None
        odds_away = None
        bookmakers = event.get('bookmakers', [])
        if bookmakers:
            # Берём первого букмекера
            bm = bookmakers[0]
            for market in bm.get('markets', []):
                if market.get('key') == 'h2h':
                    for outcome in market.get('outcomes', []):
                        name = outcome.get('name', '')
                        price = outcome.get('price')
                        if name == home_team:
                            odds_home = price
                        elif name == away_team:
                            odds_away = price
                    break

        matches.append({
            'match_id': match_id,
            'home': home_team,
            'away': away_team,
            'tour': tour,
            'sport_key': sport_key,
            'sport_title': sport_title,
            'commence_time': commence_time,
            'match_time': match_time,
            'match_date': match_date,
            'odds_home': odds_home,
            'odds_away': odds_away,
            'source': 'the-odds-api',
        })

    return matches


def fetch_all_tennis_matches() -> List[Dict]:
    """Получить все предстоящие теннисные матчи."""
    key = _get_api_key()
    if not key:
        print('  ⚠️ Нет API-ключа. Используй --mock для теста или зарегистрируйся на https://the-odds-api.com/#get-access')
        return []

    print('  Получаю список спортов...')
    sports = fetch_sports()
    tennis_sports = [s for s in sports if 'tennis' in s.get('group', '').lower()
                     or s.get('key', '').startswith('tennis_')]
    # Фильтруем: только in season
    tennis_sports = [s for s in tennis_sports if s.get('active', False)]
    print(f'  Найдено {len(tennis_sports)} активных теннисных турниров')

    all_matches = []
    # 1. Пробуем 'upcoming' — это дешевле (1 запрос)
    print('  Запрашиваю upcoming (все виды спорта)...')
    upcoming_data = fetch_tennis_odds('upcoming', regions='uk,eu', markets='h2h')
    if upcoming_data:
        # Фильтруем только теннис
        tennis_events = [e for e in upcoming_data if 'tennis' in str(e.get('sport_key', '')).lower()]
        matches = parse_tennis_matches(tennis_events)
        all_matches.extend(matches)
        print(f'  → {len(matches)} теннисных матчей из upcoming')

    # 2. Если недостаточно, дозапрашиваем по турнирам
    if len(all_matches) < 10 and tennis_sports:
        for ts in tennis_sports[:5]:  # максимум 5 турниров (экономия квоты)
            key_name = ts.get('key', '')
            print(f'  Запрашиваю {key_name}...')
            data = fetch_tennis_odds(key_name, regions='uk,eu', markets='h2h')
            if data:
                # Определяем тур
                tour = 'ATP' if 'atp' in key_name else 'WTA'
                matches = parse_tennis_matches(data, tour)
                # Дедупликация
                existing_ids = {m['match_id'] for m in all_matches}
                new_matches = [m for m in matches if m['match_id'] not in existing_ids]
                all_matches.extend(new_matches)
                print(f'  → {len(new_matches)} новых')

    print(f'  Всего: {len(all_matches)} матчей')
    return all_matches


def save_odds(matches: List[Dict]):
    """Сохранить коэффициенты."""
    os.makedirs(ODDS_DIR, exist_ok=True)

    output = {
        'updated_at': datetime.now(UTC).isoformat(),
        'count': len(matches),
        'matches': matches,
    }

    # Атомарная запись
    tmp = ODDS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    os.rename(tmp, ODDS_FILE)
    print(f'  ✅ Сохранено: {ODDS_FILE} ({len(matches)} матчей)')


def mock_data() -> List[Dict]:
    """Заглушка для тестирования без API."""
    return [
        {
            'match_id': 'mock_atp_001',
            'home': 'Carlos Alcaraz',
            'away': 'Jannik Sinner',
            'tour': 'ATP',
            'sport_key': 'tennis_atp_french_open',
            'sport_title': 'ATP French Open',
            'commence_time': (datetime.now(UTC) + timedelta(days=1)).isoformat() + 'Z',
            'match_time': '14:00',
            'match_date': (datetime.now(UTC) + MOW + timedelta(days=1)).strftime('%d.%m.%Y'),
            'odds_home': 1.85,
            'odds_away': 2.00,
            'source': 'mock',
        },
        {
            'match_id': 'mock_atp_002',
            'home': 'Novak Djokovic',
            'away': 'Alexander Zverev',
            'tour': 'ATP',
            'sport_key': 'tennis_atp_french_open',
            'sport_title': 'ATP French Open',
            'commence_time': (datetime.now(UTC) + timedelta(days=1, hours=2)).isoformat() + 'Z',
            'match_time': '16:00',
            'match_date': (datetime.now(UTC) + MOW + timedelta(days=1)).strftime('%d.%m.%Y'),
            'odds_home': 1.65,
            'odds_away': 2.30,
            'source': 'mock',
        },
        {
            'match_id': 'mock_atp_003',
            'home': 'Daniil Medvedev',
            'away': 'Stefanos Tsitsipas',
            'tour': 'ATP',
            'sport_key': 'tennis_atp_french_open',
            'sport_title': 'ATP French Open',
            'commence_time': (datetime.now(UTC) + timedelta(days=1, hours=4)).isoformat() + 'Z',
            'match_time': '18:00',
            'match_date': (datetime.now(UTC) + MOW + timedelta(days=1)).strftime('%d.%m.%Y'),
            'odds_home': 1.90,
            'odds_away': 1.95,
            'source': 'mock',
        },
        {
            'match_id': 'mock_wta_001',
            'home': 'Iga Swiatek',
            'away': 'Aryna Sabalenka',
            'tour': 'WTA',
            'sport_key': 'tennis_wta_french_open',
            'sport_title': 'WTA French Open',
            'commence_time': (datetime.now(UTC) + timedelta(days=1, hours=3)).isoformat() + 'Z',
            'match_time': '17:00',
            'match_date': (datetime.now(UTC) + MOW + timedelta(days=1)).strftime('%d.%m.%Y'),
            'odds_home': 1.55,
            'odds_away': 2.50,
            'source': 'mock',
        },
        {
            'match_id': 'mock_wta_002',
            'home': 'Coco Gauff',
            'away': 'Elena Rybakina',
            'tour': 'WTA',
            'sport_key': 'tennis_wta_french_open',
            'sport_title': 'WTA French Open',
            'commence_time': (datetime.now(UTC) + timedelta(days=1, hours=5)).isoformat() + 'Z',
            'match_time': '19:00',
            'match_date': (datetime.now(UTC) + MOW + timedelta(days=1)).strftime('%d.%m.%Y'),
            'odds_home': 1.80,
            'odds_away': 2.05,
            'source': 'mock',
        },
    ]


def status_check():
    """Проверить статус API (без расходования квоты)."""
    key = _get_api_key()
    if not key:
        print('❌ API-ключ не найден.')
        print('  Для регистрации: https://the-odds-api.com/#get-access')
        print('  После получения ключа сохрани в /etc/odds_api.key или ODDS_API_KEY')
        print()
        print('  Шаги регистрации:')
        print('    1. Открой https://the-odds-api.com/#get-access')
        print('    2. Введи email → получишь ключ на почту')
        print('    3. Запиши ключ: echo "твой_ключ" > /etc/odds_api.key')
        print('    4. Запусти снова python3 fetch_tennis_odds.py')
        print()
        print('  Или используй --mock для теста без API')
        return

    print('🔑 Ключ найден.')
    sports = fetch_sports()
    if sports:
        tennis = [s for s in sports if 'tennis' in s.get('group', '').lower()]
        print(f'  ✅ API работает! Найдено {len(tennis)} теннисных турниров:')
        for s in tennis[:10]:
            status = '✅' if s.get('active') else '⏸️'
            print(f'    {status} {s.get("key", "")} — {s.get("title", "")}')
        if len(tennis) > 10:
            print(f'    ... и ещё {len(tennis) - 10}')
    else:
        print('  ❌ Не удалось получить список спортов.')

    # Проверяем квоту
    remaining = None
    try:
        resp = requests.get(f'{BASE}/v4/sports/', params={'apiKey': key}, timeout=10)
        remaining = resp.headers.get('x-requests-remaining')
        used = resp.headers.get('x-requests-used')
    except:
        pass
    if remaining:
        print(f'  📊 Осталось: {remaining}, использовано: {used}')


def main():
    key = _get_api_key()
    if '--mock' in sys.argv:
        print('🎾 Тест с заглушкой (--mock)')
        matches = mock_data()
        save_odds(matches)
        print('✅ Заглушка сохранена')
        return

    if '--status' in sys.argv:
        print('=== Статус The Odds API ===')
        status_check()
        return

    print('🎾 Получение коэффициентов через The Odds API')
    print(f'  Файл ключа: {API_KEY_FILE if os.path.exists(API_KEY_FILE) else "не найден"}')

    if not key:
        print('  ⚠️ Ключ не найден. Запусти с --mock для теста.')
        print('  Или выполни: python3 fetch_tennis_odds.py --status — инструкция')
        return

    matches = fetch_all_tennis_matches()
    save_odds(matches)

    if matches:
        for m in matches[:5]:
            print(f'  {m["tour"]}: {m["home"]} vs {m["away"]} '
                  f'({m["odds_home"]}/{m["odds_away"]}) {m["match_date"]} {m["match_time"]}')
        if len(matches) > 5:
            print(f'  ... и ещё {len(matches) - 5}')


if __name__ == '__main__':
    main()
