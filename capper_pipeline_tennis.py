#!/usr/bin/env python3
"""
Tennis Capper — теннисный каперский пайплайн.

Режимы:
  --batch       — полная генерация прогнозов на все предстоящие матчи
  --refresh     — обновить прогнозы для матчей <= 3ч
  --mock        — использовать заглушки вместо API (тестирование)

Сохраняет: /opt/predictions_data.json + БД (как футбольный пайплайн)
"""

import json, sys, os, re, math
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import requests

sys.path.insert(0, '/opt')
from capper_common import call_deepseek_with_cache

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

# ─── Tennis модули ─────────────────────────────────────────────────
from tennis_models import TennisStats, _surface_group
from tennis_ratings import TennisElo, combine_probabilities
from fetch_tennis_odds import fetch_all_tennis_matches, mock_data, ODDS_FILE, parse_tennis_matches
from name_ru import ru_name

# ─── Константы ──────────────────────────────────────────────────────
MOW = timedelta(hours=3)
UTC = timezone.utc
PRED_LEAGUES_PATH = '/opt/prediction_leagues.json'
PRED_PATH = '/opt/predictions_data.json'


# ═══════════════════ Загрузчик данных ═══════════════════

def _init_tennis_data(tour='atp'):
    """Инициализировать данные: Elo + статистика."""
    elo = TennisElo(tour)
    if not elo._loaded:
        print(f'  🎾 Elo ({tour}): обучение на истории...')
        elo.train_on_history(year_from=2020)
    else:
        print(f'  🎾 Elo ({tour}): загружен из кеша ({len(elo.ratings)} игроков)')

    stats = TennisStats(tour)
    print(f'  📊 Статистика: {len(stats.matches)} матчей, {len(stats.players)} игроков')
    return elo, stats


def _find_player_odds(home, away, odds_matches):
    """Найти коэффициенты для пары игроков."""
    home_l = home.strip().lower()
    away_l = away.strip().lower()
    for m in odds_matches:
        mh = m.get('home', '').strip().lower()
        ma = m.get('away', '').strip().lower()
        # Прямое совпадение
        if mh == home_l and ma == away_l:
            return m
        # Наоборот
        if mh == away_l and ma == home_l:
            return {
                **m,
                'home': m.get('away', ''),
                'away': m.get('home', ''),
                'odds_home': m.get('odds_away'),
                'odds_away': m.get('odds_home'),
            }
        # Частичное совпадение (фамилии)
        h_parts = home_l.split()
        a_parts = away_l.split()
        if len(h_parts) > 1 and len(a_parts) > 1:
            h_last = h_parts[-1]
            a_last = a_parts[-1]
            if h_last in mh and a_last in ma:
                return m
            if h_last in ma and a_last in mh:
                return {
                    **m,
                    'home': m.get('away', ''),
                    'away': m.get('home', ''),
                    'odds_home': m.get('odds_away'),
                    'odds_away': m.get('odds_home'),
                }
    return None


# ═══════════════════ Elo + статистика для матча ═══════════════════

