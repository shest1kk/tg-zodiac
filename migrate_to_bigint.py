"""
Миграция для изменения типа поля id с INTEGER на BIGINT в PostgreSQL.

Выполните этот скрипт ОДИН РАЗ после обновления кода.
"""
import asyncio
import logging
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from config import DATABASE_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def migrate_to_bigint():
    """Миграция типа id с INTEGER на BIGINT"""
    engine = create_async_engine(DATABASE_URL, echo=False)
    
    try:
        async with engine.begin() as conn:
            # Проверяем текущий тип поля id
            check_query = text("""
                SELECT data_type 
                FROM information_schema.columns 
                WHERE table_name = 'users' AND column_name = 'id';
            """)
            result = await conn.execute(check_query)
            row = result.fetchone()
            
            if row:
                current_type = row[0]
                logger.info(f"Текущий тип поля id: {current_type}")
                
                if current_type == 'integer':
                    logger.info("Начинаю миграцию INTEGER -> BIGINT...")
                    
                    # Изменяем тип поля id на BIGINT
                    migrate_query = text("""
                        ALTER TABLE users 
                        ALTER COLUMN id TYPE BIGINT;
                    """)
                    await conn.execute(migrate_query)
                    logger.info("✅ Миграция успешно выполнена! Тип id изменен на BIGINT.")
                elif current_type == 'bigint':
                    logger.info("✅ Тип id уже BIGINT. Миграция не требуется.")
                else:
                    logger.warning(f"⚠️ Неожиданный тип поля id: {current_type}")
            else:
                logger.info("Таблица users не найдена. Она будет создана автоматически при первом запуске.")
                
    except Exception as e:
        logger.error(f"❌ Ошибка при миграции: {e}")
        raise
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(migrate_to_bigint())

