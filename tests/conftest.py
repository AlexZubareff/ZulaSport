"""
Фикстуры и хелперы для тестов пайплайна Zula Спорт.
"""

import os, json, shutil, pytest
from datetime import datetime, timedelta, timezone

MOW = timedelta(hours=3)
UTC = timezone.utc

# ─── Образцы тестовых данных ────────────────────────────────────────

def sample_tv_channels(today_fmt='16.05.2026', tomorrow_fmt='20260517'):
    """Образец tv_channels_data.json с матчами на сегодня и завтра."""
    # Сегодняшние матчи (не должны попадать в фильтр next_date)
    today_matches = [
        {'sport': 'football', 'league': 'Бундеслига', 'source': 'static',
         'home': 'Бавария', 'away': 'Дортмунд', 'time': '18:30',
         'channels': [], 'game_id': 1001},
        {'sport': 'football', 'league': 'Бундеслига', 'source': 'static',
         'home': 'Лейпциг', 'away': 'Шальке', 'time': '20:00',
         'channels': [], 'game_id': 1002},
        {'sport': 'hockey', 'league': 'НХЛ', 'source': 'espn',
         'home': 'Рейнджерс', 'away': 'Бостон', 'time': '02:00',
         'channels': [{'country': 'USA', 'channel': 'ESPN'}]},
    ]
    # Завтрашние матчи (должны попадать в фильтр next_date)
    tomorrow_matches = [
        {'sport': 'football', 'league': 'АПЛ', 'source': 'matchtv',
         'home': 'Ман Сити', 'away': 'Арсенал', 'time': '17:00',
         'channels': [{'country': 'RU', 'channel': 'Матч ТВ'}], 'game_id': 2001},
        {'sport': 'football', 'league': 'Ла Лига', 'source': 'static',
         'home': 'Барса', 'away': 'Реал', 'time': '22:00',
         'channels': [], 'game_id': 2002},
        {'sport': 'basketball', 'league': 'NBA', 'source': 'espn',
         'home': 'Лейкерс', 'away': 'Селтикс', 'time': '03:00',
         'channels': [{'country': 'USA', 'channel': 'TNT'}]},
    ]
    return {
        'date': tomorrow_fmt,
        'updated_at': '2026-05-16T08:00:00',
        'matches': today_matches + tomorrow_matches,
    }


def sample_upcoming(today_fmt='16.05.2026'):
    """Образец upcoming_matches.json с матчами на сегодня."""
    return {
        'date': today_fmt,
        'matches': [
            {'home': 'Бавария', 'away': 'Дортмунд', 'time': '18:30',
             'game_id': 1001, 'league': 'Бундеслига', 'league_id': 78},
            {'home': 'Лейпциг', 'away': 'Шальке', 'time': '20:00',
             'game_id': 1002, 'league': 'Бундеслига', 'league_id': 78},
        ],
    }


def sample_predictions():
    """Образец predictions_data.json."""
    return {
        'predictions': [
            {
                'home': 'Ман Сити', 'away': 'Арсенал',
                'league': 'АПЛ', 'time': '17:00', 'game_id': 2001,
                'verdict': 'Победа хозяев',
                'prediction': 'Ман Сити явный фаворит. Glicko рейтинг...',
                'odds': {'home': 1.5, 'draw': 4.2, 'away': 6.5},
                'totals': {'total_line': 2.5, 'over': 1.7, 'under': 2.1},
                'glicko': {'home_prob': 0.65, 'draw_prob': 0.20, 'away_prob': 0.15,
                           'home_rating': 1600, 'away_rating': 1500,
                           'home_xg': 2.1, 'away_xg': 1.2},
                'has_lineups': False,
                'generated_at': '2026-05-16T07:00:00',
            }
        ],
        'generated_at': '2026-05-16T07:00:00',
    }


def sample_prediction_leagues():
    """Образец prediction_leagues.json (активные лиги)."""
    return {
        '_comment': 'тестовый',
        'active': {
            'АПЛ': ['sstats:39'],
            'Ла Лига': ['sstats:140'],
            'Серия А': ['sstats:135'],
            'Бундеслига': ['sstats:78'],
            'Лига 1': ['sstats:61'],
            'РПЛ': ['sstats:235'],
        },
    }


# ─── Хелперы для тестов ─────────────────────────────────────────────

_BACKUP_DIR = '/tmp/test_backups'


def backup_files(*paths):
    """Сохранить копии файлов перед тестом."""
    os.makedirs(_BACKUP_DIR, exist_ok=True)
    for p in paths:
        if os.path.exists(p):
            name = os.path.basename(p)
            shutil.copy2(p, os.path.join(_BACKUP_DIR, name + '.bak'))


def restore_files(*paths):
    """Восстановить файлы после теста."""
    for p in paths:
        name = os.path.basename(p)
        bak = os.path.join(_BACKUP_DIR, name + '.bak')
        if os.path.exists(bak):
            shutil.copy2(bak, p)
            os.remove(bak)


def write_fixture(path, data):
    """Записать тестовые данные в файл."""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


@pytest.fixture
def fixture_tv_channels(tmp_path):
    """Создать тестовый tv_channels_data.json."""
    data = sample_tv_channels()
    path = tmp_path / 'tv_channels_data.json'
    write_fixture(path, data)
    return str(path), data


@pytest.fixture
def fixture_upcoming(tmp_path):
    """Создать тестовый upcoming_matches.json."""
    data = sample_upcoming()
    path = tmp_path / 'upcoming_matches.json'
    write_fixture(path, data)
    return str(path), data


@pytest.fixture
def fixture_predictions(tmp_path):
    """Создать тестовый predictions_data.json."""
    data = sample_predictions()
    path = tmp_path / 'predictions_data.json'
    write_fixture(path, data)
    return str(path), data
