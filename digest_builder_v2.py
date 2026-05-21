#!/usr/bin/env python3
"""
Два дайджеста:
1. Итоги прошедшего дня (results) — матчи, завершённые с 00:00 до 23:59
2. План на следующий день (plan) — предстоящие матчи с каналами
"""
import os, sys, json, re, requests, subprocess
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '/opt')
from date_utils import normalize_date, format_date_display, format_date_storage, format_date_iso

MOW = timedelta(hours=3)

# ============== ESPN Лиги ==============
LEAGUES = [
    ('soccer/eng.1', 'АПЛ',                  '🏴󠁧󠁢󠁥󠁮󠁧󠁿'),
    ('soccer/esp.1', 'Ла Лига',              '🇪🇸'),
    ('soccer/ita.1', 'Серия А',              '🇮🇹'),
    ('soccer/ger.1', 'Бундеслига',           '🇩🇪'),
    ('soccer/fra.1', 'Лига 1',               '🇫🇷'),
    ('soccer/por.1', 'Чемпионат Португалии', '🇵🇹'),
    ('hockey/nhl',   'НХЛ',                  '🇺🇸'),
    ('basketball/nba', 'НБА',                 '🏀'),
]

TEAMS = {
    'ARS': 'Арсенал', 'AVL': 'Астон Вилла', 'BHA': 'Брайтон',
    'BOU': 'Борнмут', 'BRE': 'Брентфорд', 'CHE': 'Челси',
    'CRY': 'Кристал Пэлас', 'EVE': 'Эвертон', 'FUL': 'Фулхэм',
    'IPS': 'Ипсвич', 'LEI': 'Лестер', 'LIV': 'Ливерпуль',
    'MCI': 'Манчестер Сити', 'MUN': 'Манчестер Юнайтед',
    'NEW': 'Ньюкасл', 'NFO': 'Ноттингем Форест',
    'SOU': 'Саутгемптон', 'TOT': 'Тоттенхэм', 'WHU': 'Вест Хэм',
    'WOL': 'Вулверхэмптон', 'SUN': 'Сандерленд',
    'MAN': 'Манчестер Юнайтед',
    'RMA': 'Реал Мадрид', 'BAR': 'Барселона', 'ATM': 'Атлетико',
    'BET': 'Реал Бетис', 'RSO': 'Реал Сосьедад', 'VIL': 'Вильярреал',
    'VAL': 'Валенсия', 'SEV': 'Севилья', 'BIL': 'Атлетик Бильбао',
    'ATH': 'Атлетик Бильбао', 'OSA': 'Осасуна', 'GET': 'Хетафе',
    'CEL': 'Сельта', 'RAY': 'Райо Вальекано', 'GIR': 'Жирона',
    'ALA': 'Алавес', 'LEV': 'Леванте', 'ESP': 'Эспаньол',
    'MLL': 'Мальорка', 'ELC': 'Эльче', 'OVI': 'Реал Овьедо',
    'NAP': 'Наполи', 'INT': 'Интер', 'MIL': 'Милан',
    'JUV': 'Ювентус', 'ROMA': 'Рома', 'LAZ': 'Лацио',
    'ATA': 'Аталанта', 'FIO': 'Фиорентина', 'BOL': 'Болонья',
    'TOR': 'Торино', 'UDI': 'Удинезе', 'SAS': 'Сассуоло',
    'GEN': 'Дженоа', 'CAG': 'Кальяри', 'LEC': 'Лечче',
    'PAR': 'Парма', 'PIS': 'Пиза', 'COMO': 'Комо',
    'CRE': 'Кремонезе', 'VER': 'Верона',
    'BAY': 'Бавария', 'BVB': 'Боруссия Дортмунд', 'DOR': 'Боруссия Дортмунд',
    'RBL': 'РБ Лейпциг', 'B04': 'Байер', 'SGE': 'Айнтрахт',
    'VFB': 'Штутгарт', 'SCF': 'Фрайбург', 'SVW': 'Вердер',
    'FCU': 'Унион Берлин', 'HDH': 'Хайденхайм', 'FCA': 'Аугсбург',
    'KOE': 'Кёльн', 'STP': 'Сент-Паули', 'HOF': 'Хоффенхайм',
    'TSG': 'Хоффенхайм', 'HSV': 'Гамбург', 'M05': 'Майнц',
    'WOB': 'Вольфсбург', 'BMG': 'Боруссия М.',
    'PSG': 'ПСЖ', 'LYON': 'Лион', 'MON': 'Монако',
    'MAR': 'Марсель', 'OLM': 'Марсель', 'LILL': 'Лилль',
    'RCL': 'Ланс', 'NIC': 'Ницца', 'NICE': 'Ницца',
    'STR': 'Страсбур', 'LOR': 'Лорьян', 'AUX': 'Осер',
    'ANG': 'Анже', 'HAC': 'Гавр', 'TOU': 'Тулуза',
    'REN': 'Ренн', 'NAN': 'Нант', 'METZ': 'Мец',
    'SLB': 'Бенфика', 'FCP': 'Порту', 'SCP': 'Спортинг',
    'BRA': 'Брага', 'VSC': 'Витория Гимарайнш',
    'SCB': 'Санта Клара', 'CDSC': 'Санта Клара',
    'ALV': 'Алверка', 'AVS': 'АВС', 'CPAC': 'Каза Пиа',
    'CDN': 'Насьонал', 'EPF': 'Эшторил', 'EST': 'Эштрела',
    'FCF': 'Фамаликан', 'CDT': 'Тондела',
    'GVFC': 'Жил Висенте', 'MFC': 'Морейренсе',
    'RAFC': 'Арока',
    'FLA': 'Флорида', 'TOR': 'Торонто', 'BOS': 'Бостон',
    'TBL': 'Тампа-Бэй', 'TB': 'Тампа-Бэй', 'MTL': 'Монреаль',
    'DET': 'Детройт', 'OTT': 'Оттава', 'BUF': 'Баффало',
    'CAR': 'Каролина', 'NJD': 'Нью-Джерси', 'NYR': 'Рейнджерс',
    'NYI': 'Айлендерс', 'PIT': 'Питтсбург', 'WSH': 'Вашингтон',
    'PHI': 'Филадельфия', 'CBJ': 'Коламбус', 'COL': 'Колорадо',
    'DAL': 'Даллас', 'MIN': 'Миннесота', 'WPG': 'Виннипег',
    'NSH': 'Нэшвилл', 'STL': 'Сент-Луис', 'UTA': 'Юта',
    'VGK': 'Вегас', 'EDM': 'Эдмонтон', 'LAK': 'Лос-Анджелес',
    'LA': 'Лос-Анджелес', 'VAN': 'Ванкувер', 'ANA': 'Анахайм',
    'SJS': 'Сан-Хосе', 'CGY': 'Калгари', 'SEA': 'Сиэтл',
    'CHI': 'Чикаго',
}

