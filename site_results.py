#!/usr/bin/env python3
"""
Страница результатов (читает из БД).

Материалы из БД: matches (finished), predictions (с результатами).
"""

import os, sys, json
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, '/opt')
from date_utils import format_date_display, format_date_iso
import site_common
from site_common import escape, _team_logo, render_match_card

try:
    import db
    _DB_OK = bool(db.get_stats() is not None)
except:
    _DB_OK = False

MOW = timedelta(hours=3)


def _result_card(m, preds_lookup):
    """Карточка результата матча."""
    league = m.get('league', '')
    home = m.get('home', '')
    away = m.get('away', '')
    score = m.get('score', '')

    home_logo = _team_logo(home, league)
    away_logo = _team_logo(away, league)
    
    pred = preds_lookup.get((league, home, away))
    pred_result = None
    if pred:
        rw = pred.get('result_win')
        rt = pred.get('result_total')
        if rw == 'correct' or rt == 'correct':
            pred_result = 'correct'
        elif rw == 'incorrect' or rt == 'incorrect':
            pred_result = 'incorrect'

    return render_match_card(
        home=home, away=away, league=league,
        status='finished',
        score=score,
        home_logo=home_logo,
        away_logo=away_logo,
        pred_result=pred_result,
    )


def generate_results(output_path='/var/www/sport/results.html'):
    now = datetime.now(timezone.utc) + MOW
    now_str = format_date_display(now) + ' ' + now.strftime('%H:%M')
    yesterday = format_date_iso((now - timedelta(days=1)))

    matches_by_date = defaultdict(list)
    preds_lookup = {}

    # БД: результаты
    if _DB_OK:
        try:
            yesterday_matches = db.execute(
                "SELECT * FROM matches WHERE status='finished' AND match_date >= CURRENT_DATE - 1 ORDER BY match_time",
            )
            for m in yesterday_matches:
                matches_by_date[str(m['match_date'])[:10]].append(dict(m))

            # Прогнозы с результатами
            finished_preds = db.execute(
                "SELECT * FROM predictions WHERE status='finished' ORDER BY evaluated_at DESC"
            )
            for p in finished_preds:
                key = (p['league'], p['home'], p['away'])
                preds_lookup[key] = dict(p)
        except Exception as e:
            print(f'  ⚠️ БД: {e}')

    if not matches_by_date:
        # Fallback: live_scores
        from generate_site_legacy import get_results_text, _load_live_scores
        live = _load_live_scores()
        fallback_html = get_results_text(live)
        matches_by_date['yesterday'] = []
        html = site_common.page_header('Результаты', 'results', now_str)
        html += f'<div class="section-title">📊 Результаты</div>'
        html += fallback_html if fallback_html else '<p style="color:#666;font-size:14px">Нет данных.</p>'
        html += site_common.page_footer()
        html = html.replace('JS_PLACEHOLDER', site_common.page_script('{}', '{}'))
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f'✅ Результаты (fallback): {output_path}')
        return bool(fallback_html)

    html = site_common.page_header('Результаты', 'results', now_str)

    for date_key in sorted(matches_by_date.keys(), reverse=True):
        # Формат даты: DD.MM.YYYY
        try:
            dt = date_key if isinstance(date_key, datetime) else datetime.strptime(str(date_key), '%Y-%m-%d')
            display_date = dt.strftime('%d.%m.%Y')
        except:
            display_date = date_key

        html += f'<div class="section-title">📊 {display_date}</div><div class="card-grid">'
        for m in matches_by_date[date_key]:
            html += _result_card(m, preds_lookup)
        html += '</div>'

    html += site_common.page_footer()
    html = html.replace('JS_PLACEHOLDER', site_common.page_script('{}', '{}'))

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    total = sum(len(v) for v in matches_by_date.values())
    print(f'✅ Результаты ({total}): {output_path}')
    return total


if __name__ == '__main__':
    generate_results()
