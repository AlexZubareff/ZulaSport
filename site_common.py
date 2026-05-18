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
}

LOGO_LEAGUES = set(LEAGUE_LOGOS.keys())

EMOJI_MAP = {'football': '⚽', 'hockey': '🏒', 'basketball': '🏀', 'tennis': '🎾'}


# ─── Хелперы ────────────────────────────────────────────────────────


def escape(s):
    if s is None:
        return ''
    return html_mod.escape(str(s))


def _normalize(name):
    import unicodedata
    nfkd = unicodedata.normalize('NFKD', name)
    return nfkd.encode('ASCII', 'ignore').decode().lower().strip()


def _team_logo(team_name):
    if not team_name:
        return ''
    norm = _normalize(team_name)
    for key, info in _TEAM_LOGOS.items():
        if _normalize(key) == norm:
            return info.get('src', '') if isinstance(info, dict) else info
    return ''


def league_logo_html(league):
    url = LEAGUE_LOGOS.get(league)
    if url:
        return f'<img class="league-logo" src="{url}" alt="" loading="lazy">'
    emoji = EMOJI_MAP.get('football', '⚽')
    return emoji


def section_header(league, sport='football'):
    """Собрать section-sub с логотипом лиги."""
    logo_html = league_logo_html(league)
    return f'<div class="section-sub">{logo_html} {escape(league)}</div>'


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
.up-v1-grid { display: flex; gap: 14px; }
.up-v1-left { flex: 1; min-width: 0; }
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
    .card-grid .up-card,
    .card-grid .result-card { margin-bottom: 0; }
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
.result-card {
    background: linear-gradient(135deg, #1a3a1a, #1a1a1a);
    border: 1px solid #2a4a2a;
    border-radius: 12px;
    padding: 10px 14px;
    margin-bottom: 8px;
}
.rc-row {
    display: flex; align-items: center; justify-content: space-between;
    padding: 4px 0;
}
.rc-row-away { border-top: 1px solid #2a4a2a; margin-top: 4px; padding-top: 8px; }
.rc-left { display: flex; align-items: center; gap: 6px; }
.rc-name { font-size: 14px; font-weight: 600; color: #fff; }
.rc-sc { font-size: 18px; font-weight: 800; color: #00e676; font-variant-numeric: tabular-nums; }
.rl-logo { width: 20px; height: 20px; object-fit: contain; flex-shrink: 0; }
.rc-games {
    font-size: 14px; color: #fff; font-weight: 500;
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
.p-btn {{
    display: block; width: 100%;
    margin: 4px 0 2px;
    padding: 8px;
    background: rgba(0,230,118,0.1);
    border: 1px solid rgba(0,230,118,0.3);
    border-radius: 6px;
    color: #00e676;
    font-size: 11px; font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    cursor: pointer;
}}
.p-btn:hover {{
    background: rgba(0,230,118,0.2);
}}

.p-txt {{
    margin-bottom: 14px;
    padding: 12px;
    background: #0f1a2a;
    border: 1px solid #2a3a4a;
    border-radius: 8px;
    font-size: 13px;
    line-height: 1.7;
    color: #aaa;
}}

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

    .result-card { padding: 8px 10px; }
    .rc-sc { font-size: 16px; }
    .rc-name { font-size: 16px; }

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
'''

# ═══════════════════════════════════════════════════════════════════
# HTML-компоненты
# ═══════════════════════════════════════════════════════════════════


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
<style>{CSS}</style>
</head>
<body>
<div class="container">

    <div class="header">
        <div>
            <h1>🌀 Zula <span>Спорт</span></h1>
            <div class="update">Обновлено: {escape(now_str)} МСК</div>
        </div>
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
    return f'''
<script id="news-data" type="application/json">{news_json_escaped}</script>
<script id="pred-data" type="application/json">{pred_json_escaped}</script>
<script>
// ─── Article Modal ────────────────────────────────────────────────
const ARTICLE_DATA = (function() {{
    try {{ return JSON.parse(document.getElementById('news-data').textContent); }} catch(e) {{ return []; }}
}})();

function escapeHtml(str) {{
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}}

function openArticle(idx) {{
    const article = ARTICLE_DATA[idx];
    if (!article) return;

    let bodyHtml = '';
    if (article.content_ru) {{
        const paragraphs = article.content_ru.split('\\\\n').filter(function(p) {{ return p.trim(); }});
        bodyHtml = paragraphs.map(function(p) {{ return '<p>' + escapeHtml(p.trim()) + '</p>'; }}).join('');
        bodyHtml += '<p style="color:#555;font-size:12px;margin-top:16px;border-top:1px solid #2a2a2a;padding-top:12px">🌐 Перевод с оригинала</p>';
    }} else if (article.content) {{
        bodyHtml = article.content;
    }} else {{
        bodyHtml = '<p>' + escapeHtml(article.desc) + '</p>';
        if (article.desc && article.desc.length < 100) {{
            bodyHtml += '<p style="color:#666;margin-top:12px;font-size:13px">⚠️ Полный текст временно недоступен</p>';
        }}
    }}

    document.getElementById('modal-source').textContent = article.source;
    document.getElementById('modal-time').textContent = article.time;
    document.getElementById('modal-body').innerHTML = bodyHtml;
    document.getElementById('modal-body').querySelectorAll('img').forEach(function(img) {{
        img.onerror = function() {{ this.style.display = 'none'; }};
    }});
    document.getElementById('modal-source-link').href = article.link;
    document.getElementById('article-modal').classList.add('active');
    document.body.style.overflow = 'hidden';
}}

function closeArticle() {{
    document.getElementById('article-modal').classList.remove('active');
    document.body.style.overflow = '';
}}

document.getElementById('article-modal').addEventListener('click', function(e) {{
    if (e.target === this) closeArticle();
}});
document.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') closeArticle();
}});

// ─── Prediction Modal ────────────────────────────────────────────
const PRED_DATA = (function() {{
    try {{ return JSON.parse(document.getElementById('pred-data').textContent); }} catch(e) {{ return {{}}; }}
}})();

function openPrediction(league, home, away) {{
    const key = league + '||' + home + '||' + away;
    const pred = PRED_DATA[key];
    if (!pred) return;

    document.getElementById('pred-league').innerHTML = (new Map([['АПЛ','🇬🇧'],['Ла Лига','🇪🇸'],['Серия А','🇮🇹'],['Бундеслига','🇩🇪'],['Лига 1','🇫🇷'],['РПЛ','🇷🇺']]).get(pred.league) || '⚽') + ' ' + pred.league;
    document.getElementById('pred-teams').innerHTML = '<div>' + (pred.home_logo ? '<img src="' + pred.home_logo + '" style="width:18px;height:18px;vertical-align:middle;margin-right:6px">' : '') + '<span style="vertical-align:middle;font-size:16px;color:#fff">' + pred.home + '</span></div><div style="margin-top:2px">' + (pred.away_logo ? '<img src="' + pred.away_logo + '" style="width:18px;height:18px;vertical-align:middle;margin-right:6px">' : '') + '<span style="vertical-align:middle;font-size:16px;color:#ccc">' + pred.away + '</span></div><div style="font-size:11px;color:#888;margin-top:6px">' + (pred.time || '') + '</div>';

    let h = renderPrediction(pred);
    document.getElementById('pred-body').innerHTML = h;
    document.getElementById('pred-modal').classList.add('active');
    document.body.style.overflow = 'hidden';
}}

function renderPrediction(pred) {{
    let h = '';
    h += '<div style="background:linear-gradient(135deg,#1e3a1e,#2a5a2a);border-radius:12px;padding:16px;text-align:center;margin-bottom:16px">';
    h += '<div style="font-size:20px;font-weight:700;color:#00e676">' + escapeHtml(pred.home) + ' — ' + escapeHtml(pred.away) + '</div>';
    if (pred.glicko) {{
        h += '<div style="margin-top:10px;display:flex;gap:6px;font-size:12px">';
        h += '<div style="flex:1;background:rgba(0,0,0,0.3);border-radius:6px;padding:6px;color:#aaa"><div>' + escapeHtml(pred.home) + '</div><div style="font-size:16px;font-weight:700;color:#fff">' + Math.round(pred.glicko.home_prob * 100) + '%</div></div>';
        h += '<div style="flex:1;background:rgba(0,0,0,0.3);border-radius:6px;padding:6px;color:#aaa"><div>Ничья</div><div style="font-size:16px;font-weight:700;color:#ffd700">' + Math.round(pred.glicko.draw_prob * 100) + '%</div></div>';
        h += '<div style="flex:1;background:rgba(0,0,0,0.3);border-radius:6px;padding:6px;color:#aaa"><div>' + escapeHtml(pred.away) + '</div><div style="font-size:16px;font-weight:700;color:#fff">' + Math.round(pred.glicko.away_prob * 100) + '%</div></div>';
        h += '</div>';
    }}
    h += '</div>';

    if (pred.glicko) {{
        let hr = Math.round(pred.glicko.home_rating || 0);
        let ar = Math.round(pred.glicko.away_rating || 0);
        let hx = pred.glicko.home_xg ? pred.glicko.home_xg.toFixed(2) : '';
        let ax = pred.glicko.away_xg ? pred.glicko.away_xg.toFixed(2) : '';
        if (hr || ar) {{
            h += '<div style="margin:0 0 10px;display:flex;align-items:center">';
            h += '<div style="flex:1;text-align:left;padding:0 12px"><div style="font-size:11px;color:#888">' + escapeHtml(pred.home) + '</div><div style="font-size:18px;font-weight:700;color:#fff">' + hr + '</div></div>';
            h += '<div style="text-align:center;line-height:1.2"><div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px">Рейтинг</div><div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px">Glicko</div></div>';
            h += '<div style="flex:1;text-align:right;padding:0 12px"><div style="font-size:11px;color:#888">' + escapeHtml(pred.away) + '</div><div style="font-size:18px;font-weight:700;color:#fff">' + ar + '</div></div>';
            h += '</div>';
        }}
        if (hx || ax) {{
            h += '<div style="margin:0 0 10px;display:flex;align-items:center">';
            h += '<div style="flex:1;text-align:left;padding:0 12px"><div style="font-size:11px;color:#888">' + escapeHtml(pred.home) + '</div><div style="font-size:18px;font-weight:700;color:#00e676">' + hx + '</div></div>';
            h += '<div style="text-align:center;line-height:1.2"><div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px">Ожидаемые</div><div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px">голы (xG)</div></div>';
            h += '<div style="flex:1;text-align:right;padding:0 12px"><div style="font-size:11px;color:#888">' + escapeHtml(pred.away) + '</div><div style="font-size:18px;font-weight:700;color:#00e676">' + ax + '</div></div>';
            h += '</div>';
        }}
    }}

    let odds = pred.odds || {{}};
    let totals = pred.totals || {{}};
    if (odds.home || odds.draw || odds.away || totals.over || totals.under) {{
        h += '<div style="margin-bottom:14px;display:flex;gap:8px;flex-wrap:wrap;justify-content:center">';
        if (odds.home) h += '<div style="background:#1a1a1a;border:1px solid #2a2a2a;border-radius:8px;padding:6px 12px;text-align:center;min-width:60px"><div style="font-size:10px;color:#888;text-transform:uppercase">П1</div><div style="font-size:15px;font-weight:700;color:#fff">' + odds.home + '</div></div>';
        if (odds.draw) h += '<div style="background:#1a1a1a;border:1px solid #2a2a2a;border-radius:8px;padding:6px 12px;text-align:center;min-width:60px"><div style="font-size:10px;color:#888;text-transform:uppercase">X</div><div style="font-size:15px;font-weight:700;color:#ffd700">' + odds.draw + '</div></div>';
        if (odds.away) h += '<div style="background:#1a1a1a;border:1px solid #2a2a2a;border-radius:8px;padding:6px 12px;text-align:center;min-width:60px"><div style="font-size:10px;color:#888;text-transform:uppercase">П2</div><div style="font-size:15px;font-weight:700;color:#fff">' + odds.away + '</div></div>';
        if (totals.over) h += '<div style="background:#1a1a1a;border:1px solid #2a2a2a;border-radius:8px;padding:6px 12px;text-align:center;min-width:60px"><div style="font-size:10px;color:#888;text-transform:uppercase">ТБ ' + (totals.total_line || 2.5) + '</div><div style="font-size:15px;font-weight:700;color:#00e676">' + totals.over + '</div></div>';
        if (totals.under) h += '<div style="background:#1a1a1a;border:1px solid #2a2a2a;border-radius:8px;padding:6px 12px;text-align:center;min-width:60px"><div style="font-size:10px;color:#888;text-transform:uppercase">ТМ ' + (totals.total_line || 2.5) + '</div><div style="font-size:15px;font-weight:700;color:#ff9800">' + totals.under + '</div></div>';
        h += '</div>';
    }}

    if (pred.prediction_text) {{
        h += '<div style="background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px;padding:14px;font-size:14px;line-height:1.7;color:#ccc">' + pred.prediction_text + '</div>';
    }}
    return h;
}}

function closePrediction() {{
    document.getElementById('pred-modal').classList.remove('active');
    document.body.style.overflow = '';
}}
document.getElementById('pred-modal').addEventListener('click', function(e) {{
    if (e.target === this) closePrediction();
}});

// ─── Stats Modal ──────────────────────────────────────────────────
function closeStats() {{
    document.getElementById('stats-modal').classList.remove('active');
    document.body.style.overflow = '';
}}
</script>'''