NHK_TEAMS = {
    'FLA': 'Флорида', 'TOR': 'Торонто', 'BOS': 'Бостон',
    'TBL': 'Тампа-Бэй', 'TB': 'Тампа-Бэй', 'MTL': 'Монреаль',
    'DET': 'Детройт', 'OTT': 'Оттава', 'BUF': 'Баффало',
    'CAR': 'Каролина', 'NJD': 'Нью-Джерси', 'NYR': 'Рейнджерс',
    'NYI': 'Айлендерс', 'PIT': 'Питтсбург', 'WSH': 'Вашингтон',
    'PHI': 'Филадельфия', 'CBJ': 'Коламбус', 'COL': 'Колорадо',
    'DAL': 'Даллас', 'MIN': 'Миннесота', 'WPG': 'Виннипег',
    'NSH': 'Нэшвилл', 'STL': 'Сент-Луис', 'UTA': 'Юта',
    'VGK': 'Вегас', 'EDM': 'Эдмонтон', 'LAK': 'Лос-Анджелес',
    'LA': 'Лос-Анджелес', 'VAN': 'Ванкувер', 'ANA': 'Анахайм',
    'SJS': 'Сан-Хосе', 'CGY': 'Калгари', 'SEA': 'Сиэтл',
    'CHI': 'Чикаго',
}

POR_TEAMS = {'FCA': 'Фаренсе'}

CONTEXT_ABBR = {
    'TOR': {'soccer/ita.1': 'Торино', 'hockey/nhl': 'Торонто', 'default': 'Торино'},
    'FCA': {'soccer/ger.1': 'Аугсбург', 'soccer/por.1': 'Фаренсе', 'default': 'Аугсбург'},
    'BRE': {'soccer/eng.1': 'Брентфорд', 'soccer/fra.1': 'Брест', 'default': 'Брентфорд'},
}

