# Анализ: что в БД, что оставить как есть

## Текущая архитектура данных

```
┌─────────────────────────────────────────────────────┐
│  SStats API   Flashscore   ESPN   matchtv.ru        │
└────────┬────────────────────┬───────────────────────┘
         ▼                    ▼
   ┌──────────┐    ┌─────────────────┐
   │daily     │    │tv_channels      │ ← кеш на сегодня/завтра
   │_results  │    │upcoming_matches │
   │_data.json│    │_data.json       │
   └────┬─────┘    └────────┬────────┘
        │                   │
        ▼                   ▼
   ┌──────────────────────────────────────────┐
   │  capper_pipeline.py                       │
   │  ┌────────────────────────────────────┐  │
   │  │  predictions_data.json (очередь)   │  │
   │  │  predictions_history.json (архив)  │  │
   │  └────────────────────────────────────┘  │
   └──────────────────────────────────────────┘
        │
        ▼
   ┌──────────────────────────────────────────┐
   │  evaluate_predictions.py                  │
   │  читает live_scores + daily_results      │
   │  оценивает → двигает из очереди в архив   │
   └──────────────────────────────────────────┘
        │
        ▼
   ┌──────────────────────────────────────────┐
   │  generate_site.py → HTML (nginx)         │
   │  send_prediction_stats.py → Telegram     │
   │  capper_pipeline (few-shot, stats)       │
   └──────────────────────────────────────────┘
```

---

## Что храним и что меняем

### 📦 В БД — Predictions (главное)

| Сейчас | Размер | Частота записи | Читают |
|--------|--------|---------------|--------|
| `predictions_data.json` | 11 KB | Каждый batch/refresh | capper, evaluate, site |
| `predictions_history.json` | ~50 KB | Каждая evaluate оценка | capper, evaluate, stats |

**Проблемы:**
- Нет ACID — race condition убил историю
- Нет индексов — поиск похожих матчей (few-shot) полный перебор
- Нет аналитики в реальном времени
- Нет доступа извне (ЛК, админка)

**Решение:** одна таблица `predictions` в Postgres.

### 📄 Оставить как файлы — оперативные данные

Данные, которые живут < 24ч и перезаписываются целиком каждый раз:

| Файл | Размер | Живёт | Почему не в БД |
|------|--------|-------|----------------|
| `live_scores_data.json` | 1 KB | 15 мин | Эфемерен, перезаписывается целиком, не нужны запросы |
| `daily_results_data.json` | 1 KB | 1 день | Перезаписывается раз в день, нужен только evaluate |
| `tv_channels_data.json` | 7 KB | 1-2 дня | Кеш, нужен только capper`у |
| `upcoming_matches.json` | 1 KB | 1 день | Производный от tv_channels |

### 📄 Оставить как файлы — контент и модели

| Файл/дир | Размер | Почему не в БД |
|----------|--------|----------------|
| `news_data.json` + `news.html` | ~600 KB | Контент, нужен только генерации сайта |
| `xgb_win.json`, `xgb_total.json` | ~500 KB | Бинарные ML-модели |
| `dataset.json`, `dataset.csv` | ~1.6 MB | Тренировочные данные, нужны только train.py |
| `sport_cache.json`, `team_*.json` | ~500 KB | Кеши API, живут своей жизнью |
| Сайт (`*.html`) | ~450 KB | Статика, отдаётся nginx`ом |

---

## Структура БД

### Таблица: `predictions`

```sql
-- Единое хранилище всех прогнозов.
-- Статус = upcoming → очередь, finished → архив.

CREATE TABLE predictions (
    id              SERIAL PRIMARY KEY,

    -- Ключевые поля / бизнес-идентификатор
    match_id        TEXT UNIQUE,           -- дата||лига||home||away (для обратной совместимости)
    league          TEXT NOT NULL,
    home            TEXT NOT NULL,
    away            TEXT NOT NULL,
    match_time      TEXT,                  -- HH:MM
    date            TEXT,                  -- DD.MM.YYYY

    -- Статус жизненного цикла
    status          TEXT NOT NULL DEFAULT 'upcoming'
                    CHECK (status IN ('upcoming', 'finished')),

    -- Результат матча (заполняется evaluate)
    score           TEXT,                  -- "3:1"
    actual_winner   TEXT,                  -- home / draw / away
    actual_total    TEXT,                  -- over / under
    total_line      REAL,                  -- 2.5

    -- Прогноз (текст)
    prediction_text TEXT,
    verdict         TEXT,

    -- Исходные коэффициенты
    odds_home       REAL,
    odds_draw       REAL,
    odds_away       REAL,
    odds_over       REAL,
    odds_under      REAL,

    -- Glicko
    glicko_home_prob    REAL,
    glicko_draw_prob    REAL,
    glicko_away_prob    REAL,
    glicko_home_rating  REAL,
    glicko_away_rating  REAL,
    glicko_home_xg      REAL,
    glicko_away_xg      REAL,

    -- XGBoost вердикт
    xgb_win_pred    TEXT,                  -- home/draw/away
    xgb_win_conf    REAL,
    xgb_total_pred  TEXT,                  -- over/under
    xgb_total_conf  REAL,

    -- Результат оценки (correct / incorrect / NULL если не оценён)
    result_win      TEXT CHECK (result_win IN ('correct', 'incorrect', NULL)),
    result_total    TEXT CHECK (result_total IN ('correct', 'incorrect', NULL)),

    -- Мета
    has_lineups     BOOLEAN DEFAULT FALSE,
    generated_at    TIMESTAMPTZ,
    evaluated_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),

    -- SStats game_id (для перепроверки)
    game_id         INTEGER
);

-- Индексы для частых запросов
CREATE INDEX idx_predictions_status    ON predictions(status);
CREATE INDEX idx_predictions_league    ON predictions(league);
CREATE INDEX idx_predictions_date      ON predictions(date);
CREATE INDEX idx_predictions_generated ON predictions(generated_at);
CREATE INDEX idx_predictions_result    ON predictions(result_win, result_total);
```

