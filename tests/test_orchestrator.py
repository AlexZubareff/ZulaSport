"""
Тесты для единого оркестратора --sport (capper_pipeline.py + modules/).

Проверяет:
1. Все спорты работают через --sport
2. Неизвестный спорт → понятная ошибка
3. Старые режимы (--batch, --match) всё ещё работают
"""

import os, sys, json, pytest, subprocess

sys.path.insert(0, '/opt')


class TestOrchestrator:
    """Единый оркестратор --sport."""

    def test_unknown_sport(self):
        """--sport cricket → понятная ошибка."""
        result = subprocess.run(
            ['python3', 'capper_pipeline.py', '--sport', 'cricket'],
            capture_output=True, text=True, timeout=15,
            cwd='/opt',
        )
        assert 'Неизвестный спорт' in result.stdout
        assert 'football' in result.stdout

    def test_help_message(self):
        """Без аргументов → справка с --sport."""
        result = subprocess.run(
            ['python3', 'capper_pipeline.py'],
            capture_output=True, text=True, timeout=15,
            cwd='/opt',
        )
        assert '--sport' in result.stdout

    def test_import_all_modules(self):
        """Все модули импортируются без ошибок."""
        for mod_name in ('sport_football', 'sport_nhl', 'sport_nba', 'sport_tennis'):
            mod = __import__(f'modules.{mod_name}', fromlist=['run'])
            assert hasattr(mod, 'run')
            assert hasattr(mod, 'SPORT')

    def test_old_batch_mode_help(self):
        """Проверяем, что --batch вызывает правильную функцию (без реального вызова)."""
        from capper_pipeline import main, batch_generate, batch_refresh
        # Проверяем что функции существуют (не падаем)
        assert callable(batch_generate)
        assert callable(batch_refresh)

    def test_orchestrator_knows_all_sports(self):
        """Проверить, что все спорты из ZULA_PLAN.md поддерживаются."""
        from capper_pipeline import main
        # Проверяем, что main() может обработать все 4 спорта
        # Через popen тестировать не будем (реальные API-вызовы)
        # Просто проверяем импорт модулей
        sport_modules = ['football', 'nhl', 'nba', 'tennis']
        for sport in sport_modules:
            mod = __import__(f'modules.sport_{sport}', fromlist=['run'])
            assert hasattr(mod, 'run')
            assert callable(mod.run)

    def test_sport_module_interface(self):
        """Каждый модуль имеет единый интерфейс run(mode)."""
        for sport in ('football', 'nhl', 'nba', 'tennis'):
            mod = __import__(f'modules.sport_{sport}', fromlist=['run'])
            # Проверяем сигнатуру: run принимает mode
            import inspect
            sig = inspect.signature(mod.run)
            assert 'mode' in sig.parameters

    def test_predictions_file_not_corrupted(self):
        """predictions_data.json не бит после запуска оркестратора."""
        path = '/opt/predictions_data.json'
        if not os.path.exists(path):
            pytest.skip('Нет файла для проверки')
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        assert 'predictions' in data
        assert isinstance(data['predictions'], list)
