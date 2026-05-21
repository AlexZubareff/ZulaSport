#!/usr/bin/env python3
"""
Модуль прогнозов на НХЛ (делегирует capper_pipeline_nhl.py).

Используется единым оркестратором: capper_pipeline.py --sport nhl

Режимы: --batch, --refresh
"""

import sys, os

sys.path.insert(0, '/opt')

SPORT = 'nhl'
LEAGUE_NAME = 'НХЛ'


def run(mode: str = 'batch', force_refresh: bool = False):
    """Запустить NHL пайплайн.

    Args:
        mode: 'batch' | 'refresh'
        force_refresh: пропустить кеш DeepSeek
    """
    # Импортируем существующий пайплайн
    from capper_pipeline_nhl import batch_generate, batch_refresh

    if mode == 'refresh':
        batch_refresh()
    else:
        batch_generate()
