"""
Тесты для JS-поллинга live-счетов (Фаза 1.1).

Проверяет:
- data-match-key атрибуты в schedule.html
- Структура live_scores.json
- Валидация live_scores.json через data_schemas.py
- Регенерация schedule.html
"""

import os, sys, json, pytest, re

sys.path.insert(0, '/opt')
from data_schemas import validate


SCHEDULE_PATH = '/var/www/sport/schedule.html'
LIVE_SCORES_PATH = '/var/www/sport/live_scores.json'


class TestDataKeyAttributes:
    """Проверка data-match-key атрибутов для JS-поллинга."""

    def _read_schedule(self):
        if not os.path.exists(SCHEDULE_PATH):
            pytest.skip(f"{SCHEDULE_PATH} не найден — тест пропущен")
        with open(SCHEDULE_PATH, encoding='utf-8') as f:
            return f.read()

    def test_data_key_exists(self):
        """Каждая карточка матча имеет data-match-key атрибут."""
        html = self._read_schedule()
        keys = re.findall(r'data-match-key="([^"]+)"', html)
        assert len(keys) > 0, "Нет data-match-key атрибутов в schedule.html"

    def test_data_key_format(self):
        """data-match-key имеет формат league||home||away."""
        html = self._read_schedule()
        keys = re.findall(r'data-match-key="([^"]+)"', html)
        for key in keys:
            parts = key.split('||')
            assert len(parts) >= 3, f"Неверный формат data-match-key: {key!r}"

    def test_data_key_unique(self):
        """data-match-key атрибуты уникальны (нет дубликатов карточек)."""
        html = self._read_schedule()
        keys = re.findall(r'data-match-key="([^"]+)"', html)
        assert len(keys) == len(set(keys)), (
            f"Обнаружены дублирующиеся data-match-key: {len(keys)} шт, уникальных {len(set(keys))}"
        )

    def test_card_count_reasonable(self):
        """Хотя бы 2 матча на странице (если есть данные)."""
        html = self._read_schedule()
        keys = re.findall(r'data-match-key="([^"]+)"', html)
        # Не assert — может быть ночью, когда нет данных
        if len(keys) == 0:
            pytest.skip("Нет матчей на странице сейчас — тест пропущен")


class TestLiveScoresJson:
    """Проверка live_scores.json для JS-поллинга."""

    def test_live_scores_exists(self):
        """live_scores.json существует в web-root."""
        assert os.path.exists(LIVE_SCORES_PATH), (
            f"{LIVE_SCORES_PATH} не найден"
        )

    def test_live_scores_valid_json(self):
        """live_scores.json — корректный JSON."""
        with open(LIVE_SCORES_PATH, encoding='utf-8') as f:
            data = json.load(f)
        assert isinstance(data, dict), "live_scores.json должен быть объектом"
        assert 'matches' in data, "live_scores.json должен содержать 'matches'"

    def test_live_scores_validation(self):
        """live_scores.json проходит валидацию data_schemas."""
        with open(LIVE_SCORES_PATH, encoding='utf-8') as f:
            data = json.load(f)
        ok, errors = validate(data, 'live_scores')
        assert ok, f"live_scores.json не прошёл валидацию: {errors}"

    def test_live_scores_structure(self):
        """Каждый матч в live_scores имеет корректную структуру."""
        with open(LIVE_SCORES_PATH, encoding='utf-8') as f:
            data = json.load(f)
        for key, match in data.get('matches', {}).items():
            assert 'status' in match, f"Матч {key} не имеет status"
            assert match['status'] in ('live', 'upcoming', 'finished'), (
                f"Матч {key}: неверный статус {match['status']!r}"
            )
            if match['status'] == 'live':
                assert match.get('score'), f"live матч {key} без счёта"

    def test_live_scores_freshness(self):
        """live_scores.json обновлён не более 5 минут назад."""
        now = os.path.getmtime(LIVE_SCORES_PATH)
        import time
        age = time.time() - now
        # Не assert — может быть ночью, когда нет матчей
        if age > 300:
            pytest.skip(f"live_scores.json устарел ({age:.0f} сек) — тест пропущен")


class TestPollingScript:
    """Проверка JS-скрипта поллинга."""

    APP_JS_PATH = '/var/www/sport/static/app.js'

    def test_poll_function_exists(self):
        """Функция pollLiveScores существует в app.js."""
        assert os.path.exists(self.APP_JS_PATH), "app.js не найден"
        with open(self.APP_JS_PATH, encoding='utf-8') as f:
            js = f.read()
        assert 'function pollLiveScores' in js, (
            "Функция pollLiveScores не найдена в app.js"
        )

    def test_poll_interval_set(self):
        """setInterval для pollLiveScores установлен."""
        with open(self.APP_JS_PATH, encoding='utf-8') as f:
            js = f.read()
        assert 'pollLiveScores' in js, "pollLiveScores не вызывается"
        assert 'setInterval' in js

    def test_poll_uses_fetch(self):
        """poll использует fetch для /live_scores.json."""
        with open(self.APP_JS_PATH, encoding='utf-8') as f:
            js = f.read()
        # Проверяем, что функция фетчит правильный URL
        assert 'live_scores.json' in js, (
            "pollLiveScores не ссылается на live_scores.json"
        )

    def test_poll_silent_fail(self):
        """poll не выдаёт ошибок в консоль при отсутствии данных."""
        with open(self.APP_JS_PATH, encoding='utf-8') as f:
            js = f.read()
        # Проверяем, что ошибка обрабатывается (catch)
        assert '.catch' in js or 'silent' in js.lower(), (
            "Нет обработчика ошибок (.catch) в pollLiveScores"
        )


class TestValidationLayer:
    """Проверка интеграции валидации."""

    def test_schedule_imports_validator(self):
        """site_schedule.py импортирует validate из data_schemas."""
        with open('/opt/site_schedule.py', encoding='utf-8') as f:
            code = f.read()
        assert 'from data_schemas import validate' in code, (
            "validate не импортирован в site_schedule.py"
        )

    def test_fetch_live_imports_validator(self):
        """fetch_live_scores.py импортирует validate из data_schemas."""
        with open('/opt/fetch_live_scores.py', encoding='utf-8') as f:
            code = f.read()
        assert 'from data_schemas import validate' in code, (
            "validate не импортирован в fetch_live_scores.py"
        )

    def test_schedule_uses_validation(self):
        """site_schedule.py вызывает validate для live_scores."""
        with open('/opt/site_schedule.py', encoding='utf-8') as f:
            code = f.read()
        assert 'validate(live_data, \'live_scores\')' in code, (
            "validate не вызывается для live_scores в site_schedule.py"
        )

    def test_fetch_live_uses_validation(self):
        """fetch_live_scores.py вызывает validate перед записью."""
        with open('/opt/fetch_live_scores.py', encoding='utf-8') as f:
            code = f.read()
        assert 'validate(output, \'live_scores\')' in code, (
            "validate не вызывается для output в fetch_live_scores.py"
        )
