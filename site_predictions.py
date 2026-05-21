#!/usr/bin/env python3
"""
Страница прогнозов (читает из БД).
"""

import os, sys, json, hashlib, html as html_mod
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, '/opt')
import site_common
from site_common import escape, _team_logo, render_match_card

# Теннисные имена (русские переводы)
from tennis_names import ru_name as tennis_ru_name

# БД
try:
    import db
    _DB_OK = bool(db.get_stats())
except:
    _DB_OK = False

MOW = timedelta(hours=3)


def _card(pred):
    """Карточка прогноза: render_match_card + бейдж + кнопка."""
    league = pred.get('league', '')
    is_tennis = league in ('ATP', 'WTA')
    home = pred.get('home', '')
    away = pred.get('away', '')
    home_display = pred.get('home_ru', '') or tennis_ru_name(home) if is_tennis else home
    away_display = pred.get('away_ru', '') or tennis_ru_name(away) if is_tennis else away
    time_str = pred.get('match_time', '') or pred.get('time', '')
    cid = 'p' + hashlib.md5(f'{league}||{home}||{away}'.encode()).hexdigest()[:8]
    text = pred.get('prediction_text', '') or pred.get('prediction', '') or pred.get('verdict', '')

    home_logo = _team_logo(home_display, league)
    away_logo = _team_logo(away_display, league)

    # Вероятности → бейдж
    hp = float(pred.get('glicko_home_prob', 0) or 0)
    ap = float(pred.get('glicko_away_prob', 0) or 0)
    if is_tennis:
        # В теннисе нет ничьей
        dp = 0.0
        win_label = 'П1' if hp >= ap else 'П2'
    else:
        dp = float(pred.get('glicko_draw_prob', 0) or 0)
        win_label = max([('П1', hp), ('X', dp), ('П2', ap)], key=lambda x: x[1])[0]
    tl = float(pred.get('total_line', 2.5) or 2.5)
    over = pred.get('odds_over')
    under = pred.get('odds_under')
    if over and under:
        total_label = f'ТБ {tl}' if float(over) <= float(under) else f'ТМ {tl}'
    elif over:
        total_label = f'ТБ {tl}'
    elif under:
        total_label = f'ТМ {tl}'
    else:
        total_label = '—'

    top = render_match_card(
        home=home_display, away=away_display, league=league,
        status='scheduled',
        match_time=time_str,
        home_logo=home_logo,
        away_logo=away_logo,
        has_pred=True,
    )

    html = f'''
<div class="pred-widget">
{top}
    <div class="pred-mid">{win_label} {total_label}</div>
    <button class="p-btn" onclick="toggleTxt('{cid}')" id="b-{cid}">Показать прогноз</button>
    <div class="p-txt" id="{cid}" style="display:none">{html_mod.escape(text)}</div>
</div>'''
    return html


def generate_predictions(output_path='/var/www/sport/predictions.html'):
    now = datetime.now(timezone.utc) + MOW
    now_str = now.strftime('%d.%m.%Y %H:%M')

    preds_by_league = defaultdict(list)

    # БД
    if _DB_OK:
        try:
            for p in db.get_queue():
                preds_by_league[p.get('league', 'Другое')].append(dict(p))
        except Exception as e:
            print(f'  ⚠️ БД: {e}')
    else:
        # Fallback: JSON
        fpath = '/opt/predictions_data.json'
        if os.path.exists(fpath):
            try:
                with open(fpath, encoding='utf-8') as f:
                    for p in json.load(f).get('predictions', []):
                        preds_by_league[p.get('league', 'Другое')].append(p)
            except:
                pass

    js = '''<script>
function toggleTxt(id) {
    var el = document.getElementById(id);
    var btn = document.getElementById('b-' + id);
    if (el.style.display === 'none') {
        el.style.display = "block";
        el.parentNode.style.zIndex = "20";
        btn.textContent = 'Закрыть';
    } else {
        el.style.display = "none";
        el.parentNode.style.zIndex = "";
        btn.textContent = 'Показать прогноз';
    }
}
</script>'''

    html = site_common.page_header('Прогнозы', 'predictions', now_str)
    html += '<div class="section-title">📈 Активные прогнозы</div>'

    if not preds_by_league:
        html += '<p style="color:#666;font-size:14px">Нет активных прогнозов.</p>'
    else:
        html += '<div class="card-grid">'
        for league in sorted(preds_by_league.keys()):
            sport = 'tennis' if league in ('ATP', 'WTA') else 'football'
            html += site_common.section_header(league, sport)
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
