"""
Тесты для кеша DeepSeek (Фаза 1.2).

Структура кеша (data_schemas):
- _version, entries { md5_hash: { result, ts, match } }
"""

import os, sys, json, time, hashlib, pytest

sys.path.insert(0, '/opt')
sys.path.insert(0, '/opt/tests')

from capper_common import (
    _prediction_cache_key,
    _load_cache,
    _save_cache,
    call_deepseek_with_cache,
    get_cache_stats,
    clear_cache,
    CACHE_FILE,
    CACHE_VERSION,
)
from data_schemas import validate


SAMPLE_MATCH = {
    'home': 'Спартак',
    'away': 'Зенит',
    'league': 'РПЛ',
}

SAMPLE_SSTATS = {
    'odds': [{'home': 2.5, 'draw': 3.2, 'away': 3.0}],
    'glicko': {
        'home_prob': 0.45,
        'away_prob': 0.30,
        'draw_prob': 0.25,
    },
    'totals': {'total_line': 2.5, 'over': 1.8, 'under': 2.0},
}


class TestCacheKey:
    def test_key_consistency(self):
        """Одинаковые данные → одинаковый хеш."""
        k1 = _prediction_cache_key(SAMPLE_MATCH, SAMPLE_SSTATS)
        k2 = _prediction_cache_key(SAMPLE_MATCH, SAMPLE_SSTATS)
        assert k1 == k2

    def test_key_changes_with_odds(self):
        """Изменение кэфов → разный хеш."""
        k1 = _prediction_cache_key(SAMPLE_MATCH, SAMPLE_SSTATS)
        s2 = {**SAMPLE_SSTATS, 'odds': [{'home': 3.0, 'draw': 3.4, 'away': 2.5}]}
        k2 = _prediction_cache_key(SAMPLE_MATCH, s2)
        assert k1 != k2

    def test_key_changes_with_glicko(self):
        """Изменение Glicko → разный хеш."""
        k1 = _prediction_cache_key(SAMPLE_MATCH, SAMPLE_SSTATS)
        s2 = {**SAMPLE_SSTATS, 'glicko': {'home_prob': 0.6, 'away_prob': 0.2, 'draw_prob': 0.2}}
        k2 = _prediction_cache_key(SAMPLE_MATCH, s2)
        assert k1 != k2

    def test_key_changes_with_teams(self):
        """Другие команды → разный хеш."""
        k1 = _prediction_cache_key(SAMPLE_MATCH, SAMPLE_SSTATS)
        m2 = {'home': 'Динамо', 'away': 'ЦСКА', 'league': 'РПЛ'}
        k2 = _prediction_cache_key(m2, SAMPLE_SSTATS)
        assert k1 != k2

    def test_key_format(self):
        """Хеш — 32 hex-символа (MD5)."""
        key = _prediction_cache_key(SAMPLE_MATCH, SAMPLE_SSTATS)
        assert len(key) == 32
        assert all(c in '0123456789abcdef' for c in key)


class TestCachePersistence:
    def setup_method(self):
        clear_cache()

    def test_save_and_load(self):
        """Сохранили → загрузили — данные целы."""
        _save_cache({'abc123': {'result': 'test', 'ts': time.time(), 'match': 'A — B'}})
        loaded = _load_cache()
        assert 'abc123' in loaded
        assert loaded['abc123']['result'] == 'test'

    def test_cache_ttl(self):
        """Устаревшие записи (>30 мин) не загружаются."""
        old_ts = time.time() - 3600  # 1 час назад
        _save_cache({'old': {'result': 'x', 'ts': old_ts, 'match': 'O — P'}})
        loaded = _load_cache()
        assert 'old' not in loaded

    def test_version_mismatch(self):
        """Несовпадение версии → пустой кеш."""
        data = {'_version': CACHE_VERSION + 99, 'entries': {}}
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        loaded = _load_cache()
        assert loaded == {}

    def test_broken_json(self):
        """Битый JSON → пустой кеш, без падения."""
        with open(CACHE_FILE, 'w') as f:
            f.write('{not json}')
        loaded = _load_cache()
        assert loaded == {}


