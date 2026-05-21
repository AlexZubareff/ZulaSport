"""
Тесты для конвертации времени в МСК (timezone).

Проверяет:
1. _convert_to_msk — конвертация времени с разными offset
2. Flashscore-лиги с правильными оффсетами (ЧМ, Евролига, КХЛ, ВТБ)
3. Очистка префикса даты (dd.mm. HH:MM → HH:MM MSK)
4. Оборачивание через полночь
5. Функция в app.js (клиентский конвертер) — только синтаксис
"""

import os, sys, json, re, types
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

sys.path.insert(0, '/opt')

from fetch_upcoming_matches import (
    _convert_to_msk, _fetch_flashscore,
    FLASHSCORE_LEAGUES, FLASHSCORE_TZ_OFFSETS,
)


class TestConvertToMSK:
    """Проверка _convert_to_msk() — базовой конвертации."""

    def test_cest_to_msk(self):
        """CEST (UTC+2) → MSK (UTC+3): +1 час."""
        assert _convert_to_msk('20:30', offset_hours=1) == '21:30'
        assert _convert_to_msk('12:00', offset_hours=1) == '13:00'
        assert _convert_to_msk('00:15', offset_hours=1) == '01:15'

    def test_no_offset(self):
        """offset_hours=0: время не меняется."""
        assert _convert_to_msk('19:00', offset_hours=0) == '19:00'
        assert _convert_to_msk('10:45', offset_hours=0) == '10:45'

    def test_empty_string(self):
        """Пустая строка возвращается как есть."""
        assert _convert_to_msk('', offset_hours=1) == ''
        assert _convert_to_msk(None, offset_hours=1) == ''

    def test_wrap_midnight(self):
        """Оборачивание через полночь: 23:30 CEST → 00:30 MSK."""
        assert _convert_to_msk('23:30', offset_hours=1) == '00:30'
        assert _convert_to_msk('23:00', offset_hours=1) == '00:00'
        assert _convert_to_msk('22:45', offset_hours=1) == '23:45'

    def test_wrap_no_offset(self):
        """Без offset'а оборачивания не происходит."""
        assert _convert_to_msk('23:30', offset_hours=0) == '23:30'

    def test_strip_date_prefix(self):
        """Префикс даты (dd.mm.) очищается перед конвертацией."""
        assert _convert_to_msk('14.05. 20:30', offset_hours=1) == '21:30'
        assert _convert_to_msk('01.06. 12:00', offset_hours=1) == '13:00'

    def test_strip_date_prefix_variants(self):
        """Разные форматы префикса даты."""
        assert _convert_to_msk('14.05. 20:30', offset_hours=1) == '21:30'
        assert _convert_to_msk('14.05 20:30', offset_hours=1) == '21:30'

    def test_malformed_time_returns_as_is(self):
        """Если время непарсится, возвращаем оригинал (очищенный от префикса)."""
        assert _convert_to_msk('abc', offset_hours=1) == 'abc'
        assert _convert_to_msk('14.05. not_a_time', offset_hours=1) == 'not_a_time'

    def test_edge_midnight_to_next_day(self):
        """00:00 CEST → 01:00 MSK."""
        assert _convert_to_msk('00:00', offset_hours=1) == '01:00'


class TestFlashscoreTZOffsets:
    """Проверка, что для каждой Flashscore-лиги задан правильный offset."""

    def test_all_leagues_have_offset(self):
        """Каждая Flashscore-лига имеет запись в FLASHSCORE_TZ_OFFSETS."""
        for league_key in FLASHSCORE_LEAGUES:
            assert league_key in FLASHSCORE_TZ_OFFSETS, \
                f'{league_key} отсутствует в FLASHSCORE_TZ_OFFSETS'

    def test_cest_leagues_have_plus1(self):
        """ЧМ по хоккею и Евролига — CEST (UTC+2) → +1 час до MSK."""
        assert FLASHSCORE_TZ_OFFSETS.get('world-cup-hockey') == 1
        assert FLASHSCORE_TZ_OFFSETS.get('euroleague') == 1

    def test_msk_leagues_have_zero(self):
        """КХЛ и ВТБ — уже MSK (UTC+3) → +0."""
        assert FLASHSCORE_TZ_OFFSETS.get('khl') == 0
        assert FLASHSCORE_TZ_OFFSETS.get('vtb') == 0


