#!/usr/bin/env python3
"""Парсер TV Guide Матч ТВ — извлечение программы всех каналов"""
import requests, re, json, html
from datetime import datetime, timezone, timedelta

MOW = timedelta(hours=3)

CHANNEL_NAMES = {
    'matchtv': 'Матч ТВ',
    'premier': 'Матч! Премьер',
    'strana': 'Матч! Страна',
    'futbol-1': 'Матч! Футбол 1',
    'futbol-2': 'Матч! Футбол 2',
    'futbol-3': 'Матч! Футбол 3',
    'arena': 'Матч! Арена',
    'igra': 'Матч! Игра',
    'boec': 'Матч! Боец',
    'konnyj-mir': 'Конный мир',
}

def fetch_tvguide(date_str=None):
    """Получить программу всех каналов Матч ТВ"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    url = 'https://matchtv.ru/tvguide'
    if date_str:
        url += f'?date={date_str}'
    resp = requests.get(url, headers=headers, timeout=15)
    text = resp.text
    
    # Разделяем по каналам (по логотипу)
    parts = re.split(r'alt=\"Логотип канала ', text)
    
    channels = {}
    for part in parts[1:]:
        # Имя канала
        name_match = re.search(r'([^\"]+)', part)
        if not name_match: continue
        name = name_match.group(1)
        
        # Все передачи
        times = re.findall(r'transmission__time-block-time[^>]*>([^<]+)', part)
        titles = re.findall(r'transmission__title[^>]*>([^<]+)', part)
        
        programs = []
        for j in range(min(len(times), len(titles))):
            t = times[j].strip()
            title = html.unescape(titles[j].strip())
            programs.append({'time': t, 'title': title})
        
        channels[name] = programs
    
    return channels


def find_sport_broadcasts(channels):
    """Найти спортивные трансляции (футбол/хоккей)"""
    today = datetime.now(timezone.utc) + MOW
    results = []
    
    sport_keywords = ['футбол', 'хоккей', 'рпл', 'кхл', 'чемпионат', 'премьер-лига']
    
    for ch_name, programs in channels.items():
        for prog in programs:
            title_lower = prog['title'].lower()
            if any(kw in title_lower for kw in sport_keywords):
                results.append({
                    'channel': ch_name,
                    'time': prog['time'],
                    'title': prog['title'],
                })
    
    return results


def find_match_channel(match, channels):
    """Найти на каком канале Матч ТВ идёт матч"""
    t1 = match['team1'].lower()[:6]
    t2 = match['team2'].lower()[:6]
    
    found_channels = []
    for ch_name, programs in channels.items():
        for prog in programs:
            title_lower = prog['title'].lower()
            # Ищем совпадение по командам
            if t1 in title_lower and t2 in title_lower:
                found_channels.append(ch_name)
    
    return found_channels


def get_all_tv_channels(date_str=None):
    """Получить программу со всеми каналами"""
    return fetch_tvguide(date_str)


def find_real_channel(match, channels):
    """Найти реальный канал Матч ТВ для матча"""
    t1 = match['team1'].lower().strip()[:6]
    t2 = match['team2'].lower().replace('тольятти', '').strip()[:6]
    t2 = t2[:5] if t2 and t2[-1] == ' ' else t2[:6]
    
    # Маппинг имён каналов из TV Guide -> короткие названия
    channel_short = {
        'Матч ТВ': 'Матч ТВ',
        'Матч Премьер': 'Матч! Премьер',
        'Матч Страна': 'Матч! Страна',
        'Футбол 1': 'Матч! Футбол 1',
        'Футбол 2': 'Матч! Футбол 2',
        'Футбол 3': 'Матч! Футбол 3',
        'Матч Арена': 'Матч! Арена',
        'Матч Игра': 'Матч! Игра',
        'Матч Боец': 'Матч! Боец',
        'Конный мир': 'Конный мир',
    }
    
    found = []
    for ch_name, programs in channels.items():
        short = channel_short.get(ch_name, ch_name)
        for prog in programs:
            title_lower = prog['title'].lower()
            # Убираем кавычки и скобки для сравнения
            clean_title = title_lower.replace('"', '').replace('«', '').replace('»', '').replace('(', '').replace(')', '')
            if t1 in clean_title and t2 in clean_title:
                if short not in found:
                    found.append(short)
    
    return found


if __name__ == '__main__':
    channels = get_all_tv_channels()
    print(f'Каналов: {len(channels)}')
    for name, progs in channels.items():
        print(f'\n=== {name} ({len(progs)}) ===')
        for p in progs[:5]:
            print(f'  {p["time"]} | {p["title"][:80]}')
    
    print('\n\n=== Спортивные трансляции ===')
    sport = find_sport_broadcasts(channels)
    for s in sport:
        print(f'  [{s["channel"]}] {s["time"]} | {s["title"][:80]}')
