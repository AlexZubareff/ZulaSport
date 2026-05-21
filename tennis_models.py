#!/usr/bin/env python3
"""
Модуль статистики тенниса: форма, H2H, поверхность, матчи игрока.

Основан на данных JeffSackmann (CSV) — /opt/data/tennis/atp/, /opt/data/tennis/wta/

Использование:
    from tennis_models import TennisStats
    ts = TennisStats('atp')
    form = ts.player_form('Carlos Alcaraz', surface='Hard', n=10)
    h2h = ts.h2h('Carlos Alcaraz', 'Novak Djokovic')
    stats = ts.player_stats('Carlos Alcaraz')
"""

import os, csv
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

# Импорт загрузчика
import sys
sys.path.insert(0, '/opt')
from fetch_tennis_atp_data import load_matches, load_players, load_rankings

# ─── Поверхности ───────────────────────────────────────────────────
SURFACES = {
    'Hard': ['Hard', 'Acrylic', 'Cement', 'Plexipave', 'DecoTurf'],
    'Clay': ['Clay', 'Red Clay', 'Green Clay', 'Brick'],
    'Grass': ['Grass'],
    'Carpet': ['Carpet', 'Indoor Carpet'],
}

def _surface_group(surface: str) -> str:
    """Привести поверхность к группе: Hard, Clay, Grass, Carpet, Unknown."""
    if not surface:
        return 'Unknown'
    s = surface.strip()
    for group, members in SURFACES.items():
        if any(m.lower() in s.lower() for m in members):
            return group
    return 'Unknown'


