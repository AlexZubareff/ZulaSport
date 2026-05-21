#!/usr/bin/env python3
"""
NBA Models — Elo-рейтинг команд, форма, H2H, вероятности.

Основа: данные из fetch_nba_espn_data.py (ESPN API).

Особенности:
  - ESPN API — основной источник данных (SStats не поддерживает NBA)
  - Elo через API + результаты завершённых матчей
  - Форма из ESPN teamStatistics
  - H2H из истории матчей
  - Комбинированная вероятность: Elo + форма + букмекер + ESPN Matchup Predictor

Использование:
    from nba_models import NbaElo
    elo = NbaElo()
    prob = elo.predict('Oklahoma City Thunder', 'San Antonio Spurs')
    print(prob)
"""

import json, os, math
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import sys
sys.path.insert(0, '/opt')

# ─── Константы ──────────────────────────────────────────────────────
DATA_DIR = '/opt/data/nba'
ELO_PATH = '/opt/data/nba/elo_ratings.json'
DEFAULT_ELO = 1500
K_FACTOR = 20      # NBA — низкая вариативность, K=20 (норма)
K_FACTOR_PLAYOFFS = 30  # В плей-офф чуть выше
HOME_ADV_ELO = 45  # NBA домашнее преимущество ~3 очка в спреде ≈ 45 Elo

# Веса для комбинированной вероятности
WEIGHT_ELO = 0.40
WEIGHT_FORM = 0.20
WEIGHT_H2H = 0.10
WEIGHT_ODDS = 0.30
WEIGHT_ESPN_PREDICTOR = 0.00  # зарезервировано под ESPN Matchup Predictor


# ═══════════════════════════════════════════════════════════════════
#  Elo Ratings
# ═══════════════════════════════════════════════════════════════════

class NbaElo:
    """
    Elo-рейтинг для команд NBA.

    - Инициализация 1500 (или из кеша)
    - Обновление после каждого матча
    - K=20 (низкая вариативность), K=30 в плей-офф
    - Сохранение в JSON
    """

    def __init__(self):
        self.ratings = {}          # {team_name: elo}
        self.home_advantage = DEFAULT_ELO + HOME_ADV_ELO
        self.match_count = defaultdict(int)
        self._loaded = False
        self._load_cached()

    def _load_cached(self):
        if os.path.exists(ELO_PATH):
            try:
                with open(ELO_PATH, encoding='utf-8') as f:
                    data = json.load(f)
                self.ratings = data.get('ratings', {})
                self.match_count = defaultdict(int, data.get('match_count', {}))
                self._loaded = True
            except:
                pass

    def _save_cached(self):
        data = {
            'ratings': self.ratings,
            'match_count': dict(self.match_count),
            'updated_at': datetime.now().isoformat(),
        }
        os.makedirs(os.path.dirname(ELO_PATH), exist_ok=True)
        with open(ELO_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def init_from_season(self, teams_info=None):
        """
        Инициализировать Elo из данных сезона (record win%).
        Если нет данных — все 1500.
        """
        if teams_info is None:
            # Попробуем загрузить из кеша расписания
            sched_path = f'{DATA_DIR}/schedule.json'
            if os.path.exists(sched_path):
                try:
                    with open(sched_path, encoding='utf-8') as f:
                        sched_data = json.load(f)
                    teams_info = sched_data.get('teams_info', {})
                except:
                    pass

        if teams_info:
            for team, info in teams_info.items():
                wins = info.get('wins', 0)
                losses = info.get('losses', 0)
                total = wins + losses
                if total > 0:
                    win_pct = wins / total
                    # 0.500 → 1500, 0.700 → 1620, 0.300 → 1380
                    base_elo = 1500 + (win_pct - 0.500) * 1000
                    self.ratings[team] = round(max(1100, min(1900, base_elo)), 1)

        self._loaded = True
        if self.ratings:
            print(f'  🏀 Elo: инициализировано {len(self.ratings)} команд')
        self._save_cached()

    def get_elo(self, team: str) -> float:
        return self.ratings.get(team, DEFAULT_ELO)

    def expected_score(self, elo_a: float, elo_b: float) -> float:
        """Ожидаемый счёт (вероятность победы) для A против B."""
        return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))

    def update_after_match(self, home: str, away: str,
                           home_score: int, away_score: int,
                           is_playoff: bool = False):
        """Обновить Elo после матча."""
        elo_home = self.get_elo(home)
        elo_away = self.get_elo(away)

        home_adv = HOME_ADV_ELO if not is_playoff else 0

        expected_home = self.expected_score(elo_home + home_adv, elo_away)
        expected_away = 1.0 - expected_home

        actual_home = 1.0 if home_score > away_score else 0.0
        actual_away = 1.0 - actual_home

        # Разница очков (point differential)
        pt_diff = abs(home_score - away_score)
        k = K_FACTOR_PLAYOFFS if is_playoff else K_FACTOR
        # NBA: за каждые 10 очков разницы +20% к K
        k_adjusted = k * (1 + min(pt_diff, 40) / 10 * 0.2)

        new_elo_home = elo_home + k_adjusted * (actual_home - expected_home)
        new_elo_away = elo_away + k_adjusted * (actual_away - expected_away)

        self.ratings[home] = round(new_elo_home, 1)
        self.ratings[away] = round(new_elo_away, 1)
        self.match_count[home] += 1
        self.match_count[away] += 1

        self._save_cached()

    def predict(self, home: str, away: str, is_playoff: bool = False) -> dict:
        """Прогноз на матч."""
        elo_home = self.get_elo(home)
        elo_away = self.get_elo(away)
        home_adv = HOME_ADV_ELO if not is_playoff else 0

        prob_home = self.expected_score(elo_home + home_adv, elo_away)
        prob_away = 1.0 - prob_home

        return {
            'home': home,
            'away': away,
            'elo_home': round(elo_home, 1),
            'elo_away': round(elo_away, 1),
            'home_adv': home_adv,
            'home_prob': round(prob_home, 4),
            'away_prob': round(prob_away, 4),
            'elo_diff': round(elo_home - elo_away, 1),
            'is_playoff': is_playoff,
        }

    def train_on_history(self, schedule_path=None):
        """Обучить Elo на завершённых матчах из schedule.json."""
        if schedule_path is None:
            schedule_path = f'{DATA_DIR}/schedule.json'

        if not os.path.exists(schedule_path):
            return 0

        try:
            with open(schedule_path, encoding='utf-8') as f:
                sched = json.load(f)
        except:
            return 0

        finished = sched.get('finished', [])
        if not finished:
            return 0

        for m in finished:
            home = m.get('home', '')
            away = m.get('away', '')
            hs = m.get('home_score')
            as_ = m.get('away_score')
            is_playoff = m.get('is_playoff', False) or m.get('playoff', False)
            if home and away and hs is not None and as_ is not None:
                self.update_after_match(home, away, hs, as_, is_playoff=is_playoff)

        print(f'  ✅ NbaElo: обучено на {len(finished)} матчах')
        return len(finished)


