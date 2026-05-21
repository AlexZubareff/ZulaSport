#!/usr/bin/env python3
"""
Capper — каперский скилл. Сбор данных + прогноз.
Режимы:
  --match "Ком1" "Ком2" [league_key]  — один матч (как было)
  --batch                              — все матчи из upcoming_matches.json
  --refresh                            — обновить прогнозы для матчей <= 1ч (составы)

Сохраняет: /opt/predictions_data.json
"""

import json, sys, os, re, time as time_module
from datetime import datetime, timedelta, timezone
import random
import requests
from playwright.sync_api import sync_playwright

sys.path.insert(0, '/opt')
from capper_common import call_deepseek_with_cache, get_cache_stats
from alert import report_success, report_failure, wrap_source

# БД (если доступна)
try:
    import db
    _DB_AVAILABLE = True
except Exception:
    _DB_AVAILABLE = False

# ─── НАСТРОЙКИ ────────────────────────────────────────────────────────
SSTATS_KEY = os.environ.get('SSTATS_KEY', '')
if not SSTATS_KEY:
    try:
        with open('/etc/sstats.key') as f:
            SSTATS_KEY = f.read().strip()
    except: pass
SSTATS = 'https://api.sstats.net'

DEEPSEEK_KEY = ''
try:
    with open('/etc/deepseek.key') as f:
        DEEPSEEK_KEY = f.read().strip()
except: pass

# ID лиг в SStats
LS = {'rpl': 235, 'epl': 39, 'laliga': 140, 'seriea': 135, 'bundesliga': 78, 'ligue1': 61, 'ucl': 2, 'uel': 3, 'uecl': 848}

# Пути flashscore
FS_PATHS = {'rpl': '/football/russia/premier-league/', 'epl': '/football/england/premier-league/',
    'laliga': '/football/spain/laliga/', 'seriea': '/football/italy/serie-a/',
    'bundesliga': '/football/germany/bundesliga/', 'ligue1': '/football/france/ligue-1/',
    'ucl': '/football/europe/champions-league/', 'uel': '/football/europe/europa-league/',
    'uecl': '/football/europe/conference-league/'}

# Активные лиги для прогнозов
_PRED_LEAGUES = {}
try:
    with open('/opt/prediction_leagues.json') as f:
        _PRED_LEAGUES = json.load(f).get('active', {})
except: pass

MOW = timedelta(hours=3)
UTC = timezone.utc


# ═══════════════════ SStats API ═══════════════════

def sq(endpoint, params=None):
    p = {'apikey': SSTATS_KEY}
    if params: p.update(params)
    try:
        r = requests.get(f'{SSTATS}{endpoint}', params=p, timeout=15)
        return r.json()
    except: return None


def fetch_sstats(game_id):
    """Собрать SStats данные по game_id: кэфы, Glicko, травмы, статистику."""
    result = {'game_id': game_id}
    
    # Детали игры
    games = sq('/Games/list', {'Id': game_id})
    if not games:
        return result
    data = games.get('data', []) if isinstance(games, dict) else (games if isinstance(games, list) else [])
    game = data[0] if data else None
    if not game:
        return result
    
    result['home'] = game.get('homeTeam', {}).get('name', '?')
    result['away'] = game.get('awayTeam', {}).get('name', '?')
    result['date'] = game.get('date', '')
    result['flashId'] = game.get('flashId', '')
    
    # Коэффициенты (из Games/list — структура [{marketId, odds: [{name, value}]}])
    odds_raw = game.get('odds', [])
    if isinstance(odds_raw, dict): odds_raw = list(odds_raw.values())
    result['odds'] = []
    result['totals'] = {}
    for market in (odds_raw if isinstance(odds_raw, list) else []):
        if not isinstance(market, dict): continue
        mo = market.get('odds', [])
        if not isinstance(mo, list): continue
        vals = {}
        for o in mo:
            if isinstance(o, dict):
                n = str(o.get('name', '')).lower()
                v = o.get('value')
                if v is not None:
                    if n == 'home': vals['home'] = float(v)
                    elif n == 'away': vals['away'] = float(v)
                    elif n == 'draw': vals['draw'] = float(v)
                    elif n.startswith('over'): 
                        vals['over'] = float(v)
                        import re as _re
                        m = _re.search(r'[\d.]+', o.get('name', ''))
                        if m:
                            vals['total_line'] = float(m.group())
                        vals['type'] = 'total'
                    elif n.startswith('under'): 
                        vals['under'] = float(v)
                        vals['type'] = 'total'
        if 'type' in vals and 'over' in vals and 'under' in vals:
            tl = vals.get('total_line', 0)
            # Приоритет: 2.5 > 3.5 > 0.5 (наиболее релевантный тотал)
            current_tl = result['totals'].get('total_line', 0)
            if tl in (2.5, 3.5) or (current_tl == 0):
                result['totals']['total_line'] = tl
                result['totals']['over'] = vals['over']
                result['totals']['under'] = vals['under']
        elif len(vals) == 3 and 'home' in vals and 'away' in vals and 'draw' in vals:
            if not result['odds']:
                result['odds'].append(vals)  # берём первый полный market (1X2)
    
    # Glicko
    gl = sq('/Games/glicko/' + str(game_id))
    if isinstance(gl, dict):
        gd = gl.get('data', {})
        glicko = gd.get('glicko', {}) if isinstance(gd, dict) else gl.get('glicko', {})
        if isinstance(glicko, dict) and glicko.get('homeWinProbability'):
            result['glicko'] = {
                'home_prob': glicko['homeWinProbability'],
                'away_prob': glicko['awayWinProbability'],
                'draw_prob': max(0, 1.0 - glicko['homeWinProbability'] - glicko['awayWinProbability']),
                'home_rating': glicko.get('homeRating', 0),
                'away_rating': glicko.get('awayRating', 0),
                'home_xg': glicko.get('homeXg', 0),
                'away_xg': glicko.get('awayXg', 0),
            }
    
    # Травмы
    inj = sq('/Games/injuries', {'gameId': game_id})
    if isinstance(inj, list): result['injuries'] = inj
    elif isinstance(inj, dict) and 'data' in inj: result['injuries'] = inj['data']
    
    # Статистика команд (форма)
    stats = sq('/Games/last-games-stats', {'gameId': game_id})
    if isinstance(stats, dict): result['stats'] = stats
    
    return result


