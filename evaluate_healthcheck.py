#!/usr/bin/env python3
"""
Healthcheck связности пайплайна прогнозов.

Проверяет:
1. После каждого прогона evaluate количество finished прогнозов растёт
2. Файлы данных свежие (не старше 24ч)
3. Никакие критичные этапы не падают молча

Запуск: после evaluate_predictions.py (cron 15 6 * * * и */15 10-20 * * *)
Алерт: если evaluate не оценил ни одного нового прогноза за N циклов
"""

import os, json, sys, time
from datetime import datetime, timezone

# ─── Конфиг ─────────────────────────────────────────────────────────
HISTORY_PATH = '/opt/predictions_history.json'
PRED_PATH = '/opt/predictions_data.json'
RESULTS_PATH = '/tmp/daily_results_data.json'
LIVE_PATH = '/tmp/live_scores_data.json'

STATE_FILE = '/opt/.evaluate_health_state.json'
MAX_AGE_HOURS = 8  # Максимальный возраст daily_results
MAX_EMPTY_RUNS = 3  # Сколько раз подряд evaluate может не оценить ничего

# ─── Каналы для алертов ────────────────────────────────────────────
BOT_TOKEN_FILE = '/etc/bot_token.key'
CHANNEL_ID = '-1003928523816'  # @zula_sport_news

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


def send_alert(message):
    """Отправить алерт в Telegram."""
    if not os.path.exists(BOT_TOKEN_FILE):
        print('  Нет bot_token, алерт не отправлен')
        return
    token = open(BOT_TOKEN_FILE).read().strip()
    import requests
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    try:
        requests.post(url, json={
            'chat_id': CHANNEL_ID,
            'text': '🚨 ' + message,
            'parse_mode': 'HTML',
        }, timeout=10)
        print('  Алерт отправлен')
    except Exception as e:
        print(f'  Ошибка отправки алерта: {e}')


def check():
    issues = []
    now = datetime.now(UTC)
    now_ts = now.timestamp()

    # ── Состояние предыдущего запуска ──
    state = load_json(STATE_FILE, {
        'last_finished_count': 0,
        'last_total_predictions': 0,
        'empty_runs': 0,
        'last_check': None,
        'last_alert': None,
    })

    # ── 1. История прогнозов ──
    history = load_json(HISTORY_PATH)
    if not history:
        issues.append('predictions_history.json не найден')
    else:
        finished = history.get('summary', {}).get('finished', 0)
        total = history.get('summary', {}).get('total_predictions', 0)

        print(f'История: {total} всего, {finished} завершено')

        if finished > state.get('last_finished_count', 0):
            # Прогресс есть — сбрасываем счётчик пустых прогонов
            state['empty_runs'] = 0
            print(f'  Прогресс: +{finished - state["last_finished_count"]} новых finished')
        elif finished == state.get('last_finished_count', 0):
            # Finished не растёт
            state['empty_runs'] = state.get('empty_runs', 0) + 1
            print(f'  Нет новых finished ({state["empty_runs"]}/{MAX_EMPTY_RUNS})')

        state['last_finished_count'] = finished
        state['last_total_predictions'] = total

    # ── 2. Очередь ──
    queue = load_json(PRED_PATH, {})
    queue_len = len(queue.get('predictions', [])) if queue else 0
    print(f'Очередь: {queue_len} прогнозов')

    # ── 3. Свежесть данных ──
    for path, label in [(RESULTS_PATH, 'daily_results'), (LIVE_PATH, 'live_scores'),
                         (HISTORY_PATH, 'predictions_history')]:
        if os.path.exists(path):
            mtime = os.path.getmtime(path)
            age_hours = (now_ts - mtime) / 3600
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

    # ── 4. Срабатываем по порогам ──
    if issues:
        alert_text = 'Проблемы пайплайна прогнозов:\n' + '\n'.join(f'• {i}' for i in issues)
        print(f'\n⚠️ Проблемы:\n' + '\n'.join(f'  • {i}' for i in issues))

        # Дедупликация алертов: не чаще раза в час
        last_alert = state.get('last_alert')
        silence_period = 3600  # 1 час
        if not last_alert or (now_ts - last_alert) > silence_period:
            send_alert(alert_text)
            state['last_alert'] = now_ts
    else:
        print('\n✅ Все проверки пройдены')

    if state['empty_runs'] >= MAX_EMPTY_RUNS:
        alert_text = (f'evaluate не оценил новых прогнозов {state["empty_runs"]} раз подряд. '
                      f'Возможно, daily_results не обновляются или маппинг имён сломан.')
        if not state.get('last_alert') or (now_ts - state['last_alert']) > 3600:
            send_alert(alert_text)
            state['last_alert'] = now_ts

    state['last_check'] = now.isoformat()
    save_json(STATE_FILE, state)

    return len(issues) + (state['empty_runs'] >= MAX_EMPTY_RUNS)


if __name__ == '__main__':
    problems = check()
    sys.exit(min(problems, 127))  # exit code = number of problems