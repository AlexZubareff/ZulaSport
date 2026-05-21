"""
Тест очереди прогнозов (evaluate_predictions.py → predictions_history.json).

Проверяет:
1. Парсинг счёта и исходов
2. Матчинг прогнозов с результатами
3. Перенос из очереди в историю
4. Удаление оценённых из очереди
5. Дедупликация
6. Пересчёт сводки
"""

import os, sys, json, pytest
from unittest.mock import patch

sys.path.insert(0, '/opt')

from evaluate_predictions import parse_score, result_outcome
from evaluate_predictions import predicted_outcome, predicted_total
from evaluate_predictions import actual_total_outcome, total_goals, compute_result


# ─── Парсинг счёта ──────────────────────────────────────────────────

class TestScoreParsing:
    def test_football(self):
        assert parse_score('4:2') == (4, 2)
        assert parse_score('0:0') == (0, 0)
    def test_tennis(self):
        assert parse_score('1-6 1-6') == (1, 6)
    def test_empty(self):
        assert parse_score('') == (None, None)
        assert parse_score(None) == (None, None)


# ─── Исход (П1/Х/П2) ────────────────────────────────────────────────

class TestOutcome:
    def test_home_win(self):
        assert result_outcome('3:1') == 'home'
    def test_away_win(self):
        assert result_outcome('0:2') == 'away'
    def test_draw(self):
        assert result_outcome('2:2') == 'draw'


# ─── Glicko ─────────────────────────────────────────────────────────

class TestPredictedOutcome:
    def test_home(self):
        o, c = predicted_outcome({'glicko': {'home_prob': .6, 'draw_prob': .2, 'away_prob': .2}})
        assert o == 'home' and round(c, 1) == .6
    def test_no_glicko(self):
        assert predicted_outcome({}) == (None, None)


# ─── Total ───────────────────────────────────────────────────────────

class TestTotal:
    def test_total_goals(self):
        assert total_goals('3:1') == 4
    def test_recommend_over(self):
        rec, line = predicted_total({'totals': {'total_line': 2.5, 'over': 1.7, 'under': 2.1}})
        assert rec == 'over'
    def test_recommend_under(self):
        rec, line = predicted_total({'totals': {'total_line': 2.5, 'over': 2.1, 'under': 1.7}})
        assert rec == 'under'
    def test_actual_over(self):
        assert actual_total_outcome('3:1', 2.5) == 'over'
    def test_no_totals(self):
        assert predicted_total({}) == (None, None)


# ─── Compute result ─────────────────────────────────────────────────

class TestComputeResult:
    def test_win_correct_total_correct(self):
        pred = {
            'glicko': {'home_prob': .6, 'draw_prob': .2, 'away_prob': .2},
            'totals': {'total_line': 2.5, 'over': 1.7, 'under': 2.1},
        }
        r = compute_result(pred, '3:0')
        assert r['win']['correct'] is True
        assert r['total']['correct'] is True  # 3 > 2.5 = over

    def test_win_incorrect_total_incorrect(self):
        pred = {
            'glicko': {'home_prob': .6, 'draw_prob': .2, 'away_prob': .2},
            'totals': {'total_line': 2.5, 'over': 1.7, 'under': 2.1},
        }
        r = compute_result(pred, '0:2')
        assert r['win']['correct'] is False  # predicted home, actual away
        assert r['total']['correct'] is False  # 2 < 2.5 = under, predicted over

    def test_draw_predicted_draw_actual(self):
        pred = {
            'glicko': {'home_prob': .2, 'draw_prob': .6, 'away_prob': .2},
            'totals': {'total_line': 2.5, 'over': 1.7, 'under': 2.1},
        }
        r = compute_result(pred, '1:1')
        assert r['win']['correct'] is True
        assert r['total']['correct'] is False  # 2 < 2.5

    def test_no_score_returns_none(self):
        pred = {'glicko': {'home_prob': .5, 'draw_prob': .3, 'away_prob': .2}}
        assert compute_result(pred, None) is None
        assert compute_result(pred, '') is None


# ─── Полный цикл ────────────────────────────────────────────────────
# Хелпер для подмены путей


