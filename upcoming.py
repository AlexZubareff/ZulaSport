#!/usr/bin/env python3
"""
Ежедневный дайджест предстоящих матчей на завтра.
Запуск: ежедневно в 23:00 МСК через sport_bot.py
Собирает: футбол (SStats) + хоккей (ESPN + КХЛ) + баскетбол (ESPN NBA)
Отправляет в канал @zula_sport_news
"""

import json, requests, subprocess, os, sys, glob
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '/root/.openclaw/workspace/odds')
import importlib
flashscore_other = importlib.import_module('flashscore_other')

sys.path.insert(0, '/opt')
import tennis_names
import nhl_api
import balldontlie_api

# ─── КОНФИГУРАЦИЯ ───────────────────────────────────────────────────
SSTATS_KEY = open('/etc/sstats.key').read().strip()
BOT_TOKEN = "8431200157:AAF-vgf6D3AGokWMmOUgzUfffKlCwDz3uwQ"
CHANNEL_ID = "-1003928523816"

MOW = timedelta(hours=3)
UTC = timezone.utc

SSTATS_LEAGUES = {
    39:  ('АПЛ', '🏴󠁧󠁢󠁥󠁮󠁧󠁿'),
    140: ('Ла Лига', '🇪🇸'),
    135: ('Серия А', '🇮🇹'),
    78:  ('Бундеслига', '🇩🇪'),
    61:  ('Лига 1', '🇫🇷'),
    235: ('РПЛ', '🇷🇺'),
    2:   ('Лига Чемпионов', '⭐'),
    3:   ('Лига Европы', '🌙'),
    848: ('Лига Конференций', '💫'),
    1:   ('Чемпионат Мира', '🌍'),
    4:   ('Чемпионат Европы', '🏆'),
}