# ═══════════════════ Flashscore ═══════════════════

def fetch_lineups_flashscore(flash_id):
    """Парсит стартовые составы с Flashscore по flashId SStats."""
    url = f'https://www.flashscore.com/match/{flash_id}/#/match-summary/lineups'
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True, args=['--no-sandbox'])
            page = b.new_page(viewport={'width': 1920, 'height': 1080})
            page.set_default_timeout(20000)
            page.goto(url, wait_until='domcontentloaded', timeout=20000)
            page.wait_for_timeout(5000)
            text = page.evaluate('() => document.body.innerText')
            b.close()
    except:
        return None

    if 'LINEUPS' not in text and 'СОСТАВ' not in text and 'STARTING' not in text:
        return None

    lines = text.split('\n')
    result = {'home': [], 'away': [], 'formation_home': '', 'formation_away': '', 'bench_home': [], 'bench_away': []}
    section, side = None, None

    for i, l in enumerate(lines):
        l = l.strip()
        if l in ('LINEUPS', 'СОСТАВ', 'STARTING LINEUPS'):
            section = 'lineups'; continue
        if l in ('SUBSTITUTES', 'ЗАПАСНЫЕ', 'BENCH'):
            section = 'bench'; continue
        if l in ('HOME', 'ДОМА', 'ХОЗЯЕВА'):
            side = 'home'
            if i+1 < len(lines) and re.match(r'^\d{1,2}-\d{1,2}-\d{1,2}', lines[i+1].strip()):
                result['formation_home'] = lines[i+1].strip()
            continue
        if l in ('AWAY', 'ГОСТИ', 'В ГОСТЯХ'):
            side = 'away'
            if i+1 < len(lines) and re.match(r'^\d{1,2}-\d{1,2}-\d{1,2}', lines[i+1].strip()):
                result['formation_away'] = lines[i+1].strip()
            continue

        if not side or not l or len(l) < 2: continue
        if re.match(r'^\d{1,2}-\d{1,2}-\d{1,2}', l): continue
        if l in ('?', 'LINEUPS NOT AVAILABLE', 'СОСТАВЫ НЕ ДОСТУПНЫ', 'SUBSTITUTES',
                 'ЗАПАСНЫЕ', 'BENCH', 'HOME', 'AWAY', 'ДОМА', 'ГОСТИ'): continue

        if section == 'lineups':
            result.setdefault(side, []).append(l)
        elif section == 'bench':
            result.setdefault(f'bench_{side}', []).append(l)

    if result['home'] or result['away']:
        return result
    return None


def find_match_flashscore(team1, team2, league_key=None):
    """Поиск матча на Flashscore."""
    urls = ['https://www.flashscore.com/']
    if league_key in FS_PATHS:
        urls.insert(0, 'https://www.flashscore.com' + FS_PATHS[league_key])

    t1l, t2l = team1.lower(), team2.lower()
    p1 = [w for w in t1l.split() if len(w) > 2] or [t1l]
    p2 = [w for w in t2l.split() if len(w) > 2] or [t2l]

    for url in urls:
        try:
            with sync_playwright() as p:
                b = p.chromium.launch(headless=True, args=['--no-sandbox'])
                page = b.new_page(viewport={'width': 1920, 'height': 1080})
                page.set_default_timeout(20000)
                page.goto(url, wait_until='domcontentloaded', timeout=20000)
                page.wait_for_timeout(5000)
                page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                page.wait_for_timeout(3000)
                found = page.evaluate('''(d) => {
                    const [t1l, t2l, p1, p2] = d;
                    for (const r of document.querySelectorAll('.event__match')) {
                        const h = r.querySelector('.event__homeParticipant');
                        const a = r.querySelector('.event__awayParticipant');
                        const l = r.querySelector('a[href*="/match/"]');
                        if (!h || !a || !l) continue;
                        const hh = h.textContent.trim().toLowerCase(), aa = a.textContent.trim().toLowerCase();
                        if ((p1.every(w => hh.includes(w)) && p2.every(w => aa.includes(w))) ||
                            (p2.every(w => hh.includes(w)) && p1.every(w => aa.includes(w)))) {
                            const hr = l.getAttribute('href') || '';
                            return {team1: h.textContent.trim(), team2: a.textContent.trim(),
                                    url: hr.startsWith('http') ? hr : 'https://www.flashscore.com' + hr};
                        }
                    }
                    return null;
                }''', [t1l, t2l, p1, p2])
                b.close()
                if found: return found
        except:
            continue
    return None


