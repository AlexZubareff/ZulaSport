#!/usr/bin/env python3
"""
Сбор результатов завершённых матчей для оценки прогнозов.

Читает из БД прогнозы со статусом 'upcoming' и датой в прошлом,
группирует по датам и лигам, дёргает соответствующие API,
сохраняет все результаты в /tmp/results_data.json.

Запуск:
  python3 /opt/fetch_results.py                 # все даты с прогнозами
  python3 /opt/fetch_results.py --date 2026-05-20  # конкретная дата
"""

import argparse
import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, date, timedelta, timezone

# ─── Пути ───────────────────────────────────────────────────────────────
sys.path.insert(0, '/opt')

# ─── Логирование ────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('fetch_results')

# ─── Импорты ────────────────────────────────────────────────────────────
import db
from daily_results import fetch_sstats_league, fetch_espn
from nhl_api import fetch_nhl_results

# ─── Константы ──────────────────────────────────────────────────────────
SSTATS_KEY = open('/etc/sstats.key').read().strip()
UTC = timezone.utc
MOW = timedelta(hours=3)
RESULTS_FILE = '/tmp/results_data.json'
RATE_LIMIT_SLEEP = 0.5  # секунд между API-запросами

# Маппинг: название лиги в БД → (тип источника, параметры)
# type: 'sstats' = SStats API, 'nhl' = NHL API, 'nba' = ESPN NBA, 'skip' = пропускаем
# Для SStats второй элемент — LeagueId
LEAGUE_SOURCE = {
    'АПЛ':            ('sstats', 39),
    'Ла Лига':        ('sstats', 140),
    'Серия А':        ('sstats', 135),
    'Бундеслига':     ('sstats', 78),
    'Лига 1':         ('sstats', 61),
    'РПЛ':            ('sstats', 235),
    'Лига Европы':    ('sstats', 3),
    'Лига чемпионов': ('sstats', 2),
    'НХЛ':            ('nhl',   None),
    'NBA':            ('nba',   None),
    # Теннис ATP/WTA — пропускаем (сложные результаты)
}

# SStats LeagueId → название (для обратной совместимости с daily_results)
SSTATS_LID_TO_LEAGUE = {
    39: 'АПЛ', 140: 'Ла Лига', 135: 'Серия А',
    78: 'Бундеслига', 61: 'Лига 1', 235: 'РПЛ',
    2: 'Лига чемпионов', 3: 'Лига Европы', 848: 'Лига Конференций',
}


# ═══════════════════════════════════════════════════════════════════════
# Работа с БД
# ═══════════════════════════════════════════════════════════════════════

def get_predictions_to_evaluate(target_date=None):
    """
    Получить прогнозы со статусом 'upcoming' и датой матча до today.
    Если target_date указан — только за эту дату.
    Возвращает список dict.
    """
    if target_date:
        dt = target_date
        rows = db.execute(
            "SELECT id, league, home, away, match_date, status FROM predictions "
            "WHERE status = 'upcoming' AND match_date = %s ORDER BY league",
            (dt,)
        )
    else:
        rows = db.execute(
            "SELECT id, league, home, away, match_date, status FROM predictions "
            "WHERE status = 'upcoming' AND match_date < CURRENT_DATE ORDER BY match_date, league"
        )
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════
# Источники данных
# ═══════════════════════════════════════════════════════════════════════

def fetch_sstats_league_results(lid: int, league_name: str,
                                date_from: datetime, date_to: datetime) -> list:
    """
    Завершённые матчи SStats-лиги за период.
    Возвращает список dict: {league, home, away, score, date}
    """
    log.info(f'  SStats lid={lid} ({league_name}): {date_from.date()} – {date_to.date()}')
    try:
        matches, err = fetch_sstats_league(lid, date_from, date_to)
        if err:
            log.warning(f'  ⚠️ SStats lid={lid} ({league_name}): {err}')
            return []
    except Exception as e:
        log.error(f'  ❌ SStats lid={lid} ({league_name}): {e}')
        return []

    results = []
    for m in matches:
        results.append({
            'league': league_name,
            'home': m['home'],
            'away': m['away'],
            'score': m['score'],
            'date': m['date'].strftime('%Y-%m-%d'),
        })
    return results


def fetch_nhl_date_results(date_str: str) -> list:
    """
    Завершённые матчи НХЛ за дату (YYYYMMDD).
    Возвращает список dict: {league, home, away, score, date}
    NHL API возвращает счёт как away:home — сохраняем как есть.
    """
    log.info(f'  НХЛ: {date_str}')
    try:
        matches = fetch_nhl_results(date_str)
    except Exception as e:
        log.error(f'  ❌ НХЛ: {e}')
        return []

    iso_date = f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}'
    results = []
    for m in matches:
        results.append({
            'league': 'НХЛ',
            'home': m['home'],
            'away': m['away'],
            'score': m['score'],
            'date': iso_date,
        })
    return results


def fetch_nba_date_results(date_str: str) -> list:
    """
    Завершённые матчи NBA за дату (YYYYMMDD).
    Использует ESPN API через fetch_espn.
    """
    log.info(f'  NBA: {date_str}')
    try:
        matches, err = fetch_espn('basketball/nba', date_str)
        if err:
            log.warning(f'  ⚠️ NBA: {err}')
            return []
    except Exception as e:
        log.error(f'  ❌ NBA: {e}')
        return []

    iso_date = f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}'
    results = []
    for m in matches:
        results.append({
            'league': 'NBA',
            'home': m['home'],
            'away': m['away'],
            'score': m['score'],
            'date': iso_date,
        })
    return results


# ═══════════════════════════════════════════════════════════════════════
# Сбор результатов
# ═══════════════════════════════════════════════════════════════════════

