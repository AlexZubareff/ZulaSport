#!/usr/bin/env python3
"""
Ежедневный отчёт по статистике прогнозов.
Формирует и отправляет в Telegram из predictions_history.json.

Запуск: 9:20 / 23:20 по крону
"""

import os, sys, json
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '/opt')
from date_utils import format_date_display, format_date_iso

# ─── Конфиг ─────────────────────────────────────────────────────────
HISTORY_PATH = '/opt/predictions_history.json'
BOT_TOKEN = open('/opt/sport_bot.py').read().split('TOKEN = "')[1].split('"')[0]
CHAT_IDS = [208291706]

MOW = timezone(timedelta(hours=3))

# БД
try:
    import db
    _DB_AVAILABLE = True
except:
    _DB_AVAILABLE = False


def send_all(text):
    import requests as _r
    for cid in CHAT_IDS:
        try:
            _r.post(
                f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
                json={'chat_id': cid, 'text': text, 'parse_mode': 'Markdown'},
                timeout=10,
            )
        except:
            pass


def _bar(correct, total):
    if total == 0:
        return '—'
    pct = round(correct / total * 100, 1)
    icon = '🟢' if pct >= 60 else '🟡' if pct >= 40 else '🔴'
    return f'{icon} {correct}/{total} ({pct}%)'


def fmt_summary(summary, today_str):
    lines = []
    lines.append(f'📊 *Статистика прогнозов* — {today_str}')
    lines.append('')

    if not summary or summary.get('total_predictions', 0) == 0:
        lines.append('_Нет данных_')
        return '\n'.join(lines)

    # За сегодня
    finished = [h for h in summary.get('_today', [])
                if h.get('result') and h['result'].get('win')]
    if finished:
        w_tot = sum(1 for h in finished if h['result']['win'].get('correct') is not None)
        w_cor = sum(1 for h in finished if h['result']['win'].get('correct') is True)
        t_tot = sum(1 for h in finished if h['result']['total'].get('correct') is not None)
        t_cor = sum(1 for h in finished if h['result']['total'].get('correct') is True)
        lines.append(f'*За сутки ({len(finished)} матчей)*')
        lines.append(f'  🎯 Исход: {_bar(w_cor, w_tot)}')
        lines.append(f'  📊 Тотал: {_bar(t_cor, t_tot)}')
        lines.append('')

    # За всё время
    s = summary
    lines.append(f'*За всё время ({s["total_predictions"]} прогнозов, '
                 f'{s["finished"]} завершено)*')
    lines.append(f'  🎯 Исход: {_bar(s["win"]["correct"], s["win"]["total"])}')
    lines.append(f'  📊 Тотал: {_bar(s["total"]["correct"], s["total"]["total"])}')
    lines.append('')

    # По лигам
    by_league = s.get('by_league', {})
    if by_league:
        lines.append('*По лигам:*')
        for league in sorted(by_league.keys()):
            v = by_league[league]
            lines.append(f'  {league}')
            lines.append(f'    🎯 Исход: {_bar(v["win"]["correct"], v["win"]["total"])}')
            lines.append(f'    📊 Тотал: {_bar(v["total"]["correct"], v["total"]["total"])}')

    return '\n'.join(lines)


def main():
    now = datetime.now(MOW)
    today_str = format_date_display(now)
    today_iso = format_date_iso(now)

    summary = None

    # БД
    if _DB_AVAILABLE:
        try:
            s = db.get_stats()
            if s and s.get('total_predictions', 0) > 0:
                summary = s
                # Сегодняшние
                today_preds = db.execute(
                    "SELECT * FROM predictions WHERE status='finished' AND match_date = %s",
                    (today_iso,)
                )
                summary['_today'] = [dict(r) for r in today_preds] if today_preds else []
                print(f'📊 Из БД: {summary["total_predictions"]} прогнозов')
        except Exception as e:
            print(f'  БД: {e}')

    # Fallback: JSON
    if not summary and os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, encoding='utf-8') as f:
            data = json.load(f)
        summary = data.get('summary', {})
        all_preds = data.get('predictions', [])
        summary['_today'] = [h for h in all_preds
                             if h.get('match_date') == today_iso or h.get('date') == today_iso
                             and h.get('status') == 'finished']

    if not summary or summary.get('total_predictions', 0) == 0:
        send_all('📊 Статистика прогнозов пока не собирается — нет данных.')
        print('  Нет данных')
        return

    report = fmt_summary(summary, today_str)
    print(report)
    print()
    print('—' * 30)

    send_all(report)
    print('✅ Отправлено')


if __name__ == '__main__':
    main()
