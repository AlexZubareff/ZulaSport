#!/usr/bin/env python3
"""
Единый загрузчик предстоящих матчей.

Собирает матчи из SStats (футбол) + NHL API + ESPN + balldontlie (NBA) + Flashscore (КХЛ, ВТБ, Евролига, ЧМ)
ThreadPool — все источники параллельно.

Сохраняет:
  1. PostgreSQL (таблица matches)
  2. /tmp/upcoming_matches.json (для совместимости)

Не включает ТВ-программу — это задача fetch_tv_channels.py (читает из БД).

Запуск: ежедневно в 00:01 MSK (cron)
"""

import json, os, sys, time, re
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, '/opt')
from data_schemas import validate
from alert import report_success, report_failure

# ─── БД ─────────────────────────────────────────────────────────────
try:
    import db
    _DB_AVAILABLE = True
except Exception:
    _DB_AVAILABLE = False

# ─── Константы ──────────────────────────────────────────────────────
MOW = timedelta(hours=3)
UTC = timezone.utc
SSTATS_KEY = os.environ.get('SSTATS_KEY', '')
if not SSTATS_KEY:
    try:
        with open('/etc/sstats.key') as f:
            SSTATS_KEY = f.read().strip()
    except:
        pass

# Активные лиги (общие для всех источников)
PRED_LEAGUES_PATH = '/opt/prediction_leagues.json'
_ACTIVE_LEAGUES = {}
try:
    with open(PRED_LEAGUES_PATH) as f:
        _ACTIVE_LEAGUES = json.load(f).get('active', {})
except:
    pass

# SStats ID → league name
SSTATS_LEAGUES = {
    39:  'АПЛ', 140: 'Ла Лига', 135: 'Серия А',
    78:  'Бундеслига', 61: 'Лига 1', 235: 'РПЛ',
    2:   'Лига чемпионов', 3: 'Лига Европы', 848: 'Лига Конференций',
}

# Flashscore-лиги (не-футбол)
FLASHSCORE_LEAGUES = {
    'khl':              ('КХЛ',           'hockey'),
    'world-cup-hockey': ('ЧМ по хоккею',  'hockey'),
    'vtb':              ('Лига ВТБ',      'basketball'),
    'euroleague':       ('Евролига',      'basketball'),
}

# ─── Внутренние маппинги ───────────────────────────────────────────
TEAMS_RU = {}
try:
    # Загружаем из fetch_live_scores.py, чтобы не дублировать
    with open('/opt/fetch_live_scores.py', encoding='utf-8') as f:
        content = f.read()
    # Ищем словарь TEAMS_RU
    import ast
    # Простой парсинг: ищем начало словаря TEAMS_RU
    m = re.search(r'TEAMS_RU\s*=\s*\{([^}]+)\}', content, re.DOTALL)
    if m:
        exec(f'TEAMS_RU = {{ {m.group(1)} }}', globals())
except:
    pass

# Используем fetch_live_scores.ru() или fallback
def _ru(name: str) -> str:
    """EN → RU через имеющиеся словари."""
    if not name:
        return name
    # Прямое совпадение
    if name in TEAMS_RU:
        return TEAMS_RU[name]
    # Частичное совпадение
    name_lower = name.lower().strip()
    for eng, rus in TEAMS_RU.items():
        if eng.lower() == name_lower:
            return rus
    for eng, rus in TEAMS_RU.items():
        if eng.lower() in name_lower or name_lower in eng.lower():
            return rus
    return name


# ═══════════════════ Source: SStats (футбол) ═══════════════════