class TestCacheIntegration:
    def setup_method(self):
        clear_cache()

    def test_cache_hit(self):
        """Кеш попадание: generate_fn не вызывается второй раз."""
        call_count = [0]

        def gen_fn():
            call_count[0] += 1
            return 'Прогноз Спартак — Зенит'

        # Первый вызов — промах
        r1 = call_deepseek_with_cache(SAMPLE_MATCH, SAMPLE_SSTATS, gen_fn)
        assert r1 == 'Прогноз Спартак — Зенит'
        assert call_count[0] == 1

        # Второй вызов — попадание
        r2 = call_deepseek_with_cache(SAMPLE_MATCH, SAMPLE_SSTATS, gen_fn)
        assert r2 == 'Прогноз Спартак — Зенит'
        assert call_count[0] == 1  # не вызывался повторно

    def test_cache_miss_on_change(self):
        """Изменение данных → промах кеша, вызов generate_fn."""
        call_count = [0]

        def gen_fn():
            call_count[0] += 1
            return f'Прогноз #{call_count[0]}'

        r1 = call_deepseek_with_cache(SAMPLE_MATCH, SAMPLE_SSTATS, gen_fn)
        assert call_count[0] == 1

        # Меняем кэфы
        s2 = {**SAMPLE_SSTATS, 'odds': [{'home': 4.0, 'draw': 3.5, 'away': 2.0}]}
        r2 = call_deepseek_with_cache(SAMPLE_MATCH, s2, gen_fn)
        assert call_count[0] == 2  # новый вызов
        assert r1 != r2

    def test_force_refresh(self):
        """force_refresh=True → пропускает кеш."""
        call_count = [0]

        def gen_fn():
            call_count[0] += 1
            return f'Прогноз #{call_count[0]}'

        r1 = call_deepseek_with_cache(SAMPLE_MATCH, SAMPLE_SSTATS, gen_fn)
        assert call_count[0] == 1

        r2 = call_deepseek_with_cache(SAMPLE_MATCH, SAMPLE_SSTATS, gen_fn, force_refresh=True)
        assert call_count[0] == 2  # force — пропустил кеш

    def test_cache_stats(self):
        """get_cache_stats возвращает корректную статистику."""
        clear_cache()
        stats = get_cache_stats()
        assert stats['total_entries'] == 0

        def gen_fn():
            return 'test'

        call_deepseek_with_cache(SAMPLE_MATCH, SAMPLE_SSTATS, gen_fn)
        stats = get_cache_stats()
        assert stats['total_entries'] == 1
        assert stats['avg_age_sec'] >= 0


class TestCacheSchema:
    def test_cache_passes_validation(self):
        """Структура кеша проходит валидацию data_schemas."""
        data = {
            '_version': CACHE_VERSION,
            'updated_at': '2026-05-21T12:00:00',
            'entries': {
                'abc123': {'result': 'text', 'ts': time.time(), 'match': 'A — B'},
            },
        }
        ok, errors = validate(data, 'deepseek_cache')
        assert ok, f"Ошибки валидации: {errors}"

    def test_cache_schema_missing_fields(self):
        """Без обязательных полей — ошибка валидации."""
        ok, errors = validate({'entries': {}}, 'deepseek_cache')
        assert not ok
        err_str = ' '.join(errors)
        assert '_version' in err_str

    def test_cache_schema_wrong_version_type(self):
        """_version должен быть integer."""
        ok, errors = validate({'_version': '1', 'entries': {}}, 'deepseek_cache')
        assert not ok


class TestDeepSeekPipelineImport:
    """Проверка, что пайплайны импортируют кеш."""

    PIPELINES = [
        '/opt/capper_pipeline.py',
        '/opt/capper_pipeline_nhl.py',
        '/opt/capper_pipeline_nba.py',
        '/opt/capper_pipeline_tennis.py',
    ]

    def test_all_import_capper_common(self):
        """Все пайплайны импортируют call_deepseek_with_cache."""
        for pipe in self.PIPELINES:
            assert os.path.exists(pipe), f"{pipe} не найден"
            with open(pipe, encoding='utf-8') as f:
                code = f.read()
            assert 'from capper_common import' in code, (
                f"{pipe} не импортирует capper_common"
            )

    def test_all_use_cache(self):
        """Все пайплайны вызывают call_deepseek_with_cache."""
        for pipe in self.PIPELINES:
            with open(pipe, encoding='utf-8') as f:
                code = f.read()
            assert 'call_deepseek_with_cache' in code, (
                f"{pipe} не использует call_deepseek_with_cache"
            )
