#!/usr/bin/env python3
"""
NHL Capper — каперский пайплайн для хоккея (НХЛ).

Режимы:
  --batch       — полная генерация прогнозов на все предстоящие матчи
  --refresh     — обновить прогнозы для матчей <= 3ч

Сохраняет: /opt/predictions_data.json + БД
"""

import json, sys, os, re, math
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import requests

sys.path.insert(0, '/opt')

# ─── БД ─────────────────────────────────────────────────────────────
try:
    import db
    _DB_AVAILABLE = True
except:
    _DB_AVAILABLE = False

# ─── DeepSeek ───────────────────────────────────────────────────────
DEEPSEEK_KEY = ''
try:
    with open('/etc/deepseek.key') as f:
        DEEPSEEK_KEY = f.read().strip()
except:
    pass

# ─── NHL модули ────────────────────────────────────────────────────
from nhl_models import NhlElo, NhlForm, NhlH2H, combine_prob
from fetch_nhl_data import ru, fetch_schedule, fetch_standings

# ─── Константы ──────────────────────────────────────────────────────
MOW = timedelta(hours=3)
UTC = timezone.utc
PRED_LEAGUES_PATH = '/opt/prediction_leagues.json'
PRED_PATH = '/opt/predictions_data.json'
DATA_DIR = '/opt/data/nhl'


# ═══════════════════ Загрузчик данных ═══════════════════

def _init_nhl_data():
    """Инициализировать Elo + данные."""
    elo = NhlElo()
    if not elo._loaded:
        print('  🏒 Elo: инициализация из таблицы...')
        standings = fetch_standings()
        elo.init_from_standings(standings)

    # Train
    trained = elo.train_on_history()
    if trained:
        print(f'  🏒 Elo: дообучено на {trained} матчах')

    # Form
    nhl_form = NhlForm()
    standings_data = fetch_standings()
    form_data = nhl_form.from_standings(standings_data)
    print(f'  📊 Форма: {len(form_data)} команд')

    # H2H
    try:
        with open(f'{DATA_DIR}/schedule.json', encoding='utf-8') as f:
            sched_data = json.load(f)
    except:
        sched_data = {'upcoming': [], 'finished': []}
    h2h_data = NhlH2H.from_schedule(sched_data)
    print(f'  📊 H2H: {len(h2h_data)} пар')

    return elo, nhl_form, form_data, h2h_data


# ═══════════════════ Анализ матча ═══════════════════

def analyze_nhl_match(match: dict, elo: NhlElo, nhl_form: NhlForm,
                      form_data: dict, h2h_data: dict) -> Dict:
    """Полный анализ одного хоккейного матча."""
    home = match.get('home', '')
    away = match.get('away', '')
    game_type = match.get('game_type', 2)

    result = {
        'home': home,
        'home_ru': match.get('home_ru', ru(home)),
        'away': away,
        'away_ru': match.get('away_ru', ru(away)),
    }

    # 1. Elo прогноз
    elo_pred = elo.predict(home, away, game_type=game_type)
    result['elo'] = elo_pred

    # 2. Форма
    ff = nhl_form.form_factor(form_data, home, away)
    result['form'] = ff

    # 3. H2H
    h2h_res = NhlH2H.get_h2h(h2h_data, home, away)
    result['h2h'] = h2h_res

    # 4. Odds
    odds = match.get('odds', {})
    result['odds_raw'] = odds

    # 5. Комбинированная вероятность
    combined = combine_prob(elo_pred, ff, h2h_res, odds)
    result['combined'] = combined

    # 6. Серия (плей-офф)
    series = match.get('series', {})
    if series:
        result['series'] = series

    return result


# ═══════════════════ DeepSeek генерация ═══════════════════