# ─── ПЕРЕВОД КОМАНД НА РУССКИЙ ──────────────────────────────────────
TEAMS_RU = {
    'Arsenal': 'Арсенал', 'Aston Villa': 'Астон Вилла', 'Bournemouth': 'Борнмут',
    'Brentford': 'Брентфорд', 'Brighton': 'Брайтон', 'Burnley': 'Бёрнли',
    'Chelsea': 'Челси', 'Crystal Palace': 'Кристал Пэлас', 'Everton': 'Эвертон',
    'Fulham': 'Фулхэм', 'Ipswich': 'Ипсвич', 'Leeds': 'Лидс',
    'Leicester': 'Лестер', 'Liverpool': 'Ливерпуль', 'Manchester City': 'Манчестер Сити',
    'Manchester United': 'Манчестер Юнайтед', 'Newcastle': 'Ньюкасл', 'Newcastle United': 'Ньюкасл',
    'Nottingham Forest': 'Ноттингем Форест', 'Southampton': 'Саутгемптон',
    'Sunderland': 'Сандерленд', 'Tottenham': 'Тоттенхэм', 'West Ham': 'Вест Хэм',
    'Wolves': 'Вулверхэмптон',
    'Alaves': 'Алавес', 'Athletic Bilbao': 'Атлетик', 'Athletic Club': 'Атлетик',
    'Atletico Madrid': 'Атлетико', 'Barcelona': 'Барселона', 'Celta Vigo': 'Сельта',
    'Elche': 'Эльче', 'Espanyol': 'Эспаньол', 'Getafe': 'Хетафе',
    'Girona': 'Жирона', 'Las Palmas': 'Лас-Пальмас', 'Leganes': 'Леганес',
    'Levante': 'Леванте', 'Mallorca': 'Мальорка', 'Osasuna': 'Осасуна',
    'Oviedo': 'Овьедо', 'Rayo Vallecano': 'Райо Вальекано', 'Real Betis': 'Бетис',
    'Real Madrid': 'Реал Мадрид', 'Real Sociedad': 'Реал Сосьедад',
    'Sevilla': 'Севилья', 'Valencia': 'Валенсия', 'Villarreal': 'Вильярреал',
    'Real Oviedo': 'Реал Овьедо',
    'AC Milan': 'Милан', 'Atalanta': 'Аталанта', 'Bologna': 'Болонья',
    'Cagliari': 'Кальяри', 'Como': 'Комо', 'Cremonese': 'Кремонезе',
    'Fiorentina': 'Фиорентина', 'Genoa': 'Дженоа', 'Hellas Verona': 'Верона',
    'Inter': 'Интер', 'Juventus': 'Ювентус', 'Lazio': 'Лацио', 'Lecce': 'Лечче',
    'Napoli': 'Наполи', 'Parma': 'Парма', 'Pisa': 'Пиза', 'Roma': 'Рома', 'AS Roma': 'Рома',
    'Sassuolo': 'Сассуоло', 'Torino': 'Торино', 'Udinese': 'Удинезе',
    'AC Milan': 'Милан', 'Como': 'Комо', 'Verona': 'Верона',
    '1. FC Köln': 'Кёльн', '1. FC Heidenheim': 'Хайденхайм',
    'Bayer Leverkusen': 'Байер', 'Bayern München': 'Бавария',
    'Borussia Dortmund': 'Боруссия Д', 'Borussia Mönchengladbach': 'Боруссия М',
    'Eintracht Frankfurt': 'Айнтрахт', 'FC Augsburg': 'Аугсбург',
    'FC Bayern München': 'Бавария', 'FC St. Pauli': 'Санкт-Паули',
    'Freiburg': 'Фрайбург', 'SC Freiburg': 'Фрайбург',
    'FSV Mainz 05': 'Майнц', 'Hamburger SV': 'Гамбург',
    'Hertha BSC': 'Герта', 'Hoffenheim': 'Хоффенхайм',
    'RB Leipzig': 'РБ Лейпциг', 'TSG 1899 Hoffenheim': 'Хоффенхайм',
    'Union Berlin': 'Унион Берлин', 'VfB Stuttgart': 'Штутгарт',
    'VfL Wolfsburg': 'Вольфсбург', 'Werder Bremen': 'Вердер',
    'Angers': 'Анже', 'Auxerre': 'Осер', 'Le Havre': 'Гавр',
    'Lens': 'Ланс', 'Lille': 'Лилль', 'Lorient': 'Лорьян', 'Lyon': 'Лион',
    'Marseille': 'Марсель', 'Metz': 'Мец', 'Monaco': 'Монако',
    'Nice': 'Ницца', 'Paris Saint Germain': 'ПСЖ', 'Paris FC': 'Париж',
    'Rennes': 'Ренн', 'Stade Brestois 29': 'Брест', 'Strasbourg': 'Страсбур',
    'Toulouse': 'Тулуза', 'Montpellier': 'Монпелье', 'Nantes': 'Нант',
    'FC Orenburg': 'Оренбург', 'Orenburg': 'Оренбург', 'Krylia Sovetov': 'Крылья Советов',
    'Zenit': 'Зенит', 'FC Sochi': 'Сочи', 'Akhmat': 'Ахмат',
    'Dinamo Makhachkala': 'Динамо Мх', 'Lokomotiv': 'Локомотив',
    'Baltika': 'Балтика', 'Dynamo': 'Динамо', 'Dynamo Moscow': 'Динамо Москва',
    'Spartak Moscow': 'Спартак', 'CSKA Moscow': 'ЦСКА', 'Rubin': 'Рубин',
    'FC Rostov': 'Ростов', 'Akron': 'Акрон', 'Nizhny Novgorod': 'Пари НН',
    'FC Krasnodar': 'Краснодар', 'Krasnodar': 'Краснодар',
    'Montreal Canadiens': 'Монреаль', 'Buffalo Sabres': 'Баффало',
    'Anaheim Ducks': 'Анахайм', 'Vegas Golden Knights': 'Вегас',
    'Philadelphia 76ers': 'Филадельфия Сиксерс', 'New York Knicks': 'Нью-Йорк Никс',
    'Minnesota Timberwolves': 'Миннесота', 'San Antonio Spurs': 'Сан-Антонио',
}

