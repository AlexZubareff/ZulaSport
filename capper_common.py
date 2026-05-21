#!/usr/bin/env python3
"""
Общий модуль для всех пайплайнов capper.

Содержит:
- Единый DeepSeek-клиент с кешем (хеш от команд + кэфы + Glicko)
- call_deepseek_with_cache() — основной вход
- Валидация через data_schemas
"""

import json, os, sys, hashlib, time, requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, '/opt')
from data_schemas import validate

CACHE_FILE = '/tmp/deepseek_cache.json'
CACHE_TTL = 1800  # 30 минут
CACHE_VERSION = 1


def _prediction_cache_key(match_info, sstats_data):
    """Вычисляет хеш от данных матча для кеширования прогноза."""
    home = match_info.get('home', '')
    away = match_info.get('away', '')
    league = match_info.get('league', '')

    odds = sstats_data.get('odds', [])
    o = odds[0] if odds else {}
    g = sstats_data.get('glicko', {})

    raw = '|'.join([
        home, away, league,
        str(o.get('home', '')),
        str(o.get('draw', '')),
        str(o.get('away', '')),
        str(g.get('home_prob', '')),
        str(g.get('away_prob', '')),
        str(g.get('draw_prob', '')),
        str(sstats_data.get('totals', {}).get('total_line', '')),
        str(sstats_data.get('totals', {}).get('over', '')),
        str(sstats_data.get('totals', {}).get('under', '')),
    ])
    return hashlib.md5(raw.encode()).hexdigest()


def _load_cache():
    """Загружает кеш из файла."""
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, encoding='utf-8') as f:
            data = json.load(f)
        # Валидация
        ok, _ = validate(data, 'deepseek_cache')
        if not ok:
            return {}
        # Проверка версии
        if data.get('_version') != CACHE_VERSION:
            return {}
        # Очистка устаревших записей
        now = time.time()
        entries = data.get('entries', {})
        fresh = {}
        for key, entry in entries.items():
            if now - entry.get('ts', 0) < CACHE_TTL:
                fresh[key] = entry
        return fresh
    except:
        return {}


def _save_cache(entries):
    """Сохраняет кеш в файл с валидацией."""
    data = {
        '_version': CACHE_VERSION,
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'entries': entries,
    }
    # Валидация перед записью
    ok, errors = validate(data, 'deepseek_cache')
    if not ok:
        # Фолбэк: пишем без валидации, логируем
        pass

    tmp = CACHE_FILE + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.rename(tmp, CACHE_FILE)
    except:
        pass


def call_deepseek_with_cache(match_info, sstats_data, generate_fn, force_refresh=False):
    """
    Вызывает DeepSeek с кешированием.
    
    Args:
        match_info: dict с home, away, league, date
        sstats_data: dict с odds, glicko, totals
        generate_fn: функция, которая делает реальный вызов DeepSeek и возвращает текст
        force_refresh: принудительно пропустить кеш
    
    Returns:
        str: текст прогноза
    """
    cache_key = _prediction_cache_key(match_info, sstats_data)

    if not force_refresh:
        cache = _load_cache()
        if cache_key in cache:
            entry = cache[cache_key]
            # Проверяем, что кеш не устарел
            if time.time() - entry.get('ts', 0) < CACHE_TTL:
                return entry.get('result', '')

    # Кеш промахнулся — вызываем DeepSeek
    result = generate_fn()

    # Сохраняем в кеш
    cache = _load_cache()
    cache[cache_key] = {
        'result': result,
        'ts': time.time(),
        'match': f"{match_info.get('home', '')} — {match_info.get('away', '')}",
    }
    _save_cache(cache)

    return result


def get_cache_stats():
    """Возвращает статистику кеша."""
    cache = _load_cache()
    total = len(cache)
    ages = [time.time() - e.get('ts', 0) for e in cache.values()]
    avg_age = sum(ages) / len(ages) if ages else 0
    return {
        'total_entries': total,
        'avg_age_sec': round(avg_age),
        'max_age_sec': round(max(ages)) if ages else 0,
    }


def clear_cache():
    """Очищает кеш."""
    _save_cache({})


def batch_generate_predictions(matches, generate_one_fn, max_workers=5, force_refresh=False):
    """
    Параллельная генерация прогнозов для списка матчей.
    
    Args:
        matches: список dict с home, away, league и т.д.
        generate_one_fn: функция(match_info) -> str
        max_workers: сколько DeepSeek запросов одновременно (по умолч. 5)
        force_refresh: пропустить кеш
    
    Returns:
        list[str]: прогнозы в том же порядке, что и matches
    """
    results = [None] * len(matches)

    def _task(i, match):
        try:
            return i, generate_one_fn(match)
        except Exception as e:
            print(f'  ⚠️ [{i+1}/{len(matches)}] {match.get("home","?")} — {match.get("away","?")}: {e}')
            return i, None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_task, i, m) for i, m in enumerate(matches)]
        for future in as_completed(futures):
            i, result = future.result()
            results[i] = result
            print(f'  ✅ [{i+1}/{len(matches)}] прогноз готов')

    return results


