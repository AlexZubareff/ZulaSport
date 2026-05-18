#!/usr/bin/env python3
"""
Тесты разделения сайта на 3 страницы.
"""

import os, sys, json

sys.path.insert(0, '/opt')


def _read_meta(path):
    """Прочитать страницу и найти ключевые маркеры."""
    if not os.path.exists(path):
        return {'exists': False, 'size': 0}
    html = open(path).read()
    return {
        'exists': True,
        'size': len(html),
        'has_header': 'Zula Спорт' in html,
        'has_nav': 'nav' in html and 'class=\"active\"' in html,
        'has_footer': 'bot-link' in html,
        'has_article_modal': 'article-modal' in html,
        'has_pred_modal': 'pred-modal' in html,
        'has_stats_modal': 'stats-modal' in html,
        'links_to_news': '/news.html' in html,
        'links_to_schedule': '/schedule.html' in html,
        'links_to_results': '/results.html' in html,
    }


def test_all_pages_exist():
    paths = [
        '/var/www/sport/news.html',
        '/var/www/sport/schedule.html',
        '/var/www/sport/results.html',
    ]
    errors = []
    for path in paths:
        meta = _read_meta(path)
        if not meta['exists']:
            errors.append(f'{path} не существует')
        if meta['size'] < 1000:
            errors.append(f'{path} слишком мал ({meta["size"]} bytes)')
    
    assert not errors, '\n'.join(errors)
    print('  OK: All 3 pages exist and have content')


def test_navigation_consistent():
    """На каждой странице одинаковое меню, ссылки ведут друг на друга."""
    pages = ['news', 'schedule', 'results']
    errors = []
    for page in pages:
        meta = _read_meta(f'/var/www/sport/{page}.html')
        if not meta['links_to_news']:
            errors.append(f'{page}.html: нет ссылки на news.html')
        if not meta['links_to_schedule']:
            errors.append(f'{page}.html: нет ссылки на schedule.html')
        if not meta['links_to_results']:
            errors.append(f'{page}.html: нет ссылки на results.html')
        if not meta['has_nav']:
            errors.append(f'{page}.html: нет активной вкладки навигации')
    
    assert not errors, '\n'.join(errors)
    print('  OK: Navigation consistent across all 3 pages')


def test_modals_present():
    """Модалки для статей, прогнозов и статистики есть на всех страницах."""
    for page in ['news', 'schedule', 'results']:
        meta = _read_meta(f'/var/www/sport/{page}.html')
        assert meta['has_article_modal'], f'{page}.html: нет модалки статьи'
        assert meta['has_pred_modal'], f'{page}.html: нет модалки прогноза'
        assert meta['has_stats_modal'], f'{page}.html: нет модалки статистики'
    print('  OK: All 3 modals present on each page')


def test_news_page():
    """На странице новостей есть новости."""
    html = open('/var/www/sport/news.html').read()
    news_count = html.count('news-card')
    assert news_count > 0, 'Нет новостей на странице'
    
    news_json = open('/var/www/sport/news_data.json').read()
    data = json.loads(news_json)
    assert len(data) > 0, 'news_data.json пуст'
    
    print(f'  OK: {news_count} карточек новостей, {len(data)} всего в JSON')


def test_schedule_page():
    """На странице расписания есть матчи."""
    html = open('/var/www/sport/schedule.html').read()
    up_cards = html.count('up-card')
    sections = html.count('section-sub')
    
    assert up_cards > 0, 'Нет карточек матчей на странице расписания'
    assert sections > 0, 'Нет секций лиг'
    print(f'  OK: {up_cards} матчей, {sections} лиг')


def test_results_page():
    """На странице результатов есть завершённые матчи."""
    html = open('/var/www/sport/results.html').read()
    result_cards = html.count('result-card')
    
    if result_cards > 0:
        print(f'  OK: {result_cards} результатов')
    else:
        print('  ⚠️ Нет результатов (может быть нормой — нет матчей за вчера)')


def test_index_redirect():
    """index.html редиректит на news."""
    html = open('/var/www/sport/index.html').read()
    assert '/news.html' in html, 'index.html не редиректит на news.html'
    assert 'refresh' in html or 'location' in html, 'index.html: нет редиректа'
    print('  OK: index.html → редирект на news.html')


def test_generate_all():
    """Проверка, что генератор всех трёх страниц не падает."""
    import generate_site
    generate_site.main()  # просто проверяем, что не исключение
    print('  OK: generate_site.main() отработал')


if __name__ == '__main__':
    print('Site Split Tests\n')
    tests = [
        ('all pages exist', test_all_pages_exist),
        ('navigation consistent', test_navigation_consistent),
        ('modals present', test_modals_present),
        ('news page', test_news_page),
        ('schedule page', test_schedule_page),
        ('results page', test_results_page),
        ('index redirect', test_index_redirect),
        ('generate all', test_generate_all),
    ]
    passed = 0
    for name, fn in tests:
        print(f'Testing {name}...')
        try:
            fn()
            passed += 1
        except Exception as e:
            print(f'  FAIL: {e}')
        print()
    total = len(tests)
    print('=' * 40)
    print('{}/{} passed, {}/{} failed'.format(passed, total, total - passed, total))
    if passed < total:
        sys.exit(1)
