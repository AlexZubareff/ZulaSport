#!/usr/bin/env python3
"""
Модуль доступа к БД для пайплайна прогнозов.

Использование:
    from db import get_conn
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(...)

Все операции с predictions и training_data.
"""

import os, json
from datetime import datetime, timezone
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

# ─── Конфиг ─────────────────────────────────────────────────────────
DB_CONFIG = {
    'host': os.environ.get('PG_HOST', 'localhost'),
    'port': int(os.environ.get('PG_PORT', 5432)),
    'dbname': os.environ.get('PG_DB', 'predictions_db'),
    'user': os.environ.get('PG_USER', 'predictions_user'),
    'password': os.environ.get('PG_PASSWORD', 'pred2026'),
}

UTC = timezone.utc


# ─── Подключение ─────────────────────────────────────────────────────

@contextmanager
def get_conn():
    """Контекстный менеджер для соединения. Автокоммит при выходе."""
    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute(sql, params=None):
    """Удобная обёртка: выполнить запрос, вернуть список строк."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description:
                return cur.fetchall()
            return []


def execute_one(sql, params=None):
    """Вернуть одну строку или None."""
    rows = execute(sql, params)
    return rows[0] if rows else None


# ═══════════════════════════════════════════════════════════════════════
#  MIGRATIONS
# ═══════════════════════════════════════════════════════════════════════

MIGRATIONS = [
    # 001: predictions
    """
    CREATE TABLE IF NOT EXISTS predictions (
        id              SERIAL PRIMARY KEY,
        match_id        TEXT UNIQUE,
        league          TEXT NOT NULL,
        home            TEXT NOT NULL,
        away            TEXT NOT NULL,
        match_time      TEXT,
        match_date      DATE,
        status          TEXT NOT NULL DEFAULT 'upcoming'
                        CHECK (status IN ('upcoming', 'finished')),
        score           TEXT,
        actual_winner   TEXT,
        actual_total    TEXT,
        prediction_text TEXT,
        verdict         TEXT,
        odds_home       REAL, odds_draw REAL, odds_away REAL,
        odds_over       REAL, odds_under REAL, total_line REAL,
        glicko_home_prob   REAL, glicko_draw_prob REAL, glicko_away_prob REAL,
        glicko_home_rating REAL, glicko_away_rating REAL,
        glicko_home_xg     REAL, glicko_away_xg REAL,
        xgb_win_pred    TEXT, xgb_win_conf REAL,
        xgb_total_pred  TEXT, xgb_total_conf REAL,
        has_lineups     BOOLEAN DEFAULT FALSE,
        game_id         INTEGER,
        generated_at    TIMESTAMPTZ,
        evaluated_at    TIMESTAMPTZ,
        created_at      TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_pred_status    ON predictions(status);
    CREATE INDEX IF NOT EXISTS idx_pred_league    ON predictions(league);
    CREATE INDEX IF NOT EXISTS idx_pred_date      ON predictions(match_date);
    """,

    # 002: add result columns if missing (for backward compat with evaluate)
    """
    ALTER TABLE predictions ADD COLUMN IF NOT EXISTS result_win   TEXT
        CHECK (result_win IN ('correct', 'incorrect'));
    """,
    """
    ALTER TABLE predictions ADD COLUMN IF NOT EXISTS result_total TEXT
        CHECK (result_total IN ('correct', 'incorrect'));
    """,

    # 003: training_data
    """
    CREATE TABLE IF NOT EXISTS training_data (
        id              SERIAL PRIMARY KEY,
        source          TEXT NOT NULL DEFAULT 'sstats',
        league          TEXT NOT NULL,
        home            TEXT,
        away            TEXT,
        match_date      DATE,
        score           TEXT,
        actual_winner   TEXT NOT NULL,
        actual_total    TEXT NOT NULL,
        total_line      REAL DEFAULT 2.5,
        glicko_home_prob   REAL, glicko_draw_prob REAL, glicko_away_prob REAL,
        glicko_home_rating REAL, glicko_away_rating REAL,
        glicko_home_xg     REAL, glicko_away_xg REAL,
        odds_home REAL, odds_draw REAL, odds_away REAL,
        odds_over REAL, odds_under REAL,
        created_at      TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_training_source ON training_data(source);
    """,

    # 004: model_versions
    """
    CREATE TABLE IF NOT EXISTS model_versions (
        id              SERIAL PRIMARY KEY,
        model_type      TEXT NOT NULL CHECK (model_type IN ('win', 'total')),
        trained_at      TIMESTAMPTZ DEFAULT NOW(),
        train_count     INTEGER,
        val_accuracy    REAL,
        train_accuracy  REAL,
        model_path      TEXT,
        feature_count   INTEGER,
        active          BOOLEAN DEFAULT TRUE
    );
    """,
    # 005: teams
    """
    CREATE TABLE IF NOT EXISTS teams (
        id              SERIAL PRIMARY KEY,
        canonical_name  TEXT UNIQUE NOT NULL,
        name_en         TEXT,
        short_name      TEXT,
        logo_url        TEXT,
        league          TEXT,
        sstats_id       INTEGER
    );
    """,
    # 006: team_aliases
    """
    CREATE TABLE IF NOT EXISTS team_aliases (
        id              SERIAL PRIMARY KEY,
        team_id         INTEGER REFERENCES teams(id) ON DELETE CASCADE,
        alias           TEXT NOT NULL,
        lang            TEXT DEFAULT 'ru',
        UNIQUE(team_id, alias)
    );
    CREATE INDEX IF NOT EXISTS idx_alias_alias ON team_aliases(alias);
    """,
    # 007: matches
    """
    CREATE TABLE IF NOT EXISTS matches (
        id              SERIAL PRIMARY KEY,
        league          TEXT NOT NULL,
        home            TEXT NOT NULL,
        away            TEXT NOT NULL,
        match_date      DATE NOT NULL,
        match_time      TEXT,
        source          TEXT,
        score           TEXT,
        status          TEXT DEFAULT 'scheduled'
                        CHECK (status IN ('scheduled', 'live', 'finished')),
        channel         TEXT,
        tournament      TEXT,
        game_id         INTEGER,
        espn_id         TEXT,
        created_at      TIMESTAMPTZ DEFAULT NOW(),
        updated_at      TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(league, home, away, match_date)
    );
    CREATE INDEX IF NOT EXISTS idx_matches_date   ON matches(match_date);
    CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);
    """,

    # 009: teams columns
    """
    ALTER TABLE teams ADD COLUMN IF NOT EXISTS logo_url TEXT;
    ALTER TABLE teams ADD COLUMN IF NOT EXISTS name_en TEXT;
    """,
    # 010: home_team_id, away_team_id in predictions
    """
    ALTER TABLE predictions ADD COLUMN IF NOT EXISTS home_team_id INTEGER REFERENCES teams(id);
    ALTER TABLE predictions ADD COLUMN IF NOT EXISTS away_team_id INTEGER REFERENCES teams(id);
    CREATE INDEX IF NOT EXISTS idx_pred_home_team ON predictions(home_team_id);
    CREATE INDEX IF NOT EXISTS idx_pred_away_team ON predictions(away_team_id);
    """,
    # 008: match_ref in predictions
    """
    ALTER TABLE predictions ADD COLUMN IF NOT EXISTS match_ref INTEGER REFERENCES matches(id);
    CREATE INDEX IF NOT EXISTS idx_pred_match_ref ON predictions(match_ref);
    """,

]


def run_migrations():
    """Накатить миграции. Идемпотентно."""
    for i, sql in enumerate(MIGRATIONS, 1):
        try:
            execute(sql)
            print(f'  ✅ Миграция {i:03d}')
        except Exception as e:
            print(f'  ❌ Миграция {i:03d}: {e}')
            raise


# ═══════════════════════════════════════════════════════════════════════
#  PREDICTIONS
# ═══════════════════════════════════════════════════════════════════════

def save_prediction(pred: dict):
    """INSERT или UPDATE прогноза по match_id."""
    import re
    import sys

    match_date = pred.get('match_date')
    if not match_date and pred.get('generated_at'):
        try:
            match_date = datetime.fromisoformat(pred['generated_at']).strftime('%Y-%m-%d')
        except:
            pass
    if not match_date and pred.get('match_id'):
        parts = pred['match_id'].split('||')
        if parts and re.match(r'\d{2}\.\d{2}\.\d{4}', parts[0]):
            try:
                d = datetime.strptime(parts[0], '%d.%m.%Y')
                match_date = d.strftime('%Y-%m-%d')
            except:
                pass

    sql = """
    INSERT INTO predictions (
        match_id, league, home, away, match_time, match_date, status,
        score, actual_winner, actual_total, total_line,
        prediction_text, verdict,
        odds_home, odds_draw, odds_away, odds_over, odds_under,
        glicko_home_prob, glicko_draw_prob, glicko_away_prob,
        glicko_home_rating, glicko_away_rating,
        glicko_home_xg, glicko_away_xg,
        xgb_win_pred, xgb_win_conf, xgb_total_pred, xgb_total_conf,
        has_lineups, game_id, generated_at, evaluated_at,
        result_win, result_total
    ) VALUES (
        %(match_id)s, %(league)s, %(home)s, %(away)s,
        %(match_time)s, %(match_date)s,
        COALESCE(%(status)s, 'upcoming'),
        %(score)s, %(actual_winner)s, %(actual_total)s, %(total_line)s,
        %(prediction_text)s, %(verdict)s,
        %(odds_home)s, %(odds_draw)s, %(odds_away)s,
        %(odds_over)s, %(odds_under)s,
        %(glicko_home_prob)s, %(glicko_draw_prob)s, %(glicko_away_prob)s,
        %(glicko_home_rating)s, %(glicko_away_rating)s,
        %(glicko_home_xg)s, %(glicko_away_xg)s,
        %(xgb_win_pred)s, %(xgb_win_conf)s,
        %(xgb_total_pred)s, %(xgb_total_conf)s,
        %(has_lineups)s, %(game_id)s,
        %(generated_at)s::timestamptz, %(evaluated_at)s::timestamptz,
        %(result_win)s, %(result_total)s
    )
    ON CONFLICT (match_id) DO UPDATE SET
        status          = EXCLUDED.status,
        score           = COALESCE(EXCLUDED.score, predictions.score),
        result_win      = COALESCE(EXCLUDED.result_win, predictions.result_win),
        result_total    = COALESCE(EXCLUDED.result_total, predictions.result_total),
        evaluated_at    = COALESCE(EXCLUDED.evaluated_at, predictions.evaluated_at),
        prediction_text = COALESCE(EXCLUDED.prediction_text, predictions.prediction_text),
        verdict         = COALESCE(EXCLUDED.verdict, predictions.verdict),
        xgb_win_pred    = COALESCE(EXCLUDED.xgb_win_pred, predictions.xgb_win_pred),
        xgb_total_pred  = COALESCE(EXCLUDED.xgb_total_pred, predictions.xgb_total_pred),
        xgb_win_conf    = COALESCE(EXCLUDED.xgb_win_conf, predictions.xgb_win_conf),
        xgb_total_conf  = COALESCE(EXCLUDED.xgb_total_conf, predictions.xgb_total_conf)
    """

    params = _pred_to_params(pred)
    execute(sql, params)
    
    # Обновляем match_ref, если есть match_id
    if params.get('match_id'):
        update_match_ref(
            params['match_id'],
            params.get('league'),
            params.get('home'),
            params.get('away'),
            params.get('match_date')
        )
    
    # Разрешаем имена команд в team_id
    if params.get('home') or params.get('away'):
        home_id = team_resolve(params.get('home'))
        away_id = team_resolve(params.get('away'))
        if home_id or away_id:
            update_sql = []
            update_params = {}
            if home_id:
                update_sql.append("home_team_id = %(home_id)s")
                update_params['home_id'] = home_id['id']
            if away_id:
                update_sql.append("away_team_id = %(away_id)s")
                update_params['away_id'] = away_id['id']
            if update_sql:
                update_params['match_id'] = params['match_id']
                execute(f"UPDATE predictions SET {', '.join(update_sql)} WHERE match_id = %(match_id)s", update_params)


def _pred_to_params(pred: dict) -> dict:
    """Преобразовать прогноз из формата JSON в плоские имена для SQL."""
    p = dict(pred)

    if 'time' in p and 'match_time' not in p:
        p['match_time'] = p.pop('time')
    if 'prediction' in p and 'prediction_text' not in p:
        p['prediction_text'] = p.pop('prediction')
    if 'date' in p and 'match_date' not in p:
        p['match_date'] = p.pop('date')

    odds = p.pop('odds', None)
    if isinstance(odds, dict):
        p['odds_home'] = odds.get('home')
        p['odds_draw'] = odds.get('draw')
        p['odds_away'] = odds.get('away')
    elif isinstance(odds, list) and odds:
        o = odds[0]
        p['odds_home'] = o.get('home')
        p['odds_draw'] = o.get('draw')
        p['odds_away'] = o.get('away')

    totals = p.pop('totals', None)
    if isinstance(totals, dict):
        p['odds_over'] = totals.get('over')
        p['odds_under'] = totals.get('under')
        p['total_line'] = totals.get('total_line')

    g = p.pop('glicko', None)
    if isinstance(g, dict):
        p['glicko_home_prob'] = g.get('home_prob')
        p['glicko_draw_prob'] = g.get('draw_prob')
        p['glicko_away_prob'] = g.get('away_prob')
        p['glicko_home_rating'] = g.get('home_rating')
        p['glicko_away_rating'] = g.get('away_rating')
        p['glicko_home_xg'] = g.get('home_xg')
        p['glicko_away_xg'] = g.get('away_xg')

    xgb = p.pop('xgb_verdict', None)
    if isinstance(xgb, dict):
        p['xgb_win_pred'] = xgb.get('win_prediction')
        p['xgb_win_conf'] = xgb.get('win_confidence')
        p['xgb_total_pred'] = xgb.get('total_prediction')
        p['xgb_total_conf'] = xgb.get('total_confidence')

    r = p.pop('result', None)
    if isinstance(r, dict):
        p['result_win'] = None
        if isinstance(r.get('win'), dict):
            p['result_win'] = 'correct' if r['win'].get('correct') else 'incorrect' if r['win'].get('correct') is False else None
        p['result_total'] = None
        if isinstance(r.get('total'), dict):
            p['result_total'] = 'correct' if r['total'].get('correct') else 'incorrect' if r['total'].get('correct') is False else None

    for key in ('generated_at', 'evaluated_at'):
        val = p.get(key)
        if isinstance(val, str):
            try:
                p[key] = datetime.fromisoformat(val.replace('Z', '+00:00')).isoformat()
            except:
                p[key] = None

    p['has_lineups'] = bool(p.get('has_lineups'))

    if not p.get('match_date') and p.get('generated_at'):
        try:
            dt_val = p['generated_at']
            if isinstance(dt_val, str):
                dt_val = datetime.fromisoformat(dt_val.replace('Z', '+00:00'))
            p['match_date'] = dt_val.strftime('%Y-%m-%d')
        except:
            pass

    # Нормализуем match_date в ISO-формат (YYYY-MM-DD)
    md = p.get('match_date')
    if md and isinstance(md, str) and len(md) == 10:
        if '.' in md:
            try:
                p['match_date'] = datetime.strptime(md, '%d.%m.%Y').strftime('%Y-%m-%d')
            except:
                pass

    if not p.get('match_id') and p.get('league') and p.get('home') and p.get('away'):
        d = ''
        if p.get('match_date'):
            try:
                if isinstance(p['match_date'], str) and len(p['match_date']) == 10:
                    dt_val = datetime.strptime(p['match_date'], '%Y-%m-%d')
                    d = dt_val.strftime('%d.%m.%Y')
            except:
                pass
        if not d and p.get('generated_at'):
            try:
                g = p['generated_at']
                if isinstance(g, str):
                    g = datetime.fromisoformat(g.replace('Z', '+00:00'))
                d = g.strftime('%d.%m.%Y')
            except:
                d = ''
        p['match_id'] = f"{d}||{p['league']}||{p['home']}||{p['away']}"

    for key in ('match_date', 'score', 'actual_winner', 'actual_total',
                'prediction_text', 'evaluated_at', 'result_win', 'result_total',
                'odds_home', 'odds_draw', 'odds_away',
                'odds_over', 'odds_under',
                'xgb_win_pred', 'xgb_win_conf', 'xgb_total_pred', 'xgb_total_conf',
                'total_line', 'game_id', 'espn_id', 'match_time',
                'glicko_home_prob', 'glicko_draw_prob', 'glicko_away_prob',
                'glicko_home_rating', 'glicko_away_rating',
                'glicko_home_xg', 'glicko_away_xg'):
        if key not in p:
            p[key] = None

    return p


def get_queue(league: str = None, limit: int = 50) -> list:
    sql = "SELECT * FROM predictions WHERE status='upcoming'"
    params = {}
    if league:
        sql += " AND league = %(league)s"
        params['league'] = league
    sql += " ORDER BY match_time NULLS LAST, created_at LIMIT %(limit)s"
    params['limit'] = limit
    return execute(sql, params)


def get_history(league: str = None, limit: int = 100) -> list:
    sql = "SELECT * FROM predictions WHERE status='finished'"
    params = {}
    if league:
        sql += " AND league = %(league)s"
        params['league'] = league
    sql += " ORDER BY evaluated_at DESC NULLS LAST LIMIT %(limit)s"
    params['limit'] = limit
    return execute(sql, params)


def get_stats() -> dict:
    rows = execute("""
        SELECT
            COUNT(*) AS total_predictions,
            COUNT(*) FILTER (WHERE status = 'finished') AS finished,
            COUNT(*) FILTER (WHERE status = 'upcoming') AS upcoming,
            COUNT(*) FILTER (WHERE result_win = 'correct') AS win_correct,
            COUNT(*) FILTER (WHERE result_win IS NOT NULL) AS win_total,
            COUNT(*) FILTER (WHERE result_total = 'correct') AS tot_correct,
            COUNT(*) FILTER (WHERE result_total IS NOT NULL) AS tot_total
        FROM predictions
    """)
    s = rows[0] if rows else {}

    by_league = {}
    league_rows = execute("""
        SELECT league,
            COUNT(*) FILTER (WHERE result_win = 'correct') AS win_correct,
            COUNT(*) FILTER (WHERE result_win IS NOT NULL) AS win_total,
            COUNT(*) FILTER (WHERE result_total = 'correct') AS tot_correct,
            COUNT(*) FILTER (WHERE result_total IS NOT NULL) AS tot_total
        FROM predictions WHERE status = 'finished'
        GROUP BY league ORDER BY league
    """)
    for r in league_rows:
        by_league[r['league']] = {
            'win': {'correct': r['win_correct'], 'total': r['win_total']},
            'total': {'correct': r['tot_correct'], 'total': r['tot_total']},
        }

    return {
        'total_predictions': s.get('total_predictions', 0),
        'finished': s.get('finished', 0),
        'upcoming': s.get('upcoming', 0),
        'win': {'total': s.get('win_total', 0), 'correct': s.get('win_correct', 0),
                'incorrect': s.get('win_total', 0) - s.get('win_correct', 0)},
        'total': {'total': s.get('tot_total', 0), 'correct': s.get('tot_correct', 0),
                  'incorrect': s.get('tot_total', 0) - s.get('tot_correct', 0)},
        'by_league': by_league,
    }


def find_similar(home_prob, draw_prob, away_prob, league=None, top_k=3):
    sql = """
        SELECT *, (
            ABS(COALESCE(glicko_home_prob, 0) - %(hp)s)
            + ABS(COALESCE(glicko_draw_prob, 0) - %(dp)s)
            + ABS(COALESCE(glicko_away_prob, 0) - %(ap)s)
        ) AS dist
        FROM predictions
        WHERE status = 'finished'
          AND (result_win = 'correct' OR result_total = 'correct')
          AND glicko_home_prob IS NOT NULL
    """
    params = {'hp': home_prob, 'dp': draw_prob, 'ap': away_prob}
    if league:
        sql += " AND league = %(league)s"
        params['league'] = league
    sql += " ORDER BY dist LIMIT %(limit)s"
    params['limit'] = top_k
    return execute(sql, params)


# ═══════════════════════════════════════════════════════════════════════
#  TEAMS
# ═══════════════════════════════════════════════════════════════════════

def team_resolve(name: str, league: str = None) -> dict:
    """Найти команду по любому алиасу.
    Если указана лига — ищем с учётом лиги (для разрешения коллизий).
    """
    if not name:
        return None
    
    cleaned = name.strip()
    cleaned_lower = cleaned.lower()
    
    # 1. Точное совпадение canonical_name + league
    if league:
        row = execute_one(
            "SELECT * FROM teams WHERE canonical_name = %s AND league = %s",
            (cleaned, league)
        )
        if row:
            return row
    
    # 2. Алиас + league
    if league:
        row = execute_one("""
            SELECT t.* FROM teams t
            JOIN team_aliases a ON a.team_id = t.id
            WHERE a.alias = %s AND t.league = %s
        """, (cleaned_lower, league))
        if row:
            return row
    
    # 3. Точное совпадение canonical_name (без лиги)
    row = execute_one(
        "SELECT * FROM teams WHERE canonical_name = %s",
        (cleaned,)
    )
    if row:
        return row
    
    # 4. Алиас (без лиги)
    row = execute_one("""
        SELECT t.* FROM teams t
        JOIN team_aliases a ON a.team_id = t.id
        WHERE a.alias = %s
    """, (cleaned_lower,))
    if row:
        return row
    
    # 5. canonical_name + league c NULL-fallback (последняя надежда)
    if league:
        row = execute_one("""
            SELECT * FROM teams WHERE canonical_name = %s AND (league = %s OR league IS NULL)
            ORDER BY league NULLS LAST LIMIT 1
        """, (cleaned, league))
        if row:
            return row
    
    return None


def get_all_teams(league: str = None) -> list:
    sql = "SELECT * FROM teams"
    params = {}
    if league:
        sql += " WHERE league = %(league)s"
        params['league'] = league
    sql += " ORDER BY canonical_name"
    return execute(sql, params)


# ═══════════════════════════════════════════════════════════════════════
#  MATCHES
# ═══════════════════════════════════════════════════════════════════════

def save_match(m: dict):
    """INSERT или UPDATE матча."""
    m['match_date'] = m.get('match_date') or m.get('date')
    m['score'] = m.get('score')
    sql = """
    INSERT INTO matches (league, home, away, match_date, match_time,
                         source, score, status, channel, tournament,
                         game_id, espn_id)
    VALUES (%(league)s, %(home)s, %(away)s, %(match_date)s, %(match_time)s,
            %(source)s, %(score)s, %(status)s, %(channel)s, %(tournament)s,
            %(game_id)s, %(espn_id)s)
    ON CONFLICT (league, home, away, match_date) DO UPDATE SET
        status     = EXCLUDED.status,
        score      = COALESCE(EXCLUDED.score, matches.score),
        source     = COALESCE(EXCLUDED.source, matches.source),
        match_time = COALESCE(EXCLUDED.match_time, matches.match_time)
    """
    params = {
        'league': m['league'], 'home': m['home'], 'away': m['away'],
        'match_date': m['match_date'], 'match_time': m.get('match_time'),
        'source': m.get('source'), 'score': m['score'],
        'status': m.get('status', 'scheduled'),
        'channel': m.get('channel'), 'tournament': m.get('tournament'),
        'game_id': m.get('game_id'), 'espn_id': m.get('espn_id'),
    }
    execute(sql, params)



def find_match_id(league, home, away, match_date=None):
    """Найти ID матча по лиге и командам. Вернуть int или None."""
    if match_date:
        row = execute_one("""
            SELECT id FROM matches WHERE league = %s
            AND home = %s AND away = %s AND match_date = %s
        """, (league, home, away, match_date))
        if row:
            return row['id']
    row = execute_one("""
        SELECT id FROM matches WHERE league = %s
        AND ((home = %s AND away = %s) OR (home = %s AND away = %s))
        AND match_date >= CURRENT_DATE - 3
        ORDER BY match_date DESC LIMIT 1
    """, (league, home, away, away, home))
    if row:
        return row['id']
    return None


def update_match_ref(pred_match_id, league, home, away, match_date=None):
    """Найти матч и привязать прогноз к нему."""
    match_ref = find_match_id(league, home, away, match_date)
    if match_ref and pred_match_id:
        execute("UPDATE predictions SET match_ref = %s WHERE match_id = %s",
                (match_ref, pred_match_id))
        return True
    return False


def get_matches(date: str = None, league: str = None, status: str = None, limit: int = 50) -> list:
    sql = "SELECT * FROM matches WHERE 1=1"
    params = {}
    if date:
        sql += " AND match_date = %(date)s"
        params['date'] = date
    if league:
        sql += " AND league = %(league)s"
        params['league'] = league
    if status:
        sql += " AND status = %(status)s"
        params['status'] = status
    sql += " ORDER BY match_time, league LIMIT %(limit)s"
    params['limit'] = limit
    return execute(sql, params)


# ═══════════════════════════════════════════════════════════════════════
#  TRAINING DATA
# ═══════════════════════════════════════════════════════════════════════

def save_training_sample(sample: dict):
    sql = """
    INSERT INTO training_data (
        source, league, home, away, match_date, score,
        actual_winner, actual_total, total_line,
        glicko_home_prob, glicko_draw_prob, glicko_away_prob,
        glicko_home_rating, glicko_away_rating,
        glicko_home_xg, glicko_away_xg,
        odds_home, odds_draw, odds_away, odds_over, odds_under
    ) VALUES (
        %(source)s, %(league)s, %(home)s, %(away)s,
        %(match_date)s, %(score)s,
        %(actual_winner)s, %(actual_total)s, %(total_line)s,
        %(glicko_home_prob)s, %(glicko_draw_prob)s, %(glicko_away_prob)s,
        %(glicko_home_rating)s, %(glicko_away_rating)s,
        %(glicko_home_xg)s, %(glicko_away_xg)s,
        %(odds_home)s, %(odds_draw)s, %(odds_away)s,
        %(odds_over)s, %(odds_under)s
    )
    ON CONFLICT DO NOTHING
    """
    execute(sql, sample)


def get_training_data(limit: int = None) -> list:
    sql = "SELECT * FROM training_data ORDER BY created_at"
    if limit:
        sql += " LIMIT %(limit)s"
    return execute(sql, {'limit': limit} if limit else {})


def count_training() -> int:
    row = execute_one("SELECT COUNT(*) AS cnt FROM training_data")
    return row['cnt'] if row else 0


# ═══════════════════════════════════════════════════════════════════════
#  MODEL VERSIONS
# ═══════════════════════════════════════════════════════════════════════

def save_model_version(model_type, train_count, val_accuracy, train_accuracy, model_path, feature_count):
    execute("UPDATE model_versions SET active = FALSE WHERE model_type = %s", (model_type,))
    execute("""
        INSERT INTO model_versions
            (model_type, train_count, val_accuracy, train_accuracy, model_path, feature_count)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (model_type, train_count, val_accuracy, train_accuracy, model_path, feature_count))


