# Полный анализ данных для БД

## Все сущности проекта

| # | Сущность | Сейчас | Объём | Жизненный цикл |
|---|----------|--------|-------|----------------|
| 1 | **Predictions** | `predictions_data.json` + `predictions_history.json` | ~50 KB | Постоянно |
| 2 | **Training data** | `dataset.json` + `dataset.csv` | 1.6 MB | Растёт с каждой оценкой |
| 3 | **Model versions** | Не хранится | — | Каждое обучение |
| 4 | **Matches / results** | `daily_results_data.json` | 1 KB | 1 день |
| 5 | **Matches / schedule** | `tv_channels_data.json` + `upcoming_matches.json` | 8 KB | 3 дня |
| 6 | **Live scores** | `live_scores_data.json` | 1 KB | 15 мин |
| 7 | **Teams** | `team_mapper.py` (7 функций, 200+ алиасов) + `sport_cache.json` | 50 KB | Постоянно |
| 8 | **Leagues** | `prediction_leagues.json` + `capper_pipeline.py` | <1 KB | Статика |
| 9 | **News** | `news_data.json` + `news.html` | 600 KB | Постоянно |
| 10 | **Translation cache** | `sport_translation_cache.json` | 440 KB | Постоянно |

---

## 1️⃣ Должно быть в БД (обязательно)

### predictions — ядро бизнеса

```sql
CREATE TABLE predictions (
    id              SERIAL PRIMARY KEY,
    match_id        TEXT UNIQUE,
    league          TEXT NOT NULL,
    home            TEXT NOT NULL,
    away            TEXT NOT NULL,
    match_time      TEXT,                  -- HH:MM
    match_date      DATE,
    status          TEXT DEFAULT 'upcoming'
                    CHECK (status IN ('upcoming', 'finished')),
    score           TEXT,
    actual_winner   TEXT,
    actual_total    TEXT,
    prediction_text TEXT,
    verdict         TEXT,
    -- odds
    odds_home REAL, odds_draw REAL, odds_away REAL,
    odds_over REAL, odds_under REAL, total_line REAL,
    -- glicko
    glicko_home_prob REAL, glicko_draw_prob REAL, glicko_away_prob REAL,
    glicko_home_rating REAL, glicko_away_rating REAL,
    glicko_home_xg REAL, glicko_away_xg REAL,
    -- xgb
    xgb_win_pred TEXT, xgb_win_conf REAL,
    xgb_total_pred TEXT, xgb_total_conf REAL,
    -- result
    result_win TEXT CHECK (result_win IN ('correct','incorrect')),
    result_total TEXT CHECK (result_total IN ('correct','incorrect')),
    -- meta
    has_lineups BOOLEAN DEFAULT FALSE,
    game_id INTEGER,
    generated_at TIMESTAMPTZ,
    evaluated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_pred_status    ON predictions(status);
CREATE INDEX idx_pred_league    ON predictions(league);
CREATE INDEX idx_pred_date      ON predictions(match_date);
```

### training_data — сырьё для модели

```sql
CREATE TABLE training_data (
    id              SERIAL PRIMARY KEY,
    source          TEXT NOT NULL,     -- 'sstats' / 'prediction' / 'manual'
    league          TEXT NOT NULL,
    home            TEXT, away TEXT,
    match_date      DATE,
    score           TEXT,
    actual_winner   TEXT NOT NULL,
    actual_total    TEXT NOT NULL,
    glicko_home_prob REAL, glicko_draw_prob REAL, glicko_away_prob REAL,
    glicko_home_rating REAL, glicko_away_rating REAL,
    glicko_home_xg REAL, glicko_away_xg REAL,
    odds_home REAL, odds_draw REAL, odds_away REAL,
    odds_over REAL, odds_under REAL, total_line REAL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_training_source ON training_data(source);
```

### model_versions — история обучения

```sql
CREATE TABLE model_versions (
    id              SERIAL PRIMARY KEY,
    model_type      TEXT NOT NULL,     -- 'win' / 'total'
    trained_at      TIMESTAMPTZ DEFAULT NOW(),
    train_count     INTEGER,
    val_accuracy    REAL,
    train_accuracy  REAL,
    model_path      TEXT,
    feature_count   INTEGER,
    active          BOOLEAN DEFAULT TRUE
);
```

---

## 2️⃣ Стоит перенести (сильно упростит код)

### teams — единый справочник команд

Сейчас в `team_mapper.py` 7 функций и 200+ алиасов для fuzzy-маппинга имён. Это хрупкая логика, которую можно заменить таблицей:

```sql
CREATE TABLE teams (
    id              SERIAL PRIMARY KEY,
    canonical_name  TEXT UNIQUE NOT NULL,  -- 'Манчестер Сити'
    name_en         TEXT,                  -- 'Manchester City'
    short_name      TEXT,                  -- 'Ман Сити'
    logo_url        TEXT,
    league          TEXT,                  -- 'АПЛ'
    sstats_id       INTEGER               -- ID команды в SStats (если есть)
);

-- Алиасы: все возможные варианты написания
CREATE TABLE team_aliases (
    id              SERIAL PRIMARY KEY,
    team_id         INTEGER REFERENCES teams(id),
    alias           TEXT UNIQUE NOT NULL,   -- 'man city', 'ман сити', 'mancity'
    lang            TEXT DEFAULT 'ru'       -- ru/en
);
```

**Что это даёт:**
- `resolve('Манчестер Сити')` → `team_aliases.alias` JOIN `teams` → одноимённый запрос
- Не нужно триграмм, нормализации, кешей
- Логотипы хранятся централизованно
- Можно привязать к prediction через team_id

