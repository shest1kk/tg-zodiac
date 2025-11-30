# PowerShell скрипт с командами для управления Docker контейнерами

Write-Host "=== Команды управления Docker контейнерами ===" -ForegroundColor Green
Write-Host ""

Write-Host "📦 ОСНОВНЫЕ КОМАНДЫ:" -ForegroundColor Yellow
Write-Host ""

Write-Host "# Запуск контейнеров"
Write-Host "docker-compose up -d --build" -ForegroundColor Cyan
Write-Host ""

Write-Host "# Остановка контейнеров (graceful)"
Write-Host "docker-compose stop" -ForegroundColor Cyan
Write-Host ""

Write-Host "# Остановка с удалением контейнеров"
Write-Host "docker-compose down" -ForegroundColor Cyan
Write-Host ""

Write-Host "# Перезапуск бота"
Write-Host "docker-compose restart bot" -ForegroundColor Cyan
Write-Host ""

Write-Host "# Перезапуск всех сервисов"
Write-Host "docker-compose restart" -ForegroundColor Cyan
Write-Host ""

Write-Host "# Статус контейнеров"
Write-Host "docker-compose ps" -ForegroundColor Cyan
Write-Host ""

Write-Host "🔄 ОБНОВЛЕНИЕ КОДА:" -ForegroundColor Yellow
Write-Host ""

Write-Host "# Пересборка и перезапуск бота (после изменения кода)"
Write-Host "docker-compose up -d --build --force-recreate bot" -ForegroundColor Cyan
Write-Host ""

Write-Host "# Полная пересборка с нуля"
Write-Host "docker-compose build --no-cache; docker-compose up -d" -ForegroundColor Cyan
Write-Host ""

Write-Host "# Обновить код и перезапустить (одна команда)"
Write-Host "docker-compose down; docker-compose up -d --build" -ForegroundColor Cyan
Write-Host ""

Write-Host "📝 ЛОГИ:" -ForegroundColor Yellow
Write-Host ""

Write-Host "# Логи бота (следить в реальном времени)"
Write-Host "docker-compose logs -f bot" -ForegroundColor Cyan
Write-Host ""

Write-Host "# Последние 100 строк логов"
Write-Host "docker-compose logs --tail=100 bot" -ForegroundColor Cyan
Write-Host ""

Write-Host "# Логи с ошибками"
Write-Host "docker-compose logs bot | Select-String -Pattern 'error' -CaseSensitive:`$false" -ForegroundColor Cyan
Write-Host ""

Write-Host "🔧 ОТЛАДКА:" -ForegroundColor Yellow
Write-Host ""

Write-Host "# Войти в контейнер бота"
Write-Host "docker-compose exec bot bash" -ForegroundColor Cyan
Write-Host ""

Write-Host "# Войти в PostgreSQL"
Write-Host "docker-compose exec postgres psql -U bot -d botdb" -ForegroundColor Cyan
Write-Host ""

Write-Host "# Проверить переменные окружения"
Write-Host "docker-compose exec bot env | Select-String -Pattern 'TG_TOKEN|DATABASE_URL|ADMIN_ID'" -ForegroundColor Cyan
Write-Host ""

Write-Host "# Использование ресурсов"
Write-Host "docker stats" -ForegroundColor Cyan
Write-Host ""

Write-Host "💾 БЭКАП:" -ForegroundColor Yellow
Write-Host ""

Write-Host "# Бэкап базы данных"
$backupCmd = "docker-compose exec postgres pg_dump -U bot botdb > backup_$(Get-Date -Format 'yyyyMMdd_HHmmss').sql"
Write-Host $backupCmd -ForegroundColor Cyan
Write-Host ""

Write-Host "🧹 ОЧИСТКА:" -ForegroundColor Yellow
Write-Host ""

Write-Host "# Удалить остановленные контейнеры"
Write-Host "docker-compose rm -f" -ForegroundColor Cyan
Write-Host ""

Write-Host "# Очистить неиспользуемые образы"
Write-Host "docker image prune -a" -ForegroundColor Cyan
Write-Host ""

Write-Host "Все команды готовы к использованию!" -ForegroundColor Green