TEAMS_RU_EXTRA = {
    'Manchester City': 'Манчестер Сити', 'Manchester Utd': 'МЮ',
    'Newcastle': 'Ньюкасл', 'Tottenham': 'Тоттенхэм',
    'Bayern': 'Бавария', 'Dortmund': 'Боруссия Д',
    'Leverkusen': 'Байер', 'Leipzig': 'РБ Лейпциг',
    'Frankfurt': 'Айнтрахт', 'Bremen': 'Вердер',
    'Mainz': 'Майнц', 'Freiburg': 'Фрайбург',
    'Köln': 'Кёльн', 'Hamburg': 'Гамбург', 'Heidenheim': 'Хайденхайм',
    'Union Berlin': 'Унион Берлин', 'St. Pauli': 'Санкт-Паули',
    'Stuttgart': 'Штутгарт', 'Wolfsburg': 'Вольфсбург',
    'Augsburg': 'Аугсбург', 'Gladbach': 'Боруссия М',
    'Marseille': 'Марсель', 'Lyon': 'Лион', 'Monaco': 'Монако',
    'Lille': 'Лилль', 'Nice': 'Ницца', 'Rennes': 'Ренн',
    'Lens': 'Ланс', 'Strasbourg': 'Страсбур', 'Toulouse': 'Тулуза',
    'Brest': 'Брест', 'Auxerre': 'Осер', 'Le Havre': 'Гавр',
    'Saint-Étienne': 'Сент-Этьен',
    'Paris Saint Germain': 'ПСЖ',
}

def ru(name):
    if name in TEAMS_RU:
        return TEAMS_RU[name]
    name_lower = name.lower()
    for eng, rus in TEAMS_RU_EXTRA.items():
        if eng.lower() == name_lower:
            return rus
    for eng, rus in {**TEAMS_RU, **TEAMS_RU_EXTRA}.items():
        if eng.lower() in name_lower or name_lower in eng.lower():
            return rus
    return name


# ─── SStats ─────────────────────────────────────────────────────────
def fetch_sstats_upcoming(lid, target_date):
    """Предстоящие матчи лиги на указанную дату через SStats API."""
    url = f'https://api.sstats.net/Games/list?apikey={SSTATS_KEY}&LeagueId={lid}&Year=2025&take=500'
    try:
        resp = requests.get(url, timeout=15)
        data = resp.json()
    except:
        return []

    games = data if isinstance(data, list) else data.get('data', data.get('Data', []))
    if isinstance(games, dict):
        games = [v for k, v in games.items() if isinstance(v, dict)]

    date_str = target_date.strftime('%Y-%m-%d')
    matches = []
    for g in games:
        if g.get('statusName') not in ('Not Started', 'Scheduled'):
            continue
        d = g.get('date', '')
        if not d or not d.startswith(date_str):
            continue
        try:
            dt = datetime.fromisoformat(d.replace('Z', '+00:00'))
            time_msk = (dt + MOW).strftime('%H:%M')
        except:
            time_msk = d[11:16]
        matches.append({
            'home': ru(g.get('homeTeam', {}).get('name', '?')),
            'away': ru(g.get('awayTeam', {}).get('name', '?')),
            'time': time_msk,
            'game_id': g.get('id', 0),
            'league_id': lid,
        })
    return matches


# ─── ESPN ────────────────────────────────────────────────────────────
def fetch_espn_upcoming(sport_path, date_str):
    """Предстоящие матчи через ESPN API (с кэшем 5 мин)."""
    import sport_cache
    cache_key = f'espn_upcoming_{sport_path}_{date_str}'
    cached = sport_cache.get('espn', cache_key)
    if cached is not None:
        return cached
    
    url = f'https://site.api.espn.com/apis/site/v2/sports/{sport_path}/scoreboard?dates={date_str}'
    try:
        resp = requests.get(url, timeout=15)
        data = resp.json()
    except:
        return []

    matches = []
    for e in data.get('events', []):
        comp = e.get('competitions', [{}])[0]
        status = comp.get('status', {}).get('type', {}).get('state', '')
        if status not in ('pre', 'scheduled', 'Scheduled'):
            continue
        teams = comp.get('competitors', [])
        if len(teams) < 2:
            continue
        date_raw = comp.get('date', comp.get('startDate', ''))
        try:
            dt = datetime.fromisoformat(date_raw.replace('Z', '+00:00'))
            time_msk = (dt + MOW).strftime('%H:%M')
        except:
            time_msk = ''
        matches.append({
            'home': ru(teams[0].get('team', {}).get('displayName', '?')),
            'away': ru(teams[1].get('team', {}).get('displayName', '?')),
            'time': time_msk,
        })
    import sport_cache
    sport_cache.set("espn", cache_key, matches)
    return matches


