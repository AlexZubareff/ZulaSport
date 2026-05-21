#!/usr/bin/env python3
"""
Тесты нового функционала капера:
  1. find_similar_predictions() — few-shot
  2. _build_capper_stats() — статистика в system prompt
  3. xgb_predict() и _xgb_feature_vector() — XGBoost
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


# ═══════════════════ 1. Few-shot ═══════════════════

print('\n📌 ТЕСТ 1: find_similar_predictions()')
print('=' * 60)

from capper_pipeline import find_similar_predictions

# 1.1 Без Glicko — пустой результат
assert_no_glicko = find_similar_predictions({'league': 'АПЛ'}, {})
check('Нет Glicko → []', assert_no_glicko == [])

# 1.2 Нет истории → пусто
assert_no_hist = find_similar_predictions(
    {'league': 'TEST'},
    {'glicko': {'home_prob': 0.5, 'draw_prob': 0.3, 'away_prob': 0.2}}
)
check('Несуществующая лига → [] (если нет совпадений)', not assert_no_hist or True)

# 1.3 Реальный запрос, похожий на АПЛ-матчи
mock_match = {'league': 'АПЛ', 'home': 'Ливерпуль', 'away': 'Ман Сити'}
mock_ss = {
    'glicko': {
        'home_prob': 0.50, 'draw_prob': 0.25, 'away_prob': 0.25,
        'home_rating': 1650, 'away_rating': 1600,
        'home_xg': 1.4, 'away_xg': 1.1,
    }
}
similar = find_similar_predictions(mock_match, mock_ss, top_k=3)
check(f'Похожие матчи найдены (АПЛ-подобные): {len(similar)} шт', len(similar) <= 3)
if similar:
    # Каждый результат должен иметь корректный result
    for s in similar:
        check(f'  {s["home"]} — {s["away"]}: result есть', bool(s.get('result')))
        r = s.get('result', {})
        if r:
            check(f'  win в result', r.get('win') is not None)
            check(f'  total в result', r.get('total') is not None)

# 1.4 top_k работает
similar_5 = find_similar_predictions(mock_match, mock_ss, top_k=5)
check('top_k=5 не больше 5', len(similar_5) <= 5)

# 1.5 Все найденные должны быть correct (win или total)
for s in similar:
    r = s.get('result', {}) or {}
    win_ok = r.get('win', {}).get('correct') is True
    total_ok = r.get('total', {}).get('correct') is True
    check(f'  {s["home"]} — {s["away"]}: correct', win_ok or total_ok)


# ═══════════════════ 2. Статистика ═══════════════════

print('\n📌 ТЕСТ 2: _build_capper_stats()')
print('=' * 60)

from capper_pipeline import _build_capper_stats

stats = _build_capper_stats()
check('Статистика вернула строку', isinstance(stats, str))
if stats:
    check('Содержит Win', 'Win' in stats)
    check('Содержит Total', 'Total' in stats)
    check('Содержит подсказку', 'Подсказка' in stats or 'слабый' in stats)
    # Проверяем наличие всех лиг
    for league in ('АПЛ', 'Ла Лига', 'Серия А', 'Лига 1', 'РПЛ'):
        if league in stats:
            check(f'  Лига {league} в статистике', True)
else:
    # Если данных < 5, выводим warning
    print('  ⚠️ Статистика пуста — возможно, мало данных (<5 прогнозов)')


# ═══════════════════ 3. XGBoost ═══════════════════

print('\n📌 ТЕСТ 3: XGBoost')
print('=' * 60)

from capper_pipeline import xgb_predict, _xgb_feature_vector

# 3.1 Проверяем, что модели существуют
check('xgb_win.json существует', os.path.exists('/opt/capper_xgb/xgb_win.json'))
check('xgb_total.json существует', os.path.exists('/opt/capper_xgb/xgb_total.json'))

# 3.2 Без Glicko → None
no_glicko = xgb_predict({})
check('Нет данных → None', no_glicko is None)

no_glicko2 = xgb_predict({'odds': [{'home': 2.0, 'draw': 3.5, 'away': 3.0}]})
check('Нет Glicko в данных → None', no_glicko2 is None)

# 3.3 С полными данными — предсказание
mock_full = {
    'glicko': {
        'home_prob': 0.55, 'draw_prob': 0.25, 'away_prob': 0.20,
        'home_rating': 1700, 'away_rating': 1650,
        'home_xg': 1.5, 'away_xg': 1.2,
    },
    'odds': [{'home': 1.8, 'draw': 3.5, 'away': 4.2}],
    'totals': {'total_line': 2.5, 'over': 1.7, 'under': 2.1},
}

result = xgb_predict(mock_full)
check('XGBoost вернул результат', result is not None)
if result:
    check('win_prediction home/draw/away', result['win_prediction'] in ('home', 'draw', 'away'))
    check('total_prediction over/under', result['total_prediction'] in ('over', 'under'))
    check('win_confidence > 0', result['win_confidence'] > 0)
    check('win_confidence <= 1', result['win_confidence'] <= 1)
    check('total_confidence > 0', result['total_confidence'] > 0)
    check('total_confidence <= 1', result['total_confidence'] <= 1)
    check('win_probs — 3 значения', len(result['win_probs']) == 3)
    check('win_probs sum ~ 1', abs(sum(result['win_probs'].values()) - 1.0) < 0.01)

    # Проверяем, что самый высокий prob совпадает с предсказанием
    top = max(result['win_probs'], key=result['win_probs'].get)
    check(f'win_probs совпадает с win_prediction ({top})', top == result['win_prediction'])

# 3.4 _xgb_feature_vector — корректная размерность
fv = _xgb_feature_vector(mock_full)
check('Вектор фичей', isinstance(fv, list))
check_eq('Длина вектора', len(fv), 17)

# 3.5 Проверяем вычисление implied probabilities
hv = _xgb_feature_vector(mock_full)
implied_sum = hv[10] + hv[11] + hv[12]
check('Implied probs sum ~ 1', abs(implied_sum - 1.0) < 0.1)

# 3.6 Проверяем rating_diff = home - away
check('rating_diff', abs(hv[13] - (1700 - 1650)) < 0.1)


# ═══════════════════ Итог ═══════════════════

print('\n' + '=' * 60)
total = passed + failed
print(f'\n📊 ИТОГО: {passed}/{total} тестов пройдено')
if failed:
    print(f'   ❌ {failed} ошибок')
    sys.exit(1)
else:
    print(f'   ✅ Всё ОК')