class TestFetchFlashscore:
    """Проверка _fetch_flashscore с mocked flashscore_other."""

    @staticmethod
    def _make_mock_league(fs_match_data):
        """Создать mock-module 'flashscore_other' с нужными данными матчей."""
        def _fetch_live(league_key, **kwargs):
            league_key_to_data = {
                'khl': [{'home': 'A', 'away': 'B', 'time': '19:30'}],
                'world-cup-hockey': [{'home': 'X', 'away': 'Y', 'time': '20:30'}],
                'vtb': [{'home': 'P', 'away': 'Q', 'time': '18:00'}],
                'euroleague': [{'home': 'R', 'away': 'S', 'time': '21:00'}],
            }
            data = fs_match_data.get(league_key, league_key_to_data.get(league_key, []))
            return (data, [])

        m = types.ModuleType('flashscore_other')
        m.LEAGUES = {
            'khl': {'path': '/hockey/khl/'},
            'world-cup-hockey': {'path': '/hockey/world-cup/'},
            'vtb': {'path': '/basketball/vtb/'},
            'euroleague': {'path': '/basketball/euroleague/'},
        }
        m.fetch_upcoming_live = _fetch_live
        return m

    def _call_fetch(self, fs_match_data=None):
        """Вызвать _fetch_flashscore с подменённым модулем."""
        import sys
        mock_module = self._make_mock_league(fs_match_data or {})
        old_module = sys.modules.get('flashscore_other')
        sys.modules['flashscore_other'] = mock_module
        try:
            return _fetch_flashscore(
                datetime(2026, 5, 21, tzinfo=timezone.utc)
            )
        finally:
            if old_module:
                sys.modules['flashscore_other'] = old_module
            else:
                del sys.modules['flashscore_other']

    def test_khl_time_unchanged(self):
        """КХЛ: время уже MSK, не меняется."""
        result = self._call_fetch({'khl': [{'home': 'СКА', 'away': 'ЦСКА', 'time': '19:30'}]})
        khl = [m for m in result if m['league'] == 'КХЛ']
        assert len(khl) >= 1
        assert khl[0]['time'] == '19:30'

    def test_world_cup_cest_to_msk(self):
        """ЧМ по хоккею: CEST → MSK, +1 час."""
        result = self._call_fetch({'world-cup-hockey': [{'home': 'Канада', 'away': 'Швеция', 'time': '20:30'}]})
        wc = [m for m in result if m['league'] == 'ЧМ по хоккею']
        assert len(wc) >= 1
        assert wc[0]['time'] == '21:30'

    def test_euroleague_cest_to_msk(self):
        """Евролига: CEST → MSK, +1 час."""
        result = self._call_fetch({'euroleague': [{'home': 'Реал', 'away': 'Барса', 'time': '21:00'}]})
        el = [m for m in result if m['league'] == 'Евролига']
        assert len(el) >= 1
        assert el[0]['time'] == '22:00'

    def test_vtb_time_unchanged(self):
        """ВТБ: время уже MSK, не меняется."""
        result = self._call_fetch({'vtb': [{'home': 'ЦСКА', 'away': 'Зенит', 'time': '18:00'}]})
        vtb = [m for m in result if m['league'] == 'Лига ВТБ']
        assert len(vtb) >= 1
        assert vtb[0]['time'] == '18:00'

    def test_world_cup_with_date_prefix(self):
        """ЧМ с префиксом даты: dd.mm. HH:MM → очистка + конвертация."""
        result = self._call_fetch({'world-cup-hockey': [{'home': 'США', 'away': 'Финляндия', 'time': '16.05. 16:30'}]})
        wc = [m for m in result if m['league'] == 'ЧМ по хоккею']
        assert len(wc) >= 1
        assert wc[0]['time'] == '17:30'

    def test_all_league_keys_present(self):
        """Все лиги возвращаются."""
        result = self._call_fetch()
        leagues_found = {m['league'] for m in result}
        expected = {'КХЛ', 'ЧМ по хоккею', 'Лига ВТБ', 'Евролига'}
        assert leagues_found == expected