def parse_match_flashscore(url):
    """Парсит Flashscore: стадион, судья, форма, H2H, таблица."""
    data = {'info': {}, 'form': {}, 'h2h': [], 'standings': []}
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True, args=['--no-sandbox'])
            page = b.new_page(viewport={'width': 1920, 'height': 1080})
            page.set_default_timeout(20000)
            page.goto(url, wait_until='domcontentloaded', timeout=20000)
            page.wait_for_timeout(6000)
            r = page.evaluate('''() => {
                const L = document.body.innerText.split('\\n');
                const info = {}, form = {}, h2h = [];
                for (let i = 0; i < L.length; i++) {
                    const l = L[i].trim();
                    if (l.startsWith('REFEREE')) info.referee = l.replace(/REFEREE[\\s:]+/, '').trim();
                    if (l.startsWith('STADIUM')) info.venue = l.replace(/STADIUM[\\s:]+/, '').trim();
                }
                let fi = L.findIndex(l => l.trim() === 'FORM');
                if (fi >= 0) {
                    let team = null, reading = false;
                    for (let i = fi + 1; i < Math.min(fi + 40, L.length); i++) {
                        const l = L[i].trim();
                        if (['TABLE', 'HEAD TO HEAD'].includes(l)) break;
                        if (/^\\d+\\.$/.test(l)) { team = null; reading = false; continue; }
                        if (l === '?') { reading = true; continue; }
                        if (!team && l.length > 2 && !/^[?.\\-\\s]+$/.test(l) && l !== 'FORM') {
                            team = l; form[team] = []; reading = false; continue;
                        }
                        if (reading && team && ['W','D','L'].includes(l)) form[team].push(l);
                        if (reading && team && !['W','D','L'].includes(l)) reading = false;
                    }
                }
                let hi = L.findIndex(l => l.trim() === 'HEAD TO HEAD');
                if (hi >= 0) {
                    for (let i = hi + 1; i < Math.min(hi + 40, L.length); i++) {
                        const l = L[i].trim();
                        if (!l || ['TABLE','FORM'].includes(l)) break;
                        if (!/^\\d{2}\\.\\d{2}\\.\\d{2,4}$/.test(l)) continue;
                        const entry = {date: l, team1: '', team2: '', score: ''};
                        const after = [];
                        for (let j = i + 1; j < Math.min(i + 8, L.length); j++) {
                            const n = L[j].trim();
                            if (!n || /^\\d{2}\\.\\d{2}\\.\\d{2,4}$/.test(n) ||
                                ['TABLE','FORM','HEAD TO HEAD'].includes(n)) break;
                            after.push(n);
                        }
                        const names = after.filter(x => x.length > 3 && !/^\\d+$/.test(x) && x !== '?' && x !== 'Show');
                        if (names.length >= 2) { entry.team1 = names[0]; entry.team2 = names[1]; }
                        const nums = after.filter(x => /^\\d{1,2}$/.test(x) && parseInt(x) <= 15);
                        if (nums.length >= 2) entry.score = nums[0] + ':' + nums[1];
                        h2h.push(entry);
                    }
                }
                let si = L.findIndex(l => l.trim() === 'TABLE');
                const st = [];
                if (si >= 0) {
                    let cur = null;
                    for (let i = si + 1; i < Math.min(si + 300, L.length); i++) {
                        const l = L[i].trim();
                        if (!l || ['#','TEAM','P','W','D','L','F','A','GD','PTS','FORM'].includes(l)) continue;
                        if (l.startsWith('Follow') || l === 'FOOTBALL') break;
                        if (/^\\d{1,2}\\.$/.test(l)) {
                            if (cur) st.push(cur); if (st.length >= 16) break;
                            cur = {pos: l.replace('.',''), name: '', p: '', w:'', d:'', l:'', f:'', gd:'', pts:'', form:[]};
                            continue;
                        }
                        if (!cur) continue;
                        if (!cur.name && l.length > 2 && !/^[.\\-?\\d]+$/.test(l)) { cur.name = l; continue; }
                        if (cur.name && /^\\d{1,2}$/.test(l)) {
                            if (!cur.p) { cur.p = l; continue; }
                            if (!cur.w) { cur.w = l; continue; }
                            if (!cur.d) { cur.d = l; continue; }
                            if (!cur.l) { cur.l = l; continue; }
                        }
                        if (cur.p && cur.w && cur.d && cur.l && /^\\d+:\\d+$/.test(l)) { cur.f = l; continue; }
                        if (cur.f && /^-?\\d{1,3}$/.test(l) && !cur.gd) { cur.gd = l; continue; }
                        if (cur.gd && /^\\d{1,3}$/.test(l) && !cur.pts) { cur.pts = l; continue; }
                        if (cur.pts && ['W','D','L'].includes(l)) cur.form.push(l);
                    }
                    if (cur) st.push(cur);
                }
                return {info, form, h2h, standings: st};
            }''')
            data = {k: r[k] for k in data}
            b.close()
    except:
        pass
    return data


# ═══════════════════ Few-shot (похожие матчи) ═══════════════════

def find_similar_predictions(match_info, sstats_data, top_k=3):
    """Ищет похожие завершённые матчи с верными прогнозами.
    Сначала БД, fallback на JSON."""
    import json, os

    g = sstats_data.get('glicko', {})
    if not g:
        return []

    home_prob = g.get('home_prob', 0.5)
    draw_prob = g.get('draw_prob', 0.25)
    away_prob = g.get('away_prob', 0.25)
    league = match_info.get('league', '')

    # БД
    if _DB_AVAILABLE:
        try:
            rows = db.find_similar(home_prob, draw_prob, away_prob, league, top_k)
            if rows:
                # Конвертируем RealDictRow в обычные dict (для совместимости с JSON форматом)
                result = []
                for r in rows:
                    d = dict(r)
                    # Восстанавливаем вложенную структуру для совместимости
                    d['result'] = {
                        'win': {'correct': d.pop('result_win', None) == 'correct',
                                'predicted': d.get('xgb_win_pred')},
                        'total': {'correct': d.pop('result_total', None) == 'correct',
                                  'predicted': d.get('xgb_total_pred')},
                    }
                    d['glicko'] = {
                        'home_prob': d.pop('glicko_home_prob', None),
                        'draw_prob': d.pop('glicko_draw_prob', None),
                        'away_prob': d.pop('glicko_away_prob', None),
                    }
                    result.append(d)
                return result
        except:
            pass

    # Fallback: JSON (старый формат)
    hist_path = '/opt/predictions_history.json'
    if not os.path.exists(hist_path):
        return []

    try:
        with open(hist_path, encoding='utf-8') as f:
            hist = json.load(f)
    except:
        return []

    candidates = []
    for p in hist.get('predictions', []):
        r = p.get('result')
        if not r or not isinstance(r, dict):
            continue
        win_ok = r.get('win', {}).get('correct') is True
        total_ok = r.get('total', {}).get('correct') is True
        if not (win_ok or total_ok):
            continue
        if p.get('league') and p.get('league') != league:
            pl_penalty = 0.15
        else:
            pl_penalty = 0.0
        pg = p.get('glicko', {})
        if not pg:
            continue
        dist = abs(pg.get('home_prob', 0) - home_prob) \
             + abs(pg.get('draw_prob', 0) - draw_prob) \
             + abs(pg.get('away_prob', 0) - away_prob) \
             + pl_penalty
        if dist < 0.4:
            candidates.append((dist, p))

    candidates.sort(key=lambda x: x[0])
    return [c[1] for c in candidates[:top_k]]


