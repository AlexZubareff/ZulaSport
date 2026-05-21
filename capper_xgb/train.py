#!/usr/bin/env python3
"""
Обучение XGBoost для прогнозов исходов и тоталов.

Две модели:
- xgb_win.json — классификация home/draw/away
- xgb_total.json — классификация over/under

Запуск: python3 /opt/capper_xgb/train.py
"""

import os, sys, json, warnings
import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
from collections import Counter

warnings.filterwarnings('ignore')
np.random.seed(42)

DATASET_PATH = '/opt/capper_xgb/dataset.json'
MODEL_DIR = '/opt/capper_xgb'
os.makedirs(MODEL_DIR, exist_ok=True)

# БД
try:
    sys.path.insert(0, '/opt')
    import db
    _DB_AVAILABLE = True
except:
    _DB_AVAILABLE = False

# ─── Загрузка и подготовка ─────────────────────────────────────────

print('📂 Загрузка датасета...')
games = []

# Сначала БД
if _DB_AVAILABLE:
    try:
        rows = db.get_training_data()
        if rows and len(rows) >= 100:
            games = [dict(r) for r in rows]
            print(f'   Из БД: {len(games)} записей')
    except Exception as e:
        print(f'   БД: {e}')

# Fallback: JSON
if not games and os.path.exists(DATASET_PATH):
    with open(DATASET_PATH) as f:
        data = json.load(f)
    games = data.get('games', [])
    print(f'   Из JSON: {len(games)} записей')

if not games:
    print('❌ Нет данных для обучения')
    sys.exit(1)

# Отбираем только те, где есть Glicko (основные фичи)
with_glicko = [g for g in games if g.get('glicko_home_prob') is not None]
print(f'   С Glicko: {len(with_glicko)}')

if len(with_glicko) < 50:
    print('❌ Слишком мало данных с Glicko для обучения')
    sys.exit(1)

# ─── Фичи ───────────────────────────────────────────────────────────

def extract_features(g):
    """Вектор фич для одной записи."""
    f = []
    # Glicko вероятности (3)
    f.append(g.get('glicko_home_prob', 0.33))
    f.append(g.get('glicko_draw_prob', 0.33))
    f.append(g.get('glicko_away_prob', 0.33))

    # Glicko рейтинги (2)
    f.append(g.get('glicko_home_rating', 1500))
    f.append(g.get('glicko_away_rating', 1500))

    # Glicko xG (2)
    f.append(g.get('glicko_home_xg', 1.2))
    f.append(g.get('glicko_away_xg', 1.2))

    # Кэфы (3)
    f.append(g.get('odds_home', 2.0) or 2.0)
    f.append(g.get('odds_draw', 3.5) or 3.5)
    f.append(g.get('odds_away', 2.0) or 2.0)

    # Производные от кэфов (3)
    oh = 1.0 / max(g.get('odds_home', 2.0) or 2.0, 0.01)
    od = 1.0 / max(g.get('odds_draw', 3.5) or 3.5, 0.01)
    oa = 1.0 / max(g.get('odds_away', 2.0) or 2.0, 0.01)
    margin = oh + od + oa
    f.append(oh / margin)  # implied home prob
    f.append(od / margin)  # implied draw prob
    f.append(oa / margin)  # implied away prob

    # Разница рейтингов (1)
    f.append(g.get('glicko_home_rating', 1500) - g.get('glicko_away_rating', 1500))

    # Разница xG (1)
    f.append((g.get('glicko_home_xg', 1.2) or 1.2) - (g.get('glicko_away_xg', 1.2) or 1.2))

    # Тоталы (2)
    f.append(g.get('odds_over', 1.9) or 1.9)
    f.append(g.get('odds_under', 1.9) or 1.9)

    return np.array(f, dtype=np.float32)


FEATURE_NAMES = [
    'glicko_home_prob', 'glicko_draw_prob', 'glicko_away_prob',
    'glicko_home_rating', 'glicko_away_rating',
    'glicko_home_xg', 'glicko_away_xg',
    'odds_home', 'odds_draw', 'odds_away',
    'implied_home_prob', 'implied_draw_prob', 'implied_away_prob',
    'rating_diff', 'xg_diff',
    'odds_over', 'odds_under',
]

# ─── Win модель ─────────────────────────────────────────────────────

print('\n🏆 Win модель (П1/Х/П2)...')
win_map = {'home': 0, 'draw': 1, 'away': 2}

X_win, y_win = [], []
for g in with_glicko:
    winner = g.get('actual_winner')
    if winner not in win_map:
        continue
    X_win.append(extract_features(g))
    y_win.append(win_map[winner])

X_win = np.array(X_win)
y_win = np.array(y_win)

print(f'   Размер: {len(X_win)}')
print(f'   Распределение:')
for name, idx in sorted(win_map.items(), key=lambda x: x[1]):
    cnt = (y_win == idx).sum()
    print(f'     {name}: {cnt} ({cnt/len(y_win)*100:.1f}%)')

# Train/val split
X_tr, X_val, y_tr, y_val = train_test_split(X_win, y_win, test_size=0.2, random_state=42, stratify=y_win)

