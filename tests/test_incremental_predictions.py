"""
Тест инкрементальной генерации страницы прогнозов.

Проверяет:
1. Первые 20 прогнозов — статический HTML
2. Остальные — JSON-блоб с данными для JS
3. Кнопка "Показать ещё" присутствует при >20 прогнозов
4. JS-скрипт loadMorePreds определён
5. predictions.html генерируется без ошибок
"""

import os, sys, json, pytest, hashlib
from unittest.mock import patch

sys.path.insert(0, '/opt')

# Мокаем БД, чтобы не зависеть от реальных данных
MOCK_PREDS = []
for i in range(30):
    MOCK_PREDS.append({
        'league': 'АПЛ' if i < 25 else 'НХЛ',
        'home': f'Team_{i}A',
        'away': f'Team_{i}B',
        'prediction_text': f'Прогноз для матча {i}',
        'verdict': f'Вердикт {i}',
        'match_time': f'{10 + i % 12}:00',
        'time': f'{10 + i % 12}:00',
        'game_id': i,
        'glicko_home_prob': 0.6, 'glicko_away_prob': 0.4,
        'odds_over': 1.8, 'odds_under': 2.0, 'total_line': 2.5,
        'generated_at': '2026-05-21T07:00:00',
        'status': 'upcoming',
        'odds': {'home': 1.5}, 'totals': {'total_line': 2.5, 'over': 1.8},
    })


class TestIncrementalPredictions:
    """Тест инкрементальной генерации predictions.html."""

    @patch('site_predictions.db.get_queue', return_value=MOCK_PREDS)
    @patch('site_predictions._DB_OK', True)
    def test_generate_predictions(self, mock_db, tmp_path):
        """predictions.html генерируется без ошибок."""
        import site_predictions
        out = str(tmp_path / 'predictions.html')
        result = site_predictions.generate_predictions(out)

        assert result == 30  # Все прогнозы
        assert os.path.exists(out)

    @patch('site_predictions.db.get_queue', return_value=MOCK_PREDS)
    @patch('site_predictions._DB_OK', True)
    def test_first_20_static_html(self, mock_db, tmp_path):
        """Первые 20 прогнозов — статический HTML (pred-widget)."""
        import site_predictions
        out = str(tmp_path / 'predictions_static.html')
        site_predictions.generate_predictions(out)

        with open(out) as f:
            html = f.read()

        # Статические карточки
        assert html.count('class="pred-widget"') >= 20  # первые 20 статические

    @patch('site_predictions.db.get_queue', return_value=MOCK_PREDS)
    @patch('site_predictions._DB_OK', True)
    def test_json_data_blob_present(self, mock_db, tmp_path):
        """JSON-блоб с данными для JS присутствует в HTML."""
        import site_predictions
        out = str(tmp_path / 'predictions_json.html')
        site_predictions.generate_predictions(out)

        with open(out) as f:
            html = f.read()

        assert 'pred-data-json' in html
        assert 'PRED_DATA' in html

        # Извлекаем JSON
        import re
        m = re.search(r'id="pred-data-json"[^>]*>([^<]+)<', html)
        assert m, 'JSON-блоб не найден'

    @patch('site_predictions.db.get_queue', return_value=MOCK_PREDS)
    @patch('site_predictions._DB_OK', True)
    def test_load_more_button_present(self, mock_db, tmp_path):
        """Кнопка 'Показать ещё' присутствует для лиг с >20 прогнозов."""
        import site_predictions
        out = str(tmp_path / 'predictions_more.html')
        site_predictions.generate_predictions(out)

        with open(out) as f:
            html = f.read()

        assert 'Показать ещё' in html

    @patch('site_predictions.db.get_queue', return_value=MOCK_PREDS[:5])
    @patch('site_predictions._DB_OK', True)
    def test_no_more_button_if_under_20(self, mock_db, tmp_path):
        """Если прогнозов ≤20 — кнопки 'Показать ещё' нет."""
        import site_predictions
        out = str(tmp_path / 'predictions_no_more.html')
        site_predictions.generate_predictions(out)

        with open(out) as f:
            html = f.read()

        assert 'Показать ещё' not in html

    @patch('site_predictions.db.get_queue', return_value=MOCK_PREDS)
    @patch('site_predictions._DB_OK', True)
    def test_load_more_js_func_defined(self, mock_db, tmp_path):
        """JS-функция loadMorePreds определена в HTML."""
        import site_predictions
        out = str(tmp_path / 'predictions_js.html')
        site_predictions.generate_predictions(out)

        with open(out) as f:
            html = f.read()

        assert 'function loadMorePreds' in html
        assert 'function toggleTxt' in html

    @patch('site_predictions.db.get_queue', return_value=[])
    @patch('site_predictions._DB_OK', True)
    def test_empty_predictions(self, mock_db, tmp_path):
        """При пустых прогнозах страница не падает."""
        import site_predictions
        out = str(tmp_path / 'predictions_empty.html')
        result = site_predictions.generate_predictions(out)

        assert result == 0
        assert os.path.exists(out)

    @patch('site_predictions.db.get_queue', side_effect=Exception('DB error'))
    @patch('site_predictions._DB_OK', True)
    def test_db_error_graceful(self, mock_db, tmp_path):
        """Ошибка БД не ломает генерацию — грациозное падение."""
        import site_predictions
        out = str(tmp_path / 'predictions_err.html')

        # Не должно быть исключения
        result = site_predictions.generate_predictions(out)

        assert result == 0
        assert os.path.exists(out)
