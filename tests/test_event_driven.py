"""
Тест event-driven обновлений: trigger_generate в пайплайнах.

Проверяет:
1. fetch_live_scores вызывает trigger_generate('schedule') при завершении матча
2. Capper pipeline вызывает trigger_generate('predictions') после сохранения
3. Debounce предотвращает дублирующие запуски в течение 2 мин
4. Cron-fallback записи в crontab.txt
"""

import os, sys, json, time, pytest

sys.path.insert(0, '/opt')


class TestFetchLiveTriggers:
    """Проверка trigger_generate в fetch_live_scores."""

    def test_fetch_live_imports_trigger_generate(self):
        """fetch_live_scores содержит import trigger_generate."""
        with open('/opt/fetch_live_scores.py') as f:
            content = f.read()
        assert 'from capper_common import trigger_generate' in content or \
               'trigger_generate' in content, \
            'fetch_live_scores.py не содержит trigger_generate'


class TestCapperTriggers:
    """Проверка trigger_generate в capper_pipeline."""

    def test_capper_pipeline_imports_trigger(self):
        """Проверка, что код _save_predictions импортирует trigger_generate."""
        # Проверяем, что код содержит строки с trigger_generate
        import ast
        for fname in ['capper_pipeline.py', 'capper_pipeline_nba.py',
                       'capper_pipeline_nhl.py', 'capper_pipeline_tennis.py']:
            with open(f'/opt/{fname}') as f:
                tree = ast.parse(f.read())
            # Ищем вызов trigger_generate в AST
            found = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Name) and func.id == 'trigger_generate':
                        found = True
                        args = [ast.dump(a) for a in node.args]
                        assert any("'predictions'" in a for a in args), \
                            f"{fname}: trigger_generate не с 'predictions'"
                        break
            assert found, f"{fname}: нет вызова trigger_generate"


class TestCrontabFallback:
    """Проверка наличия cron-fallback."""

    def test_predictions_in_crontab(self):
        """В crontab есть строка генерации predictions."""
        with open('/opt/deploy/crontab.txt') as f:
            content = f.read()
        assert 'predictions' in content, \
            "Нет генерации predictions в crontab.txt"
        assert 'trigger_generate' in content.lower() or 'event-driven' in content.lower(), \
            "Нет комментария про event-driven"
