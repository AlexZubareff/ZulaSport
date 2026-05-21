#!/usr/bin/env python3
"""
Healthcheck связности пайплайна прогнозов.

Проверяет:
1. После каждого прогона evaluate количество finished прогнозов растёт
2. Файлы данных свежие (не старше 24ч)
3. Никакие критичные этапы не падают молча

Выводит проблемы в stdout — перехватывается OpenClaw cron и доставляет сюда.
"""

import os, json, sys
from datetime import datetime, timezone

sys.path.insert(0, '/opt')
from alert import healthcheck_errors, get_all_status, ERROR_STATE_PATH

HISTORY_PATH = '/opt/predictions_history.json'
PRED_PATH = '/opt/predictions_data.json'
RESULTS_PATH = '/tmp/daily_results_data.json'
LIVE_PATH = '/tmp/live_scores_data.json'

STATE_FILE = '/opt/.evaluate_health_state.json'
MAX_AGE_HOURS = 8
MAX_EMPTY_RUNS = 3

UTC = timezone.utc


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


def check():
    issues = []
    now = datetime.now(UTC)
    now_ts = now.timestamp()

    state = load_json(STATE_FILE, {
        'last_finished_count': 0,
        'last_total_predictions': 0,
        'empty_runs': 0,
        'last_check': None,
        'last_alert': None,
    })

    # 1. История прогнозов
    history = load_json(HISTORY_PATH)
    if not history:
        issues.append('predictions_history.json не найден')
    else:
        finished = history.get('summary', {}).get('finished', 0)
        total = history.get('summary', {}).get('total_predictions', 0)
        print(f'История: {total} всего, {finished} завершено')

        if finished > state.get('last_finished_count', 0):
            state['empty_runs'] = 0
            print(f'  Прогресс: +{finished - state["last_finished_count"]} новых finished')
        elif finished == state.get('last_finished_count', 0):
            state['empty_runs'] = state.get('empty_runs', 0) + 1
            print(f'  Нет новых finished ({state["empty_runs"]}/{MAX_EMPTY_RUNS})')

        state['last_finished_count'] = finished
        state['last_total_predictions'] = total

    # 2. Очередь
    queue = load_json(PRED_PATH, {})
    queue_len = len(queue.get('predictions', [])) if queue else 0
    print(f'Очередь: {queue_len} прогнозов')

    # 3. Свежесть данных
    for path, label in [(RESULTS_PATH, 'daily_results'), (LIVE_PATH, 'live_scores'),
                         (HISTORY_PATH, 'predictions_history')]:
        if os.path.exists(path):
            age_hours = (now_ts - os.path.getmtime(path)) / 3600
            if age_hours > MAX_AGE_HOURS:
                msg = f'{label} старше {MAX_AGE_HOURS}ч ({age_hours:.1f}ч)'
                issues.append(msg)
                print(f'  ⚠️ {msg}')
            else:
                print(f'  {label} свеж ({age_hours:.1f}ч)')
        else:
            msg = f'{path} не существует'
            issues.append(msg)
            print(f'  ❌ {msg}')

    # 4. Срабатываем по порогам — только stdout (OpenClaw cron доставит)
    if issues:
        print(f'\n⚠️ Проблемы:')
        for i in issues:
            print(f'  ❌ {i}')

        # Дедупликация: выводим ISSUE только если прошло > 1ч с последнего
        last_alert = state.get('last_alert')
        silence_period = 3600
        if not last_alert or (now_ts - last_alert) > silence_period:
            print(f'\nISSUE: Проблемы пайплайна прогнозов — {" • ".join(issues)}')
            state['last_alert'] = now_ts
    else:
        print('\n✅ Все проверки пройдены')

    if state['empty_runs'] >= MAX_EMPTY_RUNS:
        msg = (f'evaluate не оценил новых прогнозов {state["empty_runs"]} раз подряд. '
               f'Возможно, daily_results не обновляются или маппинг имён сломан.')
        if not state.get('last_alert') or (now_ts - state['last_alert']) > 3600:
            print(f'\nISSUE: {msg}')
            state['last_alert'] = now_ts

    # 5. Проверка счётчиков ошибок из alert.py
    print()
    alert_issues = healthcheck_errors()

    state['last_check'] = now.isoformat()
    save_json(STATE_FILE, state)

    return len(issues) + (state['empty_runs'] >= MAX_EMPTY_RUNS) + alert_issues


if __name__ == '__main__':
    problems = check()
    sys.exit(min(problems, 127))
