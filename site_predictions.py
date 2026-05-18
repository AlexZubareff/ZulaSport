#!/usr/bin/env python3
"""
Страница прогнозов.
Карточка как на расписании + прогноз посередине.
"""

import os, sys, json
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, '/opt')
import site_common
from generate_site_legacy import _team_logo, _TEAM_LOGOS, escape

UTC = timezone.utc
MOW = timedelta(hours=3)

# Логотипы лиг для показа
_LOGO_LEAGUES = {'АПЛ', 'Ла Лига', 'Серия А', 'Бундеслига', 'Лига 1', 'РПЛ', 'НХЛ', 'NBA'}


def _render_card(pred):
    """Карточка матча с прогнозом по центру."""
    league = pred.get('league', '')
    home = pred.get('home', '')
    away = pred.get('away', '')
    time_str = pred.get('time', '')
    odds = pred.get('odds', {})
    totals = pred.get('totals', {})
    glicko = pred.get('glicko', {})

    # Флаги и логотипы команд
    _info_h = _TEAM_LOGOS.get(home, {})
    _info_a = _TEAM_LOGOS.get(away, {})
    h_flag = _info_h.get('flag', '') if isinstance(_info_h, dict) else ''
    a_flag = _info_a.get('flag', '') if isinstance(_info_a, dict) else ''
    home_disp = f'{h_flag} {escape(home)}' if h_flag else escape(home)
    away_disp = f'{a_flag} {escape(away)}' if a_flag else escape(away)

    home_logo = _team_logo(home)
    away_logo = _team_logo(away)
    h_logo = f'<img class="rl-logo" src="{home_logo}" alt="" loading="lazy" onerror="this.style.display=\'none\'">' if home_logo and league in _LOGO_LEAGUES else ''
    a_logo = f'<img class="rl-logo" src="{away_logo}" alt="" loading="lazy" onerror="this.style.display=\'none\'">' if away_logo and league in _LOGO_LEAGUES else ''

    # Прогноз по победителю (максимальная вероятность)
    hp = glicko.get('home_prob', 0) or 0
    dp = glicko.get('draw_prob', 0) or 0
    ap = glicko.get('away_prob', 0) or 0
    outcomes = [('П1', hp), ('X', dp), ('П2', ap)]
    win_label = max(outcomes, key=lambda x: x[1])[0]

    # Прогноз по тоталу (по минимальному кэфу)
    tl = totals.get('total_line', 2.5)
    over = totals.get('over')
    under = totals.get('under')
    if over and under:
        if float(over) <= float(under):
            total_label = f'ТБ {tl}'
        else:
            total_label = f'ТМ {tl}'
    elif over:
        total_label = f'ТБ {tl}'
    elif under:
        total_label = f'ТМ {tl}'
    else:
        total_label = '—'

    return f'''
<div class="up-card up-card-v1 pred-card">
    <div class="up-v1-grid">
        <div class="up-v1-left">
            <div class="up-v1-row">
                <span class="up-v1-team-row">{h_logo}<span class="up-v1-name">{home_disp}</span></span>
            </div>
            <div class="up-v1-row up-v1-row-away">
                <span class="up-v1-team-row">{a_logo}<span class="up-v1-name">{away_disp}</span></span>
            </div>
        </div>
        <div class="pred-center">{win_label} {total_label}</div>
        <div class="up-v1-right">
            <div class="up-v1-time">{escape(time_str)}</div>
        </div>
    </div>
</div>'''


def generate_predictions(output_path='/var/www/sport/predictions.html'):
    now = datetime.now(UTC) + MOW
    now_str = now.strftime('%d.%m.%Y %H:%M')

    preds_by_league = defaultdict(list)
    if os.path.exists('/opt/predictions_data.json'):
        try:
            with open('/opt/predictions_data.json', encoding='utf-8') as f:
                for p in json.load(f).get('predictions', []):
                    preds_by_league[p.get('league', 'Другое')].append(p)
        except:
            pass

    html = site_common.page_header('Прогнозы', 'predictions', now_str)
    html += '<div class="section-title">📈 Активные прогнозы</div>'

    if not preds_by_league:
        html += '<p style="color:#666;font-size:14px">Нет активных прогнозов.</p>'
    else:
        html += '<div class="card-grid">'
        for league in sorted(preds_by_league.keys()):
            html += site_common.section_header(league, 'football')
            for p in preds_by_league[league]:
                html += _render_card(p)
        html += '</div>'

    html += site_common.page_footer()
    html = html.replace('JS_PLACEHOLDER', site_common.page_script('{}', '{}'))

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    total = sum(len(v) for v in preds_by_league.values())
    print(f'✅ Прогнозы ({total})')
    return total


if __name__ == '__main__':
    generate_predictions()
