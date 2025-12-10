"""
Безопасная миграция для добавления таблиц квизов
Поддерживает как SQLite, так и PostgreSQL
"""
import asyncio
import logging
from sqlalchemy import text
from database import engine, DATABASE_URL, Quiz, QuizParticipant, QuizResult

logger = logging.getLogger(__name__)


async def migrate_quiz_tables():
    """Добавляет таблицы для квизов, если их еще нет"""
    try:
        async with engine.begin() as conn:
            if 'sqlite' in DATABASE_URL.lower():
                # Для SQLite
                logger.info("Проверяю структуру таблиц квизов для SQLite...")
                
                # Проверяем таблицу quizzes
                result = await conn.execute(text("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='quizzes'
                """))
                if result.first() is None:
                    logger.info("Создаю таблицу quizzes...")
                    await conn.run_sync(lambda sync_conn: Quiz.__table__.create(sync_conn, checkfirst=True))
                    logger.info("✅ Таблица quizzes создана")
                else:
                    logger.info("✅ Таблица quizzes уже существует")
                
                # Проверяем таблицу quiz_participants
                result = await conn.execute(text("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='quiz_participants'
                """))
                if result.first() is None:
                    logger.info("Создаю таблицу quiz_participants...")
                    await conn.run_sync(lambda sync_conn: QuizParticipant.__table__.create(sync_conn, checkfirst=True))
                    logger.info("✅ Таблица quiz_participants создана")
                else:
                    logger.info("✅ Таблица quiz_participants уже существует")
                
                # Проверяем таблицу quiz_results
                result = await conn.execute(text("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='quiz_results'
                """))
                if result.first() is None:
                    logger.info("Создаю таблицу quiz_results...")
                    await conn.run_sync(lambda sync_conn: QuizResult.__table__.create(sync_conn, checkfirst=True))
                    logger.info("✅ Таблица quiz_results создана")
                else:
                    logger.info("✅ Таблица quiz_results уже существует")
                    
            else:
                # Для PostgreSQL
                logger.info("Проверяю структуру таблиц квизов для PostgreSQL...")
                
                # Проверяем таблицу quizzes
                result = await conn.execute(text("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'quizzes'
                """))
                if result.first() is None:
                    logger.info("Создаю таблицу quizzes...")
                    await conn.run_sync(lambda sync_conn: Quiz.__table__.create(sync_conn, checkfirst=True))
                    logger.info("✅ Таблица quizzes создана")
                else:
                    logger.info("✅ Таблица quizzes уже существует")
                
                # Проверяем таблицу quiz_participants
                result = await conn.execute(text("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'quiz_participants'
                """))
                if result.first() is None:
                    logger.info("Создаю таблицу quiz_participants...")
                    await conn.run_sync(lambda sync_conn: QuizParticipant.__table__.create(sync_conn, checkfirst=True))
                    logger.info("✅ Таблица quiz_participants создана")
                else:
                    logger.info("✅ Таблица quiz_participants уже существует")
                
                # Проверяем таблицу quiz_results
                result = await conn.execute(text("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'quiz_results'
                """))
                if result.first() is None:
                    logger.info("Создаю таблицу quiz_results...")
                    await conn.run_sync(lambda sync_conn: QuizResult.__table__.create(sync_conn, checkfirst=True))
                    logger.info("✅ Таблица quiz_results создана")
                else:
                    logger.info("✅ Таблица quiz_results уже существует")
            
            logger.info("✅ Миграция квизов завершена успешно!")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при миграции: {e}", exc_info=True)
        # Не поднимаем исключение, чтобы бот мог запуститься
        logger.warning("Миграция завершилась с ошибкой, но бот продолжит работу")


async def main():
    """Главная функция"""
    try:
        await migrate_quiz_tables()
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
