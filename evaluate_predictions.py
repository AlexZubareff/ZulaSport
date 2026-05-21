#!/usr/bin/env python3
"""
Оценка точности прогнозов — по типу ставки.

Читает очередь прогнозов (predictions_data.json), матчит с результатами
из live_scores (live/finished) и daily_results (finished).
Оценённые прогнозы переносит в history, из очереди удаляет.

Запуск: после daily_results (9:15 МСК) и после live-обновлений.
"""

import os, json
from datetime import datetime, timezone
from collections import defaultdict

# Импорт маппера команд
import team_mapper

# БД (если доступна)
try:
    import db
    _DB_AVAILABLE = True
except Exception:
    _DB_AVAILABLE = False

# ─── Пути ───────────────────────────────────────────────────────────
PRED_PATH = '/opt/predictions_data.json'
HISTORY_PATH = '/opt/predictions_history.json'
LIVE_PATH = '/tmp/live_scores_data.json'
RESULTS_PATH = '/tmp/daily_results_data.json'
UTC = timezone.utc


# ─── Хелперы ───────────────────────────────────────────────────────


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except:
        return default


def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_score(score_str):
    """(total_home_goals, total_away_goals) из строки счёта."""
    if not score_str:
        return None, None
    if '-' in score_str and ':' not in score_str:
        parts = score_str.strip().split()
        if not parts:
            return None, None
        last = parts[-1]
        if '-' not in last:
            return None, None
        a, b = last.split('-')
        try:
            return int(a), int(b)
        except:
            return None, None
    if ':' in score_str:
        a, b = score_str.split(':')
        try:
            return int(a), int(b)
        except:
            return None, None
    return None, None


def total_goals(score_str):
    h, a = parse_score(score_str)
    if h is None or a is None:
        return None
    return h + a


# ─── Win (П1/Х/П2) ─────────────────────────────────────────────────


def result_outcome(score_str):
    h, a = parse_score(score_str)
    if h is None or a is None:
        return None
    if h > a:
        return 'home'
    elif a > h:
        return 'away'
    else:
        return 'draw'


def predicted_outcome(pred):
    g = pred.get('glicko', {})
    if not g:
        return None, None
    probs = {
        'home': g.get('home_prob', 0),
        'draw': g.get('draw_prob', 0),
        'away': g.get('away_prob', 0),
    }
    best = max(probs, key=probs.get)
    return best, probs[best]


# ─── Total (Over/Under) ─────────────────────────────────────────────


def predicted_total(pred):
    t = pred.get('totals')
    if not t or not isinstance(t, dict):
        return None, None
    over_odds = t.get('over')
    under_odds = t.get('under')
    line = t.get('total_line')
    if over_odds is None or under_odds is None or line is None:
        return None, None
    if over_odds <= under_odds:
        return 'over', line
    else:
        return 'under', line


def actual_total_outcome(score_str, line):
    total = total_goals(score_str)
    if total is None or line is None:
        return None
    if total > line:
        return 'over'
    else:
        return 'under'


# ─── Форматирование отчёта ──────────────────────────────────────────


def fmt_accuracy(correct, total):
    if total == 0:
        return '—'
    pct = round(correct / total * 100, 1)
    icon = '🟢' if pct >= 60 else '🟡' if pct >= 40 else '🔴'
    return f'{icon} {correct}/{total} ({pct}%)'


# ─── Вычисление result_data из прогноза и счёта ────────────────────


def compute_result(pred, score_str):
    """Вычисляет result_data (win + total) для прогноза с заданным счётом."""
    if not score_str:
        return None

    best_outcome, confidence = predicted_outcome(pred) or (None, None)
    rec_total, total_line = predicted_total(pred)

    # win
    actual = result_outcome(score_str)
    win_data = None
    if best_outcome and actual:
        win_data = {
            'predicted': best_outcome,
            'actual': actual,
            'confidence': round(confidence, 2) if confidence else None,
            'correct': (best_outcome == actual),
        }

    # total
    actual_tot = actual_total_outcome(score_str, total_line)
    total_data = None
    if rec_total and actual_tot:
        total_data = {
            'predicted': rec_total,
            'actual': actual_tot,
            'line': total_line,
            'correct': (rec_total == actual_tot),
        }

    return {'win': win_data, 'total': total_data}


# ─── Сбор счётов из разных источников ──────────────────────────────


