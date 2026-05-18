"""
Тест загрузки матчей для прогнозов: _load_matches() из capper_pipeline.

Проверяет:
1. Приоритет upcoming_matches.json
2. Fallback на tv_channels_data.json
3. Фильтрация по активным лигам
4. Формат матчей (наличие game_id)
"""

import os, sys, json, pytest

sys.path.insert(0, '/opt')

import capper_pipeline

_orig_exists = os.path.exists
_orig_open = __builtins__['open']


class TestMatchLoading:
    """Загрузка матчей для прогнозов."""

    def _write(self, path, data):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)

    def test_upcoming_priority(self, tmp_path, monkeypatch):
        """
        Если есть upcoming_matches.json — берётся из него,
        даже если tv_channels_data.json тоже есть.
        """
        up_file = tmp_path / 'upcoming_matches.json'
        tv_file = tmp_path / 'tv_channels_data.json'

        self._write(up_file, {
            'date': '17.05.2026',
            'matches': [
                {'home': 'Ман Сити', 'away': 'Арсенал', 'time': '17:00',
                 'game_id': 2001, 'league': 'АПЛ', 'league_id': 39},
                {'home': 'Барса', 'away': 'Реал', 'time': '22:00',
                 'game_id': 2002, 'league': 'Ла Лига', 'league_id': 140},
            ],
        })
        self._write(tv_file, {
            'date': '20260517',
            'matches': [
                {'sport': 'football', 'league': 'АПЛ', 'home': 'A', 'away': 'B',
                 'time': '17:00', 'game_id': 3001},
                {'sport': 'football', 'league': 'АПЛ', 'home': 'C', 'away': 'D',
                 'time': '17:00', 'game_id': 3002},
                {'sport': 'football', 'league': 'Ла Лига', 'home': 'E', 'away': 'F',
                 'time': '22:00', 'game_id': 3003},
            ],
        })

        def _mock_exists(path):
            basename = os.path.basename(path)
            if basename == 'upcoming_matches.json':
                return _orig_exists(str(up_file))
            if basename == 'tv_channels_data.json':
                return _orig_exists(str(tv_file))
            return _orig_exists(path)

        def _mock_open(path, *args, **kwargs):
            basename = os.path.basename(path)
            if basename == 'upcoming_matches.json':
                path = str(up_file)
            elif basename == 'tv_channels_data.json':
                path = str(tv_file)
            return _orig_open(path, *args, **kwargs)

        monkeypatch.setattr(os.path, 'exists', _mock_exists)
        monkeypatch.setattr('builtins.open', _mock_open)

        matches = capper_pipeline._load_matches()

        assert len(matches) == 2, (
            f"Ожидалось 2 матча из upcoming, получено: {len(matches)}"
        )
        leagues = {m['league'] for m in matches}
        assert leagues == {'АПЛ', 'Ла Лига'}, f"Лиги: {leagues}"

    def test_fallback_to_tv_channels(self, tmp_path, monkeypatch):
        """Без upcoming берём футбол из tv_channels."""
        tv_file = tmp_path / 'tv_channels_data.json'

        self._write(tv_file, {
            'date': '20260517',
            'matches': [
                {'sport': 'football', 'league': 'АПЛ', 'home': 'A', 'away': 'B',
                 'time': '17:00', 'game_id': 3001},
                {'sport': 'football', 'league': 'Ла Лига', 'home': 'C', 'away': 'D',
                 'time': '22:00', 'game_id': 3002},
                {'sport': 'hockey', 'league': 'НХЛ', 'home': 'R', 'away': 'B',
                 'time': '02:00'},
            ],
        })

        state = {'upcoming_exists': False}

        def _mock_exists(path):
            basename = os.path.basename(path)
            if basename == 'upcoming_matches.json':
                return state['upcoming_exists']
            if basename == 'tv_channels_data.json':
                return _orig_exists(str(tv_file))
            return _orig_exists(path)

        def _mock_open(path, *args, **kwargs):
            basename = os.path.basename(path)
            if basename == 'tv_channels_data.json':
                path = str(tv_file)
            return _orig_open(path, *args, **kwargs)

        monkeypatch.setattr(os.path, 'exists', _mock_exists)
        monkeypatch.setattr('builtins.open', _mock_open)

        matches = capper_pipeline._load_matches()

        assert len(matches) == 2, (
            f"Ожидалось 2 матча (fallback), получено: {len(matches)}"
        )
        for m in matches:
            assert m.get('game_id'), f"Матч {m['home']}—{m['away']} без game_id"

    def test_empty_no_files(self, monkeypatch):
        """Если нет ни одного файла — пустой список."""
        def _mock_exists(path):
            basename = os.path.basename(path)
            if basename in ('upcoming_matches.json', 'tv_channels_data.json'):
                return False
            return _orig_exists(path)

        monkeypatch.setattr(os.path, 'exists', _mock_exists)

        matches = capper_pipeline._load_matches()
        assert matches == [], f"Ожидался пустой список, получено: {matches}"

    def test_filter_inactive_leagues(self, tmp_path, monkeypatch):
        """Матчи из неактивных лиг отбрасываются."""
        up_file = tmp_path / 'upcoming_matches.json'

        self._write(up_file, {
            'date': '17.05.2026',
            'matches': [
                {'home': 'A', 'away': 'B', 'time': '17:00',
                 'game_id': 100, 'league': 'АПЛ', 'league_id': 39},
                {'home': 'C', 'away': 'D', 'time': '22:00',
                 'game_id': 101, 'league': 'Ла Лига', 'league_id': 140},
                {'home': 'E', 'away': 'F', 'time': '20:00',
                 'game_id': 102, 'league': 'Лига Чемпионов', 'league_id': 2},
            ],
        })

        def _mock_exists(path):
            basename = os.path.basename(path)
            if basename == 'upcoming_matches.json':
                return _orig_exists(str(up_file))
            if basename == 'tv_channels_data.json':
                return False
            return _orig_exists(path)

        def _mock_open(path, *args, **kwargs):
            basename = os.path.basename(path)
            if basename == 'upcoming_matches.json':
                path = str(up_file)
            return _orig_open(path, *args, **kwargs)

        monkeypatch.setattr(os.path, 'exists', _mock_exists)
        monkeypatch.setattr('builtins.open', _mock_open)

        matches = capper_pipeline._load_matches()

        assert len(matches) == 2, (
            f"Лига Чемпионов должна быть отфильтрована, "
            f"получено: {len(matches)}"
        )
        assert all(m['league'] in ('АПЛ', 'Ла Лига') for m in matches), (
            "Все матчи должны быть из активных лиг"
        )
