#!/usr/bin/env python3
"""
Тесты часовых поясов для всех источников данных Zula Sport.

Проверяет корректность конвертации времени в МСК (UTC+3) для каждого источника.
"""

import sys
import os
sys.path.insert(0, '/opt')

from datetime import datetime, timezone, timedelta
import json
import unittest
from unittest import mock

MOW = timedelta(hours=3)
UTC = timezone.utc


class TestTimezoneConversions(unittest.TestCase):
    """Базовые тесты конвертации времени."""

    def test_iso_utc_to_msk(self):
        """ISO 8601 с Z суффиксом (UTC → MSK)."""
        cases = [
            # (ISO string, expected MSK time)
            ('2026-05-21T12:00:00Z', '15:00'),
            ('2026-05-21T00:00:00Z', '03:00'),
            ('2026-05-21T21:00:00Z', '00:00'),
            ('2026-05-21T00:30:00.000Z', '03:30'),
        ]
        for iso, expected_msk in cases:
            dt = datetime.fromisoformat(iso.replace('Z', '+00:00'))
            msk_time = (dt + MOW).strftime('%H:%M')
            self.assertEqual(msk_time, expected_msk, f'{iso} → {msk_time} != {expected_msk}')

    def test_iso_utc_with_explicit_tz_to_msk(self):
        """ISO 8601 с +00:00 (SStats)."""
        cases = [
            ('2025-08-15T19:00:00+00:00', '22:00'),
            ('2026-05-21T19:00:00+00:00', '22:00'),
        ]
        for iso, expected_msk in cases:
            dt = datetime.fromisoformat(iso)
            msk_time = (dt + MOW).strftime('%H:%M')
            self.assertEqual(msk_time, expected_msk, f'{iso} → {msk_time} != {expected_msk}')

    def test_edge_midnight_crossing(self):
        """Переход через полночь при конвертации."""
        cases = [
            # 22:00 UTC → 01:00 MSK (следующий день)
            ('2026-05-21T22:00:00Z', '01:00'),
            # 23:00 UTC → 02:00 MSK
            ('2026-05-21T23:00:00Z', '02:00'),
            # 23:59 UTC → 02:59 MSK
            ('2026-05-21T23:59:00Z', '02:59'),
            # 00:00 UTC → 03:00 MSK
            ('2026-05-21T00:00:00Z', '03:00'),
        ]
        for iso, expected_msk in cases:
            dt = datetime.fromisoformat(iso.replace('Z', '+00:00'))
            msk_time = (dt + MOW).strftime('%H:%M')
            self.assertEqual(msk_time, expected_msk, f'{iso} → {msk_time} != {expected_msk}')


class TestConvertToMsk(unittest.TestCase):
    """Тесты _convert_to_msk из fetch_upcoming_matches.py."""

    @classmethod
    def setUpClass(cls):
        # Импортируем функцию из модуля
        from fetch_upcoming_matches import _convert_to_msk
        cls.convert = staticmethod(_convert_to_msk)

    def test_no_offset(self):
        """Без смещения: время не меняется."""
        self.assertEqual(self.convert('15:00', 0), '15:00')
        self.assertEqual(self.convert('00:00', 0), '00:00')
        self.assertEqual(self.convert('23:59', 0), '23:59')

    def test_offset_plus_one(self):
        """Смещение +1 (CEST → MSK)."""
        self.assertEqual(self.convert('15:00', 1), '16:00')
        self.assertEqual(self.convert('00:00', 1), '01:00')
        self.assertEqual(self.convert('23:00', 1), '00:00')  # полночь

    def test_offset_plus_three(self):
        """Смещение +3 (UTC → MSK)."""
        self.assertEqual(self.convert('00:00', 3), '03:00')
        self.assertEqual(self.convert('21:00', 3), '00:00')  # переход через полночь
        self.assertEqual(self.convert('12:30', 3), '15:30')

    def test_with_date_prefix(self):
        """Формат с префиксом даты (dd.mm. HH:MM)."""
        self.assertEqual(self.convert('21.05. 15:00', 1), '16:00')
        self.assertEqual(self.convert('21.05. 15:00', 0), '15:00')
        self.assertEqual(self.convert('21.05 15:00', 3), '18:00')

    def test_empty_string(self):
        """Пустая строка."""
        self.assertEqual(self.convert('', 1), '')
        self.assertEqual(self.convert(None, 1), '')

    def test_wrap_around_midnight(self):
        """Обёртка вокруг полуночи."""
        cases = [
            ('23:00', 1, '00:00'),
            ('23:30', 1, '00:30'),
            ('22:00', 3, '01:00'),
            ('23:00', 3, '02:00'),
            ('01:00', 23, '00:00'),  # большой offset
        ]
        for time_str, offset, expected in cases:
            self.assertEqual(self.convert(time_str, offset), expected)