def _build_capper_stats_nhl():
    """Статистика капера для system prompt."""
    s = None
    if _DB_AVAILABLE:
        try:
            s = db.get_stats()
        except:
            s = None

    if not s or s.get('total_predictions', 0) < 3:
        return ''

    total = s.get('total_predictions', 0)
    if total < 3:
        return ''

    win = s.get('win', {})
    tot = s.get('total', {})
    wt = win.get('total', 0) or 1
    tt = tot.get('total', 0) or 1
    wc = win.get('correct', 0)
    tc = tot.get('correct', 0)

    by_league = s.get('by_league', {})
    lines = []
    lines.append('📊 Твоя текущая статистика:')
    lines.append(f'Win: {wc}/{wt} ({wc/wt*100:.0f}%) | Total: {tc}/{tt} ({tc/tt*100:.0f}%)')

    if by_league:
        lines.append('По лигам:')
        for league, st in sorted(by_league.items(),
                                  key=lambda x: x[1].get('win', {}).get('total', 0), reverse=True):
            w = st.get('win', {})
            t = st.get('total', {})
            wt_l = w.get('total', 0) or 1
            tt_l = t.get('total', 0) or 1
            lines.append(f'  {league}: Win {w.get("correct",0)}/{w.get("total",0)} '
                        f'({w.get("correct",0)/wt_l*100:.0f}%), '
                        f'Total {t.get("correct",0)}/{t.get("total",0)} '
                        f'({t.get("correct",0)/tt_l*100:.0f}%)')

    if wc < tc:
        lines.append('Подсказка: исходы — слабый сигнал, будь осторожнее с фаворитами.')
    else:
        lines.append('Подсказка: тоталы — слабый сигнал, перепроверь аргументы.')

    return '\n' + '\n'.join(lines)


def _build_nhl_prompt(analysis: Dict) -> str:
    """Собрать промпт для DeepSeek."""
    home_ru = analysis['home_ru']
    away_ru = analysis['away_ru']
    home = analysis['home']
    away = analysis['away']
    elo = analysis['elo']
    ff = analysis['form']
    h2h = analysis['h2h']
    combined = analysis['combined']
    series = analysis.get('series', {})
    odds = analysis.get('odds_raw', {})

    parts = []
    parts.append(f'Хоккей. НХЛ: {away_ru} — {home_ru}')

    if series:
        round_names = {1: '1/4 финала', 2: '1/2 финала', 3: 'Финал конференции', 4: 'Финал Кубка Стэнли'}
        rn = round_names.get(series.get('round', 0), f'Раунд {series.get("round")}')
        parts.append(f'🏆 {rn}, игра {series.get("game_of_series", "?")} серии')
        parts.append(f'Счёт в серии: {home_ru} {series.get("home_wins", 0)} — {series.get("away_wins", 0)} {away_ru}')

    parts.append(f'\n📍 {analysis["elo"].get("home_adv", 0) > 0 and "Дома" or "Нейтральный лёд"}')

    # Elo
    parts.append(f'\nElo рейтинг:')
    parts.append(f'  {home_ru}: {elo["elo_home"]:.0f}')
    parts.append(f'  {away_ru}: {elo["elo_away"]:.0f}')
    parts.append(f'  Разница: {elo["elo_diff"]:+.0f}')
    parts.append(f'  Вероятность: {home_ru} {elo["home_prob"]*100:.0f}% / {away_ru} {elo["away_prob"]*100:.0f}%')

    # Комбинированная
    parts.append(f'\nКомбинированная вероятность:')
    parts.append(f'  {home_ru} {combined["home_prob"]*100:.0f}% / {away_ru} {combined["away_prob"]*100:.0f}%')
    w = combined.get('weights', {})
    parts.append(f'  (Elo {w.get("elo", 0)*100:.0f}% + форма {w.get("form",0)*100:.0f}% '
                 f'+ H2H {w.get("h2h",0)*100:.0f}% + кэфы {w.get("odds",0)*100:.0f}%)')

    # Форма
    fh = ff.get('home_form', {})
    fa = ff.get('away_form', {})
    if fh:
        parts.append(f'\nФорма {home_ru}:')
        parts.append(f'  L10: {fh.get("l10_wins", 0)}W / {fh.get("l10_losses", 0)}L / {fh.get("l10_ot_losses", 0)}OTL')
        gd_h = fh.get('l10_gd', 0)
        parts.append(f'  Разница шайб L10: {gd_h:+d}')
        parts.append(f'  Дома: {fh.get("home_wins", 0)}W / {fh.get("home_losses", 0)}L')
        parts.append(f'  За игру: {fh.get("gf_per_g", 0):.2f} забивают, {fh.get("ga_per_g", 0):.2f} пропускают')
    if fa:
        parts.append(f'\nФорма {away_ru}:')
        parts.append(f'  L10: {fa.get("l10_wins", 0)}W / {fa.get("l10_losses", 0)}L / {fa.get("l10_ot_losses", 0)}OTL')
        gd_a = fa.get('l10_gd', 0)
        parts.append(f'  Разница шайб L10: {gd_a:+d}')
        parts.append(f'  В гостях: {fa.get("road_wins", 0)}W / {fa.get("road_losses", 0)}L')
        parts.append(f'  За игру: {fa.get("gf_per_g", 0):.2f} забивают, {fa.get("ga_per_g", 0):.2f} пропускают')

    # H2H
    if h2h.get('total', 0) > 0:
        parts.append(f'\nОчные встречи (всего {h2h["total"]}):')
        h_w = h2h.get(f'{home}_wins', 0)
        a_w = h2h.get(f'{away}_wins', 0)
        parts.append(f'  {home_ru}: {h_w} побед — {away_ru}: {a_w} побед')
        # Последние 5
        if h2h.get('matches'):
            parts.append('  Последние:')
            for m in h2h['matches'][-5:]:
                winner = m.get('winner', '')
                w_ru = home_ru if winner == 'home' else away_ru
                parts.append(f'    {m.get("score")} — {w_ru}')

    # Коэффициенты
    if odds:
        oh = odds.get('home_dec')
        oa = odds.get('away_dec')
        if oh and oa:
            parts.append(f'\nКоэффициенты: {home_ru} — {oh}, {away_ru} — {oa}')

    # Streak
    if fh and fh.get('streak_code'):
        sc = fh['streak_code']
        parts.append(f'\n{home_ru}: {"+" if sc == "W" else "-"}{fh["streak_count"]}')

    parts.append('\nНапиши прогноз живым человеческим языком, как обсуждаешь хоккей с другом. '
                 'Без шаблонов, списков и заголовков. Начни нестандартно. '
                 'В конце чёткий вердикт на исход матча (кто победит и почему). '
                 'В НХЛ нет ничьих — если основное время заканчивается вничью, играют овертайм до первой шайбы.')

    return '\n'.join(parts)


