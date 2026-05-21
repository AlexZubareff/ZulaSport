#!/usr/bin/env python3
"""
Тесты интеграции с БД: db.py, миграции, сайт.

Проверяет:
  1. db.py — базовые функции (get_queue, get_stats, find_similar, team_resolve)
  2. Миграции — данные перенесены корректно
  3. Сайт — генерация страниц не падает
  4. Интеграция — capper_pipeline читает/пишет через БД
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

def check_eq(name, got, expected, detail=''):
    global passed, failed
    if got == expected:
        print(f'  ✅ {name}')
        passed += 1
    else:
        print(f'  ❌ {name} — ожидалось {expected!r}, получено {got!r}  {detail}')
        failed += 1

print('🧪 ТЕСТЫ ИНТЕГРАЦИИ С БД')
print('=' * 60)


# ═══════════════════ 1. db.py ═══════════════════

print('\n📌 ТЕСТ 1: db.py — базовые функции')
print('-' * 40)

import db

# 1.1 get_stats
stats = db.get_stats()
check('get_stats() вернул dict', isinstance(stats, dict))
check('total_predictions >= 0', stats.get('total_predictions', -1) >= 0)
check('win в stats', 'win' in stats)
check('total в stats', 'total' in stats)
check('by_league в stats', 'by_league' in stats)

# 1.2 get_queue
queue = db.get_queue()
check('get_queue() вернул list', isinstance(queue, list))
if queue:
    q = queue[0]
    check('queue[0] имеет home', bool(q.get('home')))
    check('queue[0] имеет league', bool(q.get('league')))
    check('queue[0] статус upcoming', q.get('status') == 'upcoming')

# 1.3 get_queue с фильтром по лиге
if queue:
    leagues = set(q['league'] for q in queue)
    if leagues:
        some_league = list(leagues)[0]
        filtered = db.get_queue(league=some_league)
        check(f'get_queue(league={some_league}) работает', len(filtered) > 0)
        check(f'все матчи {some_league}', all(q['league'] == some_league for q in filtered))

# 1.4 get_history
history = db.get_history()
check('get_history() вернул list', isinstance(history, list))

# 1.5 find_similar
similar = db.find_similar(0.5, 0.25, 0.25)
check('find_similar() вернул list', isinstance(similar, list))
check('top_k работает', len(similar) <= 3)

# 1.6 find_similar с лигой
if similar:
    similar_league = db.find_similar(0.5, 0.25, 0.25, league='АПЛ')
    check('find_similar с лигой', isinstance(similar_league, list))

# 1.7 team_resolve
chelsea = db.team_resolve('Челси')
check('team_resolve(Челси) находит команду', chelsea is not None and 'id' in chelsea)
if chelsea:
    check('team_resolve имеет canonical_name', bool(chelsea.get('canonical_name')))

# 1.8 team_resolve по алиасу
city = db.team_resolve('manchester city')
check('team_resolve(manchester city) через алиас', city is not None)

# 1.9 get_matches
matches = db.get_matches()
check('get_matches() вернул list', isinstance(matches, list))

# 1.10 get_matches с фильтрами
if matches:
    today_matches = db.get_matches(status='scheduled')
    check('get_matches(status=scheduled)', isinstance(today_matches, list))

# 1.11 execute_one
row = db.execute_one("SELECT COUNT(*) AS c FROM predictions")
check('execute_one возвращает строку', row is not None and 'c' in row)
check('predictions count', isinstance(row['c'], int))

# 1.12 count_training
cnt = db.count_training()
check('count_training()', isinstance(cnt, int) and cnt >= 0)

# 1.13 model_versions
ver = db.get_active_model('win')
check('get_active_model(win)', ver is None or 'model_path' in ver)


# ═══════════════════ 2. Миграции ═══════════════════

print('\n📌 ТЕСТ 2: Данные перенесены корректно')
print('-' * 40)

# 2.1 Таблицы существуют
tables = [r['table_name'] for r in db.execute(
    "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
)]
for t in ['predictions', 'training_data', 'model_versions', 'teams', 'team_aliases', 'matches']:
    check(f'Таблица {t} существует', t in tables)

# 2.2 Прогнозы в БД
check('predictions не пуста', stats['total_predictions'] >= 3)

# 2.3 Команды
cnt = db.execute_one("SELECT COUNT(*) AS c FROM teams")['c']
check('teams не пуста (>=190)', cnt >= 190)

cnt_aliases = db.execute_one("SELECT COUNT(*) AS c FROM team_aliases")['c']
check('team_aliases не пуста (>=200)', cnt_aliases >= 200)

# 2.4 Матчи
cnt = db.execute_one("SELECT COUNT(*) AS c FROM matches")['c']
check('matches не пуста (>=16)', cnt >= 16)

# 2.5 Логотипы
cnt = db.execute_one("SELECT COUNT(*) AS c FROM teams WHERE logo_url IS NOT NULL AND logo_url != ''")['c']
check('есть команды с логотипами', cnt > 0)

# 2.6 name_en
cnt = db.execute_one("SELECT COUNT(*) AS c FROM teams WHERE name_en IS NOT NULL")['c']
check('есть команды с name_en', cnt > 0)

# 2.7 training_data
cnt = db.count_training()
check('training_data не пуста (>=1000)', cnt >= 1000)

# 2.8 match_ref у прогнозов
linked = db.execute("SELECT COUNT(*) AS c FROM predictions WHERE match_ref IS NOT NULL")
check('есть прогнозы, привязанные к матчам', linked[0]['c'] >= 2)

# 2.9 home_team_id / away_team_id
linked_teams = db.execute("SELECT COUNT(*) AS c FROM predictions WHERE home_team_id IS NOT NULL AND away_team_id IS NOT NULL")
check('есть прогнозы, привязанные к командам', linked_teams[0]['c'] >= 3)


# ═══════════════════ 3. Сайт ═══════════════════

print('\n📌 ТЕСТ 3: Генерация страниц сайта')
print('-' * 40)

from site_schedule import generate_schedule
from site_predictions import generate_predictions
from site_results import generate_results

# 3.1 schedule
sched = generate_schedule('/tmp/test_schedule.html')
check('schedule сгенерирован', os.path.getsize('/tmp/test_schedule.html') > 1000)
check('schedule вернул кортеж', isinstance(sched, tuple))
check('schedule: сегодня > 0', sched[0] > 0)

# 3.2 predictions
pred = generate_predictions('/tmp/test_predictions.html')
check('predictions сгенерирован', os.path.getsize('/tmp/test_predictions.html') > 1000)
check('predictions вернул число', isinstance(pred, int))
check('predictions: > 0', pred > 0)

# 3.3 results
res = generate_results('/tmp/test_results.html')
check('results сгенерирован', os.path.getsize('/tmp/test_results.html') > 1000)
check('results вернул bool/int', res is not None)

# 3.4 HTML валиден
for f in ['/tmp/test_schedule.html', '/tmp/test_predictions.html', '/tmp/test_results.html']:
    with open(f) as fh:
        html = fh.read()
    name = os.path.basename(f)
    check(f'{name}: закрывающий </html> есть', '</html>' in html)
    check(f'{name}: есть nav', '<div class="nav">' in html)

# 3.5 Страницы содержат данные (не пустые)
with open('/tmp/test_predictions.html') as f:
    html = f.read()
    check('predictions содержит up-card', 'up-card' in html)

with open('/tmp/test_schedule.html') as f:
    html = f.read()
    check('schedule содержит up-card', 'up-card' in html)

with open('/tmp/test_results.html') as f:
    html = f.read()
    check('results содержит карточки', 'up-card' in html or 'card-grid' in html)


# ═══════════════════ 4. Capper pipeline ═══════════════════

print('\n📌 ТЕСТ 4: Интеграция capper_pipeline + БД')
print('-' * 40)

from capper_pipeline import _build_capper_stats, find_similar_predictions

# 4.1 Статистика из БД
stats_block = _build_capper_stats()
check('_build_capper_stats из БД', isinstance(stats_block, str))

# 4.2 Few-shot из БД
mock_match = {'league': 'АПЛ', 'home': 'test', 'away': 'test'}
mock_ss = {
    'glicko': {
        'home_prob': 0.5, 'draw_prob': 0.25, 'away_prob': 0.25,
        'home_rating': 1500, 'away_rating': 1500,
        'home_xg': 1.2, 'away_xg': 1.2,
    },
}
similar = find_similar_predictions(mock_match, mock_ss)
check('find_similar_predictions через БД', isinstance(similar, list))


# ═══════════════════ 5. Тестовые данные в БД ═══════════════════

print('\n📌 ТЕСТ 5: Дедупликация и ON CONFLICT')
print('-' * 40)

# 5.1 Повторное сохранение того же прогноза не создаёт дубль
before = db.execute_one("SELECT COUNT(*) AS c FROM predictions")['c']
p = db.get_queue()
if p:
    first = dict(p[0])
    db.save_prediction(first)
    after = db.execute_one("SELECT COUNT(*) AS c FROM predictions")['c']
    check('save_prediction не дублирует', after == before)


# ═══════════════════ Итог ═══════════════════

print(f'\n{"=" * 60}')
total = passed + failed
print(f'\n📊 ИТОГО: {passed}/{total} тестов пройдено')
if failed:
    print(f'   ❌ {failed} ошибок')
    sys.exit(1)
else:
    print(f'   ✅ Всё ОК')
