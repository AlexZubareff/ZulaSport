"""
Тест SSoT: PostgreSQL как первичный источник данных.

Проверяет:
1. evaluate_predictions загружает очередь из БД при доступности
2. evaluate_predictions загружает историю из БД при доступности
3. Fallback на JSON при отсутствии БД
4. Валидация data_schemas при записи в JSON
5. Сохранение прогнозов в БД + JSON
"""

import os, sys, json, pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, '/opt')

import evaluate_predictions as ep


# ═══════════════════════════════════════════════════════════════════
#  Хелперы
# ═══════════════════════════════════════════════════════════════════

def _make_pred(league, home, away, **kw):
    """Создать тестовый прогноз."""
    base = {
        'home': home, 'away': away, 'league': league,
        'time': '17:00', 'game_id': 1,
        'glicko': {'home_prob': .6, 'draw_prob': .2, 'away_prob': .2,
                   'home_rating': 1600, 'away_rating': 1500,
                   'home_xg': 1, 'away_xg': 0.5},
        'totals': {'total_line': 2.5, 'over': 1.7, 'under': 2.1},
        'odds': {}, 'prediction': f'{home} выиграет',
        'verdict': 'Победа хозяев', 'generated_at': '2026-05-21T07:00:00',
    }
    base.update(kw)
    return base


def _save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)


# ═══════════════════════════════════════════════════════════════════
#  Тесты загрузки очереди (БД / JSON fallback)
# ═══════════════════════════════════════════════════════════════════

class TestLoadQueueSSoT:
    """Загрузка очереди прогнозов: БД → JSON fallback."""

    @patch('evaluate_predictions._DB_AVAILABLE', True)
    def test_load_queue_from_db(self, tmp_path):
        """При доступной БД загружает очередь из неё."""
        # Мокаем db.get_queue()
        mock_queue = [
            {'league': 'АПЛ', 'home': 'Team A', 'away': 'Team B',
             'prediction_text': 'Тест', 'match_time': '17:00',
             'status': 'upcoming', 'generated_at': '2026-05-21T07:00:00'},
        ]

        with patch('evaluate_predictions.db.get_queue', return_value=mock_queue):
            queue, used_db = ep._load_queue()

        assert used_db is True
        assert len(queue) == 1
        assert queue[0]['league'] == 'АПЛ'
        assert queue[0]['home'] == 'Team A'

    @patch('evaluate_predictions._DB_AVAILABLE', True)
    def test_load_queue_from_db_empty_fallback_json(self, tmp_path):
        """БД пуста → JSON fallback."""
        pred_path = str(tmp_path / 'predictions_data.json')
        _save_json(pred_path, {
            'predictions': [
                _make_pred('АПЛ', 'Team A', 'Team B'),
            ],
            'generated_at': '2026-05-21T07:00:00',
        })
        ep.PRED_PATH = pred_path

        with patch('evaluate_predictions.db.get_queue', return_value=[]):
            queue, used_db = ep._load_queue()

        assert used_db is True
        assert len(queue) == 1

    @patch('evaluate_predictions._DB_AVAILABLE', False)
    def test_load_queue_no_db(self, tmp_path):
        """БД недоступна → JSON fallback."""
        pred_path = str(tmp_path / 'predictions_data_fallback.json')
        _save_json(pred_path, {
            'predictions': [
                _make_pred('НХЛ', 'Bruins', 'Canadiens'),
            ],
            'generated_at': '2026-05-21T07:00:00',
        })
        ep.PRED_PATH = pred_path

        queue, used_db = ep._load_queue()

        assert used_db is False
        assert len(queue) == 1
        assert queue[0]['home'] == 'Bruins'

    @patch('evaluate_predictions._DB_AVAILABLE', False)
    def test_load_queue_no_db_no_json(self, tmp_path):
        """Ни БД, ни JSON — пустая очередь."""
        ep.PRED_PATH = str(tmp_path / 'nonexistent.json')

        queue, used_db = ep._load_queue()

        assert used_db is False
        assert queue == []

    @patch('evaluate_predictions._DB_AVAILABLE', True)
    def test_load_queue_db_error_fallback(self, tmp_path):
        """Ошибка БД → JSON fallback."""
        pred_path = str(tmp_path / 'predictions_data_err.json')
        _save_json(pred_path, {
            'predictions': [
                _make_pred('АПЛ', 'Team A', 'Team B'),
            ],
        })
        ep.PRED_PATH = pred_path

        with patch('evaluate_predictions.db.get_queue', side_effect=Exception('DB down')):
            queue, used_db = ep._load_queue()

        assert used_db is False
        assert len(queue) == 1


