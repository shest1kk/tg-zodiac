import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Загружаем переменные окружения
# В Docker переменные уже будут установлены через env_file в docker-compose.yml
# В локальном запуске загружаем из .env файла

# Сначала проверяем, есть ли переменные уже в окружении (Docker случай)
if not os.getenv("TG_TOKEN"):
    # Если нет - загружаем из .env файла (локальный запуск)
    env_path = Path(__file__).parent / ".env"
    cwd_env = Path(os.getcwd()) / ".env"
    
    env_file_to_use = None
    
    if env_path.exists():
        env_file_to_use = env_path
        load_dotenv(dotenv_path=env_path, override=True)
    elif cwd_env.exists():
        env_file_to_use = cwd_env
        load_dotenv(dotenv_path=cwd_env, override=True)
    else:
        # Пытаемся загрузить из текущей рабочей директории
        load_dotenv(override=True)
    
    # Дополнительная диагностика: если файл существует, но переменная не загрузилась
    if env_file_to_use and env_file_to_use.exists() and not os.getenv("TG_TOKEN"):
        try:
            # Пробуем прочитать файл напрямую для диагностики
            with open(env_file_to_use, 'r', encoding='utf-8-sig') as f:  # utf-8-sig убирает BOM
                env_content = f.read()
                # Проверяем наличие TG_TOKEN в файле
                if 'TG_TOKEN' in env_content:
                    # Пробуем загрузить еще раз с явным указанием кодировки
                    from dotenv import dotenv_values
                    env_dict = dotenv_values(dotenv_path=env_file_to_use, encoding='utf-8-sig')
                    if 'TG_TOKEN' in env_dict and env_dict['TG_TOKEN']:
                        # Вручную устанавливаем переменную окружения
                        os.environ['TG_TOKEN'] = env_dict['TG_TOKEN']
        except Exception:
            pass  # Игнорируем ошибки при диагностике

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

TG_TOKEN = os.getenv("TG_TOKEN")
if not TG_TOKEN:
    # Диагностическая информация
    env_file_exists = Path(__file__).parent / ".env"
    current_dir_env = Path(os.getcwd()) / ".env"
    
    error_msg = "TG_TOKEN не установлен в переменных окружения!\n\n"
    error_msg += f"Проверено:\n"
    error_msg += f"  - {env_file_exists} (существует: {env_file_exists.exists()})\n"
    error_msg += f"  - {current_dir_env} (существует: {current_dir_env.exists()})\n"
    error_msg += f"  - Текущая рабочая директория: {os.getcwd()}\n"
    error_msg += f"  - Расположение config.py: {Path(__file__).parent}\n\n"
    error_msg += "Убедитесь, что файл .env находится в корне проекта и содержит строку:\n"
    error_msg += "TG_TOKEN=your_bot_token_here"
    
    raise ValueError(error_msg)

# Поддержка PostgreSQL и SQLite
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    # Fallback на SQLite если DATABASE_URL не указан
    DATABASE_URL = "sqlite+aiosqlite:///zodiac_bot.db"
    logger.info("Используется SQLite база данных (по умолчанию)")

DAILY_HOUR = int(os.getenv("DAILY_HOUR", "9"))   # час рассылки (по умолчанию 9:00)
DAILY_MINUTE = int(os.getenv("DAILY_MINUTE", "0"))

# ID администраторов (опционально, для админ-команд)
# Можно указать несколько через запятую: "123456789,987654321"
ADMIN_IDS = os.getenv("ADMIN_ID") or os.getenv("ADMIN_IDS")
if ADMIN_IDS:
    try:
        # Поддерживаем оба варианта: один ID или несколько через запятую
        ADMIN_IDS = [int(id.strip()) for id in ADMIN_IDS.split(",") if id.strip()]
        if not ADMIN_IDS:
            ADMIN_IDS = None
    except ValueError:
        ADMIN_IDS = None
else:
    ADMIN_IDS = None

# Обратная совместимость: если был ADMIN_ID, сохраняем для старых фильтров
ADMIN_ID = ADMIN_IDS[0] if ADMIN_IDS else None

# Названия знаков зодиака
ZODIAC_NAMES = {
    1: "♈ Овен", 2: "♉ Телец", 3: "♊ Близнецы", 4: "♋ Рак",
    5: "♌ Лев", 6: "♍ Дева", 7: "♎ Весы", 8: "♏ Скорпион",
    9: "♐ Стрелец", 10: "♑ Козерог", 11: "♒ Водолей", 12: "♓ Рыбы"
}