def get_active_model(model_type: str) -> dict:
    return execute_one(
        "SELECT * FROM model_versions WHERE model_type = %s AND active = TRUE", (model_type,)
    )


# ═══════════════════════════════════════════════════════════════════════
#  Теннис
# ═══════════════════════════════════════════════════════════════════════

def save_tennis_match(match_id, tennis_data: dict):
    """Сохранить детали теннисного матча в tennis_matches."""
    execute("""
        INSERT INTO tennis_matches (match_id, tournament, tier, gender, round,
            sets_data, winner_home, winner_away, has_ret, has_wo)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (match_id) DO UPDATE SET
            tournament = EXCLUDED.tournament,
            tier = EXCLUDED.tier,
            gender = EXCLUDED.gender,
            round = EXCLUDED.round,
            sets_data = EXCLUDED.sets_data,
            winner_home = EXCLUDED.winner_home,
            winner_away = EXCLUDED.winner_away,
            has_ret = EXCLUDED.has_ret,
            has_wo = EXCLUDED.has_wo
    """, (
        match_id,
        tennis_data.get('tournament', ''),
        tennis_data.get('tier', ''),
        tennis_data.get('gender', ''),
        tennis_data.get('round', ''),
        json.dumps(tennis_data.get('sets', [])),
        tennis_data.get('winner_home'),
        tennis_data.get('winner_away'),
        tennis_data.get('has_ret', False),
        tennis_data.get('has_wo', False),
    ))