def tr(name, league_path=''):
    ctx = CONTEXT_ABBR.get(name)
    if ctx:
        if league_path in ctx:
            return ctx[league_path]
        return ctx.get('default', name)
    if 'nhl' in league_path and name in NHK_TEAMS:
        return NHK_TEAMS[name]
    if 'por' in league_path and name in POR_TEAMS:
        return POR_TEAMS[name]
    return TEAMS.get(name, name)


def fetch_espn(date_str):
    """Загрузка матчей ESPN на дату"""
    matches = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    for path, lname, emoji in LEAGUES:
        url = f'https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={date_str}'
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            data = resp.json()
            for ev in data.get('events', []):
                comp = ev.get('competitions', [{}])[0]
                c = comp.get('competitors', [])
                if len(c) < 2:
                    continue
                t1 = tr(c[0].get('team',{}).get('abbreviation',''), path)
                t2 = tr(c[1].get('team',{}).get('abbreviation',''), path)
                date_utc = comp.get('date', '')
                tm = '--:--'
                try:
                    t = datetime.fromisoformat(date_utc.replace('Z', '+00:00'))
                    tm = (t + MOW).strftime('%H:%M')
                except:
                    pass
                st = comp.get('status',{}).get('type',{})
                state = 'scheduled'
                if st.get('state') == 'post':
                    state = 'finished'
                elif st.get('state') in ('in','live'):
                    state = 'live'
                sc1 = c[0].get('score','-')
                sc2 = c[1].get('score','-')
                if isinstance(sc1, dict): sc1 = sc1.get('value','-')
                if isinstance(sc2, dict): sc2 = sc2.get('value','-')
                if sc1 == '-' or sc2 == '-' or sc1 == '' or sc2 == '':
                    score_s = '-:-'
                else:
                    score_s = f'{sc1}:{sc2}'
                matches.append({
                    'time': tm, 'team1': t1, 'team2': t2,
                    'score': score_s, 'state': state,
                    'league': lname, 'emoji': emoji,
                    'date': date_str,
                })
        except:
            continue
    return matches


def fetch_myscore(league_path, output_file):
    """Загрузка через Playwright (РПЛ/КХЛ)"""
    try:
        script = f'''
import os, json
from playwright.sync_api import sync_playwright
try:
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-blink-features=AutomationControlled'])
    context = browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', viewport={{{{'width': 1920, 'height': 1080}}}})
    page = context.new_page()
    page.set_default_timeout(60000)
    page.add_init_script('Object.defineProperty(navigator, "webdriver", {{ get: () => undefined }});')
    page.goto('https://www.myscore.ru{league_path}', wait_until='domcontentloaded')
    page.wait_for_timeout(8000)
    events = page.query_selector_all('.event__match')
    data = []
    for ev in events:
        time_el = ev.query_selector('.event__time')
        home_el = ev.query_selector('.event__homeParticipant')
        away_el = ev.query_selector('.event__awayParticipant')
        score_el = ev.query_selector('.event__score')
        stage_el = ev.query_selector('.event__stage')
        time = time_el.inner_text().strip() if time_el else ''
        home = home_el.inner_text().strip() if home_el else ''
        away = away_el.inner_text().strip() if away_el else ''
        score = score_el.inner_text().strip() if score_el else '-'
        stage = stage_el.inner_text().strip() if stage_el else ''
        if home and away:
            data.append({{'time': time, 'home': home, 'away': away, 'score': score, 'stage': stage}})
    # Дополнительно: собираем матчи из текста страницы (будущие даты)
    import re
    text = page.inner_text('body')
    # Ищем строки вида "27.4. Магнитогорск - Ак Барс, 28.4. Авангард - Локомотив"
    # Сначала находим все даты, потом парсим команды
    future_matches = []
    # Ищем сегменты вида "ЧИСЛО.ЧИСЛО. Команда-Команда"
    parts = re.split(r'(?=\d{{1,2}}\.\d{{1,2}}\.)', text)
    for part in parts:
        dm = re.match(r'(\d{{1,2}}\.\d{{1,2}}\.)\s*([А-Яа-я\s-]+?)\s*-\s*([А-Яа-я\s-]+?)(?=[,\.]|\s|$)', part.strip())
        if dm:
            date_part, home, away = dm.groups()
            home = home.strip().strip('-')
            away = away.strip().strip('-')
            if home and away and len(home) > 2 and len(away) > 2:
                future_matches.append((date_part, home, away))
    for date_part, home, away in future_matches:
        dup = any(d['home'] == home and d['away'] == away for d in data)
        if not dup:
            data.append({{'time': date_part + ' 00:00', 'home': home, 'away': away, 'score': '-', 'stage': ''}})
    with open('{output_file}', 'w') as f:
        json.dump(data, f, ensure_ascii=False)
except:
    pass
finally:
    os._exit(0)
'''
        subprocess.run([sys.executable, '-c', script], timeout=65)
        with open(output_file) as f:
            return json.load(f)
    except:
        return []


