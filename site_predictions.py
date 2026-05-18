#!/usr/bin/env python3
"""
Генератор страницы прогнозов.
Показывает только матчи, на которые есть активные прогнозы (не оценённые).
Добавляется: после capper_pipeline.py
Удаляется: после evaluate_predictions.py (матч сыгран и оценён)
"""

import os, sys, json
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, '/opt')
import site_common
from generate_site_legacy import _team_logo, escape

UTC = timezone.utc
MOW = timedelta(hours=3)


def _format_pct(val):
    if val is None:
        return '—'
    return f'{round(val * 100)}%'


def _render_pred_card(pred):
    """Одна карточка прогноза."""
    league = pred.get('league', '')
    home = pred.get('home', '')
    away = pred.get('away', '')
    time_str = pred.get('time', '')
    odds = pred.get('odds', {})
    totals = pred.get('totals', {})
    glicko = pred.get('glicko', {})
    verdict = pred.get('verdict', '')

    # Вероятности
    hp = _format_pct(glicko.get('home_prob'))
    dp = _format_pct(glicko.get('draw_prob'))
    ap = _format_pct(glicko.get('away_prob'))

    # Рейтинг и xG
    hr = round(glicko.get('home_rating', 0)) if glicko.get('home_rating') else ''
    ar = round(glicko.get('away_rating', 0)) if glicko.get('away_rating') else ''
    hx = f"{glicko['home_xg']:.2f}" if glicko.get('home_xg') else ''
    ax = f"{glicko['away_xg']:.2f}" if glicko.get('away_xg') else ''

    # Логотипы
    h_logo = _team_logo(home)
    a_logo = _team_logo(away)
    h_logo_html = f'<img class="rl-logo" src="{h_logo}" alt="" loading="lazy" onerror="this.style.display=\'none\'">' if h_logo else ''
    a_logo_html = f'<img class="rl-logo" src="{a_logo}" alt="" loading="lazy" onerror="this.style.display=\'none\'">' if a_logo else ''

    # odds блок
    odds_html = ''
    if odds or totals:
        parts = []
        if odds.get('home'): parts.append(f'<span class="pred-odds-box"><span class="pred-odds-label">П1</span><span class="pred-odds-val">{odds["home"]}</span></span>')
        if odds.get('draw'): parts.append(f'<span class="pred-odds-box"><span class="pred-odds-label">X</span><span class="pred-odds-val" style="color:#ffd700">{odds["draw"]}</span></span>')
        if odds.get('away'): parts.append(f'<span class="pred-odds-box"><span class="pred-odds-label">П2</span><span class="pred-odds-val">{odds["away"]}</span></span>')
        tl = totals.get('total_line', 2.5)
        if totals.get('over'): parts.append(f'<span class="pred-odds-box"><span class="pred-odds-label">ТБ {tl}</span><span class="pred-odds-val" style="color:#00e676">{totals["over"]}</span></span>')
        if totals.get('under'): parts.append(f'<span class="pred-odds-box"><span class="pred-odds-label">ТМ {tl}</span><span class="pred-odds-val" style="color:#ff9800">{totals["under"]}</span></span>')
        if parts:
            odds_html = f'<div class="pred-odds-row">{" ".join(parts)}</div>'

    # Вердикт (первые 150 символов)
    verdict_short = verdict[:150] + '…' if len(verdict) > 150 else (verdict or '')

    return f'''
    <div class="pred-card">
        <div class="pred-top-row">
            <div class="pred-teams">
                <div class="pred-team">{h_logo_html}<span class="pred-team-name">{escape(home)}</span></div>
                <div class="pred-team pred-team-away">{a_logo_html}<span class="pred-team-name">{escape(away)}</span></div>
            </div>
            <div class="pred-time-score">
                <div class="pred-time">{escape(time_str)}</div>
            </div>
        </div>
        <div class="pred-probs">
            <div class="pred-prob-bar">
                <div class="pred-prob-seg pred-prob-home" style="flex:{glicko.get("home_prob", 0.33)*100:.0f}"></div>
                <div class="pred-prob-seg pred-prob-draw" style="flex:{glicko.get("draw_prob", 0.33)*100:.0f}"></div>
                <div class="pred-prob-seg pred-prob-away" style="flex:{glicko.get("away_prob", 0.33)*100:.0f}"></div>
            </div>
            <div class="pred-prob-labels">
                <span>{escape(home)} {hp}</span>
                <span>Ничья {dp}</span>
                <span>{ap} {escape(away)}</span>
            </div>
        </div>
        {odds_html}
        {f'<div class="pred-ratings">' if hr or ar else ''}
        {f'<span>Рейтинг: {hr} — {ar}</span>' if hr or ar else ''}
        {f'<span>xG: {hx} — {ax}</span>' if hx or ax else ''}
        {f'</div>' if hr or ar else ''}
        {f'<div class="pred-verdict">{escape(verdict_short)}</div>' if verdict_short else ''}
    </div>'''