def _build_score_lookup():
    """
    Собирает lookup (league, home, away) → score из всех доступных источников.
    Приоритет: live (если finished) > daily_results (finished).
    Имена команд приводятся к каноническому виду через team_mapper.
    Возвращает словарь ключ→(score, status).
    """
    lookup = {}
    all_result_names = []

    # 1. Live scores (только finished — счёт окончательный)
    live = load_json(LIVE_PATH, {})
    for key, m in live.get('matches', {}).items():
        if m.get('status') in ('finished',) and m.get('score'):
            parts = key.split('||', 2)
            if len(parts) == 3:
                home_canon, _ = team_mapper.resolve(parts[1])
                away_canon, _ = team_mapper.resolve(parts[2])
                lookup[(parts[0], home_canon, away_canon)] = (m['score'], 'finished')

    # 2. Daily results (finished)
    results = load_json(RESULTS_PATH, {})
    for r in results.get('results', []):
        league = r.get('league', '')
        home = r.get('home', '')
        away = r.get('away', '')
        score = r.get('score')
        if league and home and away and score:
            home_canon, _ = team_mapper.resolve(home)
            away_canon, _ = team_mapper.resolve(away)
            k = (league, home_canon, away_canon)
            all_result_names.append(home)
            all_result_names.append(away)
            lookup[k] = (score, 'finished')

    return lookup


# ═══════════════════ Оценка ═══════════════════════════════════════


