#!/usr/bin/env python3
"""
Модуль прогнозов на NBA (делегирует capper_pipeline_nba.py).

Используется единым оркестратором: capper_pipeline.py --sport nba

Режимы: --batch, --refresh
"""

import sys, os

sys.path.insert(0, '/opt')

SPORT = 'nba'
LEAGUE_NAME = 'NBA'


def run(mode: str = 'batch', force_refresh: bool = False):
    """Запустить NBA пайплайн.

    Args:
        mode: 'batch' | 'refresh'
        force_refresh: пропустить кеш DeepSeek
    """
    from capper_pipeline_nba import batch_generate, batch_refresh

    if mode == 'refresh':
        batch_refresh()
    else:
        batch_generate()