### Таблица: `prediction_log` (опционально, append-only)

```sql
-- Аудит всех изменений статуса прогнозов.
-- Для отладки и истории изменений.
CREATE TABLE prediction_log (
    id          SERIAL PRIMARY KEY,
    match_id    TEXT NOT NULL,
    event       TEXT NOT NULL,   -- created / evaluated / updated
    old_status  TEXT,
    new_status  TEXT,
    details     JSONB,
    logged_at   TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Как будет выглядеть интеграция

### Новый файл: `/opt/db.py`

```python
import psycopg2
from psycopg2.extras import RealDictCursor

DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'dbname': 'predictions_db',
    'user': 'predictions_user',
    'password': '...',
}

def get_conn():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)

def save_prediction(pred: dict):
    """INSERT ... ON CONFLICT (match_id) DO UPDATE"""
    
def get_queue(league: str = None) -> list:
    """SELECT * WHERE status='upcoming' ORDER BY match_time"""
    
def get_history(league: str = None, limit: int = 100) -> list:
    """SELECT * WHERE status='finished' ORDER BY evaluated_at DESC"""
    
def get_stats() -> dict:
    """SELECT result_win, COUNT(*) ... GROUP BY ..."""
    
def find_similar(glicko_home_prob, glicko_draw_prob, glicko_away_prob, league):
    """Поиск похожих матчей (ORDER BY ABS(home_prob - x) + ...)"""
```

### Замена в скриптах

| Скрипт | Сейчас | Станет |
|--------|--------|--------|
| `capper_pipeline.py` | `_save_predictions()` → JSON | `db.save_prediction()` |
| `generate_prediction_text()` → read history for few-shot | `db.find_similar()` |
| `_build_capper_stats()` → read history summary | `db.get_stats()` |
| `evaluate_predictions.py` | load JSON → eval → save JSON | `db.get_queue()` → eval → `db.save_prediction()` |
| `send_prediction_stats.py` | read JSON → format → send | `db.get_stats()` → format → send |
| `generate_site.py` / `site_predictions.py` | read JSON → generate HTML | `db.get_queue()` + `db.get_history()` |

### Pipeline меняется так

```diff
- predict.write     → predictions_data.json
- evaluate.read    → predictions_data.json + predictions_history.json
- evaluate.write   → predictions_history.json (перезапись целиком)
+ predict.write    → INSERT INTO predictions
+ evaluate.read    → SELECT * WHERE status='upcoming'
+ evaluate.write   → UPDATE predictions SET status='finished', result_win=...
```

---

## Риски и оценки

| Риск | Вероятность | Митигация |
|------|------------|-----------|
| Postgres упадёт | Низкая | systemd auto-restart + reconnect в db.py |
| Ошибка в миграции (потеряем 3 прогноза) | Средняя | Бекап JSON перед миграцией |
| Тормоза при каждом batch (INSERT) | Низкая | 3-20 записей за раз — копейки |
| Сложность разработки (переписывать 5 скриптов) | Средняя | Заменяем только чтение/запись, логика не меняется |

---

## Резюме

**В БД:** только predictions и связанные статусы.

**Остаётся как есть:** live_scores, daily_results, tv_channels, новости, XGBoost модели, статика сайта.

**Всего затронуто скриптов:** 5 (capper_pipeline, evaluate_predictions, send_prediction_stats, site_predictions, evaluate_healthcheck).

Если ок — ставлю Postgres, создаю `db.py`, делаю миграцию существующих данных, переписываю скрипты. Ориентир — ~2-3 часа на всё.