# ═══════════════════ Статистика капера ═══════════════════

def _build_capper_stats():
    """Собирает блок статистики для system prompt.
    Сначала БД, fallback на JSON."""
    import json, os

    s = None
    # БД
    if _DB_AVAILABLE:
        try:
            s = db.get_stats()
        except:
            s = None

    # Fallback: JSON
    if not s or s.get('total_predictions', 0) < 5:
        hist_path = '/opt/predictions_history.json'
        if os.path.exists(hist_path):
            try:
                with open(hist_path, encoding='utf-8') as f:
                    hist = json.load(f)
                s = hist.get('summary', {})
            except:
                pass

    if not s:
        return ''
    total = s.get('total_predictions', 0)
    if total < 5:
        return ''

    win = s.get('win', {})
    tot = s.get('total', {})
    by_league = s.get('by_league', {})

    wt = win.get('total', 0) or 1
    tt = tot.get('total', 0) or 1
    wc = win.get('correct', 0)
    tc = tot.get('correct', 0)

    lines = []
    lines.append('📊 Твоя текущая статистика:')
    lines.append(f'Win: {wc}/{wt} ({wc/wt*100:.0f}%) | Total: {tc}/{tt} ({tc/tt*100:.0f}%)')

    if by_league:
        lines.append('По лигам:')
        for league, st in sorted(by_league.items(), key=lambda x: x[1].get('win', {}).get('total', 0), reverse=True):
            w = st.get('win', {})
            t = st.get('total', {})
            wt_l = w.get('total', 0) or 1
            tt_l = t.get('total', 0) or 1
            lines.append(f'  {league}: Win {w.get("correct",0)}/{w.get("total",0)} ({w.get("correct",0)/wt_l*100:.0f}%), '
                        f'Total {t.get("correct",0)}/{t.get("total",0)} ({t.get("correct",0)/tt_l*100:.0f}%)')

    # Слабое место
    if wc < tc:
        lines.append(f'Подсказка: исходы — твой слабый сигнал (Win {wc/wt*100:.0f}%), будь осторожнее с фаворитами.')
    else:
        lines.append(f'Подсказка: тоталы — твой слабый сигнал (Total {tc/tt*100:.0f}%), перепроверь аргументы.')

    return '\n' + '\n'.join(lines)


# ═══════════════════ XGBoost ═══════════════════

def _xgb_feature_vector(sstats_data):
    """Превращает sstats_data в вектор фич для XGBoost."""
    g = sstats_data.get('glicko', {}) or {}
    odds = sstats_data.get('odds')
    if isinstance(odds, list) and odds:
        odds = odds[0]
    if not isinstance(odds, dict):
        odds = {}
    totals = sstats_data.get('totals', {}) or {}

    hp = g.get('home_prob', 0.33)
    dp = g.get('draw_prob', 0.33)
    ap = g.get('away_prob', 0.33)
    hr = g.get('home_rating', 1500)
    ar = g.get('away_rating', 1500)
    hx = g.get('home_xg', 1.2)
    ax = g.get('away_xg', 1.2)

    oh = float(odds.get('home', 2.0))
    od = float(odds.get('draw', 3.5))
    oa = float(odds.get('away', 2.0))

    ih = 1.0 / max(oh, 0.01)
    id_ = 1.0 / max(od, 0.01)
    ia = 1.0 / max(oa, 0.01)
    margin = ih + id_ + ia

    return [
        hp, dp, ap,
        hr, ar,
        hx, ax,
        oh, od, oa,
        ih / margin, id_ / margin, ia / margin,
        hr - ar,
        hx - ax,
        float(totals.get('over', 1.9)),
        float(totals.get('under', 1.9)),
    ]


def xgb_predict(sstats_data):
    """Предсказание XGBoost моделей для текущего матча.
    Возвращает dict с вердиктами или None, если модели не загружены/нет данных."""
    import os, json
    import numpy as np
    import xgboost as xgb

    win_path = '/opt/capper_xgb/xgb_win.json'
    total_path = '/opt/capper_xgb/xgb_total.json'

    if not os.path.exists(win_path) or not os.path.exists(total_path):
        return None

    g = sstats_data.get('glicko', {})
    if not g:
        return None

    features = np.array([_xgb_feature_vector(sstats_data)], dtype=np.float32)

    try:
        model_win = xgb.XGBClassifier()
        model_win.load_model(win_path)

        model_total = xgb.XGBClassifier()
        model_total.load_model(total_path)

        # Win: home/draw/away
        win_probs = model_win.predict_proba(features)[0]
        win_labels = ['home', 'draw', 'away']
        win_pred = win_labels[np.argmax(win_probs)]
        win_conf = float(win_probs.max())

        # Total: over/under (с total_line из данных)
        total_line = sstats_data.get('totals', {}).get('total_line', 2.5)
        feat_tot = np.append(features[0], total_line).reshape(1, -1)
        total_probs = model_total.predict_proba(feat_tot)[0]
        total_pred = 'over' if total_probs[0] > total_probs[1] else 'under'
        total_conf = float(max(total_probs))

        return {
            'win_prediction': win_pred,
            'win_confidence': round(win_conf, 3),
            'win_probs': {l: round(float(p), 3) for l, p in zip(win_labels, win_probs)},
            'total_prediction': total_pred,
            'total_confidence': round(total_conf, 3),
        }
    except Exception as e:
        print(f'  ⚠️ XGBoost error: {e}')
        return None


# ═══════════════════ DeepSeek + Humanizer ═══════════════════

