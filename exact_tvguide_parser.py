#!/usr/bin/env python3
"""
ТОЧНЫЙ ПАРСЕР TV-GUIDE МАТЧ ТВ
Использует точные классы элементов для парсинга
"""

import requests
import re
import json
from datetime import datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup

def fetch_tvguide():
    """Получить TV Guide страницу"""
    print("🔄 Загружаем TV Guide...")
    
    try:
        url = "https://matchtv.ru/tvguide"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        print(f"✅ Получено {len(response.text)} символов")
        
        return response.text
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return None

def parse_with_exact_classes(html):
    """Парсить TV Guide используя точные классы элементов"""
    if not html:
        return []
    
    print("🔍 Парсим с использованием точных классов...")
    
    soup = BeautifulSoup(html, 'html.parser')
    all_broadcasts = []
    
    # 1. Находим все блоки каналов
    # Класс: p-tv-guide-schedule-channel-carcass
    channel_blocks = soup.find_all('div', class_='p-tv-guide-schedule-channel-carcass')
    
    print(f"📊 Найдено {len(channel_blocks)} блоков каналов")
    
    for channel_block in channel_blocks:
        try:
            # 2. Получаем информацию о канале
            channel_info = get_channel_info(channel_block)
            
            # 3. Находим все трансляции этого канала
            # Класс: p-tv-guide-schedule-channel-transmission
            transmissions = channel_block.find_all('div', class_='p-tv-guide-schedule-channel-transmission')
            
            for transmission in transmissions:
                try:
                    # 4. Парсим каждую трансляцию
                    broadcast = parse_transmission(transmission, channel_info)
                    if broadcast:
                        all_broadcasts.append(broadcast)
                except Exception as e:
                    continue
                    
        except Exception as e:
            print(f"⚠️  Ошибка при парсинге канала: {e}")
            continue
    
    return all_broadcasts

def get_channel_info(channel_block):
    """Получить информацию о канале"""
    channel_info = {
        'name': 'Неизвестный канал',
        'slug': 'unknown',
        'logo': None
    }
    
    # Ищем логотип канала
    # Класс: p-tv-guide-schedule-channel__logo-image
    logo_img = channel_block.find('img', class_='p-tv-guide-schedule-channel__logo-image')
    if logo_img:
        if 'alt' in logo_img.attrs:
            alt_text = logo_img['alt']
            # Извлекаем название канала из alt текста
            if 'Логотип канала' in alt_text:
                channel_info['name'] = alt_text.replace('Логотип канала ', '')
        
        if 'src' in logo_img.attrs:
            channel_info['logo'] = logo_img['src']
    
    # Ищем ссылку на канал для определения slug
    # Класс: p-tv-guide-schedule-channel__logo-wrapper
    channel_link = channel_block.find('a', class_='p-tv-guide-schedule-channel__logo-wrapper')
    if channel_link and 'href' in channel_link.attrs:
        href = channel_link['href']
        # Извлекаем slug из URL: /tvguide/premier → premier
        slug_match = re.search(r'/tvguide/([^/]+)', href)
        if slug_match:
            channel_info['slug'] = slug_match.group(1)
    
    return channel_info

def parse_transmission(transmission, channel_info):
    """Парсить одну трансляцию"""
    # 1. Время трансляции
    # Класс: p-tv-guide-schedule-channel-transmission__time-block-time
    time_elem = transmission.find('span', class_='p-tv-guide-schedule-channel-transmission__time-block-time')
    if not time_elem:
        return None
    
    time_str = time_elem.get_text(strip=True)
    
    # 2. Название трансляции
    # Класс: p-tv-guide-schedule-channel-transmission__title
    title_elem = transmission.find('span', class_='p-tv-guide-schedule-channel-transmission__title')
    if not title_elem:
        return None
    
    title = title_elem.get_text(strip=True)
    
    # 3. Проверяем, является ли это прямой трансляцией
    # Класс: p-tv-guide-schedule-channel-transmission__live-icon (иконка live)
    is_live_icon = bool(transmission.find('svg', class_='p-tv-guide-schedule-channel-transmission__live-icon'))
    
    # 4. Проверяем текст на "Прямая трансляция"
    is_live_text = 'прямая трансляция' in title.lower()
    
    # 5. Определяем, является ли это прямой трансляцией
    is_live = is_live_icon or is_live_text
    
    # 6. Ссылка (если есть)
    link = None
    link_elem = transmission.find('a', href=True)
    if link_elem and 'href' in link_elem.attrs:
        href = link_elem['href']
        if not href.startswith('http'):
            href = urljoin('https://matchtv.ru', href)
        link = href
    
    # 7. Определяем вид спорта
    sport = detect_sport(title)
    
    # 8. Определяем, является ли это спортивной трансляцией
    is_sports = sport != 'другой'
    
    # 9. Статус трансляции
    status = 'запланировано'
    if is_live:
        status = 'в эфире'
    
    broadcast = {
        'channel': channel_info['name'],
        'channel_slug': channel_info['slug'],
        'time': time_str,
        'title': title,
        'sport': sport,
        'is_live': is_live,
        'is_live_icon': is_live_icon,
        'is_live_text': is_live_text,
        'is_sports': is_sports,
        'link': link,
        'status': status,
        'parsed_at': datetime.now().isoformat()
    }
    
    return broadcast

