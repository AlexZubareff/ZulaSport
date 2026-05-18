#!/usr/bin/env python3
"""
Страница прогнозов.
Карточка — один в один как на расписании (_render_match_card).
Кнопка раскрытия текста — снизу карточки, отдельным блоком.
"""

import os, sys, json, hashlib, html as html_mod
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, '/opt')
import site_common
from generate_site_legacy import _render_match_card, _team_logo

UTC = timezone.utc
MOW = timedelta(hours=3)


def generate_predictions(output_path='/var/www/sport/predictions.html'):
    now = datetime.now(UTC) + MOW
    now_str = now.strftime('%d.%m.%Y %H:%M')

    # Прогнозы из очереди
    preds_by_league = defaultdict(list)
    pred_path = '/opt/predictions_data.json'
    if os.path.exists(pred_path):
        try:
            with open(pred_path, encoding='utf-8') as f:
                for p in json.load(f).get('predictions', []):
                    preds_by_league[p.get('league', 'Другое')].append(p)
        except:
            pass

    # Строим словарь для модалки прогнозов (как на расписании)
    pred_lookup = {}
    for p in sum(preds_by_league.values(), []):
        k = (p.get('league', ''), p.get('home', ''), p.get('away', ''))
        pred_lookup[k] = p

    pred_json = {}
    for k, v in pred_lookup.items():
        key = k[0] + '||' + k[1] + '||' + k[2]
        pred_json[key] = {
            **v,
            'home_logo': _team_logo(k[1]),
            'away_logo': _team_logo(k[2]),
        }
    pred_json_escaped = json.dumps(pred_json, ensure_ascii=False, default=str)

    # JS для сворачивания текста
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
    html += '<div class="section-title">📈 Активные прогнозы</div>'

    if not preds_by_league:
        html += '<p style="color:#666;font-size:14px">Нет активных прогнозов.</p>'
    else:
        html += '<div class="card-grid">'
        for league in sorted(preds_by_league.keys()):
            html += site_common.section_header(league, 'football')
            for p in preds_by_league[league]:
                cid = 'p' + hashlib.md5(f'{league}||{p["home"]}||{p["away"]}'.encode()).hexdigest()[:8]
                text = p.get('prediction', '') or p.get('verdict', '')

                # Карточка — как на расписании, без кнопки прогноза
                match = {
                    'home': p['home'],
                    'away': p['away'],
                    'league': league,
                    'time': p.get('time', ''),
                    'sport': 'football',
                }
                html += _render_match_card(match, {}, pred_lookup, site_common.LOGO_LEAGUES, False)

                # Кнопка и текст снизу карточки
                html += f'''
<button class="p-btn" onclick="toggleTxt('{cid}')" id="b-{cid}">Показать прогноз</button>
<div class="p-txt" id="{cid}" style="display:none">{html_mod.escape(text)}</div>'''
        html += '</div>'

    html += site_common.page_footer()
    html = html.replace('JS_PLACEHOLDER', site_common.page_script('{}', pred_json_escaped) + js)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    total = sum(len(v) for v in preds_by_league.values())
    print(f'✅ Прогнозы ({total})')
    return total


if __name__ == '__main__':
    generate_predictions()
