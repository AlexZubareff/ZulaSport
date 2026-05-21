#!/usr/bin/env python3
"""
NHL Models — Elo-рейтинг команд, форма, H2H, вероятности.

Основа: данные из fetch_nhl_data.py (schedule.json, standings.json).

Использование:
    from nhl_models import NhlElo
    elo = NhlElo()
    prob = elo.predict('Colorado Avalanche', 'Vegas Golden Knights')
    print(prob)  # {'home_prob': 0.62, 'away_prob': 0.38, ...}
"""

import json, os, math
from datetime import datetime, timezone, timedelta
from collections import defaultdict, OrderedDict

import sys
sys.path.insert(0, '/opt')

# ─── Константы ──────────────────────────────────────────────────────
DATA_DIR = '/opt/data/nhl'
ELO_PATH = '/opt/data/nhl/elo_ratings.json'
DEFAULT_ELO = 1500
K_FACTOR = 32  # Стандартный K-factor для командных видов
K_FACTOR_PLAYOFFS = 48  # В плей-офф K-factor выше

# Веса для комбинированной вероятности
WEIGHT_ELO = 0.45
WEIGHT_FORM = 0.25
WEIGHT_H2H = 0.15
WEIGHT_ODDS = 0.15


# ═══════════════════════════════════════════════════════════════════
#  Elo Ratings
# ═══════════════════════════════════════════════════════════════════

class NhlElo:
    """
    Elo-рейтинг для команд НХЛ.

    - Инициализация из турнирной таблицы (points → Elo)
    - Обновление после каждого матча
    - Сохранение в JSON для персистентности
    - Расчёт вероятности победы
    """

    def __init__(self):
        self.ratings = {}       # {team_name: elo}
        self.home_advantage = DEFAULT_ELO + 35  # Стандартное преимущество дома
        self.match_count = defaultdict(int)
        self._loaded = False
        self._load_cached()

    def _load_cached(self):
        """Загрузить кеш Elo."""
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
        """Сохранить кеш Elo."""
        data = {
            'ratings': self.ratings,
            'match_count': dict(self.match_count),
            'updated_at': datetime.now().isoformat(),
        }
        os.makedirs(os.path.dirname(ELO_PATH), exist_ok=True)
        with open(ELO_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def init_from_standings(self, standings=None):
        """Инициализировать Elo из турнирной таблицы.
        Используем points как прокси: points/Gp * 1500 + base.
        """
        if standings is None:
            try:
                with open(f'{DATA_DIR}/standings.json', encoding='utf-8') as f:
                    standings = json.load(f)
            except:
                print('  ⚠️ Статистика не найдена, использую дефолтный Elo=1500')
                return

        for s in standings:
            team = s.get('team', '')
            if not team or team == '?':
                continue
            gp = s.get('games_played', 82) or 82
            pts = s.get('points', 0) or 0
            # scale: 70 pts → 1300, 100 → 1450, 120 → 1550
            # pts/GP норма: ~1.0 (82 pts), отлично ~1.5 (123 pts)
            norm = (pts / max(gp, 1) - 0.85) * 500 + 1500
            base_elo = max(1000, min(1800, norm))
            self.ratings[team] = round(base_elo, 1)

        self._loaded = True
        print(f'  🏒 Elo: инициализировано {len(self.ratings)} команд из таблицы')
        self._save_cached()

    def get_elo(self, team: str) -> float:
        """Текущий Elo команды."""
        return self.ratings.get(team, DEFAULT_ELO)

    def home_elo(self, team: str) -> float:
        """Elo с учётом домашнего преимущества."""
        return self.ratings.get(team, DEFAULT_ELO) + 35

    def expected_score(self, elo_a: float, elo_b: float) -> float:
        """Ожидаемый счёт (вероятность победы) для команды A против B."""
        return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))

    def update_after_match(self, home: str, away: str, home_score: int, away_score: int,
                            game_type: int = 2):
        """Обновить Elo после матча.
        game_type: 2 = regular, 3 = playoffs
        """
        elo_home = self.get_elo(home)
        elo_away = self.get_elo(away)
        home_adv = 35

        # В плей-офф нет «домашнего преимущества» в Elo
        if game_type == 3:
            home_adv = 0

        expected_home = self.expected_score(elo_home + home_adv, elo_away)
        expected_away = 1.0 - expected_home

        # Определяем победителя
        if home_score > away_score:
            actual_home = 1.0
            actual_away = 0.0
        else:
            actual_home = 0.0
            actual_away = 1.0

        # В НХЛ важна разница шайб (goal differential)
        goal_diff = abs(home_score - away_score)
        # K-factor с учётом разницы
        k = K_FACTOR_PLAYOFFS if game_type == 3 else K_FACTOR
        k_adjusted = k * (1 + min(goal_diff, 7) * 0.1)

        new_elo_home = elo_home + k_adjusted * (actual_home - expected_home)
        new_elo_away = elo_away + k_adjusted * (actual_away - expected_away)

        self.ratings[home] = round(new_elo_home, 1)
        self.ratings[away] = round(new_elo_away, 1)
        self.match_count[home] += 1
        self.match_count[away] += 1

        self._save_cached()

    def predict(self, home: str, away: str, game_type: int = 2) -> dict:
        """Прогноз на матч: вероятности, Elo, разница."""
        elo_home = self.get_elo(home)
        elo_away = self.get_elo(away)
        home_adv = 35 if game_type != 3 else 0

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
            'game_type': game_type,
        }

    def train_on_history(self, schedule_path=None):
        """Обучить Elo на завершённых матчах из schedule.json."""
        if schedule_path is None:
            schedule_path = f'{DATA_DIR}/schedule.json'

        if not os.path.exists(schedule_path):
            print(f'  ⚠️ Нет history: {schedule_path}')
            return 0

        try:
            with open(schedule_path, encoding='utf-8') as f:
                sched = json.load(f)
        except:
            return 0

        finished = sched.get('finished', [])
        if not finished:
            print('  ⚠️ Нет завершённых матчей для обучения')
            return 0

        for m in finished:
            home = m.get('home', '')
            away = m.get('away', '')
            hs = m.get('home_score')
            as_ = m.get('away_score')
            gt = m.get('game_type', 2)
            if home and away and hs is not None and as_ is not None:
                self.update_after_match(home, away, hs, as_, game_type=gt)

        print(f'  ✅ Elo: обучено на {len(finished)} матчах')
        return len(finished)


