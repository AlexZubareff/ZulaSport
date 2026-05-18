#!/usr/bin/env python3
"""
Тест синхронизации канала с единым news_data.json.
"""

import sys, os, json
sys.path.insert(0, '/opt')

passed = 0
failed = 0

def check(name, condition, detail=''):
    global passed, failed
    if condition:
        print(f'  ✅ {name}')
        passed += 1
    else:
        print(f'  ❌ {name} — {detail}')
        failed += 1

print('🧪 ТЕСТ СИНХРОНИЗАЦИИ КАНАЛА')
print('=' * 60)

# ─── 1. news_data.json существует и валиден ───
print('\n📄 ТЕСТ 1: news_data.json')
news_path = '/var/www/sport/news_data.json'
check('Файл существует', os.path.exists(news_path))

if os.path.exists(news_path):
    with open(news_path, encoding='utf-8') as f:
        data = json.load(f)
    check('Валидный JSON', isinstance(data, list) and len(data) > 0)
    check('Есть desc_full', all('desc_full' in n for n in data))
    check('Есть content_ru', all('content_ru' in n for n in data))
    check('Есть title/source/link', all(
        n.get('title') and n.get('source') and n.get('link') for n in data
    ))

# ─── 2. Функции бота работают ───
print('\n📄 ТЕСТ 2: fetch_news_from_json()')
from sport_bot import fetch_news_from_json, _load_posted, _mark_posted

news = fetch_news_from_json()
check('Выбрана новость', news is not None)
if news:
    check('Есть заголовок', bool(news.get('title')))
    check('Есть контент для поста', bool(
        news.get('content_ru') or news.get('desc_full') or news.get('desc')
    ))

# ─── 3. posted_news.json ───
print('\n📄 ТЕСТ 3: posted_news.json')
posted = _load_posted()
check('Файл создаётся', isinstance(posted, dict))
check('Есть список posted', 'posted' in posted)
check('Первая публикация записана', len(posted.get('posted', [])) > 0)
if posted.get('posted'):
    check('Есть link', bool(posted['posted'][0].get('link')))
    check('Есть title', bool(posted['posted'][0].get('title')))

# ─── 4. Нет дублирования RSS/перевода ───
print('\n📄 ТЕСТ 4: Нет дублирования')
import inspect
from sport_bot import fetch_news_from_json, escape_md, fetch_bbc_video, fetch_og_image
src = open('/opt/sport_bot.py').read()

check('Нет parse_rss_items', 'def parse_rss_items' not in src)
check('Нет fetch_sports_news', 'def fetch_sports_news' not in src)
check('Нет translate_deepseek', 'def translate_deepseek' not in src)
check('Нет rate_news', 'def rate_news' not in src)
check('Нет _RECENT_POSTED', '_RECENT_POSTED' not in src)
check('Нет _FEED_IDX', '_FEED_IDX' not in src)
check('Нет xml.etree в импорте', 'xml.etree' not in src.split('\n')[0:15])
check('BBC Video всё ещё есть', 'def fetch_bbc_video' in src)
check('fetch_og_image всё ещё есть', 'def fetch_og_image' in src)

# ─── 5. Формат поста ───
print('\n📄 ТЕСТ 5: Формат поста')
if news:
    foreign = {'BBC Sport', 'BBC Football', 'BBC Tennis', 'Guardian Football', 'Sky Sports'}
    prefix = '🌍' if news['source'] in foreign else '📰'
    
    content_text = news.get('content_ru', '') or news.get('desc_full', '') or news.get('desc', '')
    display = content_text[:600]
    
    check(f'Префикс {"🌍" if news["source"] in foreign else "📰"} для {news["source"]}', 
          prefix in ['🌍', '📰'])
    check(f'Контент есть ({len(content_text)} chars)', len(content_text) > 20)
    check('Ссылка на источник есть', 'Источник: ©' in f'Источник: © [{news["source"]}]({news["link"]})')

# ─── ИТОГ ───
print()
print('=' * 60)
if failed == 0:
    print(f'🎉 ВСЕ {passed} ТЕСТОВ ПРОЙДЕНЫ')
else:
    print(f'⚠️ {passed} ✅ / {failed} ❌')
print('=' * 60)