def analyze_match(home, away, elo, stats, surface=None) -> Dict:
    """Полный анализ теннисного матча."""
    result = {
        'home': home,
        'away': away,
        'surface': surface or 'Unknown',
    }

    # 1. Elo прогноз
    elo_pred = elo.predict(home, away, surface=surface)
    result['elo'] = elo_pred

    # 2. Форма
    form_h = stats.form_summary(home, surface=surface, n=10)
    form_a = stats.form_summary(away, surface=surface, n=10)
    result['form'] = {'home': form_h, 'away': form_a}

    # 3. H2H
    h2h = stats.h2h_summary(home, away)
    result['h2h'] = h2h

    # 4. H2H на этой поверхности
    if surface:
        h2h_surface = stats.recent_h2h_on_surface(home, away, surface)
        result['h2h_surface'] = h2h_surface

    # 5. Статистика (эйсы, двойные)
    stat_h = stats.player_stats(home, n=15)
    stat_a = stats.player_stats(away, n=15)
    result['serve_stats'] = {'home': stat_h, 'away': stat_a}

    # 6. Рейтинг
    result['ranking'] = {
        'home': stats.player_ranking(home),
        'away': stats.player_ranking(away),
    }

    # 7. Предпочтения по поверхности
    pref_h = stats.surface_preference(home, n=40)
    pref_a = stats.surface_preference(away, n=40)
    result['surface_pref'] = {'home': pref_h, 'away': pref_a}

    # 8. Комбинированная вероятность
    elo_prob = elo_pred['prob1']
    h2h_prob = None
    form_prob = None

    if h2h['total'] > 0:
        p1 = home.strip()
        p1_wins = h2h.get(f'{p1}_wins', 0)
        h2h_prob = p1_wins / max(h2h['total'], 1)

    # Форма
    if form_h['total'] > 0 or form_a['total'] > 0:
        h_win = form_h['win_pct']
        a_win = form_a['win_pct']
        total = h_win + a_win
        if total > 0:
            form_prob = h_win / total

    combined = combine_probabilities(elo_prob, h2h_prob, form_prob)
    result['combined_prob'] = round(combined, 4)
    result['combined_prob_away'] = round(1 - combined, 4)

    return result


def _determine_surface_from_league(tour_tag):
    """Определить поверхность по турниру (приблизительно)."""
    return 'Hard'


# ═══════════════════ DeepSeek генерация ═══════════════════

def _build_capper_stats_tennis():
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

    return (
        f'\n📊 Твоя текущая статистика: '
        f'Win {wc}/{wt} ({wc/wt*100:.0f}%) | Total {tc}/{tt} ({tc/tt*100:.0f}%)'
    )


def _build_tennis_prompt(analysis: Dict, odds_match=None) -> str:
    """Собрать промпт для DeepSeek."""
    home = analysis['home']
    away = analysis['away']
    surface = analysis['surface']
    elo = analysis['elo']
    form = analysis['form']
    h2h = analysis['h2h']
    h2h_surface = analysis.get('h2h_surface')
    serve_stats = analysis['serve_stats']
    ranking = analysis['ranking']
    surface_pref = analysis['surface_pref']
    combined = analysis['combined_prob']

    parts = []
    parts.append(f'Теннисный матч: {ru_name(home)} — {ru_name(away)}')
    parts.append(f'Покрытие: {surface}')

    r_h = ranking.get('home')
    r_a = ranking.get('away')
    if r_h or r_a:
        parts.append(f'Рейтинг: {ru_name(home)} — {r_h or "—"}, {ru_name(away)} — {r_a or "—"}')

    parts.append(f'\nElo рейтинг:')
    parts.append(f'  {ru_name(home)}: {elo["elo1"]:.0f}')
    parts.append(f'  {ru_name(away)}: {elo["elo2"]:.0f}')
    parts.append(f'  Вероятность: {ru_name(home)} {elo["prob1"]*100:.0f}% / {ru_name(away)} {elo["prob2"]*100:.0f}%')
    parts.append(f'  Комбинированная: {ru_name(home)} {combined*100:.0f}% / {ru_name(away)} {analysis["combined_prob_away"]*100:.0f}%')

    # Форма
    for side, form_data in [('home', form['home']), ('away', form['away'])]:
        name = ru_name(home) if side == 'home' else ru_name(away)
        if form_data['total'] > 0:
            parts.append(f'\nФорма {name} ({surface}): {form_data["wins"]}W/{form_data["losses"]}L '
                         f'({form_data["win_pct"]*100:.0f}%)')
            if form_data.get('by_surface'):
                for s, d in form_data['by_surface'].items():
                    parts.append(f'  {s}: {d["w"]}W/{d["l"]}L')

    # H2H
    if h2h['total'] > 0:
        p1 = home.strip()
        p2 = away.strip()
        p1_w = h2h.get(f'{p1}_wins', 0)
        p2_w = h2h.get(f'{p2}_wins', 0)
        parts.append(f'\nОчные встречи: {ru_name(p1)} {p1_w} — {ru_name(p2)} {p2_w} (всего {h2h["total"]})')
        if h2h_surface and h2h_surface.get('total', 0) > 0:
            p1_ws = h2h_surface.get(f'{p1}_wins', 0)
            p2_ws = h2h_surface.get(f'{p2}_wins', 0)
            parts.append(f'На {surface}: {p1_ws}-{p2_ws}')

    # Статистика подачи
    for side, name, data in [('home', home, serve_stats['home']),
                              ('away', away, serve_stats['away'])]:
        if data:
            parts.append(f'\n{ru_name(name)}: эйсы {data.get("avg_ace", "—")}/м, '
                         f'ДО {data.get("avg_df", "—")}/м, '
                         f'1-я подача {data.get("first_serve_pct", 0)*100:.0f}%')

    # Коэффициенты
    if odds_match:
        oh = odds_match.get('odds_home')
        oa = odds_match.get('odds_away')
        if oh and oa:
            parts.append(f'\nКоэффициенты: {ru_name(home)} — {oh}, {ru_name(away)} — {oa}')

    # Предпочтения по поверхности
    if surface_pref.get('home') and surface_pref.get('away'):
        parts.append('\nУспешность по покрытиям:')
        for s in ['Hard', 'Clay', 'Grass']:
            h = surface_pref['home'].get(s, {})
            a = surface_pref['away'].get(s, {})
            if h or a:
                h_pct = f'{h["win_pct"]*100:.0f}%' if h else '—'
                a_pct = f'{a["win_pct"]*100:.0f}%' if a else '—'
                parts.append(f'  {s}: {ru_name(home)} {h_pct} vs {ru_name(away)} {a_pct}')

    parts.append('\nНапиши прогноз. Сначала краткий анализ (1-2 предложения), ')
    parts.append('затем чёткий вердикт: исход + уверенность в %.')

    return '\n'.join(parts)