def get_tennis_matches(date_from=None, date_to=None):
    """Получить теннисные матчи с деталями через JOIN."""
    from datetime import datetime
    sql = """
        SELECT m.id, m.league, m.home, m.away, m.match_date, m.match_time,
               m.score, m.source, m.status,
               tm.tournament, tm.tier, tm.gender, tm.round,
               tm.sets_data, tm.winner_home, tm.winner_away,
               tm.has_ret, tm.has_wo
        FROM matches m
        JOIN tennis_matches tm ON tm.match_id = m.id
        WHERE 1=1
    """
    params = []
    if date_from:
        sql += " AND m.match_date >= %s"
        params.append(date_from)
    if date_to:
        sql += " AND m.match_date < %s"
        params.append(date_to)
    sql += " ORDER BY m.match_date, m.match_time"
    
    rows = execute(sql, params)
    result = []
    for r in rows:
        entry = {
            'tournament': r['tournament'],
            'tier': r['tier'],
            'gender': r['gender'],
            'round': r['round'],
            'player1': r['home'],
            'player2': r['away'],
            'score': r['score'],
            'match_date': r['match_date'],
            'winner1': r['winner_home'],
            'winner2': r['winner_away'],
            'has_ret': r['has_ret'],
            'has_wo': r['has_wo'],
        }
        # Парсим sets_data из JSONB
        try:
            entry['sets'] = json.loads(r['sets_data']) if isinstance(r['sets_data'], str) else (r['sets_data'] or [])
        except:
            entry['sets'] = []
        result.append(entry)
    return result


# ═══════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import sys
    if '--migrate' in sys.argv:
        run_migrations()
        print('✅ Миграции выполнены')
    elif '--migrate-from-json' in sys.argv:
        from migrate_from_json import migrate_predictions
        migrate_predictions()
        print('✅ Миграция из JSON завершена')
    elif '--migrate-teams' in sys.argv:
        from migrate_team_mapper import migrate_teams
        migrate_teams()
        print('✅ Миграция команд завершена')
    elif '--migrate-matches' in sys.argv:
        from migrate_matches import migrate_matches
        migrate_matches()
        print('✅ Миграция матчей завершена')
    else:
        print('Режимы: migrate | migrate-from-json | migrate-teams | migrate-matches')