def generate_prediction_text(match_info, sstats_data, fs_data, lineups=None, similar_preds=None, stats_block='', xgb_verdict=None):
    """Сформировать текст прогноза через DeepSeek.
    xgb_verdict: результат xgb_predict() или None."""
    if not DEEPSEEK_KEY:
        return _fallback_prediction(sstats_data)

    # Собираем промпт
    parts = [f'Матч: {match_info.get("home", "?")} — {match_info.get("away", "?")}']
    parts.append(f'Лига: {match_info.get("league", "?")}')
    parts.append(f'Дата: {match_info.get("date", "?")}')

    # Glicko
    g = sstats_data.get('glicko', {})
    if g:
        parts.append(f'\nGlicko рейтинг:\n  {match_info.get("home","?")}: рейтинг {g.get("home_rating","?")}, вероятность {g.get("home_prob",0)*100:.0f}%, xG {g.get("home_xg",0):.2f}')
        parts.append(f'  {match_info.get("away","?")}: рейтинг {g.get("away_rating","?")}, вероятность {g.get("away_prob",0)*100:.0f}%, xG {g.get("away_xg",0):.2f}')
        parts.append(f'  Ничья: {g.get("draw_prob",0)*100:.0f}%')

    # Коэффициенты
    odds = sstats_data.get('odds', [])
    if odds:
        o = odds[0]
        avg_h = sum(o['home'] for o in odds[:3]) / max(len(odds[:3]), 1) if isinstance(odds, list) else o.get('home', 0)
        parts.append(f'\nКоэффициенты: 1) {o.get("home","?")} X) {o.get("draw","?")} 2) {o.get("away","?")}')

    # Форма
    fs_form = fs_data.get('form', {})
    if fs_form:
        for team_name, form_list in fs_form.items():
            if form_list:
                parts.append(f'{team_name}: форма {" ".join(form_list)}')

    # H2H
    h2h = fs_data.get('h2h', [])
    if h2h:
        parts.append('\nОчные встречи:')
        for h in h2h[:5]:
            parts.append(f'  {h.get("date","")}: {h.get("team1","")} — {h.get("team2","")} {h.get("score","")}')

    # Таблица
    st = fs_data.get('standings', [])
    if st:
        parts.append('\nТурнирная таблица (топ-5):')
        for s in st[:5]:
            if s.get('pts'):
                parts.append(f'  {s["pos"]}. {s["name"]} — {s["pts"]} оч.')

    # Стадион, судья
    info = fs_data.get('info', {})
    if info.get('venue'): parts.append(f'\nСтадион: {info["venue"]}')
    if info.get('referee'): parts.append(f'Судья: {info["referee"]}')

    # Травмы
    inj = sstats_data.get('injuries', [])
    if inj:
        parts.append('\nТравмы:')
        for i in inj[:5]:
            p = i.get('player', {})
            name = p.get('name', '?') if isinstance(p, dict) else str(p)
            team = i.get('teamName', '')
            reason = i.get('reason', '')
            parts.append(f'  {team}: {name} ({reason})')

    # Составы (если есть)
    if lineups:
        parts.append(f'\nСтартовые составы:')
        if lineups.get('formation_home'): parts.append(f'{match_info.get("home","?")} ({lineups["formation_home"]}):')
        for p in lineups.get('home', []):
            parts.append(f'  • {p}')
        if lineups.get('formation_away'): parts.append(f'{match_info.get("away","?")} ({lineups["formation_away"]}):')
        for p in lineups.get('away', []):
            parts.append(f'  • {p}')
        if lineups.get('bench_home'):
            parts.append(f'Запасные ({match_info.get("home","?")}): {", ".join(lineups["bench_home"][:5])}')
        if lineups.get('bench_away'):
            parts.append(f'Запасные ({match_info.get("away","?")}): {", ".join(lineups["bench_away"][:5])}')

    # Тоталы
    if sstats_data.get('totals') and sstats_data['totals'].get('over'):
        tl = sstats_data['totals'].get('total_line', 2.5)
        parts.append(f'\nТотал {tl}: Over {sstats_data["totals"]["over"]}, Under {sstats_data["totals"]["under"]}')

    # ✨ Few-shot: похожие матчи из истории
    if similar_preds:
        parts.append('\n\nПохожие матчи из твоей статистики (где прогноз оказался верным):')
        for sp in similar_preds:
            sp_home = sp.get('home', '?')
            sp_away = sp.get('away', '?')
            sp_score = sp.get('score', '?')
            sp_result = sp.get('result', {})
            win_verdict = sp_result.get('win', {}).get('predicted', '?')
            total_verdict = sp_result.get('total', {}).get('predicted', '?')
            parts.append(f'  • {sp_home} — {sp_away} ({sp_score}): исход={win_verdict}, тотал={total_verdict}')

    # ✨ XGBoost вердикт
    if xgb_verdict:
        w = xgb_verdict
        wl = {'home': 'хозяев', 'draw': 'ничью', 'away': 'гостей'}
        parts.append(f'\n🤖 Математическая модель прогнозирует:')
        parts.append(f'  Исход: {wl.get(w["win_prediction"], w["win_prediction"])} (уверенность {w["win_confidence"]*100:.0f}%)')
        parts.append(f'  Тотал: {w["total_prediction"].upper()} (уверенность {w["total_confidence"]*100:.0f}%)')
        parts.append(f'  Вероятности: П1 {w["win_probs"]["home"]*100:.0f}%, X {w["win_probs"]["draw"]*100:.0f}%, П2 {w["win_probs"]["away"]*100:.0f}%')

    prompt = '\n'.join(parts)
    prompt += '\n\nНапиши прогноз живым человеческим языком, как обсуждаешь матч с другом. Без шаблонов, списков и заголовков. Каждый раз начинай по-разному: вопросом, неожиданным фактом, цифрой, интригой, сравнением. В конце укажи вердикт на исход и отдельно на тотал (с аргументацией).' 

    # ✨ Собираем system prompt со статистикой
    system_msg = 'Ты спортивный аналитик с ярким стилем. Пиши прогноз как человек, а не как отчёт. Без списков, заголовков, приветствий и жирного текста. Каждый прогноз начинай уникально: вопросом, цифрой, интригой, сочной цитатой, историей — не повторяйся. В конце чёткий вердикт.'
    if stats_block:
        system_msg += stats_block

    try:
        resp = requests.post('https://api.deepseek.com/v1/chat/completions', json={
            'model': 'deepseek-chat',
            'messages': [
                {'role': 'system', 'content': system_msg},
                {'role': 'user', 'content': prompt}
            ],
            'temperature': 0.65,
            'max_tokens': 1500
        }, headers={'Authorization': f'Bearer {DEEPSEEK_KEY}'}, timeout=30)
        data = resp.json()
        if 'choices' in data and len(data['choices']) > 0:
            text = data['choices'][0]['message']['content'].strip()
            # Заменяем тотал на ТБ/ТМ
            text = text.replace('Over', 'ТБ').replace('Under', 'ТМ')
            text = text.replace('over', 'ТБ').replace('under', 'ТМ')
            text = text.replace('тотал больше', 'ТБ').replace('тотал меньше', 'ТМ')
            text = text.replace('Тотал больше', 'ТБ').replace('Тотал меньше', 'ТМ')
            text = text.replace('тотал', 'тотал').replace('Тотал', 'Тотал')
            text = _diversify_opening(text)
            return text
    except:
        pass
    return _fallback_prediction(sstats_data)