def classify_matches(raw_matches, league, emoji, ref_date):
    """Классификация сырых матчей из myscore по статусу"""
    today = datetime.now(timezone.utc) + MOW
    today_dt = today.replace(hour=0, minute=0, second=0, microsecond=0)
    
    result = []
    for m in raw_matches:
        time_text = m['time'].strip()
        home = m['home']
        away = m['away']
        score = m['score'].strip()
        stage = m.get('stage', '').strip()
        
        match_date = ref_date.strftime('%d.%m.%Y')
        time_part = time_text
        
        if '.' in time_text:
            parts = time_text.replace('\n', ' ').split()
            if len(parts) >= 2:
                match_date = parts[0].strip('.')
                time_part = parts[1]
                try:
                    d, mon = map(int, match_date.split('.'))
                    match_date = f'{d:02d}.{mon:02d}.{ref_date.year}'
                except:
                    match_date = ref_date.strftime('%d.%m.%Y')
        
        state = 'scheduled'
        has_score = bool(score and score != '-' and score != '–')
        
        if has_score or score == '0' or score == '1' or score == '2' or (score and len(score) <= 3 and score.isdigit()):
            has_ot = any(x in stage for x in ['OT', 'Бул', 'Pen', 'После'])
            if has_ot:
                state = 'finished'
            else:
                try:
                    dt = datetime.strptime(match_date, '%d.%m.%Y')
                    if (today_dt - dt).days >= 1:
                        state = 'finished'
                    elif (today_dt - dt).days == 0:
                        state = 'live'
                except:
                    state = 'finished'
        elif score and score != '-:-':
            try:
                dt = datetime.strptime(match_date, '%d.%m.%Y')
                if (today_dt - dt).days >= 1:
                    state = 'finished'
            except:
                pass
        
        if score in ['-', '–', '']:
            score = '-:-'
        
        # Определяем был ли в raw time текст с датой (точка = dd.mm)
        has_raw_date = '.' in time_text.partition(' ')[0] if ' ' in time_text.strip() else False
        
        result.append({
            'time': time_part,
            'team1': home,
            'team2': away,
            'score': score,
            'state': state,
            'date': match_date,
            'league': league,
            'emoji': emoji,
            'has_raw_date': has_raw_date,
        })
    
    return result


def fetch_tvguide(date_str=None):
    """Загрузка программы Матч ТВ с tvguide"""
    try:
        sys.path.insert(0, '/opt')
        from matchtv_tvguide import get_all_tv_channels
        return get_all_tv_channels(date_str)
    except:
        return {}


# ============ Основная логика ============
try:
    import sys; sys.path.insert(0, '/opt')
    from matchtv_tvguide import find_real_channel as _frc
    _find_channel = _frc
except:
    _find_channel = None

def fetch_myscore_data():
    """Playwright только для КХЛ (РПЛ через SStats — HTTP, без браузера). Кэш 2 часа."""
    import sport_cache
    cached = sport_cache.get('myscore', 'khl_only')
    if cached is not None:
        return [], cached
    
    khl_raw = fetch_myscore('/hockey/russia/khl/', '/tmp/khl_data.json')
    sport_cache.set('myscore', 'khl_only', khl_raw)
    return [], khl_raw