def collect_results(predictions, target_date=None):
    """
    Собрать результаты для всех лиг/дат из списка прогнозов.
    Возвращает список dict для /tmp/results_data.json.
    """
    # Группируем по дате
    by_date = defaultdict(set)  # date → set of leagues
    all_dates = set()

    for p in predictions:
        d = p['match_date']
        if isinstance(d, datetime):
            d = d.date()
        all_dates.add(d)
        by_date[d].add(p['league'])

    dates_sorted = sorted(all_dates)
    if not dates_sorted:
        log.info('  Нет дат для сбора результатов')
        return []

    log.info(f'  Даты: {dates_sorted[0]} – {dates_sorted[-1]} ({len(dates_sorted)} дней)')

    results = []

    # ── 1. SStats: футбольные лиги (батч-запрос за весь диапазон) ──
    sstats_leagues = set()
    for d, leagues in by_date.items():
        for lg in leagues:
            src = LEAGUE_SOURCE.get(lg)
            if src and src[0] == 'sstats':
                sstats_leagues.add((src[1], lg))  # (lid, league_name)

    if sstats_leagues:
        dt_from = datetime.combine(min(dates_sorted), datetime.min.time(), tzinfo=UTC)
        dt_to = datetime.combine(max(dates_sorted), datetime.max.time(), tzinfo=UTC)

        for lid, league_name in sorted(sstats_leagues):
            try:
                league_results = fetch_sstats_league_results(lid, league_name, dt_from, dt_to)
                results.extend(league_results)
                time.sleep(RATE_LIMIT_SLEEP)
            except Exception as e:
                log.error(f'  ❌ SStats lid={lid}: {e}')

    # ── 2. НХЛ: по дням ──
    nhl_dates = set()
    for d, leagues in by_date.items():
        if 'НХЛ' in leagues:
            nhl_dates.add(d)

    for d in sorted(nhl_dates):
        date_str = d.strftime('%Y%m%d')
        try:
            nhl_results = fetch_nhl_date_results(date_str)
            results.extend(nhl_results)
            time.sleep(RATE_LIMIT_SLEEP)
        except Exception as e:
            log.error(f'  ❌ НХЛ {date_str}: {e}')

    # ── 3. NBA: по дням ──
    nba_dates = set()
    for d, leagues in by_date.items():
        if 'NBA' in leagues:
            nba_dates.add(d)

    for d in sorted(nba_dates):
        date_str = d.strftime('%Y%m%d')
        try:
            nba_results = fetch_nba_date_results(date_str)
            results.extend(nba_results)
            time.sleep(RATE_LIMIT_SLEEP)
        except Exception as e:
            log.error(f'  ❌ NBA {date_str}: {e}')

    log.info(f'  Всего собрано: {len(results)} результатов')
    return results


# ═══════════════════════════════════════════════════════════════════════
# Сохранение
# ═══════════════════════════════════════════════════════════════════════

def save_results(results):
    """Сохранить результаты в /tmp/results_data.json."""
    data = {
        'results': results,
        'generated_at': datetime.now(UTC).isoformat(),
        'total': len(results),
    }
    tmp = RESULTS_FILE + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.rename(tmp, RESULTS_FILE)
        log.info(f'  💾 {RESULTS_FILE}: {len(results)} результатов')
    except Exception as e:
        log.error(f'  ❌ Ошибка сохранения {RESULTS_FILE}: {e}')
        raise


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(
        description='Сбор результатов завершённых матчей для оценки прогнозов'
    )
    parser.add_argument(
        '--date', type=str, default=None,
        help='Конкретная дата в формате YYYY-MM-DD (по умолчанию: все даты)'
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Подробный вывод'
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.verbose:
        log.setLevel(logging.DEBUG)

    log.info('📊 Сбор результатов для оценки прогнозов')

    # Определяем дату
    target_date = None
    if args.date:
        try:
            target_date = datetime.strptime(args.date, '%Y-%m-%d').date()
            log.info(f'  Целевая дата: {target_date}')
        except ValueError:
            log.error(f'❌ Неверный формат даты: {args.date}. Используйте YYYY-MM-DD')
            sys.exit(1)

    # Читаем прогнозы из БД
    predictions = get_predictions_to_evaluate(target_date)
    if not predictions:
        log.info('  Нет прогнозов для оценки (все уже обработаны или дата в будущем)')
        # Сохраняем пустой файл чтобы evaluate_predictions не падал
        save_results([])
        return

    unique_leagues = sorted(set(p['league'] for p in predictions))
    log.info(f'  Прогнозов: {len(predictions)}, лиги: {unique_leagues}')

    # Проверяем, что все лиги поддерживаются
    unsupported = [lg for lg in unique_leagues if lg not in LEAGUE_SOURCE]
    if unsupported:
        log.warning(f'  ⚠️ Неподдерживаемые лиги (пропускаем): {unsupported}')
        log.info('    ATP/WTA пропущены по условию задачи')

    # Собираем результаты
    results = collect_results(predictions, target_date)

    # Сохраняем
    save_results(results)

    # Статистика
    if results:
        by_league = defaultdict(int)
        by_date = defaultdict(int)
        for r in results:
            by_league[r['league']] += 1
            by_date[r['date']] += 1

        log.info(f'\n  📊 По лигам:')
        for lg, cnt in sorted(by_league.items()):
            log.info(f'    {lg}: {cnt}')
        log.info(f'\n  📅 По датам:')
        for d, cnt in sorted(by_date.items()):
            log.info(f'    {d}: {cnt}')

    log.info('✅ Готово')


if __name__ == '__main__':
    main()
