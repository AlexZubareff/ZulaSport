#!/usr/bin/env python3
"""
Обработчик команд для @ZulaSportNews_bot
Динамическая ReplyKeyboard: виды спорта → лиги
"""

import sys
import os
import time
import json
import requests
import logging
from datetime import datetime, timedelta, timezone
import urllib.request
import re
import copy
import random
import socket
socket.setdefaulttimeout(10)

sys.path.insert(0, '/opt')
import digest_builder_v2 as dg
from matchtv_tvguide import fetch_tvguide as fetch_tvprogram


TOKEN = "8431200157:AAF-vgf6D3AGokWMmOUgzUfffKlCwDz3uwQ"
ALLOWED_GROUP = -1003708361475
ALLOWED_CHANNEL = -1003928523816

LOG_FILE = "/opt/voice-processor/sport_bot.log"

class FlushFileHandler(logging.FileHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[FlushFileHandler(LOG_FILE), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

_tg_session = requests.Session()
# Hard socket-level timeout to prevent hanging
for scheme in ('https://',):
    _tg_session.get_adapter(scheme).max_retries = 0

def tg_api(method, **kwargs):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    if method == 'getUpdates':
        # Explicitly allow message + callback_query updates
        kwargs['allowed_updates'] = ['message', 'callback_query']
        try:
            r = _tg_session.get(url, params=kwargs, timeout=(3, 10))
        except Exception:
            return None
    else:
        try:
            r = _tg_session.post(url, data=kwargs, timeout=(3, 15)) if kwargs else _tg_session.get(url, timeout=(3, 15))
        except Exception:
            return None
    try:
        return r.json()
    except Exception:
        return None


def send_message(chat_id, text, reply_markup=None, parse_mode='Markdown'):
    data = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    return tg_api("sendMessage", **data)

def answer_callback(callback_id, text=""):
    return tg_api("answerCallbackQuery", callback_query_id=callback_id, text=text)


# ============================================================
# КЛАВИАТУРЫ (ReplyKeyboard — меняется динамически)
# ============================================================

def keyboard_main():
    """Главная — категории спорта"""
    return {
        "keyboard": [
            [{"text": "⚽ Футбол"}, {"text": "🏒 Хоккей"}],
            [{"text": "🏀 Баскетбол"}, {"text": "🎾 Теннис"}],
            [{"text": "📅 Сегодня"}, {"text": "🔴 LIVE"}],
            [{"text": "📺 ТВ-гид"}, {"text": "📊 Дайджест"}],
        ],
        "resize_keyboard": True
    }

def keyboard_football():
    """Футбольные лиги"""
    return {
        "keyboard": [
            [{"text": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ"}, {"text": "🇪🇸 Ла Лига"}, {"text": "🇮🇹 Серия А"}],
            [{"text": "🇩🇪 Бундеслига"}, {"text": "🇫🇷 Лига 1"}, {"text": "🇵🇹 Португалия"}],
            [{"text": "🇷🇺 РПЛ"}, {"text": "🏆 ЛЧ"}, {"text": "🏆 ЛЕ"}],
            [{"text": "🔙 Назад к видам спорта"}],
        ],
        "resize_keyboard": True
    }

def keyboard_periods(league_cmd, league_name, emoji):
    """Инлайн-кнопки для выбора периода матчей"""
    return {
        "inline_keyboard": [
            [{"text": "🔴 Лайв", "callback_data": f"period_live_{league_cmd}"},
             {"text": "⏳ Сегодня", "callback_data": f"period_today_{league_cmd}"}],
            [{"text": "📅 Завтра", "callback_data": f"period_tomorrow_{league_cmd}"},
             {"text": "🏁 Вчера", "callback_data": f"period_yesterday_{league_cmd}"}],
        ]
    }


def keyboard_hockey():
    """Хоккейные лиги"""
    return {
        "keyboard": [
            [{"text": "🏒 КХЛ"}, {"text": "🏒 НХЛ"}],
            [{"text": "🔙 Назад к видам спорта"}],
        ],
        "resize_keyboard": True
    }

def keyboard_basketball():
    """Баскетбольные лиги"""
    return {
        "keyboard": [
            [{"text": "🏀 НБА"}, {"text": "🏀 Евролига"}],
            [{"text": "🔙 Назад к видам спорта"}],
        ],
        "resize_keyboard": True
    }

def keyboard_tennis():
    """Теннисные турниры"""
    return {
        "keyboard": [
            [{"text": "🎾 ATP"}, {"text": "🎾 WTA"}],
            [{"text": "🔙 Назад к видам спорта"}],
        ],
        "resize_keyboard": True
    }


# ============================================================
# ПРОЦЕССИНГ + КЭШ
# ============================================================

import sport_cache as _sc

def now_mow():
    return datetime.now(timezone.utc) + timedelta(hours=3)

def get_espn(date_str):
    """ESPN с общим кэшем 5 мин (доступен из всех скриптов)"""
    cached = _sc.get('espn', f'espn_{date_str}')
    if cached is not None:
        return cached
    data = dg.fetch_espn(date_str)
    _sc.set('espn', f'espn_{date_str}', data)
    return data

def format_matches(matches, title):
    if not matches:
        return f"{title}\n\nМатчей нет"
    lines = [f"📊 *{title}*"]

    # LIVE
    live = [m for m in matches if m.get('state') == 'live']
    if live:
        lines.append(f"\n🔴 *Прямо сейчас:*")
        for m in live:
            lines.append(f"  {m['emoji']} {m['team1']} — {m['team2']} │ {m.get('score', '?')}")

    # Предстоящие (scheduled/future) на сегодня
    upcoming = [m for m in matches if m.get('state') in ('scheduled', 'future')]
    if upcoming:
        lines.append(f"\n⏳ *Ожидаются:*")
        for m in upcoming:
            t = m.get('time', m.get('start_time', '?'))
            lines.append(f"  {m['emoji']} {m['team1']} — {m['team2']} │ 🕐 {t}")

    # Завершённые (finished) — только за прошлые сутки
    finished = [m for m in matches if m.get('state') == 'finished']
    if finished:
        lines.append(f"\n🏁 *Завершённые:*")
        for m in finished:
            lines.append(f"  {m['emoji']} {m['team1']} — {m['team2']} │ {m.get('score', '?')}")

    return '\n'.join(lines)


def fetch_tv_guide_text(date_obj):
    try:

        date_str = date_obj.strftime('%Y-%m-%d')
        programs = fetch_tvprogram(date_str)
        if not programs:
            return f"📺 ТВ-программа на {date_obj.strftime('%d.%m')}\n\nНет данных"
        lines = [f"📺 *ТВ-гид на {date_obj.strftime('%d.%m')}*"]
        for prog in programs[:15]:
            t = prog.get('time', '')
            title = prog.get('title', '')
            ch = prog.get('channel', '')
            if title:
                line = f"⏱ {t} — *{title}*"
                if ch:
                    line += f" ({ch})"
                lines.append(line)
        return '\n'.join(lines)
    except:
        return "📺 ТВ-гид временно недоступен"


def get_matches_for_league(league_cmd, ref_date, state_filter=None):
    """Возвращает матчи по лиге. state_filter: 'live', 'upcoming', 'finished', None=всё"""
    league_names = {
        'rpl': ('РПЛ', '🇷🇺'), 'khl': ('КХЛ', '🏒'), 'nhl': ('НХЛ', '🏒'),
        'epl': ('АПЛ', '🏴󠁧󠁢󠁥󠁮󠁧󠁿'), 'laliga': ('Ла Лига', '🇪🇸'),
        'seriea': ('Серия А', '🇮🇹'), 'bundesliga': ('Бундеслига', '🇩🇪'),
        'ligue1': ('Лига 1', '🇫🇷'), 'portugal': ('Португалия', '🇵🇹'),
        'nba': ('НБА', '🏀'), 'euroleague': ('Евролига', '🏀'),
        'atp': ('ATP', '🎾'), 'wta': ('WTA', '🎾'),
        'ucl': ('Лига чемпионов', '🏆'), 'uel': ('Лига Европы', '🏆'),
    }
    name, emoji = league_names.get(league_cmd, (league_cmd.upper(), '⚽'))

    def filter_league(matches):
        return [m for m in matches if m.get('league_short') == name or m.get('league') == name]

    # Завершённые — вчера
    yesterday = ref_date - timedelta(days=1)
    espn_yes = dg.fetch_espn(yesterday.strftime('%Y%m%d'))
    finished = [m for m in filter_league(espn_yes) if m.get('state') == 'finished']

    # Сегодня — live и предстоящие
    espn_today = dg.fetch_espn(ref_date.strftime('%Y%m%d'))
    today = filter_league(espn_today)
    live = [m for m in today if m.get('state') == 'live']
    upcoming_today = [m for m in today if m.get('state') in ('scheduled', 'future')]

    # Завтра — предстоящие
    tomorrow = ref_date + timedelta(days=1)
    espn_tom = dg.fetch_espn(tomorrow.strftime('%Y%m%d'))
    upcoming_tom = filter_league(espn_tom)

    all_matches = finished + live + upcoming_today + upcoming_tom

    if not all_matches:
        return f"{emoji} {name}: матчей нет"

    lines = [f"📊 *{emoji} {name}*"]

    if live:
        lines.append(f"\n🔴 *Прямо сейчас:*")
        for m in live:
            lines.append(f"  {m['emoji']} {m['team1']} — {m['team2']} │ {m.get('score', '?')}")

    if upcoming_today:
        lines.append(f"\n⏳ *Сегодня:*")
        for m in upcoming_today:
            t = m.get('time', m.get('start_time', '?'))
            lines.append(f"  {m['emoji']} {m['team1']} — {m['team2']} │ 🕐 {t}")

    if upcoming_tom:
        lines.append(f"\n📅 *Завтра:*")
        for m in upcoming_tom:
            t = m.get('time', m.get('start_time', '?'))
            lines.append(f"  {m['emoji']} {m['team1']} — {m['team2']} │ 🕐 {t}")

    if finished:
        lines.append(f"\n🏁 *Вчера:*")
        for m in finished:
            lines.append(f"  {m['emoji']} {m['team1']} — {m['team2']} │ {m.get('score', '?')}")

    return '\n'.join(lines)


# ============================================================
# НОВОСТИ (из news_data.json — единый источник с сайтом)
# ============================================================

_POSTED_FILE = '/opt/posted_news.json'


def _load_posted():
    """Загрузить список опубликованных новостей."""
    try:
        with open(_POSTED_FILE) as f:
            return json.load(f)
    except:
        return {'posted': [], 'max_items': 100}


def _save_posted(posted):
    """Сохранить список опубликованных."""
    try:
        # Обрезаем до лимита
        if len(posted['posted']) > posted.get('max_items', 100):
            posted['posted'] = posted['posted'][-posted['max_items']:]
        with open(_POSTED_FILE, 'w') as f:
            json.dump(posted, f)
    except:
        pass


_FOREIGN = {'BBC Sport', 'BBC Football', 'BBC Tennis', 'Guardian Football', 'Sky Sports'}
_RUSSIAN = {'Чемпионат', 'Sports.ru'}

def _news_type(source):
    """'foreign' или 'russian'"""
    if source in _FOREIGN:
        return 'foreign'
    return 'russian'


def _mark_posted(article_link, title, source):
    """Отметить новость как опубликованную."""
    posted = _load_posted()
    links = {p['link'] for p in posted['posted']}
    if article_link in links:
        return
    posted['posted'].append({
        'link': article_link,
        'title': title[:80],
        'source': source,
        'type': _news_type(source),
        'time': time.time(),
    })
    _save_posted(posted)


def _is_posted(article_link):
    posted = _load_posted()
    return any(p['link'] == article_link for p in posted['posted'])


def fetch_news_from_json():
    """Выбрать новость из news_data.json с чередованием foreign ↔ russian."""
    news_path = '/var/www/sport/news_data.json'
    if not os.path.exists(news_path):
        logger.warning('news_data.json не найден')
        return None
    
    try:
        with open(news_path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f'Ошибка загрузки news_data.json: {e}')
        return None
    
    if not data:
        return None
    
    posted = _load_posted()
    posted_links = {p['link'] for p in posted.get('posted', [])}
    
    # Определяем, какой тип нужен сейчас (чередование)
    last_type = posted.get('posted', [{}])[-1].get('type', '') if posted.get('posted') else ''
    need_type = 'russian' if last_type == 'foreign' else 'foreign'
    
    logger.info(f"🔄 Очередность: последний был {last_type or '—'}, ищем {need_type}")
    
    # Сортируем по свежести
    sorted_news = sorted(data, key=lambda x: x.get('ts', 0), reverse=True)
    
    chosen = None
    # Сначала ищем неповторившуюся с нужным типом
    for n in sorted_news:
        if n['link'] not in posted_links and _news_type(n.get('source', '')) == need_type:
            chosen = n
            logger.info(f"🏆 Выбрана: «{n['title'][:50]}» ({n['source']}) — {need_type}")
            break
    
    # Если нет — любую неповторившуюся (другого типа)
    if not chosen:
        for n in sorted_news:
            if n['link'] not in posted_links:
                chosen = n
                logger.info(f"🏆 Выбрана: «{n['title'][:50]}» ({n['source']}) — запасной вариант")
                break
    
    if not chosen:
        logger.warning('Нет неповторяющихся новостей в news_data.json')
        return None
    
    _mark_posted(chosen['link'], chosen['title'], chosen.get('source', ''))
    return chosen


def fetch_og_image(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=10).read().decode('utf-8', errors='ignore')
        m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html, re.I)
        if m:
            return m.group(1)
        m = re.search(r'content=["\']([^"\']+\.(?:jpg|jpeg|png|webp))["\']', html, re.I)
        if m:
            return m.group(1)
    except:
        pass
    return None


def fetch_bbc_video():
    """Получает последнее видео с BBC Sport YouTube"""
    try:
        import xml.etree.ElementTree as _ET
        # Get latest video via oEmbed or feed
        feed = "https://www.youtube.com/feeds/videos.xml?channel_id=UCW6-BQWFA70Dyyc7ZpZ9Xlg"
        req = urllib.request.Request(feed, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=10)
        root = _ET.fromstring(resp.read())
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        entries = root.findall('atom:entry', ns)
        if entries:
            entry = entries[0]
            title = entry.find('atom:title', ns)
            link = entry.find('atom:link', ns)
            group = entry.find('{http://search.yahoo.com/mrss/}group')
            thumb = group.find('{http://search.yahoo.com/mrss/}thumbnail') if group is not None else None
            if title is not None and link is not None:
                return {
                    'title': title.text or '',
                    'url': link.attrib.get('href', ''),
                    'thumbnail': thumb.attrib.get('url', f'https://img.youtube.com/vi/{entries[0].find("atom:videoId", ns).text if entries[0].find("atom:videoId", ns) is not None else ""}/hqdefault.jpg') if thumb is not None else '',
                }
    except:
        pass
    return None


def escape_md(text):
    """Escape for Telegram Markdown (not V2). Only escapes _, *, [, ], `"""
    if not text:
        return ''
    for ch in ['_', '*', '[', ']', '`']:
        text = text.replace(ch, '\\' + ch)
    return text


def post_news_to_channel(now_msk, post_type='news'):
    """
    post_type: 'results' | 'news' | 'upcoming'
    """
    try:
        hour = now_msk.hour
        if post_type == 'upcoming':
            # ВЕЧЕРНИЙ ПОСТ: предстоящие матчи на завтра
            try:
                import subprocess as _sp_up
                _sp_up.run([sys.executable, '/opt/upcoming.py'], capture_output=False, timeout=120)
            except Exception as _e_up:
                logger.warning(f'upcoming error: {_e_up}')
            return

        espn = get_espn(now_msk.strftime('%Y%m%d'))

        news_lines = []
        photo_url = None

        # ===== Формирование поста в зависимости от типа =====
        match_lines = []

        if post_type == 'results':
            # ЕДИНСТВЕННЫЙ ПОСТ ДНЯ: дайджест результатов (через daily_results.py)
            # daily_results.py сам отправляет пост в канал + inline-кнопки, больше ничего не нужно
            try:
                import subprocess as _sp_dr
                _sp_dr.run([sys.executable, '/opt/daily_results.py'], capture_output=False, timeout=120)
            except Exception as _e_dr:
                logger.warning(f'daily_results error: {_e_dr}')
        else:
            # ОСТАЛЬНЫЕ ПОСТЫ: только новость (видео или текст)
            # Каждый 3-й пост — видео BBC Sport
            video_counter = getattr(post_news_to_channel, 'video_count', 0)
            post_video = (video_counter + 1) % 3 == 0

            if post_video:
                v = fetch_bbc_video()
                if v:
                    news_lines.append(f'🎬 BBC Sport — видео')
                    news_lines.append(v['title'])
                    news_lines.append('')
                    news_lines.append(v['url'])
                    photo_url = v['thumbnail']
                    post_news_to_channel.video_count = (video_counter + 1) % 10
                    logger.info(f"📹 BBC Video: {v['title'][:50]}")

            try:
                if not news_lines:
                    news = fetch_news_from_json()
                if news:
                    title = news['title']
                    link = news['link']
                    source = news['source']
                    
                    # У зарубежных источников title уже переведён (сайт)
                    # У российских — оригинал на русском
                    _FOREIGN = {'BBC Sport', 'BBC Football', 'BBC Tennis', 'Guardian Football', 'Sky Sports'}
                    
                    if source in _FOREIGN:
                        news_lines.append(f'🌍 {source}')
                    else:
                        news_lines.append(f'📰 {source}')
                    
                    news_lines.append(title)
                    
                    # Используем content_ru для зарубежных, desc_full для российских
                    content_text = news.get('content_ru', '') or news.get('desc_full', '') or news.get('desc', '')
                    if content_text and len(content_text) > 20:
                        # Обрезаем до ~600 символов для компактного поста
                        display = content_text[:600]
                        # Обрезаем по последнему предложению
                        if len(content_text) > 600:
                            last_dot = max(display.rfind('.'), display.rfind('!'), display.rfind('?'))
                            if last_dot > 300:
                                display = display[:last_dot+1]
                            else:
                                display += '...'
                        news_lines.append(display)
                    
                    news_lines.append('')
                    news_lines.append(f'Источник: © [{source}]({link})')
                    photo_url = fetch_og_image(link)
            except:
                pass

        # Собираем пост в зависимости от типа
        if post_type == 'results':
            raw_caption = '\n'.join(match_lines) + ('' if not match_lines else '')
        else:
            raw_caption = '\n'.join(news_lines) + ('' if not news_lines else '')
        if post_type == 'results':
            pass  # empty results post handled by daily_results.py
        elif not raw_caption.strip():
            raw_caption = f"📡 Спорт-сводка"

        def send_single_post(chat, text, photo_src=None, use_md=False):
            """Отправляет один пост в чат. Если photo_src — локальный файл или URL — отправляет с фото."""
            plain = text.replace('*', '')
            try:
                inline_kb = {"inline_keyboard": [
                    [{"text": "📊 Статистика", "url": "https://t.me/ZulaSportNews_bot"}],
                ]}
                if photo_src and isinstance(photo_src, str) and os.path.exists(photo_src):
                    _data = {"chat_id": chat, "caption": text if use_md else plain,
                             "parse_mode": "Markdown" if use_md else "", "reply_markup": json.dumps(inline_kb)}
                    with open(photo_src, 'rb') as _bf:
                        _resp = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                            data=_data, files={"photo": _bf}, timeout=30)
                        r = _resp.json()
                elif photo_src and isinstance(photo_src, str) and photo_src.startswith('http'):
                    payload = {
                        'chat_id': chat, 'photo': photo_src,
                        'caption': text if use_md else plain,
                        'parse_mode': 'Markdown' if use_md else '',
                        'reply_markup': json.dumps(inline_kb),
                    }
                    _resp = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", json=payload, timeout=30)
                    r = _resp.json()
                else:
                    r = tg_api("sendMessage", chat_id=chat, text=text, parse_mode='Markdown' if use_md else '')
                if r and r.get('ok'):
                    logger.info(f"✅ Пост отправлен в {chat} — {len(text)} симв")
                    return True
                else:
                    logger.warning(f"send fail: {r.get('description','') if r else 'no response'}")
                    r2 = tg_api("sendMessage", chat_id=chat, text=plain)
                    return bool(r2 and r2.get('ok'))
            except Exception as e:
                logger.warning(f"send error: {e}")
                try:
                    r2 = tg_api("sendMessage", chat_id=chat, text=plain)
                    return bool(r2 and r2.get('ok'))
                except:
                    return False

        def send_to(targets):
            """Отправляет пост с баннером для результатов и предстоящих"""
            _photo = photo_url if photo_url and photo_url.startswith('http') else None
            # Для результатов — локальный баннер
            if post_type == 'results' and os.path.exists('/opt/banner.jpg'):
                _photo = '/opt/banner.jpg'
            for chat in targets:
                use_md = True
                send_single_post(chat, raw_caption, photo_src=_photo, use_md=use_md)

        if post_type != 'results':
            send_to([ALLOWED_CHANNEL, ALLOWED_GROUP])

        type_label = {'results': 'результаты 📊', 'news': 'новости 📰', 'upcoming': 'расписание 📅'}
        logger.info(f"Автопостинг {post_type} — {'📷' if photo_url else '📝'} {len(raw_caption)} символов")
    except Exception as e:
        import traceback
        logger.error(f"post_news: {e}\n{traceback.format_exc()}")


# ============================================================
# MAIN
# ============================================================

def main():
    logger.info("🚀 Sport News Bot (динамическая клавиатура)")

    # Принудительно сбрасываем allowed_updates при старте (исключает баг после очистки чата)
    try:
        r = requests.post(f"https://api.telegram.org/bot{TOKEN}/setWebhook",
            json={'url': '', 'allowed_updates': ['message', 'callback_query']}, timeout=10)
        if r.json().get('ok'):
            logger.info("Allowed updates reset: message + callback_query")
        else:
            logger.warning(f"Webhook reset: {r.json().get('description')}")
    except Exception as e:
        logger.warning(f"Webhook reset failed: {e}")

    STATE_FILE = '/opt/sport_bot_state.json'

    def load_state():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except:
            return {}

    def save_state(state):
        try:
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f)
        except:
            pass

    now_msk = now_mow()
    last_update_id = 0

    # Загружаем состояние после рестарта
    state = load_state()
    logger.info(f"Загружено состояние: last_post_ts={state.get('last_post_ts', 0)}")

    next_post_ts = 0  # будет инициализирован в цикле
    post_phase = None  # None | 'results' | 'news' | 'upcoming'

    while True:
        try:
            now_msk = now_mow()
            now_ts = now_msk.timestamp()
            current_hour = now_msk.hour

            # ===== ИНИЦИАЛИЗАЦИЯ: строим расписание на сегодня =====
            if next_post_ts == 0:
                day_start = now_msk.replace(hour=9, minute=0, second=0, microsecond=0).timestamp()
                day_end_upcoming = now_msk.replace(hour=23, minute=5, second=0, microsecond=0).timestamp()
                last_news_limit = now_msk.replace(hour=22, minute=50, second=0, microsecond=0).timestamp()

                if now_ts > day_end_upcoming:
                    next_post_ts = 0
                    logger.info("Постинг на сегодня завершён, ждём завтра 9:00")

                elif now_ts < day_start:
                    first_delay = random.randint(0, 15)
                    next_post_ts = day_start + first_delay * 60
                    post_phase = 'results'
                    logger.info(f"Расписание: результаты в {datetime.fromtimestamp(next_post_ts, tz=now_msk.tzinfo).strftime('%H:%M')}, затем новости ~каждые 40-60 мин, предстоящие ~22:50-23:05")

                else:
                    last_ts = state.get('last_post_ts', 0)
                    last_phase = state.get('post_phase', '')

                    if last_phase == 'upcoming' or last_ts > last_news_limit:
                        next_post_ts = 0
                        logger.info("Постинг уже завершён, ждём завтра")
                    elif last_phase == 'results' or (last_ts and last_ts < day_start + 30*60):
                        post_phase = 'news'
                        next_post_ts = now_ts + random.randint(1, 5) * 60
                        logger.info(f"Рестарт: следующая новость через несколько мин")
                    else:
                        post_phase = 'news'
                        delay_min = random.randint(40, 60)
                        next_post_ts = last_ts + delay_min * 60
                        if next_post_ts > last_news_limit:
                            next_post_ts = 0
                        else:
                            logger.info(f"Рестарт: новости в {datetime.fromtimestamp(next_post_ts, tz=now_msk.tzinfo).strftime('%H:%M')}")

            # ===== ПОСТИНГ =====
            if next_post_ts > 0 and now_ts >= next_post_ts:
                now_msk = now_mow()
                day_start_ts = now_msk.replace(hour=9, minute=0, second=0, microsecond=0).timestamp()
                last_news_limit = now_msk.replace(hour=22, minute=50, second=0, microsecond=0).timestamp()

                if post_phase == 'results':
                    logger.info("Постинг результатов...")
                    post_news_to_channel(now_msk, 'results')
                    state['last_post_ts'] = now_ts
                    state['post_phase'] = 'results'
                    save_state(state)
                    post_phase = 'news'
                    next_post_ts = now_ts + 15 * 60
                    logger.info(f"Первая новость через 15 мин (в ~{datetime.fromtimestamp(next_post_ts, tz=now_msk.tzinfo).strftime('%H:%M')})")

                elif post_phase == 'news':
                    if now_ts >= last_news_limit:
                        upcoming_delay = random.randint(0, 15)
                        next_post_ts = now_ts + upcoming_delay * 60
                        post_phase = 'upcoming'
                        logger.info(f"Переходим к предстоящим матчам")
                    else:
                        logger.info("Постинг новости...")
                        post_news_to_channel(now_msk, 'news')
                        state['last_post_ts'] = now_ts
                        state['post_phase'] = 'news'
                        save_state(state)
                        delay_min = random.randint(40, 60)
                        next_post_ts = now_ts + delay_min * 60
                        if next_post_ts >= last_news_limit:
                            upcoming_delay = random.randint(0, 15)
                            next_post_ts = last_news_limit + upcoming_delay * 60
                            post_phase = 'upcoming'
                            logger.info(f"Следующий пост: предстоящие матчи")
                        else:
                            logger.info(f"Следующая новость через {delay_min} мин (в {datetime.fromtimestamp(next_post_ts, tz=now_msk.tzinfo).strftime('%H:%M')})")

                elif post_phase == 'upcoming':
                    if now_ts >= now_msk.replace(hour=23, minute=5, second=0).timestamp():
                        logger.info("Пропускаем предстоящие — уже после 23:05")
                        next_post_ts = 0
                    else:
                        logger.info("Постинг предстоящих матчей...")
                        post_news_to_channel(now_msk, 'upcoming')
                        state['last_post_ts'] = now_ts
                        state['post_phase'] = 'upcoming'
                        save_state(state)
                        next_post_ts = 0
                        logger.info("Постинг на сегодня завершён")

            # getUpdates in subprocess — reliable non-blocking
            import subprocess as _sp, json as _json
            updates = None
            try:
                _code = f'''
import requests, json
try:
    r = requests.get("https://api.telegram.org/bot{TOKEN}/getUpdates",
        params={{"offset": {last_update_id + 1}, "timeout": 1, "allowed_updates": ["message", "callback_query"]}},
        timeout=(2, 2))
    if r.status_code == 200:
        print(json.dumps(r.json()))
except: pass
'''
                _r = _sp.run(['python3', '-c', _code], capture_output=True, text=True, timeout=4)
                if _r.stdout:
                    updates = _json.loads(_r.stdout)
            except:
                pass

            if updates and updates.get("ok"):
                for update in updates.get("result", []):
                    if "callback_query" in update:
                        cb = update["callback_query"]
                        cb_data = cb.get("data", "")
                        cb_chat = cb.get("message", {}).get("chat", {}).get("id")

                        if cb_data.startswith("period_"):
                            parts = cb_data.split("_", 2)
                            period = parts[1]  # live, today, tomorrow, yesterday
                            league_cmd = parts[2]

                            if period == "live":
                                msg = get_matches_for_league(league_cmd, ref_date, state_filter='live')
                            elif period == "today":
                                msg = get_matches_for_league(league_cmd, ref_date, state_filter='upcoming')
                            elif period == "tomorrow":
                                msg = get_matches_for_league(league_cmd, ref_date + timedelta(days=1), state_filter='upcoming')
                            elif period == "yesterday":
                                msg = get_matches_for_league(league_cmd, ref_date - timedelta(days=1), state_filter='finished')
                            else:
                                msg = "Неизвестный период"

                            # Edit the message to show results, remove keyboard
                            tg_api("editMessageText", chat_id=cb_chat, message_id=cb.get("message",{}).get("message_id"),
                                   text=msg, parse_mode="Markdown")
                            answer_callback(cb.get("id"))
                        elif cb_data == "expand_all":
                            try:
                                with open('/tmp/sport_expand.json') as _ef:
                                    _edata = json.load(_ef)
                                _html = _edata.get('html', 'Нет данных')
                                tg_api("editMessageText", chat_id=cb_chat,
                                    message_id=cb.get("message",{}).get("message_id"),
                                    text='📋 <b>Все результаты</b>\n\n' + _html, parse_mode="HTML")
                            except Exception as _ee:
                                tg_api("editMessageText", chat_id=cb_chat,
                                    message_id=cb.get("message",{}).get("message_id"),
                                    text='❌ Данные недоступны (перезапустите дайджест)')
                            answer_callback(cb.get("id"))
                        elif cb_data == "expand_all_upcoming":
                            try:
                                with open('/tmp/sport_expand_upcoming.json') as _ef:
                                    _edata = json.load(_ef)
                                _html = _edata.get('html', 'Нет данных')
                                tg_api("editMessageText", chat_id=cb_chat,
                                    message_id=cb.get("message",{}).get("message_id"),
                                    text='📋 <b>Предстоящие матчи — полный список</b>\n\n' + _html, parse_mode="HTML")
                            except Exception as _ee:
                                tg_api("editMessageText", chat_id=cb_chat,
                                    message_id=cb.get("message",{}).get("message_id"),
                                    text='❌ Данные недоступны (перезапустите дайджест)')
                            answer_callback(cb.get("id"))
                        elif cb_data.startswith("react_"):
                            # Reactions: increment counter on the button
                            _reaction_type = cb_data.replace("react_", "")
                            _reaction_labels = {
                                "fire": "🔥",
                                "like": "👍",
                                "wow": "😱",
                                "bad": "💩",
                            }
                            _emoji = _reaction_labels.get(_reaction_type, "❓")
                            answer_callback(cb.get("id"), text=f"{_emoji}")
                        else:
                            answer_callback(cb.get("id"))
                        last_update_id = update["update_id"]
                        continue

                    msg = update.get("message", {})
                    chat_id = msg.get("chat", {}).get("id")
                    text = msg.get("text", "").strip()

                    if chat_id == ALLOWED_GROUP or chat_id == ALLOWED_CHANNEL:
                        last_update_id = update["update_id"]
                        continue

                    if chat_id is not None and chat_id > 0:
                        ref_date = now_mow().date()
                        t_start = time.time()

                        # ===== НАВИГАЦИЯ =====

                        if text == '/clear':
                            send_message(chat_id, "🗑 Очищаю историю...")
                            try:
                                _cur_id = update.get('message', {}).get('message_id', 0)
                                _deleted = 0
                                _start_id = max(1, _cur_id - 5000)
                                # Delete from current message backwards
                                for _mid in range(_cur_id, _start_id - 1, -1):
                                    try:
                                        _r = requests.post(f"https://api.telegram.org/bot{TOKEN}/deleteMessage",
                                            json={"chat_id": chat_id, "message_id": _mid}, timeout=3)
                                        if _r.json().get('ok'):
                                            _deleted += 1
                                    except:
                                        pass
                                send_message(chat_id, f"✅ Удалено {_deleted} сообщений")
                            except Exception as _e:
                                send_message(chat_id, f"⚠ Ошибка: {_e}")

                        if text == '/start':
                            send_message(chat_id,
                                "🤖 *Sport News Bot*\n\n"
                                "Нажимай на кнопки внизу 👇\n\n"
                                "⚽ Футбол 🏒 Хоккей 🏀 Баскетбол 🎾 Теннис\n"
                                "— нажимаешь, клавиатура меняется на лиги\n\n"
                                "Или быстрые кнопки:\n"
                                "📅 Сегодня — все матчи дня\n"
                                "🔴 LIVE — что идёт сейчас\n"
                                "📊 Дайджест — полная сводка дня\n"
                                "📺 ТВ-гид — программа телеканалов",
                                reply_markup=keyboard_main())

                        # ===== СМЕНА КЛАВИАТУРЫ =====

                        elif text == "⚽ Футбол":
                            send_message(chat_id, "⚽ *Футбол*\n\nВыбери лигу:", reply_markup=keyboard_football())
                            logger.info(f"Total Футбол: {time.time()-t_start:.3f}s from msg to reply")
                        elif text == "🏒 Хоккей":
                            send_message(chat_id, "🏒 *Хоккей*\n\nВыбери лигу:", reply_markup=keyboard_hockey())
                        elif text == "🏀 Баскетбол":
                            send_message(chat_id, "🏀 *Баскетбол*\n\nВыбери лигу:", reply_markup=keyboard_basketball())
                        elif text == "🎾 Теннис":
                            send_message(chat_id, "🎾 *Теннис*\n\nВыбери турнир:", reply_markup=keyboard_tennis())
                        elif text == "🔙 Назад к видам спорта":
                            send_message(chat_id, "🏠 *Главное меню*\n\nВыбери вид спорта:", reply_markup=keyboard_main())

                        # ===== ЛИГИ =====

                        elif text in ("🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ", "🇪🇸 Ла Лига", "🇮🇹 Серия А", "🇩🇪 Бундеслига",
                                       "🇫🇷 Лига 1", "🇵🇹 Португалия", "🇷🇺 РПЛ",
                                       "🏆 ЛЧ", "🏆 ЛЕ",
                                       "🏒 КХЛ", "🏒 НХЛ",
                                       "🏀 НБА", "🏀 Евролига",
                                       "🎾 ATP", "🎾 WTA"):

                            league_map = {
                                '🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ': ('epl', 'АПЛ', '🏴󠁧󠁢󠁥󠁮󠁧󠁿'), '🇪🇸 Ла Лига': ('laliga', 'Ла Лига', '🇪🇸'), '🇮🇹 Серия А': ('seriea', 'Серия А', '🇮🇹'),
                                '🇩🇪 Бундеслига': ('bundesliga', 'Бундеслига', '🇩🇪'), '🇫🇷 Лига 1': ('ligue1', 'Лига 1', '🇫🇷'),
                                '🇵🇹 Португалия': ('portugal', 'Португалия', '🇵🇹'), '🇷🇺 РПЛ': ('rpl', 'РПЛ', '🇷🇺'),
                                '🏆 ЛЧ': ('ucl', 'Лига чемпионов', '🏆'), '🏆 ЛЕ': ('uel', 'Лига Европы', '🏆'),
                                '🏒 КХЛ': ('khl', 'КХЛ', '🏒'), '🏒 НХЛ': ('nhl', 'НХЛ', '🏒'),
                                '🏀 НБА': ('nba', 'НБА', '🏀'), '🏀 Евролига': ('euroleague', 'Евролига', '🏀'),
                                '🎾 ATP': ('atp', 'ATP', '🎾'), '🎾 WTA': ('wta', 'WTA', '🎾'),
                            }
                            cmd, lname, lemoji = league_map.get(text, (text, text, '⚽'))
                            period_keyboard = keyboard_periods(cmd, lname, lemoji)
                            send_message(chat_id, f"{lemoji} *{lname}*\n\nВыбери период:", reply_markup=period_keyboard)

                        # ===== КОМАНДЫ =====

                        elif text == "📅 Сегодня":
                            espn = get_espn(ref_date.strftime('%Y%m%d'))
                            send_message(chat_id, format_matches(espn, f"📅 Матчи {ref_date.strftime('%d.%m')}"))

                        elif text == "🔴 LIVE":
                            espn = get_espn(ref_date.strftime('%Y%m%d'))
                            ecl = [m for m in espn if m.get('state') == 'live']
                            if live:
                                send_message(chat_id, format_matches(live, "🔴 LIVE сейчас"))
                            else:
                                send_message(chat_id, "🔴 Сейчас LIVE матчей нет")

                        elif text == "📺 ТВ-гид":
                            send_message(chat_id, fetch_tv_guide_text(ref_date))

                        elif text == "📊 Дайджест":
                            try:
                                dg
                                results, plan = dg.run_daily()
                                send_message(chat_id, results + '\n\n' + plan)
                            except Exception as e:
                                send_message(chat_id, f"❌ Ошибка дайджеста: {e}")

                        elif text == "🔙 Главное меню":
                            send_message(chat_id, "🏠 *Главное меню*", reply_markup=keyboard_main())

                        elif text.startswith('/'):
                            cmd = text[1:].lower()
                            if cmd in ('today', 'live', 'digest', 'tv', 'rpl', 'khl', 'nhl', 'epl', 'laliga', 'seriea', 'bundesliga', 'ligue1', 'portugal', 'ucl', 'uel'):
                                cmds = {
                                    'today': '📅 Сегодня', 'live': '🔴 LIVE', 'digest': '📊 Дайджест', 'tv': '📺 ТВ-гид',
                                    'rpl': '🇷🇺 РПЛ', 'khl': '🏒 КХЛ', 'nhl': '🏒 НХЛ',
                                    'epl': '🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ', 'laliga': '🇪🇸 Ла Лига', 'seriea': '🇮🇹 Серия А',
                                    'bundesliga': '🇩🇪 Бундеслига', 'ligue1': '🇫🇷 Лига 1', 'portugal': '🇵🇹 Португалия',
                                    'ucl': '🏆 ЛЧ', 'uel': '🏆 ЛЕ',
                                }
                                # Simulate button press
                                btn_text = cmds.get(cmd, cmd)
                                import copy
                                msg_copy = copy.copy(msg)
                                msg_copy['text'] = btn_text
                                # Re-process
                                bt_map = {
                                    '📅 Сегодня': '📅 Сегодня', '🔴 LIVE': '🔴 LIVE',
                                    '📺 ТВ-гид': '📺 ТВ-гид', '📊 Дайджест': '📊 Дайджест',
                                    '🇷🇺 РПЛ': '🇷🇺 РПЛ', '🏒 КХЛ': '🏒 КХЛ', '🏒 НХЛ': '🏒 НХЛ',
                                    '🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ': '🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ', '🇪🇸 Ла Лига': '🇪🇸 Ла Лига',
                                    '🇮🇹 Серия А': '🇮🇹 Серия А', '🇩🇪 Бундеслига': '🇩🇪 Бундеслига',
                                    '🇫🇷 Лига 1': '🇫🇷 Лига 1', '🇵🇹 Португалия': '🇵🇹 Португалия',
                                }
                                # Just run the command directly
                                if cmd == 'today':
                                    espn = get_espn(ref_date.strftime('%Y%m%d'))
                                    send_message(chat_id, format_matches(espn, f"📅 Матчи {ref_date.strftime('%d.%m')}"))
                                elif cmd == 'live':
                                    espn = get_espn(ref_date.strftime('%Y%m%d'))
                                    ecl = [m for m in espn if m.get('state') == 'live']
                                    send_message(chat_id, format_matches(live, "🔴 LIVE сейчас") if ecl else "🔴 Сейчас нет LIVE")
                                elif cmd == 'digest':
                                    dg
                                    results, plan = dg.run_daily()
                                    send_message(chat_id, results + '\n\n' + plan)
                                elif cmd == 'tv':
                                    send_message(chat_id, fetch_tv_guide_text(ref_date))
                                else:
                                    msg_text = get_matches_for_league(cmd, ref_date)
                                    send_message(chat_id, msg_text)
                            else:
                                send_message(chat_id, "Команды: /today /live /digest /tv /rpl /khl /nhl /ucl /uel", reply_markup=keyboard_main())
                        else:
                            send_message(chat_id, "Нажимай на кнопки внизу 👇", reply_markup=keyboard_main())

                    last_update_id = update["update_id"]

            time.sleep(1)

        except KeyboardInterrupt:
            break
        except Exception as e:
            import traceback
            logger.error(f"Main loop: {e}\n{traceback.format_exc()}")
            time.sleep(10)


if __name__ == "__main__":
    main()
