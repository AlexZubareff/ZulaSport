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
                       data_key=''):
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
        card_class += ' finished-card up-v1-finished'
        parts = score.split(':')
        h_score = parts[0].strip() if len(parts) >= 1 else ''
        a_score = parts[1].strip() if len(parts) >= 2 else ''
        
        right_extra = ''
        if pred_result == 'correct':
            right_extra = '<span class="pred-result pred-correct">✓</span>'
        elif pred_result == 'incorrect':
            right_extra = '<span class="pred-result pred-incorrect">✗</span>'
        
        return f'''
<div class="{card_class}" {data_attr}>
    <div class="up-v1-grid">
        <div class="up-v1-left">
            <div class="up-v1-row">
                <span class="up-v1-team-row">{h_logo}<span class="up-v1-name">{escape(home)}</span></span>
                <span class="up-v1-team-score">{escape(h_score)}</span>
            </div>
            <div class="up-v1-row up-v1-row-away">
                <span class="up-v1-team-row">{a_logo}<span class="up-v1-name">{escape(away)}</span></span>
                <span class="up-v1-team-score">{escape(a_score)}</span>
            </div>
        </div>
        <div class="up-v1-right">{right_extra}</div>
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


# ═══════════════════════════════════════════════════════════════════
# CSS
# ═══════════════════════════════════════════════════════════════════

CSS = '''
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0f0f0f;
    color: #e0e0e0;
    line-height: 1.5;
}
a { color: inherit; text-decoration: none; }
.container { max-width: 800px; margin: 0 auto; padding: 16px; }

