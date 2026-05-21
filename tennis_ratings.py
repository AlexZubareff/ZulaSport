#!/usr/bin/env python3
"""
Рейтинг ATP/WTA из CSV + Elo для тенниса.

Elo-based рейтинг для тенниса:
  - K-factor: 32 для ATP, 24 для WTA
  - Учёт поверхности (поверхностный Elo)
  - Ожидаемый результат на основе разницы рейтингов

Использование:
    from tennis_ratings import TennisElo
    elo = TennisElo()
    prob = elo.predict('Carlos Alcaraz', 'Novak Djokovic', surface='Clay')
    print(prob)  # {'player1': 0.55, 'player2': 0.45}
"""

import os, csv, json, math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import sys
sys.path.insert(0, '/opt')
from fetch_tennis_atp_data import load_matches, load_rankings

# ─── Константы ─────────────────────────────────────────────────────
ELO_CACHE_PATH = '/opt/data/tennis/elo_ratings.json'
DEFAULT_ELO = 1500
K_FACTOR = {'atp': 25, 'wta': 20}  # Чуть ниже стандартного (для теннисных матчей)
K_FACTOR_SURFACE = {'atp': 15, 'wta': 12}  # Для поверхностного Elo


class TennisElo:
    """
    Elo-рейтинг для тенниса.
    - Общий рейтинг + рейтинг по каждой поверхности.
    - Сохраняется в JSON для персистентности.
    - Расчёт вероятности победы.
    """

    def __init__(self, tour='atp'):
        self.tour = tour
        self.k = K_FACTOR[tour]
        self.k_surface = K_FACTOR_SURFACE[tour]
        # rating: {player_name: elo}
        self.ratings = {}
        # surface_ratings: {player_name: {surface: elo}}
        self.surface_ratings = defaultdict(lambda: defaultdict(lambda: DEFAULT_ELO))
        # match_count: {player_name: int}
        self.match_count = defaultdict(int)
        self._loaded = False
        self._load_cached()

    def _load_cached(self):
        """Загрузить кеш."""
        if os.path.exists(ELO_CACHE_PATH):
            try:
                with open(ELO_CACHE_PATH, encoding='utf-8') as f:
                    data = json.load(f)
                d = data.get(self.tour, {})
                self.ratings = d.get('ratings', {})
                for player, surfaces in d.get('surface_ratings', {}).items():
                    for s, elo in surfaces.items():
                        self.surface_ratings[player][s] = elo
                self.match_count = defaultdict(int, d.get('match_count', {}))
                self._loaded = True
            except:
                pass

    def _save_cached(self):
        """Сохранить кеш."""
        data = {}
        if os.path.exists(ELO_CACHE_PATH):
            try:
                with open(ELO_CACHE_PATH, encoding='utf-8') as f:
                    data = json.load(f)
            except:
                pass

        data[self.tour] = {
            'ratings': self.ratings,
            'surface_ratings': {p: dict(s) for p, s in self.surface_ratings.items()},
            'match_count': dict(self.match_count),
        }
        os.makedirs(os.path.dirname(ELO_CACHE_PATH), exist_ok=True)
        with open(ELO_CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_elo(self, player: str, surface: str = None) -> float:
        """Текущий Elo игрока (общий или на поверхности)."""
        player = player.strip()
        if surface:
            return self.surface_ratings[player].get(
                self._surface_group(surface),
                self.ratings.get(player, DEFAULT_ELO)
            )
        return self.ratings.get(player, DEFAULT_ELO)

    def _surface_group(self, surface):
        from tennis_models import _surface_group
        return _surface_group(surface)

    def expected_score(self, elo_a: float, elo_b: float) -> float:
        """Ожидаемый счёт (вероятность победы A над B)."""
        return 1.0 / (1.0 + math.pow(10, (elo_b - elo_a) / 400.0))

    def update(self, winner: str, loser: str, surface: str = None):
        """Обновить рейтинги после матча."""
        winner = winner.strip()
        loser = loser.strip()
        if not winner or not loser:
            return

        # Текущие рейтинги
        w_elo = self.ratings.get(winner, DEFAULT_ELO)
        l_elo = self.ratings.get(loser, DEFAULT_ELO)

        # Ожидаемый результат
        expected_w = self.expected_score(w_elo, l_elo)
        expected_l = 1.0 - expected_w

        # Actual: победитель = 1, проигравший = 0
        w_new = w_elo + self.k * (1.0 - expected_w)
        l_new = l_elo + self.k * (0.0 - expected_l)

        self.ratings[winner] = w_new
        self.ratings[loser] = max(l_new, 100)  # не ниже 100
        self.match_count[winner] += 1
        self.match_count[loser] += 1

        # Поверхностный Elo
        if surface:
            s = self._surface_group(surface)
            w_surface = self.surface_ratings[winner].get(s, DEFAULT_ELO)
            l_surface = self.surface_ratings[loser].get(s, DEFAULT_ELO)

            expected_ws = self.expected_score(w_surface, l_surface)
            expected_ls = 1.0 - expected_ws

            self.surface_ratings[winner][s] = w_surface + self.k_surface * (1.0 - expected_ws)
            self.surface_ratings[loser][s] = max(
                l_surface + self.k_surface * (0.0 - expected_ls), 100
            )

    def predict(self, player1: str, player2: str, surface: str = None) -> Dict:
        """Вероятность победы для каждого игрока."""
        elo1 = self.get_elo(player1, surface)
        elo2 = self.get_elo(player2, surface)
        prob1 = self.expected_score(elo1, elo2)
        return {
            'player1': player1,
            'player2': player2,
            'elo1': round(elo1, 1),
            'elo2': round(elo2, 1),
            'prob1': round(prob1, 4),
            'prob2': round(1 - prob1, 4),
            'surface': surface,
        }

    def train_on_history(self, year_from=2020):
        """Обучить Elo на исторических матчах."""
        matches = load_matches(self.tour, min_rank=0)
        # Фильтруем по году
        filtered = []
        for m in matches:
            try:
                d = int(m.get('tourney_date', '0'))
                year = d // 10000
                if year >= year_from:
                    filtered.append(m)
            except:
                continue

        # Сортируем по дате
        filtered.sort(key=lambda x: x.get('tourney_date', '0'))

        print(f'  Обучаю Elo на {len(filtered)} матчах...')
        count = 0
        for m in filtered:
            winner = m.get('winner_name', '').strip()
            loser = m.get('loser_name', '').strip()
            surface = m.get('surface', '')
            if winner and loser:
                self.update(winner, loser, surface)
                count += 1

        self._save_cached()
        print(f'  ✅ Обработано {count} матчей, {len(self.ratings)} игроков')
        return self.ratings

    def top_players(self, n=20, surface=None):
        """Топ N по Elo."""
        players = []
        for name, elo in self.ratings.items():
            if surface:
                elo = self.surface_ratings[name].get(self._surface_group(surface), elo)
            players.append({'name': name, 'elo': round(elo, 1), 'matches': self.match_count[name]})
        players.sort(key=lambda x: x['elo'], reverse=True)
        return players[:n]


# ═══════════════════════════════════════════════════════════════════
#  Комбинированный прогноз (Elo + форма + H2H)
# ═══════════════════════════════════════════════════════════════════

def combine_probabilities(elo_prob: float, h2h_weight: float = None,
                          form_weight: float = None) -> float:
    """Скомбинировать вероятности из разных источников.
    Все веса нормализуются. Возвращается вероятность для player1."""
    weights = []
    probs = []

    if elo_prob is not None:
        weights.append(0.5)
        probs.append(elo_prob)

    if h2h_weight is not None:
        weights.append(0.2)
        probs.append(h2h_weight)

    if form_weight is not None:
        weights.append(0.3)
        probs.append(form_weight)

    if not probs:
        return 0.5

    total_weight = sum(weights)
    return sum(p * w for p, w in zip(probs, weights)) / total_weight


if __name__ == '__main__':
    import sys

    print('=== Tennis Elo ===')
    elo = TennisElo('atp')

    # Обучаем
    if '--train' in sys.argv:
        elo.train_on_history(year_from=2020)
        print('\nТоп-10 (общий):')
        for p in elo.top_players(10):
            print(f'  {p["name"]}: {p["elo"]} ({p["matches"]} матчей)')

    # Тест предсказания
    print('\nПрогнозы:')
    for p1, p2, surf in [
        ('Carlos Alcaraz', 'Novak Djokovic', 'Clay'),
        ('Jannik Sinner', 'Carlos Alcaraz', 'Hard'),
        ('Daniil Medvedev', 'Novak Djokovic', 'Hard'),
    ]:
        pred = elo.predict(p1, p2, surface=surf)
        print(f'  {p1} vs {p2} ({surf}): {pred["prob1"]*100:.0f}% / {pred["prob2"]*100:.0f}% '
              f'(Elo: {pred["elo1"]:.0f} vs {pred["elo2"]:.0f})')