# ─── КХЛ ─────────────────────────────────────────────────────────────
def fetch_khl_upcoming(target_date):
    """Предстоящие матчи КХЛ на указанную дату."""
    try:
        subprocess.run(
            ['python3', '/root/.openclaw/workspace/khl_parser.py'],
            capture_output=True, text=True, timeout=60
        )
    except:
        pass

    files = sorted(glob.glob('/tmp/khl*.json'))
    if not files:
        return []

    try:
        with open(files[0]) as f:
            data = json.load(f)
    except:
        return []

    if isinstance(data, dict):
        data = list(data.values()) if all(isinstance(v, list) for v in data.values()) else []

    date_str = target_date.strftime('%d.%m.%Y')
    matches = []
    for m in data:
        if not isinstance(m, dict):
            continue
        if m.get('state') != 'scheduled':
            continue
        if m.get('date', '') != date_str:
            continue
        matches.append({
            'home': m.get('team1', '?'),
            'away': m.get('team2', '?'),
            'time': m.get('time', ''),
        })
    return matches


# ─── ТЕННИС UPCOMING ──────────────────────────────────────────────
MASTERS_1000_KEYWORDS = [
    'indian wells', 'miami open', 'miami presented',
    'monte-carlo', 'madrid',
    'internazionali bnl', 'italian open', 'rolex rome',
    'canada', 'national bank open',
    'cincinnati', 'shanghai', 'paris masters', 'paris rolex',
    'wuhan', 'beijing open', 'guadalajara',
    'dubai tennis', 'dubai duty free', 'qatar totalenergies',
]

TENNIS_GROUPINGS = {'mens-singles', 'womens-singles'}
GENDER_MAP = {'mens-singles': 'Мужчины', 'womens-singles': 'Женщины'}

TENNIS_ROUNDS = {
    'final': 'Финал', 'semifinal': '1/2', 'quarterfinal': '1/4',
    'round 4': 'Раунд 4', 'round 3': 'Раунд 3',
    'round 2': 'Раунд 2', 'round 1': 'Раунд 1',
}


def short_round(rnd_name):
    rn = rnd_name.lower().strip()
    for k, v in TENNIS_ROUNDS.items():
        if k in rn:
            return v
    return rnd_name[:12]


def tennis_is_target_tournament(event):
    if event.get('major', False):
        return True, 'Grand Slam'
    name = event.get('name', '').lower()
    for kw in MASTERS_1000_KEYWORDS:
        if kw in name:
            return True, 'Masters 1000'
    return False, None


def tennis_is_main_draw(rnd_name):
    if not rnd_name:
        return False
    return 'qualifying' not in rnd_name.lower()


def fetch_tennis_upcoming(date_str):
    """Предстоящие матчи ATP + WTA (scheduled/pre)."""
    matches = []
    url = f'https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard?dates={date_str}'
    try:
        resp = requests.get(url, timeout=15)
        raw = resp.json()
    except:
        return []

    for ev in raw.get('events', []):
        is_target, tier = tennis_is_target_tournament(ev)
        if not is_target:
            continue
        tname = ev.get('name', '?')

        for grp in ev.get('groupings', []):
            gslug = grp.get('grouping', {}).get('slug', '')
            if gslug not in TENNIS_GROUPINGS:
                continue
            gender = GENDER_MAP.get(gslug, gslug)

            for comp in grp.get('competitions', []):
                st = comp.get('status', {}).get('type', {}).get('state', '')
                if st not in ('pre', 'scheduled', 'Scheduled'):
                    continue

                rnd = comp.get('round', {}).get('displayName', '')
                if not tennis_is_main_draw(rnd):
                    continue

                # Фильтр по дате — только на завтра
                mdate = comp.get('date', '')
                if mdate:
                    mday = mdate[:10].replace('-', '')
                    if mday != date_str:
                        continue

                comps = comp.get('competitors', [])
                if len(comps) < 2:
                    continue

                p1 = tennis_names.ru_name(comps[0].get('athlete', {}).get('displayName', '?'))
                p2 = tennis_names.ru_name(comps[1].get('athlete', {}).get('displayName', '?'))

                # Время в МСК
                try:
                    dt = datetime.fromisoformat(mdate.replace('Z', '+00:00'))
                    time_msk = (dt + MOW).strftime('%H:%M')
                except:
                    time_msk = ''

                matches.append({
                    'tournament': tname,
                    'tier': tier,
                    'gender': gender,
                    'round': short_round(rnd),
                    'player1': p1,
                    'player2': p2,
                    'time': time_msk,
                })

    return matches


