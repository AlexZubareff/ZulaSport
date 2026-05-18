# GitHub Actions Secrets для ZulaSport

Эти секреты нужно добавить в `Settings → Secrets and variables → Actions`:

| Secret | Значение |
|--------|----------|
| `DEPLOY_KEY` | Приватный SSH-ключ для доступа к серверу |
| `HOST` | IP сервера (195.133.9.206) |
| `USERNAME` | Пользователь SSH (root) |
| `PORT` | Порт SSH (22) |

## CI/CD Pipeline

**CI** (`.github/workflows/ci.yml`):
- Запускается на каждый push/PR в main
- Проверяет синтаксис Python
- Проверяет экспорт site_common
- Проверяет структуру файлов

**Deploy** (`.github/workflows/deploy.yml`):
- Запускается на push в main
- SSH в сервер
- `git pull` + `generate_site.py --section all`
- Прогоняет тесты
- Перезагружает nginx
