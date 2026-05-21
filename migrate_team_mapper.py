#!/usr/bin/env python3
"""
Миграция team_mapper.py → таблицы teams + team_aliases.
"""

import sys
sys.path.insert(0, '/opt')
import team_mapper
from db import execute, execute_one

def migrate_teams():
    """Извлечь команды и алиасы из team_mapper и загрузить в БД."""
    # Получаем все канонические имена и алиасы
    import importlib
    importlib.reload(team_mapper)
    
    # Достаём алиасы напрямую из модуля
    aliases = getattr(team_mapper, '_ALIAS_TO_CANON', {})
    if not aliases:
        print('❌ Не удалось прочитать _ALIAS_TO_CANON')
        return
    
    # Группируем алиасы по каноническим именам
    canon_to_aliases = {}
    for alias, canon in aliases.items():
        if canon not in canon_to_aliases:
            canon_to_aliases[canon] = set()
        canon_to_aliases[canon].add(alias)
    
    print(f'📊 Найдено канонических имён: {len(canon_to_aliases)}')
    
    inserted_teams = 0
    inserted_aliases = 0
    
    for canon, alias_set in sorted(canon_to_aliases.items()):
        # Вставляем команду
        execute("""
            INSERT INTO teams (canonical_name)
            VALUES (%s)
            ON CONFLICT (canonical_name) DO UPDATE SET canonical_name = EXCLUDED.canonical_name
        """, (canon,))
        
        # Получаем ID
        team = execute_one("SELECT id FROM teams WHERE canonical_name = %s", (canon,))
        if not team:
            continue
        team_id = team['id']
        inserted_teams += 1
        
        # Алиасы
        for alias in alias_set:
            if alias == canon.lower():
                continue  # сам канон — не алиас
            try:
                execute("""
                    INSERT INTO team_aliases (team_id, alias, lang)
                    VALUES (%s, %s, 'ru')
                    ON CONFLICT (team_id, alias) DO NOTHING
                """, (team_id, alias))
                inserted_aliases += 1
            except:
                pass
    
    print(f'✅ Команд: {inserted_teams}')
    print(f'✅ Алиасов: {inserted_aliases}')
    
    # Проверка
    count = execute_one("SELECT COUNT(*) AS c FROM teams")
    print(f'\n📊 В БД: {count["c"] if count else 0} команд')


if __name__ == '__main__':
    migrate_teams()