# Обучение Win
win_model = xgb.XGBClassifier(
    objective='multi:softprob',
    num_class=3,
    n_estimators=200,
    max_depth=6,
    learning_rate=0.08,
    subsample=0.8,
    colsample_bytree=0.7,
    reg_lambda=2.0,
    reg_alpha=1.0,
    min_child_weight=3,
    eval_metric='mlogloss',
    early_stopping_rounds=20,
    random_state=42,
    verbosity=0,
)

eval_set = [(X_tr, y_tr), (X_val, y_val)]
win_model.fit(X_tr, y_tr, eval_set=eval_set, verbose=False)

# Оценка
y_pred = win_model.predict(X_val)
val_acc = accuracy_score(y_val, y_pred)
print(f'\n   Validation accuracy: {val_acc:.4f} ({val_acc*100:.1f}%)')

y_pred_train = win_model.predict(X_tr)
train_acc = accuracy_score(y_tr, y_pred_train)
print(f'   Train accuracy: {train_acc:.4f} ({train_acc*100:.1f}%)')

# Отчёт по классам
print('\n   Classification report:')
print('   ' + classification_report(y_val, y_pred, target_names=['home', 'draw', 'away'], zero_division=0).replace('\n', '\n   '))

# Feature importance
imp = win_model.feature_importances_
top_idx = np.argsort(imp)[-8:]
print('   Топ-8 фич:')
for idx in reversed(top_idx):
    print(f'     {FEATURE_NAMES[idx]}: {imp[idx]:.3f}')

# Сохраняем
model_path = os.path.join(MODEL_DIR, 'xgb_win.json')
win_model.save_model(model_path)
print(f'   ✅ Сохранена: {model_path}')

# ─── Total модель ───────────────────────────────────────────────────

print('\n📊 Total модель (Over/Under)...')
total_map = {'over': 0, 'under': 1}

X_tot, y_tot = [], []
for g in with_glicko:
    total = g.get('actual_total')
    if total not in total_map:
        continue
    # Добавляем total_line как доп фичу
    feat = np.append(extract_features(g), g.get('total_line', 2.5))
    X_tot.append(feat)
    y_tot.append(total_map[total])

X_tot = np.array(X_tot)
y_tot = np.array(y_tot)

print(f'   Размер: {len(X_tot)}')
for name, idx in sorted(total_map.items(), key=lambda x: x[1]):
    cnt = (y_tot == idx).sum()
    print(f'     {name}: {cnt} ({cnt/len(y_tot)*100:.1f}%)')

if len(set(y_tot)) < 2:
    print('   ⚠️ Только один класс — не учим тотал')
else:
    X_tr_t, X_val_t, y_tr_t, y_val_t = train_test_split(
        X_tot, y_tot, test_size=0.2, random_state=42, stratify=y_tot)

    total_model = xgb.XGBClassifier(
        objective='binary:logistic',
        n_estimators=200,
        max_depth=5,
        learning_rate=0.08,
        subsample=0.8,
        colsample_bytree=0.7,
        reg_lambda=2.0,
        reg_alpha=1.0,
        min_child_weight=3,
        eval_metric='logloss',
        early_stopping_rounds=20,
        random_state=42,
        verbosity=0,
    )

    total_model.fit(X_tr_t, y_tr_t, eval_set=[(X_tr_t, y_tr_t), (X_val_t, y_val_t)], verbose=False)

    y_pred_t = total_model.predict(X_val_t)
    val_acc_t = accuracy_score(y_val_t, y_pred_t)
    print(f'\n   Validation accuracy: {val_acc_t:.4f} ({val_acc_t*100:.1f}%)')

    y_pred_tr_t = total_model.predict(X_tr_t)
    print(f'   Train accuracy: {accuracy_score(y_tr_t, y_pred_tr_t):.4f}')

    model_path_t = os.path.join(MODEL_DIR, 'xgb_total.json')
    total_model.save_model(model_path_t)
    print(f'   ✅ Сохранена: {model_path_t}')

    # Сохраняем в БД
    if _DB_AVAILABLE:
        db.save_model_version('total', len(with_glicko), val_acc_t,
                              accuracy_score(y_tr_t, y_pred_tr_t),
                              model_path_t, len(FEATURE_NAMES) + 1)

# ─── Бейзлайн (кто был бы фаворитом по кэфам) ─────────────────────

print('\n📊 Бейзлайн: «кэфовый фаворит»')
correct_by_odds = 0
total_by_odds = 0
for g in with_glicko:
    odds = [g.get('odds_home', 2.0) or 2.0,
            g.get('odds_draw', 3.5) or 3.5,
            g.get('odds_away', 2.0) or 2.0]
    if not all(odds):
        continue
    implied = [1.0 / o for o in odds]
    margin = sum(implied)
    implied = [i / margin for i in implied]
    pred = ['home', 'draw', 'away'][np.argmax(implied)]
    if pred == g.get('actual_winner'):
        correct_by_odds += 1
    total_by_odds += 1

print(f'   Кэфовый фаворит: {correct_by_odds}/{total_by_odds} ({correct_by_odds/total_by_odds*100:.1f}%)')

# Сохраняем версию в БД
if _DB_AVAILABLE:
    db.save_model_version('win', len(with_glicko), val_acc,
                          accuracy_score(y_tr, y_pred_train),
                          model_path, len(FEATURE_NAMES))

print(f'\n{"="*50}')
print(f'✅ Обучение завершено')
print(f'   Модели: {MODEL_DIR}/xgb_win.json, {MODEL_DIR}/xgb_total.json')