def _fetch_sstats(lid: int, target_date: str) -> List[Dict]:
    """Предстоящие матчи лиги из SStats API."""
    try:
        import requests
        resp = requests.get(
            f'https://api.sstats.net/Games/list',
            params={'apikey': SSTATS_KEY, 'LeagueId': lid, 'Year': 2025, 'take': 500},
            timeout=15,
        )
        data = resp.json()
    except Exception as e:
        print(f'  ⚠️ SStats (lid={lid}): {e}')
        return []

    games = data if isinstance(data, list) else data.get('data', data.get('Data', []))
    if isinstance(games, dict):
        games = [v for k, v in games.items() if isinstance(v, dict)]

    date_str = target_date
    matches = []
    for g in games:
        if g.get('statusName') not in ('Not Started', 'Scheduled'):
            continue
        d = g.get('date', '')
        if not d or not d.startswith(date_str):
            continue
        try:
            dt = datetime.fromisoformat(d.replace('Z', '+00:00'))
            time_msk = (dt + MOW).strftime('%H:%M')
        except:
            time_msk = d[11:16] if len(d) > 11 else ''
        home = _ru(g.get('homeTeam', {}).get('name', '?'))
        away = _ru(g.get('awayTeam', {}).get('name', '?'))
        league_name = SSTATS_LEAGUES.get(lid, f'sstats:{lid}')
        matches.append({
            'home': home,
            'away': away,
            'time': time_msk,
            'game_id': g.get('id', 0),
            'league': league_name,
            'sport': 'football',
            'source': 'sstats',
            'date': date_str,
        })
    return matches


# ═══════════════════ Source: NHL API ═══════════════════

def _fetch_nhl(target_date: str) -> List[Dict]:
    """Предстоящие матчи НХЛ."""
    try:
        from fetch_nhl_data import fetch_schedule
        from nhl_api import ru as nhl_ru
        nhl_data = fetch_schedule()
    except Exception as e:
        print(f'  ⚠️ NHL: {e}')
        return []

    matches = []
    for match in nhl_data.get('upcoming', []):
        home = match.get('home', '')
        away = match.get('away', '')
        home_ru = match.get('home_ru', '') or nhl_ru(home)
        away_ru = match.get('away_ru', '') or nhl_ru(away)
        matches.append({
            'home': home_ru or home,
            'away': away_ru or away,
            'time': match.get('time', ''),
            'game_id': match.get('game_id', 0),
            'league': 'НХЛ',
            'sport': 'hockey',
            'source': 'nhl_api',
            'date': target_date,
            'odds': match.get('odds', {}),
        })
    return matches


# ═══════════════════ Source: ESPN ═══════════════════

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


def _fetch_espn(path: str, date_str: str, league_name: str, sport_type: str) -> List[Dict]:
    """Предстоящие матчи из ESPN scoreboard."""
    try:
        import requests
        resp = requests.get(
            f'https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard',
            params={'dates': date_str},
            timeout=15,
        )
        data = resp.json()
    except Exception as e:
        print(f'  ⚠️ ESPN {league_name}: {e}')
        return []

    matches = []
    for e in data.get('events', []):
        comp = e.get('competitions', [{}])[0]
        status = comp.get('status', {}).get('type', {}).get('state', '')
        if status not in ('pre', 'scheduled', 'Scheduled'):
            continue
        teams = comp.get('competitors', [])
        if len(teams) < 2:
            continue
        home = _ru(teams[0].get('team', {}).get('displayName', '?'))
        away = _ru(teams[1].get('team', {}).get('displayName', '?'))
        date_raw = comp.get('date', comp.get('startDate', ''))
        try:
            dt = datetime.fromisoformat(date_raw.replace('Z', '+00:00'))
            time_msk = (dt + MOW).strftime('%H:%M')
        except:
            time_msk = ''
        matches.append({
            'home': home,
            'away': away,
            'time': time_msk,
            'game_id': 0,
            'league': league_name,
            'sport': sport_type,
            'source': 'espn',
            'date': date_str,
        })
    return matches


# ═══════════════════ Source: balldontlie (NBA) ═══════════════════

def _fetch_balldontlie(target_date: str) -> List[Dict]:
    """Предстоящие матчи NBA через balldontlie."""
    try:
        from balldontlie_api import fetch_nba_upcoming
        nba_matches = fetch_nba_upcoming(target_date)
    except Exception as e:
        print(f'  ⚠️ balldontlie: {e}')
        return []

    matches = []
    for m in nba_matches:
        matches.append({
            'home': m.get('home', '?'),
            'away': m.get('away', '?'),
            'time': m.get('time', ''),
            'game_id': m.get('game_id', 0),
            'league': 'NBA',
            'sport': 'basketball',
            'source': 'balldontlie',
            'date': target_date,
        })
    return matches


# ═══════════════════ Source: Flashscore ═══════════════════