class TennisStats:
    """Статистика теннисных матчей: форма, H2H, поверхность."""

    def __init__(self, tour='atp', year_from=2020):
        self.tour = tour  # 'atp' or 'wta'
        self.year_from = year_from
        self._matches = None
        self._players = None
        self._rankings = None
        self._last_match_by_player = {}

    @property
    def matches(self):
        if self._matches is None:
            self._load_all()
        return self._matches

    @property
    def players(self):
        if self._players is None:
            self._load_all()
        return self._players

    @property
    def rankings(self):
        if self._rankings is None:
            self._load_all()
        return self._rankings

    def _load_all(self):
        """Загрузить все матчи + игроков."""
        self._matches = load_matches(self.tour, min_rank=0)
        self._players = load_players(self.tour)
        self._rankings = load_rankings(self.tour)
        self._build_player_id_map()
        print(f'  {self.tour.upper()}: {len(self._matches)} матчей, {len(self._players)} игроков')

    def _build_player_id_map(self):
        """Построить {имя_игрока: player_id} из players.csv."""
        self._player_name_to_id = {}
        if not self._players:
            return
        for p in self._players:
            pid = p.get('player_id', '')
            first = (p.get('name_first', '') or '').strip()
            last = (p.get('name_last', '') or '').strip()
            if first or last:
                full = f'{first} {last}'.strip()
                if full and pid:
                    self._player_name_to_id[full.lower()] = pid

    def _match_key(self, m):
        """Уникальный ключ матча для дедупликации."""
        return (m.get('tourney_id', ''), m.get('match_num', ''), m.get('winner_name', ''), m.get('loser_name', ''))

    def _match_date(self, m):
        """Дата матча как datetime."""
        try:
            return datetime.strptime(str(m.get('tourney_date', '')), '%Y%m%d')
        except:
            return None

    def player_matches(self, player_name: str) -> List[Dict]:
        """Все матчи игрока (как победитель и как проигравший)."""
        if not player_name:
            return []
        results = []
        for m in self.matches:
            if m.get('winner_name', '').strip() == player_name.strip():
                results.append({
                    **m,
                    '_player_role': 'winner',
                    '_opponent': m.get('loser_name', ''),
                    '_result': 'W',
                })
            elif m.get('loser_name', '').strip() == player_name.strip():
                results.append({
                    **m,
                    '_player_role': 'loser',
                    '_opponent': m.get('winner_name', ''),
                    '_result': 'L',
                })

        # Сортируем по дате
        results.sort(key=lambda x: self._match_date(x) or datetime.min, reverse=True)
        return results

    def player_form(self, player_name: str, surface: str = None, n: int = 10) -> List[Dict]:
        """Форма на последних N матчей (по поверхности, если указана)."""
        all_matches = self.player_matches(player_name)
        if not all_matches:
            return []

        surface_group = _surface_group(surface) if surface else None
        result = []
        for m in all_matches:
            m_surface = _surface_group(m.get('surface', ''))
            if surface_group and m_surface != surface_group:
                continue
            result.append(m)
            if len(result) >= n:
                break

        return result

    def form_summary(self, player_name: str, surface: str = None, n: int = 10) -> Dict:
        """Сводка формы: W/L, последние исходы подряд."""
        matches = self.player_form(player_name, surface, n)
        wins = sum(1 for m in matches if m['_result'] == 'W')
        losses = sum(1 for m in matches if m['_result'] == 'L')
        # Последние результаты
        results = [m['_result'] for m in matches]

        # Проценты по поверхностям
        by_surface = defaultdict(lambda: {'w': 0, 'l': 0})
        for m in matches:
            s = _surface_group(m.get('surface', 'Unknown'))
            if m['_result'] == 'W':
                by_surface[s]['w'] += 1
            else:
                by_surface[s]['l'] += 1

        return {
            'player': player_name,
            'total': len(matches),
            'wins': wins,
            'losses': losses,
            'win_pct': round(wins / max(wins + losses, 1), 3),
            'form': ''.join(results),
            'by_surface': dict(by_surface),
        }

    def h2h(self, player1: str, player2: str) -> List[Dict]:
        """Очные встречи между двумя игроками."""
        if not player1 or not player2:
            return []

        results = []
        p1, p2 = player1.strip(), player2.strip()
        for m in self.matches:
            w = m.get('winner_name', '').strip()
            l = m.get('loser_name', '').strip()
            cond1 = (w == p1 and l == p2)
            cond2 = (w == p2 and l == p1)
            if cond1 or cond2:
                results.append({
                    'date': m.get('tourney_date', ''),
                    'tourney': m.get('tourney_name', ''),
                    'surface': m.get('surface', ''),
                    'round': m.get('round', ''),
                    'winner': w,
                    'loser': l,
                    'score': m.get('score', ''),
                    'winner_rank': m.get('winner_rank'),
                    'loser_rank': m.get('loser_rank'),
                })

        # Сортируем по дате (новые сверху)
        results.sort(key=lambda x: x.get('date', ''), reverse=True)
        return results

    def h2h_summary(self, player1: str, player2: str) -> Dict:
        """Сводка H2H."""
        matches = self.h2h(player1, player2)
        p1, p2 = player1.strip(), player2.strip()
        p1_wins = sum(1 for m in matches if m['winner'] == p1)
        p2_wins = sum(1 for m in matches if m['winner'] == p2)

        # По поверхностям
        by_surface = defaultdict(lambda: {p1: 0, p2: 0})
        for m in matches:
            s = _surface_group(m.get('surface', 'Unknown'))
            if m['winner'] == p1:
                by_surface[s][p1] += 1
            else:
                by_surface[s][p2] += 1

        last_winner = matches[0]['winner'] if matches else None

        return {
            'player1': p1,
            'player2': p2,
            f'{p1}_wins': p1_wins,
            f'{p2}_wins': p2_wins,
            'total': len(matches),
            'by_surface': dict(by_surface),
            'last_winner': last_winner,
            'matches': matches,
        }

    def player_stats(self, player_name: str, n: int = 20) -> Dict:
        """Средняя статистика: эйсы, двойные ошибки, процент первой подачи."""
        matches = self.player_form(player_name, n=n)
        if not matches:
            return {}

        stats = {
            'ace': [], 'df': [], 'first_in': [], 'first_won': [],
            'second_in': [], 'second_won': [], 'serve_pct': [],
        }

        for m in matches:
            if m['_player_role'] == 'winner':
                prefix = 'w_'
                opp_prefix = 'l_'
            else:
                prefix = 'l_'
                opp_prefix = 'w_'

            ace = m.get(f'{prefix}ace')
            df = m.get(f'{prefix}df')
            first_in = m.get(f'{prefix}1stIn')
            first_won = m.get(f'{prefix}1stWon')
            svpt = m.get(f'{prefix}svpt')  # total serve points
            second_won = m.get(f'{prefix}2ndWon')

            if ace is not None:
                stats['ace'].append(float(ace))
            if df is not None:
                stats['df'].append(float(df))
            if first_in is not None and svpt and float(svpt) > 0:
                stats['first_in'].append(float(first_in) / float(svpt))
            if first_won is not None and first_in and float(first_in) > 0:
                stats['first_won'].append(float(first_won) / float(first_in))
            if second_won is not None and svpt and first_in and (float(svpt) - float(first_in)) > 0:
                stats['second_won'].append(float(second_won) / (float(svpt) - float(first_in)))

        def avg(vals):
            return round(sum(vals) / max(len(vals), 1), 2) if vals else 0

        return {
            'player': player_name,
            'matches': len(matches),
            'avg_ace': avg(stats['ace']),
            'avg_df': avg(stats['df']),
            'first_serve_pct': avg(stats['first_in']),
            'first_serve_won_pct': avg(stats['first_won']),
            'second_serve_won_pct': avg(stats['second_won']),
        }

    def player_ranking(self, player_name: str) -> Optional[int]:
        """Текущий рейтинг игрока."""
        if not self.rankings or not player_name:
            return None
        
        # Ищем player_id по имени
        pid = self._player_name_to_id.get(player_name.strip().lower())
        if not pid:
            return None
        
        for r in self.rankings:
            if r.get('player', '') == pid:
                try:
                    return int(r.get('rank', 0))
                except:
                    return None
        return None

    def surface_preference(self, player_name: str, n: int = 30) -> Dict:
        """Предпочтения по поверхности игрока."""
        matches = self.player_form(player_name, n=n)
        by_surface = defaultdict(lambda: {'w': 0, 'l': 0})
        for m in matches:
            s = _surface_group(m.get('surface', 'Unknown'))
            if m['_result'] == 'W':
                by_surface[s]['w'] += 1
            else:
                by_surface[s]['l'] += 1

        result = {}
        for s, data in by_surface.items():
            total = data['w'] + data['l']
            result[s] = {
                'wins': data['w'],
                'losses': data['l'],
                'win_pct': round(data['w'] / max(total, 1), 3),
            }
        return result

    def recent_h2h_on_surface(self, player1: str, player2: str, surface: str) -> Dict:
        """H2H на конкретной поверхности."""
        all_h2h = self.h2h(player1, player2)
        surface_group = _surface_group(surface)

        h2h_surface = [m for m in all_h2h if _surface_group(m.get('surface', '')) == surface_group]
        p1, p2 = player1.strip(), player2.strip()

        if not h2h_surface:
            return {'total': 0, 'p1_wins': 0, 'p2_wins': 0}

        p1_wins = sum(1 for m in h2h_surface if m['winner'] == p1)
        p2_wins = sum(1 for m in h2h_surface if m['winner'] == p2)

        return {
            'surface': surface_group,
            'total': len(h2h_surface),
            f'{p1}_wins': p1_wins,
            f'{p2}_wins': p2_wins,
            'last_winner': h2h_surface[0]['winner'] if h2h_surface else None,
        }


