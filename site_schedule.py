#!/usr/bin/env python3
"""
Генератор страницы расписания (читает из БД).
"""

import os, sys, json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/opt')
from date_utils import format_date_display, format_date_iso, today_display, today_iso, tomorrow_display, tomorrow_iso
import site_common
from site_common import escape, _team_logo, render_match_card
from generate_site_legacy import get_tvguide_section
from tennis_names import ru_name as tennis_ru_name
from data_schemas import validate

try:
    import db
    db.get_stats()  # проверка
    HAS_DB = True
except:
    HAS_DB = False

MOW = timedelta(hours=3)


def _render_card(m, preds_lookup, live_lookup=None):
    league = m.get('league', '')
    home = m.get('home', '')
    away = m.get('away', '')
    time_str = m.get('match_time', '') or m.get('time', '') or ''
    import re
    time_str = re.sub(r'^\d{2}\.\d{2}\.\s*', '', time_str)
    score = m.get('score', '')

    home_logo = _team_logo(home, league)
    away_logo = _team_logo(away, league)
    pred = preds_lookup.get((league, home, away))
    data_key = f'{league}||{home}||{away}'

    # Проверяем LIVE
    status = 'scheduled'
    live_score = ''
    if live_lookup:
        live_info = live_lookup.get(data_key)
        if live_info and live_info.get('status') == 'live':
            status = 'live'
            live_score = live_info.get('score', '')
            score = live_score

    if not status == 'live' and score:
        status = 'finished'

    return render_match_card(
        home=home, away=away, league=league,
        status=status,
        match_time=time_str,
        score=score,
        home_logo=home_logo,
        away_logo=away_logo,
        has_pred=bool(pred),
        data_key=data_key,
    )


def generate_schedule(output_path='/var/www/sport/schedule.html'):
    now = datetime.now(timezone.utc) + MOW
    now_str = format_date_display(now) + ' ' + now.strftime('%H:%M')
    today = today_iso()
    tomorrow = tomorrow_iso()
    tomorrow_legacy = tomorrow_display()

    preds_lookup = {}
    live_lookup = {}
    today_matches = []
    tomorrow_matches = []
    tvguide_rows = get_tvguide_section()
    used_db = False

    # Загружаем live scores с валидацией
    live_path = '/tmp/live_scores_data.json'
    if os.path.exists(live_path):
        try:
            with open(live_path, encoding='utf-8') as f:
                live_data = json.load(f)
            ok, errs = validate(live_data, 'live_scores')
            if not ok:
                print(f'  ⚠️ live_scores.json не прошёл валидацию: {errs}')
            else:
                live_lookup = live_data.get('matches', {})
        except Exception as e:
            print(f'  ⚠️ Ошибка загрузки live_scores.json: {e}')

    if HAS_DB:
        try:
            for p in db.get_queue():
                preds_lookup[(p['league'], p['home'], p['away'])] = dict(p)

            today_matches = [dict(m) for m in db.execute(
                "SELECT * FROM matches WHERE match_date = %s "
                "AND status = 'scheduled' ORDER BY league, match_time",
                (today,)
            )]
            tomorrow_matches = [dict(m) for m in db.execute(
                "SELECT * FROM matches WHERE match_date = %s "
                "AND status = 'scheduled' ORDER BY league, match_time",
                (tomorrow,)
            )]
            used_db = True
        except Exception as e:
            print(f'  ⚠️ БД: {e}')

    from generate_site_legacy import get_upcoming as _legacy_upcoming
    if not used_db or not today_matches:
        today_str = today_display()
        today_matches = _legacy_upcoming(target_date=today_str)
    if not used_db or not tomorrow_matches:
        tomorrow_matches = _legacy_upcoming(target_date=tomorrow_legacy)
    if not used_db:
        fpath = '/opt/predictions_data.json'
        if os.path.exists(fpath):
            try:
                with open(fpath, encoding='utf-8') as f:
                    for p in json.load(f).get('predictions', []):
                        preds_lookup[(p.get('league',''), p.get('home',''), p.get('away',''))] = p
            except:
                pass

    def section_matches(matches, is_upcoming=True):
        html = '<div class="card-grid">'
        prev = ''
        for m in matches:
            league = m.get('league', m.get('sport', ''))
            if league != prev:
                sport = 'tennis' if league in ('ATP', 'WTA') else 'football'
                html += site_common.section_header(league, sport)
                prev = league
            html += _render_card(m, preds_lookup, live_lookup)
        html += '</div>'
        return html

    today_html = section_matches(today_matches, True)
    tomorrow_html = section_matches(tomorrow_matches, True)

    tv_html = ''
    if tvguide_rows:
        tv_html = f'''
        <div class="section-title">📺 Матч ТВ — программа</div>
        <table class="compact-table">{tvguide_rows}</table>
        <div class="source-note">Источник: matchtv.ru</div>'''

    html = site_common.page_header('Расписание', 'schedule', now_str)
    html += f'''
    <div class="section-title">📅 Сегодня — {today}</div>
    {today_html}
    {'' if today_html else '<p style="color:#666;font-size:14px">Нет данных.</p>'}

    <div class="section-title">📅 Завтра — {tomorrow}</div>
    {tomorrow_html}
    {'' if tomorrow_html else '<p style="color:#666;font-size:14px">Нет данных.</p>'}

    {tv_html}'''

    # Прогнозы для модалки
    pred_json = {}
    for p in db.get_queue():
        key = f'{p["league"]}||{p["home"]}||{p["away"]}'
        home_logo = _team_logo(p['home'], p['league'])
        away_logo = _team_logo(p['away'], p['league'])
        pred_json[key] = dict(p)
        pred_json[key]['home_logo'] = home_logo
        pred_json[key]['away_logo'] = away_logo
    pred_json_escaped = json.dumps(pred_json, ensure_ascii=False, default=str)
    
    html += site_common.page_footer()
    html = html.replace('JS_PLACEHOLDER', site_common.page_script('{}', pred_json_escaped))

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f'✅ Расписание (сегодня: {len(today_matches)}, завтра: {len(tomorrow_matches)})')
    return len(today_matches), len(tomorrow_matches)


if __name__ == '__main__':
    generate_schedule()
