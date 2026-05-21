#!/usr/bin/env python3
"""
Страница прогнозов (читает из БД).

Инкрементальная генерация:
- Первые 20 прогнозов — статический HTML
- Остальные — JSON-блоб + JS-рендер (как liveScores или новости)
- Кнопка "Показать ещё" подгружает остальные
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

# ─── JS для инкрементальной подгрузки ──────────────────────────────

_INCREMENTAL_JS = '''<script>
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

function predCardHtml(league, home, away, timeStr, text, hLogo, aLogo, winLabel, totalLabel, cid) {
    var top = '<div class="up-card up-card-v1">' +
        '<div class="up-v1-grid"><div class="up-v1-left">' +
        '<div class="up-v1-row"><span class="up-v1-team-row">' +
        (hLogo ? '<img class="rl-logo" src="' + hLogo + '" alt="" loading="lazy" onerror="this.style.display=\'none\'">' : '') +
        '<span class="up-v1-name">' + escapeHtml(home) + '</span></span></div>' +
        '<div class="up-v1-row up-v1-row-away"><span class="up-v1-team-row">' +
        (aLogo ? '<img class="rl-logo" src="' + aLogo + '" alt="" loading="lazy" onerror="this.style.display=\'none\'">' : '') +
        '<span class="up-v1-name">' + escapeHtml(away) + '</span></span></div>' +
        '</div><div class="up-v1-right">' +
        (timeStr ? '<div class="up-v1-time">' + escapeHtml(timeStr) + '</div>' : '') +
        '</div></div></div>';
    return '<div class="pred-widget">' + top +
        '<div class="pred-mid">' + escapeHtml(winLabel) + ' ' + escapeHtml(totalLabel) + '</div>' +
        '<button class="p-btn" onclick="toggleTxt(\\'' + cid + '\\')" id="b-' + cid + '">Показать прогноз</button>' +
        '<div class="p-txt" id="' + cid + '" style="display:none">' + escapeHtml(text) + '</div></div>';
}

function escapeHtml(s) {
    if (!s) return '';
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
            .replace(/'/g,'&#039;').replace(/"/g,'&quot;');
}

var PRED_DATA = {};
var PRED_INITIAL = 20;
var PRED_COUNTER = {};

function loadMorePreds(league) {
    var data = PRED_DATA[league];
    if (!data) return;
    var start = PRED_COUNTER[league] || PRED_INITIAL;
    var batch = data.slice(start, start + 10);
    if (batch.length === 0) {
        var btn = document.getElementById('pm-' + league.replace(/[^a-zA-Z0-9]/g, '_'));
        if (btn) btn.style.display = 'none';
        return;
    }
    var container = document.getElementById('pc-' + league.replace(/[^a-zA-Z0-9]/g, '_'));
    for (var i = 0; i < batch.length; i++) {
        var p = batch[i];
        var cid = 'pj' + p._idx;
        var html = predCardHtml(league, p.home, p.away, p.timeStr, p.text,
            p.hLogo, p.aLogo, p.winLabel, p.totalLabel, cid);
        var div = document.createElement('div');
        div.innerHTML = html;
        container.appendChild(div.firstChild);
    }
    PRED_COUNTER[league] = start + batch.length;
    if (start + batch.length >= data.length) {
        var btn = document.getElementById('pm-' + league.replace(/[^a-zA-Z0-9]/g, '_'));
        if (btn) btn.style.display = 'none';
    }
}
</script>'''


# ─── Функции для построения карточки ──────────────────────────────

def _build_pred_data(pred):
    """Извлечь данные прогноза для JSON-блоб (без генерации HTML)."""
    league = pred.get('league', '')
    is_tennis = league in ('ATP', 'WTA')
    home = pred.get('home', '')
    away = pred.get('away', '')
    home_display = pred.get('home_ru', '') or tennis_ru_name(home) if is_tennis else home
    away_display = pred.get('away_ru', '') or tennis_ru_name(away) if is_tennis else away
    time_str = pred.get('match_time', '') or pred.get('time', '')
    text = pred.get('prediction_text', '') or pred.get('prediction', '') or pred.get('verdict', '')
    home_logo = _team_logo(home_display, league)
    away_logo = _team_logo(away_display, league)

    hp = float(pred.get('glicko_home_prob', 0) or 0)
    ap = float(pred.get('glicko_away_prob', 0) or 0)
    if is_tennis:
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

    return {
        'home': home_display,
        'away': away_display,
        'timeStr': time_str,
        'text': text,
        'hLogo': home_logo,
        'aLogo': away_logo,
        'winLabel': win_label,
        'totalLabel': total_label,
    }


def _static_card(pred, cid):
    """Сгенерировать статический HTML для прогноза."""
    d = _build_pred_data(pred)
    text = d['text']
    league = pred.get('league', '')
    home_display = d['home']
    away_display = d['away']
    time_str = d['timeStr']
    home_logo = d['hLogo']
    away_logo = d['aLogo']
    win_label = d['winLabel']
    total_label = d['totalLabel']

    top = render_match_card(
        home=home_display, away=away_display, league=league,
        status='scheduled',
        match_time=time_str,
        home_logo=home_logo,
        away_logo=away_logo,
        has_pred=True,
    )

    return f'''
<div class="pred-widget">
{top}
    <div class="pred-mid">{win_label} {total_label}</div>
    <button class="p-btn" onclick="toggleTxt('{cid}')" id="b-{cid}">Показать прогноз</button>
    <div class="p-txt" id="{cid}" style="display:none">{html_mod.escape(text)}</div>
</div>'''


# ═══════════════════ Генератор ═════════════════════════════════════

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

    # Собираем превью-данные для JS
    pred_data_js = {}
    all_preds_flat = []
    pred_idx = 0

    for league in sorted(preds_by_league.keys()):
        items = []
        for p in preds_by_league[league]:
            d = _build_pred_data(p)
            d['_idx'] = pred_idx
            all_preds_flat.append(d)
            items.append(d)
            pred_idx += 1
        pred_data_js[league] = items

    # JS-данные (переносим только необходимые поля)
    js_data = {}
    for league, items in pred_data_js.items():
        js_data[league] = [{
            'home': i['home'],
            'away': i['away'],
            'timeStr': i['timeStr'],
            'text': i['text'],
            'hLogo': i['hLogo'],
            'aLogo': i['aLogo'],
            'winLabel': i['winLabel'],
            'totalLabel': i['totalLabel'],
            '_idx': i['_idx'],
        } for i in items]

    pred_json_escaped = json.dumps(js_data, ensure_ascii=False)

    html = site_common.page_header('Прогнозы', 'predictions', now_str)
    html += '<div class="section-title">📈 Активные прогнозы</div>'

    if not preds_by_league:
        html += '<p style="color:#666;font-size:14px">Нет активных прогнозов.</p>'
    else:
        html += '<div class="card-grid">'
        for league in sorted(preds_by_league.keys()):
            sport = 'tennis' if league in ('ATP', 'WTA') else 'football'
            html += site_common.section_header(league, sport)

            items = preds_by_league[league]
            static_count = min(20, len(items))

            # Статические (первые 20)
            for p in items[:static_count]:
                cid = 'p' + hashlib.md5(
                    f'{p.get("league","")}||{p.get("home","")}||{p.get("away","")}'.encode()
                ).hexdigest()[:8]
                html += _static_card(p, cid)

            # Контейнер для динамических
            league_safe = league.replace('/', '_').replace(' ', '_')
            dynamic_count = len(items) - static_count
            if dynamic_count > 0:
                html += f'''<div id="pc-{league_safe}"></div>
                <button id="pm-{league_safe}" class="more-btn" onclick="loadMorePreds('{escape(league)}')">
                    Показать ещё ({dynamic_count})</button>'''

        html += '</div>'

    html += site_common.page_footer()
    html = html.replace('JS_PLACEHOLDER', site_common.page_script('{}', '{}'))
    html = html.replace('</body>', f'''
<script id="pred-data-json" type="application/json">{pred_json_escaped}</script>
<script>
var PRED_DATA_LOAD = JSON.parse(document.getElementById('pred-data-json').textContent);
PRED_DATA = PRED_DATA_LOAD;
</script>
{_INCREMENTAL_JS}
</body>''')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    total = sum(len(v) for v in preds_by_league.values())
    dynamic_total = sum(max(0, len(v) - 20) for v in preds_by_league.values())
    print(f'✅ Прогнозы ({total}, {dynamic_total} динамических)')
    return total


if __name__ == '__main__':
    generate_predictions()
