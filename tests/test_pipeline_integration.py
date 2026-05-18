#!/usr/bin/env python3
"""
Интеграционный тест пайплайна: capper -> daily_results -> evaluate.

Проверяет, что:
1. Моковые прогнозы находят свои счета в моковых результатах
2. team_mapper правильно связывает разные варианты имён
3. evaluate корректно обновляет историю
"""

import os, sys, json, tempfile
sys.path.insert(0, '/opt')
import team_mapper
import evaluate_predictions as ep

# ─── Тестовые данные ───────────────────────────────────────────────

MOCK_PREDICTIONS = [
    {
        'home': 'Атлетико',
        'away': 'Жирона',
        'league': 'Ла Лига',
        'time': '19:30',
        'odds': {'home': 1.62, 'draw': 4.2, 'away': 5.25},
        'totals': {'over': 1.62, 'under': 2.20, 'total_line': 2.5},
        'glicko': {'home_prob': 0.55, 'draw_prob': 0.25, 'away_prob': 0.20},
        'generated_at': '2026-05-17T12:00:00',
    },
    {
        'home': 'Manchester City',
        'away': 'Арсенал',
        'league': 'АПЛ',
        'time': '17:00',
        'odds': {'home': 1.40, 'draw': 4.50, 'away': 7.00},
        'totals': {'over': 1.80, 'under': 2.00, 'total_line': 2.5},
        'glicko': {'home_prob': 0.65, 'draw_prob': 0.20, 'away_prob': 0.15},
        'generated_at': '2026-05-17T12:01:00',
    },
    {
        'home': 'Атлетик',
        'away': 'Барселона',
        'league': 'Ла Лига',
        'time': '22:00',
        'odds': {'home': 3.80, 'draw': 3.40, 'away': 2.00},
        'totals': {'over': 1.70, 'under': 2.10, 'total_line': 2.5},
        'glicko': {'home_prob': 0.25, 'draw_prob': 0.28, 'away_prob': 0.47},
        'generated_at': '2026-05-17T12:02:00',
    },
    {
        'home': 'Борнмут',
        'away': 'Бёрнли',
        'league': 'АПЛ',
        'time': '14:30',
        'odds': {'home': 2.10, 'draw': 3.40, 'away': 3.60},
        'totals': {'over': 1.90, 'under': 1.90, 'total_line': 2.5},
        'glicko': {'home_prob': 0.42, 'draw_prob': 0.28, 'away_prob': 0.30},
        'generated_at': '2026-05-17T12:03:00',
    },
]

MOCK_RESULTS = [
    {'sport': 'football', 'league': 'Ла Лига', 'home': 'Атлетико Мадрид', 'away': 'Жирона', 'score': '2:0'},
    {'sport': 'football', 'league': 'АПЛ', 'home': 'Манчестер Сити', 'away': 'Арсенал', 'score': '1:3'},
    {'sport': 'football', 'league': 'Ла Лига', 'home': 'Атлетик', 'away': 'Барселона', 'score': '0:2'},
    {'sport': 'football', 'league': 'АПЛ', 'home': 'Борнмут', 'away': 'Бёрнли', 'score': '2:1'},
]

# ─── Тесты ─────────────────────────────────────────────────────────


def test_team_mapper():
    cases = [
        ('Атлетико', 'Атлетико Мадрид'),
        ('Athletic Bilbao', 'Атлетик'),
        ('Manchester City', 'Манчестер Сити'),
        ('Бёрнли', 'Бёрнли'),
        ('Бернли', 'Бёрнли'),
        ('Арсенал', 'Арсенал'),
        ('Atletico Madrid', 'Атлетико Мадрид'),
    ]
    errors = []
    for inp, expected in cases:
        result, method = team_mapper.resolve(inp)
        if result != expected:
            errors.append('  {} -> {}, expected {} (method: {})'.format(inp, result, expected, method))
    assert not errors, '\n' + '\n'.join(errors)
    print('  OK: team_mapper all mappings correct')


