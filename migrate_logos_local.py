#!/usr/bin/env python3
"""
Перенести логотипы команд с SStats CDN на локальное хранение.

1. Для каждой команды с logo_url из SStats — ищем локальный файл
2. Если нет — качаем с SStats и сохраняем в /var/www/sport/static/logos/
3. Обновляем logo_url в БД на /static/logos/ID.png
"""

import os, sys, json, requests, time
sys.path.insert(0, '/opt')
from db import execute, execute_one

# Пути
LOGO_DIR = '/var/www/sport/static/logos'
TEAM_LOGOS_PATH = '/opt/team_logos.json'
os.makedirs(LOGO_DIR, exist_ok=True)

# Загружаем team_logos.json
with open(TEAM_LOGOS_PATH, encoding='utf-8') as f:
    logos_data = json.load(f)
logo_map = logos_data.get('teams', {})  # name -> {url, ru} or url string


def find_local_logo(team_name, sstats_id=None):
    """Поиск локального файла логотипа."""
    # 1. По имени (каноническое или ru)
    for lookup_name in [team_name]:
        info = logo_map.get(lookup_name)
        if isinstance(info, dict):
            url = info.get('url', '')
            if url and url.startswith('/static/'):
                return url
        elif isinstance(info, str) and info.startswith('/static/'):
            return info
    
    # 2. По ru-полю
    for key, info in logo_map.items():
        if isinstance(info, dict) and info.get('ru') == team_name:
            url = info.get('url', '')
            if url and url.startswith('/static/'):
                return url
    
    return None


def download_logo(sstats_id, team_name):
    """Скачать логотип с SStats."""
    import os
    key = open("/etc/sstats.key").read().strip()
    if not key or not sstats_id:
        return None
    
    url = f'https://sstats.net/assets/logos/{sstats_id}.png'
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200 and len(r.content) > 100:
            filename = f'{sstats_id}.png'
            filepath = os.path.join(LOGO_DIR, filename)
            with open(filepath, 'wb') as f:
                f.write(r.content)
            print(f'  📥 Скачан: {filename} ({len(r.content)} байт)')
            return f'/static/logos/{filename}'
    except:
        pass
    return None


def migrate():
    teams = execute("SELECT id, canonical_name, sstats_id, logo_url FROM teams WHERE logo_url IS NOT NULL AND logo_url != ''")
    print(f'Команд с logo_url: {len(teams)}')
    
    updated = 0
    downloaded = 0
    
    for t in teams:
        name = t['canonical_name']
        sid = t['sstats_id']
        current_logo = t['logo_url']
        
        # Уже локальный?
        if current_logo and '/static/' in current_logo:
            continue
        
        # Ищем локальный
        local_url = find_local_logo(name, sid)
        
        # Если не нашли — качаем
        if not local_url and sid:
            local_url = download_logo(sid, name)
            if local_url:
                downloaded += 1
        
        # Обновляем в БД
        if local_url and local_url != current_logo:
            execute("UPDATE teams SET logo_url = %s WHERE id = %s", (local_url, t['id']))
            updated += 1
            print(f'  ✅ {name}: {os.path.basename(local_url)}')
    
    print(f'\n📊 Обновлено в БД: {updated}')
    print(f'📥 Скачано с SStats: {downloaded}')
    
    total = execute_one("SELECT COUNT(*) AS c FROM teams WHERE logo_url IS NOT NULL AND logo_url != ''")
    local = execute_one("SELECT COUNT(*) AS c FROM teams WHERE logo_url LIKE '/static/%'")
    print(f'Команд с лого: {total["c"]}, из них локальных: {local["c"]}')


if __name__ == '__main__':
    migrate()
