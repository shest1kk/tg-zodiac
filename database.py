import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime
from sqlalchemy.exc import SQLAlchemyError
from config import DATABASE_URL

# Определяем тип ID в зависимости от БД
# SQLite не поддерживает autoincrement для BigInteger, используем Integer
if 'sqlite' in DATABASE_URL.lower():
    ID_TYPE = Integer
else:
    ID_TYPE = BigInteger

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


class Raffle(Base):
    """Управление розыгрышами"""
    __tablename__ = "raffles"
    id = Column(ID_TYPE, primary_key=True, autoincrement=True)
    raffle_number = Column(Integer, nullable=False, unique=True)  # Номер розыгрыша (1, 2, 3...)
    raffle_date = Column(String, nullable=False, unique=True)  # Дата розыгрыша (YYYY-MM-DD)
    is_active = Column(Boolean, default=True, nullable=False)  # Активен ли розыгрыш
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)  # Время создания
    stopped_at = Column(DateTime, nullable=True)  # Время остановки (если остановлен)


class RaffleParticipant(Base):
    """Участники розыгрыша"""
    __tablename__ = "raffle_participants"
    id = Column(ID_TYPE, primary_key=True, autoincrement=True)  # Integer для SQLite, BigInteger для PostgreSQL
    user_id = Column(BigInteger, nullable=False)  # ID пользователя
    raffle_date = Column(String, nullable=False)  # Дата розыгрыша (YYYY-MM-DD)
    question_id = Column(Integer, nullable=False)  # ID вопроса (1-5)
    question_text = Column(String, nullable=False)  # Текст вопроса
    answer = Column(String, nullable=True)  # Ответ пользователя
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)  # Время получения вопроса (нажатия кнопки)
    is_correct = Column(Boolean, nullable=True)  # True - принят, False - отклонен, None - не проверен
    message_id = Column(BigInteger, nullable=True)  # ID сообщения с объявлением для редактирования
    announcement_time = Column(DateTime, nullable=True)  # Время отправки объявления о розыгрыше

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