#!/usr/bin/env python3
"""
Сбор ТВ-каналов для предстоящих матчей.
Запускается после upcoming.py, сохраняет результат в JSON.

Источники:
1. ESPN broadcast per-match — НХЛ, NBA
2. Статический маппинг — футбол, КХЛ, ВТБ, Euroleague, ЧМ по хоккею, теннис

Формат сохранения:
  /tmp/tv_channels_data.json — перезаписывается каждый день
"""

import sys, os, json, re, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, '/opt')
import tv_channels
import upcoming as _up
import matchtv_tvguide as _mtv

UTC = timezone.utc

# Обратный маппинг: русское название команды → английское
_RU_TO_EN = {v: k for k, v in _up.TEAMS_RU.items()}
_RU_TO_EN.update({v: k for k, v in _up.TEAMS_RU_EXTRA.items()})

_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}


# ─── ESPN per-match broadcast ───────────────────────────────────────
def fetch_espn_scoreboard(league_path):
    """Получить scoreboard ESPN с broadcast-каналами.
    Возвращает список матчей: {home, away, channels[]}
    """
    url = f'https://site.api.espn.com/apis/site/v2/sports/{league_path}/scoreboard'
    try:
        req = urllib.request.Request(url, headers=_headers)
        resp = urllib.request.urlopen(req, timeout=15)
        raw = resp.read()
        try:
            data = json.loads(raw)
        except:
            import gzip
            data = json.loads(gzip.decompress(raw))

        matches = []
        for event in data.get('events', []):
            comp = event.get('competitions', [{}])[0]
            competitors = comp.get('competitors', [])
            teams = [c.get('team', {}).get('displayName', '?') for c in competitors]
            channels = set()
            for bc in comp.get('broadcasts', []):
                for name in bc.get('names', []):
                    channels.add(name.strip())

            if len(teams) >= 2:
                matches.append({
                    'home': teams[0] if teams[0] != '?' else teams[1],
                    'away': teams[1] if len(teams) > 1 else teams[0],
                    'channels': list(channels),
                })
        return matches
    except Exception as e:
        return []


# ─── MATCH TV ────────────────────────────────────────────────────────
def _matchtv_channels(target_date):
    """Получить программу Матч ТВ на дату."""
    date_str = target_date.strftime('%Y-%m-%d')
    try:
        return _mtv.fetch_tvguide(date_str)
    except:
        return {}


def matchtv_for_match(match, mtv_channels):
    """Найти матч в программе Матч ТВ. Возвращает список каналов или []."""
    if not mtv_channels:
        return []
    found = _mtv.find_real_channel(match, mtv_channels)
    if found:
        return [{'country': 'Russia', 'channel': c} for c in found]
    return []


# ─── СТАТИЧЕСКИЙ МАППИНГ ───────────────────────────────────────────
def static_channels(league_name, match_data=None):
    """Каналы из tv_channels."""
    ch = tv_channels.get_broadcast(league_name, match_data)
    if ch:
        return [{'country': 'Static', 'channel': c} for c in ch]
    return []