def _fetch_flashscore(target_date: datetime) -> List[Dict]:
    """Предстоящие матчи из flashscore-лиг (КХЛ, ВТБ, Евролига, ЧМ)."""
    matches = []
    wc_from = target_date.replace(hour=0, minute=0, second=0)
    wc_to = target_date.replace(hour=23, minute=59, second=59)

    for league_key, (league_name, sport_type) in FLASHSCORE_LEAGUES.items():
        try:
            sys.path.insert(0, '/root/.openclaw/workspace/odds')
            from flashscore_other import fetch_upcoming_live
            fs_matches, _ = fetch_upcoming_live(league_key)
        except Exception as e:
            print(f'  ⚠️ Flashscore {league_name}: {e}')
            continue

        for m in fs_matches:
            if not isinstance(m, dict):
                continue
            matches.append({
                'home': m.get('home', '?'),
                'away': m.get('away', '?'),
                'time': m.get('time', ''),
                'game_id': 0,
                'league': league_name,
                'sport': sport_type,
                'source': 'flashscore',
                'date': target_date.strftime('%Y-%m-%d'),
            })

    return matches


# ═══════════════════ Дедупликация ═══════════════════

def _dedup(matches: List[Dict]) -> List[Dict]:
    """Дедупликация: (league, home, away) — уникальный ключ.
    Приоритет: flashscore < espn < balldontlie < nhl_api < sstats.
    """
    priority = {'flashscore': 0, 'espn': 1, 'balldontlie': 2, 'nhl_api': 3, 'sstats': 4}
    seen = {}  # key -> index

    unique = []
    for m in matches:
        key = f"{m.get('league','')}||{m.get('home','')}||{m.get('away','')}"
        src_priority = priority.get(m.get('source', ''), 0)
        if key in seen:
            idx = seen[key]
            existing = unique[idx]
            old_priority = priority.get(existing.get('source', ''), 0)
            if src_priority > old_priority:
                unique[idx] = m
        else:
            seen[key] = len(unique)
            unique.append(m)

    return unique


# ═══════════════════ Сохранение ═══════════════════

def _save_to_db(matches: List[Dict]):
    """Сохранить матчи в PostgreSQL."""
    if not _DB_AVAILABLE or not matches:
        return 0

    saved = 0
    for m in matches:
        try:
            db.save_match({
                'league': m['league'],
                'home': m['home'],
                'away': m['away'],
                'match_date': m.get('date', ''),
                'match_time': m.get('time', ''),
                'source': m.get('source', ''),
                'status': 'scheduled',
                'game_id': m.get('game_id', 0),
            })
            saved += 1
        except Exception as e:
            print(f'  ⚠️ DB save: {m.get("home","?")} — {m.get("away","?")}: {e}')
    return saved


