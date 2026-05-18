#!/usr/bin/env bash
# ==============================================================
# healthcheck.sh — мониторинг пайплайна Zula Спорт
# Проверяет: свежесть данных, работу nginx, целостность файлов
# При проблемах — алерт в Telegram
# Запуск по cron: */15 * * * *
# ==============================================================

set -euo pipefail

# ─── Конфиг ─────────────────────────────────────────────────────────
# Сайт теперь на HTTPS. Проверяем конкретную страницу (не IP).
SITE_URL="https://zulasport.ru/predictions.html"
INDEX="/var/www/sport/news.html"        # теперь главная — news.html
TV_CHANNELS="/tmp/tv_channels_data.json"
PREDICTIONS="/opt/predictions_data.json"
UPCOMING="/tmp/upcoming_matches.json"
LOG="/var/log/zula-healthcheck.log"
STATE_FILE="/tmp/zula-healthcheck.state"  # для dedup алертов

# Лимиты
MAX_AGE_MIN=75              # news.html — не старше 75 мин (крон каждые 30)
TV_MAX_AGE_HOURS=26         # tv_channels — не старше 26ч (должен обновляться раз в день)
MIN_TV_MATCHES=5            # минимум матчей в tv_channels
MIN_PREDICTIONS=1           # минимум прогнозов

# Telegram (читаем из /opt/sport_bot.py или задаём напрямую)
CHAT_ID="-1003928523816"    # @zula_sport_news
BOT_TOKEN=""                # будет найден ниже

# ─── Найти токен бота ───────────────────────────────────────────────
if [[ -z "$BOT_TOKEN" ]]; then
    BOT_TOKEN=$(grep -oP 'TOKEN\s*=\s*["'\'']\K[^"'\'']+' /opt/sport_bot.py 2>/dev/null || true)
fi

# ─── Функции ─────────────────────────────────────────────────────────

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg" >> "$LOG"
    echo "$msg"
}

alert() {
    local subject="$1" message="$2"
    log "⚠️  $subject — $message"

    # Дедупликация: не спамим одним и тем же чаще раза в час
    if [[ -f "$STATE_FILE" ]]; then
        local last_subject last_ts now
        last_subject=$(head -1 "$STATE_FILE" 2>/dev/null || echo "")
        last_ts=$(tail -1 "$STATE_FILE" 2>/dev/null || echo "0")
        now=$(date +%s)
        if [[ "$last_subject" == "$subject" && $((now - last_ts)) -lt 3600 ]]; then
            log "  └─ дедуплицировано (повтор <1ч)"
            return
        fi
    fi
    echo "$subject" > "$STATE_FILE"
    date +%s >> "$STATE_FILE"

    # Отправка в Telegram
    if [[ -n "$BOT_TOKEN" ]]; then
        local text="⚠️ *Zula Healthcheck*\\n*$subject*\\n$message"
        curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
            -d "chat_id=${CHAT_ID}" \
            -d "text=${text}" \
            -d "parse_mode=Markdown" \
            -o /dev/null -w "" 2>/dev/null || true
    fi
}

ok() {
    log "✅ $*"
}

# ─── Проверки ───────────────────────────────────────────────────────

errors=0

# 1. Сайт доступен
if ! curl -s -o /dev/null -w '%{http_code}' "$SITE_URL" 2>/dev/null | grep -q 200; then
    alert "Сайт недоступен" "HTTP не 200"
    errors=$((errors + 1))
else
    ok "Сайт доступен"
fi

# 2. index.html не старше MAX_AGE_MIN
if [[ -f "$INDEX" ]]; then
    age_min=$(($(date +%s) - $(stat -c %Y "$INDEX")))  # секунд
    age_min=$((age_min / 60))                           # минут
    if [[ $age_min -gt $MAX_AGE_MIN ]]; then
        alert "index.html устарел" "${age_min} мин назад (лимит: ${MAX_AGE_MIN})"
        errors=$((errors + 1))
    else
        ok "index.html свежий (${age_min} мин)"
    fi
else
    alert "index.html не найден" "$INDEX"
    errors=$((errors + 1))
fi