def _fallback_prediction(sstats_data):
    """Запасной прогноз на основе цифр."""
    odds = sstats_data.get('odds', [])
    if not odds:
        return 'Недостаточно данных для прогноза'
    o = odds[0]
    margin = 1/o['home'] + 1/o['draw'] + 1/o['away']
    hp = (1/o['home']) / margin * 100
    ap = (1/o['away']) / margin * 100
    if hp > ap:
        return f'Фаворит — хозяева ({hp:.0f}%). Кэф: {o["home"]}.'
    else:
        return f'Фаворит — гости ({ap:.0f}%). Кэф: {o["away"]}.'


# ═══════════════════ Process match ═══════════════════

def process_match(match_info, fetch_fs=True, fetch_lineups_flag=False, pw_page=None):
    """
    Полный цикл прогноза для одного матча.
    match_info: {home, away, league, time, game_id, ...}
    pw_page: переиспользуемый Playwright page (или None).
    Возвращает dict с прогнозом или None.
    """
    home = match_info.get('home', '')
    away = match_info.get('away', '')
    league = match_info.get('league', '')
    game_id = match_info.get('game_id')

    print(f'  🔮 {home} — {away}... ', end='', flush=True)

    # 1. SStats
    if game_id:
        ss = fetch_sstats(game_id)
    else:
        print('❌ нет game_id')
        return None

    if not ss.get('odds') and not ss.get('glicko'):
        print('❌ нет данных SStats')
        return None

    # 2. Flashscore (форма, H2H, таблица)
    fs_data = {'info': {}, 'form': {}, 'h2h': [], 'standings': []}
    if fetch_fs:
        try:
            if ss.get('flashId'):
                fs_url = f'https://www.flashscore.com/match/{ss["flashId"]}/#/match-summary'
                fs_data = parse_match_flashscore(fs_url)
            else:
                fs_match = find_match_flashscore(home, away, league)
                if fs_match:
                    fs_data = parse_match_flashscore(fs_match['url'])
        except:
            pass

    # 3. Составы (если нужно)
    lineups = None
    if fetch_lineups_flag and ss.get('flashId'):
        lineups = fetch_lineups_flashscore(ss['flashId'])
        if lineups:
            print(f'составы ✅... ', flush=True)

    # 4. ✨ Few-shot: похожие матчи из истории
    similar_preds = find_similar_predictions(match_info, ss)
    if similar_preds:
        print(f'few-shot {len(similar_preds)} ✅... ', end='', flush=True)

    # 5. ✨ Статистика капера в system prompt
    stats_block = _build_capper_stats()
    if stats_block:
        print(f'stats ✅... ', end='', flush=True)

    # 5.5 ✨ XGBoost модель
    xgb_verdict = xgb_predict(ss)
    if xgb_verdict:
        print(f'xgb {xgb_verdict["win_prediction"]} ({xgb_verdict["win_confidence"]:.0%}) ✅... ', end='', flush=True)

    # 6. DeepSeek прогноз (с кешем)
    match_info_full = {**match_info, 'home': match_info.get('home', home), 'away': match_info.get('away', away), 'home_en': ss.get('home', home), 'away_en': ss.get('away', away)}

    # Определяем, нужен ли force refresh
    force_refresh = '--refresh' in sys.argv or '--no-cache' in sys.argv

    def _do_generate():
        return generate_prediction_text(match_info_full, ss, fs_data, lineups,
                                         similar_preds=similar_preds, stats_block=stats_block,
                                         xgb_verdict=xgb_verdict)

    pred_text = call_deepseek_with_cache(
        match_info={
            'home': match_info.get('home', home),
            'away': match_info.get('away', away),
            'league': league,
        },
        sstats_data=ss,
        generate_fn=_do_generate,
        force_refresh=force_refresh,
    )

    if force_refresh:
        print(f'✅ DeepSeek (force)')
    return {
        'home': match_info.get('home', home),
        'away': match_info.get('away', away),
        'league': league,
        'time': match_info.get('time', ''),
        'game_id': game_id,
        'verdict': pred_text.split('.')[0] if '.' in pred_text else pred_text[:80],
        'prediction': pred_text,
        'odds': {'home': round(ss['odds'][0]['home'], 2), 'draw': round(ss['odds'][0]['draw'], 2), 'away': round(ss['odds'][0]['away'], 2)} if ss.get('odds') else None,
        'totals': ss.get('totals', {}),
        'glicko': ss.get('glicko'),
        'xgb_verdict': xgb_verdict,
        'has_lineups': bool(lineups),
        'generated_at': datetime.now().isoformat(),
    }


# ═══════════════════ Batch modes ═══════════════════