def generate_predictions(output_path='/var/www/sport/predictions.html'):
    now = datetime.now(UTC) + MOW
    now_str = now.strftime('%d.%m.%Y %H:%M')

    # ── Прогнозы из очереди ──
    predictions_by_league = defaultdict(list)
    pred_path = '/opt/predictions_data.json'
    if os.path.exists(pred_path):
        try:
            with open(pred_path, encoding='utf-8') as f:
                pred_data = json.load(f)
            for p in pred_data.get('predictions', []):
                league = p.get('league', 'Другое')
                predictions_by_league[league].append(p)
        except:
            pass

    # ── Статистика из истории ──
    stats = {}
    hist_path = '/opt/predictions_history.json'
    if os.path.exists(hist_path):
        try:
            with open(hist_path, encoding='utf-8') as f:
                hist = json.load(f)
            stats = hist.get('summary', {})
        except:
            pass

    # ── HTML ──
    html = site_common.page_header('Прогнозы', 'predictions', now_str)

    # Статистика
    win_total = stats.get('win', {}).get('total', 0)
    win_correct = stats.get('win', {}).get('correct', 0)
    tot_total = stats.get('total', {}).get('total', 0)
    tot_correct = stats.get('total', {}).get('correct', 0)
    finished = stats.get('finished', 0)

    if finished > 0:
        win_pct = round(win_correct / win_total * 100) if win_total > 0 else 0
        tot_pct = round(tot_correct / tot_total * 100) if tot_total > 0 else 0
        win_color = '🟢' if win_pct >= 60 else '🟡' if win_pct >= 40 else '🔴'
        tot_color = '🟢' if tot_pct >= 60 else '🟡' if tot_pct >= 40 else '🔴'
        stats_html = f'''
        <div class="pred-stats">
            <div class="pred-stats-title">📊 Статистика прогнозов <span class="pred-stats-sub">({finished} завершено)</span></div>
            <div class="pred-stats-row">
                <div class="pred-stat-box">
                    <div class="pred-stat-label">Исход (П1/Х/П2)</div>
                    <div class="pred-stat-val">{win_color} {win_correct}/{win_total} ({win_pct}%)</div>
                </div>
                <div class="pred-stat-box">
                    <div class="pred-stat-label">Тотал (Over/Under)</div>
                    <div class="pred-stat-val">{tot_color} {tot_correct}/{tot_total} ({tot_pct}%)</div>
                </div>
            </div>
        </div>'''
    else:
        stats_html = ''

    html += f'''
    {stats_html}
    <div class="section-title">📈 Активные прогнозы</div>'''

    if not predictions_by_league:
        html += '<p style="color:#666;font-size:14px">Нет активных прогнозов.</p>'
    else:
        html += '<div class="card-grid">'
        for league in sorted(predictions_by_league.keys()):
            preds = predictions_by_league[league]
            html += site_common.section_header(league, 'football')
            for p in preds:
                html += _render_pred_card(p)
        html += '</div>'

    html += site_common.page_footer()
    html = html.replace('JS_PLACEHOLDER', site_common.page_script('{}', '{}'))

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    total_preds = sum(len(v) for v in predictions_by_league.values())
    print(f'✅ Прогнозы ({total_preds} активных): {output_path}')
    return total_preds


if __name__ == '__main__':
    generate_predictions()