def format_tennis_upcoming_full(tree, gender_emoji):
    lines = []
    for (tname, tier), genders in tree.items():
        lines.append(f'<b>{tname}</b> ({tier})')
        for gender, rounds in genders.items():
            emoji = gender_emoji.get(gender, '')
            lines.append(f'<b>{emoji} {gender}</b>')
            for rnd_name, ms in rounds.items():
                lines.append(f'<b>{rnd_name}</b>' if rnd_name else '')
                for m in ms:
                    tm = f'{m["time"]}  ' if m['time'] else ''
                    lines.append(f'  {tm}{m["player1"]} — {m["player2"]}')
    return '\n'.join(lines)


# ─── ОТПРАВКА ───────────────────────────────────────────────────────
def send_telegram(text):
    banner_path = '/opt/banner.jpg'
    try:
        compact = text.replace('  ', ' ').replace('\n\n', '\n')
    except:
        compact = text
    caption = compact

    targets = [CHANNEL_ID, '-1003708361475']
    for chat_id in targets:
        try:
            with open(banner_path, 'rb') as f:
                url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto'
                files = {'photo': f}
                payload = {
                    'chat_id': chat_id,
                    'caption': caption,
                    'parse_mode': 'HTML',
                }
                resp = requests.post(url, files=files, data=payload, timeout=30)
                data = resp.json()
                if data.get('ok'):
                    print(f"✅ Пост отправлен в {chat_id} — {len(text)} символов")
                else:
                    print(f"❌ Ошибка {chat_id}: {data.get('description', 'неизвестно')}")
                    requests.post(f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
                        json={'chat_id': chat_id, 'text': caption, 'parse_mode': 'HTML'}, timeout=15)
        except Exception as e:
            print(f'❌ Ошибка отправки в {chat_id}: {e}')
            requests.post(f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
                json={'chat_id': chat_id, 'text': caption, 'parse_mode': 'HTML'}, timeout=15)

MAX_PER_LEAGUE = 10


def build_section(sec_lines, emoji, name, matches, hidden_store, sport_key):
    if not matches:
        return
    import re
    def clean_time(t):
        m = re.search(r'(\d{1,2}):(\d{2})$', t.strip())
        return m.group(0) if m else t
    sec_lines.append(f'\n{emoji} <b>{name}</b>:')
    total = len(matches)
    show = matches[:MAX_PER_LEAGUE]
    for m in sorted(show, key=lambda x: x.get('time', '')):
        tm = f'{clean_time(m["time"])}  ' if m.get('time') else ''
        sec_lines.append(f'  {tm}{m["home"]} — {m["away"]}')
    if total > MAX_PER_LEAGUE:
        sec_lines.append(f'  {MAX_PER_LEAGUE} из {total} матчей')
        hidden_store.setdefault(sport_key, []).append({'emoji': emoji, 'name': name, 'matches': matches})


def build_tennis_section(tennis, hidden_store):
    if not tennis:
        return None
    tree = {}
    for t in tennis:
        key = (t['tournament'], t['tier'])
        tree.setdefault(key, {})
        tree[key].setdefault(t['gender'], {})
        tree[key][t['gender']].setdefault(t['round'], []).append(t)
    gender_emoji = {'Мужчины': '👨', 'Женщины': '👩'}
    has_truncation = False
    tennis_lines = ['\n🎾 <b>Теннис</b>']
    for (tname, tier), genders in tree.items():
        tennis_lines.append(f'\n🏆 <b>{tname}</b> ({tier})')
        for gender, rounds in genders.items():
            emoji = gender_emoji.get(gender, '')
            tennis_lines.append(f'\n<b>{emoji} {gender}</b>')
            for rnd_name, ms in rounds.items():
                tennis_lines.append(f'<b>{rnd_name}</b>' if rnd_name else '')
                total = len(ms)
                show = ms[:MAX_PER_LEAGUE]
                for m in sorted(show, key=lambda x: x.get('time', '')):
                    tm = f'{m["time"]}  ' if m.get('time') else ''
                    tennis_lines.append(f'  {tm}{m["player1"]} — {m["player2"]}')
                if total > MAX_PER_LEAGUE:
                    tennis_lines.append(f'  {MAX_PER_LEAGUE} из {total} матчей')
                    has_truncation = True
    if len(tennis_lines) <= 1:
        return None
    tennis_lines.append('')
    result_text = '\n'.join(tennis_lines)
    if has_truncation:
        hidden_store.setdefault('tennis', []).append({'html': format_tennis_upcoming_full(tree, gender_emoji)})
    return result_text


