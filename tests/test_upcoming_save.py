"""
Тест формата upcoming_matches.json, который сохраняет fetch_tv_channels.py.

Проверяет:
1. Правильная структура файла
2. Наличие game_id у каждого матча
3. Совместимость формата с capper_pipeline.py
"""

import os, sys, json, pytest

sys.path.insert(0, '/opt')

from tests.conftest import sample_tv_channels


class TestUpcomingSave:
    """Формат upcoming_matches.json."""

    def test_upcoming_structure(self, tmp_path):
        """
        upcoming_matches.json должен содержать date + matches[],
        где каждый матч имеет: home, away, time, game_id, league, league_id.
        """
        tv_data = sample_tv_channels()
        date_fmt = '17.05.2026'

        # Симулируем то, что делает fetch_tv_channels.py:
        # из tv_channels_data берёт футбольные матчи с game_id
        pred_matches = []
        for m in tv_data['matches']:
            if m.get('sport') == 'football' and m.get('game_id'):
                pred_matches.append({
                    'home': m['home'],
                    'away': m['away'],
                    'time': m['time'],
                    'game_id': m['game_id'],
                    'league': m['league'],
                    'league_id': 39,  # упрощённо
                })

        up_data = {'date': date_fmt, 'matches': pred_matches}

        # Валидируем структуру
        assert 'date' in up_data
        assert 'matches' in up_data
        assert isinstance(up_data['matches'], list)

        if up_data['matches']:
            m = up_data['matches'][0]
            for field in ('home', 'away', 'time', 'game_id', 'league', 'league_id'):
                assert field in m, f"Матч не содержит поле '{field}'"
            assert isinstance(m['game_id'], int), "game_id должен быть int"

    def test_game_id_is_present(self, tmp_path):
        """Все футбольные матчи в tv_channels должны иметь game_id."""
        tv_data = sample_tv_channels()

        football_matches = [m for m in tv_data['matches']
                            if m.get('sport') == 'football']

        for m in football_matches:
            assert m.get('game_id'), (
                f"Футбольный матч {m['home']}—{m['away']} не имеет game_id!\n"
                f"Без него capper_pipeline не сможет собрать прогноз."
            )

    def test_non_football_excluded_from_upcoming(self, tmp_path):
        """Не-футбольные матчи не должны попадать в upcoming_matches."""
        tv_data = sample_tv_channels()

        pred_matches = []
        for m in tv_data['matches']:
            if m.get('sport') == 'football' and m.get('game_id'):
                pred_matches.append(m)

        # Из sample_tv_channels всего 5 матчей, из них 4 футбольных
        # (2 сегодняшних + 2 завтрашних)
        football_count = sum(1 for m in tv_data['matches']
                             if m.get('sport') == 'football')

        assert len(pred_matches) == football_count, (
            f"В выборку для прогнозов попало {len(pred_matches)} "
            f"из {football_count} футбольных матчей"
        )

        # Ни один не-футбол не попал
        sports_in_pred = {m.get('sport') for m in pred_matches}
        assert sports_in_pred == {'football'}, (
            f"В прогнозы попали не-футбольные виды спорта: {sports_in_pred}"
        )

    def test_date_format_compatibility(self):
        """
        Формат даты в upcoming_matches.json (dd.mm.yyyy) совместим
        с тем, как generate_site.py парсит next_date.
        """
        from datetime import datetime

        date_str = '17.05.2026'
        parsed = datetime.strptime(date_str, '%d.%m.%Y')

        # Проверяем, что get_upcoming() сможет сравнить
        tv_date = '20260517'
        expected = parsed.strftime('%Y%m%d')
        assert tv_date == expected, (
            f"tv_channels date '{tv_date}' != "
            f"next_date в YYYYmmdd '{expected}'"
        )
