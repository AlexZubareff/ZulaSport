#!/usr/bin/env python3
"""
Миграция существующих данных из JSON в PostgreSQL.

Переносит:
1. predictions_data.json → predictions (queue)
2. predictions_history.json → predictions (history)
3. dataset.json → training_data
"""

import os, json, sys
sys.path.insert(0, '/opt')

from db import save_prediction, save_training_sample, count_training, get_conn, execute

PRED_PATH = '/opt/predictions_data.json'
HISTORY_PATH = '/opt/predictions_history.json'
DATASET_PATH = '/opt/capper_xgb/dataset.json'

counts = {'queue': 0, 'history': 0, 'training': 0, 'errors': 0}


def migrate_predictions():
    """Перенести прогнозы из JSON в БД."""
    # 1. Очередь
    if os.path.exists(PRED_PATH):
        try:
            with open(PRED_PATH, encoding='utf-8') as f:
                data = json.load(f)
            queue = data.get('predictions', [])
            for pred in queue:
                if not isinstance(pred, dict):
                    continue
                pred['status'] = 'upcoming'
                try:
                    save_prediction(pred)
                    counts['queue'] += 1
                except Exception as e:
                    print(f'  ❌ queue: {pred.get("home","?")} — {pred.get("away","?")}: {e}')
                    counts['errors'] += 1
            print(f'  Очередь: {counts["queue"]} прогнозов')
        except Exception as e:
            print(f'  ❌ predictions_data.json: {e}')

    # 2. История
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, encoding='utf-8') as f:
                data = json.load(f)
            history = data.get('predictions', [])
            for pred in history:
                if not isinstance(pred, dict):
                    continue
                pred['status'] = pred.get('status', 'finished')
                try:
                    save_prediction(pred)
                    counts['history'] += 1
                except Exception as e:
                    print(f'  ❌ history: {pred.get("home","?")} — {pred.get("away","?")}: {e}')
                    counts['errors'] += 1
            print(f'  История: {counts["history"]} прогнозов')
        except Exception as e:
            print(f'  ❌ predictions_history.json: {e}')


def migrate_training():
    """Перенести тренировочные данные из dataset.json."""
    if not os.path.exists(DATASET_PATH):
        print('  ❌ dataset.json не найден')
        return

    try:
        with open(DATASET_PATH, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f'  ❌ dataset.json: {e}')
        return

    games = data.get('games', [])
    for g in games:
        if not isinstance(g, dict):
            continue
        sample = {
            'source': 'sstats',
            'league': g.get('league_name', ''),
            'home': g.get('home', ''),
            'away': g.get('away', ''),
            'match_date': g.get('date', '')[:10] if g.get('date') else None,
            'score': g.get('score', ''),
            'actual_winner': g.get('actual_winner', ''),
            'actual_total': g.get('actual_total', ''),
            'total_line': g.get('total_line', 2.5),
            'glicko_home_prob': g.get('glicko_home_prob'),
            'glicko_draw_prob': g.get('glicko_draw_prob'),
            'glicko_away_prob': g.get('glicko_away_prob'),
            'glicko_home_rating': g.get('glicko_home_rating'),
            'glicko_away_rating': g.get('glicko_away_rating'),
            'glicko_home_xg': g.get('glicko_home_xg'),
            'glicko_away_xg': g.get('glicko_away_xg'),
            'odds_home': g.get('odds_home'),
            'odds_draw': g.get('odds_draw'),
            'odds_away': g.get('odds_away'),
            'odds_over': g.get('odds_over'),
            'odds_under': g.get('odds_under'),
        }
        try:
            save_training_sample(sample)
            counts['training'] += 1
        except Exception as e:
            print(f'  ❌ training: {g.get("league_name")} {g.get("home")}-{g.get("away")}: {e}')
            counts['errors'] += 1

    print(f'  Training data: {counts["training"]} сэмплов')


if __name__ == '__main__':
    print('📦 Миграция из JSON в PostgreSQL')
    print('=' * 50)

    print('\n1️⃣ Прогнозы:')
    migrate_predictions()

    print('\n2️⃣ Тренировочные данные:')
    migrate_training()

    print('\n' + '=' * 50)
    total_ok = counts['queue'] + counts['history'] + counts['training']
    print(f'✅ Перенесено: {total_ok} записей')
    if counts['errors']:
        print(f'❌ Ошибок: {counts["errors"]}')
    print(f'📊 В БД теперь:')
    from db import get_stats, count_training
    stats = get_stats()
    if stats:
        print(f'   Predictions: {stats["total_predictions"]} (queue={stats["upcoming"]}, history={stats["finished"]})')
    print(f'   Training data: {count_training()} сэмплов')