# 3. tv_channels_data.json — дата и количество
if [[ -f "$TV_CHANNELS" ]]; then
    # Свежесть файла
    age_hours=$(($(date +%s) - $(stat -c %Y "$TV_CHANNELS")))
    age_hours=$((age_hours / 3600))
    if [[ $age_hours -gt $TV_MAX_AGE_HOURS ]]; then
        alert "tv_channels_data.json устарел" "${age_hours}ч назад (лимит: ${TV_MAX_AGE_HOURS})"
        errors=$((errors + 1))
    else
        ok "tv_channels_data.json свежий (${age_hours}ч)"
    fi

    # Количество матчей (сумма по всем датам)
    match_count=$(python3 -c "
import json
with open('${TV_CHANNELS}') as f:
    d = json.load(f)
by_date = d.get('matches_by_date', {})
total = sum(len(v) for v in by_date.values())
print(total)
" 2>/dev/null || echo "0")
    if [[ "$match_count" -lt "$MIN_TV_MATCHES" ]]; then
        alert "Мало матчей" "tv_channels: ${match_count} (мин: ${MIN_TV_MATCHES})"
        errors=$((errors + 1))
    else
        ok "Матчей: ${match_count}"
    fi
else
    alert "tv_channels_data.json не найден" ""
    errors=$((errors + 1))
fi

# 4. В tv_channels есть данные на завтра
if [[ -f "$TV_CHANNELS" ]]; then
    date_ok=$(python3 -c "
import json
from datetime import datetime, timedelta, timezone
with open('${TV_CHANNELS}') as f:
    d = json.load(f)
by_date = d.get('matches_by_date', {})
tomorrow = (datetime.now(timezone.utc) + timedelta(hours=3) + timedelta(days=1)).strftime('%Y%m%d')
matches_count = len(by_date.get(tomorrow, []))
print('OK' if matches_count > 0 else f'MISSING: {tomorrow} has 0 matches')
" 2>/dev/null || echo "PARSE_ERROR")
    if [[ "$date_ok" != "OK" ]]; then
        alert "tv_channels: нет данных на завтра" "$date_ok"
        errors=$((errors + 1))
    else
        ok "tv_channels: данные на завтра есть"
    fi
fi

# 5. Прогнозы
if [[ -f "$PREDICTIONS" ]]; then
    pred_count=$(python3 -c "
import json
with open('${PREDICTIONS}') as f:
    d = json.load(f)
print(len(d.get('predictions', [])))
" 2>/dev/null || echo "0")
    if [[ "$pred_count" -lt "$MIN_PREDICTIONS" ]]; then
        alert "Нет прогнозов" "predictions: ${pred_count}"
        errors=$((errors + 1))
    else
        ok "Прогнозов: ${pred_count}"
    fi
else
    # Не критично — прогнозы могут ещё не сгенерироваться
    log "ℹ️  predictions_data.json не найден (может быть нормально до 7:00)"
fi

# 6. upcoming_matches.json для прогнозов
if [[ -f "$UPCOMING" ]]; then
    up_count=$(python3 -c "
import json
with open('${UPCOMING}') as f:
    d = json.load(f)
    by_date = d.get('matches_by_date', {})
    print(sum(len(v) for v in by_date.values()))
" 2>/dev/null || echo "0")
    if [[ "$up_count" -eq 0 ]]; then
        alert "upcoming_matches.json пуст" ""
        errors=$((errors + 1))
    else
        ok "Матчей для прогнозов: ${up_count}"
    fi
fi

# ─── Итог ────────────────────────────────────────────────────────────

if [[ $errors -eq 0 ]]; then
    ok "Все проверки пройдены"
else
    log "❌ Найдено ${errors} проблем"
fi

exit $errors

# ─── Live scores (только в дневное время) ──────────────────────────

_check_live_scores() {
    local live_file
    if [[ ! -f "$live_file" ]]; then
        alert "live_scores_data.json не найден" "$live_file"
        return 1
    fi

    # Свежесть
    local age_sec now_ts file_ts
    now_ts=$(date +%s)
    file_ts=$(stat -c %Y "$live_file" 2>/dev/null || echo "0")
    age_sec=$((now_ts - file_ts))
    if [[ $age_sec -gt $LIVE_MAX_AGE_SEC ]]; then
        alert "live_scores устарел" "${age_sec} сек назад (лимит: ${LIVE_MAX_AGE_SEC})"
        return 1
    fi
    ok "live_scores свежий (${age_sec} сек)"

    # Проверка: есть live-матчи без stats?
    local result
    result=$(python3 -c "
import json
with open('${live_file}') as f:
    d = json.load(f)
matches = d.get('matches', {})
live_no_stats = []
for key, m in matches.items():
    if m.get('status') == 'live' and ('stats' not in m or not m['stats']):
        live_no_stats.append(key)
if live_no_stats:
    print('MISSING: {} live matches without stats'.format(len(live_no_stats)))
    for k in live_no_stats[:3]:
        print('  ' + k)
else:
    # Считаем статистику
    total = len(matches)
    live = sum(1 for m in matches.values() if m['status'] == 'live')
    with_stats = sum(1 for m in matches.values() if 'stats' in m and m['stats'])
    print('OK total={} live={} stats={}'.format(total, live, with_stats))
" 2>/dev/null || echo "PARSE_ERROR")

    if [[ "$result" == PARSE_ERROR ]]; then
        alert "live_scores ошибка чтения" "Не удалось распарсить JSON"
        return 1
    elif [[ "$result" == MISSING:* ]]; then
        alert "Live без статистики" "$result"
        return 1
    else
        ok "live_scores: $result"
    fi
    return 0
}

# ─── Запуск проверки live ──────────────────────────────────────────
if ! _check_live_scores; then
    errors=$((errors + 1))
fi
