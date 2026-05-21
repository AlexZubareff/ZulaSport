#!/usr/bin/env python3
"""
Система оповещения для пайплайна Zula Sport.

- Счётчики ошибок по источникам (.api_error_state.json)
- Telegram-алерты при 3+ последовательных сбоях
- Дедупликация (не спамить чаще 1 раза в час)
- Логирование в /var/log/zula/
"""

import json, os, sys, time, logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# Настройка логгера
os.makedirs('/var/log/zula', exist_ok=True)
logging.basicConfig(
    filename='/var/log/zula/alerts.log',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger('alert')

ERROR_STATE_PATH = '/opt/.api_error_state.json'
SILENCE_PERIOD = 3600  # 1 час между алертами одного источника
ERROR_THRESHOLD = 3  # количество последовательных сбоев для алерта


def _get_telegram_bot():
    """Получить Telegram bot token и chat_id из окружения или файла."""
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat = os.environ.get('TELEGRAM_ALERT_CHAT', '@zula_sport_news')

    if not token:
        # Пробуем прочитать из файла daily_results.py
        try:
            with open('/opt/daily_results.py', encoding='utf-8') as f:
                for line in f:
                    if 'BOT_TOKEN' in line and 'os.environ' in line:
                        break
        except:
            pass

    return token, chat


def _send_telegram(message: str) -> bool:
    """Отправить сообщение в Telegram."""
    token, chat = _get_telegram_bot()
    if not token:
        logger.warning('Нет Telegram токена для отправки алерта')
        return False

    try:
        import requests
        resp = requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={
                'chat_id': chat,
                'text': message,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            logger.info(f'Telegram алерт отправлен: {message[:100]}...')
            return True
        else:
            logger.error(f'Telegram ошибка: {resp.status_code} {resp.text[:200]}')
            return False
    except Exception as e:
        logger.error(f'Telegram исключение: {e}')
        return False


def _load_state() -> dict:
    """Загрузить состояние счётчиков ошибок."""
    if not os.path.exists(ERROR_STATE_PATH):
        return {
            '_version': 1,
            'updated_at': datetime.now(timezone.utc).isoformat(),
            'sources': {},
        }
    try:
        with open(ERROR_STATE_PATH, encoding='utf-8') as f:
            return json.load(f)
    except:
        return {
            '_version': 1,
            'updated_at': datetime.now(timezone.utc).isoformat(),
            'sources': {},
        }


def _save_state(state: dict):
    """Сохранить состояние счётчиков ошибок."""
    state['updated_at'] = datetime.now(timezone.utc).isoformat()
    tmp = ERROR_STATE_PATH + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.rename(tmp, ERROR_STATE_PATH)
    except Exception as e:
        logger.error(f'Ошибка сохранения состояния: {e}')


def report_success(source: str):
    """Сообщить об успешном выполнении источника.

    Сбрасывает счётчик ошибок для этого источника.
    """
    state = _load_state()
    sources = state.get('sources', {})
    if source not in sources:
        sources[source] = {
            'consecutive_failures': 0,
            'last_failure': None,
            'last_success': None,
            'last_alert_sent': None,
        }
    sources[source]['consecutive_failures'] = 0
    sources[source]['last_success'] = datetime.now(timezone.utc).isoformat()
    state['sources'] = sources
    _save_state(state)


def report_failure(source: str, error: str = '') -> Optional[str]:
    """Сообщить об ошибке источника.

    Если превышен порог — возвращает текст алерта для отправки (или None).
    """
    state = _load_state()
    sources = state.get('sources', {})
    if source not in sources:
        sources[source] = {
            'consecutive_failures': 0,
            'last_failure': None,
            'last_success': None,
            'last_alert_sent': None,
        }

    info = sources[source]
    info['consecutive_failures'] = info.get('consecutive_failures', 0) + 1
    info['last_failure'] = datetime.now(timezone.utc).isoformat()
    info['last_error'] = error

    fails = info['consecutive_failures']
    now_ts = time.time()
    last_alert = info.get('last_alert_sent')

    # Логируем каждый сбой
    logger.warning(f'⚠️ {source}: сбой #{fails} — {error[:100]}')

    # Проверяем порог и дедупликацию
    if fails >= ERROR_THRESHOLD:
        if not last_alert or (now_ts - last_alert) > SILENCE_PERIOD:
            alert_msg = (
                f'🚨 {source}: {fails} последовательных сбоев\n'
                f'Последняя ошибка: {error[:200]}'
            )
            info['last_alert_sent'] = now_ts
            state['sources'] = sources
            _save_state(state)

            # Отправляем алерт
            sent = _send_telegram(alert_msg)
            if not sent:
                logger.warning(f'Не удалось отправить алерт для {source}')

            return alert_msg

    state['sources'] = sources
    _save_state(state)
    return None


def get_source_status(source: str) -> dict:
    """Получить статус источника."""
    state = _load_state()
    sources = state.get('sources', {})
    return sources.get(source, {
        'consecutive_failures': 0,
        'last_failure': None,
        'last_success': None,
        'last_alert_sent': None,
    })


def get_all_status() -> dict:
    """Получить статус всех источников."""
    state = _load_state()
    return {
        'updated_at': state.get('updated_at'),
        'sources': state.get('sources', {}),
    }


def wrap_source(source_name: str):
    """Декоратор для обёртки функции с автоматическим отслеживанием ошибок."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                report_success(source_name)
                return result
            except Exception as e:
                report_failure(source_name, str(e))
                raise
        return wrapper
    return decorator


def healthcheck_errors():
    """Проверить состояние ошибок и отправить сводку.

    Вызывается из evaluate_healthcheck.py раз в 15 минут.
    Возвращает количество источников с ошибками.
    """
    state = get_all_status()
    sources = state.get('sources', {})
    problems = []

    for name, info in sources.items():
        fails = info.get('consecutive_failures', 0)
        if fails >= ERROR_THRESHOLD:
            last_err = info.get('last_error', 'неизвестно')
            problems.append(f'❌ {name}: {fails} сбоев ({last_err[:100]})')

    if problems:
        summary = '\n'.join(problems)
        print(f'Проблемы пайплайна:\n{summary}')

        # Проверяем, не затих ли алерт-канал
        now_ts = time.time()
        last_any_alert = max(
            (s.get('last_alert_sent', 0) or 0) for s in sources.values()
        ) if sources else 0

        if last_any_alert and (now_ts - last_any_alert) > SILENCE_PERIOD * 4:
            print(f'\n⚠️ Алерты не отправлялись > {SILENCE_PERIOD*4//3600}ч')
    else:
        print('✅ Все источники в норме')

    return len(problems)
