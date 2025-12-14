"""
Миграция для добавления полей регистрации в таблицу users
"""
import asyncio
import logging
from sqlalchemy import text
from database import AsyncSessionLocal, engine, init_db
from config import logger

async def migrate():
    """Добавляет поля регистрации в таблицу users"""
    try:
        async with engine.begin() as conn:
            # Проверяем, существует ли колонка registration_status
            if 'postgresql' in str(engine.url).lower():
                # PostgreSQL
                result = await conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'users' AND column_name = 'registration_status'
                """))
                exists = result.scalar() is not None
            else:
                # SQLite
                result = await conn.execute(text("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='users'
                """))
                if result.scalar():
                    result = await conn.execute(text("PRAGMA table_info(users)"))
                    columns = [row[1] for row in result.fetchall()]
                    exists = 'registration_status' in columns
                else:
                    exists = False
            
            if not exists:
                logger.info("Добавляю поля регистрации в таблицу users...")
                
                if 'postgresql' in str(engine.url).lower():
                    # PostgreSQL
                    await conn.execute(text("""
                        ALTER TABLE users 
                        ADD COLUMN IF NOT EXISTS registration_status VARCHAR,
                        ADD COLUMN IF NOT EXISTS registration_first_name VARCHAR,
                        ADD COLUMN IF NOT EXISTS registration_last_name VARCHAR,
                        ADD COLUMN IF NOT EXISTS registration_position VARCHAR,
                        ADD COLUMN IF NOT EXISTS registration_department VARCHAR,
                        ADD COLUMN IF NOT EXISTS registration_city VARCHAR,
                        ADD COLUMN IF NOT EXISTS registration_source VARCHAR,
                        ADD COLUMN IF NOT EXISTS registration_completed BOOLEAN DEFAULT FALSE NOT NULL
                    """))
                else:
                    # SQLite
                    await conn.execute(text("""
                        ALTER TABLE users 
                        ADD COLUMN registration_status VARCHAR
                    """))
                    await conn.execute(text("""
                        ALTER TABLE users 
                        ADD COLUMN registration_first_name VARCHAR
                    """))
                    await conn.execute(text("""
                        ALTER TABLE users 
                        ADD COLUMN registration_last_name VARCHAR
                    """))
                    await conn.execute(text("""
                        ALTER TABLE users 
                        ADD COLUMN registration_position VARCHAR
                    """))
                    await conn.execute(text("""
                        ALTER TABLE users 
                        ADD COLUMN registration_department VARCHAR
                    """))
                    await conn.execute(text("""
                        ALTER TABLE users 
                        ADD COLUMN registration_city VARCHAR
                    """))
                    await conn.execute(text("""
                        ALTER TABLE users 
                        ADD COLUMN registration_source VARCHAR
                    """))
                    await conn.execute(text("""
                        ALTER TABLE users 
                        ADD COLUMN registration_completed BOOLEAN DEFAULT 0 NOT NULL
                    """))
                
                logger.info("✅ Поля регистрации успешно добавлены в таблицу users")
            else:
                logger.info("ℹ️ Поля регистрации уже существуют в таблице users")
        
    except Exception as e:
        logger.error(f"Ошибка при миграции: {e}", exc_info=True)
        raise

async def main():
    """Главная функция"""
    await init_db()
    await migrate()

if __name__ == "__main__":
    asyncio.run(main())