**Кого касается:** `team_mapper.py` можно выкинуть, `evaluate_predictions.py` и `capper_pipeline.py` упростить.

### matches — единая таблица матчей

Сейчас матчи размазаны по трём файлам: schedule (tv_channels), results (daily_results), live (live_scores). У каждого свой формат.

```sql
CREATE TABLE matches (
    id              SERIAL PRIMARY KEY,
    league          TEXT NOT NULL,
    home            TEXT NOT NULL,
    away            TEXT NOT NULL,
    match_date      DATE NOT NULL,
    match_time      TEXT,                  -- HH:MM
    source          TEXT,                  -- 'tv' / 'espn' / 'sstats'

    -- Результат
    score           TEXT,                  -- '3:1'
    status          TEXT DEFAULT 'scheduled'
                    CHECK (status IN ('scheduled', 'live', 'finished')),

    -- Мета
    channel         TEXT,                  -- телеканал
    tournament      TEXT,                  -- турнир
    game_id         INTEGER,              -- SStats game_id
    espn_id         TEXT,                  -- ESPN event ID

    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(league, home, away, match_date)
);

CREATE INDEX idx_matches_date   ON matches(match_date);
CREATE INDEX idx_matches_status ON matches(status);
CREATE INDEX idx_matches_league ON matches(league);
```

**Что это даёт:**
- Predictions можно привязать к matches через `FOREIGN KEY`
- Сайт читает schedule/results из одной таблицы
- Не нужно три файла и `storage.py`
- Легко отследить матчи без прогноза

---

## 3️⃣ Оставить как файлы (не надо в БД)

| Сущность | Почему |
|----------|--------|
| **Live scores** | Живут 15 мин, перезаписываются целиком, не имеют исторической ценности. Запросы не нужны — только чтение для сайта |
| **XGBoost model files** (`.json`) | Бинарные файлы, которые грузит `xgboost.load_model()`. Положить в БД можно, но бессмысленно — они тяжелее, чем их метаданные в `model_versions` |
| **News articles** | 28 статей, контент, не структурированы под SQL. Если появятся поиск/фильтр по командам — можно перенести. Пока не нужно |
| **News HTML** | Сгенерированные страницы, статика nginx |
| **Translation cache** | 440 KB кеша переводов новостей. Если переедут статьи — переедет и кеш |
| **Sport cache** | 50 KB временных кешей ESPN API. Очищается раз в день |

---

## 4️⃣ Схема связей

```
leagues ──────┐
              ├── predictions ──────┐
teams ────────┘                     │
                                    ├── training_data
matches ────────────────────────────┘
                                   │
                           model_versions
```

---

## 5️⃣ Что конкретно меняется в скриптах

| Скрипт | Сейчас | После |
|--------|--------|-------|
| `capper_pipeline.py` | Читает JSON queue + history | `INSERT INTO predictions` + `SELECT FROM predictions WHERE status='finished'` (few-shot) |
| `evaluate_predictions.py` | Читает 3 JSON, пишет 2 JSON | `SELECT FROM predictions WHERE status='upcoming'` → `UPDATE SET status='finished'` |
| `send_prediction_stats.py` | Читает history JSON | `SELECT league, result_win, COUNT(*) ... GROUP BY` |
| `train.py` | Читает `dataset.json` | `SELECT FROM training_data` |
| `collect_data.py` | Пишет `dataset.json` | `INSERT INTO training_data` |
| `team_mapper.py` | 200+ алиасов в коде | `SELECT alias, canonical FROM team_aliases JOIN teams` |
| `site_predictions.py` | Читает JSON | `SELECT FROM predictions WHERE status='upcoming'` |
| `site_results.py` | Читает `live_scores.json` | `SELECT FROM matches WHERE status='finished'` |
| `site_schedule.py` | Читает `upcoming_matches.json` | `SELECT FROM matches WHERE status='scheduled'` |

---

## 6️⃣ Оценка

| Этап | Время |
|------|-------|
| Установка Postgres + создание БД | 10 мин |
| `db.py` — модуль доступа | 30 мин |
| Таблицы predictions + training_data + model_versions | 30 мин |
| Миграция существующих данных (3 прогноза + 1960 training) | 20 мин |
| Переписать capper_pipeline (чтение/запись) | 30 мин |
| Переписать evaluate_predictions (чтение/запись) | 30 мин |
| Переписать train.py / collect_data.py | 20 мин |
| Таблицы teams + team_aliases + миграция team_mapper | 40 мин |
| Таблица matches + замена site_* скриптам | 40 мин |
| Тесты | 30 мин |
| **Итого** | **~4-5 часов** |

Можно сделать за 2 подхода: сначала predictions + training + models (ядро), потом teams + matches (упрощение кода).

### 🔄 Open: разрешение коллизий логотипов

**Дата:** 19.05.2026  
**Статус:** отложено

**Проблема:** Одно название команды в разных лигах — разные логотипы.
- Пример: «Локомотив» в РПЛ (футбол) и «Локомотив» в КХЛ (хоккей)
- Сейчас показывается лого футбольного Локомотива для всех матчей

**Решение (когда вернёмся):**
- Добавить колонку `sport` в `teams` и `matches`
- Создать отдельные записи в БД для команд с разными лого по разным видам спорта
- `_team_logo()` — учитывать `league` + `sport` при поиске
- В `team_resolve()` — приоритет точного совпадения (имя + лига + спорт) над общим

**Затронутые файлы:** `site_common.py` (_team_logo), `db.py` (team_resolve), `site_schedule.py` и `site_results.py` (передача league в _team_logo — уже сделано)
