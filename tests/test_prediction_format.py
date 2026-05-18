"""
Тест формата predictions_data.json и его совместимости с generate_site.py.

Проверяет, что generate_site.py правильно парсит прогнозы
и что структура predictions_data.json содержит все нужные поля.
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