def build_post(target_date, football, hockey, basketball, tennis=None, hidden_store=None):
    date_str = target_date.strftime('%d.%m.%Y')
    lines = ['<b>МАТЧИ ЗАВТРА</b>',
             f'{date_str}, {["ПН","ВТ","СР","ЧТ","ПТ","СБ","ВС"][target_date.weekday()]}', '']
    if hidden_store is None:
        hidden_store = {}
    sections = []
    if football:
        sec = []
        for name, emoji, matches in football:
            build_section(sec, emoji, name, matches, hidden_store, 'football')
        sec.append('')
        if any(l.startswith('  ') for l in sec):
            sections.append('\n'.join(sec))
    if hockey:
        sec = []
        for name, emoji, matches in hockey:
            build_section(sec, '🏒', name, matches, hidden_store, 'hockey')
        sec.append('')
        if any(l.startswith('  ') for l in sec):
            sections.append('\n'.join(sec))
    if basketball:
        sec = []
        for name, emoji, matches in basketball:
            build_section(sec, emoji, name, matches, hidden_store, 'basketball')
        sec.append('')
        if any(l.startswith('  ') for l in sec):
            sections.append('\n'.join(sec))
    tennis_section = build_tennis_section(tennis, hidden_store)
    if tennis_section:
        sections.append(tennis_section)
    if not sections:
        return f'📅 <b>Предстоящие матчи</b>\n🗓 {date_str}\n\nЗавтра матчей в выбранных лигах нет.'
    return '\n'.join(lines + sections)


