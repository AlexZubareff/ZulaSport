#!/usr/bin/env python3
"""
Генератор статического сайта Zula Спорт.
Запускает нужные генераторы по флагу --section.

Использование:
  python3 generate_site.py --section news      → news.html
  python3 generate_site.py --section schedule  → schedule.html
  python3 generate_site.py --section results   → results.html
  python3 generate_site.py --section all       → все три
  python3 generate_site.py                     → все три
"""

import sys, os

sys.path.insert(0, '/opt')


def main():
    section = 'all'
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg in ('--section', '-s') and i + 1 < len(args):
            section = args[i + 1]

    sections = {
        'news': ['news'],
        'schedule': ['schedule'],
        'results': ['results'],
        'predictions': ['predictions'],
        'all': ['news', 'schedule', 'results', 'predictions'],
    }

    to_run = sections.get(section, sections['all'])

    if 'news' in to_run:
        print('=== Новости ===')
        from site_news import generate_news
        generate_news('/var/www/sport/news.html')

    if 'schedule' in to_run:
        print('=== Расписание ===')
        from site_schedule import generate_schedule
        generate_schedule('/var/www/sport/schedule.html')

    if 'results' in to_run:
        print('=== Результаты ===')
        from site_results import generate_results
        generate_results('/var/www/sport/results.html')

    if 'predictions' in to_run:
        print('=== Прогнозы ===')
        from site_predictions import generate_predictions
        generate_predictions('/var/www/sport/predictions.html')

    # Редирект index.html → news.html
    if section == 'all':
        redirect_html = '''<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="0;url=/news.html">
<title>Zula Спорт</title>
</head><body>
<p>Переход на <a href="/news.html">главную страницу</a>...</p>
</body></html>'''
        with open('/var/www/sport/index.html', 'w', encoding='utf-8') as f:
            f.write(redirect_html)
        print('✅ index.html → редирект на /news.html')

    print(f'✅ Секция(и): {", ".join(to_run)}')


if __name__ == '__main__':
    main()
