#!/usr/bin/env python3
"""
Страница прогнозов.
Карточка как на расписании, но с прогнозом посередине.
"""

import os, sys, json, hashlib, html as html_mod
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, '/opt')
import site_common
from generate_site_legacy import _team_logo, _TEAM_LOGOS, escape

UTC = timezone.utc
MOW = timedelta(hours=3)


def _card(pred):
    """Карточка как на расписании + прогноз посередине."""
    league = pred.get('league', '')
    home = pred.get('home', '')
    away = pred.get('away', '')
    time_str = pred.get('time', '')
    odds = pred.get('odds', {})
    totals = pred.get('totals', {})
    glicko = pred.get('glicko', {})
    cid = 'p' + hashlib.md5(f'{league}||{home}||{away}'.encode()).hexdigest()[:8]
    text = pred.get('prediction', '') or pred.get('verdict', '')

    # Флаги и лого как в _render_match_card
    _info_h = _TEAM_LOGOS.get(home, {})
    _info_a = _TEAM_LOGOS.get(away, {})
    h_flag = _info_h.get('flag', '') if isinstance(_info_h, dict) else ''
    a_flag = _info_a.get('flag', '') if isinstance(_info_a, dict) else ''
    home_disp = f'{h_flag} {escape(home)}' if h_flag else escape(home)
    away_disp = f'{a_flag} {escape(away)}' if a_flag else escape(away)

    home_logo = _team_logo(home)
    away_logo = _team_logo(away)
    h_logo = f'<img class="rl-logo" src="{home_logo}" alt="" loading="lazy" onerror="this.style.display=\'none\'">' if home_logo and league in site_common.LOGO_LEAGUES else ''
    a_logo = f'<img class="rl-logo" src="{away_logo}" alt="" loading="lazy" onerror="this.style.display=\'none\'">' if away_logo and league in site_common.LOGO_LEAGUES else ''

    # Прогноз
    hp = glicko.get('home_prob', 0) or 0
    dp = glicko.get('draw_prob', 0) or 0
    ap = glicko.get('away_prob', 0) or 0
    outcomes = [('П1', hp), ('X', dp), ('П2', ap)]
    win_label = max(outcomes, key=lambda x: x[1])[0]

    tl = totals.get('total_line', 2.5)
    over = totals.get('over')
    under = totals.get('under')
    if over and under:
        total_label = f'ТБ {tl}' if float(over) <= float(under) else f'ТМ {tl}'
    elif over:
        total_label = f'ТБ {tl}'
    elif under:
        total_label = f'ТМ {tl}'
    else:
        total_label = '—'

    # Карточка: лево (команды) | центр (прогноз) | право (время)
    html = f'''
<div class="up-card up-card-v1">
    <div class="up-v1-grid">
        <div class="up-v1-left">
            <div class="up-v1-row">
                <span class="up-v1-team-row">{h_logo}<span class="up-v1-name">{home_disp}</span></span>
            </div>
            <div class="up-v1-row up-v1-row-away">
                <span class="up-v1-team-row">{a_logo}<span class="up-v1-name">{away_disp}</span></span>
            </div>
        </div>
        <div class="pred-mid"><div>{win_label} {total_label}</div></div>
        <div class="up-v1-right">
            <div class="up-v1-time">{escape(time_str)}</div>
        </div>
    </div>
    <button class="p-btn" onclick="toggleTxt('{cid}')" id="b-{cid}">Показать прогноз</button>
    <div class="p-txt" id="{cid}" style="display:none">{html_mod.escape(text)}</div>
</div>'''

    return html


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

    js = '''<script>
function toggleTxt(id) {
    var el = document.getElementById(id);
    var btn = document.getElementById('b-' + id);
    if (el.style.display === 'none') {
        el.style.display = 'block';
        btn.textContent = 'Закрыть';
    } else {
        el.style.display = 'none';
        btn.textContent = 'Показать прогноз';
    }
}
</script>'''

    html = site_common.page_header('Прогнозы', 'predictions', now_str)
    html += '<div class="section-title">📈 Активные прогнозы <span style="font-size:11px;color:#555">v3</span></div>'

    if not preds_by_league:
        html += '<p style="color:#666;font-size:14px">Нет активных прогнозов.</p>'
    else:
        html += '<div class="card-grid">'
        for league in sorted(preds_by_league.keys()):
            html += site_common.section_header(league, 'football')
            for p in preds_by_league[league]:
                html += _card(p)
        html += '</div>'

    html += site_common.page_footer()
    html = html.replace('JS_PLACEHOLDER', site_common.page_script('{}', '{}') + js)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    total = sum(len(v) for v in preds_by_league.values())
    print(f'✅ Прогнозы ({total})')
    return total


if __name__ == '__main__':
    generate_predictions()