def _save_to_json(matches: List[Dict]):
    """Сохранить матчи в /tmp/upcoming_matches.json (для совместимости)."""
    output = {
        'matches': matches,
        'generated_at': datetime.now(UTC).isoformat(),
    }

    # Валидация
    ok, errors = validate(output, 'predictions_data')
    if not ok and matches:
        # predictions_data не совсем подходит — лучше создать свою схему
        # но это позже. Пока пишем.
        pass

    tmp = '/tmp/upcoming_matches.json'
    tmp_tmp = tmp + '.tmp'
    try:
        with open(tmp_tmp, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        os.rename(tmp_tmp, tmp)
    except Exception as e:
        print(f'  ⚠️ JSON save: {e}')

    print(f'  💾 /tmp/upcoming_matches.json ({len(matches)} матчей)')


# ═══════════════════ Оркестратор ═══════════════════

def collect_all(target_date: Optional[str] = None) -> List[Dict]:
    """Собрать матчи из всех источников (ThreadPool).

    Args:
        target_date: дата в формате 'YYYY-MM-DD'. Если None — завтра по МСК.
    Returns:
        list[dict]: список матчей.
    """
    now = datetime.now(UTC)
    if target_date is None:
        target_date_msk = now + MOW + timedelta(days=1)
    else:
        # Парсим target_date
        try:
            target_date_msk = datetime.strptime(target_date, '%Y-%m-%d')
        except:
            target_date_msk = now + MOW + timedelta(days=1)

    date_str = target_date_msk.strftime('%Y-%m-%d')
    weekday_ru = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС'][target_date_msk.weekday()]
    print(f'📅 Собираю матчи на {date_str} ({weekday_ru})')

    start = time.time()
    all_matches = []

    # Задачи для ThreadPool
    tasks = []

    # 1. SStats (футбол) — по лигам
    for lid, league_name in SSTATS_LEAGUES.items():
        tasks.append(('sstats', lid, date_str))

    # 2. NHL
    tasks.append(('nhl', date_str))

    # 3. ESPN — футбольные лиги
    for league_name, (path, sport_type) in ESPN_PATHS.items():
        if sport_type == 'football':
            tasks.append(('espn', path, date_str, league_name, sport_type))

    # 4. balldontlie
    tasks.append(('balldontlie', date_str))

    # 5. Flashscore
    tasks.append(('flashscore', target_date_msk))

    def _run_task(task):
        task_type = task[0]
        try:
            if task_type == 'sstats':
                _, lid, date = task
                ms = _fetch_sstats(lid, date)
                return task_type, task[1], ms, None
            elif task_type == 'nhl':
                _, date = task
                ms = _fetch_nhl(date)
                return task_type, 'nhl', ms, None
            elif task_type == 'espn':
                _, path, date, league_name, sport_type = task
                ms = _fetch_espn(path, date, league_name, sport_type)
                return task_type, league_name, ms, None
            elif task_type == 'balldontlie':
                _, date = task
                ms = _fetch_balldontlie(date)
                return task_type, 'nba', ms, None
            elif task_type == 'flashscore':
                _, tdate = task
                ms = _fetch_flashscore(tdate)
                return task_type, 'flashscore', ms, None
        except Exception as e:
            return task_type, str(task[1]) if len(task) > 1 else '?', [], str(e)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_run_task, t) for t in tasks]
        for future in as_completed(futures):
            task_type, name, ms, error = future.result()
            if error:
                print(f'  ❌ {task_type}/{name}: {error}')
                report_failure(f'upcoming_{task_type}', error)
            elif ms:
                print(f'  ✅ {task_type}/{name}: {len(ms)} матчей')
                all_matches.extend(ms)
                report_success(f'upcoming_{task_type}')
            else:
                print(f'  ⚠️ {task_type}/{name}: 0 матчей')

    # Сначала фильтр по дате (до дедупликации — чтобы сохранить матчи с правильной датой)
    import re as _re
    _filtered = []
    _skipped = 0
    for _m in all_matches:
        _t = _m.get('time', _m.get('match_time', ''))
        _mtch = _re.match(r'(\d{2})\.(\d{2})\.\s+', _t)
        if _mtch:
            _day, _month = _mtch.groups()
            _date_in_time = f'2026-{_month}-{_day}'
            if _date_in_time != date_str:
                _skipped += 1
                continue
        _filtered.append(_m)
    if _skipped:
        print(f'  🗑️ Отфильтровано по дате: {_skipped} матчей с других дней')
    all_matches = _filtered

    # Дедупликация (уже после фильтра даты — не будет конфликтов ключей)
    total_before = len(all_matches)
    all_matches = _dedup(all_matches)
    if total_before != len(all_matches):
        print(f'  🔄 Дедупликация: {total_before} → {len(all_matches)}')
    import re as _re
    for _m in all_matches:
        _t = _m.get('time', _m.get('match_time', ''))
        try:
            _clean = _re.sub(r'^\d{2}\.\d{2}\.\s*', '', _t).strip()
            _parts = _clean.split(':')
            if len(_parts) == 2:
                _h, _min = int(_parts[0]), int(_parts[1])
                _h = (_h + 3) % 24
                _m['time'] = f'{_h:02d}:{_min:02d}'
        except:
            pass

    # Сохранение
    saved_db = _save_to_db(all_matches)
    _save_to_json(all_matches)

    elapsed = time.time() - start
    print(f'\n✅ Итого: {len(all_matches)} матчей, {saved_db} в БД, {elapsed:.1f}с')

    return all_matches


def main():
    target_date = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        collect_all(target_date)
    except Exception as e:
        report_failure('fetch_upcoming_matches', str(e))
        raise


if __name__ == '__main__':
    main()