/* Header */
.header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 20px 0 16px; border-bottom: 1px solid #2a2a2a; margin-bottom: 24px;
}
.header h1 { font-size: 24px; font-weight: 700; color: #00e676; }
.header h1 span { color: #e0e0e0; }
.header .update { font-size: 13px; color: #888; }
.nav { display: flex; gap: 16px; padding: 12px 0; flex-wrap: wrap; }
.nav a {
    color: #888; font-size: 14px; padding: 4px 0;
    border-bottom: 2px solid transparent; transition: 0.2s;
}
.nav a:hover, .nav a.active { color: #00e676; border-color: #00e676; }

/* News */
.news-card {
    display: block; margin-bottom: 12px;
    background: #1a1a1a; border-radius: 10px;
    border: 1px solid #2a2a2a; transition: 0.2s;
}
.news-card:hover { border-color: #00e676; background: #1e1e1e; }
.news-row {
    display: flex; gap: 14px; padding: 14px;
}
.news-img {
    flex-shrink: 0; width: 120px; height: 80px;
    border-radius: 8px; overflow: hidden;
}
.news-row.no-img .news-img { display: none; }
.news-row.no-img { gap: 0; }
.news-img img { width: 100%; height: 100%; object-fit: cover; }

.news-body { flex: 1; min-width: 0; }
.news-meta { display: flex; justify-content: space-between; font-size: 12px; color: #888; margin-bottom: 6px; }
.news-source { color: #00e676; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; font-size: 11px; }
.news-time { color: #666; }
.news-title { font-size: 16px; font-weight: 600; margin-bottom: 4px; color: #fff; }
.news-desc { font-size: 14px; color: #999; }

/* Sections */
.section-title {
    font-size: 18px; font-weight: 700; margin: 24px 0 12px;
    padding-bottom: 8px; border-bottom: 1px solid #2a2a2a;
}
.section-sub {
    font-size: 15px; font-weight: 600; margin: 16px 0 8px; color: #aaa;
    display: flex; align-items: center; gap: 6px;
}
.league-logo {
    width: 18px; height: 18px; object-fit: contain;
    flex-shrink: 0;
}

/* Tables */
.compact-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.compact-table tr { border-bottom: 1px solid #1e1e1e; }
.compact-table td { padding: 8px 6px; }
.compact-table td.time { color: #888; white-space: nowrap; width: 60px; }
.compact-table td.ch { color: #00e676; white-space: nowrap; width: 100px; font-size: 12px; }

/* Match cards */
.up-card { margin-bottom: 10px; border-radius: 12px; padding: 10px 14px; }
.up-card-v1 {
    background: linear-gradient(135deg, #1a2a3a, #1a1a1a);
    border: 1px solid #2a3a4a;
}
.up-v1-grid { display: flex; gap: 14px; justify-content: space-between; }
.up-v1-left { min-width: 0; flex: 1; }

/* Finished: напротив каждой команды — её счёт */
.up-v1-finished .up-v1-left .up-v1-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.up-v1-team-score { font-size: 22px; font-weight: 800; color: #00e676; font-variant-numeric: tabular-nums; white-space: nowrap; }

.up-v1-right {
    display: flex; flex-direction: column; align-items: center;
    justify-content: center; gap: 6px; flex-shrink: 0;
}
.up-v1-row { padding: 4px 0; }
.up-v1-row-away { margin-top: 2px; padding-top: 6px; }
.up-v1-team-row { display: flex; align-items: center; gap: 6px; }
.up-v1-name { font-size: 14px; font-weight: 600; color: #fff; }
.up-v1-time {
    font-size: 22px; font-weight: 800; color: #888;
    font-variant-numeric: tabular-nums;
    text-align: center;
}
.up-v1-predict-btn {
    font-size: 11px; font-weight: 600; color: #00e676;
    background: rgba(0,230,118,0.1);
    border: 1px solid rgba(0,230,118,0.3);
    border-radius: 6px; padding: 4px 12px;
    cursor: pointer; transition: 0.2s;
    text-transform: uppercase; letter-spacing: 1px;
}
.up-v1-predict-btn:hover {
    background: rgba(0,230,118,0.2);
    border-color: #00e676;
}
.up-v1-predict-off {
    color: #555 !important;
    background: rgba(255,255,255,0.05) !important;
    border-color: #333 !important;
    cursor: default !important;
    pointer-events: none;
}
.up-v1-tv { margin-top: 6px; font-size: 12px; color: #ff9800; padding-top: 6px; border-top: 1px solid #2a3a4a; }

/* Live badge */
.up-v1-live-badge {
    font-size: 11px; font-weight: 800; color: #fff;
    background: #e53935; border-radius: 4px; padding: 2px 8px;
    text-transform: uppercase; letter-spacing: 1px;
    animation: livePulse 1.5s ease-in-out infinite;
}
@keyframes livePulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }

/* Grid: 2 колонки на десктопе */
.card-grid { display: block; }
@media (min-width: 768px) {
    .card-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 10px;
    }
    .card-grid .section-sub { grid-column: 1 / -1; margin-bottom: 4px; }
    .card-grid .up-card { margin-bottom: 0; }
}

/* Live / finished score */
.up-v1-score {
    font-size: 22px; font-weight: 800; color: #fff;
    font-variant-numeric: tabular-nums;
    text-align: center;
}
.up-v1-score.finished { color: #00e676; }

.up-v1-score-home {
    font-size: 22px; font-weight: 800; color: #00e676;
    font-variant-numeric: tabular-nums;
    text-align: center;
}
.up-v1-score-away {
    font-size: 22px; font-weight: 800; color: #00e676;
    font-variant-numeric: tabular-nums;
    text-align: center;
    margin-top: -2px;
}

/* Result card */
.rl-logo { width: 20px; height: 20px; object-fit: contain; flex-shrink: 0; }
    font-variant-numeric: tabular-nums;
    letter-spacing: 3px;
    flex: 1; text-align: right;
    margin-right: 12px;
}

/* TV guide */
.source-note { font-size: 11px; color: #555; margin-top: 8px; text-align: right; }

/* Footer */
.footer {
    margin-top: 32px; padding: 20px 0; border-top: 1px solid #2a2a2a;
    text-align: center; font-size: 13px; color: #666;
}
.footer a { color: #00e676; }
.footer .bot-link {
    display: inline-block; margin-top: 8px;
    padding: 8px 20px; background: #00e676; color: #000;
    border-radius: 20px; font-weight: 600; font-size: 14px;
}

.more-btn {
    display: block; width: 100%; padding: 12px; margin: 16px 0;
    background: #1a1a1a; border: 1px solid #333; border-radius: 10px;
    color: #00e676; font-size: 15px; font-weight: 600;
    cursor: pointer; transition: 0.2s;
}
.more-btn:hover { background: #222; border-color: #00e676; }

/* Scrollbar */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: #0f0f0f; }
::-webkit-scrollbar-thumb { background: #333; border-radius: 3px; }

/* Modal for article reading */
.modal-overlay {
    display: none; position: fixed; inset: 0; z-index: 1000;
    background: rgba(0,0,0,0.85); backdrop-filter: blur(4px);
    justify-content: center; align-items: flex-start; overflow-y: auto;
    padding: 40px 16px;
}
.modal-overlay.active { display: flex; }
.modal-card {
    background: #1a1a1a; border-radius: 14px; max-width: 720px; width: 100%;
    border: 1px solid #2a2a2a; overflow: hidden;
    animation: modalIn 0.25s ease;
}
@keyframes modalIn {
    from { opacity: 0; transform: translateY(24px); }
    to { opacity: 1; transform: translateY(0); }
}
.modal-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 16px 20px; border-bottom: 1px solid #2a2a2a;
    position: sticky; top: 0; background: #1a1a1a; z-index: 1;
}
.modal-header-left { display: flex; flex-direction: column; gap: 4px; }
.modal-close {
    width: 32px; height: 32px; border-radius: 50%; border: none;
    background: #333; color: #ccc; font-size: 18px; cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    transition: 0.2s; flex-shrink: 0;
}
.modal-close:hover { background: #555; color: #fff; }
.modal-body {
    padding: 20px; line-height: 1.75; font-size: 15px;
    color: #ccc; overflow-y: auto; max-height: 65vh;
}
.modal-body p { margin-bottom: 14px; }
.modal-body h2, .modal-body h3, .modal-body h4 { color: #fff; margin: 20px 0 10px; }
.modal-body img { max-width: 100%; height: auto; border-radius: 8px; margin: 14px 0; }
.modal-body a { color: #00e676; text-decoration: underline; }
.modal-body ul, .modal-body ol { margin: 10px 0; padding-left: 24px; }
.modal-body li { margin-bottom: 6px; }
.modal-body blockquote {
    border-left: 3px solid #00e676; padding: 8px 14px; margin: 14px 0;
    background: rgba(0,230,118,0.05); border-radius: 0 8px 8px 0;
    color: #aaa;
}
.modal-body .news-desc {
    font-size: 13px; color: #888; margin-bottom: 16px;
    padding-bottom: 16px; border-bottom: 1px solid #2a2a2a;
}
.modal-footer {
    display: flex; align-items: center; justify-content: space-between;
    padding: 12px 20px; border-top: 1px solid #2a2a2a;
}
.modal-footer a {
    color: #00e676; font-size: 13px; font-weight: 600;
    transition: 0.2s; padding: 6px 12px; border-radius: 6px;
}
.modal-footer a:hover { background: rgba(0,230,118,0.1); }

/* Stats Modal */
.stats-live {
    font-size: 10px; font-weight: 800; color: #e53935;
    text-align: center; text-transform: uppercase; letter-spacing: 1px;
    animation: pulse 1.5s ease-in-out infinite; margin-bottom: 4px;
}
.stats-header {
    display: flex; align-items: center; justify-content: center; gap: 10px;
    padding-bottom: 14px; border-bottom: 1px solid #2a3a4a; margin-bottom: 14px;
}
.stats-team { flex: 1; font-size: 15px; font-weight: 700; color: #fff; text-align: center; }
.stats-score {
    font-size: 26px; font-weight: 800; color: #fff; font-variant-numeric: tabular-nums;
    text-align: center; flex-shrink: 0; min-width: 50px;
}
.stats-table { width: 100%; border-collapse: collapse; }
.stats-table td { padding: 6px 6px; font-size: 13px; }
.stats-table .stat-home { text-align: right; font-weight: 700; color: #fff; width: 20%; }
.stats-table .stat-name { text-align: center; color: #888; width: 60%; font-size: 12px; }
.stats-table .stat-away { text-align: left; font-weight: 700; color: #fff; width: 20%; }
.stats-table tr:nth-child(even) { background: rgba(255,255,255,0.03); }
.percent-row td { padding: 8px 6px 2px !important; }
.percent-label { font-size: 11px; color: #888; text-align: center; margin-bottom: 4px; }
.percent-bars { display: flex; align-items: center; gap: 8px; justify-content: center; }
.percent-val { font-size: 12px; font-weight: 700; color: #fff; min-width: 32px; text-align: center; }
.percent-track { flex: 1; height: 6px; background: #2a3a4a; border-radius: 3px; overflow: hidden; display: flex; max-width: 180px; }
.percent-home { height: 100%; background: #00e676; }
.percent-away { height: 100%; background: #00bcd4; }

/* Predictions page */
.pred-card {
    position: relative;
}
.pred-card .p-txt {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    right: 0;
    z-index: 10;
    margin: 0 !important;
    border-radius: 10px;
}
.pred-mid {
    display: flex; align-items: center;
    font-size: 16px; font-weight: 800; color: #fff;
    white-space: nowrap; flex-shrink: 0; padding: 0 10px;
}

.p-btn {
    display: block; width: 100%;
    margin: 4px 0 2px;
    padding: 8px;
    background: rgba(0,230,118,0.1);
    border: 1px solid rgba(0,230,118,0.3);
    border-radius: 6px;
    color: #00e676;
    font-size: 11px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 1px;
    cursor: pointer;
}
.p-btn:hover { background: rgba(0,230,118,0.2); }

.p-txt {
    margin-bottom: 14px; padding: 12px;
    background: #0f1a2a; border: 1px solid #2a3a4a;
    border-radius: 8px; font-size: 13px;
    line-height: 1.7; color: #aaa;
}

/* Mobile responsive */
@media (max-width: 640px) {
    .container { padding: 10px; }
    .header { flex-direction: column; align-items: flex-start; gap: 6px; padding: 14px 0 12px; }
    .header h1 { font-size: 20px; }
    .header .update { font-size: 11px; }
    .nav { gap: 10px; padding: 8px 0; }
    .nav a { font-size: 13px; padding: 4px 2px; }
    .section-title { font-size: 16px; margin: 18px 0 10px; }
    .section-sub { font-size: 13px; margin: 12px 0 6px; }

    .up-card { padding: 8px 10px; }
    .up-v1-grid { gap: 8px; }
    .up-v1-name { font-size: 16px; }
    .up-v1-time { font-size: 16px; }
    .up-v1-score { font-size: 16px; }
    .up-v1-score-home { font-size: 16px; }
    .up-v1-score-away { font-size: 16px; }
    .up-v1-predict-btn { font-size: 10px; padding: 3px 8px; }
    .up-v1-tv { font-size: 11px; }
    .rl-logo { width: 16px; height: 16px; }

    

    .news-row { flex-direction: column; padding: 10px; }
    .news-img { width: 100%; height: 140px; }
    .news-title { font-size: 15px; }
    .news-desc { font-size: 13px; }
    .news-body { padding: 0; }

    .compact-table { font-size: 12px; }
    .compact-table td { padding: 6px 4px; }
    .compact-table td.ch { font-size: 10px; width: 70px; }

    .modal-overlay { padding: 0; align-items: flex-end; }
    .modal-card { border-radius: 14px 14px 0 0; max-width: 100%; }
    .modal-body { padding: 14px; font-size: 14px; max-height: 70vh; }
    .modal-header { padding: 12px 14px; }
    .modal-footer { padding: 10px 14px; }

    .footer { font-size: 12px; padding: 14px 0; }
}

# ═══════════════════════════════════════════════════════════════════
# HTML-компоненты
# ═══════════════════════════════════════════════════════════════════


'''

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
        href = f'/' + (key if key != 'predictions' else 'predictions') + '.html'
        nav_html += f'<a href="{href}" class="{cls}">{label}</a>'

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
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="container">

    <div class="header">
        <h1>🌀 Zula <span>Спорт</span></h1>
        <div class="update">Обновлено: {escape(now_str)} МСК</div>
    </div>

    <div class="nav">{nav_html}</div>'''


def page_footer():
    return f'''
    <div class="footer">
        <p>🌀 Zula Спорт — автоматический агрегатор новостей и расписания</p>
        <p>Данные: BBC, Sky Sports, Guardian, Чемпионат, Sports.ru, Матч ТВ</p>
        <a href="https://t.me/ZulaSportNews_bot" class="bot-link" target="_blank">📱 Бот в Telegram</a>
    </div>

</div>

<!-- Article Modal -->
<div id="article-modal" class="modal-overlay">
    <div class="modal-card">
        <div class="modal-header">
            <div class="modal-header-left">
                <span id="modal-source" class="news-source" style="text-transform:uppercase;letter-spacing:0.5px;font-size:11px"></span>
                <span id="modal-time" class="news-time" style="font-size:12px"></span>
            </div>
            <button class="modal-close" onclick="closeArticle()">✕</button>
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
            <button class="modal-close" onclick="closePrediction()">✕</button>
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
            <button class="modal-close" onclick="closeStats()">✕</button>
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