def detect_sport(title):
    """Определить вид спорта по названию"""
    title_lower = title.lower()
    
    sports_map = {
        'футбол': ['футбол', 'football', 'чемпионат', 'лига', 'кубок', 'рпл', 'уефа', 'premier'],
        'хоккей': ['хоккей', 'hockey', 'нхл', 'кхл'],
        'баскетбол': ['баскетбол', 'basketball'],
        'теннис': ['теннис', 'tennis'],
        'волейбол': ['волейбол', 'volleyball'],
        'бокс': ['бокс', 'boxing', 'ufc', 'мма', 'единоборств'],
        'гминастика': ['гминастик', 'gymnastics'],
        'плавание': ['плавани', 'swimming'],
        'тяжелая атлетика': ['тяжелая атлетика', 'weightlifting'],
        'автоспорт': ['автоспорт', 'formula', 'f1', 'гонк', 'ралли'],
        'дзюдо': ['дзюдо', 'judo'],
        'гандбол': ['гандбол', 'handball'],
        'регби': ['регби', 'rugby'],
        'биатлон': ['биатлон', 'biathlon'],
        'лыжи': ['лыж', 'ski'],
        'коньки': ['коньк', 'skating'],
    }
    
    for sport, keywords in sports_map.items():
        for keyword in keywords:
            if keyword in title_lower:
                return sport
    
    return 'другой'

def filter_only_live_sports(broadcasts):
    """Фильтровать ТОЛЬКО прямые спортивные трансляции"""
    filtered = []
    
    for b in broadcasts:
        # Только прямые (иконка live ИЛИ текст "прямая трансляция") И спортивные
        if (b['is_live'] and b['is_sports']):
            filtered.append(b)
    
    # Убираем дубликаты (одинаковое время и название)
    unique = []
    seen = set()
    
    for b in filtered:
        key = (b['time'], b['title'][:50])  # Первые 50 символов названия
        if key not in seen:
            seen.add(key)
            unique.append(b)
    
    # Сортируем по времени
    def extract_time(time_str):
        try:
            hours, minutes = map(int, time_str.split(':'))
            return hours * 60 + minutes
        except:
            return 9999
    
    unique.sort(key=lambda x: extract_time(x['time']))
    
    return unique

def print_results(broadcasts):
    """Вывести результаты"""
    if not broadcasts:
        print("\n❌ Прямых спортивных трансляций не найдено")
        return
    
    today = datetime.now().strftime('%d.%m.%Y')
    print(f"\n📡 ПРЯМЫЕ СПОРТИВНЫЕ ТРАНСЛЯЦИИ МАТЧ ТВ ({today}):")
    print("=" * 70)
    
    # Группируем по каналам
    channels = {}
    for b in broadcasts:
        channel = b['channel']
        if channel not in channels:
            channels[channel] = []
        channels[channel].append(b)
    
    total_count = 0
    
    for channel_name, channel_broadcasts in channels.items():
        print(f"\n📡 {channel_name.upper()}:")
        print("-" * 50)
        
        for i, b in enumerate(channel_broadcasts, 1):
            sport_emoji = {
                'футбол': '⚽',
                'хоккей': '🏒',
                'баскетбол': '🏀',
                'теннис': '🎾',
                'волейбол': '🏐',
                'бокс': '🥊',
                'плавание': '🏊',
                'гминастика': '🤸',
                'автоспорт': '🏎️',
                'тяжелая атлетика': '🏋️',
                'дзюдо': '🥋',
                'гандбол': '🤾',
                'регби': '🏉',
                'биатлон': '🎯',
                'лыжи': '⛷️',
                'коньки': '⛸️',
            }.get(b['sport'], '📺')
            
            live_mark = "🔴 " if b['is_live_icon'] else "   "
            text_mark = "📝" if b['is_live_text'] else ""
            
            print(f"{i}. {live_mark}{b['time']} {sport_emoji} {text_mark} {b['title']}")
            
            if b['link']:
                print(f"   🔗 {b['link']}")
        
        total_count += len(channel_broadcasts)
        print(f"   📊 На канале: {len(channel_broadcasts)} трансляций")
    
    print(f"\n📊 ИТОГО: {total_count} прямых спортивных трансляций")
    print(f"   📡 Каналов: {len(channels)}")

