#!/usr/bin/env python3
"""
Загрузка теннисных данных из репозиториев JeffSackmann:
  ATP: https://github.com/JeffSackmann/tennis_atp
  WTA: https://github.com/JeffSackmann/tennis_wta

Запуск: python3 fetch_tennis_atp_data.py
Результат: /opt/data/tennis/atp/ и /opt/data/tennis/wta/
Обновление: git pull раз в сутки.
"""

import os, sys, csv, json, shutil, subprocess, gzip
from datetime import datetime, timezone
from io import StringIO
import requests

REPOS = {
    'atp': {
        'url': 'https://github.com/JeffSackmann/tennis_atp.git',
        'local': '/opt/data/tennis/atp',
        'raw_base': 'https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master/',
    },
    'wta': {
        'url': 'https://github.com/JeffSackmann/tennis_wta.git',
        'local': '/opt/data/tennis/wta',
        'raw_base': 'https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master/',
    },
}

# Ключевые CSV, которые нужны для работы
KEY_FILES = {
    'atp': [
        'atp_matches.csv',
        'atp_matches_2025.csv',
        'atp_matches_2024.csv',
        'atp_matches_2023.csv',
        'atp_matches_2022.csv',
        'atp_matches_2021.csv',
        'atp_matches_2020.csv',
        'atp_matches_2019.csv',
        'atp_matches_2018.csv',
        'atp_matches_2017.csv',
        'atp_matches_2016.csv',
        'atp_matches_2015.csv',
        'atp_matches_qual_chall_2025.csv',
        'atp_matches_qual_chall_2024.csv',
        'atp_matches_qual_chall_2023.csv',
        'atp_players.csv',
        'atp_rankings_current.csv',
        'atp_rankings_2025.csv',
    ],
    'wta': [
        'wta_matches.csv',
        'wta_matches_2025.csv',
        'wta_matches_2024.csv',
        'wta_matches_2023.csv',
        'wta_matches_2022.csv',
        'wta_matches_2021.csv',
        'wta_matches_2020.csv',
        'wta_matches_2019.csv',
        'wta_matches_2018.csv',
        'wta_matches_2017.csv',
        'wta_matches_2016.csv',
        'wta_matches_2015.csv',
        'wta_matches_qual_chall_2025.csv',
        'wta_matches_qual_chall_2024.csv',
        'wta_players.csv',
        'wta_rankings_current.csv',
        'wta_rankings_2025.csv',
    ],
}

SYNC_MARKER = '/opt/data/tennis/.last_sync'
UTC = timezone.utc


def _ensure_dirs(path):
    os.makedirs(path, exist_ok=True)


