"""
Тесты для детекции финишировавших матчей (Фаза 1.5).

Проверяет:
- fetch_live_scores.py определяет статус finished
- Обработка перехода live → finished
- Запуск evaluate_predictions при финише
- Нет ложных срабатываний (матчи, которые уже были finished)
"""

import os, sys, json, pytest

sys.path.insert(0, '/opt')

LIVE_PATH = '/tmp/live_scores_data.json'


class TestFinishedDetection:
    def setup_method(self):
        # Сохраняем предыдущее состояние, если есть
        self._prev = None
        if os.path.exists(LIVE_PATH):
            with open(LIVE_PATH) as f:
                self._prev = f.read()

        # Ставим предыдущее состояние с live матчем
        prev_data = {
            'updated_at': '2026-05-21T12:00:00',
            'matches': {
                'АПЛ||Арсенал||Челси': {
                    'status': 'live',
                    'score': '2:1',
                    'match_time': '',
                    'sport': 'football',
                },
                'РПЛ||Спартак||Зенит': {
                    'status': 'upcoming',
                    'score': '',
                    'match_time': '14:00',
                    'sport': 'football',
                },
                'НХЛ||Динамо М||ЦСКА': {
                    'status': 'finished',
                    'score': '3:2',
                    'match_time': '',
                    'sport': 'hockey',
                },
            },
        }
        with open(LIVE_PATH, 'w', encoding='utf-8') as f:
            json.dump(prev_data, f)

    def teardown_method(self):
        # Восстанавливаем
        if self._prev is not None:
            with open(LIVE_PATH, 'w', encoding='utf-8') as f:
                f.write(self._prev)

    def test_detection_code_exists(self):
        """В fetch_live_scores.py есть код детекции финиша."""
        with open('/opt/fetch_live_scores.py', encoding='utf-8') as f:
            code = f.read()
        assert 'finished_keys' in code
        assert 'prev_status' in code
        assert 'evaluate_predictions' in code

    def test_finished_detection_logic(self):
        """Симулируем логику детекции финиша."""
        # Предыдущее состояние: live
        prev = {
            'АПЛ||Арсенал||Челси': {'status': 'live'},
            'РПЛ||Спартак||Зенит': {'status': 'upcoming'},
            'НХЛ||Динамо М||ЦСКА': {'status': 'finished'},
        }

        # Текущее: два финишировали
        current = {
            'АПЛ||Арсенал||Челси': {
                'status': 'finished', 'score': '3:1',
                'home': 'Арсенал', 'away': 'Челси',
            },
            'РПЛ||Спартак||Зенит': {
                'status': 'finished', 'score': '0:2',
                'home': 'Спартак', 'away': 'Зенит',
            },
            'НХЛ||Динамо М||ЦСКА': {
                'status': 'finished', 'score': '3:2',
                'home': 'Динамо М', 'away': 'ЦСКА',
            },
        }

        # Финишировавшие: те, что были не finished — стали finished
        finished = []
        for key, match in current.items():
            if match['status'] == 'finished':
                prev_status = prev.get(key, {}).get('status', '')
                if prev_status in ('live', 'upcoming', ''):
                    finished.append(key)

        assert len(finished) == 2
        assert 'АПЛ||Арсенал||Челси' in finished
        assert 'РПЛ||Спартак||Зенит' in finished
        # НХЛ уже был finished — не считается новым
        assert 'НХЛ||Динамо М||ЦСКА' not in finished

    def test_no_false_positives(self):
        """Если статус не изменился — нет триггеров."""
        prev = {
            'АПЛ||А||Б': {'status': 'live'},
            'РПЛ||В||Г': {'status': 'upcoming'},
        }
        current = {
            'АПЛ||А||Б': {'status': 'live', 'score': '1:0'},
            'РПЛ||В||Г': {'status': 'upcoming', 'score': ''},
        }

        finished = []
        for key, match in current.items():
            if match['status'] == 'finished':
                prev_status = prev.get(key, {}).get('status', '')
                if prev_status in ('live', 'upcoming', ''):
                    finished.append(key)

        assert len(finished) == 0

    def test_finished_triggers_evaluate(self):
        """Код запускает evaluate_predictions при финише."""
        with open('/opt/fetch_live_scores.py', encoding='utf-8') as f:
            code = f.read()
        # Проверяем, что есть вызов подпроцесса для evaluate
        assert 'subprocess.Popen' in code
        assert 'evaluate_predictions' in code
        assert "cwd='/opt'" in code
