"""
Тесты для системы оповещения (Фаза 1.4).

Проверяет:
- Счётчики ошибок: report_success и report_failure
- Порог алертов: 3+ сбоев → alert
- Дедупликация: не спамить
- Состояние: чтение статуса
- Интеграция: data_schemas валидация
- Декоратор wrap_source
"""

import os, sys, json, time, pytest

sys.path.insert(0, '/opt')
from alert import (
    report_success,
    report_failure,
    get_source_status,
    get_all_status,
    healthcheck_errors,
    wrap_source,
    ERROR_STATE_PATH,
    ERROR_THRESHOLD,
)


class TestErrorState:
    def setup_method(self):
        # Очищаем состояние перед каждым тестом
        self._reset_state()

    def _reset_state(self):
        state = {'_version': 1, 'updated_at': '', 'sources': {}}
        with open(ERROR_STATE_PATH, 'w', encoding='utf-8') as f:
            json.dump(state, f)

    def test_report_success(self):
        """report_success сбрасывает счётчик до 0."""
        for _ in range(3):
            report_failure('test_source', 'error')
        report_success('test_source')
        status = get_source_status('test_source')
        assert status['consecutive_failures'] == 0

    def test_report_failure_count(self):
        """report_failure увеличивает счётчик."""
        report_failure('test_source', 'err1')
        status = get_source_status('test_source')
        assert status['consecutive_failures'] == 1

    def test_failure_below_threshold(self):
        """Меньше порога → нет алерта."""
        for i in range(ERROR_THRESHOLD - 1):
            result = report_failure('test_source', f'err{i}')
            assert result is None  # нет алерта

    def test_failure_at_threshold(self):
        """При пороге → возвращается текст алерта."""
        result = None
        for i in range(ERROR_THRESHOLD):
            result = report_failure('test_source', f'err{i}')
        assert result is not None
        assert 'test_source' in result
        assert str(ERROR_THRESHOLD) in result

    def test_alert_deduplication(self):
        """После алерта — повторные сбои не спамят (тишина 1ч)."""
        # Первые 3 сбоя — алерт
        for i in range(ERROR_THRESHOLD):
            report_failure('test_source', f'err{i}')
        # Ещё 2 сбоя — тишина (дедупликация)
        r1 = report_failure('test_source', 'err_extra1')
        assert r1 is None  # дедупликация

    def test_multiple_sources(self):
        """Разные источники — независимые счётчики."""
        report_failure('src_a', 'err')
        report_failure('src_b', 'err')
        report_failure('src_b', 'err')
        status_a = get_source_status('src_a')
        status_b = get_source_status('src_b')
        assert status_a['consecutive_failures'] == 1
        assert status_b['consecutive_failures'] == 2


class TestHealthcheck:
    def setup_method(self):
        state = {'_version': 1, 'updated_at': '', 'sources': {}}
        with open(ERROR_STATE_PATH, 'w', encoding='utf-8') as f:
            json.dump(state, f)

    def test_healthcheck_clean(self):
        """Без ошибок → 0 проблем."""
        report_success('src_a')
        n = healthcheck_errors()
        assert n == 0

    def test_healthcheck_with_errors(self):
        """С ошибками → проблемы найдены."""
        for _ in range(ERROR_THRESHOLD):
            report_failure('src_crash', 'broken')
        n = healthcheck_errors()
        assert n >= 1

    def test_get_all_status(self):
        """get_all_status возвращает список источников."""
        all_s = get_all_status()
        assert 'sources' in all_s
        assert 'updated_at' in all_s


class TestWrapSource:
    def setup_method(self):
        state = {'_version': 1, 'updated_at': '', 'sources': {}}
        with open(ERROR_STATE_PATH, 'w', encoding='utf-8') as f:
            json.dump(state, f)

    def test_wrap_success(self):
        """Успешная функция → report_success вызван."""
        @wrap_source('wrapped_test')
        def good_func():
            return 'ok'

        result = good_func()
        status = get_source_status('wrapped_test')
        assert result == 'ok'
        assert status['consecutive_failures'] == 0

    def test_wrap_failure(self):
        """Падающая функция → report_failure вызван."""
        @wrap_source('wrapped_fail')
        def bad_func():
            raise ValueError('test error')

        with pytest.raises(ValueError):
            bad_func()
        status = get_source_status('wrapped_fail')
        assert status['consecutive_failures'] >= 1