def _run_eval(tmp_path, queue, live_scores=None, daily_results=None):
    """Подменить пути evaluate и запустить. Возвращает (history, queue_after)."""
    import importlib, evaluate_predictions as ep
    importlib.reload(ep)

    qpath = str(tmp_path / 'queue.json')
    hpath = str(tmp_path / 'history.json')
    lpath = str(tmp_path / 'live.json')
    rpath = str(tmp_path / 'results.json')

    save_json(qpath, {'predictions': queue})
    save_json(hpath, {})
    save_json(lpath, {'matches': live_scores or {}})
    save_json(rpath, {'results': daily_results or []})

    _oq, _oh, _ol, _or = ep.PRED_PATH, ep.HISTORY_PATH, ep.LIVE_PATH, ep.RESULTS_PATH
    ep.PRED_PATH, ep.HISTORY_PATH, ep.LIVE_PATH, ep.RESULTS_PATH = qpath, hpath, lpath, rpath
    with patch('evaluate_predictions._DB_AVAILABLE', False):
        ep.evaluate()
    ep.PRED_PATH, ep.HISTORY_PATH, ep.LIVE_PATH, ep.RESULTS_PATH = _oq, _oh, _ol, _or

    history = json.load(open(hpath)) if os.path.getsize(hpath) > 2 else {'predictions': [], 'summary': {}}
    queue_after = json.load(open(qpath)).get('predictions', []) if os.path.exists(qpath) else []

    return history, queue_after


def save_json(p, d):
    with open(p, 'w') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def _make_pred(league, home, away, **kw):
    base = {
        'home': home, 'away': away, 'league': league,
        'time': '17:00', 'game_id': 1,
        'glicko': {'home_prob': .6, 'draw_prob': .2, 'away_prob': .2,
                   'home_rating': 1600, 'away_rating': 1500,
                   'home_xg': 1, 'away_xg': 0.5},
        'totals': {'total_line': 2.5, 'over': 1.7, 'under': 2.1},
        'odds': {}, 'prediction': f'{home} выиграет',
    }
    base.update(kw)
    return base


