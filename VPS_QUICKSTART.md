# ⚡ Быстрый старт на VPS

## 🎯 Краткая инструкция (5 минут)

### 1. Подключитесь через Termius

- Добавьте новый хост (IP, порт 22, пользователь)
- Подключитесь

### 2. Установите Docker

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
# Переподключитесь!
```

### 3. Загрузите проект

**Вариант A (Git):**
```bash
mkdir -p ~/projects && cd ~/projects
git clone YOUR_REPO_URL
cd tg-zodiac
```

**Вариант B (SFTP в Termius):**
- Откройте SFTP в Termius
- Перетащите папку проекта

### 4. Создайте .env

```bash
nano .env
```

Вставьте:
```env
TG_TOKEN=ваш_токен
ADMIN_ID=ваш_id
DAILY_HOUR=9
DAILY_MINUTE=0
```

Сохраните: `Ctrl+O`, `Enter`, `Ctrl+X`

### 5. Запустите

```bash
docker compose up -d --build
docker compose logs -f bot
```

### 6. Готово!

Проверьте бота в Telegram командой `/start`

---

## 📝 Основные команды

```bash
# Логи
docker compose logs -f bot

# Перезапуск
docker compose up -d --build --force-recreate bot

# Статус
docker compose ps

# Остановка
docker compose stop
```

---

**Полная инструкция:** `VPS_DEPLOY.md`

