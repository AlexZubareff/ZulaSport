#!/usr/bin/env python3
"""
Генератор статического сайта Zula Спорт.
Собирает новости, результаты, расписание и ТВ-программу → index.html
Запуск по cron: каждые 30-60 минут
"""

import os, sys, json, re, html as html_mod
from datetime import datetime, timedelta, timezone
from pathlib import Path
import feedparser
from readability import Document as ReadabilityDoc

sys.path.insert(0, '/opt')
import tv_channels, requests
from matchtv_tvguide import fetch_tvguide, find_sport_broadcasts

# ─── ЛИГИ С ПРОГНОЗАМИ ─────────────────────────────────────────────
_PRED_LEAGUES = set()
_pred_path = '/opt/prediction_leagues.json'
if os.path.exists(_pred_path):
    try:
        with open(_pred_path) as f:
            _PRED_LEAGUES = set(json.load(f).get('active', {}).keys())
    except:
        pass


# ─── ЛОГОТИПЫ КОМАНД ────────────────────────────────────────────────
_TEAM_LOGOS = {}
_logos_path = '/opt/team_logos.json'
if os.path.exists(_logos_path):
    try:
        with open(_logos_path) as f:
            _TEAM_LOGOS = json.load(f).get('teams', {})
    except:
        pass


def _normalize(name):
    """Нормализовать название: убрать диакритику, нижний регистр."""
    import unicodedata
    nfkd = unicodedata.normalize('NFKD', name)
    return nfkd.encode('ASCII', 'ignore').decode().lower().strip()


def _team_logo(team_name):
    """Найти URL логотипа по названию команды."""
    if not team_name:
        return ''
    # Точное совпадение
    if team_name in _TEAM_LOGOS:
        return _TEAM_LOGOS[team_name]['url']
    # Нормализованное (без диакритики: Alavés → Alaves)
    norm = _normalize(team_name)
    if norm:
        for k, v in _TEAM_LOGOS.items():
            if _normalize(k) == norm:
                return v['url']
    # По словам (только для составных названий из 2+ слов, не для "УНИКС", "Зенит")
    words = team_name.split()
    if len(words) >= 2:
        for w in words:
            if w in _TEAM_LOGOS:
                return _TEAM_LOGOS[w]['url']
    return ''

UTC = timezone.utc
MOW = timedelta(hours=3)
OUTPUT = '/var/www/sport/index.html'

# ─── ARTICLE CONTENT EXTRACTION ────────────────────────────────────
def extract_article_content(url, timeout=12):
    """Извлечь полный текст статьи через readability-lxml."""
    try:
        resp = requests.get(url, timeout=timeout, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
        })
        resp.raise_for_status()
        doc = ReadabilityDoc(resp.text)
        content = doc.summary()
        # Обрезать слишком длинные (не удалось извлечь — весь HTML)
        if len(content) > 50000:
            return ''
        return content
    except:
        return ''


def sanitize_content(html_text):
    """Подчистить HTML контент: убрать мусор, html/body обёртки, заголовки статей."""
    if not html_text:
        return ''
    # Убрать скрипты и стили
    html_text = re.sub(r'<script[^>]*>.*?</script>', '', html_text, flags=re.DOTALL)
    html_text = re.sub(r'<style[^>]*>.*?</style>', '', html_text, flags=re.DOTALL)
    # Убрать on* атрибуты (onclick, onload, и т.д.)
    html_text = re.sub(r' on\w+="[^"]*"', '', html_text)
    # Убрать обёртку от readability: <html><body>...</body></html>
    html_text = re.sub(r'</?html>|</?body>', '', html_text)
    # Убрать внешний контейнер <div> (первый и последний, если readability завернул)
    html_text = re.sub(r'^<div>', '', html_text)
    html_text = re.sub(r'</div>$', '', html_text)
    # Убрать header.article-head (заголовок внутри статьи — он уже есть в модалке)
    html_text = re.sub(r'<header[^>]*>.*?</header>', '', html_text, flags=re.DOTALL)
    # Убрать пустые div-обёртки
    html_text = re.sub(r'<div[^>]*>\s*</div>', '', html_text)
    # Убрать баннеры и рекламные вставки
    html_text = re.sub(r'<p[^>]*class="[^"]*banner[^"]*"[^>]*>.*?</p>', '', html_text, flags=re.DOTALL)
    # Убрать навигационные элементы
    html_text = re.sub(r'<nav[^>]*>.*?</nav>', '', html_text, flags=re.DOTALL)
    # Убрать пустые абзацы
    html_text = re.sub(r'<p>\s*</p>', '', html_text)
    return html_text.strip()

# ─── RSS FEEDS ───────────────────────────────────────────────────────
# ─── TRANSLATION ────────────────────────────────────────────────────
_TRANS_CACHE = '/tmp/sport_translation_cache.json'

def _load_cache():
    try:
        with open(_TRANS_CACHE) as f:
            return json.load(f)
    except:
        return {}

_MAX_CACHE = 200  # храним не больше 200 переводов

def _save_cache(cache):
    try:
        # Если кэш слишком большой — удаляем старые записи
        if len(cache) > _MAX_CACHE:
            # cache: {text_hash: {translated, time}} или {text: translated}
            # Если старый формат (просто ключ-значение), конвертируем
            items = []
            for k, v in cache.items():
                if isinstance(v, dict):
                    items.append((v.get('time', 0), k, v))
                else:
                    items.append((0, k, v))
            items.sort(reverse=True)  # свежие первые
            cache = {k: (v if isinstance(v, dict) else v) for _, k, v in items[:_MAX_CACHE]}
        
        with open(_TRANS_CACHE, 'w') as f:
            json.dump(cache, f, ensure_ascii=False)
    except:
        pass

def _translate(text):
    """Перевести текст на русский через DeepSeek с кэшированием."""
    if not text or len(text) < 10:
        return text
    cache = _load_cache()
    key = text[:100]
    
    # Проверяем кэш (поддерживаем оба формата)
    if key in cache:
        val = cache[key]
        if isinstance(val, dict):
            return val.get('translated', text)
        return val

    try:
        key_file = open('/etc/deepseek.key')
        api_key = key_file.read().strip()
        key_file.close()
        resp = requests.post('https://api.deepseek.com/v1/chat/completions', json={
            'model': 'deepseek-chat',
            'messages': [
                {'role': 'system', 'content': 'Переведи на русский. Только перевод, без пояснений. Сохрани имена, названия команд и клубов.'},
                {'role': 'user', 'content': text}
            ],
            'temperature': 0.1,
            'max_tokens': 500
        }, headers={'Authorization': f'Bearer {api_key}'}, timeout=15)
        data = resp.json()
        if 'choices' in data and len(data['choices']) > 0:
            translated = data['choices'][0]['message']['content'].strip()
            # Сохраняем с меткой времени
            from time import time
            cache[key] = {'translated': translated, 'time': time()}
            _save_cache(cache)
            return translated
    except:
        pass
    return text


def _translate_article(html_content, source):
    """Перевести полный текст статьи на русский.
    Принимает HTML-контент, возвращает переведённый текст (без HTML-тегов).
    Если контент короткий или уже на русском — возвращает пустую строку."""
    if not html_content or source in ('Чемпионат', 'Sports.ru'):
        return ''
    
    # Извлекаем текст
    text = re.sub(r'<[^>]+>', '', html_content).strip()
    # Если есть кириллица — уже на русском
    if re.search(r'[а-яА-ЯёЁ]', text[:200]):
        return ''
    # Слишком короткий — не переводим
    if len(text) < 200:
        return ''
    
    # Ограничение 15000 символов (защита от запредельно длинных статей)
    # Средняя токен-стоимость перевода большой статьи: ~$0.002-0.005
    if len(text) > 15000:
        text = text[:15000]
    
    cache = _load_cache()
    key = 'article:' + text[:80]
    
    if key in cache:
        val = cache[key]
        if isinstance(val, dict):
            return val.get('translated', '')
        return val
    
    try:
        with open('/etc/deepseek.key') as f:
            api_key = f.read().strip()
        resp = requests.post('https://api.deepseek.com/v1/chat/completions', json={
            'model': 'deepseek-chat',
            'messages': [
                {'role': 'system', 'content': 'Ты профессиональный переводчик спортивных новостей. Переведи текст на литературный русский язык. Сохрани имена, названия команд, клубов, турниров, числа, даты в оригинале или с общепринятой транслитерацией. Только перевод, без комментариев и пояснений.'},
                {'role': 'user', 'content': text}
            ],
            'temperature': 0.1,
            'max_tokens': 5000
        }, headers={'Authorization': f'Bearer {api_key}'}, timeout=60)
        data = resp.json()
        if 'choices' in data and len(data['choices']) > 0:
            translated = data['choices'][0]['message']['content'].strip()
            from time import time
            cache[key] = {'translated': translated, 'time': time()}
            _save_cache(cache)
            return translated
    except:
        pass
    return ''


RSS_FEEDS = [
    ('https://feeds.bbci.co.uk/sport/rss.xml', 'BBC Sport'),
    ('https://feeds.bbci.co.uk/sport/football/rss.xml', 'BBC Football'),
    ('https://www.skysports.com/rss/12040', 'Sky Sports'),
    ('https://www.theguardian.com/football/rss', 'Guardian Football'),
    ('https://www.championat.com/rss/news/', 'Чемпионат'),
    ('https://www.sports.ru/rss/all_news.xml', 'Sports.ru'),
    ('https://www.mk.ru/rss/sport/index.xml', 'МК Спорт'),
]


def _extract_image(entry, source=''):
    """Извлечь URL изображения из RSS-записи.
    Guardian (signed) and BBC (slow from Russia) — skip."""
    # 1. media_content (Sky Sports, Guardian, BBC)
    if hasattr(entry, 'media_content'):
        for mc in entry.media_content:
            url = mc.get('url', '')
            if url and 'guim.co.uk' not in url and 'ichef.bbci.co.uk' not in url:
                return url

    # 2. media_thumbnail (BBC uses this)
    if hasattr(entry, 'media_thumbnail'):
        for mt in entry.media_thumbnail:
            url = mt.get('url', '')
            if url and 'ichef.bbci.co.uk' not in url:
                return url

    # 3. enclosures
    if hasattr(entry, 'enclosures'):
        for enc in entry.enclosures:
            if enc.get('type', '').startswith('image/'):
                url = enc.get('href', '')
                if url and 'ichef.bbci.co.uk' not in url:
                    return url

    # 4. img tag in summary (Чемпионат)
    summary = entry.get('summary', '')
    m = re.search(r'<img[^>]+src="([^"]+)"', summary)
    if m:
        url = m.group(1)
        if 'ichef.bbci.co.uk' not in url:
            return url

    # 5. links
    if hasattr(entry, 'links'):
        for link in entry.links:
            if link.get('type', '').startswith('image/'):
                url = link.get('href', '')
                if url and 'ichef.bbci.co.uk' not in url:
                    return url

    return ''