# ═══════════════════════════════════════════════════════════════════════
#  Единый формат прогноза
# ═══════════════════════════════════════════════════════════════════════

PREDICTION_REQUIRED_FIELDS = {'league', 'home', 'away', 'prediction'}
PREDICTION_PATH = '/opt/predictions_data.json'

# Проверка доступности БД (один раз)
_DB_AVAILABLE = False
try:
    import db
    _DB_AVAILABLE = True
except Exception:
    _DB_AVAILABLE = False


def normalize_prediction(pred: dict) -> dict:
    """Привести прогноз к единому формату (добавить отсутствующие поля с None)."""
    norm = dict(pred)
    for field in PREDICTION_REQUIRED_FIELDS:
        if field not in norm:
            raise ValueError(f'Прогнозу не хватает обязательного поля {field}: '
                             f'{pred.get("home","?")} — {pred.get("away","?")}')
        if not isinstance(norm[field], str):
            raise ValueError(f'Поле {field} должно быть str, получено {type(norm[field]).__name__}')

    for opt_field in ('verdict', 'time', 'match_date', 'game_id', 'status',
                      'odds', 'totals', 'glicko', 'xgb_verdict',
                      'generated_at', 'has_lineups', 'series', 'surface',
                      'home_en', 'away_en', 'home_ru', 'away_ru',
                      'total_line', 'tournament', 'match_id'):
        if opt_field not in norm:
            norm[opt_field] = None

    if 'status' not in pred or not pred.get('status'):
        norm['status'] = 'upcoming'

    if 'generated_at' not in pred or not pred.get('generated_at'):
        norm['generated_at'] = datetime.now().isoformat()

    return norm


def _make_pred_key(pred: dict) -> str:
    """Ключ для дедупликации: лига||home||away."""
    return f"{pred.get('league','')}||{pred.get('home','')}||{pred.get('away','')}"


# ═══════════════════════════════════════════════════════════════════════
#  Единое сохранение (JSON + PostgreSQL)
# ═══════════════════════════════════════════════════════════════════════

def save_predictions(new_predictions: list, path: str = PREDICTION_PATH):
    """
    Сохранить прогнозы: JSON + PostgreSQL.
    
    Дедупликация по (league, home, away).
    Валидация через data_schemas перед записью.
    
    Args:
        new_predictions: список dict прогнозов
        path: путь к JSON-файлу
    """
    # Отфильтровать None
    new_predictions = [p for p in new_predictions if p]
    if not new_predictions:
        return

    # Нормализация
    normalized = []
    for p in new_predictions:
        try:
            normalized.append(normalize_prediction(p))
        except ValueError as e:
            print(f'  ⚠️ {e}')
            continue

    # Если все прогнозы не прошли нормализацию — ничего не пишем
    if not normalized:
        return

    # JSON — дедупликация с существующими
    existing = {}
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                for p in json.load(f).get('predictions', []):
                    existing[_make_pred_key(p)] = p
        except:
            pass

    for p in normalized:
        existing[_make_pred_key(p)] = p

    # Если после дедупликации всё ещё пусто — не пишем
    if not existing:
        return

    output = {
        'predictions': list(existing.values()),
        'count': len(existing),
        'generated_at': datetime.now().isoformat(),
    }

    # Валидация
    ok, errors = validate(output, 'predictions_data')
    if not ok and output['predictions']:
        print(f'  ⚠️ save_predictions: {len(errors)} ошибок схемы (пишем всё равно)')
        for e in errors[:3]:
            print(f'    - {e}')

    # Атомарная запись
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        os.rename(tmp, path)
    except Exception as e:
        print(f'  ❌ save_predictions JSON: {e}')
        return

    # БД
    if _DB_AVAILABLE:
        for p in normalized:
            try:
                p['status'] = p.get('status', 'upcoming')
                db.save_prediction(p)
            except Exception as e:
                print(f'  ⚠️ DB save: {p.get("home","?")} — {p.get("away","?")}: {e}')
    else:
        print('  ⚠️ БД недоступна — только JSON')


# ═══════════════════════════════════════════════════════════════════════
#  Пост-проверка после batch-генерации
# ═══════════════════════════════════════════════════════════════════════

