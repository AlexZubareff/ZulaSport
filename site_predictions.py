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
from name_ru import ru_name as tennis_ru_name

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
    var dateStr = arguments.length > 10 ? arguments[10] : '';
    var oddsH = arguments.length > 11 ? arguments[11] : '';
    var oddsD = arguments.length > 12 ? arguments[12] : '';
    var oddsA = arguments.length > 13 ? arguments[13] : '';
    var oddsRow = '';
    var picks = '<span class="pw-pick-tag">' + escapeHtml(winLabel) + '</span>';
    if (totalLabel && totalLabel !== '—') {
        picks += '<span class="pw-pick-tag">' + escapeHtml(totalLabel) + '</span>';
    }
    if (oddsH || oddsD || oddsA) {
        oddsRow = '<div class="pw-e-odds">';
        if (oddsH) oddsRow += '<span class="pw-odd"><span class="pw-odd-label">П1</span><span class="pw-odd-val">' + oddsH + '</span></span>';
        if (oddsD) oddsRow += '<span class="pw-odd"><span class="pw-odd-label">X</span><span class="pw-odd-val">' + oddsD + '</span></span>';
        if (oddsA) oddsRow += '<span class="pw-odd"><span class="pw-odd-label">П2</span><span class="pw-odd-val">' + oddsA + '</span></span>';
        oddsRow += '</div>';
    }
    return '<div class="pw-e"><div class="up-card up-card-v1"><div class="up-v1-grid">' +
        '<div class="up-v1-left">' +
        '<div class="up-v1-row"><span class="up-v1-team-row">' +
        (hLogo ? '<img class="rl-logo" src="' + hLogo + '" alt="" loading="lazy" onerror="this.style.display=\\'none\\'">' : '') +
        '<span class="up-v1-name">' + escapeHtml(home) + '</span></span></div>' +
        '<div class="up-v1-row up-v1-row-away"><span class="up-v1-team-row">' +
        (aLogo ? '<img class="rl-logo" src="' + aLogo + '" alt="" loading="lazy" onerror="this.style.display=\\'none\\'">' : '') +
        '<span class="up-v1-name">' + escapeHtml(away) + '</span></span></div>' +
        '</div><div class="pw-e-center">' + oddsRow +
        '<div class="pw-e-pick">' + picks + '</div></div>' +
        '<div class="up-v1-right">' +
        (timeStr || dateStr ? '<div class="up-v1-time">' + (dateStr ? escapeHtml(dateStr) + ' ' : '') + (timeStr ? escapeHtml(timeStr) : '') + '</div>' : '') +
        '<div class="up-v1-predict-btn" onclick="toggleTxt(\\'' + cid + '\\')">Прогноз</div>' +
        '</div></div></div><div class="p-txt" id="' + cid + '" style="display:none">' + escapeHtml(text) + '</div></div>';
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
            p.hLogo, p.aLogo, p.winLabel, p.totalLabel, cid,
            p.dateStr, p.oddsHome, p.oddsDraw, p.oddsAway);
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

    # Флаги стран для теннисистов (всегда в приоритете над дефолтными лого)
    if is_tennis:
        _PLAYER_FLAGS = getattr(_build_pred_data, '_player_flags', None)
        if _PLAYER_FLAGS is None:
            try:
                with open('/opt/data/tennis/player_flags.json', encoding='utf-8') as _f:
                    _PLAYER_FLAGS = json.load(_f)
            except:
                _PLAYER_FLAGS = {}
            _build_pred_data._player_flags = _PLAYER_FLAGS
        h_iso = _PLAYER_FLAGS.get(home_display, '')
        a_iso = _PLAYER_FLAGS.get(away_display, '')
        if h_iso:
            home_logo = f'/static/logos/flags/{h_iso}.png'
        if a_iso:
            away_logo = f'/static/logos/flags/{a_iso}.png'

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

    # Дата для отображения на карточке
    raw_date = pred.get('match_date', '')
    date_str = ''
    if raw_date:
        if isinstance(raw_date, str):
            # YYYY-MM-DD → DD.MM
            parts = raw_date.split('-')
            if len(parts) == 3 and len(parts[0]) == 4:
                date_str = f'{parts[2]}.{parts[1]}'
            elif len(raw_date) >= 5 and '.' in raw_date:
                date_str = raw_date[:5]
        elif hasattr(raw_date, 'strftime'):
            date_str = raw_date.strftime('%d.%m')

    return {
        'home': home_display,
        'away': away_display,
        'timeStr': time_str,
        'dateStr': date_str,
        'text': text,
        'hLogo': home_logo,
        'aLogo': away_logo,
        'winLabel': win_label,
        'totalLabel': total_label,
        'oddsHome': str(pred.get('odds_home', '') or ''),
        'oddsDraw': str(pred.get('odds_draw', '') or ''),
        'oddsAway': str(pred.get('odds_away', '') or ''),
    }


