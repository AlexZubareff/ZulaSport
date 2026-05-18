# Zula Спорт

Спортивный сайт с ТВ-программой, результатами, расписанием и прогнозами.

## Структура

- `*.py` — скрипты пайплайна
- `tests/` — тесты
- `deploy/` — cron, dev-скрипт, healthcheck
- `web/` — тестовые страницы, статика (логотипы лиг)
- `web/static/` — ресурсы, не генерируемые автоматически

## Пайплайн (cron)

```
02:30 / 03:30 МСК → fetch_tv_channels.py   — ТВ-программа на завтра
04:00 МСК         → capper_pipeline.py      — прогнозы
06:15 МСК         → evaluate_predictions.py — оценка + healthcheck
07:00 МСК         → evaluate_healthcheck.py — мониторинг
10:00 МСК         → fetch_live_scores.py    — live с ESPN (самопланируется)
21:00 МСК         → daily_results.py        — результаты за сутки
```

## Внешние зависимости (не в репозитории)

| Файл | Назначение |
|------|-----------|
| `/etc/sstats.key` | API-ключ SStats |
| `/etc/bot_token.key` | Telegram bot token |
| `/var/www/sport/index.html` | Сгенерированный сайт |
| `/var/www/sport/news_data.json` | Кеш новостей |
| `/tmp/*.json` | Временные данные (live, results) |
| `/opt/predictions_history.json` | История прогнозов |
| `/opt/predictions_data.json` | Очередь прогнозов |

## Быстрый старт

```bash
dev test      # все тесты
dev check     # тесты + healthcheck
```

См. `/opt/deploy/dev` — основной инструмент разработки.