def generate_nhl_prediction(analysis: Dict) -> str:
    """Сгенерировать текст прогноза через DeepSeek."""
    if not DEEPSEEK_KEY:
        return _fallback_prediction(analysis)

    prompt = _build_nhl_prompt(analysis)
    stats_block = _build_capper_stats_nhl()

    system_msg = ('Ты спортивный аналитик с ярким стилем. Пиши прогноз как человек, а не как отчёт. '
                  'Без списков, заголовков, приветствий и жирного текста. '
                  'Каждый прогноз начинай уникально. В конце чёткий вердикт на исход (кто победит).')
    if stats_block:
        system_msg += stats_block

    try:
        resp = requests.post('https://api.deepseek.com/v1/chat/completions', json={
            'model': 'deepseek-chat',
            'messages': [
                {'role': 'system', 'content': system_msg},
                {'role': 'user', 'content': prompt}
            ],
            'temperature': 0.65,
            'max_tokens': 1200
        }, headers={'Authorization': f'Bearer {DEEPSEEK_KEY}'}, timeout=30)
        data = resp.json()
        if 'choices' in data and len(data['choices']) > 0:
            text = data['choices'][0]['message']['content'].strip()
            text = text.replace('Over', 'ТБ').replace('Under', 'ТМ')
            text = text.replace('over', 'ТБ').replace('under', 'ТМ')
            text = text.replace('тотал больше', 'ТБ').replace('тотал меньше', 'ТМ')
            return text
    except Exception as e:
        print(f'  ⚠️ DeepSeek: {e}')

    return _fallback_prediction(analysis)


def _fallback_prediction(analysis):
    """Запасной прогноз на основе цифр."""
    home_ru = analysis['home_ru']
    away_ru = analysis['away_ru']
    combined = analysis['combined']
    prob = combined['home_prob']
    elo = analysis['elo']

    if prob > 0.5:
        return (f'По моим расчётам, {home_ru} — фаворит с вероятностью {prob*100:.0f}% '
                f'(Elo {elo["elo_home"]:.0f} vs {elo["elo_away"]:.0f}). '
                f'Рекомендую чистую победу {home_ru}.')
    else:
        return (f'По моим расчётам, {away_ru} — фаворит с вероятностью {(1-prob)*100:.0f}% '
                f'(Elo {elo["elo_away"]:.0f} vs {elo["elo_home"]:.0f}). '
                f'Рекомендую чистую победу {away_ru}.')