def test_score_lookup_matching():
    """Build lookup like evaluate does, verify predictions find scores."""
    lookup = {}
    for r in MOCK_RESULTS:
        home_canon, _ = team_mapper.resolve(r['home'])
        away_canon, _ = team_mapper.resolve(r['away'])
        lookup[(r['league'], home_canon, away_canon)] = (r['score'], 'finished')

    matches = 0
    for p in MOCK_PREDICTIONS:
        home_canon, _ = team_mapper.resolve(p['home'])
        away_canon, _ = team_mapper.resolve(p['away'])
        key = (p['league'], home_canon, away_canon)
        score = lookup.get(key)
        if score:
            matches += 1
        else:
            print('  MISS: {} - {}'.format(p['home'], p['away']))

    assert matches == len(MOCK_PREDICTIONS), 'Found {}/{} matches'.format(matches, len(MOCK_PREDICTIONS))
    print('  OK: All {}/{} predictions matched scores'.format(matches, len(MOCK_PREDICTIONS)))


def test_full_evaluate_cycle():
    """Run evaluate with mock data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        old_pred = ep.PRED_PATH
        old_hist = ep.HISTORY_PATH
        old_live = ep.LIVE_PATH
        old_results = ep.RESULTS_PATH

        try:
            ep.PRED_PATH = os.path.join(tmpdir, 'predictions_data.json')
            ep.HISTORY_PATH = os.path.join(tmpdir, 'predictions_history.json')
            ep.LIVE_PATH = os.path.join(tmpdir, 'live_scores_data.json')
            ep.RESULTS_PATH = os.path.join(tmpdir, 'daily_results_data.json')

            ep.save_json(ep.PRED_PATH, {
                'predictions': MOCK_PREDICTIONS,
                'count': len(MOCK_PREDICTIONS),
                'generated_at': '2026-05-17T12:00:00',
            })
            ep.save_json(ep.RESULTS_PATH, {
                'date': '17.05.2026',
                'results': MOCK_RESULTS,
                'generated_at': '2026-05-18T06:00:00',
            })
            ep.save_json(ep.LIVE_PATH, {'updated_at': '2026-05-18T06:00:00', 'matches': {}})
            ep.save_json(ep.HISTORY_PATH, {'predictions': [], 'summary': {}, 'last_updated': None})

            result = ep.evaluate()
            assert result is not None, 'evaluate() returned None'

            summary = result['summary']
            finished_count = summary['finished']
            assert finished_count == 4, 'Expected 4 finished, got {}'.format(finished_count)

            finished = [h for h in result['predictions'] if h['status'] == 'finished']
            assert len(finished) == 4, 'Expected 4 finished in history, got {}'.format(len(finished))

            scores_str = ', '.join(['{} - {}: {}'.format(h['home'], h['away'], h['score']) for h in finished])
            print('  Finished predictions: {}'.format(scores_str))
            print('  Win: {}/{}'.format(summary['win']['correct'], summary['win']['total']))
            print('  Total: {}/{}'.format(summary['total']['correct'], summary['total']['total']))

            queue_data = ep.load_json(ep.PRED_PATH)
            if queue_data:
                qlen = len(queue_data.get('predictions', []))
                assert qlen == 0, 'Queue should be empty, has {} items'.format(qlen)

        finally:
            ep.PRED_PATH = old_pred
            ep.HISTORY_PATH = old_hist
            ep.LIVE_PATH = old_live
            ep.RESULTS_PATH = old_results

    print('  OK: Full evaluate cycle complete')


# ─── Запуск ────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('Pipeline Integration Tests\n')
    tests = [
        ('team_mapper', test_team_mapper),
        ('score lookup matching', test_score_lookup_matching),
        ('full evaluate cycle', test_full_evaluate_cycle),
    ]
    passed = 0
    for name, fn in tests:
        print('Testing {}...'.format(name))
        try:
            fn()
            passed += 1
        except Exception as e:
            print('  FAIL: {}'.format(e))
        print()
    total = len(tests)
    print('=' * 40)
    print('{}/{} passed, {}/{} failed'.format(passed, total, total - passed, total))
    if passed < total:
        sys.exit(1)
