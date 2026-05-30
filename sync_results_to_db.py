#!/usr/bin/env python3
"""
Синхронизация результатов → matches (БД).

Единый источник:
flashscore_other.fetch_results — КХЛ, ВТБ, Евролига, ЧМ по хоккею (прямой фетч)

Запуск: по крону. Результаты → БД → site_results.py + daily_results.py.
"""

import os, sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/opt')
sys.path.insert(0, '/root/.openclaw/workspace/odds')

from date_utils import format_date_display, format_date_iso, yesterday_iso, today_iso

try:
    from db import save_match, execute, find_match_id, save_tennis_match
    HAS_DB = True
except Exception as _db_err:
    print(f'  ⚠️ БД недоступна: {_db_err}')
    HAS_DB = False


# ═══ Flashscore-лиги для прямого фетча результатов ═══

FLASHSCORE_RESULTS_LEAGUES = [
    ('khl',              'КХЛ'),
    ('vtb',              'Лига ВТБ'),
    ('euroleague',       'Евролига'),
    ('world-cup-hockey', 'ЧМ по хоккею'),
]

# SStats-лиги (футбол)
SSTATS_LEAGUES = [
    (39, 'АПЛ'),
    (140, 'Ла Лига'),
    (135, 'Серия А'),
    (78, 'Бундеслига'),
    (61, 'Лига 1'),
    (235, 'РПЛ'),
    (2, 'Лига Чемпионов'),
    (3, 'Лига Европы'),
    (848, 'Лига Конференций'),
]

# ESPN-лиги (НХЛ, NBA)
ESPN_LEAGUES = [
    ('hockey/nhl', 'НХЛ'),
    ('basketball/nba', 'NBA'),
]



# Сезонные рамки (копия из fetch_upcoming_matches.py)
SEASON_RANGES = {
    'khl':              (9, 4),
    'vtb':              (9, 5),
    'euroleague':       (10, 5),
}


def _in_season(league_key: str, month: int) -> bool:
    """Проверка, входит ли месяц в сезон лиги."""
    season_range = SEASON_RANGES.get(league_key)
    if not season_range:
        return True  # без ограничений
    start_m, end_m = season_range
    if start_m <= end_m:
        return start_m <= month <= end_m
    return month >= start_m or month <= end_m


def sync_from_flashscore(target_date=None):
    """
    Фетчит завершённые матчи из flashscore и сохраняет в БД.
    Если target_date не указана — за предыдущий день.
    """
    if not HAS_DB:
        return 0, 0, 0

    now = datetime.now(timezone.utc)
    date_from = target_date or (now - timedelta(days=1))
    date_to = date_from + timedelta(days=1)

    from flashscore_other import fetch_results

    total_updated = 0
    total_created = 0
    total_errors = 0
    match_date_str = format_date_iso(date_from)

    for league_key, league_name in FLASHSCORE_RESULTS_LEAGUES:
        # Сезонная проверка
        if not _in_season(league_key, date_from.month):
            print(f'  ⏭️ {league_name}: вне сезона, пропускаем')
            continue

        try:
            matches, _ = fetch_results(
                league_key,
                date_from=date_from.isoformat(),
                date_to=date_to.isoformat()
            )
        except Exception as e:
            print(f'  ⚠️ Flashscore {league_name}: {e}')
            total_errors += 1
            continue

        print(f'  📡 {league_name}: {len(matches)} матчей')
        for m in matches:
            home = m.get('home', '')
            away = m.get('away', '')
            score = m.get('score', '')
            match_time = m.get('time', '')

            if not home or not away:
                continue

            # Определяем дату матча из flashscore (если есть)
            mdate_str = match_date_str
            if m.get('date'):
                try:
                    mdate = datetime.fromisoformat(m['date'])
                    mdate_str = format_date_iso(mdate)
                except:
                    pass

            try:
                # Ищем существующий матч
                existing = execute(
                    "SELECT id, status, score FROM matches WHERE league = %s AND home = %s AND away = %s AND match_date = %s",
                    (league_name, home, away, mdate_str)
                )

                if existing:
                    # Обновляем
                    execute(
                        "UPDATE matches SET score = %s, status = 'finished', updated_at = NOW() WHERE id = %s",
                        (score, existing[0]['id'])
                    )
                    total_updated += 1
                else:
                    # Создаём
                    save_match({
                        'league': league_name,
                        'home': home,
                        'away': away,
                        'match_date': mdate_str,
                        'match_time': match_time,
                        'source': 'flashscore',
                        'score': score,
                        'status': 'finished',
                        'channel': '',
                        'tournament': league_name,
                        'game_id': 0,
                        'espn_id': None,
                    })
                    total_created += 1
            except Exception as e:
                total_errors += 1
                if total_errors <= 3:
                    print(f'    ⚠️ {league_name} {home}-{away}: {e}')

    return total_updated, total_created, total_errors


