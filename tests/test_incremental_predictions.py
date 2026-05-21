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


class TestIncrementalPredictions:
    """Тест инкрементальной генерации predictions.html."""

    def _make_pred(self, league, idx):
        return {
            'league': league,
            'home': f'Team_{idx}A',
            'away': f'Team_{idx}B',
            'prediction': f'Прогноз для матча {idx}',
            'prediction_text': f'Прогноз для матча {idx}',
            'verdict': f'Вердикт {idx}',
            'match_time': f'{10 + idx % 12}:00',
            'time': f'{10 + idx % 12}:00',
            'game_id': idx,
            'glicko': {'home_prob': 0.6, 'draw_prob': 0.2, 'away_prob': 0.2},
            'totals': {'total_line': 2.5, 'over': 1.8, 'under': 2.0},
            'odds': {'home': 1.5},
            'generated_at': '2026-05-21T07:00:00',
            'status': 'upcoming',
        }

    def _run_generate(self, tmp_path, pred_count=30, json_only=False):
        """Сгенерировать predictions.html с тестовыми данными.
        
        Если json_only=True — использует JSON fallback (без БД).
        """
        import importlib, site_predictions
        importlib.reload(site_predictions)

        out = str(tmp_path / 'predictions.html')

        if json_only:
            # Подменяем _DB_OK на False
            import site_predictions as sp
            sp._DB_OK = False

            # Создаём JSON файл с тестовыми данными
            preds = []
            for i in range(pred_count):
                league = 'АПЛ' if i < pred_count - 5 else 'НХЛ'
                preds.append(self._make_pred(league, i))

            # Сохраняем тестовый predictions_data.json
            pred_path = str(tmp_path / 'predictions_data.json')
            with open(pred_path, 'w', encoding='utf-8') as f:
                json.dump({
                    'predictions': preds,
                    'count': len(preds),
                    'generated_at': '2026-05-21T07:00:00',
                }, f, ensure_ascii=False)

            # Используем path overlay — подменяем PREDICTION_PATH
            # Для этого используем прямой подход: записываем в реальный путь
            # и восстанавливаем после
            orig_path = '/opt/predictions_data.json'
            backup = None
            if os.path.exists(orig_path):
                with open(orig_path) as f:
                    backup = f.read()
            with open(orig_path, 'w', encoding='utf-8') as f:
                json.dump({
                    'predictions': preds,
                    'count': len(preds),
                    'generated_at': '2026-05-21T07:00:00',
                }, f, ensure_ascii=False)

            try:
                result = site_predictions.generate_predictions(out)
            finally:
                if backup:
                    with open(orig_path, 'w', encoding='utf-8') as f:
                        f.write(backup)
                elif os.path.exists(orig_path):
                    os.remove(orig_path)
        else:
            result = site_predictions.generate_predictions(out)

        return result, out

    def test_generate_predictions_many(self, tmp_path):
        """predictions.html генерируется без ошибок (30 прогнозов)."""
        # Используем JSON fallback (без БД)
        result, out = self._run_generate(tmp_path, pred_count=30, json_only=True)
        assert result == 30
        assert os.path.exists(out)

    def test_first_20_static_html(self, tmp_path):
        """Первые 20 прогнозов — статический HTML (pred-widget)."""
        result, out = self._run_generate(tmp_path, pred_count=30, json_only=True)
        assert result == 30
        with open(out) as f:
            html = f.read()
        # Статических карточек как минимум 20
        assert html.count('class="pred-widget"') >= 20

    def test_json_data_blob_present(self, tmp_path):
        """JSON-блоб с данными для JS присутствует в HTML."""
        result, out = self._run_generate(tmp_path, pred_count=30, json_only=True)
        assert result == 30
        with open(out) as f:
            html = f.read()
        assert 'pred-data-json' in html, 'Нет JSON-блоб'
        assert 'PRED_DATA' in html, 'Нет PRED_DATA'

    def test_load_more_button_present(self, tmp_path):
        """Кнопка 'Показать ещё' присутствует для лиг с >20 прогнозов."""
        result, out = self._run_generate(tmp_path, pred_count=30, json_only=True)
        assert result == 30
        with open(out) as f:
            html = f.read()
        assert 'Показать ещё' in html

    def test_no_more_button_if_under_20(self, tmp_path):
        """Если прогнозов ≤20 — кнопки 'Показать ещё' нет."""
        result, out = self._run_generate(tmp_path, pred_count=5, json_only=True)
        assert result == 5
        with open(out) as f:
            html = f.read()
        assert 'Показать ещё' not in html

    def test_load_more_js_func_defined(self, tmp_path):
        """JS-функция loadMorePreds определена в HTML."""
        result, out = self._run_generate(tmp_path, pred_count=30, json_only=True)
        assert result == 30
        with open(out) as f:
            html = f.read()
        assert 'function loadMorePreds' in html
        assert 'function toggleTxt' in html

    def test_empty_predictions(self, tmp_path):
        """При пустых прогнозах страница не падает."""
        result, out = self._run_generate(tmp_path, pred_count=0, json_only=True)
        assert result == 0
        assert os.path.exists(out)

    def test_fallback_json_no_file(self, tmp_path):
        """БД нет, JSON нет — грациозное падение."""
        import importlib, site_predictions
        importlib.reload(site_predictions)
        site_predictions._DB_OK = False

        out = str(tmp_path / 'predictions_clean.html')

        # Убеждаемся, что predictions_data.json не существует
        if os.path.exists('/opt/predictions_data.json'):
            os.rename('/opt/predictions_data.json', str(tmp_path / 'predictions_data.bak'))

        try:
            result = site_predictions.generate_predictions(out)
            assert result == 0
            assert os.path.exists(out)
        finally:
            bak = str(tmp_path / 'predictions_data.bak')
            if os.path.exists(bak):
                os.rename(bak, '/opt/predictions_data.json')