class TestSStatsYear(unittest.TestCase):
    """Тест определения года для SStats API."""

    def test_sstats_year_logic(self):
        """Проверка логики _sstats_year()."""
        from fetch_upcoming_matches import _sstats_year

        # В январе-июле: прошлый год
        with mock.patch('fetch_upcoming_matches.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 21, tzinfo=UTC)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            year = _sstats_year()
            self.assertEqual(year, 2025)

        # В августе-декабре: текущий год
        with mock.patch('fetch_upcoming_matches.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 8, 15, tzinfo=UTC)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            year = _sstats_year()
            self.assertEqual(year, 2026)


class TestNhlTimeHandling(unittest.TestCase):
    """Тесты NHL API timezone."""

    def test_nhl_start_time_utc_to_msk(self):
        """startTimeUTC из NHL API → MSK."""
        cases = [
            ('2026-05-22T00:00:00Z', '03:00'),
            ('2026-05-22T02:00:00Z', '05:00'),
            ('2026-05-22T23:30:00Z', '02:30'),
        ]
        for start_time, expected_msk in cases:
            dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            msk_time = (dt + MOW).strftime('%H:%M')
            self.assertEqual(msk_time, expected_msk)


class TestBalldontlieTimeHandling(unittest.TestCase):
    """Тесты balldontlie API timezone."""

    def test_balldontlie_datetime_to_msk(self):
        """datetime из balldontlie (NBA)."""
        cases = [
            ('2026-05-21T00:30:00.000Z', '03:30'),
            ('2026-05-22T01:00:00.000Z', '04:00'),
        ]
        for dt_str, expected_msk in cases:
            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            msk_time = (dt + MOW).strftime('%H:%M')
            self.assertEqual(msk_time, expected_msk)


class TestUpcomingYearFunction(unittest.TestCase):
    """Тест _sstats_year() в upcoming.py."""

    def test_upcoming_sstats_year(self):
        """Проверка логики _sstats_year() из upcoming.py."""
        from upcoming import _sstats_year

        # В мае (первая половина года): используем прошлый год
        with mock.patch('upcoming.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 21, tzinfo=UTC)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            self.assertEqual(_sstats_year(), 2025)

        # В августе: новый сезон, используем текущий год
        with mock.patch('upcoming.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 8, 15, tzinfo=UTC)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            self.assertEqual(_sstats_year(), 2026)


class TestFlashscoreTzOffsets(unittest.TestCase):
    """Проверка, что все FLASHSCORE_LEAGUES имеют offset."""

    def test_all_leagues_have_offset(self):
        """Каждая лига из FLASHSCORE_LEAGUES должна быть в FLASHSCORE_TZ_OFFSETS."""
        from fetch_upcoming_matches import FLASHSCORE_LEAGUES, FLASHSCORE_TZ_OFFSETS
        for key in FLASHSCORE_LEAGUES:
            self.assertIn(key, FLASHSCORE_TZ_OFFSETS,
                          f'{key} нет в FLASHSCORE_TZ_OFFSETS')


class TestFetchTvChannelsMsk(unittest.TestCase):
    """Тест функции _utc_to_msk_time из fetch_tv_channels.py."""

    def setUp(self):
        import fetch_tv_channels as ftvc
        self.utc_to_msk = ftvc._utc_to_msk_time

    def test_adds_three_hours(self):
        """Прибавляет 3 часа."""
        self.assertEqual(self.utc_to_msk('15:00'), '18:00')
        self.assertEqual(self.utc_to_msk('00:00'), '03:00')
        self.assertEqual(self.utc_to_msk('21:30'), '00:30')

    def test_with_date_prefix(self):
        """С префиксом даты dd.mm. HH:MM."""
        result = self.utc_to_msk('21.05. 15:00')
        self.assertEqual(result, '21.05. 18:00')

    def test_empty_input(self):
        """Пустой ввод."""
        self.assertEqual(self.utc_to_msk(''), '')
        self.assertEqual(self.utc_to_msk(None), None)

    def test_no_colon(self):
        """Без двоеточия."""
        self.assertEqual(self.utc_to_msk('1500'), '1500')


if __name__ == '__main__':
    unittest.main()