def _odds_html(d):
    """Собрать HTML для коэффициентов, если есть."""
    parts = []
    if d.get('oddsHome'):
        parts.append(f'<span class="pw-odd"><span class="pw-odd-label">П1</span><span class="pw-odd-val">{d["oddsHome"]}</span></span>')
    if d.get('oddsDraw'):
        parts.append(f'<span class="pw-odd"><span class="pw-odd-label">X</span><span class="pw-odd-val">{d["oddsDraw"]}</span></span>')
    if d.get('oddsAway'):
        parts.append(f'<span class="pw-odd"><span class="pw-odd-label">П2</span><span class="pw-odd-val">{d["oddsAway"]}</span></span>')
    if not parts:
        return ''
    return '<div class="pw-e-odds">' + ''.join(parts) + '</div>'


def _static_card(pred, cid):
    """Сгенерировать статический HTML для прогноза (вариант E)."""
    d = _build_pred_data(pred)
    text = d['text']
    home_display = d['home']
    away_display = d['away']
    time_str = d['timeStr']
    h_logo = f'<img class="rl-logo" src="{d["hLogo"]}" alt="" loading="lazy" onerror="this.style.display=\'none\'">' if d.get('hLogo') else ''
    a_logo = f'<img class="rl-logo" src="{d["aLogo"]}" alt="" loading="lazy" onerror="this.style.display=\'none\'">' if d.get('aLogo') else ''
    win_label = escape(d['winLabel'])
    total_label = escape(d['totalLabel'])

    odds_html = _odds_html(d)
    picks = f'<span class="pw-pick-tag">{win_label}</span>'
    if total_label and total_label != '—':
        picks += f'<span class="pw-pick-tag">{total_label}</span>'

    # Время + дата
    time_parts = []
    if d.get('dateStr'):
        time_parts.append(escape(d['dateStr']))
    if time_str:
        time_parts.append(escape(time_str))
    time_html = f'<div class="up-v1-time">{" ".join(time_parts)}</div>' if time_parts else ''

    return f'''
<div class="pw-e"><div class="up-card up-card-v1"><div class="up-v1-grid">
    <div class="up-v1-left">
        <div class="up-v1-row"><span class="up-v1-team-row">{h_logo}<span class="up-v1-name">{escape(home_display)}</span></span></div>
        <div class="up-v1-row up-v1-row-away"><span class="up-v1-team-row">{a_logo}<span class="up-v1-name">{escape(away_display)}</span></span></div>
    </div>
    <div class="pw-e-center">{odds_html}<div class="pw-e-pick">{picks}</div></div>
    <div class="up-v1-right">{time_html}<div class="up-v1-predict-btn" onclick="toggleTxt('{cid}')">Прогноз</div></div>
</div></div><div class="p-txt" id="{cid}" style="display:none">{html_mod.escape(text)}</div></div>'''


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

    # Фильтр: убираем прогнозы на уже прошедшие даты
    today = now.date()
    for league in list(preds_by_league.keys()):
        filtered = []
        for p in preds_by_league[league]:
            md = p.get('match_date', '')
            if md:
                try:
                    if isinstance(md, str):
                        if '-' in md and len(md) >= 10:
                            from datetime import date as _d
                            p_date = _d(*map(int, md[:10].split('-')))
                        elif '.' in md and len(md) >= 10:
                            from datetime import date as _d
                            p_date = _d(*map(int, [md[6:10], md[3:5], md[:2]]))
                        else:
                            filtered.append(p)
                            continue
                    elif hasattr(md, 'strftime'):
                        p_date = md
                    else:
                        filtered.append(p)
                        continue
                    if p_date >= today:
                        filtered.append(p)
                except:
                    filtered.append(p)
            else:
                filtered.append(p)
        preds_by_league[league] = filtered

    # Дедупликация: для тенниса — по fuzzy-сравнению имён
    def _name_sim(a, b):
        """Levenshtein similarity (0..1)."""
        n, m = len(a), len(b)
        if n > m: a, b, n, m = b, a, m, n
        curr = list(range(n + 1))
        for i in range(1, m + 1):
            prev, curr = curr, [i] + [0] * n
            for j in range(1, n + 1):
                cost = 0 if a[j - 1] == b[i - 1] else 1
                curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        return 1 - curr[n] / max(n, m, 1)

    # Таблица транслитерации кириллицы → латиницы (для сравнения имён)
    _TRANS_TABLE = str.maketrans({
        'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e',
        'ж':'zh','з':'z','и':'i','й':'i','к':'k','л':'l','м':'m',
        'н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u',
        'ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh','щ':'sh','ъ':'',
        'ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
    })

    def _translit(s):
        return s.translate(_TRANS_TABLE)

    for league in list(preds_by_league.keys()):
        if league in ('ATP', 'WTA'):
            original = preds_by_league[league]
            # Сортируем по ID (сначала новые)
            sorted_preds = sorted(original, key=lambda x: -(x.get('id', 0) or 0))
            keep = []
            for p in sorted_preds:
                home = p.get('home', '').lower()
                away = p.get('away', '').lower()
                p_date = str(p.get('match_date', '') or '')[:10]
                p_time = str(p.get('match_time', '') or '')[:5]
                is_dup = False
                for k in keep:
                    k_home = k.get('home', '').lower()
                    k_away = k.get('away', '').lower()
                    k_date = str(k.get('match_date', '') or '')[:10]
                    k_time = str(k.get('match_time', '') or '')[:5]
                    if p_date != k_date or p_time != k_time:
                        continue
                    # Сравниваем имена отдельно с транслитерацией
                    def _cmp(a, b):
                        return _name_sim(_translit(a), _translit(b))
                    sim_hh = _cmp(home, k_home)
                    sim_aa = _cmp(away, k_away)
                    sim_ha = _cmp(home, k_away)
                    sim_ah = _cmp(away, k_home)
                    if (sim_hh > 0.55 and sim_aa > 0.55) or (sim_ha > 0.55 and sim_ah > 0.55):
                        is_dup = True
                        break
                if not is_dup:
                    keep.append(p)
            removed = len(original) - len(keep)
            if removed:
                print(f'  🎾 {league}: убрано {removed} дублей')
            preds_by_league[league] = keep

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
            'dateStr': i.get('dateStr', ''),
            'text': i['text'],
            'hLogo': i['hLogo'],
            'aLogo': i['aLogo'],
            'winLabel': i['winLabel'],
            'totalLabel': i['totalLabel'],
            'oddsHome': i.get('oddsHome', ''),
            'oddsDraw': i.get('oddsDraw', ''),
            'oddsAway': i.get('oddsAway', ''),
            '_idx': i['_idx'],
        } for i in items]

    pred_json_escaped = json.dumps(js_data, ensure_ascii=False)

    html = site_common.page_header('Прогнозы', 'predictions', now_str)
    html += '<div class="section-title">📈 Активные прогнозы</div>'

    if not preds_by_league:
        html += '<p style="color:#666;font-size:14px">Нет активных прогнозов.</p>'
    else:
        html += '<div class="pw-grid">'
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