def sync_from_sstats(target_date=None):
    """Футбол (АПЛ, Ла Лига и т.д.) через SStats API."""
    if not HAS_DB:
        return 0, 0, 0

    from daily_results import fetch_sstats_league

    now = datetime.now(timezone.utc) + timedelta(hours=3)
    date_from = target_date or (now - timedelta(days=1))
    date_to = date_from + timedelta(days=1)
    date_str = date_from.strftime('%Y-%m-%d')

    updated = 0
    created = 0
    errors = 0

    for lid, league_name in SSTATS_LEAGUES:
        try:
            matches, err = fetch_sstats_league(lid, date_from, date_to)
            if err:
                print(f'  ⚠️ SStats {league_name}: {err}')
                errors += 1
                continue
        except Exception as e:
            print(f'  ⚠️ SStats {league_name}: {e}')
            errors += 1
            continue

        print(f'  📡 SStats {league_name}: {len(matches)} матчей')
        for m in matches:
            home = m.get('home', '')
            away = m.get('away', '')
            score = m.get('score', '')
            match_date = m.get('date', '')
            if not home or not away or not score:
                continue

            try:
                mdate_str = match_date.strftime('%Y-%m-%d') if hasattr(match_date, 'strftime') else date_str

                existing = execute(
                    "SELECT id, status, score FROM matches WHERE league = %s AND home = %s AND away = %s AND match_date = %s",
                    (league_name, home, away, mdate_str)
                )

                if existing:
                    execute(
                        "UPDATE matches SET score = %s, status = 'finished', updated_at = NOW() WHERE id = %s",
                        (score, existing[0]['id'])
                    )
                    updated += 1
                else:
                    save_match({
                        'league': league_name,
                        'home': home,
                        'away': away,
                        'match_date': mdate_str,
                        'match_time': '',
                        'source': 'sstats',
                        'score': score,
                        'status': 'finished',
                        'channel': '',
                        'tournament': league_name,
                        'game_id': 0,
                        'espn_id': None,
                    })
                    created += 1
            except Exception as e:
                errors += 1
                if errors <= 3:
                    print(f'    ⚠️ {league_name} {home}-{away}: {e}')

    return updated, created, errors


def sync_from_espn(target_date=None):
    """НХЛ, NBA через ESPN API."""
    if not HAS_DB:
        return 0, 0, 0

    from daily_results import fetch_espn

    now = datetime.now(timezone.utc) + timedelta(hours=3)
    date_from = target_date or (now - timedelta(days=1))
    date_str = date_from.strftime('%Y%m%d')
    date_iso = date_from.strftime('%Y-%m-%d')

    updated = 0
    created = 0
    errors = 0

    for sport_path, league_name in ESPN_LEAGUES:
        try:
            matches, err = fetch_espn(sport_path, date_str)
            if err:
                print(f'  ⚠️ ESPN {league_name}: {err}')
                errors += 1
                continue
        except Exception as e:
            print(f'  ⚠️ ESPN {league_name}: {e}')
            errors += 1
            continue

        print(f'  📡 ESPN {league_name}: {len(matches)} матчей')
        for m in matches:
            home = m.get('home', '')
            away = m.get('away', '')
            score = m.get('score', '')
            if not home or not away or not score:
                continue

            try:
                existing = execute(
                    "SELECT id, status, score FROM matches WHERE league = %s AND home = %s AND away = %s AND match_date = %s",
                    (league_name, home, away, date_iso)
                )

                if existing:
                    execute(
                        "UPDATE matches SET score = %s, status = 'finished', updated_at = NOW() WHERE id = %s",
                        (score, existing[0]['id'])
                    )
                    updated += 1
                else:
                    save_match({
                        'league': league_name,
                        'home': home,
                        'away': away,
                        'match_date': date_iso,
                        'match_time': '',
                        'source': 'espn',
                        'score': score,
                        'status': 'finished',
                        'channel': '',
                        'tournament': league_name,
                        'game_id': 0,
                        'espn_id': None,
                    })
                    created += 1
            except Exception as e:
                errors += 1
                if errors <= 3:
                    print(f'    ⚠️ {league_name} {home}-{away}: {e}')

    return updated, created, errors


