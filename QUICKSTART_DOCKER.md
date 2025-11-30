# 🚀 Быстрый старт с Docker

## ⚡ За 3 шага

### 1. Создайте `.env` файл

```env
TG_TOKEN=your_telegram_bot_token
ADMIN_ID=375961707,498458650
DAILY_HOUR=9
DAILY_MINUTE=0
```

### 2. Запустите

```bash
docker-compose up -d --build
```

### 3. Проверьте логи

```bash
docker-compose logs -f bot
```

## 📋 Основные команды

**Все команды смотрите в `DOCKER_COMMANDS.txt` или `DOCKER_DEPLOY.md`**

### Самые важные:

```bash
# Перезапуск после изменения кода
docker-compose up -d --build --force-recreate bot

# Просмотр логов
docker-compose logs -f bot

# Остановка
docker-compose stop

# Статус
docker-compose ps
```

## ⚠️ Важно

- Файл `data/predictions.json` монтируется из локальной папки
- Изменения в коде требуют пересборки: `docker-compose up -d --build --force-recreate bot`
- Все логи доступны через `docker-compose logs`

## 📚 Полная документация

Смотрите `DOCKER_DEPLOY.md` для детальной информации.

