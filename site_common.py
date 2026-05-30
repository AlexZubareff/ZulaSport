#!/usr/bin/env python3
"""
Общие компоненты для страниц сайта Zula Спорт.

Содержит: CSS, JS, HTML-шаблоны (header/nav/footer), общие функции.
"""

import os, json, html as html_mod
from datetime import datetime, timezone, timedelta

# ─── Константы ──────────────────────────────────────────────────────
UTC = timezone.utc
MOW = timedelta(hours=3)

# ─── Пути к данным ──────────────────────────────────────────────────
PRED_LEAGUES_PATH = '/opt/prediction_leagues.json'
TEAM_LOGOS_PATH = '/opt/team_logos.json'
NEWS_OUTPUT = '/var/www/sport/news_data.json'
LIVE_SCORES_PATH = '/tmp/live_scores_data.json'
DAILY_RESULTS_PATH = '/tmp/daily_results_data.json'
TV_CHANNELS_PATH = '/tmp/tv_channels_data.json'

# ─── Загружаем конфиги ──────────────────────────────────────────────
_PRED_LEAGUES = set()
if os.path.exists(PRED_LEAGUES_PATH):
    try:
        with open(PRED_LEAGUES_PATH) as f:
            _PRED_LEAGUES = set(json.load(f).get('active', {}).keys())
    except:
        pass

_TEAM_LOGOS = {}
if os.path.exists(TEAM_LOGOS_PATH):
    try:
        with open(TEAM_LOGOS_PATH) as f:
            _TEAM_LOGOS = json.load(f).get('teams', {})
    except:
        pass

# ─── Логотипы лиг ───────────────────────────────────────────────────
LEAGUE_LOGOS = {
    'АПЛ': '/static/leagues/апл.png',
    'Ла Лига': '/static/leagues/ла-лига.png',
    'Серия А': '/static/leagues/серия-а.png',
    'Бундеслига': '/static/leagues/бундеслига.png',
    'Лига 1': '/static/leagues/лига-1.png',
    'РПЛ': '/static/leagues/рпл.png',
    'НХЛ': '/static/leagues/нхл.png',
    'NBA': '/static/leagues/nba.png',
    'ATP': '/static/leagues/atp.png',
    'WTA': '/static/leagues/wta.png',
}

LOGO_LEAGUES = set(LEAGUE_LOGOS.keys())

EMOJI_MAP = {'football': '⚽', 'hockey': '🏒', 'basketball': '🏀', 'tennis': '🎾'}

# Маппинг лиг на эмодзи (для лиг без лого)
LEAGUE_EMOJI = {
    'ATP': '🎾',
    'WTA': '🎾',
    'АПЛ': '⚽',
    'Ла Лига': '⚽',
    'Серия А': '⚽',
    'Бундеслига': '⚽',
    'Лига 1': '⚽',
    'РПЛ': '⚽',
    'Лига Чемпионов': '⚽',
    'Лига Европы': '⚽',
    'Лига Конференций': '⚽',
    'НХЛ': '🏒',
    'NBA': '🏀',
}


# ─── Хелперы ────────────────────────────────────────────────────────


def escape(s):
    if s is None:
        return ''
    return html_mod.escape(str(s))


def _normalize(name):
    import unicodedata
    nfkd = unicodedata.normalize('NFKD', name)
    return nfkd.encode('ASCII', 'ignore').decode().lower().strip()