# ═══════════════════════════════════════════════════════════════════
#  Team Form (из ESPN)
# ═══════════════════════════════════════════════════════════════════

class NbaForm:
    """
    Форма команд NBA.

    Данные берутся из ESPN teamStatistics (season averages + records).
    """

    @staticmethod
    def from_espn_schedule(schedule_path=None) -> dict:
        """
        Извлечь форму команд из schedule.json (поля teams_info).
        teams_info собирается fetch_nba_espn_data.py из ESPN API.
        """
        if schedule_path is None:
            schedule_path = f'{DATA_DIR}/schedule.json'

        if not os.path.exists(schedule_path):
            return {}

        try:
            with open(schedule_path, encoding='utf-8') as f:
                sched = json.load(f)
        except:
            return {}

        teams_info = sched.get('teams_info', {})
        if not teams_info:
            return {}

        form = {}
        for team, info in teams_info.items():
            wins = info.get('wins', 0)
            losses = info.get('losses', 0)
            total = wins + losses or 1

            form[team] = {
                'team': team,
                'wins': wins,
                'losses': losses,
                'win_pct': round(wins / total, 3),
                'games_played': total,

                # Season stats (season averages)
                'ppg': info.get('avgPoints', info.get('points', 0)),
                'oppg': info.get('avgPointsAgainst', 0),
                'fg_pct': info.get('fieldGoalPct', 0),
                'tp_pct': info.get('threePointPct', 0),
                'ft_pct': info.get('freeThrowPct', 0),
                'rebounds': info.get('avgRebounds', info.get('rebounds', 0)),
                'assists': info.get('avgAssists', info.get('assists', 0)),

                # Дома/в гостях
                'home_wins': info.get('homeWins', 0),
                'home_losses': info.get('homeLosses', 0),
                'road_wins': info.get('roadWins', 0),
                'road_losses': info.get('roadLosses', 0),

                # Streak / L10 — через schedule если есть
                'streak': info.get('streak', ''),
            }

            # L10 если есть
            l10 = info.get('last10', info.get('l10', {}))
            if isinstance(l10, dict):
                form[team]['l10_wins'] = l10.get('wins', 0)
                form[team]['l10_losses'] = l10.get('losses', 0)

        return form

    @staticmethod
    def form_factor(form_data: dict, home: str, away: str) -> dict:
        """Сравнить форму двух команд."""
        fh = form_data.get(home, {})
        fa = form_data.get(away, {})

        # Win %
        wp_h = fh.get('win_pct', 0.5)
        wp_a = fa.get('win_pct', 0.5)

        # PPG differential
        ppg_h = fh.get('ppg', 0)
        ppg_a = fa.get('ppg', 0)
        oppg_h = fh.get('oppg', 0)
        oppg_a = fa.get('oppg', 0)
        net_h = ppg_h - oppg_h
        net_a = ppg_a - oppg_a

        # Дома/в гостях
        hw = fh.get('home_wins', 0)
        hl = fh.get('home_losses', 0)
        h_total = hw + hl or 1
        home_win_pct = hw / h_total

        rw = fa.get('road_wins', 0)
        rl = fa.get('road_losses', 0)
        r_total = rw + rl or 1
        road_win_pct = rw / r_total

        # Итоговый фактор формы (0..1, >0.5 = хозяева в лучшей форме)
        form_score = (
            wp_h * 0.30 +
            home_win_pct * 0.20 +
            max(0, (net_h - net_a) / 20) * 0.25 -
            wp_a * 0.10 -
            road_win_pct * 0.15
        )
        form_score = max(0, min(1, form_score))

        return {
            'home_form': fh,
            'away_form': fa,
            'form_score': round(form_score, 3),
            'home_win_pct': round(wp_h, 3),
            'away_win_pct': round(wp_a, 3),
            'home_home_win_pct': round(home_win_pct, 3),
            'away_road_win_pct': round(road_win_pct, 3),
            'home_net_ppg': round(net_h, 1),
            'away_net_ppg': round(net_a, 1),
        }