def fetch_news(content_cache=None):
    """Собрать новости из RSS-лент. Возвращает список, отсортированный по свежести.
    content_cache: {link: content_html} — кеш полных текстов статей из прошлой генерации."""
    if content_cache is None:
        content_cache = {}
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=2)  # новости не старше 2 дней
    news = []
    seen_links = set()

    for url, source in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                title = entry.get('title', '')
                link = entry.get('link', '')
                desc = entry.get('summary', entry.get('description', ''))
                desc_clean = re.sub(r'<[^>]+>', '', desc)[:250]
                desc_full = re.sub(r'<[^>]+>', '', desc).strip()
                img_url = _extract_image(entry, source)

                pub = entry.get('published_parsed') or entry.get('updated_parsed')
                ts = 0
                pub_str = ''
                if pub:
                    try:
                        dt = datetime(*pub[:6], tzinfo=UTC)
                        ts = dt.timestamp()
                        # Пропускаем новости старше 2 дней
                        if dt < cutoff:
                            continue
                        age = now - dt
                        secs = age.total_seconds()
                        if secs < 60:
                            pub_str = 'только что'
                        elif secs < 3600:
                            pub_str = f'{int(secs / 60)} мин. назад'
                        elif secs < 86400:
                            pub_str = f'{int(secs / 3600)} ч. назад'
                        else:
                            pub_str = dt.strftime('%d.%m')
                    except:
                        continue

                # Дедупликация по ссылке
                if link in seen_links:
                    continue
                seen_links.add(link)

                # Переводим BBC и Guardian на русский
                if source in ('BBC Sport', 'BBC Football', 'BBC Tennis', 'Guardian Football', 'Sky Sports'):
                    title = _translate(title)
                    desc_clean = _translate(desc_clean) if desc_clean else ''

                # Извлекаем полный текст статьи (из кеша или через readability)
                content = content_cache.get(link, '')
                if content:
                    content = sanitize_content(content)  # чистим кеш на всякий
                if not content and ts > 0 and len(desc_clean) > 50:
                    print(f'  📥 Извлекаю статью: {title[:50]}...')
                    content = extract_article_content(link)
                    content = sanitize_content(content)
                    if content:
                        print(f'     ✅ {len(content)} chars')

                # Переводим контент зарубежных источников
                content_ru = content_cache.get(link + '::ru', '')
                if content and not content_ru and source in ('BBC Sport', 'BBC Football', 'BBC Tennis', 'Guardian Football', 'Sky Sports'):
                    content_ru = _translate_article(content, source)
                    if content_ru:
                        print(f'     🌐 Перевод: {len(content_ru)} chars')

                # Пропускаем зарубежные live-блоги/видео/анонсы без полезного контента
                foreign = source in ('BBC Sport', 'BBC Football', 'BBC Tennis', 'Guardian Football', 'Sky Sports')
                text_len = len(re.sub(r'<[^>]+>', '', content).strip()) if content else 0
                if foreign and text_len < 80:
                    print(f'  ⏭️ Пропущен (live/анонс): {title[:50]} (текст: {text_len} симв)')
                    continue

                news.append({
                    'title': title,
                    'desc': desc_clean,
                    'desc_full': desc_full,
                    'link': link,
                    'source': source,
                    'image': img_url,
                    'time': pub_str,
                    'ts': ts,
                    'content': content,
                    'content_ru': content_ru,
                })
        except:
            continue

    # Сортируем по свежести (новые сверху)
    news.sort(key=lambda x: x['ts'], reverse=True)
    return news


# ─── RESULTS ─────────────────────────────────────────────────────────
def fetch_results():
    """Собрать результаты матчей за вчера/сегодня.
    Пытается читать из JSON, если свежий. Иначе запускает сбор."""
    # Пробуем загрузить из существующего файла daily_results
    results_file = '/tmp/daily_results_last.json'
    if os.path.exists(results_file):
        try:
            with open(results_file) as f:
                return json.load(f)
        except:
            pass

    # Пробуем запустить daily_results и перехватить вывод
    # На самом деле daily_results отправляет в Telegram, не сохраняет JSON
    # Поэтому пока возвращаем заглушку
    return []


def get_results_text(live_lookup=None):
    """Результаты из всех доступных источников.
    - finished из live_scores (сегодняшние матчи)
    + daily_results_data.json (вчерашние + хоккей/теннис)
    Дедупликация по (league, home, away).
    """
    all_results = []
    seen = set()

    # 1. Finished из live_scores
    if live_lookup:
        for key, info in live_lookup.items():
            if info.get('status') == 'finished' and info.get('score'):
                parts = key.split('||', 2)
                if len(parts) == 3:
                    league, home, away = parts
                    dedup = (league, home, away)
                    if dedup not in seen:
                        seen.add(dedup)
                        all_results.append({
                            'sport': 'football',
                            'league': league,
                            'home': home,
                            'away': away,
                            'score': info['score'],
                        })

    # 2. Daily results (хоккей, теннис, баскетбол — чего нет в ESPN)
    results_file = '/tmp/daily_results_data.json'
    if os.path.exists(results_file):
        try:
            with open(results_file) as f:
                data = json.load(f)
            for r in data.get('results', []):
                dedup = (r.get('league', ''), r.get('home', ''), r.get('away', ''))
                if dedup not in seen:
                    seen.add(dedup)
                    all_results.append(r)
        except:
            pass

    if not all_results:
        return ''

    emoji_map = {'football': '⚽', 'hockey': '🏒', 'basketball': '🏀', 'tennis': '🎾'}

    # Логотипы лиг (для секции результатов)
    _result_league_logos = {
        'АПЛ': '/static/leagues/апл.png',
        'Ла Лига': '/static/leagues/ла-лига.png',
        'Серия А': '/static/leagues/серия-а.png',
        'Бундеслига': '/static/leagues/бундеслига.png',
        'Лига 1': '/static/leagues/лига-1.png',
        'РПЛ': '/static/leagues/рпл.png',
        'НХЛ': '/static/leagues/нхл.png',
        'NBA': '/static/leagues/nba.png',
    }

    groups = {}
    for r in all_results:
        emoji = emoji_map.get(r.get('sport', ''), '📺')
        league = r.get('league', '?')
        key = f'{emoji} {league}'
        groups.setdefault(key, []).append(r)

    html = '<div class="card-grid">'
    for title, items in groups.items():
        # Извлекаем название лиги после эмодзи и ставим логотип
        parts = title.split(' ', 1)
        league_name = parts[1] if len(parts) > 1 else title
        logo_url = _result_league_logos.get(league_name, '')
        logo_html = f'<img class="league-logo" src="{logo_url}" alt="" loading="lazy">' if logo_url else ''
        html += f'<div class="section-sub">{logo_html} {escape(league_name)}</div>'
        for r in items:
            home = html_mod.escape(r.get('home', '?'))
            away = html_mod.escape(r.get('away', '?'))
            score = r.get('score', '-:-')

            # Теннис: "1-6 6-1 2-6" — геймы по сетам + сеты
            if r.get('sport') == 'tennis':
                sets = score.split()
                home_games = []
                away_games = []
                for s in sets:
                    if '-' in s:
                        parts = s.split('-')
                        home_games.append(parts[0])
                        away_games.append(parts[1])
                home_sets = sum(1 for s in sets if '-' in s and int(s.split('-')[0]) > int(s.split('-')[1]))
                away_sets = sum(1 for s in sets if '-' in s and int(s.split('-')[1]) > int(s.split('-')[0]))
                html += f'''
                <div class="result-card">
                    <div class="rc-row"><span class="rc-left"><span class="rc-name">{home}</span></span><span class="rc-games">{" ".join(home_games)}</span><span class="rc-sc">{home_sets}</span></div>
                    <div class="rc-row rc-row-away"><span class="rc-left"><span class="rc-name">{away}</span></span><span class="rc-games">{" ".join(away_games)}</span><span class="rc-sc">{away_sets}</span></div>
                </div>'''
                continue

            # Разбираем счёт на две части (Х:Y или Х-Y)
            sep = ':' if ':' in score else ('-' if '-' in score else '')
            if sep:
                parts = score.split(sep)
                home_score = parts[0].strip()
                away_score = sep.join(parts[1:]).strip() if len(parts) > 1 else ''
            else:
                home_score = score
                away_score = ''

            # Логотипы только для лиг, которые есть в ESPN
            _LOGO_LEAGUES = {'АПЛ', 'Ла Лига', 'Серия А', 'Бундеслига', 'Лига 1', 'РПЛ', 'НХЛ', 'NBA'}
            has_logo = r.get('league') in _LOGO_LEAGUES

            if has_logo:
                home_logo = _team_logo(r.get('home', ''))
                away_logo = _team_logo(r.get('away', ''))
                home_img = f'<img class="rl-logo" src="{home_logo}" alt="" loading="lazy" onerror="this.style.display=\'none\'">' if home_logo else ''
                away_img = f'<img class="rl-logo" src="{away_logo}" alt="" loading="lazy" onerror="this.style.display=\'none\'">' if away_logo else ''
            else:
                home_img = ''
                away_img = ''

            # Флаги для сборных в результатах
            _rh_info = _TEAM_LOGOS.get(r.get('home', ''), {})
            _ra_info = _TEAM_LOGOS.get(r.get('away', ''), {})
            rf_h = _rh_info.get('flag', '') if isinstance(_rh_info, dict) else ''
            rf_a = _ra_info.get('flag', '') if isinstance(_ra_info, dict) else ''
            home_disp_res = f'{rf_h} {home}' if rf_h else home
            away_disp_res = f'{rf_a} {away}' if rf_a else away

            html += f'''
                <div class="result-card">
                    <div class="rc-row"><span class="rc-left">{home_img}<span class="rc-name">{home_disp_res}</span></span><span class="rc-sc">{home_score}</span></div>
                    <div class="rc-row rc-row-away"><span class="rc-left">{away_img}<span class="rc-name">{away_disp_res}</span></span><span class="rc-sc">{away_score}</span></div>
                </div>'''

    html += '</div>'
    return html


# ─── UPCOMING MATCHES ────────────────────────────────────────────────
def get_upcoming(target_date=None):
    """Предстоящие матчи из JSON (tv_channels + прогнозные матчи).
    Использует накопительное хранилище (storage.py).
    Принимает дату в любом формате (dd.mm.yyyy, YYYY-MM-DD, YYYYmmdd).
    """
    import storage as _st
    from date_utils import normalize_date
    matches = []

    if target_date:
        target_date = normalize_date(target_date)
    else:
        target_date = ''

    # 1. Из tv_channels_data.json (все спортивные матчи)
    tv_matches = _st.get_matches_for_date('/tmp/tv_channels_data.json', target_date)
    matches.extend(tv_matches)

    # 2. Из upcoming_matches.json (футбольные матчи для прогнозов)
    up_matches = _st.get_matches_for_date('/tmp/upcoming_matches.json', target_date)
    seen_keys = {(m.get('league',''), m.get('home',''), m.get('away','')) for m in matches}
    for m in up_matches:
        key = (m.get('league',''), m.get('home',''), m.get('away',''))
        if key not in seen_keys:
            seen_keys.add(key)
            matches.append({
                'sport': 'football',
                'league': m.get('league', '?'),
                'home': m.get('home', '?'),
                'away': m.get('away', '?'),
                'time': m.get('time', '?'),
            })

    return matches


# ─── MATCH TV GUIDE ──────────────────────────────────────────────────
def get_tvguide_section():
    """ТВ-программа Матч ТВ на сегодня."""
    channels = fetch_tvguide()
    sport = find_sport_broadcasts(channels)

    if not sport:
        return ''

    rows = []
    for s in sport[:20]:
        emoji = '⚽' if 'футбол' in s['title'].lower() else '🏒' if 'хоккей' in s['title'].lower() else '🏀' if 'баскет' in s['title'].lower() else '🎾' if 'теннис' in s['title'].lower() else '📺'
        rows.append(f'<tr><td class="time">{s["time"]}</td><td class="ch">{s["channel"]}</td><td>{emoji} {html_mod.escape(s["title"])}</td></tr>')

    return ''.join(rows)


# ─── HTML GENERATION ─────────────────────────────────────────────────
def escape(s):
    return html_mod.escape(str(s))


def _load_content_cache():
    """Загрузить кеш полных текстов из прошлого news_data.json."""
    path = '/var/www/sport/news_data.json'
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        result = {}
        for item in data:
            link = item.get('link', '')
            if item.get('content'):
                result[link] = item.get('content', '')
            if item.get('content_ru'):
                result[link + '::ru'] = item.get('content_ru', '')
        return result
    except:
        return {}


def _load_live_scores():
    """Загрузить live-счета из /tmp/live_scores_data.json.
    Возвращает dict match_key → {status, score}.
    """
    path = '/tmp/live_scores_data.json'
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return data.get('matches', {})
    except:
        return {}