# ─── Флаги стран (для национальных сборных) ────────────────────────
_COUNTRY_FLAGS = {
    'Австрия': 'at', 'Азербайджан': 'az', 'Албания': 'al', 'Алжир': 'dz',
    'Англия': 'gb-eng', 'Аргентина': 'ar', 'Армения': 'am',
    'Беларусь': 'by', 'Бельгия': 'be', 'Болгария': 'bg', 'Бразилия': 'br',
    'Великобритания': 'gb', 'Венгрия': 'hu',
    'Германия': 'de', 'Греция': 'gr', 'Грузия': 'ge',
    'Дания': 'dk',
    'Египет': 'eg',
    'Израиль': 'il', 'Индия': 'in', 'Ирландия': 'ie', 'Исландия': 'is',
    'Испания': 'es', 'Италия': 'it',
    'Казахстан': 'kz', 'Камерун': 'cm', 'Канада': 'ca', 'Катар': 'qa',
    'Китай': 'cn', 'Колумбия': 'co', 'Коста-Рика': 'cr',
    'Латвия': 'lv', 'Литва': 'lt',
    'Мексика': 'mx', 'Марокко': 'ma',
    'Нигерия': 'ng', 'Нидерланды': 'nl', 'Норвегия': 'no',
    'Панама': 'pa', 'Перу': 'pe', 'Польша': 'pl', 'Португалия': 'pt',
    'Россия': 'ru', 'Румыния': 'ro',
    'Саудовская Аравия': 'sa', 'Сенегал': 'sn', 'Сербия': 'rs',
    'Словакия': 'sk', 'Словения': 'si', 'США': 'us',
    'Тунис': 'tn', 'Турция': 'tr',
    'Узбекистан': 'uz', 'Украина': 'ua', 'Уругвай': 'uy',
    'Финляндия': 'fi', 'Франция': 'fr',
    'Хорватия': 'hr',
    'Черногория': 'me', 'Чехия': 'cz',
    'Швейцария': 'ch', 'Швеция': 'se',
    'Эстония': 'ee', 'ЮАР': 'za', 'Япония': 'jp',
}

_team_logo_cache = {}
_team_logo_db = None

def _team_logo(team_name, league=None):
    """Найти лого команды: сперва кеш → флаг страны → БД (с лигой) → team_logos.json.
    
    Args:
        team_name: название команды
        league: лига (для разрешения коллизий, напр. "Локомотив" в РПЛ vs КХЛ)
    """
    global _team_logo_db
    if not team_name:
        return ''
    
    cache_key = f'{team_name}||{league or ""}'
    if cache_key in _team_logo_cache:
        return _team_logo_cache[cache_key]
    
    result = ''
    
    # 1. Флаг страны (для национальных сборных)
    iso = _COUNTRY_FLAGS.get(team_name)
    if iso:
        flag_path = f'/static/logos/flags/{iso}.png'
        if os.path.exists('/var/www/sport' + flag_path):
            result = flag_path
            _team_logo_cache[cache_key] = result
            return result
    
    # 2. БД — сперва с лигой, потом без неё
    if _team_logo_db is None:
        try:
            from db import team_resolve, execute_one
            _team_logo_db = team_resolve
            _team_logo_db2 = lambda n, l: execute_one(
                "SELECT t.* FROM teams t JOIN team_aliases a ON a.team_id = t.id "
                "WHERE a.alias = %s AND t.league = %s",
                (n.lower().strip(), l)
            ) or execute_one(
                "SELECT * FROM teams WHERE canonical_name = %s AND league = %s",
                (n.strip(), l)
            )
            _team_logo_by_league = _team_logo_db2
        except:
            _team_logo_db = False
            _team_logo_by_league = False
    
    if _team_logo_db:
        if league:
            # С лигой (точное совпадение)
            t = _team_logo_db(team_name, league)
            if t and t.get('logo_url') and t['logo_url'].startswith('/static/'):
                result = t['logo_url']
        if not result:
            # Без лиги (fallback)
            t = _team_logo_db(team_name)
            if t and t.get('logo_url') and t['logo_url'].startswith('/static/'):
                result = t['logo_url']
    
    # 3. team_logos.json (точное совпадение)
    if not result:
        info = _TEAM_LOGOS.get(team_name)
        if isinstance(info, dict):
            result = info.get('url') or info.get('src', '')
        elif isinstance(info, str):
            result = info
    
    # 4. По ru-полю
    if not result:
        for key, info in _TEAM_LOGOS.items():
            if isinstance(info, dict) and info.get('ru') == team_name:
                result = info.get('url') or info.get('src', '')
                break
    
    # 5. Нормализованное совпадение (латиница)
    if not result:
        norm = _normalize(team_name)
        if norm:
            for key, info in _TEAM_LOGOS.items():
                if _normalize(key) == norm:
                    result = info.get('url') or info.get('src', '') if isinstance(info, dict) else info
                    break
    
    _team_logo_cache[cache_key] = result
    return result


def league_logo_html(league):
    url = LEAGUE_LOGOS.get(league)
    if url:
        return f'<img class="league-logo" src="{url}" alt="" loading="lazy">'
    emoji = LEAGUE_EMOJI.get(league, '⚽')
    return emoji


