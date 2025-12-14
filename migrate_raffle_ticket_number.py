"""
Миграция для добавления поля ticket_number в таблицу raffle_participants
"""
import asyncio
import logging
from sqlalchemy import text
from database import engine, DATABASE_URL

logger = logging.getLogger(__name__)

async def migrate():
    """Добавляет колонку ticket_number в таблицу raffle_participants"""
    try:
        # Сначала проверяем, существует ли таблица
        async with engine.begin() as conn:
            if 'sqlite' in DATABASE_URL.lower():
                # Для SQLite - проверяем существование таблицы
                result = await conn.execute(text("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='raffle_participants'
                """))
                table_exists = result.first() is not None
                
                if not table_exists:
                    logger.info("Таблица raffle_participants не существует, миграция не требуется")
                    return
                
                # Проверяем, существует ли уже колонка
                result = await conn.execute(text("""
                    SELECT COUNT(*) FROM pragma_table_info('raffle_participants') 
                    WHERE name='ticket_number'
                """))
                count = result.scalar()
                
                if count == 0:
                    logger.info("Добавляю колонку ticket_number в таблицу raffle_participants...")
                    await conn.execute(text("""
                        ALTER TABLE raffle_participants 
                        ADD COLUMN ticket_number INTEGER
                    """))
                    logger.info("✅ Колонка ticket_number успешно добавлена")
                else:
                    logger.debug("✅ Колонка ticket_number уже существует")
            else:
                # Для PostgreSQL
                result = await conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='raffle_participants' 
                    AND column_name='ticket_number'
                """))
                exists = result.first() is not None
                
                if not exists:
                    logger.info("Добавляю колонку ticket_number в таблицу raffle_participants...")
                    await conn.execute(text("""
                        ALTER TABLE raffle_participants 
                        ADD COLUMN ticket_number INTEGER
                    """))
                    logger.info("✅ Колонка ticket_number успешно добавлена")
                else:
                    logger.debug("✅ Колонка ticket_number уже существует")
                    
    except Exception as e:
        logger.error(f"Ошибка при миграции: {e}", exc_info=True)
        # Не поднимаем исключение, чтобы бот мог запуститься даже при ошибке миграции
        pass

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    asyncio.run(migrate())
    print("Миграция завершена!")

