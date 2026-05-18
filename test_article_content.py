#!/usr/bin/env python3
"""
Тест функционала извлечения и отображения полных текстов статей.
Запуск: python3 test_article_content.py
"""

import sys, json, os, re
sys.path.insert(0, '/opt')

# ─── 1. Проверка, что readability работает ────────────────────────
print('=' * 60)
print('🧪 ТЕСТ 1: Импорт readability и extract_article_content')
print('=' * 60)

try:
    from generate_site import extract_article_content, sanitize_content
    print('  ✅ Функции импортированы')
except Exception as e:
    print(f'  ❌ Ошибка импорта: {e}')
    sys.exit(1)

# ─── 2. Проверка извлечения контента с реального URL ──────────────
print()
print('=' * 60)
print('🧪 ТЕСТ 2: Извлечение контстатья (championat)')
print('=' * 60)

url = 'https://www.championat.com/football/news-6469020-kdk-rfs-oshtrafoval-spartak-i-cska-za-ispolzovanie-zritelyami-pirotehniki.html'
content = extract_article_content(url)
content_clean = sanitize_content(content)

if content and len(content) > 500:
    print(f'  ✅ Контент извлечён: {len(content)} chars')
    print(f'  ✅ После очистки: {len(content_clean)} chars')
    # Проверяем, что нет script и style тегов
    if '<script' in content_clean.lower():
        print('  ❌ Остались script теги!')
    else:
        print('  ✅ Нет script тегов')
    # Проверяем наличие осмысленного текста
    text_only = re.sub(r'<[^>]+>', '', content_clean).strip()
    if len(text_only) > 200:
        print(f'  ✅ Осмысленный текст: {len(text_only)} chars')
    else:
        print(f'  ⚠️ Мало текста: {len(text_only)} chars')
else:
    print(f'  ⚠️ Контент пуст или мал ({len(content) if content else 0} chars)')

# ─── 3. Проверка news_data.json ─────────────────────────────────────
print()
print('=' * 60)
print('🧪 ТЕСТ 3: Проверка news_data.json')
print('=' * 60)

news_path = '/var/www/sport/news_data.json'
if not os.path.exists(news_path):
    print(f'  ❌ Файл {news_path} не найден')
    sys.exit(1)

with open(news_path, encoding='utf-8') as f:
    news_data = json.load(f)

print(f'  ✅ Файл загружен, новостей: {len(news_data)}')

# Подсчитываем, сколько статей с контентом
with_content = sum(1 for n in news_data if n.get('content'))
total = len(news_data)
print(f'  ✅ С контентом: {with_content}/{total} ({with_content/total*100:.0f}%)')

# Проверяем, что у каждой статьи есть необходимые поля
required_fields = ['title', 'desc', 'link', 'source', 'time', 'content']
missing = []
for i, n in enumerate(news_data):
    for field in required_fields:
        if field not in n:
            missing.append(f'  [index {i}] нет поля "{field}"')

if missing:
    print(f'  ❌ Ошибки:')
    for m in missing[:5]:
        print(f'    {m}')
else:
    print(f'  ✅ У всех статей есть все обязательные поля')

# ─── 4. Проверка index.html ────────────────────────────────────────
print()
print('=' * 60)
print('🧪 ТЕСТ 4: Проверка index.html')
print('=' * 60)

html_path = '/var/www/sport/index.html'
if not os.path.exists(html_path):
    print(f'  ❌ Файл {html_path} не найден')
    sys.exit(1)

with open(html_path, encoding='utf-8') as f:
    html = f.read()

checks = [
    ('Модалка есть', 'modal-overlay'),
    ('Кнопка закрытия', 'modal-close'),
    ('Контейнер контента', 'modal-body'),
    ('Ссылка на источник', 'modal-source-link'),
    ('Встроенные данные', 'news-data'),
    ('JS функция openArticle', 'function openArticle'),
    ('JS функция closeArticle', 'function closeArticle'),
    ('Закрытие по Escape', 'key === \'Escape\''),
    ('Закрытие по клику на оверлей', 'closeArticle'),
    ('Карточки без href', 'news-card'),
]

all_pass = True
for name, keyword in checks:
    if keyword in html:
        print(f'  ✅ {name}')
    else:
        print(f'  ❌ {name} — не найдено "{keyword}"')
        all_pass = False

# Проверяем, что старые <a href=... target=_blank убраны
old_links = re.findall(r'<a\s+href="https?://[^"]+"\s+class="news-card"', html)
if old_links:
    print(f'  ⚠️ Найдено {len(old_links)} старых ссылок-карточек (<a class="news-card">)')
else:
    print(f'  ✅ Старые прямые ссылки убраны')

# Проверяем data-news-idx
data_idxs = re.findall(r'data-news-idx="(\d+)"', html)
if data_idxs:
    print(f'  ✅ Найдено data-news-idx: {len(data_idxs)} шт (от {min(int(x) for x in data_idxs)} до {max(int(x) for x in data_idxs)})')
else:
    print(f'  ⚠️ data-news-idx не найдены')

# Проверяем встроенный JSON
json_match = re.search(r'<script id="news-data" type="application/json">(.*?)</script>', html, re.DOTALL)
if json_match:
    try:
        embedded = json.loads(json_match.group(1))
        print(f'  ✅ Встроенный JSON: {len(embedded)} статей')
    except json.JSONDecodeError as e:
        print(f'  ❌ Ошибка парсинга встроенного JSON: {e}')
        all_pass = False
else:
    print(f'  ❌ Встроенный JSON не найден')
    all_pass = False

# ─── 5. Размеры ────────────────────────────────────────────────────
print()
print('=' * 60)
print('🧪 ТЕСТ 5: Размеры файлов')
print('=' * 60)

html_size = os.path.getsize(html_path)
json_size = os.path.getsize(news_path)
print(f'  📄 index.html: {html_size:,} bytes ({html_size/1024:.1f} KB)')
print(f'  📄 news_data.json: {json_size:,} bytes ({json_size/1024:.1f} KB)')

if html_size > 500000:
    print(f'  ⚠️ HTML слишком большой (>500 KB)')
elif html_size > 100000:
    print(f'  ✅ Нормальный размер')
else:
    print(f'  ✅ Компактно')

# ─── ИТОГ ──────────────────────────────────────────────────────────
print()
print('=' * 60)
if all_pass:
    print('🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ')
else:
    print('⚠️ НЕКОТОРЫЕ ТЕСТЫ НЕ ПРОЙДЕНЫ')
print('=' * 60)
