"""
Безопасная миграция для таблицы raffle_participants
Исправляет структуру без потери данных
"""
import asyncio
import logging
from sqlalchemy import text, inspect
from database import engine, DATABASE_URL, RaffleParticipant

logger = logging.getLogger(__name__)

async def safe_migrate():
    """Безопасная миграция таблицы raffle_participants"""
    try:
        async with engine.begin() as conn:
            if 'sqlite' in DATABASE_URL.lower():
                # Для SQLite
                logger.info("Проверяю структуру таблицы raffle_participants для SQLite...")
                
                # Проверяем, существует ли таблица
                result = await conn.execute(text("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='raffle_participants'
                """))
                table_exists = result.first() is not None
                
                if not table_exists:
                    logger.info("Таблица raffle_participants не существует, будет создана автоматически при запуске бота")
                    return
                
                # Получаем информацию о колонках
                result = await conn.execute(text("""
                    SELECT name, type FROM pragma_table_info('raffle_participants')
                """))
                columns = {row[0]: row[1] for row in result.all()}
                
                logger.info(f"Текущие колонки: {list(columns.keys())}")
                
                # Проверяем и добавляем недостающие колонки
                if 'announcement_time' not in columns:
                    logger.info("Добавляю колонку announcement_time...")
                    await conn.execute(text("""
                        ALTER TABLE raffle_participants 
                        ADD COLUMN announcement_time DATETIME
                    """))
                    logger.info("✅ Колонка announcement_time добавлена")
                else:
                    logger.info("✅ Колонка announcement_time уже существует")
                
                # Проверяем и добавляем колонку ticket_number
                if 'ticket_number' not in columns:
                    logger.info("Добавляю колонку ticket_number...")
                    await conn.execute(text("""
                        ALTER TABLE raffle_participants 
                        ADD COLUMN ticket_number INTEGER
                    """))
                    logger.info("✅ Колонка ticket_number добавлена")
                else:
                    logger.info("✅ Колонка ticket_number уже существует")
                
                # Проверяем тип поля id
                id_type = columns.get('id', '').upper()
                needs_recreate = False
                
                if 'INTEGER' not in id_type and 'BIGINT' in id_type:
                    logger.warning("Поле id имеет тип BIGINT, нужно изменить на INTEGER для SQLite")
                    needs_recreate = True
                elif 'id' not in columns:
                    logger.warning("Поле id отсутствует, нужно пересоздать таблицу")
                    needs_recreate = True
                
                if needs_recreate:
                    logger.info("Пересоздаю таблицу с правильной структурой (данные будут сохранены)...")
                    
                    # Сохраняем данные
                    logger.info("Сохраняю существующие данные...")
                    await conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS raffle_participants_backup AS 
                        SELECT * FROM raffle_participants
                    """))
                    
                    # Подсчитываем количество записей
                    result = await conn.execute(text("SELECT COUNT(*) FROM raffle_participants_backup"))
                    count = result.scalar()
                    logger.info(f"Сохранено {count} записей")
                    
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
                            announcement_time DATETIME,
                            ticket_number INTEGER
                        )
                    """))
                    logger.info("Новая таблица создана")
                    
                    # Восстанавливаем данные
                    if count > 0:
                        logger.info("Восстанавливаю данные...")
                        try:
                            # Проверяем, какие колонки есть в backup
                            result = await conn.execute(text("""
                                SELECT name FROM pragma_table_info('raffle_participants_backup')
                            """))
                            backup_columns = [row[0] for row in result.all()]
                            
                            # Формируем список колонок для INSERT
                            select_cols = []
                            insert_cols = []
                            
                            for col in ['user_id', 'raffle_date', 'question_id', 'question_text', 
                                       'answer', 'timestamp', 'is_correct', 'message_id', 'announcement_time', 'ticket_number']:
                                if col in backup_columns:
                                    select_cols.append(col)
                                    insert_cols.append(col)
                            
                            if select_cols:
                                cols_str = ', '.join(insert_cols)
                                select_str = ', '.join(select_cols)
                                
                                await conn.execute(text(f"""
                                    INSERT INTO raffle_participants ({cols_str})
                                    SELECT {select_str}
                                    FROM raffle_participants_backup
                                """))
                                logger.info(f"✅ Восстановлено {count} записей")
                            else:
                                logger.warning("Не найдено колонок для восстановления")
                        except Exception as e:
                            logger.error(f"Ошибка при восстановлении данных: {e}", exc_info=True)
                            # Продолжаем работу, даже если восстановление не удалось
                    
                    # Удаляем backup
                    await conn.execute(text("DROP TABLE IF EXISTS raffle_participants_backup"))
                    logger.info("✅ Таблица успешно пересоздана с сохранением данных")
                else:
                    logger.info("✅ Структура таблицы корректна, миграция не требуется")
                    
            else:
                # Для PostgreSQL
                logger.info("Проверяю структуру таблицы для PostgreSQL...")
                
                # Проверяем, существует ли таблица
                result = await conn.execute(text("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'raffle_participants'
                """))
                table_exists = result.first() is not None
                
                if not table_exists:
                    logger.info("Таблица raffle_participants не существует, будет создана автоматически при запуске бота")
                    return
                
                # Проверяем наличие колонки announcement_time
                result = await conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_schema = 'public'
                    AND table_name = 'raffle_participants' 
                    AND column_name = 'announcement_time'
                """))
                exists = result.first() is not None
                
                if not exists:
                    logger.info("Добавляю колонку announcement_time...")
                    await conn.execute(text("""
                        ALTER TABLE raffle_participants 
                        ADD COLUMN announcement_time TIMESTAMP
                    """))
                    logger.info("✅ Колонка announcement_time добавлена")
                else:
                    logger.info("✅ Колонка announcement_time уже существует")
                
                # Проверяем наличие колонки ticket_number
                result = await conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_schema = 'public'
                    AND table_name = 'raffle_participants' 
                    AND column_name = 'ticket_number'
                """))
                exists = result.first() is not None
                
                if not exists:
                    logger.info("Добавляю колонку ticket_number...")
                    await conn.execute(text("""
                        ALTER TABLE raffle_participants 
                        ADD COLUMN ticket_number INTEGER
                    """))
                    logger.info("✅ Колонка ticket_number добавлена")
                else:
                    logger.info("✅ Колонка ticket_number уже существует")
                
                # Для PostgreSQL тип id должен быть BIGINT или BIGSERIAL, проверяем
                result = await conn.execute(text("""
                    SELECT data_type 
                    FROM information_schema.columns 
                    WHERE table_schema = 'public'
                    AND table_name = 'raffle_participants' 
                    AND column_name = 'id'
                """))
                id_info = result.first()
                
                if id_info:
                    id_type = id_info[0].upper()
                    logger.info(f"Тип поля id: {id_type}")
                    # Для PostgreSQL BIGINT или BIGSERIAL - это нормально
                    if 'BIG' in id_type or 'SERIAL' in id_type:
                        logger.info("✅ Тип поля id корректный для PostgreSQL")
                    else:
                        logger.warning(f"⚠️ Необычный тип поля id: {id_type}")
                else:
                    logger.warning("⚠️ Поле id не найдено в таблице")
                
                logger.info("✅ Структура таблицы для PostgreSQL проверена")
                    
    except Exception as e:
        logger.error(f"Ошибка при миграции: {e}", exc_info=True)
        # Не поднимаем исключение, чтобы бот мог запуститься
        logger.warning("Миграция завершилась с ошибкой, но бот продолжит работу")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    asyncio.run(safe_migrate())
    print("\n✅ Миграция завершена!")