def build_results(ref_date, rpl, khl):
    """Дайджест 1: Итоги прошедших суток"""
    today = ref_date
    date_str = format_date_storage(today)
    date_ru = format_date_display(today)
    days = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС']
    dow = days[today.weekday()]
    
    lines = []
    lines.append(f'📅 **Итоги {date_ru} ({dow})**')
    lines.append('')
    
    # Собираем матчи за сегодня
    print('📡 Результаты: ESPN...', file=sys.stderr)
    espn = fetch_espn(date_str)
    
    # Только завершённые за сегодня
    all_finished = [m for m in espn + rpl + khl if m['state'] == 'finished']
    
    # Проверяем что дата совпадает с сегодня
    today_finished = []
    for m in all_finished:
        m_date = m.get('date', '')
        if len(m_date) == 8 and m_date == date_str:
            today_finished.append(m)
        elif len(m_date) == 10 and m_date[:5] == date_ru[:5]:
            today_finished.append(m)
    
    if not today_finished:
        lines.append('Нет завершённых матчей')
        return '\n'.join(lines)
    
    # По лигам
    ALL_LEAGUES = ['АПЛ', 'Ла Лига', 'Бундеслига', 'Серия А', 'Лига 1', 'Чемпионат Португалии', 'РПЛ', 'НХЛ', 'КХЛ', 'НБА']
    for lname in ALL_LEAGUES:
        ms = [m for m in today_finished if m['league'] == lname]
        if not ms:
            continue
        emoji = ms[0]['emoji']
        lines.append(f'{emoji} **{lname}**')
        ms.sort(key=lambda x: x['time'])
        for m in ms:
            lines.append(f'  🕐 {m["time"]} | {m["team1"]} - {m["team2"]} | {m["score"]}')
        lines.append('')
    
    lines.append(f'📊 Всего: {len(today_finished)} завершённых матчей')
    
    return '\n'.join(lines)


def _find_channel(match, channels):
    try:
        from matchtv_tvguide import find_real_channel
        return find_real_channel(match, channels)
    except:
        return []

def build_plan(ref_date, rpl, khl):
    """Дайджест 2: План на следующий день"""
    # Дата плана — ref_date + 1 день
    plan_date = ref_date + timedelta(days=1)
    date_str = format_date_storage(plan_date)
    date_ru = format_date_display(plan_date)
    days = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС']
    dow = days[plan_date.weekday()]
    
    lines = []
    lines.append(f'📅 **План на {date_ru} ({dow})**')
    lines.append(f'')
    
    # Собираем матчи на завтра
    print('📡 План: ESPN...', file=sys.stderr)
    espn = fetch_espn(date_str)
    
    print('📡 План: TV Guide...', file=sys.stderr)
    tvguide_date = format_date_iso(plan_date)
    tvguide = fetch_tvguide(tvguide_date)
    
    # Только запланированные на завтра
    all_scheduled = []
    for m in espn + rpl + khl:
        if m['state'] != 'scheduled':
            continue
        m_date = m.get('date', '')
        # Пропускаем если нет даты (live без даты = сегодняшний)
        if not m_date or len(m_date) < 5:
            continue
        # Пропускаем матчи myscore без raw даты (сегодняшние live, не завтра)
        if not m.get('has_raw_date', True) and m['league'] in ('РПЛ', 'КХЛ'):
            continue
        if len(m_date) == 8:
            if m_date == date_str:
                all_scheduled.append(m)
        elif len(m_date) == 10:
            if m_date[:5] == date_ru[:5]:
                all_scheduled.append(m)
    
    # Добавляем КХЛ матчи из TV Guide если их нет в myscore
    khl_in_plan = any(m['league'] == 'КХЛ' for m in all_scheduled)
    if not khl_in_plan:
        from matchtv_tvguide import find_sport_broadcasts
        khl_from_tv = find_sport_broadcasts(tvguide)
        for prog in khl_from_tv:
            title = prog['title']
            if 'КХЛ' not in title and 'Хоккей' not in title:
                continue
            # Парсим команды из заголовка: "Хоккей. КХЛ. "Команда" - "Команда""
            import re
            # Парсим команды в кавычках: "Команда" или "Команда" (Город)
            quoted = re.findall(r'"([^"]+)"', title)
            teams = [q.strip() for q in quoted if q.strip() and len(q.strip()) > 2]
            if len(teams) >= 2:
                home = teams[0]
                away = teams[1]
                # Находим время из tvguide
                from datetime import datetime
                try:
                    dt = datetime.strptime(prog['time'], '%H:%M')
                    time = prog['time']
                except:
                    time = prog['time']
                # Избегаем дубликатов
                dup = any(m['team1'] == home and m['team2'] == away for m in all_scheduled)
                if not dup:
                    tvm = {'team1': home, 'team2': away}
                    ch = _find_channel(tvm, tvguide)
                    all_scheduled.append({
                        'time': time, 'team1': home, 'team2': away,
                        'score': '-:-', 'state': 'scheduled',
                        'date': date_ru, 'league': 'КХЛ', 'emoji': '🏒'
                    })
    
    if not all_scheduled:
        lines.append('Нет запланированных матчей')
        return '\n'.join(lines)
    
    # По лигам с каналами
    ALL_LEAGUES = ['АПЛ', 'Ла Лига', 'Бундеслига', 'Серия А', 'Лига 1', 'Чемпионат Португалии', 'РПЛ', 'НХЛ', 'КХЛ', 'НБА']
    for lname in ALL_LEAGUES:
        ms = [m for m in all_scheduled if m['league'] == lname]
        if not ms:
            continue
        emoji = ms[0]['emoji']
        lines.append(f'{emoji} **{lname}**')
        ms.sort(key=lambda x: x['time'])
        for m in ms:
            ch = _find_channel(m, tvguide)
            ch_str = f' | {", ".join(ch)}' if ch else ''
            lines.append(f'  🕐 {m["time"]} | {m["team1"]} - {m["team2"]}{ch_str}')
        lines.append('')
    
    lines.append(f'📊 Всего: {len(all_scheduled)} запланированных матчей')
    
    return '\n'.join(lines)


