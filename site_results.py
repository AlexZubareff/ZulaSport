#!/usr/bin/env python3
"""
Генератор страницы результатов.
"""

import os, sys, json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/opt')
import site_common
from generate_site_legacy import get_results_text, _load_live_scores, escape

UTC = timezone.utc
MOW = timedelta(hours=3)


def generate_results(output_path='/var/www/sport/results.html'):
    now = datetime.now(UTC) + MOW
    now_str = now.strftime('%d.%m.%Y %H:%M')
    yesterday_date = (now - timedelta(days=1)).strftime('%d.%m.%Y')

    live_lookup = _load_live_scores()
    results_html = get_results_text(live_lookup)

    html = site_common.page_header('Результаты', 'results', now_str)
    html += f'''
    <div class="section-title">📊 Результаты за {yesterday_date}</div>
    {results_html}
    {'' if results_html else '<p style="color:#666;font-size:14px">Нет данных за вчера.</p>'}'''

    html += site_common.page_footer()
    html = html.replace('JS_PLACEHOLDER', site_common.page_script('{}', '{}'))

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f'✅ Результаты: {output_path}')
    return bool(results_html)


if __name__ == '__main__':
    generate_results()
