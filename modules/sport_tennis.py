#!/usr/bin/env python3
"""
Модуль прогнозов на теннис (делегирует capper_pipeline_tennis.py).

Используется единым оркестратором: capper_pipeline.py --sport tennis

Режимы: --batch, --refresh
"""

import sys, os

sys.path.insert(0, '/opt')

SPORT = 'tennis'
LEAGUE_NAMES = ('ATP', 'WTA')


def run(mode: str = 'batch', force_refresh: bool = False):
    """Запустить теннисный пайплайн.

    Args:
        mode: 'batch' | 'refresh'
        force_refresh: пропустить кеш DeepSeek
    """
    from capper_pipeline_tennis import batch_generate, batch_refresh

    if mode == 'refresh':
        batch_refresh()
    else:
        batch_generate()