def section_header(league, sport='football'):
    """Собрать section-sub с логотипом лиги."""
    logo_html = league_logo_html(league)
    return f'<div class="section-sub">{logo_html} {escape(league)}</div>'


def render_match_card(home, away, league, status, match_time='', score='',
                       home_logo='', away_logo='',
                       has_pred=False, pred_result=None,
                       data_key='', tennis_sets=None):
    """
    Единая карточка матча для всех страниц.
    Использует оригинальные CSS-классы (up-card-v1, up-v1-grid, ...).
    
    status: 'scheduled' | 'live' | 'finished'
    pred_result: 'correct' | 'incorrect' | None
    """
    h_logo = f'<img class="rl-logo" src="{home_logo}" alt="" loading="lazy" onerror="this.style.display=\'none\'">' if home_logo else ''
    a_logo = f'<img class="rl-logo" src="{away_logo}" alt="" loading="lazy" onerror="this.style.display=\'none\'">' if away_logo else ''
    
    data_attr = f' data-match-key="{escape(data_key)}"' if data_key else ''
    card_class = 'up-card up-card-v1'
    right_col = ''
    
    if status == 'finished':
        card_class += ' finished-card'
        
        if tennis_sets:
            # Теннис: сеты в каждой строке как отдельные колонки
            def _val(s):
                try: return int(s.split('(')[0])
                except: return 0
            h_total = sum(1 for hs, a in tennis_sets if _val(hs) > _val(a))
            a_total = sum(1 for hs, a in tennis_sets if _val(a) > _val(hs))
            h_sets = ''.join(f'<span class="ts-set">{escape(hs)}</span>' for hs, _ in tennis_sets)
            a_sets = ''.join(f'<span class="ts-set">{escape(a)}</span>' for _, a in tennis_sets)
            return f'''
<div class="{card_class}" {data_attr}>
    <div class="f-row">
        <div class="f-team">{h_logo}<span class="up-v1-name">{escape(home)}</span></div>
        {h_sets}<span class="ts-set ts-total">{h_total}</span>
    </div>
    <div class="f-row">
        <div class="f-team">{a_logo}<span class="up-v1-name" style="color:#ccc">{escape(away)}</span></div>
        {a_sets}<span class="ts-set ts-total">{a_total}</span>
    </div>
</div>'''
        else:
            parts = score.split(':')
            h_score = parts[0].strip() if len(parts) >= 1 else ''
            a_score = parts[1].strip() if len(parts) >= 2 else ''
            
            return f'''
<div class="{card_class}" {data_attr}>
    <div class="f-row">
        <div class="f-team">{h_logo}<span class="up-v1-name">{escape(home)}</span></div>
        <span class="f-score">{escape(h_score)}</span>
    </div>
    <div class="f-row">
        <div class="f-team">{a_logo}<span class="up-v1-name" style="color:#ccc">{escape(away)}</span></div>
        <span class="f-score">{escape(a_score)}</span>
    </div>
</div>'''
    else:  # scheduled / live

        if status == 'live':
            card_class += ' up-v1-live-card'
            right_inner = '<div class="up-v1-live-badge">LIVE</div><div class="up-v1-score">' + escape(score) + '</div>'
        else:
            right_parts = []
            if match_time:
                right_parts.append(f'<div class="up-v1-time">{escape(match_time)}</div>')
            if has_pred:
                right_parts.append(f'<div class="up-v1-predict-btn" onclick="openPrediction(\'{escape(league)}\', \'{escape(home)}\', \'{escape(away)}\')">Прогноз</div>')
            right_inner = '\n            '.join(right_parts)
        
        return f'''
<div class="{card_class}" {data_attr}>
    <div class="up-v1-grid">
        <div class="up-v1-left">
            <div class="up-v1-row">
                <span class="up-v1-team-row">{h_logo}<span class="up-v1-name">{escape(home)}</span></span>
            </div>
            <div class="up-v1-row up-v1-row-away">
                <span class="up-v1-team-row">{a_logo}<span class="up-v1-name">{escape(away)}</span></span>
            </div>
        </div>
        <div class="up-v1-right">
            {right_inner}
        </div>
    </div>
</div>'''


def format_accuracy(correct, total):
    if total == 0:
        return '—'
    pct = round(correct / total * 100, 1)
    icon = '🟢' if pct >= 60 else '🟡' if pct >= 40 else '🔴'
    return f'{icon} {correct}/{total} ({pct}%)'


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