def run_daily():
    """Запуск обоих дайджестов (вызывается в 23:59)"""
    # ref_date в МСК. Если сейчас 00-02 ночи (МСК) — берём предыдущий день
    now_mow = datetime.now(timezone.utc) + MOW
    ref_date = now_mow - timedelta(days=1) if now_mow.hour < 3 else now_mow
    next_date = ref_date + timedelta(days=1)
    
    print(f'=== Дайджесты на {ref_date.strftime("%d.%m.%Y")} ===')
    
    # Единый вызов Playwright для РПЛ и КХЛ
    print('\n📡 Загрузка РПЛ/КХЛ...', file=sys.stderr)
    rpl_raw, khl_raw = fetch_myscore_data()
    
    # Классифицируем для сегодня (results)
    rpl_today = classify_matches(rpl_raw, 'РПЛ', '🇷🇺', ref_date)
    khl_today = classify_matches(khl_raw, 'КХЛ', '🏒', ref_date)
    
    # Классифицируем для завтра (plan)
    rpl_tomorrow = classify_matches(rpl_raw, 'РПЛ', '🇷🇺', next_date)
    khl_tomorrow = classify_matches(khl_raw, 'КХЛ', '🏒', next_date)
    
    print('\n📋 Результаты:', file=sys.stderr)
    results = build_results(ref_date, rpl_today, khl_today)
    print(results)
    print()
    
    print('\n📋 План:', file=sys.stderr)
    plan = build_plan(ref_date, rpl_tomorrow, khl_tomorrow)
    print(plan)
    
    # Сохраняем оба
    with open('/tmp/digest_results.txt', 'w', encoding='utf-8') as f:
        f.write(results)
    with open('/tmp/digest_plan.txt', 'w', encoding='utf-8') as f:
        f.write(plan)
    
    return results, plan


def send_telegram(text):
    """Отправка в Telegram"""
    TOKEN = '8306342350:AAEk1WiRwoNsXNdxh5ehfqWdifijzu0a_Eg'
    CHAT_ID = '208291706'
    r = requests.post(f'https://api.telegram.org/bot{TOKEN}/sendMessage',
                      json={'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'Markdown'},
                      timeout=15)
    return r.status_code


if __name__ == '__main__':
    if '--send' in sys.argv:
        print('📡 Формирую дайджесты...', file=sys.stderr)
        results, plan = run_daily()
        
        full = results + '\n\n' + plan
        print(full)
        
        # Отправляем
        print('📡 Отправляю...', file=sys.stderr)
        s1 = send_telegram(results)
        s2 = send_telegram(plan)
        print(f'Результаты: {s1}, План: {s2}', file=sys.stderr)
    else:
        now_mow = datetime.now(timezone.utc) + MOW
        ref_date = now_mow - timedelta(days=1) if now_mow.hour < 3 else now_mow
        next_date = ref_date + timedelta(days=1)
        
        print('📡 Загрузка РПЛ/КХЛ...', file=sys.stderr)
        rpl_raw, khl_raw = fetch_myscore_data()
        rpl_today = classify_matches(rpl_raw, 'РПЛ', '🇷🇺', ref_date)
        khl_today = classify_matches(khl_raw, 'КХЛ', '🏒', ref_date)
        rpl_tomorrow = classify_matches(rpl_raw, 'РПЛ', '🇷🇺', next_date)
        khl_tomorrow = classify_matches(khl_raw, 'КХЛ', '🏒', next_date)
        
        results = build_results(ref_date, rpl_today, khl_today)
        plan = build_plan(ref_date, rpl_tomorrow, khl_tomorrow)
        
        print(results)
        print()
        print('=' * 40)
        print()
        print(plan)