# ═══════════════════════════════════════════════════════════════════
#  Team Form
# ═══════════════════════════════════════════════════════════════════

class NhlForm:
    """Форма команд: L10, дома/в гостях, разница шайб."""

    @staticmethod
    def from_standings(standings=None) -> dict:
        """Собрать форму всех команд из таблицы."""
        if standings is None:
            try:
                with open(f'{DATA_DIR}/standings.json', encoding='utf-8') as f:
                    standings = json.load(f)
            except:
                return {}

        form = {}
        for s in standings:
            team = s.get('team', '')
            if not team:
                continue
            form[team] = {
                'team': team,
                'team_ru': s.get('team_ru', team),

                # Сезон
                'gp': s.get('games_played', 0),
                'pts': s.get('points', 0),
                'pt_pct': s.get('point_pct', 0),
                'wins': s.get('wins', 0),
                'losses': s.get('losses', 0),
                'ot_losses': s.get('ot_losses', 0),
                'gf': s.get('goal_for', 0),
                'ga': s.get('goal_against', 0),
                'gd': s.get('goal_diff', 0),
                'gf_per_g': round(s.get('goal_for', 0) / max(s.get('games_played', 1), 1), 2),
                'ga_per_g': round(s.get('goal_against', 0) / max(s.get('games_played', 1), 1), 2),

                # Дома
                'home_wins': s.get('home_wins', 0),
                'home_losses': s.get('home_losses', 0),
                'home_ot_losses': s.get('home_ot_losses', 0),
                'home_pts': s.get('home_points', 0),

                # В гостях
                'road_wins': s.get('road_wins', 0),
                'road_losses': s.get('road_losses', 0),
                'road_ot_losses': s.get('road_ot_losses', 0),
                'road_pts': s.get('road_points', 0),

                # L10
                'l10_wins': s.get('l10_wins', 0),
                'l10_losses': s.get('l10_losses', 0),
                'l10_ot_losses': s.get('l10_ot_losses', 0),
                'l10_points': s.get('l10_points', 0),
                'l10_gf': s.get('l10_goals_for', 0),
                'l10_ga': s.get('l10_goals_against', 0),
                'l10_gd': s.get('l10_goals_for', 0) - s.get('l10_goals_against', 0),

                # Streak
                'streak_code': s.get('streak_code', ''),
                'streak_count': s.get('streak_count', 0),

                # Win % в регулярке и с OT
                'rw_pct': round(s.get('wins', 0) / max(s.get('games_played', 1), 1), 3),
                'row_pct': round(s.get('regulation_plus_ot_wins', 0) / max(s.get('games_played', 1), 1), 3),
            }

        return form

    @staticmethod
    def form_factor(form_data: dict, home: str, away: str) -> dict:
        """Сравнить форму двух команд. Вернуть коррекцию."""
        fh = form_data.get(home, {})
        fa = form_data.get(away, {})

        # L10 win rates
        l10_h = fh.get('l10_wins', 0) / max(fh.get('l10_points', 1), 1) * 2 if fh.get('l10_points', 0) > 0 else 0.5
        l10_a = fa.get('l10_wins', 0) / max(fa.get('l10_points', 1), 1) * 2 if fa.get('l10_points', 0) > 0 else 0.5

        # Home/road specific
        home_gp_h = fh.get('home_wins', 0) + fh.get('home_losses', 0) + fh.get('home_ot_losses', 0) or 1
        home_win_pct = fh.get('home_wins', 0) / home_gp_h
        road_gp_a = fa.get('road_wins', 0) + fa.get('road_losses', 0) + fa.get('road_ot_losses', 0) or 1
        road_win_pct = fa.get('road_wins', 0) / road_gp_a

        # Goal differentials
        gd_h_l10 = fh.get('l10_gd', 0)
        gd_a_l10 = fa.get('l10_gd', 0)

        # Итоговый фактор формы (0..1, где >0.5 значит хозяева в лучшей форме)
        form_score = (
            l10_h * 0.35 +
            home_win_pct * 0.30 +
            max(0, gd_h_l10 / 10) * 0.15 -
            l10_a * 0.10 -
            road_win_pct * 0.05 -
            max(0, gd_a_l10 / 10) * 0.05
        )
        form_score = max(0, min(1, form_score))

        return {
            'home_form': fh,
            'away_form': fa,
            'l10_home_win_pct': round(l10_h, 3),
            'l10_away_win_pct': round(l10_a, 3),
            'home_home_win_pct': round(home_win_pct, 3),
            'away_road_win_pct': round(road_win_pct, 3),
            'l10_home_gd': gd_h_l10,
            'l10_away_gd': gd_a_l10,
            'form_score': round(form_score, 3),
        }