# ═══════════════════════════════════════════════════════════════════
#  Тесты загрузки истории (БД / JSON fallback)
# ═══════════════════════════════════════════════════════════════════

class TestLoadHistorySSoT:
    """Загрузка истории прогнозов: БД → JSON fallback."""

    @patch('evaluate_predictions._DB_AVAILABLE', True)
    def test_load_history_from_db(self):
        """При доступной БД загружает историю из неё."""
        mock_history = [
            {'league': 'АПЛ', 'home': 'Team A', 'away': 'Team B',
             'prediction_text': 'Тест', 'status': 'finished',
             'evaluated_at': '2026-05-21T08:00:00'},
        ]
        with patch('evaluate_predictions.db.get_history', return_value=mock_history):
            history, used_db = ep._load_history()

        assert used_db is True
        assert len(history) == 1

    @patch('evaluate_predictions._DB_AVAILABLE', False)
    def test_load_history_no_db(self, tmp_path):
        """БД недоступна → JSON fallback."""
        hist_path = str(tmp_path / 'predictions_history_fallback.json')
        _save_json(hist_path, {
            'predictions': [
                {'match_id': '20260521||АПЛ||A||B', 'league': 'АПЛ',
                 'home': 'A', 'away': 'B', 'status': 'finished'},
            ],
            'summary': {'total_predictions': 1, 'finished': 1},
        })
        ep.HISTORY_PATH = hist_path

        history, used_db = ep._load_history()

        assert used_db is False
        assert len(history) == 1
        assert history[0]['home'] == 'A'


# ═══════════════════════════════════════════════════════════════════
#  Тесты валидации схем
# ═══════════════════════════════════════════════════════════════════

class TestSchemaValidation:
    """Валидация схем перед записью в JSON."""

    def test_predictions_data_schema_valid(self, tmp_path):
        """Валидация корректных данных predictions_data."""
        from data_schemas import validate

        ok, errors = validate({
            'predictions': [
                {'league': 'АПЛ', 'home': 'A', 'away': 'B',
                 'prediction': 'Тест', 'generated_at': '2026-05-21T07:00:00'},
            ],
            'count': 1,
            'generated_at': '2026-05-21T07:00:00',
        }, 'predictions_data')

        assert ok, f'Ошибки: {errors}'

    def test_predictions_data_schema_missing_fields(self, tmp_path):
        """Валидация данных без обязательных полей."""
        from data_schemas import validate

        ok, errors = validate({
            'predictions': [
                {'league': 'АПЛ', 'home': 'A'},
            ],
        }, 'predictions_data')

        assert not ok
        # Должна быть ошибка об отсутствии поля 'away' и 'prediction'
        err_msgs = ' '.join(errors)
        assert 'away' in err_msgs or 'prediction' in err_msgs

    def test_predictions_history_schema_valid(self, tmp_path):
        """Валидация корректных данных predictions_history."""
        from data_schemas import validate

        ok, errors = validate({
            'predictions': [],
            'summary': {'total_predictions': 0, 'finished': 0,
                        'win': {'total': 0, 'correct': 0},
                        'total': {'total': 0, 'correct': 0}},
            'last_updated': '2026-05-21T08:00:00',
        }, 'predictions_history')

        assert ok, f'Ошибки: {errors}'

    def test_live_scores_schema_valid(self, tmp_path):
        """Валидация корректных данных live_scores."""
        from data_schemas import validate

        ok, errors = validate({
            'matches': {
                'АПЛ||A||B': {
                    'status': 'live', 'score': '1:0',
                    'match_time': '20:00', 'sport': 'football',
                },
            },
        }, 'live_scores')

        assert ok, f'Ошибки: {errors}'


# ═══════════════════════════════════════════════════════════════════
#  Тесты _save_to_json + _save_to_db
# ═══════════════════════════════════════════════════════════════════

