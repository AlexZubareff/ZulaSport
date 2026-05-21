"""
Тест формата прогнозов в predictions_data.json + capper_common сохранение.

Проверяет:
1. Все прогнозы имеют обязательные поля
2. Единый формат (одинаковая структура для всех спортов)
3. capper_common.save_predictions / normalize_prediction
"""

import os, sys, json, pytest

sys.path.insert(0, '/opt')

from tests.conftest import sample_predictions, sample_tv_channels


class TestPredictionFormat:
    """Формат и целостность данных прогнозов."""

    def test_prediction_has_required_fields(self):
        """Каждый прогноз содержит все поля, что ждёт generate_site.py."""
        data = sample_predictions()
        pred = data['predictions'][0]

        required = ['home', 'away', 'league', 'time', 'game_id',
                     'prediction', 'odds', 'glicko']
        for field in required:
            assert field in pred, f"Прогноз не содержит поле '{field}'"

        # odds
        for k in ('home', 'draw', 'away'):
            assert k in pred['odds'], f"odds не содержит '{k}'"

        # glicko
        for k in ('home_prob', 'draw_prob', 'away_prob',
                  'home_rating', 'away_rating', 'home_xg', 'away_xg'):
            assert k in pred['glicko'], f"glicko не содержит '{k}'"

    def test_glicko_probabilities_sum(self):
        """Сумма вероятностей Glicko ~1.0 (допуск 0.05)."""
        data = sample_predictions()
        for pred in data['predictions']:
            g = pred['glicko']
            total = g['home_prob'] + g['draw_prob'] + g['away_prob']
            assert abs(total - 1.0) < 0.05, (
                f"Сумма вероятностей {total:.3f} ≠ 1.0 "
                f"для {pred['home']}—{pred['away']}"
            )

    def test_prediction_match_key(self):
        """
        Ключ матча (league||home||away) должен совпадать с тем,
        как generate_site.py стыкует прогнозы с матчами.
        """
        pred = sample_predictions()['predictions'][0]
        key = f"{pred['league']}||{pred['home']}||{pred['away']}"

        # Проверяем, что такой матч есть в tv_channels
        tv = sample_tv_channels()
        found = False
        for m in tv['matches']:
            m_key = f"{m.get('league', '')}||{m.get('home', '')}||{m.get('away', '')}"
            if m_key == key:
                found = True
                break

        # Это тест-данные — АПЛ Ман Сити — Арсенал должен быть
        assert found, (
            f"Ключ '{key}' не найден среди матчей tv_channels.\n"
            f"Проверь: generate_site.py не сможет привязать прогноз к матчу."
        )

    def test_prediction_text_not_empty(self):
        """Текст прогноза не пустой."""
        data = sample_predictions()
        for pred in data['predictions']:
            assert pred.get('prediction'), (
                f"Пустой текст прогноза для {pred['home']}—{pred['away']}"
            )
            assert pred.get('verdict'), (
                f"Пустой вердикт для {pred['home']}—{pred['away']}"
            )

    def test_predictions_json_structure(self, tmp_path):
        """
        Структура predictions_data.json: корневой ключ 'predictions' — список.
        """
        path = tmp_path / 'predictions_data.json'
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(sample_predictions(), f)

        with open(path, encoding='utf-8') as f:
            loaded = json.load(f)

        assert 'predictions' in loaded, "Нет ключа 'predictions'"
        assert isinstance(loaded['predictions'], list), "'predictions' не список"
        assert len(loaded['predictions']) > 0, "Пустой список прогнозов"


class TestCapperCommonSave:
    """Тесты capper_common.save_predictions и normalize_prediction."""

    def test_save_new_predictions(self, tmp_path):
        """Сохранение новых прогнозов."""
        from capper_common import save_predictions

        pred_path = str(tmp_path / 'predictions_test.json')
        predictions = [
            {
                'league': 'АПЛ',
                'home': 'Арсенал',
                'away': 'Челси',
                'prediction': 'Тестовый прогноз для проверки формата сохранения',
                'verdict': 'Победа хозяев',
                'time': '17:00',
                'game_id': 1001,
            },
            {
                'league': 'НХЛ',
                'home': 'Бостон Брюинз',
                'away': 'Монреаль Канадиенс',
                'prediction': 'Тестовый прогноз для хоккея проверка формата',
                'verdict': 'Победа гостей',
                'time': '02:00',
            },
        ]

        save_predictions(predictions, path=pred_path)

        assert os.path.exists(pred_path)

        with open(pred_path, encoding='utf-8') as f:
            data = json.load(f)

        assert 'predictions' in data
        assert len(data['predictions']) == 2
        assert data['count'] == 2

    def test_save_additive_dedup(self, tmp_path):
        """Новые прогнозы добавляются с дедупликацией."""
        from capper_common import save_predictions

        pred_path = str(tmp_path / 'predictions_add.json')

        save_predictions([
            {'league': 'АПЛ', 'home': 'Арсенал', 'away': 'Челси',
             'prediction': 'Прогноз 1', 'verdict': 'Хозяева'},
        ], path=pred_path)

        save_predictions([
            {'league': 'АПЛ', 'home': 'Арсенал', 'away': 'Челси',
             'prediction': 'Прогноз 2 обновлённый', 'verdict': 'Хозяева'},
            {'league': 'Ла Лига', 'home': 'Барса', 'away': 'Реал',
             'prediction': 'Прогноз 3', 'verdict': 'Ничья'},
        ], path=pred_path)

        with open(pred_path, encoding='utf-8') as f:
            data = json.load(f)

        assert len(data['predictions']) == 2

        arsenals = [p for p in data['predictions'] if p['home'] == 'Арсенал']
        assert len(arsenals) == 1
        assert arsenals[0]['prediction'] == 'Прогноз 2 обновлённый'

    def test_empty_predictions_no_file(self, tmp_path):
        """Пустой список не создаёт файл."""
        from capper_common import save_predictions

        pred_path = str(tmp_path / 'predictions_empty.json')
        save_predictions([], path=pred_path)

        assert not os.path.exists(pred_path)

    def test_missing_required_fields_filtered(self, tmp_path):
        """Прогноз без обязательных полей не сохраняется."""
        from capper_common import save_predictions

        pred_path = str(tmp_path / 'predictions_bad.json')
        save_predictions([
            {'home': 'Арсенал', 'away': 'Челси',
             'prediction': 'Тест', 'verdict': 'Хозяева'},
        ], path=pred_path)

        assert not os.path.exists(pred_path)

    def test_normalize_prediction(self):
        """normalize_prediction добавляет опциональные поля."""
        from capper_common import normalize_prediction

        pred = normalize_prediction({
            'league': 'АПЛ', 'home': 'Арсенал', 'away': 'Челси',
            'prediction': 'Тест',
        })

        assert pred['status'] == 'upcoming'
        assert pred['odds'] is None
        assert pred['totals'] is None
        assert pred['glicko'] is None
        assert 'generated_at' in pred
        assert pred['has_lineups'] is None

    def test_run_post_check_missing_file(self, tmp_path):
        """run_post_check не падает при отсутствии файла."""
        from capper_common import run_post_check

        # Не должно быть исключения
        run_post_check(path='/tmp/nonexistent.json')
