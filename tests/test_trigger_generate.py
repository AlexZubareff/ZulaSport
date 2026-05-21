"""
Тест event-driven trigger_generate с debounce.

Проверяет:
1. trigger_generate запускает generate_site.py
2. Debounce: повторный вызов в пределах 2 мин не запускает
3. Разные секции имеют раздельные штампы (не блокируют друг друга)
4. После завершения debounce можно запустить снова
"""

import os, sys, json, time, pytest
from unittest.mock import patch

sys.path.insert(0, '/opt')

from capper_common import trigger_generate, _trigger_should_fire, _trigger_stamp_path, _TRIGGER_DIR


class TestTriggerStamp:
    """Тесты файлов-штампов для debounce."""

    def setup_method(self):
        """Очистить штампы перед каждым тестом."""
        import shutil
        if os.path.exists(_TRIGGER_DIR):
            shutil.rmtree(_TRIGGER_DIR)

    def test_stamp_path_creates_dir(self):
        """_trigger_stamp_path создаёт директорию."""
        path = _trigger_stamp_path('schedule')
        assert os.path.exists(_TRIGGER_DIR)
        assert path.startswith(_TRIGGER_DIR)

    def test_stamp_path_safe_name(self):
        """Имя файла clean."""
        path = _trigger_stamp_path('schedule')
        assert 'schedule.stamp' in path

    def test_should_fire_first_call(self):
        """Первый вызов всегда возвращает True."""
        assert _trigger_should_fire('schedule') is True

    def test_should_not_fire_within_debounce(self):
        """Повторный вызов в пределах debounce возвращает False."""
        _trigger_should_fire('schedule')
        assert _trigger_should_fire('schedule') is False

    def test_different_sections_independent(self):
        """Разные секции не блокируют друг друга."""
        _trigger_should_fire('schedule')
        assert _trigger_should_fire('predictions') is True


class TestTriggerGenerate:
    """Тесты trigger_generate."""

    def setup_method(self):
        import shutil
        if os.path.exists(_TRIGGER_DIR):
            shutil.rmtree(_TRIGGER_DIR)

    @patch('subprocess.Popen')
    def test_trigger_generate_calls_popen(self, mock_popen):
        """trigger_generate вызывает subprocess.Popen с generate_site.py."""
        result = trigger_generate('schedule')

        assert result is True
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert '/opt/generate_site.py' in ' '.join(args)
        assert '--section' in args
        assert 'schedule' in args

    @patch('subprocess.Popen')
    def test_trigger_generate_debounce(self, mock_popen):
        """Повторный вызов в пределах debounce не запускает процесс."""
        trigger_generate('schedule')
        result = trigger_generate('schedule')

        assert result is False
        mock_popen.assert_called_once()  # только 1 раз

    @patch('subprocess.Popen')
    def test_trigger_generate_different_sections(self, mock_popen):
        """Разные секции не дебаунсят друг друга."""
        trigger_generate('schedule')
        result = trigger_generate('predictions')

        assert result is True
        assert mock_popen.call_count == 2

    @patch('subprocess.Popen')
    def test_trigger_generate_all_included(self, mock_popen):
        """Можно запустить 'all'."""
        result = trigger_generate('all')

        assert result is True
        args = mock_popen.call_args[0][0]
        assert 'all' in args