def _load_matches():
    """Загрузить матчи для прогнозов: сначала upcoming_matches.json,
    потом fallback на tv_channels_data.json (футбол + game_id)."""
    import storage as _st
    active = set(_PRED_LEAGUES.keys())

    def _flatten(path, is_upcoming=False):
        matches = []
        by_date = _st.load_by_date(path)
        for date_str, date_matches in by_date.items():
            for m in date_matches:
                if is_upcoming:
                    if m.get('league') in active:
                        matches.append(m)
                else:
                    if m.get('sport') == 'football' and m.get('league') in active and m.get('game_id'):
                        matches.append({
                            'home': m['home'],
                            'away': m['away'],
                            'time': m.get('time', ''),
                            'game_id': m['game_id'],
                            'league': m['league'],
                        })
        return matches

    # Пробуем upcoming_matches.json (приоритет)
    matches = _flatten('/tmp/upcoming_matches.json', is_upcoming=True)
    if matches:
        print(f'📖 upcoming_matches.json: {len(matches)} матчей')
        return matches

    # Fallback: tv_channels_data.json
    matches = _flatten('/tmp/tv_channels_data.json')
    if matches:
        print(f'📖 tv_channels_data.json: {len(matches)} матчей (fallback)')
        return matches

    print('❌ Нет матчей для прогнозов')
    return []


def _batch_process_matches(matches, fetch_fs=True, fetch_lineups=False):
    """
    Обработать список матчей с одним Playwright-браузером.
    При ошибке браузера — fallback на отдельные браузеры для каждого матча.
    """
    from playwright.sync_api import sync_playwright

    predictions = []
    browser = None

    try:
        p_ctx = sync_playwright()
        p_ctx.__enter__()
        browser = p_ctx.chromium.launch(headless=True, args=['--no-sandbox'])
    except Exception as e:
        print(f'  ⚠️ Не удалось запустить Playwright: {e}')
        # Fallback: последовательный режим
        for i, m in enumerate(matches):
            start_t = time_module.time()
            pred = process_match(m, fetch_fs=fetch_fs, fetch_lineups_flag=fetch_lineups)
            if pred:
                predictions.append(pred)
            elapsed = time_module.time() - start_t
            print(f'  [{i+1}/{len(matches)}] {m.get("home","?")} — {m.get("away","?")} {elapsed:.1f}с (fallback)')
        return predictions

    try:
        for i, m in enumerate(matches):
            start_t = time_module.time()
            try:
                page = browser.new_page(viewport={'width': 1920, 'height': 1080})
                page.set_default_timeout(20000)
            except Exception as e:
                print(f'  ⚠️ Ошибка матча [{i+1}]: {e}')
                # Fallback: без Playwright для этого матча
                pred = process_match(m, fetch_fs=fetch_fs, fetch_lineups_flag=False, pw_page=None)
            if pred:
                predictions.append(pred)
            elapsed = time_module.time() - start_t
            print(f'  [{i+1}/{len(matches)}] {m.get("home","?")} — {m.get("away","?")} {elapsed:.1f}с')
            print(f'  [{i+1}/{len(matches)}] {m.get("home","?")} — {m.get("away","?")} {elapsed:.1f}с')
            # Сохраняем инкрементально после каждых 3 матчей
            if i % 3 == 2 or i == len(matches) - 1:
                pass  # caller сохранит финальный результат
    finally:
        if browser:
            try:
                browser.close()
            except:
                pass
        try:
            p_ctx.__exit__(None, None, None)
        except:
            pass

    return predictions


def batch_generate():
    """Полная генерация прогнозов на все матчи."""
    matches = _load_matches()

    if not matches:
        _save_predictions([])
        _run_post_generate_check([], 'predictions_data')
        return

    # Валидация входящих матчей
    for i, m in enumerate(matches):
        for field in ('league', 'home', 'away', 'game_id'):
            assert field in m, f'Матч [{i}] не имеет поля {field}: {m}'
        assert isinstance(m.get('league'), str), f'league должно быть str: {m}'
        assert isinstance(m.get('home'), str), f'home должно быть str: {m}'
        assert isinstance(m.get('away'), str), f'away должно быть str: {m}'

    print(f'📊 Прогнозов: {len(matches)}')
    predictions = _batch_process_matches(matches, fetch_fs=True, fetch_lineups=False)

    # Финальное сохранение
    _save_predictions(predictions)
    print(f'\n✅ Всего: {len(predictions)} прогнозов')
    _run_post_generate_check(predictions, 'predictions_data')


def batch_refresh():
    """Обновить прогнозы для матчей, до которых <= 1 час."""
    now = datetime.now(UTC) + MOW
    path = '/tmp/upcoming_matches.json'
    if not os.path.exists(path):
        return

    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    matches = data.get('matches', [])
    active = set(_PRED_LEAGUES.keys())
    matches = [m for m in matches if m.get('league') in active]

    # Загружаем текущие прогнозы
    existing = {}
    pred_path = '/opt/predictions_data.json'
    if os.path.exists(pred_path):
        try:
            with open(pred_path) as f:
                for p in json.load(f).get('predictions', []):
                    existing[(p.get('league',''), p.get('home',''), p.get('away',''))] = p
        except: pass

    # Отбираем матчи, до которых <= 1 час
    to_refresh = []
    for m in matches:
        try:
            match_time_str = m.get('time', '')
            match_hour, match_min = map(int, match_time_str.split(':'))
            match_dt = now.replace(hour=match_hour, minute=match_min, second=0)
            if match_dt < now:
                match_dt += timedelta(days=1)
        except:
            continue

        diff = (match_dt - now).total_seconds()
        if 0 < diff < 3900:  # ~1 час 5 минут
            print(f'⏰ {m["home"]} — {m["away"]} через {int(diff/60)} мин')
            to_refresh.append(m)

    if not to_refresh:
        return

    refreshed = _batch_process_matches(to_refresh, fetch_fs=True, fetch_lineups=True)

    for pred in refreshed:
        key = (pred.get('league',''), pred.get('home',''), pred.get('away',''))
        existing[key] = pred

    if refreshed:
        _save_predictions(list(existing.values()))
        print(f'✅ Обновлено: {len(refreshed)} прогнозов')