def page_header(title, active_page, now_str):
    """Общий header + навигация."""
    nav_items = [
        ('news', 'Новости'),
        ('schedule', 'Расписание'),
        ('results', 'Результаты'),
        ('predictions', 'Прогнозы'),
    ]
    nav_html = ''
    for key, label in nav_items:
        cls = 'active' if key == active_page else ''
        aria = ' aria-current="page"' if key == active_page else ''
        href = f'/' + (key if key != 'predictions' else 'predictions') + '.html'
        nav_html += f'<a href="{href}" class="{cls}"{aria}>{label}</a>'

    return f'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="300">
<title>{escape(title)} — Zula Спорт</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/style.css?v=3">
</head>
<body>
<div class="container">

    <header class="header" role="banner">
        <h1><img class="site-logo" src="/static/logo-header.png" alt="Логотип Zula Спорт"> Zula <span>Спорт</span></h1>
        <div class="update">Обновлено: {escape(now_str)} МСК</div>
    </header>

    <nav class="nav" role="navigation" aria-label="Навигация по сайту">{nav_html}</nav>'''


def page_footer():
    return f'''
    <footer class="footer" role="contentinfo">
        <p>🌀 Zula Спорт — автоматический агрегатор новостей и расписания</p>
        <p>Данные: BBC, Sky Sports, Guardian, Чемпионат, Sports.ru, Матч ТВ</p>
        <a href="https://t.me/ZulaSportNews_bot" class="bot-link" target="_blank">📱 Бот в Telegram</a>
    </footer>

</div>

<!-- Article Modal -->
<div id="article-modal" class="modal-overlay">
    <div class="modal-card">
        <div class="modal-header">
            <div class="modal-header-left">
                <span id="modal-source" class="news-source" style="text-transform:uppercase;letter-spacing:0.5px;font-size:11px"></span>
                <span id="modal-time" class="news-time" style="font-size:12px"></span>
            </div>
            <button class="modal-close" onclick="closeArticle()" aria-label="Закрыть статью">✕</button>
        </div>
        <div id="modal-body" class="modal-body"></div>
        <div class="modal-footer">
            <span></span>
            <a id="modal-source-link" href="#" target="_blank" rel="noopener">Читать в источнике →</a>
        </div>
    </div>
</div>

<!-- Prediction Modal -->
<div id="pred-modal" class="modal-overlay">
    <div class="modal-card">
        <div class="modal-header">
            <div class="modal-header-left">
                <span id="pred-league" class="news-source" style="text-transform:uppercase;letter-spacing:0.5px;font-size:11px;color:#ffd700"></span>
                <span id="pred-teams" style="font-size:14px;font-weight:600;color:#fff"></span>
            </div>
            <button class="modal-close" onclick="closePrediction()" aria-label="Закрыть прогноз">✕</button>
        </div>
        <div id="pred-body" class="modal-body"></div>
        <div class="modal-footer">
            <span></span>
        </div>
    </div>
</div>

<!-- Stats Modal -->
<div id="stats-modal" class="modal-overlay">
    <div class="modal-card" style="max-width:480px">
        <div class="modal-header" style="border-bottom:none;padding:16px 16px 0;justify-content:flex-end">
            <button class="modal-close" onclick="closeStats()" aria-label="Закрыть статистику">✕</button>
        </div>
        <div style="padding:0 20px 20px">
            <div class="stats-live">▶ LIVE</div>
            <div class="stats-header" id="stats-header">
                <div class="stats-team" id="stats-home-team"></div>
                <div class="stats-score" id="stats-score"></div>
                <div class="stats-team" id="stats-away-team"></div>
            </div>
            <table class="stats-table" id="stats-body"></table>
        </div>
    </div>
</div>

JS_PLACEHOLDER
</body>
</html>'''


# ═══════════════════════════════════════════════════════════════════
# JS (для вставки перед </body>)
# ═══════════════════════════════════════════════════════════════════

def page_script(news_json_escaped='{}', pred_json_escaped='{}'):
    return f'''<script id="news-data" type="application/json">{news_json_escaped}</script>
<script id="pred-data" type="application/json">{pred_json_escaped}</script>
<script src="/static/app.js"></script>'''
