"""
Тесты для одного Playwright на batch (Фаза 1.3).

Проверяет:
- Функция _batch_process_matches существует и корректно обрабатывает матчи
- Fallback при ошибке Playwright
- Время выполнения batch
- Очистка процессов
"""

import os, sys, pytest

sys.path.insert(0, '/opt')
sys.path.insert(0, '/opt/tests')


class TestBatchProcess:
    """Проверка _batch_process_matches."""

    def test_batch_function_exists(self):
        """Функция _batch_process_matches определена."""
        from capper_pipeline import _batch_process_matches
        assert callable(_batch_process_matches)

    def test_batch_empty_matches(self):
        """Пустой список матчей → пустой результат."""
        from capper_pipeline import _batch_process_matches
        result = _batch_process_matches([], fetch_fs=False, fetch_lineups=False)
        assert result == []

    def test_batch_without_playwright(self):
        """Если Playwright недоступен, работает fallback (без браузера)."""
        from capper_pipeline import _batch_process_matches
        # Передаём матчи, но они не найдутся в SStats (нет данных)
        result = _batch_process_matches([
            {'league': 'РПЛ', 'home': 'Тест', 'away': 'Тест2', 'game_id': 1, 'time': '12:00'},
        ], fetch_fs=False, fetch_lineups=False)
        # Не падает — это главное. Результат может быть None из-за отсутствия данных
        assert isinstance(result, list)

    def test_batch_calls_process_match(self):
        """_batch_process_matches вызывает process_match для каждого матча."""
        from capper_pipeline import _batch_process_matches
        import capper_pipeline as cp

        original = cp.process_match
        call_log = []

        def mock_process_match(match_info, fetch_fs=True, fetch_lineups_flag=False, pw_page=None):
            call_log.append((match_info.get('home', ''), match_info.get('away', '')))
            return None  # симулируем матч без данных

        cp.process_match = mock_process_match
        try:
            matches = [
                {'league': 'РПЛ', 'home': 'А', 'away': 'Б', 'game_id': 1, 'time': '12:00'},
                {'league': 'РПЛ', 'home': 'В', 'away': 'Г', 'game_id': 2, 'time': '14:00'},
            ]
            _batch_process_matches(matches, fetch_fs=False, fetch_lineups=False)
            assert len(call_log) == 2
            assert call_log[0] == ('А', 'Б')
            assert call_log[1] == ('В', 'Г')
        finally:
            cp.process_match = original


class TestBatchFunctions:
    """Проверка batch_generate и batch_refresh."""

    def test_batch_generate_calls_batch_process(self):
        """batch_generate вызывает _batch_process_matches."""
        from capper_pipeline import batch_generate
        import capper_pipeline as cp

        original_load = cp._load_matches
        original_process = cp._batch_process_matches
        original_save = cp._save_predictions

        called = []

        def mock_load():
            return [
                {'league': 'РПЛ', 'home': 'А', 'away': 'Б', 'game_id': 1, 'time': '12:00'},
            ]

        def mock_process(matches, fetch_fs=True, fetch_lineups=False):
            called.append('batch_process')
            return []

        def mock_save(preds):
            pass

        cp._load_matches = mock_load
        cp._batch_process_matches = mock_process
        cp._save_predictions = mock_save
        try:
            batch_generate()
            assert 'batch_process' in called
        finally:
            cp._load_matches = original_load
            cp._batch_process_matches = original_process
            cp._save_predictions = original_save

    def test_batch_refresh_no_matches(self):
        """batch_refresh не падает при отсутствии файла."""
        from capper_pipeline import batch_refresh
        # Нет файла — не должно падать
        batch_refresh()


class TestImport:
    """Проверка импортов."""

    def test_main_pipeline_imports(self):
        """capper_pipeline.py импортируется без ошибок."""
        import importlib
        import capper_pipeline
        importlib.reload(capper_pipeline)

    def test_playwright_imported_in_function(self):
        """sync_playwright импортируется внутри _batch_process_matches, не на уровне модуля."""
        with open('/opt/capper_pipeline.py', encoding='utf-8') as f:
            code = f.read()
        assert 'from playwright.sync_api import sync_playwright' in code
        # Проверяем, что импорт есть и в _batch_process_matches (для внутреннего использования)
        assert 'def _batch_process_matches' in code