class TestSaveSSoT:
    """Сохранение в JSON с валидацией + БД."""

    def test_save_to_json_valid(self, tmp_path):
        """Сохранение в JSON с валидацией."""
        path = str(tmp_path / 'test_predictions.json')
        data = {
            'predictions': [
                {'league': 'АПЛ', 'home': 'A', 'away': 'B',
                 'prediction': 'Тест', 'generated_at': '2026-05-21T07:00:00'},
            ],
            'count': 1,
            'generated_at': '2026-05-21T07:00:00',
        }

        ep._save_to_json(path, data, 'predictions_data')

        assert os.path.exists(path)
        with open(path) as f:
            loaded = json.load(f)
        assert loaded['count'] == 1

    def test_save_to_json_invalid_schema(self, tmp_path):
        """Сохранение с невалидной схемой (всё равно сохраняется)."""
        path = str(tmp_path / 'test_bad_data.json')
        # Отсутствует generated_at и match_time — невалидно, но сохраняется
        data = {
            'predictions': [
                {'league': 'АПЛ', 'home': 'A', 'away': 'B',
                 'prediction': 'Тест'},
            ],
            'count': 1,
            'generated_at': '2026-05-21T07:00:00',
        }

        # Не должно выбрасывать исключение
        ep._save_to_json(path, data, 'predictions_data')

        assert os.path.exists(path)

    @patch('evaluate_predictions._DB_AVAILABLE', True)
    def test_save_to_db(self, tmp_path):
        """Сохранение в БД."""
        entry = _make_pred('АПЛ', 'Team A', 'Team B')

        with patch('evaluate_predictions.db.save_prediction') as mock_save:
            result = ep._save_to_db([entry])

        assert result == 1
        mock_save.assert_called_once()

    @patch('evaluate_predictions._DB_AVAILABLE', False)
    def test_save_to_db_disabled(self, tmp_path):
        """БД недоступна — ничего не сохраняется в БД."""
        entry = _make_pred('АПЛ', 'Team A', 'Team B')

        result = ep._save_to_db([entry])

        assert result == 0

    @patch('evaluate_predictions._DB_AVAILABLE', True)
    def test_save_to_db_error(self, tmp_path):
        """Ошибка БД не прерывает сохранение других записей."""
        entry1 = _make_pred('АПЛ', 'Team A', 'Team B')
        entry2 = _make_pred('НХЛ', 'Bruins', 'Canadiens')

        def _side_effect(*args, **kwargs):
            raise Exception('DB error')

        with patch('evaluate_predictions.db.save_prediction', side_effect=_side_effect):
            result = ep._save_to_db([entry1, entry2])

        # Должен попытаться оба, но оба упадут — возвращаем 0
        # (главное — без исключения)
        assert result == 0


# ═══════════════════════════════════════════════════════════════════
#  Интеграционный тест: evaluate() с подменой путей
# ═══════════════════════════════════════════════════════════════════

