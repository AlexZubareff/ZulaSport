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
from name_ru import ru_name as tennis_ru_name

try:
    import db
    _DB_OK = bool(db.get_stats() is not None)
except:
    _DB_OK = False

MOW = timedelta(hours=3)


def _parse_tennis_sets(score):
    """Парсит теннисный счёт '6-4 6-4 6-4' в список [(h1,a1), (h2,a2), ...]."""
    if not score or '-' not in score:
        return None
    sets = []
    for part in score.split():
        if '-' in part:
            parts = part.split('-')
            if len(parts) >= 2:
                sets.append((parts[0].strip(), parts[1].strip()))
    return sets if sets else None


def _result_card(m, preds_lookup):
    """Карточка результата матча."""
    league = m.get('league', '')
    home = m.get('home', '')
    away = m.get('away', '')
    score = m.get('score', '')
    is_tennis = league in ('ATP', 'WTA', 'Roland Garros')
    if is_tennis:
        home = tennis_ru_name(home) or home
        away = tennis_ru_name(away) or away

    home_logo = _team_logo(home, league)
    away_logo = _team_logo(away, league)
    
    pred = preds_lookup.get((league, home, away))
    if not pred and is_tennis:
        orig_home = m.get('home', '')
        orig_away = m.get('away', '')
        pred = preds_lookup.get((league, orig_home, orig_away))
    pred_result = None
    if pred:
        rw = pred.get('result_win')
        rt = pred.get('result_total')
        if rw == 'correct' or rt == 'correct':
            pred_result = 'correct'
        elif rw == 'incorrect' or rt == 'incorrect':
            pred_result = 'incorrect'

    tennis_sets = _parse_tennis_sets(score) if is_tennis else None

    return render_match_card(
        home=home, away=away, league=league,
        status='finished',
        score=score,
        home_logo=home_logo,
        away_logo=away_logo,
        pred_result=pred_result,
        tennis_sets=tennis_sets,
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
            finished_matches = db.execute(
                "SELECT * FROM matches WHERE status='finished' AND match_date >= %s ORDER BY match_date DESC, match_time",
                [yesterday]
            )
            for m in finished_matches:
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

    # Собираем уникальные даты
    all_dates = sorted(matches_by_date.keys(), reverse=True)
    # Лиги — из ВСЕХ завершённых матчей в БД (чтобы кнопки не пропадали)
    all_leagues = []
    if _DB_OK:
        try:
            league_rows = db.execute("""
                SELECT DISTINCT league FROM (
                    SELECT league FROM matches WHERE status='finished'
                    UNION
                    SELECT DISTINCT league FROM predictions WHERE status IN ('upcoming','finished')
                ) l ORDER BY league
            """)
            all_leagues = [r['league'] for r in league_rows]
        except:
            pass
    if not all_leagues:
        all_leagues = sorted(set(m['league'] for date_matches in matches_by_date.values() for m in date_matches))

    html = site_common.page_header('Результаты', 'results', now_str)
    html += '<div class="section-title">📊 Результаты</div>'

    # Группировка лиг по видам спорта
    SPORT_CATEGORIES = {
        'sport_football': {'emoji': '⚽', 'name': 'Футбол',
            'leagues': ['АПЛ','Ла Лига','Серия А','Бундеслига','Лига 1','РПЛ','Лига Чемпионов','Лига Европы','Лига Конференций']},
        'sport_hockey': {'emoji': '🏒', 'name': 'Хоккей',
            'leagues': ['НХЛ','КХЛ','ЧМ по хоккею']},
        'sport_basketball': {'emoji': '🏀', 'name': 'Баскетбол',
            'leagues': ['NBA','Лига ВТБ','Euroleague']},
        'sport_tennis': {'emoji': '🎾', 'name': 'Теннис',
            'leagues': ['ATP','WTA']},
    }
    # Определяем спорт по названию лиги (для неизвестных)
    def _sport_for_league(name):
        # Case-insensitive: пробуем найти в predefined по lowercase
        nl = name.lower()
        for cat_id, cat in SPORT_CATEGORIES.items():
            if nl in [l.lower() for l in cat['leagues']]:
                return cat_id
        kw_football = ['англия','испания','италия','германия','франция','россия','премьер','чемпион','европ']
        kw_hockey = ['нхл','кхл','хоккей']
        kw_basketball = ['nba','втб','баскет','euroleague','еврол']
        kw_tennis = ['atp','wta','теннис','roland','garros','open','wimbledon','grand slam','1000','masters','cup']
        nl = name.lower()
        if any(k in nl for k in kw_tennis): return 'sport_tennis'
        if any(k in nl for k in kw_football): return 'sport_football'
        if any(k in nl for k in kw_hockey): return 'sport_hockey'
        if any(k in nl for k in kw_basketball): return 'sport_basketball'
        return None

    # Распределяем лиги по спортам (известные + определённые по ключевым словам)
    assigned = {}
    for cat_id, cat in SPORT_CATEGORIES.items():
        for l in cat['leagues']:
            assigned[l] = cat_id
    for l in all_leagues:
        if l not in assigned:
            sport = _sport_for_league(l)
            if sport:
                SPORT_CATEGORIES[sport]['leagues'].append(l)
                assigned[l] = sport

    # Неизвестные — в Другое
    other = [l for l in all_leagues if l not in assigned]
    if other:
        SPORT_CATEGORIES['sport_other'] = {'emoji': '⚽', 'name': 'Другое', 'leagues': other}

    # Эмодзи для лиг
    LEAGUE_EMOJI = {
        'NBA':'🏀','НХЛ':'🏒','АПЛ':'🏴󠁧󠁢󠁥󠁮󠁧󠁿','КХЛ':'🏒','Лига ВТБ':'🏀','Euroleague':'🏀',
        'ЧМ по хоккею':'🏒','Ла Лига':'🇪🇸','Серия А':'🇮🇹','Бундеслига':'🇩🇪',
        'Лига Европы':'🏆','Лига Конференций':'🏆','Лига 1':'🇫🇷','РПЛ':'🇷🇺',
        'ATP':'🎾','WTA':'🎾','Roland Garros':'🎾',
    }
    for l in other:
        LEAGUE_EMOJI.setdefault(l, '🎾' if any(kw in l.lower() for kw in ['roland','garros','us open','wimbledon','australian','french','grand slam','tennis']) else '⚽')

    # Фильтры: кнопки спорта + турниры
    html += '<div class="result-filters">'
    html += '<button class="filter-btn filter-sport active" data-sport="all" onclick="filterBySport(\'all\')">🏆 Все</button>'
    for cat_id, cat in SPORT_CATEGORIES.items():
        # Проверяем, есть ли у этого спорта лиги с данными
        cat_leagues = [l for l in cat['leagues'] if l in all_leagues]
        if not cat_leagues:
            continue
        html += f'<button class="filter-btn filter-sport" data-sport="{cat_id}" onclick="filterBySport(\'{cat_id}\')">{cat["emoji"]} {cat["name"]}</button>'
    html += '</div>'

    # Турниры, сгруппированные по спортам (скрыты по умолчанию)
    html += '<div class="league-filters">'
    for cat_id, cat in SPORT_CATEGORIES.items():
        cat_leagues = [l for l in cat['leagues'] if l in all_leagues]
        if not cat_leagues:
            continue
        html += f'<div class="league-group" id="lg-{cat_id}" style="display:none;margin-bottom:8px">'
        for league in cat_leagues:
            e = LEAGUE_EMOJI.get(league, '⚽')
            html += f'<button class="filter-btn filter-league" data-filter="{escape(league)}" onclick="filterResults(\'{escape(league)}\')">{e} {escape(league)}</button>'
        html += '</div>'
    html += '</div>'

    # Даты с результатами для подсветки в календаре
    available_dates = []
    for date_key in all_dates:
        try:
            dt = date_key if isinstance(date_key, datetime) else datetime.strptime(str(date_key), '%Y-%m-%d')
            display_date = dt.strftime('%d.%m.%Y')
        except:
            display_date = date_key
        available_dates.append({'key': date_key, 'display': display_date})
    available_json = json.dumps(available_dates, ensure_ascii=False)

    html += '<div class="result-date-picker" style="margin-bottom:14px;position:relative">'
    html += '<button class="filter-btn active" id="cal-toggle" onclick="toggleCalendar()">📅 Дата</button>'
    html += f'<div id="cal-container" style="display:none;position:absolute;top:100%;left:0;z-index:100;margin-top:4px" class="cal-dropdown"></div>'
    html += '</div>'
    html += f'<script>var _AVAILABLE_DATES = {available_json};</script>'

    html += '<div id="no-results-msg" style="display:none;text-align:center;padding:40px 16px;color:#666;font-size:15px">😕 За последние 7 дней событий не было</div>'

    # JS фильтрации + календарь
    html += '''<script>
var _activeLeague = 'all';
var _activeDate = 'all';
var _MONTHS = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
var _DAYS = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];

function _daysAgo(n) {
    var d = new Date();
    d.setDate(d.getDate() - n);
    var m = d.getMonth() + 1;
    var dd = d.getDate();
    return d.getFullYear() + '-' + (m < 10 ? '0' : '') + m + '-' + (dd < 10 ? '0' : '') + dd;
}

function _isRecent1(dateStr) {
    return dateStr >= _daysAgo(1);
}

function _getAvailableDates(league) {
    var dates = {};
    document.querySelectorAll('.result-date-block').forEach(function(block) {
        var blockDate = block.getAttribute('data-date');
        var hasMatch = false;
        block.querySelectorAll('.result-card-item').forEach(function(c) {
            if (league === 'all' || c.getAttribute('data-league') === league) {
                hasMatch = true;
            }
        });
        if (hasMatch) dates[blockDate] = true;
    });
    return dates;
}

// Флаг: перерендерить календарь при следующем открытии
var _calNeedsRender = true;

function toggleCalendar() {
    var c = document.getElementById('cal-container');
    if (c.style.display === 'none' || c.style.display === '') {
        c.style.display = 'block';
        if (_calNeedsRender) {
            _renderCalendar();
            _calNeedsRender = false;
        }
        window._calJustOpened = true;
        setTimeout(function() { window._calJustOpened = false; }, 100);
    } else {
        c.style.display = 'none';
    }
}

// Поддержка touch на мобильных: вызываем toggle при touchend, отменяем click
var _calToggleEl = document.getElementById('cal-toggle');
if (_calToggleEl) {
    _calToggleEl.addEventListener('touchend', function(e) {
        e.preventDefault();
        toggleCalendar();
    });
}

// Закрыть календарь при клике вне его (с задержкой для мобильных)
document.addEventListener('click', function(e) {
    if (window._calJustOpened) return;
    var c = document.getElementById('cal-container');
    if (!c || c.style.display === 'none') return;
    var picker = document.querySelector('.result-date-picker');
    if (picker && !picker.contains(e.target)) {
        c.style.display = 'none';
    }
});

function _renderCalendar() {
    var c = document.getElementById('cal-container');
    if (!c) return;
    _calNeedsRender = false;
    var now = new Date();
    var year = now.getFullYear();
    var month = now.getMonth();
    
    var first = new Date(year, month, 1);
    var last = new Date(year, month + 1, 0);
    
    // Пн=0, Вс=6 — flashscore формат
    var startDow = (first.getDay() + 6) % 7;
    var daysInMonth = last.getDate();
    
    var avail = _getAvailableDates(_activeLeague);
    
    // Очистить перед перерисовкой
    while (c.firstChild) c.removeChild(c.firstChild);
    
    var title = document.createElement('div');
    title.className = 'cal-month';
    title.textContent = _MONTHS[month] + ' ' + year;
    c.appendChild(title);
    
    var grid = document.createElement('div');
    grid.className = 'cal-grid';
    
    for (var i = 0; i < 7; i++) {
        var dow = document.createElement('div');
        dow.className = 'cal-dow';
        dow.textContent = _DAYS[i];
        grid.appendChild(dow);
    }
    
    for (var i = 0; i < startDow; i++) {
        grid.appendChild(document.createElement('div')).className = 'cal-day cal-empty';
    }
    
    for (var d = 1; d <= daysInMonth; d++) {
        var ds = year + '-' + (month < 9 ? '0' : '') + (month + 1) + '-' + (d < 10 ? '0' : '') + d;
        var dayEl = document.createElement('div');
        dayEl.className = 'cal-day';
        if (avail[ds]) dayEl.classList.add('cal-hasdata');
        if (ds === _daysAgo(0)) dayEl.classList.add('cal-today');
        dayEl.setAttribute('data-cdate', ds);
        if (avail[ds]) {
            dayEl.addEventListener('click', function(dateStr) {
                return function() { filterByDate(dateStr); };
            }(ds));
        }
        dayEl.textContent = d;
        grid.appendChild(dayEl);
    }
    
    c.appendChild(grid);
    
    // Кнопка "Все даты" внутри календаря
    var allBtn = document.createElement('div');
    allBtn.style.cssText = 'text-align:center;margin-top:8px';
    var allLink = document.createElement('button');
    allLink.className = 'filter-btn active';
    allLink.setAttribute('data-date', 'all');
    allLink.textContent = '📅 Все даты';
    allLink.onclick = function() { filterByDate('all'); };
    allBtn.appendChild(allLink);
    c.appendChild(allBtn);
    
    _updateCalHighlight();
}

function _updateCalHighlight() {
    document.querySelectorAll('.cal-day').forEach(function(el) {
        var cd = el.getAttribute('data-cdate');
        el.classList.toggle('cal-selected', cd === _activeDate);
    });
    document.querySelectorAll('.result-date-picker .filter-btn').forEach(function(b) {
        b.classList.toggle('active', b.getAttribute('data-date') === _activeDate);
    });
}

function applyFilters() {
    document.querySelectorAll('.result-date-block').forEach(function(block) {
        var blockDate = block.getAttribute('data-date');
        
        var dateMatch;
        if (_activeDate === 'all') {
            dateMatch = _isRecent1(blockDate);
        } else {
            dateMatch = blockDate === _activeDate;
        }
        
        // Сначала фильтруем карточки
        block.querySelectorAll('.result-card-item').forEach(function(c) {
            var leagueMatch = _activeLeague === 'all' || c.getAttribute('data-league') === _activeLeague;
            c.style.display = (dateMatch && leagueMatch) ? '' : 'none';
        });
        
        // Прячем/показываем группы турниров по видимости их карточек
        block.querySelectorAll('.league-group-matches').forEach(function(g) {
            var hasVisible = g.querySelectorAll('.result-card-item:not([style*="display: none"])').length > 0;
            g.style.display = hasVisible ? '' : 'none';
            // Заголовок группы — предыдущий элемент-брат
            var header = g.previousElementSibling;
            if (header && header.classList.contains('league-section-header')) {
                header.style.display = hasVisible ? '' : 'none';
            }
        });
        
        var hasVisible = block.querySelectorAll('.result-card-item:not([style*="display: none"])').length > 0;
        block.style.display = (dateMatch && hasVisible) ? '' : 'none';
    });
    
    var totalVisible = document.querySelectorAll('.result-card-item:not([style*="display: none"])').length;
    var msg = document.getElementById('no-results-msg');
    if (msg) {
        msg.style.display = (totalVisible === 0 && _activeLeague !== 'all') ? '' : 'none';
    }
    _updateCalHighlight();
}

function filterResults(league) {
    _activeLeague = league;
    _activeDate = 'all';
    // Подсвечиваем только кнопки турниров
    document.querySelectorAll('.filter-league').forEach(function(b) {
        b.classList.toggle('active', b.getAttribute('data-filter') === league);
    });
    applyFilters();
    _calNeedsRender = true;
    var c = document.getElementById('cal-container');
    if (c) c.style.display = 'none';
}

function filterByDate(dateVal) {
    _activeDate = dateVal;
    applyFilters();
    var c = document.getElementById('cal-container');
    if (c && dateVal !== 'all') c.style.display = 'none';
}

function filterBySport(sportId) {
    document.querySelectorAll('.filter-sport').forEach(function(b) {
        b.classList.toggle('active', b.getAttribute('data-sport') === sportId);
    });
    document.querySelectorAll('.league-group').forEach(function(g) {
        g.style.display = (sportId === 'all') ? 'none' : (g.id === 'lg-' + sportId ? '' : 'none');
    });
    filterResults('all');
}

// Отложить инициализацию до загрузки DOM (дата-блоки внизу страницы)
document.addEventListener('DOMContentLoaded', function() {
    _renderCalendar();
    applyFilters();
});
</script>'''
    html += '''<style>
.result-filters{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:8px}
.filter-btn{padding:6px 14px;border:1px solid #333;border-radius:20px;background:#1a1a1a;color:#aaa;cursor:pointer;font-size:13px;transition:all .2s}
.filter-btn.active,.filter-btn:hover{background:#00e676;color:#000;border-color:#00e676;font-weight:600}
.cal-month{text-align:center;font-size:15px;font-weight:600;color:#ccc;margin-bottom:8px}
.cal-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:2px;max-width:280px}
.cal-dow{text-align:center;font-size:11px;color:#666;padding:4px 0;font-weight:600}
.cal-day{text-align:center;padding:6px 0;font-size:13px;color:#555;border-radius:6px;cursor:default}
.cal-hasdata{color:#ccc;cursor:pointer}
.cal-hasdata:hover{background:#2a2a2a}
.cal-today{color:#00e676;font-weight:700}
.cal-selected{background:#00e676;color:#000!important;font-weight:700}
.cal-empty{background:0 0}
.cal-dropdown{background:#1a1a1a;border:1px solid #333;border-radius:10px;padding:12px;box-shadow:0 4px 20px rgba(0,0,0,.5)}
.league-section-header{font-size:var(--text-sm);font-weight:600;color:#aaa;padding:8px 0 4px;margin:0 4px}
.ts-set{display:inline-block;min-width:22px;text-align:center;font-size:var(--text-sm);font-weight:600;color:#ccc;padding:0 2px;font-variant-numeric:tabular-nums;flex-shrink:0}
.ts-total{min-width:26px;font-weight:700;color:var(--accent);font-size:var(--text-sm);border-left:1px solid #444;margin-left:4px;padding-left:6px;flex-shrink:0}</style>'''

    # Эмодзи для заголовков турниров (из уже готового словаря)
    def _league_header(league):
        e = LEAGUE_EMOJI.get(league, '🏆')
        return f'<div class="league-section-header">{e} {escape(league)}</div>'

    for date_key in all_dates:
        # Формат даты
        try:
            dt = date_key if isinstance(date_key, datetime) else datetime.strptime(str(date_key), '%Y-%m-%d')
            display_date = dt.strftime('%d.%m.%Y')
        except:
            display_date = date_key

        html += f'<div class="result-date-block" data-date="{escape(date_key)}">'
        html += f'<div class="section-title">📊 {display_date}</div>'
        
        # Группируем матчи этого дня по лигам
        day_matches = matches_by_date[date_key]
        leagues_in_day = []
        for m in day_matches:
            l = m.get('league', '')
            if l not in leagues_in_day:
                leagues_in_day.append(l)
        
        for league_name in leagues_in_day:
            league_matches = [m for m in day_matches if m.get('league', '') == league_name]
            el = escape(league_name)
            html += _league_header(league_name)
            html += f'<div class="card-grid league-group-matches" data-group-league="{el}">'
            for m in league_matches:
                html += f'<div class="result-card-item" data-league="{el}">'
                html += _result_card(m, preds_lookup)
                html += '</div>'
            html += '</div>'
        
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
