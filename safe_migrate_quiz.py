"""
Безопасная миграция для добавления таблиц квизов
Поддерживает как SQLite, так и PostgreSQL
"""
import asyncio
import logging
from sqlalchemy import text, inspect
from database import engine, AsyncSessionLocal, Quiz, QuizParticipant, QuizResult

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def migrate_quiz_tables():
    """Добавляет таблицы для квизов, если их еще нет"""
    try:
        async with engine.begin() as conn:
            # Проверяем, какие таблицы уже существуют
            inspector = inspect(engine.sync_engine)
            existing_tables = inspector.get_table_names()
            
            logger.info(f"Существующие таблицы: {existing_tables}")
            
            # Проверяем и создаем таблицу quizzes
            if 'quizzes' not in existing_tables:
                logger.info("Создаю таблицу quizzes...")
                await conn.run_sync(lambda sync_conn: Quiz.__table__.create(sync_conn, checkfirst=True))
                logger.info("✅ Таблица quizzes создана")
            else:
                logger.info("✅ Таблица quizzes уже существует")
            
            # Проверяем и создаем таблицу quiz_participants
            if 'quiz_participants' not in existing_tables:
                logger.info("Создаю таблицу quiz_participants...")
                await conn.run_sync(lambda sync_conn: QuizParticipant.__table__.create(sync_conn, checkfirst=True))
                logger.info("✅ Таблица quiz_participants создана")
            else:
                logger.info("✅ Таблица quiz_participants уже существует")
            
            # Проверяем и создаем таблицу quiz_results
            if 'quiz_results' not in existing_tables:
                logger.info("Создаю таблицу quiz_results...")
                await conn.run_sync(lambda sync_conn: QuizResult.__table__.create(sync_conn, checkfirst=True))
                logger.info("✅ Таблица quiz_results создана")
            else:
                logger.info("✅ Таблица quiz_results уже существует")
            
            logger.info("✅ Миграция квизов завершена успешно!")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при миграции: {e}", exc_info=True)
        raise


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
