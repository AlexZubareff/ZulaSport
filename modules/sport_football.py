#!/usr/bin/env python3
"""
Модуль прогнозов на футбол (делегирует capper_pipeline.py).

Используется единым оркестратором: capper_pipeline.py --sport football

Режимы: --batch, --refresh
"""

import sys, os

sys.path.insert(0, '/opt')

SPORT = 'football'

# Уже существует: capper_pipeline.py (основной пайплайн для футбола)
# Этот модуль — тонкая обёртка для единого формата оркестратора.


def run(mode: str = 'batch', force_refresh: bool = False):
    """Запустить футбольный пайплайн.

    Args:
        mode: 'batch' | 'refresh'
        force_refresh: пропустить кеш DeepSeek
    """
    # Импортируем существующий пайплайн
    from capper_pipeline import batch_generate, batch_refresh

    if mode == 'refresh':
        batch_refresh()
    else:
        batch_generate()