# ─── Список активных игроков из рейтинга ──────────────────────────

def get_active_players(tour='atp', top_n=100):
    """Вернуть топ-N активных игроков с их рейтингом и именем."""
    ts = TennisStats(tour)
    rankings = ts.rankings
    if not rankings:
        return []

    # Build player_id → name lookup
    pid_to_name = {}
    if ts._players:
        for p in ts._players:
            pid = p.get('player_id', '')
            first = (p.get('name_first', '') or '').strip()
            last = (p.get('name_last', '') or '').strip()
            name = f'{first} {last}'.strip()
            if pid and name:
                pid_to_name[pid] = name

    players = []
    for r in rankings:
        try:
            rank = int(r.get('rank', 0))
        except:
            continue
        if rank < 1 or rank > top_n:
            continue
        pid = r.get('player', '')
        name = pid_to_name.get(pid, f'Unknown ({pid})')
        players.append({
            'rank': rank,
            'name': name,
            'points': int(r.get('points', 0)) if r.get('points') else 0,
        })
    return sorted(players, key=lambda x: x['rank'])


def player_name_variants(name: str) -> List[str]:
    """Генерировать варианты имени для поиска."""
    name = name.strip()
    variants = [name]
    # "Carlos Alcaraz" → ["Carlos Alcaraz", "Alcaraz"]
    parts = name.split()
    if len(parts) > 1:
        variants.append(parts[-1])
        variants.append(' '.join(parts[1:]))  # отбрасываем имя
    # "de Minaur" → ["Alex de Minaur", "de Minaur"]
    if len(parts) > 2:
        variants.append(' '.join(parts[1:]))
    return variants


if __name__ == '__main__':
    print('=== Тест TennisStats ===')
    ts = TennisStats('atp')

    # Тест формы
    form = ts.form_summary('Carlos Alcaraz', surface='Clay', n=15)
    print(f'\nAlcaraz на грунте: {form["wins"]}W/{form["losses"]}L '
          f'({form["win_pct"]*100:.0f}%) форма {form["form"]}')

    # Тест H2H
    h2h = ts.h2h_summary('Carlos Alcaraz', 'Novak Djokovic')
    print(f'\nAlcaraz vs Djokovic: {h2h["Carlos Alcaraz_wins"]}-{h2h["Novak Djokovic_wins"]}')

    # Тест статистики
    stats = ts.player_stats('Carlos Alcaraz', n=15)
    if stats:
        print(f'\nAlcaraz: эйсы {stats["avg_ace"]}/м, ДО {stats["avg_df"]}/м, '
              f'1-я {stats["first_serve_pct"]*100:.0f}%')

    # Тест рейтинга
    rank = ts.player_ranking('Carlos Alcaraz')
    print(f'Рейтинг: {rank}')

    # Тест предпочтений
    pref = ts.surface_preference('Carlos Alcaraz', n=40)
    for s, d in pref.items():
        print(f'  {s}: {d["wins"]}W/{d["losses"]}L ({d["win_pct"]*100:.0f}%)')
