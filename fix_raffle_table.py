"""
Скрипт для исправления структуры таблицы raffle_participants
Пересоздает таблицу с правильным типом id (Integer вместо BigInteger для SQLite)
"""
import asyncio
import logging
from sqlalchemy import text
from database import engine, DATABASE_URL

logger = logging.getLogger(__name__)

async def fix_table():
    """Пересоздает таблицу raffle_participants с правильной структурой"""
    try:
        async with engine.begin() as conn:
            if 'sqlite' in DATABASE_URL.lower():
                # Для SQLite - пересоздаем таблицу
                logger.info("Пересоздаю таблицу raffle_participants для SQLite...")
                
                # Проверяем, существует ли таблица
                result = await conn.execute(text("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='raffle_participants'
                """))
                table_exists = result.first() is not None
                
                if table_exists:
                    # Сохраняем данные (если есть)
                    logger.info("Сохраняю существующие данные...")
                    await conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS raffle_participants_backup AS 
                        SELECT * FROM raffle_participants
                    """))
                    
                    # Удаляем старую таблицу
                    await conn.execute(text("DROP TABLE raffle_participants"))
                    logger.info("Старая таблица удалена")
                
                # Создаем новую таблицу с правильной структурой
                await conn.execute(text("""
                    CREATE TABLE raffle_participants (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id BIGINT NOT NULL,
                        raffle_date VARCHAR NOT NULL,
                        question_id INTEGER NOT NULL,
                        question_text VARCHAR NOT NULL,
                        answer VARCHAR,
                        timestamp DATETIME NOT NULL,
                        is_correct BOOLEAN,
                        message_id BIGINT,
                        announcement_time DATETIME
                    )
                """))
                logger.info("Новая таблица создана")
                
                # Восстанавливаем данные (если были)
                if table_exists:
                    try:
                        await conn.execute(text("""
                            INSERT INTO raffle_participants 
                            (user_id, raffle_date, question_id, question_text, answer, timestamp, is_correct, message_id, announcement_time)
                            SELECT user_id, raffle_date, question_id, question_text, answer, timestamp, is_correct, message_id, announcement_time
                            FROM raffle_participants_backup
                        """))
                        logger.info("Данные восстановлены")
                        
                        # Удаляем backup
                        await conn.execute(text("DROP TABLE raffle_participants_backup"))
                    except Exception as e:
                        logger.warning(f"Не удалось восстановить данные: {e}")
                        await conn.execute(text("DROP TABLE IF EXISTS raffle_participants_backup"))
                
                logger.info("✅ Таблица raffle_participants успешно пересоздана")
            else:
                # Для PostgreSQL - просто добавляем колонку, если её нет
                logger.info("Проверяю структуру таблицы для PostgreSQL...")
                result = await conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='raffle_participants' 
                    AND column_name='announcement_time'
                """))
                exists = result.first() is not None
                
                if not exists:
                    await conn.execute(text("""
                        ALTER TABLE raffle_participants 
                        ADD COLUMN announcement_time TIMESTAMP
                    """))
                    logger.info("✅ Колонка announcement_time добавлена")
                else:
                    logger.info("✅ Структура таблицы корректна")
                    
    except Exception as e:
        logger.error(f"Ошибка при исправлении таблицы: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    asyncio.run(fix_table())
    print("Исправление таблицы завершено!")