# ─── ГЛАВНАЯ ─────────────────────────────────────────────────────────
def collect():
    target_date = datetime.now(UTC) + timedelta(hours=3) + timedelta(days=1)  # MSK
    date_str = target_date.strftime('%Y%m%d')
    weekday_ru = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС'][target_date.weekday()]
    date_fmt = target_date.strftime('%d.%m.%Y')
    print(f'📅 Собираю каналы на {date_fmt} ({weekday_ru})')

    result = {
        'date': date_str,
        'updated_at': datetime.now(UTC).isoformat(),
        'matches': [],
    }

    # ── Получаем программу Матч ТВ (используется для всех лиг) ─────
    mtv = _matchtv_channels(target_date)
    print(f'\n📺 Матч ТВ: {len(mtv)} каналов')

    # Лиги, которые показывает Матч ТВ (пробуем их первыми)
    MTV_LEAGUES = {'РПЛ', 'Ла Лига', 'Серия А', 'КХЛ', 'ЧМ по хоккею'}

    # ── Футбол (Match TV + статика) ─────────────────────────────────
    print('\n⚽ Футбол:')
    for lid, (name, emoji) in _up.SSTATS_LEAGUES.items():
        matches = _up.fetch_sstats_upcoming(lid, target_date)
        for m in matches:
            home = m.get('home', m.get('team1', '?'))
            away = m.get('away', m.get('team2', '?'))
            print(f'  {emoji} {home} — {away}...', end=' ')

            # Сначала Match TV (для РПЛ, Ла Лиги, Серии А)
            if name in MTV_LEAGUES:
                ch = matchtv_for_match({'team1': home, 'team2': away}, mtv)
                if ch:
                    print(f'✅ Match TV: {len(ch)}')
                    result['matches'].append({
                        'sport': 'football', 'league': name, 'source': 'matchtv',
                        'home': home, 'away': away, 'time': m.get('time', ''),
                        'channels': ch, 'game_id': m.get('game_id', 0),
                    })
                    continue

            # Fallback на статику
            ch = static_channels(name)
            print(f'✅ статика: {len(ch)}' if ch else '❌')
            result['matches'].append({
                'sport': 'football', 'league': name, 'source': 'static',
                'home': home, 'away': away, 'time': m.get('time', ''),
                'channels': ch, 'game_id': m.get('game_id', 0),
            })

    # ── НХЛ (ESPN per-match + статика) ─────────────────────────────
    print('\n🏒 НХЛ:')
    nhl_matches = _up.nhl_api.fetch_nhl_upcoming(date_str)
    espn_nhl = fetch_espn_scoreboard('hockey/nhl')
    for m in nhl_matches:
        home = m.get('home', '?')
        away = m.get('away', '?')
        print(f'  {home} — {away}...', end=' ')

        # Переводим русские названия → английские для поиска в ESPN
        h_en = _RU_TO_EN.get(home, home)
        a_en = _RU_TO_EN.get(away, away)

        # Матчим с ESPN по английским названиям
        found = False
        for espn_m in espn_nhl:
            he = h_en.lower()
            ae = a_en.lower()
            if (he in espn_m['home'].lower() or he in espn_m['away'].lower()) and \
               (ae in espn_m['home'].lower() or ae in espn_m['away'].lower()):
                ch = [{'country': 'USA', 'channel': c} for c in espn_m['channels']]
                print(f'✅ ESPN: {len(ch)}')
                result['matches'].append({
                    'sport': 'hockey', 'league': 'НХЛ', 'source': 'espn',
                    'home': home, 'away': away, 'time': m.get('time', ''),
                    'channels': ch,
                })
                found = True
                break
        if not found:
            ch = static_channels('НХЛ')
            print(f'✅ статика: {len(ch)}')
            result['matches'].append({
                'sport': 'hockey', 'league': 'НХЛ', 'source': 'static',
                'home': home, 'away': away, 'time': m.get('time', ''),
                'channels': ch,
            })

    # ── КХЛ (Match TV + статика) ────────────────────────────────────
    print('\n🏒 КХЛ:')
    khl = _up.fetch_khl_upcoming(target_date)
    for m in khl:
        home = m.get('home', m.get('team1', '?'))
        away = m.get('away', m.get('team2', '?'))
        ch = matchtv_for_match({'team1': home, 'team2': away}, mtv)
        if ch:
            print(f'  {home} — {away}: ✅ Match TV: {len(ch)}')
            result['matches'].append({
                'sport': 'hockey', 'league': 'КХЛ', 'source': 'matchtv',
                'home': home, 'away': away, 'time': m.get('time', ''),
                'channels': ch,
            })
        else:
            ch = static_channels('КХЛ')
            print(f'  {home} — {away}: ⚠️ статика: {len(ch)}')
            result['matches'].append({
                'sport': 'hockey', 'league': 'КХЛ', 'source': 'static',
                'home': home, 'away': away, 'time': m.get('time', ''),
                'channels': ch,
            })

    # ── ЧМ по хоккею (Match TV + статика) ──────────────────────────
    print('\n🏒 ЧМ по хоккею:')
    wc_from = target_date.replace(hour=0, minute=0, second=0)
    wc_to = target_date.replace(hour=23, minute=59, second=59)
    try:
        whc, _ = _up.flashscore_other.fetch_upcoming('world-cup-hockey', wc_from, wc_to)
    except:
        whc = []
    for m in whc:
        home = m.get('home', m.get('team1', '?'))
        away = m.get('away', m.get('team2', '?'))
        ch = matchtv_for_match({'team1': home, 'team2': away}, mtv)
        if ch:
            print(f'  {home} — {away}: ✅ Match TV: {len(ch)}')
            result['matches'].append({
                'sport': 'hockey', 'league': 'ЧМ по хоккею', 'source': 'matchtv',
                'home': home, 'away': away, 'time': m.get('time', ''),
                'channels': ch,
            })
        else:
            ch = static_channels('ЧМ по хоккею')
            print(f'  {home} — {away}: ⚠️ статика: {len(ch)}')
            result['matches'].append({
                'sport': 'hockey', 'league': 'ЧМ по хоккею', 'source': 'static',
                'home': home, 'away': away, 'time': m.get('time', ''),
                'channels': ch,
            })

    # ── NBA (ESPN per-match + статика) ─────────────────────────────
    print('\n🏀 NBA:')
    nba_matches = _up.balldontlie_api.fetch_nba_upcoming(date_str)
    espn_nba = fetch_espn_scoreboard('basketball/nba')
    for m in nba_matches:
        home = m.get('home', '?')
        away = m.get('away', '?')
        print(f'  {home} — {away}...', end=' ')

        # Переводим русские названия → английские для поиска в ESPN
        h_en = _RU_TO_EN.get(home, home)
        a_en = _RU_TO_EN.get(away, away)

        found = False
        for espn_m in espn_nba:
            he = h_en.lower()
            ae = a_en.lower()
            if (he in espn_m['home'].lower() or he in espn_m['away'].lower()) and \
               (ae in espn_m['home'].lower() or ae in espn_m['away'].lower()):
                ch = [{'country': 'USA', 'channel': c} for c in espn_m['channels']]
                print(f'✅ ESPN: {len(ch)}')
                result['matches'].append({
                    'sport': 'basketball', 'league': 'NBA', 'source': 'espn',
                    'home': home, 'away': away, 'time': m.get('time', ''),
                    'channels': ch,
                })
                found = True
                break
        if not found:
            ch = static_channels('NBA')
            print(f'✅ статика: {len(ch)}')
            result['matches'].append({
                'sport': 'basketball', 'league': 'NBA', 'source': 'static',
                'home': home, 'away': away, 'time': m.get('time', ''),
                'channels': ch,
            })

    # ── Лига ВТБ (статика) ──────────────────────────────────────────
    print('\n🏀 Лига ВТБ:')
    try:
        vtb, _ = _up.flashscore_other.fetch_upcoming('vtb', wc_from, wc_to)
    except:
        vtb = []
    for m in vtb:
        home = m.get('home', m.get('team1', '?'))
        away = m.get('away', m.get('team2', '?'))
        ch = static_channels('Лига ВТБ')
        print(f'  {home} — {away}: ✅ {len(ch)}')
        result['matches'].append({
            'sport': 'basketball', 'league': 'Лига ВТБ', 'source': 'static',
            'home': home, 'away': away, 'time': m.get('time', ''),
            'channels': ch,
        })

    # ── Euroleague (статика) ─────────────────────────────────────────
    print('\n🏀 Euroleague:')
    try:
        euro, _ = _up.flashscore_other.fetch_upcoming('euroleague', wc_from, wc_to)
    except:
        euro = []
    for m in euro:
        home = m.get('home', m.get('team1', '?'))
        away = m.get('away', m.get('team2', '?'))
        ch = static_channels('Euroleague')
        print(f'  {home} — {away}: ✅ {len(ch)}')
        result['matches'].append({
            'sport': 'basketball', 'league': 'Euroleague', 'source': 'static',
            'home': home, 'away': away, 'time': m.get('time', ''),
            'channels': ch,
        })

    # ── Теннис (статика) ────────────────────────────────────────────
    print('\n🎾 Теннис:')
    tennis = _up.fetch_tennis_upcoming(date_str)
    for t in tennis:
        tname = t.get('tournament', '?')
        p1 = t.get('player1', '?')
        p2 = t.get('player2', '?')
        ch = tv_channels.tennis_broadcast(tname)
        print(f'  {p1} — {p2} ({tname}): ✅ {len(ch)}' if ch else f'  {p1} — {p2}: ❌')
        result['matches'].append({
            'sport': 'tennis', 'league': tname, 'source': 'static',
            'home': p1, 'away': p2, 'time': t.get('time', ''),
            'channels': [{'country': 'Russia', 'channel': c} for c in ch],
        })

    # ── Сохранение (накопительно по датам) ───────────────────────────
    import storage as _st
    _st.add_date('/tmp/tv_channels_data.json', date_str, result.get('matches', []))

    # ── Сохраняем футбольные матчи для прогнозов ───────────────────
    # Строим обратный маппинг: название лиги → id лиги
    _lid_by_name = {name: lid for lid, (name, _) in _up.SSTATS_LEAGUES.items()}
    pred_matches = []
    for m in result['matches']:
        if m['sport'] == 'football' and m.get('game_id'):
            pred_matches.append({
                'home': m['home'],
                'away': m['away'],
                'time': m['time'],
                'game_id': m['game_id'],
                'league': m['league'],
                'league_id': _lid_by_name.get(m['league'], 0),
            })
    try:
        _st.add_date('/tmp/upcoming_matches.json', date_str, pred_matches)
        print(f'📁 /tmp/upcoming_matches.json ({len(pred_matches)} матчей для прогнозов)')
    except Exception as e:
        print(f'⚠️ Не удалось сохранить upcoming_matches.json: {e}')

    total = len(result['matches'])
    with_tv = sum(1 for m in result['matches'] if m['channels'])
    print(f'\n{"=" * 50}')
    print(f'📊 Сохранено: {total} матчей, {with_tv} с каналами')
    print(f'📁 /tmp/tv_channels_data.json')

    return result


if __name__ == '__main__':
    collect()