def evaluate():
    now = datetime.now(UTC)

    queue = load_json(PRED_PATH, {}).get('predictions', [])
    history = load_json(HISTORY_PATH, {'predictions': [], 'summary': {}, 'last_updated': None})

    # Строим lookup счётов
    score_lookup = _build_score_lookup()
    if not score_lookup:
        print('  Нет данных о результатах (live + daily_results пусты)')
        return

    # Строим список всех известных имён для fuzzy fallback
    all_names = []
    for k in score_lookup:
        all_names.append(k[1])
        all_names.append(k[2])

    # Собираем все прогнозы кандидаты: очередь + upcoming записи в истории
    hist_preds = history.get('predictions', [])
    history_unresolved = [
        hp for hp in hist_preds
        if hp.get('status') in ('upcoming', None) and not hp.get('evaluated_at')
    ]

    candidates = list(queue) + history_unresolved
    total_candidates = len(candidates)

    if not candidates:
        print('  Нет прогнозов для оценки (очередь пуста, все исторические оценены)')
        return

    evaluated = []     # прогнозы, которые получили счёт → в историю

    def _pred_key(p):
        return (p.get('league',''), p.get('home',''), p.get('away',''), p.get('generated_at',''))
    
    queue_keys = {_pred_key(qp) for qp in queue}

    for pred in candidates:
        # Маппинг через team_mapper
        home_canon, _ = team_mapper.resolve(pred.get('home', ''), all_names)
        away_canon, _ = team_mapper.resolve(pred.get('away', ''), all_names)
        teams_key = (pred.get('league', ''), home_canon, away_canon)
        score_info = score_lookup.get(teams_key)

        if score_info:
            score_str, status = score_info
            result_data = compute_result(pred, score_str)

            # Запись для истории
            gen = pred.get('generated_at', now.isoformat())
            try:
                pred_date = datetime.fromisoformat(gen).strftime('%d.%m.%Y')
            except:
                pred_date = now.strftime('%d.%m.%Y')

            match_id = f"{pred_date}||{pred.get('league','')}||{pred.get('home','')}||{pred.get('away','')}"

            history_entry = {
                'match_id': match_id,
                'date': pred_date,
                'league': pred.get('league', ''),
                'home': pred.get('home', ''),
                'away': pred.get('away', ''),
                'time': pred.get('time', ''),
                'status': 'finished',
                'score': score_str,
                'prediction_text': pred.get('prediction', ''),
                'verdict': pred.get('verdict', ''),
                'odds': pred.get('odds'),
                'totals': pred.get('totals'),
                'glicko': pred.get('glicko'),
                'result': result_data,
                'generated_at': gen,
                'evaluated_at': now.isoformat(),
            }
            evaluated.append(history_entry)
            # Запоминаем, что этот queue-прогноз оценён
            if _pred_key(pred) in queue_keys:
                queue_keys.discard(_pred_key(pred))

    # ── Добавляем/обновляем оценённые в истории ──
    hist_preds = history.get('predictions', [])
    existing_map = {h.get('match_id'): i for i, h in enumerate(hist_preds)}
    new_count = 0
    updated_count = 0
    for entry in evaluated:
        mid = entry['match_id']
        if mid in existing_map:
            # Обновляем существующую запись (добавляем score, result, evaluated_at)
            idx = existing_map[mid]
            old = hist_preds[idx]
            # Не перезаписываем, если уже есть score (был оценён ранее)
            if old.get('score') and old.get('evaluated_at'):
                continue  # уже был финальный результат
            old['score'] = entry['score']
            old['status'] = 'finished'
            old['result'] = entry['result']
            old['evaluated_at'] = entry['evaluated_at']
            updated_count += 1
        else:
            hist_preds.append(entry)
            existing_map[mid] = len(hist_preds) - 1
            new_count += 1

    history['predictions'] = hist_preds

    # ── Пересчитываем сводку ──
    finished = [h for h in hist_preds if h.get('status') == 'finished']

    win_total = sum(1 for h in finished if h.get('result') and h['result'].get('win') and h['result']['win'].get('correct') is not None)
    win_correct = sum(1 for h in finished if h.get('result') and h['result'].get('win') and h['result']['win'].get('correct') is True)
    tot_total = sum(1 for h in finished if h.get('result') and h['result'].get('total') and h['result']['total'].get('correct') is not None)
    tot_correct = sum(1 for h in finished if h.get('result') and h['result'].get('total') and h['result']['total'].get('correct') is True)

    by_league = defaultdict(lambda: {'win': {'total': 0, 'correct': 0}, 'total': {'total': 0, 'correct': 0}})
    for h in finished:
        league = h['league']
        r = h.get('result', {})
        if r.get('win') and r['win'].get('correct') is not None:
            by_league[league]['win']['total'] += 1
            if r['win']['correct']:
                by_league[league]['win']['correct'] += 1
        if r.get('total') and r['total'].get('correct') is not None:
            by_league[league]['total']['total'] += 1
            if r['total']['correct']:
                by_league[league]['total']['correct'] += 1

    history['summary'] = {
        'total_predictions': len(hist_preds),
        'finished': len(finished),
        'upcoming': len([h for h in hist_preds if h['status'] == 'upcoming']),
        'win': {'total': win_total, 'correct': win_correct, 'incorrect': win_total - win_correct},
        'total': {'total': tot_total, 'correct': tot_correct, 'incorrect': tot_total - tot_correct},
        'by_league': dict(by_league),
    }
    history['last_updated'] = now.isoformat()

    save_json(HISTORY_PATH, history)

    # ── БД: сохраняем оценённые ──
    if _DB_AVAILABLE:
        for entry in evaluated:
            try:
                # Преобразуем history_entry в формат БД
                entry['status'] = 'finished'
                # result уже вложенный — db._pred_to_params разберёт
                db.save_prediction(entry)
            except Exception:
                pass

    # ── Обновляем очередь (удаляем оценённые) ──
    still_waiting = [qp for qp in queue if _pred_key(qp) in queue_keys]
    if still_waiting:
        save_json(PRED_PATH, {
            'predictions': still_waiting,
            'count': len(still_waiting),
            'generated_at': now.isoformat(),
        })
    else:
        # Очередь пуста — удаляем файл
        if os.path.exists(PRED_PATH):
            os.remove(PRED_PATH)

    # ── Вывод ──
    s = history['summary']
    print(f'\n  Оценено: {new_count} новых + {updated_count} обновлено')
    print(f'  В очереди осталось: {len(still_waiting)}')
    print(f'  История: {s["total_predictions"]} всего ({s["finished"]} завершено, {s["upcoming"]} предстоит)')

    win_pct = fmt_accuracy(s['win']['correct'], s['win']['total'])
    tot_pct = fmt_accuracy(s['total']['correct'], s['total']['total'])
    print(f'  🎯 Исход (П1/Х/П2): {win_pct}')
    print(f'  📊 Тотал (Over/Under): {tot_pct}')

    if by_league:
        print(f'\n  По лигам:')
        for league in sorted(by_league.keys()):
            v = by_league[league]
            print(f'    {league}: '
                  f'🎯 {fmt_accuracy(v["win"]["correct"], v["win"]["total"])} / '
                  f'📊 {fmt_accuracy(v["total"]["correct"], v["total"]["total"])}')

    return history


if __name__ == '__main__':
    evaluate()