# ═══════════════════════════════════════════════════════════════════
#  H2H
# ═══════════════════════════════════════════════════════════════════

class NbaH2H:
    """История личных встреч из завершённых матчей schedule.json."""

    @staticmethod
    def from_schedule(schedule_path=None) -> dict:
        if schedule_path is None:
            schedule_path = f'{DATA_DIR}/schedule.json'

        h2h = defaultdict(lambda: {'home_wins': 0, 'away_wins': 0, 'total': 0, 'matches': []})

        try:
            with open(schedule_path, encoding='utf-8') as f:
                schedule = json.load(f)
        except:
            return {}

        finished = schedule.get('finished', [])
        for m in finished:
            home = m.get('home', '')
            away = m.get('away', '')
            hs = m.get('home_score')
            as_ = m.get('away_score')
            if not home or not away or hs is None or as_ is None:
                continue

            key = tuple(sorted([home, away]))
            h2h[key]['total'] += 1
            h2h[key]['matches'].append({
                'home': home, 'away': away,
                'score': f'{hs}:{as_}',
                'winner': 'home' if hs > as_ else 'away',
                'home_score': hs, 'away_score': as_,
            })
            if hs > as_:
                if home == key[0]:
                    h2h[key]['home_wins'] += 1
                else:
                    h2h[key]['away_wins'] += 1
            else:
                if away == key[0]:
                    h2h[key]['home_wins'] += 1
                else:
                    h2h[key]['away_wins'] += 1

        return dict(h2h)

    @staticmethod
    def get_h2h(h2h_data: dict, team_a: str, team_b: str) -> dict:
        key = tuple(sorted([team_a, team_b]))
        data = h2h_data.get(key, {'home_wins': 0, 'away_wins': 0, 'total': 0, 'matches': []})
        result = {
            'team_a': team_a,
            'team_b': team_b,
            'total': data['total'],
            'matches': data['matches'][-10:],
        }
        if data['total'] > 0:
            if team_a == key[0]:
                result[f'{team_a}_wins'] = data['home_wins']
                result[f'{team_b}_wins'] = data['away_wins']
            else:
                result[f'{team_b}_wins'] = data['home_wins']
                result[f'{team_a}_wins'] = data['away_wins']
        else:
            result[f'{team_a}_wins'] = 0
            result[f'{team_b}_wins'] = 0
        return result