# ═══════════════════ Основной цикл ═══════════════════

def process_nhl_match(match: dict, elo: NhlElo, nhl_form: NhlForm,
                      form_data: dict, h2h_data: dict) -> Optional[Dict]:
    """Обработать один хоккейный матч."""
    home = match.get('home', '')
    away = match.get('away', '')

    if not home or not away:
        return None

    home_ru = match.get('home_ru', ru(home))
    away_ru = match.get('away_ru', ru(away))

    print(f'  🏒 {away_ru} @ {home_ru}... ', end='', flush=True)

    analysis = analyze_nhl_match(match, elo, nhl_form, form_data, h2h_data)
    prob = analysis['combined']['home_prob']
    print(f'P1={prob*100:.0f}%', end=' ', flush=True)

    pred_text = generate_nhl_prediction(analysis)
    print(f'✅')

    verdict_line = pred_text.split('.')[0] if '.' in pred_text else pred_text[:100]
    if len(verdict_line) > 120:
        verdict_line = verdict_line[:120] + '...'

    odds = analysis.get('odds_raw', {})
    elo_pred = analysis['elo']

    return {
        'home': home_ru,
        'away': away_ru,
        'home_en': home,
        'away_en': away,
        'league': 'НХЛ',
        'time': match.get('time', ''),
        'match_date': match.get('date', ''),
        'match_id': match.get('game_id'),
        'game_id': match.get('game_id'),
        'verdict': verdict_line,
        'prediction': pred_text,
        'odds': {
            'home': odds.get('home_dec'),
            'away': odds.get('away_dec'),
        },
        'glicko': {
            'home_prob': round(prob, 3),
            'away_prob': round(1 - prob, 3),
            'draw_prob': 0.0,
            'home_rating': round(elo_pred['elo_home'], 1),
            'away_rating': round(elo_pred['elo_away'], 1),
            'home_xg': 0,
            'away_xg': 0,
        },
        'generated_at': datetime.now().isoformat(),
        'series': match.get('series', {}),
        # Для совместимости с db.save_prediction
        'total_line': 5.5,
        'totals': {
            'over': None,
            'under': None,
            'total_line': 5.5,
        },
    }


def _deduplicate_matches(matches):
    """Убрать дубликаты из расписания (один и тот же game_id)."""
    seen = set()
    result = []
    for m in matches:
        gid = m.get('game_id')
        key = gid or f"{m.get('home')}||{m.get('away')}||{m.get('date')}"
        if key not in seen:
            seen.add(key)
            result.append(m)
    return result


def batch_generate():
    """Полная генерация прогнозов на все предстоящие матчи НХЛ."""
    print('🏒 Загрузка данных НХЛ...')
    matches = fetch_schedule()
    upcoming = _deduplicate_matches(matches.get('upcoming', []))
    finished = matches.get('finished', [])

    if not upcoming:
        print('❌ Нет предстоящих матчей НХЛ для прогнозов')
        _save_predictions([])
        _run_post_nhl_check([])
        return

    # Валидация входящих данных
    for i, m in enumerate(upcoming):
        for field in ('home', 'away', 'home_ru', 'away_ru', 'game_id'):
            assert field in m, f'НХЛ матч [{i}] не имеет поля {field}: {m}'

    print(f'📊 Предстоящих: {len(upcoming)}, завершённых: {len(finished)}')

    # Init models
    elo, nhl_form, form_data, h2h_data = _init_nhl_data()

    predictions = []
    for i, m in enumerate(upcoming):
        pred = process_nhl_match(m, elo, nhl_form, form_data, h2h_data)
        if pred:
            predictions.append(pred)
        if i % 3 == 2 or i == len(upcoming) - 1:
            _save_predictions(predictions)

    print(f'\n✅ Всего: {len(predictions)} прогнозов НХЛ')
    _run_post_nhl_check(predictions)