def _diversify_opening(text):
    """Заменить однотипное начало на случайное, если модель не справилась."""
    import random
    starters = [
        'А вот что интересно: ', 'По цифрам вырисовывается такая картина: ',
        'Если смотреть по статистике: ', 'Ключевой момент матча: ',
        'Расклад такой: ', 'Давай разберём: ',
        'Судя по данным: ', 'Интрига вот в чём: ',
        'Главный вопрос матча: ', 'Что говорят цифры: ',
        'Мой анализ показывает: ', 'В этом матче: ',
        'Обрати внимание: ', 'Коротко по делу: ',
        'Ситуация такая: ', 'Если честно: ',
    ]
    for old in ['Смотри, ', 'Смотри,', 'Слушай, ', 'Слушай,', 'Ну, ', 'Ну и ', 'Так, ', 'Так,']:
        if text.startswith(old):
            replacement = random.choice(starters)
            rest = text[len(old):].lstrip()
            # Capitalize first letter
            if rest and rest[0].islower():
                rest = rest[0].upper() + rest[1:]
            return replacement + rest
    return text

def _make_match_key(pred):
    """Ключ для дедупликации: лига||home||away"""
    return f"{pred.get('league','')}||{pred.get('home','')}||{pred.get('away','')}"


def _save_predictions(new_predictions):
    """Добавить прогнозы в очередь.
    Пишет в JSON (для совместимости) и в БД (если доступна).
    Дедупликация по (league, home, away).
    """
    # Отфильтровать None
    new_predictions = [p for p in new_predictions if p]
    if not new_predictions:
        return

    # Проверка обязательных полей
    for p in new_predictions:
        for field in ('league', 'home', 'away', 'prediction'):
            assert field in p, f'Прогнозу не хватает поля {field}: {p.get("home","?")} — {p.get("away","?")}'
        assert isinstance(p.get('league'), str), f'league должно быть str: {p}'
        assert isinstance(p.get('home'), str), f'home должно быть str: {p}'
        assert isinstance(p.get('away'), str), f'away должно быть str: {p}'
        assert isinstance(p.get('prediction'), str), f'prediction должно быть str: {p}'

    # JSON (как было)
    existing = {}
    pred_path = '/opt/predictions_data.json'
    if os.path.exists(pred_path):
        try:
            with open(pred_path, encoding='utf-8') as f:
                for p in json.load(f).get('predictions', []):
                    existing[_make_match_key(p)] = p
        except:
            pass

    for p in new_predictions:
        existing[_make_match_key(p)] = p

    output = {
        'predictions': list(existing.values()),
        'count': len(existing),
        'generated_at': datetime.now().isoformat(),
    }
    with open(pred_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # БД
    if _DB_AVAILABLE:
        for p in new_predictions:
            p['status'] = 'upcoming'
            try:
                db.save_prediction(p)
            except Exception:
                pass


# ═══════════════════ Пост-прогоночная проверка ═══════════════════

def _run_post_generate_check(predictions, schema_name='predictions_data'):
    """Проверить, что прогнозы сохранились корректно после batch-генерации."""
    from data_schemas import validate
    import os, json

    pred_path = '/opt/predictions_data.json'

    # 1. Проверка что файл существует
    if not os.path.exists(pred_path):
        print('  ⚠️ Post-check: predictions_data.json не найден!')
        return

    try:
        with open(pred_path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f'  ❌ Post-check: ошибка чтения predictions_data.json: {e}')
        return

    preds = data.get('predictions', [])

    # 2. Количество прогнозов > 0
    if len(preds) == 0:
        print('  ❌ Post-check: predictions_data.json пуст!')
        return

    # 3. Валидация по схеме
    ok, errors = validate(data, schema_name)
    if ok:
        print(f'  ✅ Post-check: {len(preds)} прогнозов, схема OK')
    else:
        print(f'  ⚠️ Post-check: {len(errors)} ошибок схемы (первые 3):')
        for e in errors[:3]:
            print(f'    - {e}')

    # 4. Каждый прогноз проходит проверку
    for i, p in enumerate(preds):
        for field in ('league', 'home', 'away', 'prediction'):
            if field not in p:
                print(f'  ⚠️ Post-check: прогноз [{i}] без поля {field}')
                break


# ═══════════════════ CLI ═══════════════════

def main():
    if '--batch' in sys.argv:
        batch_generate()
    elif '--refresh' in sys.argv:
        batch_refresh()
    elif len(sys.argv) >= 3:
        # Одиночный матч (старый режим)
        t1, t2 = sys.argv[1], sys.argv[2]
        lk = sys.argv[3] if len(sys.argv) > 3 else None
        match_info = {'home': t1, 'away': t2, 'league': lk or '?', 'time': '?', 'game_id': None}

        # Ищем game_id по названиям
        print(f'📡 Поиск матча: {t1} — {t2}', file=sys.stderr)
        lid = LS.get(lk, 235) if lk else 235
        data = sq('/Games/list', {'LeagueId': lid, 'Year': 2025, 'take': 200})
        games = data if isinstance(data, list) else data.get('data', [])
        for g in games:
            ht = str(g.get('homeTeam', {}).get('name', '')).lower()
            at = str(g.get('awayTeam', {}).get('name', '')).lower()
            if t1.lower() in ht and t2.lower() in at:
                match_info['game_id'] = g.get('id')
                break

        pred = process_match(match_info, fetch_fs=True, fetch_lineups_flag=True)
        if pred:
            print(f'\n=== ПРОГНОЗ ===')
            print(pred['prediction'])
            print(f'\n⚡ Сохранено в predictions_data.json')
    else:
        print('Режимы: --batch | --refresh | --match "Ком1" "Ком2" [rpl/epl/...]')


if __name__ == '__main__':
    try:
        main()
        report_success('capper_pipeline')
    except Exception as e:
        report_failure('capper_pipeline', str(e))
        raise