class TestEvaluateFlow:
    def test_simple_evaluation(self, tmp_path):
        """Прогноз с результатом → уходит в историю, из очереди удаляется."""
        pred = _make_pred('АПЛ', 'Team A', 'Team B')
        live = {'АПЛ||Team A||Team B': {'status': 'finished', 'score': '2:0',
                                         'home': 'Team A', 'away': 'Team B', 'league': 'АПЛ'}}

        history, queue_after = _run_eval(tmp_path, [pred], live_scores=live)

        assert len(history['predictions']) == 1
        assert history['predictions'][0]['status'] == 'finished'
        assert history['predictions'][0]['score'] == '2:0'
        assert history['predictions'][0]['result']['win']['correct'] is True
        assert queue_after == [], f"Очередь не пуста: {len(queue_after)}"

    def test_no_score_stays_in_queue(self, tmp_path):
        """Без результата → прогноз остаётся в очереди."""
        pred = _make_pred('АПЛ', 'Team A', 'Team B')

        history, queue_after = _run_eval(tmp_path, [pred], live_scores={})

        assert len(history['predictions']) == 0
        assert len(queue_after) == 1

    def test_daily_results_source(self, tmp_path):
        """Прогноз матчится с daily_results (не только live)."""
        pred = _make_pred('АПЛ', 'Team A', 'Team B')
        daily = [{'sport': 'football', 'league': 'АПЛ', 'home': 'Team A', 'away': 'Team B', 'score': '1:1'}]

        history, queue_after = _run_eval(tmp_path, [pred], daily_results=daily)

        assert len(history['predictions']) == 1
        assert history['predictions'][0]['score'] == '1:1'

    def test_multiple_in_queue_partial_evaluation(self, tmp_path):
        """
        В очереди 2 прогноза. У одного есть результат, у другого нет.
        Первый уходит в историю, второй остаётся.
        """
        pred1 = _make_pred('АПЛ', 'Team A', 'Team B')
        pred2 = _make_pred('Ла Лига', 'Team C', 'Team D')
        live = {'АПЛ||Team A||Team B': {'status': 'finished', 'score': '2:0',
                                        'home': 'Team A', 'away': 'Team B', 'league': 'АПЛ'}}

        history, queue_after = _run_eval(tmp_path, [pred1, pred2], live_scores=live)

        assert len(history['predictions']) == 1
        assert len(queue_after) == 1
        assert queue_after[0]['home'] == 'Team C'

    def test_dedup_in_history(self, tmp_path):
        """
        Повторный прогон с тем же результатом не создаёт дубль в истории.
        Очередь остаётся пустой.
        """
        pred = _make_pred('АПЛ', 'Team A', 'Team B')
        live = {'АПЛ||Team A||Team B': {'status': 'finished', 'score': '2:0',
                                        'home': 'Team A', 'away': 'Team B', 'league': 'АПЛ'}}

        import importlib, evaluate_predictions as ep
        importlib.reload(ep)

        qpath = str(tmp_path / 'queue2.json')
        hpath = str(tmp_path / 'history2.json')
        lpath = str(tmp_path / 'live2.json')
        rpath = str(tmp_path / 'results2.json')

        save_json(qpath, {'predictions': [pred]})
        save_json(hpath, {})
        save_json(lpath, {'matches': live})
        save_json(rpath, {'results': []})

        _oq, _oh, _ol, _or = ep.PRED_PATH, ep.HISTORY_PATH, ep.LIVE_PATH, ep.RESULTS_PATH
        ep.PRED_PATH, ep.HISTORY_PATH, ep.LIVE_PATH, ep.RESULTS_PATH = qpath, hpath, lpath, rpath

        with patch('evaluate_predictions._DB_AVAILABLE', False):
            # Первый прогон
            ep.evaluate()

            # Второй прогон — те же данные, тот же результат
            ep.evaluate()
        ep.PRED_PATH, ep.HISTORY_PATH, ep.LIVE_PATH, ep.RESULTS_PATH = _oq, _oh, _ol, _or

        history = json.load(open(hpath))
        assert len(history['predictions']) == 1, f"Дубли в истории: {len(history['predictions'])}"

    def test_summary_accuracy(self, tmp_path):
        """Сводка пересчитывается корректно."""
        p1 = _make_pred('АПЛ', 'A', 'B')  # home predicted, 2:0 → home → win correct
        p2 = _make_pred('Ла Лига', 'C', 'D', glicko={'home_prob': .2, 'draw_prob': .3, 'away_prob': .5})
        # away predicted, 0:1 → away → win correct

        live = {
            'АПЛ||A||B': {'status': 'finished', 'score': '2:0', 'home': 'A', 'away': 'B', 'league': 'АПЛ'},
            'Ла Лига||C||D': {'status': 'finished', 'score': '0:1', 'home': 'C', 'away': 'D', 'league': 'Ла Лига'},
        }

        history, _ = _run_eval(tmp_path, [p1, p2], live_scores=live)

        s = history['summary']
        assert s['total_predictions'] == 2
        assert s['finished'] == 2
        assert s['upcoming'] == 0
        assert s['win']['total'] == 2
        assert s['win']['correct'] == 2

    def test_live_status_in_progress_skipped(self, tmp_path):
        """Live-матчи без finished не оцениваются (остаются в очереди)."""
        pred = _make_pred('АПЛ', 'Team A', 'Team B')
        live = {'АПЛ||Team A||Team B': {'status': 'live', 'score': '1:0',
                                        'home': 'Team A', 'away': 'Team B', 'league': 'АПЛ'}}

        history, queue_after = _run_eval(tmp_path, [pred], live_scores=live)

        assert len(history['predictions']) == 0
        assert len(queue_after) == 1, "Live-матч не должен оцениваться"

    def test_clean_queue_removed(self, tmp_path):
        """Когда вся очередь оценена — файл удаляется."""
        pred = _make_pred('АПЛ', 'A', 'B')
        live = {'АПЛ||A||B': {'status': 'finished', 'score': '1:0',
                              'home': 'A', 'away': 'B', 'league': 'АПЛ'}}

        _, queue_after = _run_eval(tmp_path, [pred], live_scores=live)
        assert len(queue_after) == 0
