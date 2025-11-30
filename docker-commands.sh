#!/bin/bash
# Скрипт с полезными командами для управления Docker контейнерами

# Цвета для вывода
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Команды управления Docker контейнерами ===${NC}\n"

# Функция для вывода команды
print_cmd() {
    echo -e "${YELLOW}$1${NC}"
    echo ""
}

echo "📦 ОСНОВНЫЕ КОМАНДЫ:"
echo ""
print_cmd "# Запуск контейнеров"
echo "docker-compose up -d --build"

print_cmd "# Остановка контейнеров (graceful)"
echo "docker-compose stop"

print_cmd "# Остановка с удалением контейнеров"
echo "docker-compose down"

print_cmd "# Перезапуск бота"
echo "docker-compose restart bot"

print_cmd "# Перезапуск всех сервисов"
echo "docker-compose restart"

print_cmd "# Статус контейнеров"
echo "docker-compose ps"

echo ""
echo "🔄 ОБНОВЛЕНИЕ КОДА:"
echo ""
print_cmd "# Пересборка и перезапуск бота (после изменения кода)"
echo "docker-compose up -d --build --force-recreate bot"

print_cmd "# Полная пересборка с нуля"
echo "docker-compose build --no-cache && docker-compose up -d"

print_cmd "# Обновить код и перезапустить (одна команда)"
echo "docker-compose down && docker-compose up -d --build"

echo ""
echo "📝 ЛОГИ:"
echo ""
print_cmd "# Логи бота (следить в реальном времени)"
echo "docker-compose logs -f bot"

print_cmd "# Последние 100 строк логов"
echo "docker-compose logs --tail=100 bot"

print_cmd "# Логи с ошибками"
echo "docker-compose logs bot | grep -i error"

print_cmd "# Все логи"
echo "docker-compose logs -f"

echo ""
echo "🔧 ОТЛАДКА:"
echo ""
print_cmd "# Войти в контейнер бота"
echo "docker-compose exec bot bash"

print_cmd "# Войти в PostgreSQL"
echo "docker-compose exec postgres psql -U bot -d botdb"

print_cmd "# Проверить переменные окружения"
echo "docker-compose exec bot env | grep -E 'TG_TOKEN|DATABASE_URL|ADMIN_ID'"

print_cmd "# Использование ресурсов"
echo "docker stats"

echo ""
echo "💾 БЭКАП:"
echo ""
print_cmd "# Бэкап базы данных"
echo "docker-compose exec postgres pg_dump -U bot botdb > backup_\$(date +%Y%m%d_%H%M%S).sql"

print_cmd "# Бэкап с сжатием"
echo "docker-compose exec postgres pg_dump -U bot botdb | gzip > backup_\$(date +%Y%m%d_%H%M%S).sql.gz"

echo ""
echo "🧹 ОЧИСТКА:"
echo ""
print_cmd "# Удалить остановленные контейнеры"
echo "docker-compose rm -f"

print_cmd "# Очистить неиспользуемые образы"
echo "docker image prune -a"

print_cmd "# Полная очистка (осторожно!)"
echo "docker system prune -a --volumes"

echo ""
echo -e "${GREEN}Все команды готовы к использованию!${NC}"