# ═══════════════════════════════════════════════════════════════════
#  Odds parsing
# ═══════════════════════════════════════════════════════════════════

def us_to_decimal(us_odds: str) -> float:
    """Convert US odds (+200, -230) to decimal."""
    try:
        val = float(us_odds)
        if val > 0:
            return round(1 + val / 100, 2)
        else:
            return round(1 - 100 / val, 2)
    except (ValueError, TypeError):
        return None


def parse_espn_odds(match_data: dict) -> dict:
    """
    Парсинг коэффициентов из ESPN API.
    Возвращает home_dec, away_dec, spread, over_under.
    """
    odds_data = match_data.get('odds', match_data.get('_odds', {}))
    if isinstance(odds_data, list):
        odds_data = odds_data[0] if odds_data else {}

    result = {
        'home_dec': None,
        'away_dec': None,
        'home_ml': None,
        'away_ml': None,
        'spread': None,
        'over_under': None,
        'provider': 'DraftKings',
    }

    # Moneyline
    moneyline = odds_data.get('moneyline', {})
    home_ml = moneyline.get('home', {}).get('close', {}).get('odds', '')
    away_ml = moneyline.get('away', {}).get('close', {}).get('odds', '')
    if home_ml:
        result['home_dec'] = us_to_decimal(home_ml)
        result['home_ml'] = home_ml
    if away_ml:
        result['away_dec'] = us_to_decimal(away_ml)
        result['away_ml'] = away_ml

    # Spread
    spread = odds_data.get('spread')
    if spread is not None:
        result['spread'] = spread

    # Over/Under
    ou = odds_data.get('overUnder')
    if ou is not None:
        result['over_under'] = ou

    # Details string (e.g. "OKC -7.5")
    details = odds_data.get('details', '')
    if details and not result['spread']:
        try:
            parts = details.split()
            if len(parts) >= 2:
                sp = parts[-1]
                result['spread'] = float(sp)
        except:
            pass

    return result


# ═══════════════════════════════════════════════════════════════════
#  Combined Probability
# ═══════════════════════════════════════════════════════════════════

def combine_prob(elo_pred: dict, form_factor: dict = None,
                 h2h_result: dict = None, odds: dict = None,
                 espn_predictor: dict = None) -> dict:
    """
    Комбинированная вероятность: Elo + форма + H2H + букмекер + ESPN.

    Args:
        elo_pred: результат NbaElo.predict()
        form_factor: результат NbaForm.form_factor()
        h2h_result: результат NbaH2H.get_h2h()
        odds: результат parse_espn_odds()
        espn_predictor: {'home_prob': float, 'away_prob': float} (из ESPN)

    Returns:
        dict с home_prob, away_prob, weights
    """
    home = elo_pred['home']
    away = elo_pred['away']

    # 1. Elo
    prob_elo_h = elo_pred['home_prob']
    prob_elo_a = elo_pred['away_prob']

    # 2. Form
    prob_form_h = 0.5
    if form_factor:
        ff = form_factor.get('form_score', 0.5)
        prob_form_h = ff
    prob_form_a = 1 - prob_form_h

    # 3. H2H
    prob_h2h_h = 0.5
    if h2h_result and h2h_result['total'] > 0:
        h_wins = h2h_result.get(f'{home}_wins', 0)
        a_wins = h2h_result.get(f'{away}_wins', 0)
        total = h_wins + a_wins
        if total > 0:
            prob_h2h_h = h_wins / total
    prob_h2h_a = 1 - prob_h2h_h

    # 4. Odds (implied probability)
    prob_odds_h = None
    if odds and odds.get('home_dec'):
        try:
            ih = 1.0 / odds['home_dec']
            ia = 1.0 / odds['away_dec']
            margin = ih + ia
            prob_odds_h = ih / margin
        except:
            pass
    prob_odds_a = 1 - prob_odds_h if prob_odds_h else None

    # 5. ESPN Matchup Predictor (если есть)
    prob_espn_h = None
    if espn_predictor and 'home_prob' in espn_predictor:
        prob_espn_h = espn_predictor.get('home_prob', 0.5)
        prob_espn_a = espn_predictor.get('away_prob', 0.5)
    else:
        prob_espn_a = 0.5

    # Dynamic weights
    w_elo = WEIGHT_ELO
    w_form = WEIGHT_FORM
    w_h2h = WEIGHT_H2H
    w_odds = WEIGHT_ODDS
    w_espn = WEIGHT_ESPN_PREDICTOR

    # Если мало данных по форме — перекидываем на Elo
    if not form_factor or not form_factor.get('home_form'):
        w_form *= 0.3
        w_elo += w_form * 0.7

    # Если нет H2H — на Elo + odds
    if not h2h_result or h2h_result['total'] == 0:
        w_h2h = 0
        w_elo += WEIGHT_H2H * 0.5
        w_odds += WEIGHT_H2H * 0.5

    # Если нет odds — на Elo + форму
    if prob_odds_h is None:
        w_odds = 0
        w_elo += WEIGHT_ODDS * 0.6
        w_form += WEIGHT_ODDS * 0.4

    # Если есть ESPN predictor — используем его вес
    if prob_espn_h is not None:
        w_espn = 0.10
        w_elo -= 0.05
        w_odds -= 0.05

    # Нормализация
    total_w = w_elo + w_form + w_h2h + w_odds + w_espn
    w_elo /= total_w
    w_form /= total_w
    w_h2h /= total_w
    w_odds /= total_w
    w_espn /= total_w

    combined_h = (
        prob_elo_h * w_elo +
        prob_form_h * w_form +
        prob_h2h_h * w_h2h +
        (prob_odds_h or prob_elo_h) * w_odds +
        (prob_espn_h or prob_elo_h) * w_espn
    )
    combined_a = 1.0 - combined_h

    return {
        'home': home,
        'away': away,
        'home_prob': round(combined_h, 4),
        'away_prob': round(combined_a, 4),
        'draw_prob': 0.0,
        'elo_prob': round(prob_elo_h, 4),
        'form_prob': round(prob_form_h, 4),
        'h2h_prob': round(prob_h2h_h, 4),
        'odds_prob': round(prob_odds_h, 4) if prob_odds_h else None,
        'espn_prob': round(prob_espn_h, 4) if prob_espn_h is not None else None,
        'weights': {
            'elo': round(w_elo, 3),
            'form': round(w_form, 3),
            'h2h': round(w_h2h, 3),
            'odds': round(w_odds, 3),
            'espn': round(w_espn, 3),
        },
        'elo_diff': elo_pred.get('elo_diff', 0),
    }


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