def generate_tennis_prediction(analysis: Dict, odds_match=None) -> str:
    """Сгенерировать текст прогноза через DeepSeek (с кешем)."""
    if not DEEPSEEK_KEY:
        return _fallback_prediction(analysis, odds_match)

    def _do_generate():
        prompt = _build_tennis_prompt(analysis, odds_match)
        stats_block = _build_capper_stats_tennis()

        system_msg = ('Ты спортивный аналитик. Пиши структурированный прогноз с аналитикой: '
                      'аргументы за/против, ключевой фактор матча, итоговый вердикт. '
                      'Формат: абзац анализа → краткий вердикт. '
                      'В вердикте укажи: исход (кто победит), уверенность в %. '
                      'Если есть данные по тоталу — добавь и его прогноз. '
                      'Не используй шаблонные фразы про "время сбилось" или "посмотрим правде в глаза".')
        if stats_block:
            system_msg += stats_block

        try:
            resp = requests.post('https://api.deepseek.com/v1/chat/completions', json={
                'model': 'deepseek-v4-flash',
                'messages': [
                    {'role': 'system', 'content': system_msg},
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0.3,
                'max_tokens': 1200
            }, headers={'Authorization': f'Bearer {DEEPSEEK_KEY}'}, timeout=60)
            data = resp.json()
            if 'choices' in data and len(data['choices']) > 0:
                text = data['choices'][0]['message']['content'].strip()
                text = text.replace('Over', 'ТБ').replace('Under', 'ТМ')
                text = text.replace('over', 'ТБ').replace('under', 'ТМ')
                text = text.replace('тотал больше', 'ТБ').replace('тотал меньше', 'ТМ')
                return text
        except Exception as e:
            print(f'  ⚠️ DeepSeek: {e}')

        return _fallback_prediction(analysis, odds_match)

    # Исправление: analysis не содержит ключей 'combined' или 'home_ru'
    # Используем 'home'/'away' и 'combined_prob'/'combined_prob_away'
    match_info = {'home': analysis.get('home', ''), 'away': analysis.get('away', ''), 'league': 'Tennis'}
    elo = analysis.get('elo', {})
    sstats_data = {
        'odds': [{'home': odds_match.get('odds_home', 0.5) if odds_match else 0.5,
                  'draw': 0,
                  'away': odds_match.get('odds_away', 0.5) if odds_match else 0.5}],
        'glicko': {'home_prob': elo.get('prob1', analysis.get('combined_prob', 0.5)),
                   'away_prob': elo.get('prob2', analysis.get('combined_prob_away', 0.5)),
                   'draw_prob': 0},
        'totals': {},
    }
    force_refresh = '--refresh' in sys.argv or '--no-cache' in sys.argv
    return call_deepseek_with_cache(match_info, sstats_data, _do_generate, force_refresh=force_refresh)


def _fallback_prediction(analysis, odds_match=None):
    """Запасной прогноз."""
    home = ru_name(analysis['home'])
    away = ru_name(analysis['away'])
    prob = analysis['combined_prob']
    elo = analysis['elo']

    if prob > 0.5:
        return (f'По моим расчётам, {home} — фаворит с вероятностью {prob*100:.0f}% '
                f'(Elo {elo["elo1"]:.0f} vs {elo["elo2"]:.0f}). Рекомендую чистую победу {home}.')
    else:
        return (f'По моим расчётам, {away} — фаворит с вероятностью {(1-prob)*100:.0f}% '
                f'(Elo {elo["elo2"]:.0f} vs {elo["elo1"]:.0f}). Рекомендую чистую победу {away}.')


def _ru_text(text, *players):
    """Заменить английские имена игроков на русские в тексте прогноза."""
    for p in players:
        if not p:
            continue
        ru = ru_name(p)
        if ru != p:
            # exact match whole word
            text = text.replace(p, ru)
    return text


# ═══════════════════ Основной цикл ═══════════════════

def process_tennis_match(match_info, elo_atp=None, stats_atp=None, elo_wta=None, stats_wta=None, odds_matches=None):
    """Обработать один теннисный матч."""
    home = match_info.get('home', '')
    away = match_info.get('away', '')
    tour = match_info.get('tour', 'ATP')

    print(f'  🎾 {ru_name(home)} — {ru_name(away)}... ', end='', flush=True)

    is_atp = tour in ('ATP', 'atp')
    elo = elo_atp if is_atp else elo_wta
    stats = stats_atp if is_atp else stats_wta

    # Определяем поверхность
    surface = match_info.get('surface', match_info.get('sport_key', ''))
    if 'clay' in str(surface).lower() or 'french' in str(surface).lower() or 'monte' in str(surface).lower() or 'rome' in str(surface).lower() or 'madrid' in str(surface).lower() or 'barcelona' in str(surface).lower():
        surface = 'Clay'
    elif 'grass' in str(surface).lower() or 'wimbledon' in str(surface).lower() or 'halle' in str(surface).lower() or 'queen' in str(surface).lower():
        surface = 'Grass'
    else:
        surface = _determine_surface_from_league(tour)

    if not elo or not stats:
        print('⚠️ нет данных, прогноз по кэфам', end=' ', flush=True)
        oh = match_info.get('odds_home')
        oa = match_info.get('odds_away')
        if oh and oa:
            oh = float(oh)
            oa = float(oa)
            prob_h = oa / (oh + oa) if (oh + oa) > 0 else 0.5
            prob_a = 1 - prob_h
            # Создаём минимальный анализ
            analysis = {
                'home': home, 'away': away,
                'surface': surface,
                'elo': {'elo1': 1500, 'elo2': 1500, 'prob1': prob_h, 'prob2': prob_a},
                'form': {'home': {'total': 0}, 'away': {'total': 0}},
                'h2h': {'total': 0},
                'serve_stats': {'home': {}, 'away': {}},
                'ranking': {'home': None, 'away': None},
                'surface_pref': {'home': {}, 'away': {}},
                'combined_prob': prob_h,
                'combined_prob_away': prob_a,
            }
            prob = analysis['combined_prob']
            print(f'P1={prob*100:.0f}%', end=' ', flush=True)
            # Fallback: без DeepSeek, только по кэфам
            if prob > 0.5:
                fav = ru_name(home)
            else:
                fav = ru_name(away)
            pred_text = f'Фаворит по коэффициентам: {fav}. '
            pred_text += f'Вероятность победы {ru_name(home)} — {prob*100:.0f}% (кэф {oh:.2f}), '
            pred_text += f'{ru_name(away)} — {(1-prob)*100:.0f}% (кэф {oa:.2f}). '
            odds_ratio = oa / oh
            if odds_ratio > 3:
                pred_text += f'Фаворит явный, но коэффициент низкий — проходимость вероятна.'
            elif odds_ratio > 1.5:
                pred_text += f'Фаворит умеренный, есть смысл в ставке.'
            else:
                pred_text += f'Матч близкий по коэффициентам — возможен любой исход.'
            print(f'✅')
            verdict_line = pred_text[:120]
            pred_text = _ru_text(pred_text, home, away)
            return {
                'home': ru_name(home), 'away': ru_name(away),
                'home_ru': ru_name(home), 'away_ru': ru_name(away),
                'league': tour, 'time': match_info.get('match_time', ''),
                'match_date': match_info.get('match_date', ''),
                'verdict': verdict_line, 'prediction': pred_text,
                'odds': {'home': oh, 'away': oa},
                'glicko': {'home_prob': round(prob,3), 'away_prob': round(1-prob,3), 'draw_prob': 0.0,
                          'home_rating': 1500, 'away_rating': 1500, 'home_xg': 0, 'away_xg': 0},
                'generated_at': datetime.now().isoformat(),
                'surface': surface, 'tournament': match_info.get('sport_key', ''),
            }
        print('❌ нет кэфов')
        return None

    odds_match = _find_player_odds(home, away, odds_matches or [])

    print(f'{surface}', end=' ', flush=True)

    analysis = analyze_match(home, away, elo, stats, surface=surface)

    prob = analysis['combined_prob']
    print(f'P1={prob*100:.0f}%', end=' ', flush=True)

    pred_text = generate_tennis_prediction(analysis, odds_match)
    print(f'✅')

    verdict_line = pred_text.split('.')[0] if '.' in pred_text else pred_text[:100]
    if len(verdict_line) > 120:
        verdict_line = verdict_line[:120] + '...'

    pred_text = _ru_text(pred_text, home, away)

    return {
        'home': ru_name(home),
        'away': ru_name(away),
        'home_ru': ru_name(home),
        'away_ru': ru_name(away),
        'league': tour,
        'time': match_info.get('match_time', ''),
        'match_date': match_info.get('match_date', ''),
        'verdict': verdict_line,
        'prediction': pred_text,
        'odds': {
            'home': odds_match.get('odds_home') if odds_match else None,
            'away': odds_match.get('odds_away') if odds_match else None,
        } if odds_match else None,
        'glicko': {
            'home_prob': round(prob, 3),
            'away_prob': round(1 - prob, 3),
            'draw_prob': 0.0,
            'home_rating': round(analysis['elo']['elo1'], 1),
            'away_rating': round(analysis['elo']['elo2'], 1),
            'home_xg': 0,
            'away_xg': 0,
        },
        'generated_at': datetime.now().isoformat(),
        'surface': surface,
        'tournament': match_info.get('sport_key', ''),
    }


def batch_generate(mock=False):
    """Полная генерация прогнозов на все предстоящие теннисные матчи."""
    if mock:
        print('🎾 Режим --mock (заглушки)')
        odds_matches = mock_data()
    else:
        print('🎾 Загрузка коэффициентов из The Odds API...')
        try:
            odds_matches = fetch_all_tennis_matches()
        except Exception as e:
            print(f'  ⚠️ Ошибка: {e}')
            odds_matches = []

    if not odds_matches:
        print('  Нет матчей через API, пробую заглушки...')
        odds_matches = mock_data()
        mock = True

    atp_matches = [m for m in odds_matches if m.get('tour') == 'ATP']
    wta_matches = [m for m in odds_matches if m.get('tour') == 'WTA']

    if not atp_matches and not wta_matches:
        print('❌ Нет теннисных матчей для прогнозов')
        _save_predictions([])
        _run_post_tennis_check([])
        return

    # Валидация входящих данных
    for m in atp_matches + wta_matches:
        assert m.get('home'), f'Теннисный матч без home: {m}'
        assert m.get('away'), f'Теннисный матч без away: {m}'

    print(f'\n📊 ATP: {len(atp_matches)}, WTA: {len(wta_matches)}')

    elo_atp = None
    stats_atp = None
    elo_wta = None
    stats_wta = None

    if atp_matches:
        print('\n🎾 Загрузка ATP данных...', end=' ', flush=True)
        try:
            elo_atp, stats_atp = _init_tennis_data('atp')
        except Exception as e:
            print(f'⚠️ {e}')

    if wta_matches:
        print('\n🎾 Загрузка WTA данных...', end=' ', flush=True)
        try:
            elo_wta, stats_wta = _init_tennis_data('wta')
        except Exception as e:
            print(f'⚠️ {e}')

    predictions = []

    for i, m in enumerate(atp_matches):
        pred = process_tennis_match(m, elo_atp, stats_atp, elo_wta, stats_wta, atp_matches)
        if pred:
            predictions.append(pred)
        if i % 3 == 2 or i == len(atp_matches) - 1:
            _save_predictions(predictions)

    for i, m in enumerate(wta_matches):
        pred = process_tennis_match(m, elo_wta, stats_wta, elo_wta, stats_wta, wta_matches)
        if pred:
            predictions.append(pred)
        save_after = (i % 3 == 2 or i == len(wta_matches) - 1 or
                      i + len(atp_matches) == len(atp_matches) + len(wta_matches) - 1)
        if save_after:
            _save_predictions(predictions)

    print(f'\n✅ Всего: {len(predictions)} теннисных прогнозов')
    _run_post_tennis_check(predictions)


def batch_refresh():
    """Обновить прогнозы для ближайших матчей (<= 3 часа)."""
    now = datetime.now(UTC) + MOW

    existing = {}
    if os.path.exists(PRED_PATH):
        try:
            with open(PRED_PATH, encoding='utf-8') as f:
                for p in json.load(f).get('predictions', []):
                    if p.get('league') in ('ATP', 'WTA'):
                        existing[(p.get('league',''), p.get('home',''), p.get('away',''))] = p
        except:
            pass

    tennis_preds = {k: v for k, v in existing.items() if k[0] in ('ATP', 'WTA')}
    if not tennis_preds:
        print('  Нет активных теннисных прогнозов для обновления')
        return

    refreshed = []
    for key, pred in tennis_preds.items():
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
        if 0 < diff < 10800:
            print(f'⏰ {pred.get("home_ru", pred["home"])} — {pred.get("away_ru", pred["away"])} '
                  f'через {int(diff/60)} мин')
            refreshed.append(pred)

    if refreshed:
        print(f'✅ Обновлено: {len(refreshed)} прогнозов')


def _run_post_tennis_check(predictions):
    """Проверка после batch-генерации тенниса."""
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
    tennis_preds = [p for p in preds if p.get('league') in ('ATP', 'WTA')]

    if len(tennis_preds) == 0:
        print('  ❌ Post-check: нет теннисных прогнозов!')
        return

    ok, errors = validate(data, 'predictions_data')
    if ok:
        print(f'  ✅ Post-check: {len(tennis_preds)} прогнозов тенниса, схема OK')
    else:
        print(f'  ⚠️ Post-check: {len(errors)} ошибок схемы')
        for e in errors[:3]:
            print(f'    - {e}')


def _norm_key(league, home, away):
    """Нормализованный ключ для дедупликации.
    
    Переводит оба имени в русский через name_ru (если это теннис),
    чтобы 'Alejandro Tabilo' и 'Алехандро Табило' совпадали.
    """
    try:
        from name_ru import ru_name
        def normalize(name):
            ru = ru_name(name)
            # Берём последнее слово (фамилию) после перевода
            parts = ru.strip().lower().split()
            return parts[-1] if parts else name.lower()
    except Exception:
        # Fallback: просто последнее слово в нижнем регистре
        def normalize(name):
            parts = name.strip().lower().split()
            return parts[-1] if parts else name.lower()
    return f"{league}||{normalize(home)}||{normalize(away)}"


def _save_predictions(new_predictions):
    """Добавить теннисные прогнозы в общую очередь.
    
    Дедупликация: если спор+фамилии совпадают, оставляем последнюю версию.
    """
    new_predictions = [p for p in new_predictions if p]
    if not new_predictions:
        return

    for p in new_predictions:
        for field in ('league', 'home', 'away', 'prediction'):
            assert field in p, f'Теннисному прогнозу не хватает поля {field}: {p.get("home","?")} — {p.get("away","?")}'

    existing = {}
    if os.path.exists(PRED_PATH):
        try:
            with open(PRED_PATH, encoding='utf-8') as f:
                for p in json.load(f).get('predictions', []):
                    key = _norm_key(p.get('league',''), p.get('home',''), p.get('away',''))
                    # Для неменяющихся ключей храним все варианты
                    existing.setdefault(key, []).append(p)
        except:
            pass

    # Новые прогнозы: сохраняем по нормализованному ключу, затирая старые
    for p in new_predictions:
        key = _norm_key(p.get('league',''), p.get('home',''), p.get('away',''))
        existing[key] = [p]

    # Собираем обратно: из каждого ключа берём последнюю запись
    merged = []
    for items in existing.values():
        # Берём последнюю (самую свежую, с русскими именами)
        merged.append(items[-1])

    output = {
        'predictions': merged,
        'count': len(merged),
        'generated_at': datetime.now().isoformat(),
    }

    with open(PRED_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    if _DB_AVAILABLE:
        for p in new_predictions:
            p['status'] = 'upcoming'
            try:
                # Сохраняем матч в таблицу matches (для расписания/результатов)
                match_date = (p.get('match_date') or '').strip()
                # Конвертируем DD.MM.YYYY → YYYY-MM-DD
                if match_date and '.' in match_date:
                    try:
                        from datetime import datetime as _dt
                        match_date = _dt.strptime(match_date[:10], '%d.%m.%Y').strftime('%Y-%m-%d')
                    except:
                        pass
                if not match_date or match_date.count('-') != 2 or len(match_date) != 10:
                    match_date = datetime.now().strftime('%Y-%m-%d')
                tournament = p.get('tournament', '') or ''
                # Чистим префикс tennis_ для отображения
                if tournament.startswith('tennis_'):
                    tournament = tournament[7:]
                match_data = {
                    'league': p['league'],
                    'home': p['home'],
                    'away': p['away'],
                    'match_date': match_date,
                    'match_time': p.get('match_time', '') or p.get('time', ''),
                    'status': 'scheduled',
                    'source': 'theoddsapi',
                    'tournament': tournament,
                }
                match_data['match_time'] = match_data['match_time'][:5] if len(match_data['match_time']) > 5 else match_data['match_time']
                db.save_match(match_data)
            except Exception as e:
                print(f'  ⚠️ save_match: {e}')
            try:
                db.save_prediction(p)
            except:
                pass

    try:
        from capper_common import trigger_generate
        trigger_generate('predictions')
    except Exception:
        pass


def main():
    mock = '--mock' in sys.argv
    if '--batch' in sys.argv:
        batch_generate(mock=mock)
    elif '--refresh' in sys.argv:
        batch_refresh()
    else:
        print('Режимы: --batch | --refresh | --mock (тест с заглушками)')


if __name__ == '__main__':
    main()