def _render_match_card(m, live_lookup, predictions_by_match, logo_leagues, show_predictions=True):
    """Сгенерировать HTML карточки матча с учётом статуса.
    m — словарь матча (home, away, league, time)
    live_lookup — из live_scores_data.json
    predictions_by_match — из predictions_data.json
    """
    league = m.get('league', '')
    home = m.get('home', '?')
    away = m.get('away', '?')
    match_key = f'{league}||{home}||{away}'
    live_info = live_lookup.get(match_key, {})
    status = live_info.get('status', 'upcoming')
    score = live_info.get('score')

    # Экранирование и флаги
    home_e = escape(home)
    away_e = escape(away)
    _team_info_h = _TEAM_LOGOS.get(home, {})
    _team_info_a = _TEAM_LOGOS.get(away, {})
    home_flag = _team_info_h.get('flag', '') if isinstance(_team_info_h, dict) else ''
    away_flag = _team_info_a.get('flag', '') if isinstance(_team_info_a, dict) else ''
    home_display = f'{home_flag} {home_e}' if home_flag else home_e
    away_display = f'{away_flag} {away_e}' if away_flag else away_e

    # Логотипы
    home_logo = _team_logo(home)
    away_logo = _team_logo(away)
    h_logo = f'<img class="rl-logo" src="{home_logo}" alt="" loading="lazy" onerror="this.style.display=\'none\'">' if home_logo and league in logo_leagues else ''
    a_logo = f'<img class="rl-logo" src="{away_logo}" alt="" loading="lazy" onerror="this.style.display=\'none\'">' if away_logo and league in logo_leagues else ''

    channels = m.get('channels', [])
    ch_str = ' | '.join(c['channel'] for c in channels[:3]) if channels else ''

    has_pred = (league, home, away) in predictions_by_match
    match_key = f'{league}||{home}||{away}'

    # ---- Right panel: time / live / score ----
    time_str = m.get('time', '?')
    time_str = re.sub(r'^\d{2}\.\d{2}\.\s*', '', time_str)

    if status == 'live':
        right_html = f'''
            <div class="up-v1-right">
                <div class="up-v1-live-badge">▶ LIVE</div>
                <div class="up-v1-score">{score or '\u2013'}</div>
            </div>'''
    elif status == 'finished':
        score_html = ''
        if score and ':' in score:
            parts = score.split(':', 1)
            score_html = f'<div class="up-v1-score-home">{parts[0]}</div><div class="up-v1-score-away">{parts[1]}</div>'
        else:
            score_html = f'<div class="up-v1-score-home">{score or "\u2013"}</div>'
        right_html = f'''
            <div class="up-v1-right">
                {score_html}
            </div>'''
    else:
        if show_predictions and has_pred:
            pred_class = 'up-v1-predict-btn'
            pred_data_attrs = f'onclick="openPrediction(\'{league}\',\'{home}\',\'{away}\')" data-league="{league}" data-home="{home}" data-away="{away}"'
        else:
            pred_class = 'up-v1-predict-btn up-v1-predict-off'
            pred_data_attrs = ''
        right_html = f'''
            <div class="up-v1-right">
                <div class="up-v1-time">{time_str}</div>
                <div class="{pred_class}" {pred_data_attrs}>Прогноз</div>
            </div>'''

    card_attrs = ''
    if status == 'live':
        card_attrs = f' data-match-key="{match_key}" onclick="openStats(this.dataset.matchKey)" style="cursor:pointer"'
    html = f'''
        <div class="up-card up-card-v1"{card_attrs}>
            <div class="up-v1-grid">
                <div class="up-v1-left">
                    <div class="up-v1-row">
                        <span class="up-v1-team-row">{h_logo}<span class="up-v1-name">{home_display}</span></span>
                    </div>
                    <div class="up-v1-row up-v1-row-away">
                        <span class="up-v1-team-row">{a_logo}<span class="up-v1-name">{away_display}</span></span>
                    </div>'''
    if ch_str:
        html += f'<div class="up-v1-tv">{ch_str}</div>'
    html += f'''
                </div>
                {right_html}
            </div>
        </div>'''
    return html


def generate():
    from date_utils import format_date_display, today_display, tomorrow_display, yesterday_storage
    now = datetime.now(UTC) + MOW
    now_str = format_date_display(now) + ' ' + now.strftime('%H:%M')

    # Загружаем кеш контента из предыдущей генерации
    content_cache = _load_content_cache()
    news = fetch_news(content_cache)

    # Live-счета
    live_lookup = _load_live_scores()

    # Дата сегодня и завтра
    today_date = today_display()
    next_date = tomorrow_display()
    yesterday_date = format_date_display(yesterday_storage())

    # ── Результаты: daily_results + finished из live_scores ──
    results = get_results_text(live_lookup)

    # ── Сегодня: live-матчи + предстоящие на сегодня ──
    today_matches = []
    seen_today = set()

    # Добавляем live из live_scores
    if live_lookup:
        for key, info in live_lookup.items():
            if info.get('status') in ('live', 'upcoming'):
                parts = key.split('||', 2)
                if len(parts) == 3:
                    league, home, away = parts
                    dedup = (league, home, away)
                    if dedup not in seen_today:
                        seen_today.add(dedup)
                        time_str = info.get('match_time', '') or info.get('status_detail', '')
                        today_matches.append({
                            'sport': info.get('sport', 'football'),
                            'league': league,
                            'home': home,
                            'away': away,
                            'time': time_str,
                        })

    # Добавляем upcoming из tv_channels (которые ещё не в seen)
    upcoming_today = get_upcoming(target_date=today_date)
    for m in upcoming_today:
        dedup = (m.get('league', ''), m.get('home', ''), m.get('away', ''))
        if dedup not in seen_today:
            seen_today.add(dedup)
            today_matches.append(m)

    # ── Завтра: предстоящие матчи ──
    upcoming_matches = get_upcoming(target_date=next_date)

    tvguide_rows = get_tvguide_section()

    # Загружаем прогнозы
    predictions_by_match = {}
    pred_path = '/opt/predictions_data.json'
    if os.path.exists(pred_path):
        try:
            with open(pred_path, encoding='utf-8') as f:
                pred_data = json.load(f)
            for p in pred_data.get('predictions', []):
                key = (p.get('league', ''), p.get('home', ''), p.get('away', ''))
                predictions_by_match[key] = p
        except: pass

    # ── Save full news as JSON (с content для модалки) ──
    news_json_path = '/var/www/sport/news_data.json'
    news_clean = []
    for n in news:
        content = n.get('content', '')
        news_clean.append({
            'title': n['title'],
            'desc': n['desc'],
            'desc_full': n.get('desc_full', ''),
            'link': n['link'],
            'source': n['source'],
            'image': n.get('image', ''),
            'time': n['time'],
            'ts': n['ts'],
            'content': content,
            'content_ru': n.get('content_ru', ''),
        })
    try:
        with open(news_json_path, 'w', encoding='utf-8') as f:
            json.dump(news_clean, f, ensure_ascii=False)
    except Exception as e:
        print(f'⚠️ Не удалось сохранить news_data.json: {e}')

    # ── Экранирование для встраивания в JavaScript (JSON) ──
    news_json_escaped = json.dumps(news_clean, ensure_ascii=False)

    # Подготавливаем прогнозы для JS (ключи-кортежи → строки) + логотипы
    pred_json_escaped = json.dumps(
        {k[0] + '||' + k[1] + '||' + k[2]: {
            **v,
            'home_logo': _team_logo(k[1]),
            'away_logo': _team_logo(k[2]),
        } for k, v in predictions_by_match.items()},
        ensure_ascii=False, default=str
    )

    # ── News block (первые 15 в HTML, остальные подгружаются из JSON) ──
    news_html = ''
    for i, n in enumerate(news[:15]):
        img_src = n.get('image')
        news_html += f'''
        <div class="news-card" data-news-idx="{i}" onclick="openArticle({i})">
            <div class="news-row">'''
        if img_src:
            news_html += f'''
                <div class="news-img"><img src="{escape(img_src)}" alt="" loading="lazy" onerror="this.closest('.news-row').classList.add('no-img');this.remove()"></div>'''
        news_html += f'''
                <div class="news-body">
                    <div class="news-meta">
                        <span class="news-source">{escape(n['source'])}</span>
                        <span class="news-time">{escape(n['time'])}</span>
                    </div>
                    <div class="news-title">{escape(n['title'])}</div>
                    <div class="news-desc">{escape(n['desc'])}</div>
                </div>
            </div>
        </div>'''

    # Контейнер для подгружаемых новостей + кнопка
    more_news_count = len(news) - 15
    if more_news_count > 0:
        news_html += f'''
        <div id="news-more-container"></div>
        <button id="news-more-btn" class="more-btn" onclick="loadMoreNews()">Показать ещё</button>'''

    # ── Results block ──
    results_html = results  # get_results_text() уже возвращает HTML-строку

    # ── Matches sections: today and tomorrow ──
    logo_leagues = {'АПЛ', 'Ла Лига', 'Серия А', 'Бундеслига', 'Лига 1', 'РПЛ', 'НХЛ', 'NBA'}
    emoji_map = {'football': '⚽', 'hockey': '🏒', 'basketball': '🏀', 'tennis': '🎾'}
    logo_urls = {
        'АПЛ': '/static/leagues/апл.png',
        'Ла Лига': '/static/leagues/ла-лига.png',
        'Серия А': '/static/leagues/серия-а.png',
        'Бундеслига': '/static/leagues/бундеслига.png',
        'Лига 1': '/static/leagues/лига-1.png',
        'РПЛ': '/static/leagues/рпл.png',
        'НХЛ': '/static/leagues/нхл.png',
        'NBA': '/static/leagues/nba.png',
    }

    def _section_matches(matches, show_predictions=True):
        html = '<div class="card-grid">'
        prev_sport = ''
        for m in matches:
            if m.get('sport') == 'tennis' and m.get('home', '') == 'TBD' and m.get('away', '') == 'TBD':
                continue
            league = m.get('league', '')
            if league != prev_sport:
                logo_url = logo_urls.get(league, '')
                if logo_url:
                    logo_html = f'<img class="league-logo" src="{logo_url}" alt="" loading="lazy">'
                    html += f'<div class="section-sub">{logo_html} {escape(league)}</div>'
                else:
                    emoji = emoji_map.get(m.get('sport', ''), '📺')
                    html += f'<div class="section-sub">{emoji} {escape(league)}</div>'
                prev_sport = league
            html += _render_match_card(m, live_lookup, predictions_by_match, logo_leagues, show_predictions)
        html += '</div>'
        return html

    # Сегодня — матчи с live счетами
    today_html = _section_matches(today_matches, show_predictions=True)
    
    # Завтра — предстоящие матчи с прогнозами
    upcoming_html = _section_matches(upcoming_matches, show_predictions=True)

    # ── Match TV guide ──
    tv_html = ''
    if tvguide_rows:
        tv_html = f'''
        <div class="section-title">📺 Матч ТВ — программа</div>
        <table class="compact-table">{tvguide_rows}</table>
        <div class="source-note">Источник: matchtv.ru</div>'''

    # ── Assemble HTML ──
    html = f'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="300">
<title>Zula Спорт</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0f0f0f;
    color: #e0e0e0;
    line-height: 1.5;
}}
a {{ color: inherit; text-decoration: none; }}
.container {{ max-width: 800px; margin: 0 auto; padding: 16px; }}