def save_telegram_format(broadcasts):
    """Сохранить в формате для Telegram"""
    if not broadcasts:
        return None
    
    today = datetime.now().strftime('%Y%m%d_%H%M')
    telegram_file = f"/tmp/matchtv_exact_live_telegram_{today}.txt"
    
    with open(telegram_file, 'w', encoding='utf-8') as f:
        date_display = datetime.now().strftime('%d.%m.%Y')
        f.write(f"📡 *ПРЯМЫЕ СПОРТИВНЫЕ ТРАНСЛЯЦИИ МАТЧ ТВ* ({date_display}):\n\n")
        
        # Группируем по каналам
        channels = {}
        for b in broadcasts:
            channel = b['channel']
            if channel not in channels:
                channels[channel] = []
            channels[channel].append(b)
        
        for channel_name, channel_broadcasts in channels.items():
            f.write(f"*{channel_name.upper()}*:\n")
            
            for i, b in enumerate(channel_broadcasts[:8], 1):  # Ограничим 8 на канал
                sport_emoji = {
                    'футбол': '⚽',
                    'хоккей': '🏒',
                    'баскетбол': '🏀',
                    'теннис': '🎾',
                    'волейбол': '🏐',
                    'бокс': '🥊',
                    'плавание': '🏊',
                    'гминастика': '🤸',
                    'автоспорт': '🏎️',
                }.get(b['sport'], '📺')
                
                # Добавляем пометку о типе прямой трансляции
                live_type = ""
                if b['is_live_icon'] and b['is_live_text']:
                    live_type = "🔴📝 "
                elif b['is_live_icon']:
                    live_type = "🔴 "
                elif b['is_live_text']:
                    live_type = "📝 "
                
                f.write(f"{i}. *{b['time']}* {live_type}{sport_emoji} {b['title'][:80]}")
                if len(b['title']) > 80:
                    f.write("...")
                f.write("\n")
            
            f.write("\n")
    
    return telegram_file

def main():
    """Основная функция"""
    print("=" * 70)
    print("🎯 ТОЧНЫЙ ПАРСЕР TV-GUIDE МАТЧ ТВ")
    print("Использует точные классы элементов")
    print("=" * 70)
    
    # Получаем TV Guide
    html = fetch_tvguide()
    if not html:
        return
    
    # Парсим с использованием точных классов
    all_broadcasts = parse_with_exact_classes(html)
    
    print(f"\n📊 Найдено всего: {len(all_broadcasts)} трансляций")
    
    # Фильтруем спортивные
    sports_broadcasts = [b for b in all_broadcasts if b['is_sports']]
    print(f"📊 Спортивных: {len(sports_broadcasts)}")
    
    # Фильтруем ТОЛЬКО прямые спортивные
    live_sports_broadcasts = filter_only_live_sports(sports_broadcasts)
    print(f"📊 Прямых спортивных: {len(live_sports_broadcasts)}")
    
    # Выводим результаты
    if live_sports_broadcasts:
        print_results(live_sports_broadcasts)
        
        # Сохраняем для Telegram
        telegram_file = save_telegram_format(live_sports_broadcasts)
        
        print(f"\n💾 Сохранено для Telegram: {telegram_file}")
        
        print(f"\n📋 Пример сообщения:")
        print("-" * 40)
        with open(telegram_file, 'r', encoding='utf-8') as f:
            print(f.read())
    else:
        print("\n⚠️  Прямых спортивных трансляций не найдено")
        
        # Показываем какие трансляции есть (не прямые)
        if sports_broadcasts:
            print("\n📊 Найдены спортивные трансляции (не прямые):")
            for b in sports_broadcasts[:5]:
                print(f"  {b['time']} - {b['title'][:60]}...")

if __name__ == "__main__":
    main()