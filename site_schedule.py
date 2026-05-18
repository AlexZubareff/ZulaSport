#!/usr/bin/env python3
"""
Генератор страницы расписания (Сегодня + Завтра).
"""

import os, sys, json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/opt')
import site_common
from generate_site_legacy import (
    _load_live_scores, get_upcoming, get_tvguide_section,
    _render_match_card, _team_logo, escape
)

UTC = timezone.utc
MOW = timedelta(hours=3)


def generate_schedule(output_path='/var/www/sport/schedule.html'):
    now = datetime.now(UTC) + MOW
    now_str = now.strftime('%d.%m.%Y %H:%M')
    today_date = now.strftime('%d.%m.%Y')
    next_date = (now + timedelta(days=1)).strftime('%d.%m.%Y')

    live_lookup = _load_live_scores()

    # ── Сегодня ──
    today_matches = []
    seen_today = set()

    if live_lookup:
        for key, info in live_lookup.items():
            if info.get('status') in ('live', 'upcoming'):
                parts = key.split('||', 2)
                if len(parts) == 3:
                    league, home, away = parts
                    dedup = (league, home, away)
                    if dedup not in seen_today:
                        seen_today.add(dedup)
                        time_str = info.get('match_time', '') or info.get('status_detail', '')
                        today_matches.append({
                            'sport': info.get('sport', 'football'),
                            'league': league,
                            'home': home,
                            'away': away,
                            'time': time_str,
                        })

    upcoming_today = get_upcoming(target_date=today_date)
    for m in upcoming_today:
        dedup = (m.get('league', ''), m.get('home', ''), m.get('away', ''))
        if dedup not in seen_today:
            seen_today.add(dedup)
            today_matches.append(m)

    # ── Завтра ──
    upcoming_matches = get_upcoming(target_date=next_date)

    # ── ТВ-гид ──
    tvguide_rows = get_tvguide_section()

    # ── Прогнозы ──
    predictions_by_match = {}
    pred_path = '/opt/predictions_data.json'
    if os.path.exists(pred_path):
        try:
            with open(pred_path, encoding='utf-8') as f:
                pred_data = json.load(f)
            for p in pred_data.get('predictions', []):
                key = (p.get('league', ''), p.get('home', ''), p.get('away', ''))
                predictions_by_match[key] = p
        except:
            pass

    pred_json_escaped = json.dumps(
        {k[0] + '||' + k[1] + '||' + k[2]: {
            **v,
            'home_logo': _team_logo(k[1]),
            'away_logo': _team_logo(k[2]),
        } for k, v in predictions_by_match.items()},
        ensure_ascii=False, default=str
    )

    # ── Рендер ──
    def section_matches(matches, show_predictions=True):
        html = '<div class="card-grid">'
        prev_sport = ''
        for m in matches:
            if m.get('sport') == 'tennis' and m.get('home', '') == 'TBD' and m.get('away', '') == 'TBD':
                continue
            league = m.get('league', '')
            if league != prev_sport:
                html += site_common.section_header(league, m.get('sport', 'football'))
                prev_sport = league
            html += _render_match_card(m, live_lookup, predictions_by_match,
                                        site_common.LOGO_LEAGUES, show_predictions)
        html += '</div>'
        return html

    today_html = section_matches(today_matches, show_predictions=True)
    upcoming_html = section_matches(upcoming_matches, show_predictions=True)

    tv_html = ''
    if tvguide_rows:
        tv_html = f'''
        <div class="section-title">📺 Матч ТВ — программа</div>
        <table class="compact-table">{tvguide_rows}</table>
        <div class="source-note">Источник: matchtv.ru</div>'''

    # Сборка
    html = site_common.page_header('Расписание', 'schedule', now_str)

    html += f'''
    <div class="section-title">📅 Сегодня — {today_date}</div>
    {today_html}
    {'' if today_html else '<p style="color:#666;font-size:14px">Нет данных на сегодня.</p>'}

    <div class="section-title">📅 Завтра — {next_date}</div>
    {upcoming_html}
    {'' if upcoming_html else '<p style="color:#666;font-size:14px">Нет данных на ближайшее время.</p>'}

    {tv_html}'''

    # JS автообновления live-счетов
    live_poll_js = '''
<script>
// ─── Live score auto-refresh ─────────────────────────────────────
(function() {
    setInterval(function() {
        fetch('/live_scores.json')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var matches = data.matches || {};
                var cards = document.querySelectorAll('.up-card:not(.finished)');
                cards.forEach(function(card) {
                    var key = card.getAttribute('data-match-key');
                    if (!key) return;
                    var info = matches[key];
                    if (!info) return;

                    var scoreEl = card.querySelector('.up-v1-score');
                    var badgeEl = card.querySelector('.up-v1-live-badge');

                    // Обновляем счёт
                    if (info.score && scoreEl) {
                        scoreEl.textContent = info.score;
                    }

                    // Обновляем статус
                    if (info.status === 'live') {
                        if (!badgeEl) {
                            var right = card.querySelector('.up-v1-right');
                            if (right) {
                                var badge = document.createElement('div');
                                badge.className = 'up-v1-live-badge';
                                badge.textContent = 'LIVE';
                                right.insertBefore(badge, right.firstChild);
                            }
                        }
                    } else if (info.status === 'finished') {
                        card.style.opacity = '0.65';
                        if (badgeEl) badgeEl.remove();
                        if (scoreEl) scoreEl.classList.add('finished');
                    }
                });
            })
            .catch(function() {});
    }, 30000);
})();
</script>'''

    html += site_common.page_footer()
    html = html.replace('JS_PLACEHOLDER', site_common.page_script('{}', pred_json_escaped) + live_poll_js)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f'✅ Расписание (сегодня: {len(today_matches)}, завтра: {len(upcoming_matches)}): {output_path}')
    return len(today_matches), len(upcoming_matches)


if __name__ == '__main__':
    generate_schedule()