def run_post_check(sport: str = 'all', path: str = PREDICTION_PATH):
    """Проверить корректность сохранённых прогнозов после batch-генерации.
    
    Args:
        sport: фильтр по спорту ('football', 'NHL', 'NBA', 'ATP', или 'all')
        path: путь к predictions_data.json
    """
    if not os.path.exists(path):
        print(f'  ⚠️ Post-check: {path} не найден!')
        return

    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f'  ❌ Post-check: ошибка чтения: {e}')
        return

    preds = data.get('predictions', [])
    if sport != 'all':
        preds = [p for p in preds if p.get('league') in ('НХЛ', 'NBA', 'ATP', 'WTA') or p.get('sport') == sport]

    if len(preds) == 0:
        print(f'  ❌ Post-check: нет прогнозов для {sport}!')
        return

    # Валидация схемы
    ok, errors = validate(data, 'predictions_data')
    if ok:
        print(f'  ✅ Post-check: {len(preds)} прогнозов, схема OK')
    else:
        print(f'  ⚠️ Post-check: {len(errors)} ошибок схемы')
        for e in errors[:3]:
            print(f'    - {e}')

    # Проверка обязательных полей
    for i, p in enumerate(preds):
        for field in PREDICTION_REQUIRED_FIELDS:
            if field not in p:
                print(f'  ⚠️ Post-check: прогноз [{i}] без поля {field}')


# ═══════════════════════════════════════════════════════════════════════
#  Статистика капера (системный промпт)
# ═══════════════════════════════════════════════════════════════════════

def build_capper_stats_block() -> str:
    """Собрать блок статистики для system prompt.
    Сначала БД, fallback на JSON.
    """
    s = None
    if _DB_AVAILABLE:
        try:
            s = db.get_stats()
        except:
            s = None

    if not s or s.get('total_predictions', 0) < 5:
        # Fallback: JSON
        hist_path = '/opt/predictions_history.json'
        if os.path.exists(hist_path):
            try:
                with open(hist_path, encoding='utf-8') as f:
                    hist = json.load(f)
                s = hist.get('summary', {})
            except:
                pass

    if not s:
        return ''

    total = s.get('total_predictions', 0)
    if total < 5:
        return ''

    win = s.get('win', {})
    tot = s.get('total', {})
    wt = win.get('total', 0) or 1
    tt = tot.get('total', 0) or 1
    wc = win.get('correct', 0)
    tc = tot.get('correct', 0)
    by_league = s.get('by_league', {})

    lines = []
    lines.append('📊 Твоя текущая статистика:')
    lines.append(f'Win: {wc}/{wt} ({wc/wt*100:.0f}%) | Total: {tc}/{tt} ({tc/tt*100:.0f}%)')

    if by_league:
        lines.append('По лигам:')
        for league, st in sorted(by_league.items(),
                                  key=lambda x: x[1].get('win', {}).get('total', 0), reverse=True):
            w = st.get('win', {})
            t = st.get('total', {})
            wt_l = w.get('total', 0) or 1
            tt_l = t.get('total', 0) or 1
            lines.append(f'  {league}: Win {w.get("correct",0)}/{w.get("total",0)} '
                        f'({w.get("correct",0)/wt_l*100:.0f}%), '
                        f'Total {t.get("correct",0)}/{t.get("total",0)} '
                        f'({t.get("correct",0)/tt_l*100:.0f}%)')

    if wc < tc:
        lines.append('Подсказка: исходы — твой слабый сигнал (Win {:.0f}%), будь осторожнее с фаворитами.'.format(
            wc/wt*100))
    else:
        lines.append('Подсказка: тоталы — твой слабый сигнал (Total {:.0f}%), перепроверь аргументы.'.format(
            tc/tt*100))

    return '\n' + '\n'.join(lines)


# ═══════════════════════════════════════════════════════════════════════
#  Event-driven: trigger_generate с debounce
# ═══════════════════════════════════════════════════════════════════════

_TRIGGER_DEBOUNCE = 120  # 2 минуты
_TRIGGER_DIR = '/tmp/.trigger_stamps'


def _trigger_stamp_path(section: str) -> str:
    """Путь к файлу-штампу времени для секции."""
    os.makedirs(_TRIGGER_DIR, exist_ok=True)
    safe = section.replace('/', '_').replace('.', '_')
    return os.path.join(_TRIGGER_DIR, f'{safe}.stamp')


def _trigger_should_fire(section: str) -> bool:
    """Проверить, нужно ли запускать генерацию (debounce)."""
    stamp = _trigger_stamp_path(section)
    try:
        if os.path.exists(stamp):
            with open(stamp) as f:
                last_ts = float(f.read().strip())
            if time.time() - last_ts < _TRIGGER_DEBOUNCE:
                return False  # debounce — не прошло 2 мин
        with open(stamp, 'w') as f:
            f.write(str(time.time()))
        return True
    except Exception:
        return True


def trigger_generate(section: str):
    """
    Асинхронно запустить generate_site.py для секции.

    Debounce: не чаще 1 раза в {_TRIGGER_DEBOUNCE} секунд
    для каждой секции (отдельный файл-штамп).

    Args:
        section: 'schedule', 'predictions', 'results', 'all'
    """
    import subprocess

    if not _trigger_should_fire(section):
        print(f'  ⏳ trigger_generate({section}): debounce (пропускаем)')
        return False

    try:
        subprocess.Popen(
            ['python3', '/opt/generate_site.py', '--section', section],
            cwd='/opt',
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f'  🚀 trigger_generate({section}): запущен в фоне')
        return True
    except Exception as e:
        print(f'  ❌ trigger_generate({section}): {e}')
        return False
