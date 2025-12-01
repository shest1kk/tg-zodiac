import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime
from sqlalchemy.exc import SQLAlchemyError
from config import DATABASE_URL

logger = logging.getLogger(__name__)

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(BigInteger, primary_key=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    zodiac = Column(Integer, nullable=True)  # Оставляем для обратной совместимости
    zodiac_name = Column(String, nullable=True)  # Название знака зодиака
    subscribed = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)  # Дата первого запуска

# Настройка engine с улучшенными параметрами
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,  # Проверка соединения перед использованием
    pool_recycle=3600,  # Переподключение каждые 3600 секунд
)

AsyncSessionLocal = sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession
)

async def init_db():
    """Инициализация базы данных"""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("База данных успешно инициализирована")
    except SQLAlchemyError as e:
        logger.error(f"Ошибка при инициализации базы данных: {e}")
        raise