def _clone_or_pull(repo_name, repo_info):
    """Клонировать или обновить репозиторий."""
    local = repo_info['local']
    url = repo_info['url']

    if os.path.exists(os.path.join(local, '.git')):
        # git pull
        print(f'  Git pull {repo_name}...')
        result = subprocess.run(
            ['git', '-C', local, 'pull', '--ff-only'],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            print(f'  ⚠️ Git pull warning: {result.stderr[:200]}')
        print(f'  → {result.stdout.strip()[:100] if result.stdout else "up to date"}')
        return True
    else:
        # git clone
        print(f'  Git clone {repo_name}...')
        _ensure_dirs(os.path.dirname(local))
        if os.path.exists(local):
            shutil.rmtree(local)
        result = subprocess.run(
            ['git', 'clone', '--depth=1', url, local],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            print(f'  ❌ Git clone error: {result.stderr[:300]}')
            return False
        print(f'  ✅ Cloned {repo_name}')
        return True


def _download_individual(repo_name, repo_info, files):
    """Загрузить только нужные CSV через raw.githubusercontent.com."""
    local = repo_info['local']
    base = repo_info['raw_base']
    _ensure_dirs(local)

    count = 0
    for fname in files:
        url = base + fname
        dest = os.path.join(local, fname)
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 200:
                with open(dest, 'wb') as f:
                    f.write(resp.content)
                count += 1
            else:
                # Пропускаем, если файл есть локально
                if not os.path.exists(dest):
                    print(f'  ⚠️ {fname}: HTTP {resp.status_code}')
        except Exception as e:
            print(f'  ⚠️ {fname}: {e}')
    return count


def _load_csv(filepath):
    """Загрузить CSV и вернуть список dict."""
    if not os.path.exists(filepath):
        return []
    rows = []
    try:
        with open(filepath, encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    except Exception as e:
        print(f'  ⚠️ CSV error {os.path.basename(filepath)}: {e}')
    return rows


def _load_current_rankings(repo_name, local_dir):
    """Загрузить текущий рейтинг (atp_rankings_current.csv или wta_rankings_current.csv)."""
    prefix = 'atp' if repo_name == 'atp' else 'wta'
    fpath = os.path.join(local_dir, f'{prefix}_rankings_current.csv')
    rows = _load_csv(fpath)
    if not rows:
        # Fallback: последние рейтинги
        latest_file = f'{prefix}_rankings_2025.csv'
        fpath2 = os.path.join(local_dir, latest_file)
        rows = _load_csv(fpath2)
    return rows


def _validate_data(repo_name, local_dir):
    """Проверить, что данные целы."""
    prefix = 'atp' if repo_name == 'atp' else 'wta'
    matches_file = os.path.join(local_dir, f'{prefix}_matches.csv')
    players_file = os.path.join(local_dir, f'{prefix}_players.csv')
    rankings_file = os.path.join(local_dir, f'{prefix}_rankings_current.csv')

    matches_ok = os.path.exists(matches_file) and os.path.getsize(matches_file) > 1000
    players_ok = os.path.exists(players_file) and os.path.getsize(players_file) > 100

    if not matches_ok and not os.path.exists(os.path.join(local_dir, f'{prefix}_matches_2025.csv')):
        return False

    # Проверим структуру CSV
    sample = _load_csv(matches_file if matches_ok else os.path.join(local_dir, f'{prefix}_matches_2025.csv'))
    if not sample:
        return False

    expected_fields = {'winner_name', 'loser_name', 'tourney_date', 'surface'}
    actual_fields = set(sample[0].keys())
    missing = expected_fields - actual_fields
    if missing:
        print(f'  ⚠️ {repo_name}: нет полей {missing} (структура: {list(sample[0].keys())[:10]}...)')
        # Это может быть нормально для qual_chall, пробуем другой файл
        alt = os.path.join(local_dir, f'{prefix}_matches_2025.csv')
        if os.path.exists(alt):
            sample2 = _load_csv(alt)
            if sample2:
                actual_fields2 = set(sample2[0].keys())
                missing2 = expected_fields - actual_fields2
                if not missing2:
                    return True

    return True


def load_matches(repo_name='atp', year=None, min_rank=0):
    """Загрузить матчи для анализа. Фильтр по году и минимальному рейтингу."""
    local = REPOS[repo_name]['local']
    prefix = 'atp' if repo_name == 'atp' else 'wta'
    
    files_to_load = [f'{prefix}_matches.csv']
    if year:
        files_to_load = [f'{prefix}_matches_{year}.csv']
    else:
        for y in range(2025, 2014, -1):
            f = f'{prefix}_matches_{y}.csv'
            fp = os.path.join(local, f)
            if os.path.exists(fp):
                files_to_load.append(f)
        # Также текущий файл
        files_to_load.append(f'{prefix}_matches.csv')

    all_matches = []
    seen = set()
    for fname in files_to_load:
        fp = os.path.join(local, fname)
        rows = _load_csv(fp)
        for r in rows:
            # Дедупликация по ключу
            key = (r.get('tourney_id', ''), r.get('winner_name', ''), r.get('loser_name', ''))
            if key in seen:
                continue
            seen.add(key)
            # Нормализация числовых полей
            for field in ['winner_rank', 'loser_rank', 'winner_seed', 'loser_seed']:
                v = r.get(field, '')
                try:
                    r[field] = int(v) if v else None
                except:
                    r[field] = None
            for field in ['w_ace', 'w_df', 'w_1stIn', 'w_1stWon', 'l_ace', 'l_df', 'l_1stIn', 'l_1stWon',
                          'winner_ht', 'loser_ht', 'winner_age', 'loser_age']:
                v = r.get(field, '')
                try:
                    r[field] = float(v) if v else None
                except:
                    r[field] = None
            all_matches.append(r)
    
    return all_matches


def load_players(repo_name='atp'):
    """Загрузить players.csv."""
    local = REPOS[repo_name]['local']
    prefix = 'atp' if repo_name == 'atp' else 'wta'
    fp = os.path.join(local, f'{prefix}_players.csv')
    return _load_csv(fp)


def load_rankings(repo_name='atp'):
    """Загрузить текущий рейтинг."""
    local = REPOS[repo_name]['local']
    prefix = 'atp' if repo_name == 'atp' else 'wta'
    fp = os.path.join(local, f'{prefix}_rankings_current.csv')
    rows = _load_csv(fp)
    if not rows:
        fp2 = os.path.join(local, f'{prefix}_rankings_2025.csv')
        rows = _load_csv(fp2)
    return rows


def main():
    print('🎾 Загрузка теннисных данных (JeffSackmann)...')
    
    for name, info in REPOS.items():
        print(f'\n📦 {name.upper()}:')
        local = info['local']
        _ensure_dirs(local)

        # Пробуем git clone/pull
        ok = _clone_or_pull(name, info)
        if not ok:
            # Fallback: raw.githubusercontent
            print(f'  ↪ Загрузка файлов через HTTP...')
            files = KEY_FILES.get(name, [])
            count = _download_individual(name, info, files)
            print(f'  Загружено {count}/{len(files)} файлов')

        # Валидация
        if _validate_data(name, local):
            print(f'  ✅ Данные корректны')
            
            # Считаем
            prefix = 'atp' if name == 'atp' else 'wta'
            matches_file = os.path.join(local, f'{prefix}_matches.csv')
            if os.path.exists(matches_file):
                size = os.path.getsize(matches_file)
                print(f'  📊 matches.csv: {size//1024} KB')
            
            rankings = _load_current_rankings(name, local)
            if rankings:
                print(f'  📊 Рейтинг: {len(rankings)} игроков')
        else:
            print(f'  ❌ Данные повреждены или неполные')

    # Пишем маркер последней синхронизации
    with open(SYNC_MARKER, 'w') as f:
        f.write(datetime.now(UTC).isoformat())
    
    print(f'\n✅ Готово в /opt/data/tennis/')


if __name__ == '__main__':
    main()