def batch_refresh():
    """Обновить прогнозы для матчей <= 3 часов."""
    now = datetime.now(UTC) + MOW

    existing = {}
    if os.path.exists(PRED_PATH):
        try:
            with open(PRED_PATH, encoding='utf-8') as f:
                for p in json.load(f).get('predictions', []):
                    if p.get('league') == 'НХЛ':
                        existing[(p.get('home',''), p.get('away',''))] = p
        except:
            pass

    nhl_preds = {k: v for k, v in existing.items()}
    if not nhl_preds:
        print('  Нет активных прогнозов НХЛ для обновления')
        return

    refreshed = []
    for key, pred in nhl_preds.items():
        match_time = pred.get('time', '') or pred.get('match_time', '')
        if not match_time:
            continue
        try:
            parts = match_time.split(':')
            h, m = int(parts[0]), int(parts[1])
            match_dt = now.replace(hour=h, minute=m, second=0)
            if match_dt < now:
                match_dt += timedelta(days=1)
        except:
            continue

        diff = (match_dt - now).total_seconds()
        if 0 < diff < 10800:  # 3 часа
            print(f'⏰ {pred.get("home_ru", pred["home"])} — {pred.get("away_ru", pred["away"])} '
                  f'через {int(diff/60)} мин')

            # Re-fetch and re-analyze
            matches = fetch_schedule()
            upcoming = _deduplicate_matches(matches.get('upcoming', []))
            elo, nhl_form, form_data, h2h_data = _init_nhl_data()

            for m in upcoming:
                if m.get('home') == pred['home'] and m.get('away') == pred['away']:
                    new_pred = process_nhl_match(m, elo, nhl_form, form_data, h2h_data)
                    if new_pred:
                        refreshed.append(new_pred)
                        existing[key] = new_pred
                    break

    if refreshed:
        _save_predictions(list(existing.values()))
        print(f'✅ Обновлено: {len(refreshed)} прогнозов НХЛ')


def _run_post_nhl_check(predictions):
    """Проверка после batch-генерации НХЛ."""
    from data_schemas import validate
    import os, json

    pred_path = '/opt/predictions_data.json'
    if not os.path.exists(pred_path):
        print('  ⚠️ Post-check: predictions_data.json не найден!')
        return

    try:
        with open(pred_path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f'  ❌ Post-check: ошибка чтения: {e}')
        return

    preds = data.get('predictions', [])
    nhl_preds = [p for p in preds if p.get('league') == 'НХЛ']

    if len(nhl_preds) == 0:
        print('  ❌ Post-check: нет прогнозов НХЛ!')
        return

    ok, errors = validate(data, 'predictions_data')
    if ok:
        print(f'  ✅ Post-check: {len(nhl_preds)} прогнозов НХЛ, схема OK')
    else:
        print(f'  ⚠️ Post-check: {len(errors)} ошибок схемы')
        for e in errors[:3]:
            print(f'    - {e}')


def _save_predictions(new_predictions):
    """Добавить прогнозы НХЛ в общую очередь (JSON + БД)."""
    new_predictions = [p for p in new_predictions if p]
    if not new_predictions:
        return

    for p in new_predictions:
        for field in ('league', 'home', 'away', 'prediction'):
            assert field in p, f'НХЛ прогнозу не хватает поля {field}: {p.get("home","?")} — {p.get("away","?")}'

    existing = {}
    if os.path.exists(PRED_PATH):
        try:
            with open(PRED_PATH, encoding='utf-8') as f:
                for p in json.load(f).get('predictions', []):
                    key = f"{p.get('league','')}||{p.get('home','')}||{p.get('away','')}"
                    existing[key] = p
        except:
            pass

    for p in new_predictions:
        key = f"{p.get('league','')}||{p.get('home','')}||{p.get('away','')}"
        existing[key] = p

    output = {
        'predictions': list(existing.values()),
        'count': len(existing),
        'generated_at': datetime.now().isoformat(),
    }

    with open(PRED_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    if _DB_AVAILABLE:
        for p in new_predictions:
            p['status'] = 'upcoming'
            try:
                db.save_prediction(p)
            except Exception as e:
                print(f'  ⚠️ DB save: {e}')


def main():
    if '--batch' in sys.argv:
        batch_generate()
    elif '--refresh' in sys.argv:
        batch_refresh()
    else:
        print('Режимы: --batch | --refresh')
        print('  --batch   Полная генерация прогнозов')
        print('  --refresh Обновление прогнозов на ближайшие матчи')


if __name__ == '__main__':
    main()