# ═══════════════════════════════════════════════════════════════════
#  H2H
# ═══════════════════════════════════════════════════════════════════

class NhlH2H:
    """История личных встреч из прошлых матчей (game center / schedule)."""

    @staticmethod
    def from_schedule(schedule=None) -> dict:
        """Собрать H2H из завершённых матчей."""
        h2h = defaultdict(lambda: {'home_wins': 0, 'away_wins': 0, 'total': 0, 'matches': []})

        if schedule is None:
            try:
                with open(f'{DATA_DIR}/schedule.json', encoding='utf-8') as f:
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

            # Ключ: сортируем по алфавиту
            key = tuple(sorted([home, away]))
            h2h[key]['total'] += 1
            h2h[key]['matches'].append({
                'home': home, 'away': away,
                'score': f'{as_}:{hs}',
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
        """Получить H2H для пары команд."""
        key = tuple(sorted([team_a, team_b]))
        data = h2h_data.get(key, {'home_wins': 0, 'away_wins': 0, 'total': 0, 'matches': []})
        result = {
            'team_a': team_a,
            'team_b': team_b,
            'total': data['total'],
            'matches': data['matches'][-10:],  # последние 10 встреч
        }

        # Победы команды A (в H2H, team_a = sorted first)
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
#  Combined Probability
# ═══════════════════════════════════════════════════════════════════

def combine_prob(elo_pred: dict, form_factor: dict = None, h2h_result: dict = None,
                 odds: dict = None) -> dict:
    """Комбинированная вероятность: Elo + форма + H2H + коэффициенты.

    Args:
        elo_pred: результат NhlElo.predict()
        form_factor: результат NhlForm.form_factor()
        h2h_result: результат NhlH2H.get_h2h()
        odds: {'home_dec': float, 'away_dec': float} из fetch_nhl_data

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
        prob_form_a = 1 - ff
    else:
        prob_form_a = 0.5

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
    prob_odds_a = None
    if odds and odds.get('home_dec') and odds.get('away_dec'):
        try:
            ih = 1.0 / odds['home_dec']
            ia = 1.0 / odds['away_dec']
            margin = ih + ia
            prob_odds_h = ih / margin
            prob_odds_a = ia / margin
        except:
            pass

    # Веса (adaptive)
    w_elo = WEIGHT_ELO
    w_form = WEIGHT_FORM
    w_h2h = WEIGHT_H2H
    w_odds = WEIGHT_ODDS

    # Если у формы мало данных, сдвигаем вес на Elo
    if form_factor and form_factor.get('l10_home_win_pct', 0) == 0:
        w_form *= 0.5
        w_elo += w_form * 0.5

    # Если нет H2H, вес на Elo и форму
    if not h2h_result or h2h_result['total'] == 0:
        w_h2h = 0
        w_elo += WEIGHT_H2H * 0.6
        w_form += WEIGHT_H2H * 0.4

    # Если нет odds, вес на остальное
    if prob_odds_h is None:
        w_odds = 0
        w_elo += WEIGHT_ODDS * 0.5
        w_form += WEIGHT_ODDS * 0.5

    # Нормализация весов
    total_w = w_elo + w_form + w_h2h + w_odds
    w_elo /= total_w
    w_form /= total_w
    w_h2h /= total_w
    w_odds /= total_w

    # Комбинированная вероятность
    combined_h = (
        prob_elo_h * w_elo +
        prob_form_h * w_form +
        prob_h2h_h * w_h2h +
        (prob_odds_h or prob_elo_h) * w_odds
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
        'weights': {
            'elo': round(w_elo, 3),
            'form': round(w_form, 3),
            'h2h': round(w_h2h, 3),
            'odds': round(w_odds, 3),
        },
        'elo_diff': elo_pred.get('elo_diff', 0),
    }


# ═══════════════════════════════════════════════════════════════════
#  Facilities
# ═══════════════════════════════════════════════════════════════════

def load_data():
    """Загрузить все данные НХЛ. Вернуть словарь."""
    data = {}
    for name in ('schedule', 'standings', 'teams', 'player_stats'):
        path = f'{DATA_DIR}/{name}.json'
        if os.path.exists(path):
            try:
                with open(path, encoding='utf-8') as f:
                    data[name] = json.load(f)
            except:
                data[name] = []
        else:
            data[name] = []
    return data


# ═══════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import sys

    print('🏒 NHL Models')
    print()

    # Init Elo
    elo = NhlElo()
    if not elo._loaded:
        print('⏳ Инициализация Elo из таблицы...')
        elo.init_from_standings()

    # Train on finished matches
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
    nhl_form = NhlForm()
    form_data = nhl_form.from_standings()
    h2h_data = NhlH2H.from_schedule()

    for m in sched.get('upcoming', [])[:5]:
        home = m.get('home', '')
        away = m.get('away', '')
        if not home or not away:
            continue

        elo_pred = elo.predict(home, away, game_type=m.get('game_type', 2))
        ff = nhl_form.form_factor(form_data, home, away)
        h2h_r = h2h_data.get(tuple(sorted([home, away])))
        h2h_res = NhlH2H.get_h2h(h2h_data, home, away) if isinstance(h2h_data, dict) else None
        odds = m.get('odds', {})

        combined = combine_prob(elo_pred, ff, h2h_res, odds)

        h_ru = m.get('home_ru', home)
        a_ru = m.get('away_ru', away)
        print(f'  {a_ru} @ {h_ru}: '
              f'P1={combined["home_prob"]*100:.0f}% '
              f'P2={combined["away_prob"]*100:.0f}% '
              f'(Elo {elo_pred["home_prob"]*100:.0f}% | '
              f'Form {ff["form_score"]*100:.0f}%)')