/* Header */
.header {{
    display: flex; align-items: center; justify-content: space-between;
    padding: 20px 0 16px; border-bottom: 1px solid #2a2a2a; margin-bottom: 24px;
}}
.header h1 {{ font-size: 24px; font-weight: 700; color: #00e676; }}
.header h1 span {{ color: #e0e0e0; }}
.header .update {{ font-size: 13px; color: #888; }}
.nav {{ display: flex; gap: 16px; padding: 12px 0; flex-wrap: wrap; }}
.nav a {{
    color: #888; font-size: 14px; padding: 4px 0;
    border-bottom: 2px solid transparent; transition: 0.2s;
}}
.nav a:hover, .nav a.active {{ color: #00e676; border-color: #00e676; }}

/* News */
.news-card {{
    display: block; margin-bottom: 12px;
    background: #1a1a1a; border-radius: 10px;
    border: 1px solid #2a2a2a; transition: 0.2s;
}}
.news-card:hover {{ border-color: #00e676; background: #1e1e1e; }}
.news-row {{
    display: flex; gap: 14px; padding: 14px;
}}
.news-img {{
    flex-shrink: 0; width: 120px; height: 80px;
    border-radius: 8px; overflow: hidden;
}}
.news-row.no-img .news-img {{
    display: none;
}}
.news-row.no-img {{
    gap: 0;
}}
.news-img img {{
    width: 100%; height: 100%; object-fit: cover;
}}

.news-body {{
    flex: 1; min-width: 0;
}}
.news-meta {{ display: flex; justify-content: space-between; font-size: 12px; color: #888; margin-bottom: 6px; }}
.news-source {{ color: #00e676; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; font-size: 11px; }}
.news-time {{ color: #666; }}
.news-title {{ font-size: 16px; font-weight: 600; margin-bottom: 4px; color: #fff; }}
.news-desc {{ font-size: 14px; color: #999; }}

/* Sections */
.section-title {{
    font-size: 18px; font-weight: 700; margin: 24px 0 12px;
    padding-bottom: 8px; border-bottom: 1px solid #2a2a2a;
}}
.section-sub {{
    font-size: 15px; font-weight: 600; margin: 16px 0 8px; color: #aaa;
    display: flex; align-items: center; gap: 6px;
}}
.league-logo {{
    width: 18px; height: 18px; object-fit: contain;
    flex-shrink: 0;
}}

/* Tables */
.compact-table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
.compact-table tr {{ border-bottom: 1px solid #1e1e1e; }}
.compact-table td {{ padding: 8px 6px; }}
.compact-table td.time {{ color: #888; white-space: nowrap; width: 60px; }}
.compact-table td.ch {{ color: #00e676; white-space: nowrap; width: 100px; font-size: 12px; }}

/* Match rows */
.match-row {{
    padding: 8px 0; border-bottom: 1px solid #1e1e1e;
    font-size: 14px;
}}
.match-row .time {{ color: #888; margin-right: 8px; }}
.match-row .tv {{ font-size: 12px; color: #ff9800; margin-left: 8px; }}

/* Upcoming card: Стиль 1 */
.up-card {{
    margin-bottom: 10px; border-radius: 12px; padding: 10px 14px;
}}
.up-card-v1 {{
    background: linear-gradient(135deg, #1a2a3a, #1a1a1a);
    border: 1px solid #2a3a4a;
}}
.up-v1-grid {{
    display: flex; gap: 14px;
}}
.up-v1-left {{
    flex: 1; min-width: 0;
}}
.up-v1-right {{
    display: flex; flex-direction: column; align-items: center;
    justify-content: center; gap: 6px;
    flex-shrink: 0;
}}
.up-v1-row {{
    padding: 4px 0;
}}
.up-v1-row-away {{
    margin-top: 2px; padding-top: 6px;
}}
.up-v1-team-row {{
    display: flex; align-items: center; gap: 6px;
}}
.up-v1-name {{
    font-size: 14px; font-weight: 600; color: #fff;
}}
.up-v1-time {{
    font-size: 22px; font-weight: 800; color: #888;
    font-variant-numeric: tabular-nums;
    text-align: center;
}}
.up-v1-predict-btn {{
    font-size: 11px; font-weight: 600; color: #00e676;
    background: rgba(0,230,118,0.1);
    border: 1px solid rgba(0,230,118,0.3);
    border-radius: 6px; padding: 4px 12px;
    cursor: pointer; transition: 0.2s;
    text-transform: uppercase; letter-spacing: 1px;
}}
.up-v1-predict-btn:hover {{
    background: rgba(0,230,118,0.2);
    border-color: #00e676;
}}
.up-v1-predict-off {{
    color: #555 !important;
    background: rgba(255,255,255,0.05) !important;
    border-color: #333 !important;
    cursor: default !important;
    pointer-events: none;
}}
.up-v1-tv {{
    margin-top: 6px; font-size: 12px; color: #ff9800;
    padding-top: 6px; border-top: 1px solid #2a3a4a;
}}

/* Live badge */
.up-v1-live-badge {{
    font-size: 11px; font-weight: 800; color: #fff;
    background: #e53935; border-radius: 4px; padding: 2px 8px;
    text-transform: uppercase; letter-spacing: 1px;
    animation: livePulse 1.5s ease-in-out infinite;
}}
@keyframes livePulse {{
    0%, 100% {{ opacity: 1; }}
    50% {{ opacity: 0.6; }}
}}

/* Grid: 2 колонки на десктопе */
.card-grid {{
    display: block;
}}
@media (min-width: 768px) {{
    .card-grid {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 10px;
    }}
    .card-grid .section-sub {{
        grid-column: 1 / -1;
        margin-bottom: 4px;
    }}
    .card-grid .up-card,
    .card-grid .result-card {{
        margin-bottom: 0;
    }}
}}

/* Live / finished score */
.up-v1-score {{
    font-size: 22px; font-weight: 800; color: #fff;
    font-variant-numeric: tabular-nums;
    text-align: center;
}}
.up-v1-score.finished {{
    color: #00e676;
}}

/* Vertical score for finished */
.up-v1-score-home {{
    font-size: 22px; font-weight: 800; color: #00e676;
    font-variant-numeric: tabular-nums;
    text-align: center;
}}
.up-v1-score-away {{
    font-size: 22px; font-weight: 800; color: #00e676;
    font-variant-numeric: tabular-nums;
    text-align: center;
    margin-top: -2px;
}}

/* Карточка результата (стиль 1) */
.result-card {{
    background: linear-gradient(135deg, #1a3a1a, #1a1a1a);
    border: 1px solid #2a4a2a;
    border-radius: 12px;
    padding: 10px 14px;
    margin-bottom: 8px;
}}
.rc-row {{
    display: flex; align-items: center; justify-content: space-between;
    padding: 4px 0;
}}
.rc-row-away {{
    border-top: 1px solid #2a4a2a;
    margin-top: 4px;
    padding-top: 8px;
}}
.rc-left {{
    display: flex; align-items: center; gap: 6px;
}}
.rc-name {{
    font-size: 14px; font-weight: 600; color: #fff;
}}
.rc-sc {{
    font-size: 18px; font-weight: 800; color: #00e676;
    font-variant-numeric: tabular-nums;
}}
.rl-logo {{
    width: 20px; height: 20px; object-fit: contain;
    flex-shrink: 0;
}}
.rc-games {{
    font-size: 14px; color: #fff; font-weight: 500;
    font-variant-numeric: tabular-nums;
    letter-spacing: 3px;
    flex: 1; text-align: right;
    margin-right: 12px;
}}

/* TV guide */
.source-note {{ font-size: 11px; color: #555; margin-top: 8px; text-align: right; }}

/* Footer */
.footer {{
    margin-top: 32px; padding: 20px 0; border-top: 1px solid #2a2a2a;
    text-align: center; font-size: 13px; color: #666;
}}
.footer a {{ color: #00e676; }}
.footer .bot-link {{ display: inline-block; margin-top: 8px;
    padding: 8px 20px; background: #00e676; color: #000;
    border-radius: 20px; font-weight: 600; font-size: 14px;
}}

/* Responsive */
/* ─── Mobile responsive ────────────────────────────────────── */
@media (max-width: 640px) {{
    .container {{ padding: 10px; }}
    .header {{ flex-direction: column; align-items: flex-start; gap: 6px; padding: 14px 0 12px; }}
    .header h1 {{ font-size: 20px; }}
    .header .update {{ font-size: 11px; }}
    .nav {{ gap: 10px; padding: 8px 0; }}
    .nav a {{ font-size: 13px; padding: 4px 2px; }}
    .section-title {{ font-size: 16px; margin: 18px 0 10px; }}
    .section-sub {{ font-size: 13px; margin: 12px 0 6px; }}

    /* Upcoming cards */
    .up-card {{ padding: 8px 10px; }}
    .up-v1-grid {{ gap: 8px; }}
    .up-v1-name {{ font-size: 16px; }}
    .up-v1-time {{ font-size: 16px; }}
    .up-v1-score {{ font-size: 16px; }}
    .up-v1-score-home {{ font-size: 16px; }}
    .up-v1-score-away {{ font-size: 16px; }}
    .up-v1-predict-btn {{ font-size: 10px; padding: 3px 8px; }}
    .up-v1-tv {{ font-size: 11px; }}
    .rl-logo {{ width: 16px; height: 16px; }}

    /* Results */
    .result-card {{ padding: 8px 10px; }}
    .rc-sc {{ font-size: 16px; }}
    .rc-name {{ font-size: 16px; }}
    .rc-name {{ font-size: 16px; }}

    /* News */
    .news-row {{ flex-direction: column; padding: 10px; }}
    .news-img {{ width: 100%; height: 140px; }}
    .news-title {{ font-size: 15px; }}
    .news-desc {{ font-size: 13px; }}
    .news-body {{ padding: 0; }}

    /* TV guide */
    .compact-table {{ font-size: 12px; }}
    .compact-table td {{ padding: 6px 4px; }}
    .compact-table td.ch {{ font-size: 10px; width: 70px; }}

    /* Modal */
    .modal-overlay {{ padding: 0; align-items: flex-end; }}
    .modal-card {{ border-radius: 14px 14px 0 0; max-width: 100%; }}
    .modal-body {{ padding: 14px; font-size: 14px; max-height: 70vh; }}
    .modal-header {{ padding: 12px 14px; }}
    .modal-footer {{ padding: 10px 14px; }}

    /* Footer */
    .footer {{ font-size: 12px; padding: 14px 0; }}
}}

.more-btn {{
    display: block; width: 100%; padding: 12px; margin: 16px 0;
    background: #1a1a1a; border: 1px solid #333; border-radius: 10px;
    color: #00e676; font-size: 15px; font-weight: 600;
    cursor: pointer; transition: 0.2s;
}}
.more-btn:hover {{ background: #222; border-color: #00e676; }}

/* Scrollbar */
::-webkit-scrollbar {{ width: 6px; }}
::-webkit-scrollbar-track {{ background: #0f0f0f; }}
::-webkit-scrollbar-thumb {{ background: #333; border-radius: 3px; }}

/* Modal for article reading */
.modal-overlay {{
    display: none; position: fixed; inset: 0; z-index: 1000;
    background: rgba(0,0,0,0.85); backdrop-filter: blur(4px);
    justify-content: center; align-items: flex-start; overflow-y: auto;
    padding: 40px 16px;
}}
.modal-overlay.active {{ display: flex; }}
.modal-card {{
    background: #1a1a1a; border-radius: 14px; max-width: 720px; width: 100%;
    border: 1px solid #2a2a2a; overflow: hidden;
    animation: modalIn 0.25s ease;
}}
@keyframes modalIn {{
    from {{ opacity: 0; transform: translateY(24px); }}
    to {{ opacity: 1; transform: translateY(0); }}
}}
.modal-header {{
    display: flex; align-items: center; justify-content: space-between;
    padding: 16px 20px; border-bottom: 1px solid #2a2a2a;
    position: sticky; top: 0; background: #1a1a1a; z-index: 1;
}}
.modal-header-left {{ display: flex; flex-direction: column; gap: 4px; }}
.modal-close {{
    width: 32px; height: 32px; border-radius: 50%; border: none;
    background: #333; color: #ccc; font-size: 18px; cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    transition: 0.2s; flex-shrink: 0;
}}
.modal-close:hover {{ background: #555; color: #fff; }}
.modal-body {{
    padding: 20px; line-height: 1.75; font-size: 15px;
    color: #ccc; overflow-y: auto; max-height: 65vh;
}}
.modal-body p {{ margin-bottom: 14px; }}
.modal-body h2, .modal-body h3, .modal-body h4 {{ color: #fff; margin: 20px 0 10px; }}
.modal-body img {{ max-width: 100%; height: auto; border-radius: 8px; margin: 14px 0; }}
.modal-body a {{ color: #00e676; text-decoration: underline; }}
.modal-body ul, .modal-body ol {{ margin: 10px 0; padding-left: 24px; }}
.modal-body li {{ margin-bottom: 6px; }}
.modal-body blockquote {{
    border-left: 3px solid #00e676; padding: 8px 14px; margin: 14px 0;
    background: rgba(0,230,118,0.05); border-radius: 0 8px 8px 0;
    color: #aaa;
}}
.modal-body .news-desc {{
    font-size: 13px; color: #888; margin-bottom: 16px;
    padding-bottom: 16px; border-bottom: 1px solid #2a2a2a;
}}
.modal-footer {{
    display: flex; align-items: center; justify-content: space-between;
    padding: 12px 20px; border-top: 1px solid #2a2a2a;
}}
.modal-footer a {{
    color: #00e676; font-size: 13px; font-weight: 600;
    transition: 0.2s; padding: 6px 12px; border-radius: 6px;
}}
.modal-footer a:hover {{ background: rgba(0,230,118,0.1); }}

/* ── Stats Modal ── */
.stats-live {{
    font-size: 10px; font-weight: 800; color: #e53935;
    text-align: center; text-transform: uppercase; letter-spacing: 1px;
    animation: pulse 1.5s ease-in-out infinite; margin-bottom: 4px;
}}
.stats-header {{
    display: flex; align-items: center; justify-content: center; gap: 10px;
    padding-bottom: 14px; border-bottom: 1px solid #2a3a4a; margin-bottom: 14px;
}}
.stats-team {{
    flex: 1; font-size: 15px; font-weight: 700; color: #fff; text-align: center;
}}
.stats-score {{
    font-size: 26px; font-weight: 800; color: #fff; font-variant-numeric: tabular-nums;
    text-align: center; flex-shrink: 0; min-width: 50px;
}}
.stats-table {{
    width: 100%; border-collapse: collapse;
}}
.stats-table td {{
    padding: 6px 6px; font-size: 13px;
}}
.stats-table .stat-home {{
    text-align: right; font-weight: 700; color: #fff; width: 20%;
}}
.stats-table .stat-name {{
    text-align: center; color: #888; width: 60%; font-size: 12px;
}}
.stats-table .stat-away {{
    text-align: left; font-weight: 700; color: #fff; width: 20%;
}}
.stats-table tr:nth-child(even) {{
    background: rgba(255,255,255,0.03);
}}
.percent-row td {{
    padding: 8px 6px 2px !important;
}}
.percent-label {{
    font-size: 11px; color: #888; text-align: center; margin-bottom: 4px;
}}
.percent-bars {{
    display: flex; align-items: center; gap: 8px; justify-content: center;
}}
.percent-val {{
    font-size: 12px; font-weight: 700; color: #fff; min-width: 32px; text-align: center;
}}
.percent-track {{
    flex: 1; height: 6px; background: #2a3a4a; border-radius: 3px;
    overflow: hidden; display: flex; max-width: 180px;
}}
.percent-home {{
    height: 100%; background: #00e676;
}}
.percent-away {{
    height: 100%; background: #00bcd4;
}}
</style>
</head>
<body>
<div class="container">

    <div class="header">
        <div>
            <h1>🌀 Zula <span>Спорт</span></h1>
            <div class="update">Обновлено: {now_str} МСК</div>
        </div>
    </div>

    <div class="nav" id="nav">
        <a href="#news" class="active">Новости</a>
        <a href="#results">Результаты</a>
        <!-- <a href="#today">Эфир</a> -->
        <a href="#upcoming">Матчи</a>
        <!-- <a href="#tv">ТВ-гид</a> -->
    </div>

    <div id="news" class="section-title">📰 Последние новости</div>
    {news_html}

    <div id="results" class="section-title">📊 Результаты за {yesterday_date}</div>
    {results_html}
    {'' if results_html else '<p style="color:#666;font-size:14px">Загрузка результатов...</p>'}

    <div id="today-matches" class="section-title">📅 Сегодня — {today_date}</div>
    {today_html}
    {'' if today_html else '<p style="color:#666;font-size:14px">Нет данных на сегодня.</p>'}

    <div id="upcoming" class="section-title">📅 Завтра — {next_date}</div>
    {upcoming_html}
    {'' if upcoming_html else '<p style="color:#666;font-size:14px">Нет данных на ближайшее время.</p>'}

    <!-- <div id="tv" class="section-title">📺 ТВ-программа Матч ТВ</div>
    {tv_html}
    {'' if tv_html else '<p style="color:#666;font-size:14px">Загрузка программы...</p>'} -->

    <div class="footer">
        <p>🌀 Zula Спорт — автоматический агрегатор новостей и расписания</p>
        <p>Данные: BBC, Sky Sports, Guardian, Чемпионат, Sports.ru, Матч ТВ</p>
        <a href="https://t.me/ZulaSportNews_bot" class="bot-link" target="_blank">📱 Бот в Telegram</a>
    </div>

</div>

<!-- Article Modal -->
<div id="article-modal" class="modal-overlay">
    <div class="modal-card">
        <div class="modal-header">
            <div class="modal-header-left">
                <span id="modal-source" class="news-source" style="text-transform:uppercase;letter-spacing:0.5px;font-size:11px"></span>
                <span id="modal-time" class="news-time" style="font-size:12px"></span>
            </div>
            <button class="modal-close" onclick="closeArticle()">✕</button>
        </div>
        <div id="modal-body" class="modal-body"></div>
        <div class="modal-footer">
            <span></span>
            <a id="modal-source-link" href="#" target="_blank" rel="noopener">Читать в источнике →</a>
        </div>
    </div>
</div>

<!-- Prediction Modal -->
<div id="pred-modal" class="modal-overlay">
    <div class="modal-card">
        <div class="modal-header">
            <div class="modal-header-left">
                <span id="pred-league" class="news-source" style="text-transform:uppercase;letter-spacing:0.5px;font-size:11px;color:#ffd700"></span>
                <span id="pred-teams" style="font-size:14px;font-weight:600;color:#fff"></span>
            </div>
            <button class="modal-close" onclick="closePrediction()">✕</button>
        </div>
        <div id="pred-body" class="modal-body"></div>
        <div class="modal-footer">
            <span></span>
        </div>
    </div>
</div>

<!-- Stats Modal -->
<div id="stats-modal" class="modal-overlay">
    <div class="modal-card" style="max-width:480px">
        <div class="modal-header" style="border-bottom:none;padding:16px 16px 0;justify-content:flex-end">
            <button class="modal-close" onclick="closeStats()">✕</button>
        </div>
        <div style="padding:0 20px 20px">
            <div class="stats-live">▶ LIVE</div>
            <div class="stats-header" id="stats-header">
                <div class="stats-team" id="stats-home-team"></div>
                <div class="stats-score" id="stats-score"></div>
                <div class="stats-team" id="stats-away-team"></div>
            </div>
            <table class="stats-table" id="stats-body"></table>
        </div>
    </div>
</div>

<script id="news-data" type="application/json">{news_json_escaped}</script>
<script id="pred-data" type="application/json">{pred_json_escaped}</script>

<script>
// ─── Article Modal ────────────────────────────────────────────────
const ARTICLE_DATA = (function() {{
    try {{ return JSON.parse(document.getElementById('news-data').textContent); }} catch(e) {{ return []; }}
}})();

function escapeHtml(str) {{
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}}

function openArticle(idx) {{
    const article = ARTICLE_DATA[idx];
    if (!article) return;

    let bodyHtml = '';
    if (article.content_ru) {{
        // Переведённый текст → разбиваем на абзацы
        const paragraphs = article.content_ru.split('\\n').filter(function(p) {{ return p.trim(); }});
        bodyHtml = '';
        bodyHtml += paragraphs.map(function(p) {{ return '<p>' + escapeHtml(p.trim()) + '</p>'; }}).join('');
        bodyHtml += '<p style="color:#555;font-size:12px;margin-top:16px;border-top:1px solid #2a2a2a;padding-top:12px">🌐 Перевод с оригинала</p>';
    }} else if (article.content) {{
        bodyHtml = article.content;
    }} else {{
        bodyHtml = `<p>${{escapeHtml(article.desc)}}</p>`;
        if (article.desc && article.desc.length < 100) {{
            bodyHtml += '<p style="color:#666;margin-top:12px;font-size:13px">⚠️ Полный текст временно недоступен</p>';
        }}
    }}

    document.getElementById('modal-source').textContent = article.source;
    document.getElementById('modal-time').textContent = article.time;
    document.getElementById('modal-body').innerHTML = bodyHtml;
    // Скрываем битые изображения
    document.getElementById('modal-body').querySelectorAll('img').forEach(function(img) {{
        img.onerror = function() {{ this.style.display = 'none'; }};
    }});
    document.getElementById('modal-source-link').href = article.link;
    document.getElementById('article-modal').classList.add('active');
    document.body.style.overflow = 'hidden';
}}

function closeArticle() {{
    document.getElementById('article-modal').classList.remove('active');
    document.body.style.overflow = '';
}}

// Close on overlay click
document.getElementById('article-modal').addEventListener('click', function(e) {{
    if (e.target === this) closeArticle();
}});

// Close on Escape
document.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') closeArticle();
}});

// ─── Prediction Modal ────────────────────────────────────────────
const PRED_DATA = (function() {{
    try {{ return JSON.parse(document.getElementById('pred-data').textContent); }} catch(e) {{ return {{}}; }}
}})();

function openPrediction(league, home, away) {{
    const key = league + '||' + home + '||' + away;
    const pred = PRED_DATA[key];
    if (!pred) return;

    // Определяем вариант дизайна по порядку матча
    const matchKeys = Object.keys(PRED_DATA);
    const matchIdx = matchKeys.indexOf(key);
    const variant = 4; // всегда 5-й вариант

    document.getElementById('pred-league').innerHTML = (new Map([['АПЛ','🇬🇧'],['Ла Лига','🇪🇸'],['Серия А','🇮🇹'],['Бундеслига','🇩🇪'],['Лига 1','🇫🇷'],['РПЛ','🇷🇺']]).get(pred.league) || '⚽') + ' ' + pred.league;
    document.getElementById('pred-teams').innerHTML = '<div>' + (pred.home_logo ? '<img src="' + pred.home_logo + '" style="width:18px;height:18px;vertical-align:middle;margin-right:6px">' : '') + '<span style="vertical-align:middle;font-size:16px;color:#fff">' + pred.home + '</span></div><div style="margin-top:2px">' + (pred.away_logo ? '<img src="' + pred.away_logo + '" style="width:18px;height:18px;vertical-align:middle;margin-right:6px">' : '') + '<span style="vertical-align:middle;font-size:16px;color:#ccc">' + pred.away + '</span></div><div style="font-size:11px;color:#888;margin-top:6px">' + (pred.time || '') + ', 16 мая</div>';

    let h = '';
    h = renderV5(pred);

    document.getElementById('pred-body').innerHTML = h;
    document.getElementById('pred-modal').classList.add('active');
    document.body.style.overflow = 'hidden';
}}

// ─── Вариант 1: Текущий (классический) ─────────────────────────────
function renderV1(pred) {{
    let h = '';
    h += '<div style="background:linear-gradient(135deg,#1e3a1e,#2a5a2a);border-radius:12px;padding:16px;text-align:center;margin-bottom:16px">';
    h += '<div style="font-size:20px;font-weight:700;color:#00e676">' + escapeHtml(pred.home) + ' — ' + escapeHtml(pred.away) + '</div>';
    if (pred.glicko) {{
        h += '<div style="margin-top:10px;display:flex;gap:6px;font-size:12px">';
        h += '<div style="flex:1;background:rgba(0,0,0,0.3);border-radius:6px;padding:6px;color:#aaa"><div>' + escapeHtml(pred.home) + '</div><div style="font-size:16px;font-weight:700;color:#fff">' + Math.round(pred.glicko.home_prob * 100) + '%</div></div>';
        h += '<div style="flex:1;background:rgba(0,0,0,0.3);border-radius:6px;padding:6px;color:#aaa"><div>\u041d\u0438\u0447\u044c\u044f</div><div style="font-size:16px;font-weight:700;color:#ffd700">' + Math.round(pred.glicko.draw_prob * 100) + '%</div></div>';
        h += '<div style="flex:1;background:rgba(0,0,0,0.3);border-radius:6px;padding:6px;color:#aaa"><div>' + escapeHtml(pred.away) + '</div><div style="font-size:16px;font-weight:700;color:#fff">' + Math.round(pred.glicko.away_prob * 100) + '%</div></div>';
        h += '</div>';
    }}
    h += '</div>';
    if (pred.glicko) {{
        let hr = Math.round(pred.glicko.home_rating || 0);
        let ar = Math.round(pred.glicko.away_rating || 0);
        let hx = pred.glicko.home_xg ? pred.glicko.home_xg.toFixed(2) : '';
        let ax = pred.glicko.away_xg ? pred.glicko.away_xg.toFixed(2) : '';
        if (hr || ar) {{
            h += '<div style="margin:0 0 10px;display:flex;align-items:center">';
            h += '<div style="flex:1;text-align:left;padding:0 12px"><div style="font-size:11px;color:#888">' + escapeHtml(pred.home) + '</div><div style="font-size:18px;font-weight:700;color:#fff">' + hr + '</div></div>';
            h += '<div style="text-align:center;line-height:1.2"><div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px">\u0420\u0435\u0439\u0442\u0438\u043d\u0433</div><div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px">Glicko</div></div>';
            h += '<div style="flex:1;text-align:right;padding:0 12px"><div style="font-size:11px;color:#888">' + escapeHtml(pred.away) + '</div><div style="font-size:18px;font-weight:700;color:#fff">' + ar + '</div></div>';
            h += '</div>';
        }}
        if (hx || ax) {{
            h += '<div style="margin:0 0 10px;display:flex;align-items:center">';
            h += '<div style="flex:1;text-align:left;padding:0 12px"><div style="font-size:11px;color:#888">' + escapeHtml(pred.home) + '</div><div style="font-size:18px;font-weight:700;color:#00e676">' + hx + '</div></div>';
            h += '<div style="text-align:center;line-height:1.2"><div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px">\u041e\u0436\u0438\u0434\u0430\u0435\u043c\u044b\u0435</div><div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px">\u0433\u043e\u043b\u044b (xG)</div></div>';
            h += '<div style="flex:1;text-align:right;padding:0 12px"><div style="font-size:11px;color:#888">' + escapeHtml(pred.away) + '</div><div style="font-size:18px;font-weight:700;color:#00e676">' + ax + '</div></div>';
            h += '</div>';
        }}
    }}
    if (pred.odds) {{
        h += '<div style="margin:0 0 12px">';
        h += '<div style="font-size:11px;color:#888;margin-bottom:6px;text-transform:uppercase;letter-spacing:0.5px;text-align:center">\u041a\u043e\u044d\u0444\u0444\u0438\u0446\u0438\u0435\u043d\u0442\u044b</div>';
        h += '<div style="display:flex;gap:8px">';
        h += '<div style="flex:1;background:linear-gradient(180deg,#1e1e2a,#1a1a1a);border:1px solid #2a2a3a;border-radius:8px;padding:10px;text-align:center"><div style="font-size:11px;color:#888">П1</div><div style="font-size:20px;font-weight:700;color:#fff">' + pred.odds.home + '</div></div>';
        h += '<div style="flex:1;background:linear-gradient(180deg,#1e1e2a,#1a1a1a);border:1px solid #2a2a3a;border-radius:8px;padding:10px;text-align:center"><div style="font-size:11px;color:#888">X</div><div style="font-size:20px;font-weight:700;color:#ffd700">' + pred.odds.draw + '</div></div>';
        h += '<div style="flex:1;background:linear-gradient(180deg,#1e1e2a,#1a1a1a);border:1px solid #2a2a3a;border-radius:8px;padding:10px;text-align:center"><div style="font-size:11px;color:#888">П2</div><div style="font-size:20px;font-weight:700;color:#fff">' + pred.odds.away + '</div></div>';
        h += '</div></div>';
    }}
    if (pred.prediction) {{
        let pt = pred.prediction.replace(/\\*\\*Прогноз на матч.*?(\\*\\*|$)/g, '');
        pt = escapeHtml(pt);
        pt = pt.replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>');
        pt = pt.replace(/\\n\\n/g, '</p><p>');
        pt = '<div style="font-size:17px;font-weight:700;color:#fff;text-align:center;margin-bottom:12px">\u041f\u0440\u043e\u0433\u043d\u043e\u0437</div>' + pt;
        h += '<div style="font-size:14px;line-height:1.75;color:#ccc">' + pt + '</div>';
    }}
    return h;
}}

// ─── Вариант 2: Компактный (карточки) ────────────────────────────
function renderV2(pred) {{
    let h = '';
    // Блок с % 
    if (pred.glicko) {{
        let hp = Math.round(pred.glicko.home_prob * 100);
        let dp = Math.round(pred.glicko.draw_prob * 100);
        let ap = Math.round(pred.glicko.away_prob * 100);
        let homeColor = (hp > ap && hp > dp) ? '#00e676' : '#ff5252';
        let awayColor = (ap > hp && ap > dp) ? '#00e676' : '#ff5252';
        let homeBg = (hp > ap && hp > dp) ? '#1a2a1a' : '#2a1a1a';
        let awayBg = (ap > hp && ap > dp) ? '#1a2a1a' : '#2a1a1a';
        h += '<div style="display:flex;gap:10px;margin-bottom:16px">';
        h += '<div style="flex:1;background:' + homeBg + ';border-radius:10px;padding:12px;text-align:center"><div style="font-size:24px;font-weight:700;color:' + homeColor + '">' + hp + '%</div><div style="font-size:11px;color:#888;margin-top:2px">' + escapeHtml(pred.home) + '</div></div>';
        h += '<div style="flex:1;background:#2a2a1a;border-radius:10px;padding:12px;text-align:center"><div style="font-size:24px;font-weight:700;color:#ffd700">' + dp + '%</div><div style="font-size:11px;color:#888;margin-top:2px">\u041d\u0438\u0447\u044c\u044f</div></div>';
        h += '<div style="flex:1;background:' + awayBg + ';border-radius:10px;padding:12px;text-align:center"><div style="font-size:24px;font-weight:700;color:' + awayColor + '">' + ap + '%</div><div style="font-size:11px;color:#888;margin-top:2px">' + escapeHtml(pred.away) + '</div></div>';
        h += '</div>';
    }}
    // Сетка карточек статистики
    if (pred.glicko) {{
        let hr = Math.round(pred.glicko.home_rating || 0);
        let ar = Math.round(pred.glicko.away_rating || 0);
        let hx = pred.glicko.home_xg ? pred.glicko.home_xg.toFixed(2) : '';
        let ax = pred.glicko.away_xg ? pred.glicko.away_xg.toFixed(2) : '';
        h += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:16px">';
        if (hr) {{ h += '<div style="background:#1a1a1a;border-radius:8px;padding:10px;text-align:center"><div style="font-size:10px;color:#888;text-transform:uppercase">\u0420\u0435\u0439\u0442\u0438\u043d\u0433</div><div style="font-size:16px;font-weight:700;color:#fff">' + hr + '</div><div style="font-size:10px;color:#666">' + escapeHtml(pred.home) + '</div></div>'; }}
        if (ar) {{ h += '<div style="background:#1a1a1a;border-radius:8px;padding:10px;text-align:center"><div style="font-size:10px;color:#888;text-transform:uppercase">\u0420\u0435\u0439\u0442\u0438\u043d\u0433</div><div style="font-size:16px;font-weight:700;color:#fff">' + ar + '</div><div style="font-size:10px;color:#666">' + escapeHtml(pred.away) + '</div></div>'; }}
        if (hx) {{ h += '<div style="background:#1a1a1a;border-radius:8px;padding:10px;text-align:center"><div style="font-size:10px;color:#888;text-transform:uppercase">xG</div><div style="font-size:16px;font-weight:700;color:#00e676">' + hx + '</div><div style="font-size:10px;color:#666">' + escapeHtml(pred.home) + '</div></div>'; }}
        if (ax) {{ h += '<div style="background:#1a1a1a;border-radius:8px;padding:10px;text-align:center"><div style="font-size:10px;color:#888;text-transform:uppercase">xG</div><div style="font-size:16px;font-weight:700;color:#00e676">' + ax + '</div><div style="font-size:10px;color:#666">' + escapeHtml(pred.away) + '</div></div>'; }}
        h += '</div>';
    }}
    if (pred.odds) {{
        h += '<div style="display:flex;gap:8px;margin-bottom:16px">';
        h += '<div style="flex:1;background:#1a1a1a;border-radius:8px;padding:8px 4px;text-align:center;border-left:3px solid #00e676"><div style="font-size:11px;color:#888">П1</div><div style="font-size:18px;font-weight:700;color:#fff">' + pred.odds.home + '</div></div>';
        h += '<div style="flex:1;background:#1a1a1a;border-radius:8px;padding:8px 4px;text-align:center;border-left:3px solid #ffd700"><div style="font-size:11px;color:#888">X</div><div style="font-size:18px;font-weight:700;color:#ffd700">' + pred.odds.draw + '</div></div>';
        h += '<div style="flex:1;background:#1a1a1a;border-radius:8px;padding:8px 4px;text-align:center;border-left:3px solid #00e676"><div style="font-size:11px;color:#888">П2</div><div style="font-size:18px;font-weight:700;color:#fff">' + pred.odds.away + '</div></div>';
        h += '</div>';
    }}
    if (pred.prediction) {{
        let pt = pred.prediction.replace(/\\*\\*Прогноз на матч.*?(\\*\\*|$)/g, '');
        pt = escapeHtml(pt);
        pt = pt.replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>');
        pt = pt.replace(/\\n\\n/g, '</p><p>');
        // Без заголовка Прогноз — сразу текст
        h += '<div style="font-size:13px;line-height:1.6;color:#ccc;padding:12px;background:#1a1a1a;border-radius:8px">' + pt + '</div>';
    }}
    return h;
}}

// ─── Вариант 3: Табличный (статистика в ряд) ─────────────────────
function renderV3(pred) {{
    let h = '';
    // Шапка с вероятностями (маленькая строка)
    if (pred.glicko) {{
        h += '<div style="display:flex;gap:6px;margin-bottom:12px">';
        h += '<div style="flex:1;background:#1a1a1a;border-radius:6px;padding:6px;text-align:center;font-size:11px"><span style="color:#888">\u041f1 </span><span style="color:#fff;font-weight:700">' + Math.round(pred.glicko.home_prob * 100) + '%</span></div>';
        h += '<div style="flex:1;background:#1a1a1a;border-radius:6px;padding:6px;text-align:center;font-size:11px"><span style="color:#888">X </span><span style="color:#ffd700;font-weight:700">' + Math.round(pred.glicko.draw_prob * 100) + '%</span></div>';
        h += '<div style="flex:1;background:#1a1a1a;border-radius:6px;padding:6px;text-align:center;font-size:11px"><span style="color:#888">\u041f2 </span><span style="color:#fff;font-weight:700">' + Math.round(pred.glicko.away_prob * 100) + '%</span></div>';
        h += '</div>';
    }}
    // Таблица статистики
    if (pred.glicko) {{
        let hr = Math.round(pred.glicko.home_rating || 0);
        let ar = Math.round(pred.glicko.away_rating || 0);
        let hx = pred.glicko.home_xg ? pred.glicko.home_xg.toFixed(2) : '';
        let ax = pred.glicko.away_xg ? pred.glicko.away_xg.toFixed(2) : '';
        h += '<table style="width:100%;font-size:12px;border-collapse:collapse;margin-bottom:12px">';
        h += '<tr><td style="text-align:left;padding:4px;color:#888">' + escapeHtml(pred.home) + '</td><td style="text-align:center;padding:4px;color:#666;font-size:9px;text-transform:uppercase">\u0420\u0435\u0439\u0442\u0438\u043d\u0433</td><td style="text-align:right;padding:4px;color:#888">' + escapeHtml(pred.away) + '</td></tr>';
        h += '<tr><td style="text-align:left;padding:4px;font-size:18px;font-weight:700;color:#fff">' + hr + '</td><td style="text-align:center;padding:4px"></td><td style="text-align:right;padding:4px;font-size:18px;font-weight:700;color:#fff">' + ar + '</td></tr>';
        if (hx || ax) {{
            h += '<tr><td style="text-align:left;padding:4px;color:#888">' + escapeHtml(pred.home) + '</td><td style="text-align:center;padding:4px;color:#666;font-size:9px;text-transform:uppercase">xG</td><td style="text-align:right;padding:4px;color:#888">' + escapeHtml(pred.away) + '</td></tr>';
            h += '<tr><td style="text-align:left;padding:4px;font-size:18px;font-weight:700;color:#00e676">' + hx + '</td><td style="text-align:center;padding:4px"></td><td style="text-align:right;padding:4px;font-size:18px;font-weight:700;color:#00e676">' + ax + '</td></tr>';
        }}
        h += '</table>';
    }}
    if (pred.odds) {{
        h += '<div style="display:flex;gap:8px;margin-bottom:12px">';
        h += '<div style="flex:1;background:#1a1a1a;border-radius:6px;padding:8px;text-align:center"><div style="font-size:10px;color:#666;text-transform:uppercase">П1</div><div style="font-size:16px;font-weight:700;color:#fff">' + pred.odds.home + '</div></div>';
        h += '<div style="flex:1;background:#1a1a1a;border-radius:6px;padding:8px;text-align:center"><div style="font-size:10px;color:#666;text-transform:uppercase">\u041d\u0438\u0447\u044c\u044f</div><div style="font-size:16px;font-weight:700;color:#ffd700">' + pred.odds.draw + '</div></div>';
        h += '<div style="flex:1;background:#1a1a1a;border-radius:6px;padding:8px;text-align:center"><div style="font-size:10px;color:#666;text-transform:uppercase">П2</div><div style="font-size:16px;font-weight:700;color:#fff">' + pred.odds.away + '</div></div>';
        h += '</div>';
    }}
    if (pred.prediction) {{
        let pt = pred.prediction.replace(/\\*\\*Прогноз на матч.*?(\\*\\*|$)/g, '');
        pt = escapeHtml(pt);
        pt = pt.replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>');
        pt = pt.replace(/\\n\\n/g, '</p><p>');
        h += '<div style="font-size:13px;line-height:1.6;color:#999">' + pt + '</div>';
    }}
    return h;
}}

// ─── Вариант 4: Минималистичный (только суть) ────────────────────
function renderV4(pred) {{
    let h = '';
    // Большой вердикт
    let verdict = '';
    if (pred.glicko) {{
        let hp = Math.round(pred.glicko.home_prob * 100);
        let ap = Math.round(pred.glicko.away_prob * 100);
        verdict = hp > ap ? (escapeHtml(pred.home) + ' (' + hp + '%)') : (escapeHtml(pred.away) + ' (' + ap + '%)');
    }}
    h += '<div style="text-align:center;padding:20px 0 16px">';
    h += '<div style="font-size:28px;font-weight:700;color:#fff">' + verdict + '</div>';
    if (pred.odds) {{
        let avg = (1/parseFloat(pred.odds.home) + 1/parseFloat(pred.odds.draw) + 1/parseFloat(pred.odds.away));
        let prob = Math.round((1/parseFloat(pred.odds.home)) / avg * 100);
        h += '<div style="font-size:13px;color:#888;margin-top:4px">\u041a\u044d\u0444 ' + pred.odds.home + ' (' + prob + '%)</div>';
    }}
    h += '</div>';
    // Мини-статистика в одну строку
    if (pred.glicko) {{
        let hr = Math.round(pred.glicko.home_rating || 0);
        let ar = Math.round(pred.glicko.away_rating || 0);
        let hx = pred.glicko.home_xg ? pred.glicko.home_xg.toFixed(2) : '';
        let ax = pred.glicko.away_xg ? pred.glicko.away_xg.toFixed(2) : '';
        h += '<div style="display:flex;gap:0;margin-bottom:12px;text-align:center;border-bottom:1px solid #2a2a2a;padding-bottom:12px">';
        if (hr) {{ h += '<div style="flex:1"><div style="font-size:10px;color:#666;text-transform:uppercase">\u0420\u0435\u0439\u0442\u0438\u043d\u0433</div><div style="font-size:14px;color:#fff;font-weight:600">' + hr + '</div></div>'; }}
        if (hx) {{ h += '<div style="flex:1"><div style="font-size:10px;color:#666;text-transform:uppercase">xG</div><div style="font-size:14px;color:#00e676;font-weight:600">' + hx + '</div></div>'; }}
        if (ax) {{ h += '<div style="flex:1"><div style="font-size:10px;color:#666;text-transform:uppercase">xG\u0433</div><div style="font-size:14px;color:#00e676;font-weight:600">' + ax + '</div></div>'; }}
        if (ar) {{ h += '<div style="flex:1"><div style="font-size:10px;color:#666;text-transform:uppercase">\u0420\u0435\u0439\u0442\u0438\u043d\u0433</div><div style="font-size:14px;color:#fff;font-weight:600">' + ar + '</div></div>'; }}
        h += '</div>';
    }}
    if (pred.odds) {{
        h += '<div style="display:flex;gap:6px;margin-bottom:12px">';
        h += '<div style="flex:1;background:#0f0f0f;border:1px solid #2a2a2a;border-radius:6px;padding:8px;text-align:center"><div style="font-size:10px;color:#666">П1</div><div style="font-size:16px;font-weight:700;color:#fff">' + pred.odds.home + '</div></div>';
        h += '<div style="flex:1;background:#0f0f0f;border:1px solid #2a2a2a;border-radius:6px;padding:8px;text-align:center"><div style="font-size:10px;color:#666">X</div><div style="font-size:16px;font-weight:700;color:#ffd700">' + pred.odds.draw + '</div></div>';
        h += '<div style="flex:1;background:#0f0f0f;border:1px solid #2a2a2a;border-radius:6px;padding:8px;text-align:center"><div style="font-size:10px;color:#666">П2</div><div style="font-size:16px;font-weight:700;color:#fff">' + pred.odds.away + '</div></div>';
        h += '</div>';
    }}
    if (pred.prediction) {{
        let pt = pred.prediction.replace(/\\*\\*Прогноз на матч.*?(\\*\\*|$)/g, '');
        pt = escapeHtml(pt);
        pt = pt.replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>');
        pt = pt.replace(/\\n\\n/g, '</p><p>');
        h += '<div style="font-size:13px;line-height:1.6;color:#888;border-top:1px solid #2a2a2a;padding-top:12px">' + pt + '</div>';
    }}
    return h;
}}
// ─── Вариант 5: Гибрид (V2 шапка + V1 статика + V1 кэфы/текст) ──
function renderV5(pred) {{
    let h = '';
    // V2: проценты в цветных карточках
    if (pred.glicko) {{
        let hp = Math.round(pred.glicko.home_prob * 100);
        let dp = Math.round(pred.glicko.draw_prob * 100);
        let ap = Math.round(pred.glicko.away_prob * 100);
        let homeColor = (hp > ap && hp > dp) ? '#00e676' : '#ff5252';
        let awayColor = (ap > hp && ap > dp) ? '#00e676' : '#ff5252';
        let homeBg = (hp > ap && hp > dp) ? '#1a2a1a' : '#2a1a1a';
        let awayBg = (ap > hp && ap > dp) ? '#1a2a1a' : '#2a1a1a';
        h += '<div style="display:flex;gap:10px;margin-bottom:16px">';
        h += '<div style="flex:1;background:' + homeBg + ';border-radius:10px;padding:12px;text-align:center"><div style="font-size:24px;font-weight:700;color:' + homeColor + '">' + hp + '%</div><div style="font-size:11px;color:#888;margin-top:2px">' + escapeHtml(pred.home) + '</div></div>';
        h += '<div style="flex:1;background:#2a2a1a;border-radius:10px;padding:12px;text-align:center"><div style="font-size:24px;font-weight:700;color:#ffd700">' + dp + '%</div><div style="font-size:11px;color:#888;margin-top:2px">\u041d\u0438\u0447\u044c\u044f</div></div>';
        h += '<div style="flex:1;background:' + awayBg + ';border-radius:10px;padding:12px;text-align:center"><div style="font-size:24px;font-weight:700;color:' + awayColor + '">' + ap + '%</div><div style="font-size:11px;color:#888;margin-top:2px">' + escapeHtml(pred.away) + '</div></div>';
        h += '</div>';
    }}
    // V1: рейтинг и xG по центру
    if (pred.glicko) {{
        let hr = Math.round(pred.glicko.home_rating || 0);
        let ar = Math.round(pred.glicko.away_rating || 0);
        let hx = pred.glicko.home_xg ? pred.glicko.home_xg.toFixed(2) : '';
        let ax = pred.glicko.away_xg ? pred.glicko.away_xg.toFixed(2) : '';
        if (hr || ar) {{
            h += '<div style="margin:0 0 10px;display:flex;align-items:center">';
            h += '<div style="flex:1;text-align:left;padding:0 12px"><div style="font-size:11px;color:#888">' + escapeHtml(pred.home) + '</div><div style="font-size:18px;font-weight:700;color:#fff">' + hr + '</div></div>';
            h += '<div style="text-align:center;line-height:1.2"><div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px">\u0420\u0435\u0439\u0442\u0438\u043d\u0433</div><div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px">Glicko</div></div>';
            h += '<div style="flex:1;text-align:right;padding:0 12px"><div style="font-size:11px;color:#888">' + escapeHtml(pred.away) + '</div><div style="font-size:18px;font-weight:700;color:#fff">' + ar + '</div></div>';
            h += '</div>';
        }}
        if (hx || ax) {{
            h += '<div style="margin:0 0 10px;display:flex;align-items:center">';
            h += '<div style="flex:1;text-align:left;padding:0 12px"><div style="font-size:11px;color:#888">' + escapeHtml(pred.home) + '</div><div style="font-size:18px;font-weight:700;color:#00e676">' + hx + '</div></div>';
            h += '<div style="text-align:center;line-height:1.2"><div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px">\u041e\u0436\u0438\u0434\u0430\u0435\u043c\u044b\u0435</div><div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px">\u0433\u043e\u043b\u044b (xG)</div></div>';
            h += '<div style="flex:1;text-align:right;padding:0 12px"><div style="font-size:11px;color:#888">' + escapeHtml(pred.away) + '</div><div style="font-size:18px;font-weight:700;color:#00e676">' + ax + '</div></div>';
            h += '</div>';
        }}
    }}
    // V1: коэффициенты
    if (pred.odds) {{
        h += '<div style="margin:0 0 12px">';
        h += '<div style="font-size:11px;color:#888;margin-bottom:6px;text-transform:uppercase;letter-spacing:0.5px;text-align:center">\u041a\u043e\u044d\u0444\u0444\u0438\u0446\u0438\u0435\u043d\u0442\u044b</div>';
        h += '<div style="display:flex;gap:8px">';
        h += '<div style="flex:1;background:linear-gradient(180deg,#1e1e2a,#1a1a1a);border:1px solid #2a2a3a;border-radius:8px;padding:10px;text-align:center"><div style="font-size:11px;color:#888">П1</div><div style="font-size:20px;font-weight:700;color:#fff">' + pred.odds.home + '</div></div>';
        h += '<div style="flex:1;background:linear-gradient(180deg,#1e1e2a,#1a1a1a);border:1px solid #2a2a3a;border-radius:8px;padding:10px;text-align:center"><div style="font-size:11px;color:#888">X</div><div style="font-size:20px;font-weight:700;color:#ffd700">' + pred.odds.draw + '</div></div>';
        h += '<div style="flex:1;background:linear-gradient(180deg,#1e1e2a,#1a1a1a);border:1px solid #2a2a3a;border-radius:8px;padding:10px;text-align:center"><div style="font-size:11px;color:#888">П2</div><div style="font-size:20px;font-weight:700;color:#fff">' + pred.odds.away + '</div></div>';
        h += '</div></div>';
    }}
    // Тоталы
    if (pred.totals && pred.totals.over) {{
        h += '<div style="margin:0 0 12px">';
        h += '<div style="font-size:11px;color:#888;margin-bottom:6px;text-transform:uppercase;letter-spacing:0.5px;text-align:center">\u0422\u043e\u0442\u0430\u043b</div>';
        h += '<div style="display:flex;align-items:center;gap:6px">';
        h += '<div style="flex:1;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:8px;padding:8px;text-align:center"><div style="font-size:11px;color:#888">\u0422\u0411</div><div style="font-size:16px;font-weight:700;color:#ff9800">' + pred.totals.over + '</div></div>';
        h += '<div style="font-size:16px;color:#fff;font-weight:700;text-align:center;min-width:40px">' + (pred.totals.total_line || 2.5) + '</div>';
        h += '<div style="flex:1;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:8px;padding:8px;text-align:center"><div style="font-size:11px;color:#888">\u0422\u041c</div><div style="font-size:16px;font-weight:700;color:#2196f3">' + pred.totals.under + '</div></div>';
        h += '</div></div>';
    }}
    // V1: текст прогноза
    if (pred.prediction) {{
        let pt = pred.prediction.replace(/\\*\\*Прогноз на матч.*?(\\*\\*|$)/g, '');
        pt = escapeHtml(pt);
        pt = pt.replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>');
        pt = pt.replace(/\\n\\n/g, '</p><p>');
        pt = '<div style="font-size:17px;font-weight:700;color:#fff;text-align:center;margin-bottom:12px">\u041f\u0440\u043e\u0433\u043d\u043e\u0437</div>' + pt;
        h += '<div style="font-size:14px;line-height:1.75;color:#ccc">' + pt + '</div>';
    }}
    return h;
}}

function closePrediction() {{
    document.getElementById('pred-modal').classList.remove('active');
    document.body.style.overflow = '';
}}

document.getElementById('pred-modal').addEventListener('click', function(e) {{
    if (e.target === this) closePrediction();
}});

// ─── Stats Modal ──────────────────────────────────────────────────
const STAT_NAMES = {{
    'possessionPct': 'Владение',
    'totalShots': 'Всего ударов',
    'shotsOnTarget': 'Удары в створ',
    'shotPct': 'Точность ударов',
    'blockedShots': 'Заблокировано',
    'totalPasses': 'Всего пасов',
    'accuratePasses': 'Точные пасы',
    'passPct': 'Точность пасов',
    'wonCorners': 'Угловые',
    'offsides': 'Офсайды',
    'totalCrosses': 'Кроссы',
    'accurateCrosses': 'Точные кроссы',
    'crossPct': 'Точность кроссов',
    'totalLongBalls': 'Длинные передачи',
    'accurateLongBalls': 'Точные длинные',
    'longballPct': 'Точность длинных',
    'saves': 'Сейвы',
    'totalTackles': 'Отборы',
    'effectiveTackles': 'Успешных отборов',
    'tacklePct': 'Точность отборов',
    'interceptions': 'Перехваты',
    'totalClearance': 'Выносы',
    'effectiveClearance': 'Успешных выносов',
    'foulsCommitted': 'Фолы',
    'yellowCards': 'ЖК',
    'redCards': 'КК',
}};

const PCT_STATS = ['possessionPct', 'passPct', 'shotPct', 'crossPct', 'longballPct', 'tacklePct'];

function percentRow(homeVal, awayVal, label) {{
    var h = parseFloat(homeVal);
    var a = parseFloat(awayVal);
    if (isNaN(h) || isNaN(a)) return '';
    var total = h + a;
    if (total === 0) return '';
    var hp = Math.round(h / total * 100);
    var ap = 100 - hp;
    return '<tr><td colspan="3" class="percent-row">' +
        '<div class="percent-label">' + label + '</div>' +
        '<div class="percent-bars">' +
        '<span class="percent-val">' + hp + '%</span>' +
        '<div class="percent-track"><div class="percent-home" style="width:' + hp + '%"></div><div class="percent-away" style="width:' + ap + '%"></div></div>' +
        '<span class="percent-val">' + ap + '%</span>' +
        '</div></td></tr>';
}}

function openStats(matchKey) {{
    fetch('/live_scores.json?_=' + Date.now())
        .then(function(r) {{ return r.json(); }})
        .then(function(data) {{
            var info = data.matches[matchKey];
            if (!info || !info.stats) return;

            var home = info.home;
            var away = info.away;
            var hs = info.stats[home] || {{}};
            var as = info.stats[away] || {{}};

            document.getElementById('stats-home-team').textContent = home;
            document.getElementById('stats-away-team').textContent = away;
            document.getElementById('stats-score').textContent = info.score || '–';

            var order = [
                'possessionPct',
                'totalShots', 'shotsOnTarget', 'shotPct', 'blockedShots',
                'accuratePasses', 'totalPasses', 'passPct',
                'totalLongBalls', 'accurateLongBalls',
                'totalCrosses', 'accurateCrosses',
                'wonCorners', 'offsides',
                'saves',
                'effectiveTackles', 'totalTackles',
                'interceptions',
                'effectiveClearance', 'totalClearance',
                'foulsCommitted', 'yellowCards', 'redCards'
            ];

            var rows = '';
            for (var i = 0; i < order.length; i++) {{
                var key = order[i];
                if (!(key in hs) && !(key in as)) continue;
                var h = hs[key] || '—';
                var a = as[key] || '—';
                var name = STAT_NAMES[key] || key;

                if (PCT_STATS.indexOf(key) !== -1) {{
                    rows += percentRow(h, a, name);
                }} else {{
                    rows += '<tr><td class="stat-home">' + h + '</td>' +
                        '<td class="stat-name">' + name + '</td>' +
                        '<td class="stat-away">' + a + '</td></tr>';
                }}
            }}

            document.getElementById('stats-body').innerHTML = rows;
            document.getElementById('stats-modal').classList.add('active');
            document.body.style.overflow = 'hidden';
        }})
        .catch(function() {{}});
}}

function closeStats() {{
    document.getElementById('stats-modal').classList.remove('active');
    document.body.style.overflow = '';
}}

document.getElementById('stats-modal').addEventListener('click', function(e) {{
    if (e.target === this) closeStats();
}});

// ─── Nav highlight ────────────────────────────────────────────────
document.addEventListener('click', function(e) {{
    var link = e.target.closest('#nav a');
    if (link) {{
        document.querySelectorAll('#nav a').forEach(function(a) {{ a.classList.remove('active'); }});
        link.classList.add('active');
    }}
}});

// ─── Load more news ───────────────────────────────────────────────
let newsOffset = 15;
const newsPerPage = 15;
let allNewsData = null;

function loadMoreNews() {{
    const btn = document.getElementById('news-more-btn');
    const container = document.getElementById('news-more-container');
    btn.disabled = true;
    btn.textContent = 'Загрузка...';

    if (allNewsData) {{
        renderNews();
        return;
    }}

    fetch('/news_data.json')
        .then(r => r.json())
        .then(data => {{
            allNewsData = data;
            renderNews();
        }})
        .catch(() => {{
            btn.textContent = 'Ошибка загрузки';
            btn.disabled = false;
        }});
}}

function renderNews() {{
    const btn = document.getElementById('news-more-btn');
    const container = document.getElementById('news-more-container');
    const slice = allNewsData.slice(newsOffset, newsOffset + newsPerPage);

    let html = '';
    for (let i = 0; i < slice.length; i++) {{
        const n = slice[i];
        const idx = newsOffset + i;
        const img = n.image ? `<div class="news-img"><img src="${{n.image}}" alt="" loading="lazy" onerror="this.closest('.news-row').classList.add('no-img');this.remove()"></div>` : '';
        html += `
        <div class="news-card" data-news-idx="${{idx}}" onclick="openArticle(${{idx}})">
            <div class="news-row">
                ${{img}}
                <div class="news-body">
                    <div class="news-meta">
                        <span class="news-source">${{n.source}}</span>
                        <span class="news-time">${{n.time}}</span>
                    </div>
                    <div class="news-title">${{escapeHtml(n.title)}}</div>
                    <div class="news-desc">${{escapeHtml(n.desc)}}</div>
                </div>
            </div>
        </div>`;
    }}

    container.insertAdjacentHTML('beforeend', html);
    newsOffset += slice.length;

    if (newsOffset >= allNewsData.length) {{
        btn.style.display = 'none';
    }} else {{
        btn.textContent = 'Показать ещё';
        btn.disabled = false;
    }}
}}
</script>

<!-- ─── Автообновление live-счетов ──────────────────────── -->
<script>
(function() {{
    let refreshTimer = null;
    const MATCH_REFRESH_MS = 30000; // каждые 30 секунд

    function getMatchKey(upCard) {{
        // Извлекаем league, home, away из карточки матча
        const nameEls = upCard.querySelectorAll('.up-v1-name');
        if (nameEls.length < 2) return null;
        const leagueEl = upCard.closest('[id]')?.id || '';
        // league из section-sub перед карточкой
        let league = '';
        let prev = upCard.previousElementSibling;
        while (prev) {{
            if (prev.classList.contains('section-sub')) {{
                const text = prev.textContent || '';
                // Убираем эмодзи из начала
                league = text.replace(/^[^\\s]*\\s+/, '').trim();
                break;
            }}
            prev = prev.previousElementSibling;
        }}
        if (!league) return null;
        return league + '||' + (nameEls[0].textContent || '').trim() + '||' + (nameEls[1].textContent || '').trim();
    }}

    function updateLiveScores() {{
        fetch('/live_scores.json?_=' + Date.now())
            .then(r => r.json())
            .then(data => {{
                const matches = data.matches || {{}};
                const cards = document.querySelectorAll('.up-card');
                let changed = false;

                cards.forEach(function(card) {{
                    const key = getMatchKey(card);
                    if (!key || !matches[key]) return;

                    const info = matches[key];
                    const rightEl = card.querySelector('.up-v1-right');
                    if (!rightEl) return;

                    if (info.status === 'live' || info.status === 'finished') {{
                        const existingScore = rightEl.querySelector('.up-v1-score');
                        const existingLive = rightEl.querySelector('.up-v1-live-badge');

                        if (info.status === 'live' && !existingLive) {{
                            // Был upcoming → live: меняем правую колонку
                            rightEl.innerHTML = `
                                <div class="up-v1-live-badge">▶ LIVE</div>
                                <div class="up-v1-score">${{info.score || '–'}}</div>
                            `;
                            // Добавляем кликабельность карточке
                            card.setAttribute('data-match-key', key);
                            card.setAttribute('onclick', 'openStats(this.dataset.matchKey)');
                            card.style.cursor = 'pointer';
                            changed = true;
                        }} else if (info.status === 'finished' && (!existingScore || existingLive)) {{
                            // Было upcoming/live → finished: убираем LIVE, счёт вертикально
                            let scoreHtml = '';
                            if (info.score && info.score.indexOf(':') !== -1) {{
                                const pts = info.score.split(':');
                                scoreHtml = '<div class="up-v1-score-home">' + pts[0] + '</div><div class="up-v1-score-away">' + (pts[1] || '') + '</div>';
                            }} else {{
                                scoreHtml = '<div class="up-v1-score-home">' + (info.score || '–') + '</div>';
                            }}
                            rightEl.innerHTML = scoreHtml;
                            changed = true;
                        }} else if (info.status === 'live' && existingLive && existingScore && info.score) {{
                            // Обновляем счёт без перерисовки
                            const newScore = info.score;
                            if (existingScore.textContent !== newScore && newScore !== '–') {{
                                existingScore.textContent = newScore;
                                changed = true;
                            }}
                    }}
                }});

                if (changed) {{
                    clearTimeout(refreshTimer);
                    refreshTimer = setTimeout(function() {{
                        const meta = document.querySelector('meta[http-equiv="refresh"]');
                        if (meta) meta.remove();
                        setTimeout(function() {{ location.reload(); }}, 60000);
                    }}, 5000);
                }}
            }})
            .catch(function() {{}});
    }}

    // Запускаем поллинг
    setInterval(updateLiveScores, MATCH_REFRESH_MS);
}})();
</script>

</body>
</html>'''

    with open(OUTPUT, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f'✅ Сайт сгенерирован: {OUTPUT} ({len(html)} bytes)')
    print(f'   Новостей: {len(news)}, Матчей сегодня: {len(today_matches)}, завтра: {len(upcoming_matches)}, ТВ: {"есть" if tvguide_rows else "нет"}')


if __name__ == '__main__':
    generate()