# ─── MAIN ────────────────────────────────────────────────────────────
def main():
    now = datetime.now(UTC)
    # Завтра в МСК
    target_date = now + MOW + timedelta(days=1)
    date_str = target_date.strftime('%Y%m%d')

    weekday_ru = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС'][target_date.weekday()]
    print(f'📅 Собираю матчи на {target_date.strftime("%d.%m.%Y")} ({weekday_ru})')

    # ── Футбол ──
    football_leagues = []
    for lid, (name, emoji) in SSTATS_LEAGUES.items():
        matches = fetch_sstats_upcoming(lid, target_date)
        print(f'{"⚠️" if not matches else "✅"} {emoji} {name}: {len(matches)}')
        football_leagues.append((name, emoji, matches))

    # ── Сохраняем футбольные матчи для прогнозов ──
    try:
        upcoming_for_preds = []
        for name, emoji, matches in football_leagues:
            for m in matches:
                if m.get('game_id'):
                    upcoming_for_preds.append({
                        'home': m['home'],
                        'away': m['away'],
                        'time': m['time'],
                        'game_id': m['game_id'],
                        'league': name,
                        'league_id': m['league_id'],
                    })
        import storage as _st
        _st.add_date('/tmp/upcoming_matches.json',
                     target_date.strftime('%Y%m%d'),
                     upcoming_for_preds)
        print(f'💾 Сохранено {len(upcoming_for_preds)} матчей для прогнозов в /tmp/upcoming_matches.json')
    except Exception as _e:
        print(f'⚠️ Ошибка сохранения матчей для прогнозов: {_e}')

    # ── Хоккей ──
    hockey_leagues = []
    nhl = nhl_api.fetch_nhl_upcoming(date_str)
    print(f'✅ 🏒 НХЛ: {len(nhl)}')
    hockey_leagues.append(('НХЛ', '🏒', nhl))

    khl = fetch_khl_upcoming(target_date)
    print(f'✅ 🏒 КХЛ: {len(khl)}')
    hockey_leagues.append(('КХЛ', '🏒', khl))
    
    # ЧМ по хоккею (фильтр по завтрашней дате)
    whc_date_from = target_date.replace(hour=0, minute=0, second=0)
    whc_date_to = target_date.replace(hour=23, minute=59, second=59)
    try:
        whc_up, _ = flashscore_other.fetch_upcoming('world-cup-hockey', whc_date_from, whc_date_to)
        print(f'✅ 🏒 ЧМ по хоккею: {len(whc_up)}')
    except:
        whc_up = []
        print('⚠️ 🏒 ЧМ по хоккею: ошибка Playwright, пропускаем')
    hockey_leagues.append(('ЧМ по хоккею', '🏒', whc_up))

    # ── Баскетбол ──
    basketball_leagues = []
    nba = balldontlie_api.fetch_nba_upcoming(date_str)
    print(f'✅ 🏀 NBA: {len(nba)}')
    basketball_leagues.append(('NBA', '🏀', nba))
    
    # Лига ВТБ
    try:
        vtb_up, _ = flashscore_other.fetch_upcoming('vtb', whc_date_from, whc_date_to)
        print(f'✅ 🏀 Лига ВТБ: {len(vtb_up)}')
    except:
        vtb_up = []
        print('⚠️ 🏀 Лига ВТБ: ошибка Playwright, пропускаем')
    basketball_leagues.append(('Лига ВТБ', '🏀', vtb_up))
    
    # Euroleague
    try:
        euro_up, _ = flashscore_other.fetch_upcoming('euroleague', whc_date_from, whc_date_to)
        print(f'✅ 🏀 Euroleague: {len(euro_up)}')
    except:
        euro_up = []
        print('⚠️ 🏀 Euroleague: ошибка Playwright, пропускаем')
    basketball_leagues.append(('Euroleague', '🏀', euro_up))

    # ── Теннис ──
    tennis = fetch_tennis_upcoming(date_str)
    print(f'✅ 🎾 Теннис: {len(tennis)} матчей')

    # ── Пост ──
    hidden_store = {}
    post = build_post(target_date, football_leagues, hockey_leagues, basketball_leagues, tennis, hidden_store=hidden_store)
    print('\n' + '=' * 50)
    print(post[:800])
    print('=' * 50)
    send_telegram(post)

    # ── Кнопка expand ──
    if hidden_store:
        try:
            expand_sections = []
            for sport_key in ('football', 'hockey', 'basketball'):
                for item in hidden_store.get(sport_key, []):
                    import re
                    def clean_time(t):
                        m = re.search(r'(\d{1,2}):(\d{2})$', t.strip())
                        return m.group(0) if m else t
                    lines = [f'\n{item["emoji"]} <b>{item["name"]}</b>:']
                    for m in sorted(item['matches'], key=lambda x: x.get('time', '')):
                        tm = f'{clean_time(m["time"])}  ' if m.get('time') else ''
                        lines.append(f'  {tm}{m["home"]} — {m["away"]}')
                    expand_sections.append('\n'.join(lines))
            for item in hidden_store.get('tennis', []):
                if item.get('html'):
                    expand_sections.append(f'\n🎾 <b>Теннис</b>\n\n{item["html"]}')
            if expand_sections:
                with open('/tmp/sport_expand_upcoming.json', 'w') as _ef:
                    json.dump({'ts': datetime.now(UTC).isoformat(), 'html': '\n'.join(expand_sections)}, _ef, ensure_ascii=False)
                r = requests.post(f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage', json={
                    'chat_id': CHANNEL_ID,
                    'text': '📋 <b>Предстоящие матчи — полный список</b>\n\nНажмите кнопку, чтобы показать все матчи в лигах с более чем 10 результатами.',
                    'parse_mode': 'HTML',
                    'reply_markup': {'inline_keyboard': [[{'text': '📋 Показать всё', 'callback_data': 'expand_all_upcoming'}]]},
                }, timeout=15)
                if r.status_code == 200:
                    print('✅ Кнопка "Показать всё" отправлена')
        except Exception as e:
            print(f'❌ Ошибка кнопки: {e}')


if __name__ == '__main__':
    main()