def sync_from_tennis(target_date=None):
    """Теннис (ATP, WTA) через ESPN. Пишет в matches + tennis_matches."""
    if not HAS_DB:
        return 0, 0, 0

    from daily_results import fetch_tennis

    now = datetime.now(timezone.utc) + timedelta(hours=3)
    date_from = target_date or (now - timedelta(days=1))
    date_str = date_from.strftime('%Y%m%d')
    date_iso = date_from.strftime('%Y-%m-%d')

    updated = 0
    created = 0
    errors = 0

    try:
        matches = fetch_tennis(date_str)
    except Exception as e:
        print(f'  ⚠️ Теннис: {e}')
        return 0, 0, 1

    print(f'  📡 Теннис: {len(matches)} матчей')
    for m in matches:
        home = m.get('player1', '')
        away = m.get('player2', '')
        score = m.get('score', '')
        sets = m.get('sets', '')
        league_name = 'ATP' if m.get('gender') == 'Мужчины' else 'WTA'
        if not home or not away:
            continue

        try:
            existing = execute(
                "SELECT id, status, score FROM matches WHERE league = %s AND home = %s AND away = %s AND match_date = %s",
                (league_name, home, away, date_iso)
            )

            match_id = None
            if existing:
                execute(
                    "UPDATE matches SET score = %s, status = 'finished', updated_at = NOW() WHERE id = %s",
                    (score, existing[0]['id'])
                )
                match_id = existing[0]['id']
                updated += 1
            else:
                save_match({
                    'league': league_name,
                    'home': home,
                    'away': away,
                    'match_date': date_iso,
                    'match_time': '',
                    'source': 'espn',
                    'score': score,
                    'status': 'finished',
                    'channel': '',
                    'tournament': league_name,
                    'game_id': 0,
                    'espn_id': None,
                })
                match_id = find_match_id(league_name, home, away, date_iso)
                created += 1

            # Сохраняем детали в tennis_matches
            if match_id:
                save_tennis_match(match_id, {
                    'tournament': m.get('tournament', ''),
                    'tier': m.get('tier', ''),
                    'gender': m.get('gender', ''),
                    'round': m.get('round', ''),
                    'sets': m.get('sets', []),
                    'winner_home': m.get('winner1', False),
                    'winner_away': m.get('winner2', False),
                    'has_ret': m.get('has_ret', False),
                    'has_wo': m.get('has_wo', False),
                })
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f'    ⚠️ Теннис {home}-{away}: {e}')

    return updated, created, errors


def main():
    if not HAS_DB:
        print('  ❌ Нет подключения к БД')
        return

    total_cre = 0
    total_upd = 0

    print('🔁 Синхронизация flashscore → БД:')
    fs_upd, fs_cre, fs_err = sync_from_flashscore()
    print(f'  ✅ Flashscore: +{fs_cre} создано, {fs_upd} обновлено, {fs_err} ошибок')
    total_cre += fs_cre; total_upd += fs_upd

    print('🔁 Синхронизация SStats (футбол) → БД:')
    ss_upd, ss_cre, ss_err = sync_from_sstats()
    print(f'  ✅ SStats: +{ss_cre} создано, {ss_upd} обновлено, {ss_err} ошибок')
    total_cre += ss_cre; total_upd += ss_upd

    print('🔁 Синхронизация ESPN (НХЛ, NBA) → БД:')
    es_upd, es_cre, es_err = sync_from_espn()
    print(f'  ✅ ESPN: +{es_cre} создано, {es_upd} обновлено, {es_err} ошибок')
    total_cre += es_cre; total_upd += es_upd

    print('🔁 Синхронизация теннис → БД:')
    tn_upd, tn_cre, tn_err = sync_from_tennis()
    print(f'  ✅ Теннис: +{tn_cre} создано, {tn_upd} обновлено, {tn_err} ошибок')
    total_cre += tn_cre; total_upd += tn_upd

    print(f'\n📊 Итого: +{total_cre} создано, {total_upd} обновлено')
    return total_cre + total_upd


if __name__ == '__main__':
    main()