class TestEvaluateIntegration:
    """Полный цикл evaluate с разными источниками данных."""

    def _run_eval(self, tmp_path, queue=None, history=None,
                  live_scores=None, daily_results=None,
                  mock_db=False):
        """Запустить evaluate() с подменой путей."""
        import importlib
        importlib.reload(ep)

        qpath = str(tmp_path / 'queue.json')
        hpath = str(tmp_path / 'history.json')
        lpath = str(tmp_path / 'live.json')
        rpath = str(tmp_path / 'results.json')

        if queue is not None:
            _save_json(qpath, {'predictions': queue, 'generated_at': '2026-05-21T07:00:00'})
        if history is not None:
            hist_data = {'predictions': history, 'summary': {}, 'last_updated': '2026-05-21T07:00:00'}
        else:
            hist_data = {'predictions': [], 'summary': {}, 'last_updated': None}
        _save_json(hpath, hist_data)
        _save_json(lpath, {'matches': live_scores or {}})
        _save_json(rpath, {'results': daily_results or []})

        _oq, _oh, _ol, _or = ep.PRED_PATH, ep.HISTORY_PATH, ep.LIVE_PATH, ep.RESULTS_PATH
        ep.PRED_PATH, ep.HISTORY_PATH, ep.LIVE_PATH, ep.RESULTS_PATH = qpath, hpath, lpath, rpath

        if mock_db:
            with patch('evaluate_predictions._DB_AVAILABLE', False):
                with patch('evaluate_predictions._load_queue') as mock_lq:
                    mock_lq.return_value = (queue or [], False)
                    with patch('evaluate_predictions._load_history') as mock_lh:
                        mock_lh.return_value = (history or [], False)
                        ep.evaluate()
        else:
            ep.evaluate()

        ep.PRED_PATH, ep.HISTORY_PATH, ep.LIVE_PATH, ep.RESULTS_PATH = _oq, _oh, _ol, _or

        history_result = json.load(open(hpath)) if os.path.getsize(hpath) > 2 else {'predictions': []}
        queue_result = json.load(open(qpath)).get('predictions', []) if os.path.exists(qpath) and os.path.getsize(qpath) > 2 else []

        return history_result, queue_result

    @patch('evaluate_predictions._DB_AVAILABLE', False)
    def test_evaluate_json_only(self, tmp_path):
        """evaluate() работает с JSON-only (без БД)."""
        pred = _make_pred('АПЛ', 'Team A', 'Team B')
        live = {'АПЛ||Team A||Team B': {
            'status': 'finished', 'score': '2:0',
            'home': 'Team A', 'away': 'Team B', 'league': 'АПЛ',
        }}

        _oq, _oh, _ol, _or = ep.PRED_PATH, ep.HISTORY_PATH, ep.LIVE_PATH, ep.RESULTS_PATH
        qpath = str(tmp_path / 'queue_jon.json')
        hpath = str(tmp_path / 'history_jon.json')
        lpath = str(tmp_path / 'live_jon.json')
        rpath = str(tmp_path / 'results_jon.json')

        _save_json(qpath, {'predictions': [pred], 'generated_at': '2026-05-21T07:00:00'})
        _save_json(hpath, {'predictions': [], 'summary': {}, 'last_updated': None})
        _save_json(lpath, {'matches': live})
        _save_json(rpath, {'results': []})

        ep.PRED_PATH, ep.HISTORY_PATH, ep.LIVE_PATH, ep.RESULTS_PATH = qpath, hpath, lpath, rpath
        result = ep.evaluate()
        ep.PRED_PATH, ep.HISTORY_PATH, ep.LIVE_PATH, ep.RESULTS_PATH = _oq, _oh, _ol, _or

        assert result is not None
        assert result['summary']['finished'] == 1

    @patch('evaluate_predictions._DB_AVAILABLE', True)
    @patch('evaluate_predictions.db.save_prediction')
    def test_evaluate_scores_from_db(self, mock_save, tmp_path):
        """evaluate() использует счета из БД (matches) в _build_score_lookup."""
        pred = _make_pred('АПЛ', 'Team A', 'Team B')

        # Мокаем DB для _build_score_lookup (step 3 — finished matches)
        db_matches = [
            {'league': 'АПЛ', 'home': 'Team A', 'away': 'Team B',
             'score': '3:1', 'status': 'finished'},
        ]

        _oq, _oh, _ol, _or = ep.PRED_PATH, ep.HISTORY_PATH, ep.LIVE_PATH, ep.RESULTS_PATH
        qpath = str(tmp_path / 'queue_sdb.json')
        hpath = str(tmp_path / 'history_sdb.json')
        lpath = str(tmp_path / 'live_sdb.json')
        rpath = str(tmp_path / 'results_sdb.json')

        _save_json(qpath, {'predictions': [pred], 'generated_at': '2026-05-21T07:00:00'})
        _save_json(hpath, {'predictions': [], 'summary': {}, 'last_updated': None})
        _save_json(lpath, {'matches': {}})
        _save_json(rpath, {'results': []})

        ep.PRED_PATH, ep.HISTORY_PATH, ep.LIVE_PATH, ep.RESULTS_PATH = qpath, hpath, lpath, rpath

        with patch('evaluate_predictions.db.execute', return_value=db_matches):
            with patch('evaluate_predictions.db.get_queue', return_value=[]):
                with patch('evaluate_predictions.db.get_history', return_value=[]):
                    result = ep.evaluate()

        ep.PRED_PATH, ep.HISTORY_PATH, ep.LIVE_PATH, ep.RESULTS_PATH = _oq, _oh, _ol, _or

        assert result is not None
        assert result['summary']['finished'] == 1