def load_data():
    """Загрузить все данные NBA."""
    data = {}
    for name in ('schedule',):
        path = f'{DATA_DIR}/{name}.json'
        if os.path.exists(path):
            try:
                with open(path, encoding='utf-8') as f:
                    data[name] = json.load(f)
            except:
                data[name] = {}
        else:
            data[name] = {}
    return data


# ═══════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import sys

    print('🏀 NBA Models')
    print()

    elo = NbaElo()
    if not elo._loaded:
        print('⏳ Инициализация Elo из данных сезона...')
        elo.init_from_season()

    if '--train' in sys.argv:
        print('⏳ Обучение Elo на завершённых матчах...')
        trained = elo.train_on_history()
        print()

    # Show top 10
    print('🏆 Топ-10 команд по Elo:')
    sorted_teams = sorted(elo.ratings.items(), key=lambda x: x[1], reverse=True)
    for i, (team, rating) in enumerate(sorted_teams[:10]):
        print(f'  {i+1}. {team}: {rating:.0f}')

    print()

    # Predict next matches
    try:
        with open(f'{DATA_DIR}/schedule.json', encoding='utf-8') as f:
            sched = json.load(f)
    except:
        sched = {'upcoming': []}

    print('🔮 Прогнозы на предстоящие матчи:')
    nba_form = NbaForm()
    form_data = nba_form.from_espn_schedule()
    h2h_data = NbaH2H.from_schedule()

    for m in sched.get('upcoming', [])[:5]:
        home = m.get('home', '')
        away = m.get('away', '')
        if not home or not away:
            continue

        elo_pred = elo.predict(home, away, is_playoff=m.get('is_playoff', False))
        ff = nba_form.form_factor(form_data, home, away)
        h2h_res = NbaH2H.get_h2h(h2h_data, home, away) if h2h_data else None
        odds = m.get('odds', {})

        combined = combine_prob(elo_pred, ff, h2h_res, odds)

        print(f'  {away} @ {home}: '
              f'P1={combined["home_prob"]*100:.0f}% '
              f'P2={combined["away_prob"]*100:.0f}% '
              f'(Elo {elo_pred["home_prob"]*100:.0f}% | '
              f'Odds {combined["odds_prob"]*100:.0f}% {"(нет)" if combined["odds_prob"] is None else ""})')
