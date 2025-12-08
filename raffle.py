"""
Модуль для управления розыгрышами
"""
import json
import random
import logging
import asyncio
from datetime import datetime, timezone, timedelta, time as dt_time
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from aiogram import types
from sqlalchemy import select, and_
from sqlalchemy.exc import SQLAlchemyError
from database import AsyncSessionLocal, User, RaffleParticipant, Raffle
from resilience import safe_send_message, safe_send_photo

logger = logging.getLogger(__name__)

# Словарь для хранения задач таймаута: {user_id: task}
raffle_timeout_tasks = {}

# Московское время (UTC+3)
MOSCOW_TZ = timezone(timedelta(hours=3))

# Даты розыгрышей (каждый понедельник начиная с 08.12.2025)
RAFFLE_DATES = [
    "2025-12-08",
    "2025-12-15",
    "2025-12-22",
    "2025-12-29"
]

RAFFLE_HOUR = 12  # 21:00 МСК
RAFFLE_MINUTE = 00  # Минуты для запуска розыгрыша (0-59)
RAFFLE_PARTICIPATION_WINDOW = 2  # 2 часа на участие
RAFFLE_REMINDER_DELAY = 1  # 1 час до напоминания
RAFFLE_ANSWER_TIME = 15  # 15 минут на ответ (в минутах)


async def check_answer_timeout(bot, user_id: int, raffle_date: str, timeout_minutes: int):
    """Проверяет, ответил ли пользователь в течение указанного времени, и отправляет сообщение если нет"""
    try:
        # Ждем указанное количество минут
        await asyncio.sleep(timeout_minutes * 60)
        
        # Проверяем, ответил ли пользователь
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(RaffleParticipant).where(
                    and_(
                        RaffleParticipant.user_id == user_id,
                        RaffleParticipant.raffle_date == raffle_date
                    )
                )
            )
            participant = result.scalar_one_or_none()
            
            if not participant:
                # Пользователь не найден, возможно отписался или удалил запись
                return
            
            # Проверяем, ответил ли пользователь
            if participant.answer is None:
                # Пользователь не ответил - отправляем сообщение
                timeout_message = "⏰ Вы не успели ответить на вопрос в течение 15 минут."
                await safe_send_message(bot, user_id, timeout_message)
                logger.info(f"Отправлено сообщение о таймауте пользователю {user_id} (розыгрыш {raffle_date})")
            # Если ответ есть - ничего не делаем
            
            # Удаляем задачу из словаря после завершения
            raffle_timeout_tasks.pop(user_id, None)
            
    except asyncio.CancelledError:
        # Задача была отменена (пользователь ответил)
        logger.debug(f"Задача проверки таймаута отменена для пользователя {user_id}")
        # Удаляем задачу из словаря
        raffle_timeout_tasks.pop(user_id, None)
    except Exception as e:
        logger.error(f"Ошибка при проверке таймаута ответа для пользователя {user_id}: {e}")
        # Удаляем задачу из словаря даже при ошибке
        raffle_timeout_tasks.pop(user_id, None)


def load_questions() -> Optional[Dict]:
    """Загружает вопросы из question.json"""
    questions_path = Path("data/question.json")
    if not questions_path.exists():
        logger.error("Файл question.json не найден!")
        return None
    
    try:
        with open(questions_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Ошибка при загрузке вопросов: {e}")
        return None


def get_random_question(raffle_date: str) -> Optional[Dict]:
    """Получает случайный вопрос для указанной даты розыгрыша"""
    questions_data = load_questions()
    if not questions_data or "raffle_dates" not in questions_data:
        return None
    
    raffle_dates = questions_data["raffle_dates"]
    if raffle_date not in raffle_dates:
        logger.warning(f"Вопросы для даты {raffle_date} не найдены")
        return None
    
    questions = raffle_dates[raffle_date]
    if not questions:
        return None
    
    # Преобразуем словарь в список и выбираем случайный
    questions_list = list(questions.values())
    if not questions_list:
        return None
    
    return random.choice(questions_list)


def get_question_by_id(question_id: int, raffle_date: str) -> Optional[Dict]:
    """Получает вопрос по ID для указанной даты розыгрыша"""
    questions_data = load_questions()
    if not questions_data or "raffle_dates" not in questions_data:
        return None
    
    raffle_dates = questions_data["raffle_dates"]
    if raffle_date not in raffle_dates:
        return None
    
    questions = raffle_dates[raffle_date]
    for question_key, question in questions.items():
        if question.get("id") == question_id:
            return question
    
    return None


def get_all_questions(raffle_date: str = None) -> List[Dict]:
    """Получает все вопросы для указанной даты или всех дат"""
    questions_data = load_questions()
    if not questions_data or "raffle_dates" not in questions_data:
        return []
    
    raffle_dates = questions_data["raffle_dates"]
    
    if raffle_date:
        # Возвращаем вопросы для конкретной даты
        if raffle_date not in raffle_dates:
            return []
        questions = raffle_dates[raffle_date]
        return list(questions.values())
    else:
        # Возвращаем все вопросы из всех дат
        all_questions = []
        for date_questions in raffle_dates.values():
            all_questions.extend(list(date_questions.values()))
        return all_questions


def get_all_raffle_dates() -> List[str]:
    """Получает список всех дат розыгрышей из question.json"""
    questions_data = load_questions()
    if not questions_data or "raffle_dates" not in questions_data:
        return []
    
    return list(questions_data["raffle_dates"].keys())


def save_questions_data(questions_data: Dict) -> bool:
    """Сохраняет данные вопросов в question.json
    
    Args:
        questions_data: Полная структура данных с raffle_dates
        
    Returns:
        True если успешно, False в противном случае
    """
    questions_path = Path("data/question.json")
    try:
        with open(questions_path, "w", encoding="utf-8") as f:
            json.dump(questions_data, f, ensure_ascii=False, indent=4)
        logger.info(f"Вопросы успешно сохранены в {questions_path}")
        return True
    except (IOError, json.JSONEncodeError) as e:
        logger.error(f"Ошибка при сохранении вопросов: {e}")
        return False


def update_question(question_id: int, raffle_date: str, title: str, text: str) -> bool:
    """Обновляет вопрос по ID для указанной даты розыгрыша
    
    Args:
        question_id: ID вопроса
        raffle_date: Дата розыгрыша
        title: Новое название вопроса
        text: Новый текст вопроса
        
    Returns:
        True если успешно, False в противном случае
    """
    questions_data = load_questions()
    if not questions_data or "raffle_dates" not in questions_data:
        return False
    
    raffle_dates = questions_data["raffle_dates"]
    if raffle_date not in raffle_dates:
        return False
    
    questions = raffle_dates[raffle_date]
    for question_key, question in questions.items():
        if question.get("id") == question_id:
            question["title"] = title
            question["text"] = text
            return save_questions_data(questions_data)
    
    return False


async def has_raffle_started(raffle_date: str) -> bool:
    """Проверяет, начался ли розыгрыш (были ли отправлены объявления)
    
    Args:
        raffle_date: Дата розыгрыша в формате YYYY-MM-DD
        
    Returns:
        True если розыгрыш начался (есть участники с announcement_time), False иначе
    """
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(RaffleParticipant).where(
                    and_(
                        RaffleParticipant.raffle_date == raffle_date,
                        RaffleParticipant.announcement_time.isnot(None)
                    )
                ).limit(1)
            )
            participant = result.scalar_one_or_none()
            return participant is not None
    except Exception as e:
        logger.error(f"Ошибка при проверке начала розыгрыша {raffle_date}: {e}")
        return False  # В случае ошибки разрешаем редактирование


def is_raffle_date(date_str: Optional[str] = None) -> bool:
    """Проверяет, является ли дата датой розыгрыша"""
    if date_str is None:
        current_date = datetime.now(MOSCOW_TZ).date()
        date_str = current_date.strftime("%Y-%m-%d")
    
    return date_str in RAFFLE_DATES


def get_next_raffle_date() -> Optional[str]:
    """Получает дату следующего розыгрыша"""
    current_date = datetime.now(MOSCOW_TZ).date()
    
    for raffle_date_str in RAFFLE_DATES:
        raffle_date = datetime.strptime(raffle_date_str, "%Y-%m-%d").date()
        if raffle_date >= current_date:
            return raffle_date_str
    
    return None


async def create_or_get_raffle(raffle_date: str, force_activate: bool = False) -> Optional[Raffle]:
    """Создает или получает розыгрыш для указанной даты
    
    Args:
        raffle_date: Дата розыгрыша
        force_activate: Если True, активирует существующий остановленный розыгрыш
    """
    try:
        async with AsyncSessionLocal() as session:
            # Проверяем, существует ли уже розыгрыш
            result = await session.execute(
                select(Raffle).where(Raffle.raffle_date == raffle_date)
            )
            raffle = result.scalar_one_or_none()
            
            if raffle:
                # Если розыгрыш существует и был остановлен, активируем его при force_activate
                if force_activate and not raffle.is_active:
                    raffle.is_active = True
                    raffle.stopped_at = None  # Сбрасываем время остановки
                    await session.commit()
                    logger.info(f"Розыгрыш #{raffle.raffle_number} ({raffle_date}) активирован заново")
                return raffle
            
            # Получаем следующий номер розыгрыша
            result = await session.execute(
                select(Raffle.raffle_number).order_by(Raffle.raffle_number.desc()).limit(1)
            )
            last_number = result.scalar_one_or_none()
            next_number = (last_number or 0) + 1
            
            # Создаем новый розыгрыш
            # Используем МСК время для created_at, но убираем timezone для PostgreSQL
            moscow_now = datetime.now(MOSCOW_TZ)
            # Конвертируем в UTC и убираем timezone для совместимости с БД (TIMESTAMP WITHOUT TIME ZONE)
            created_at_utc = moscow_now.astimezone(timezone.utc).replace(tzinfo=None)
            raffle = Raffle(
                raffle_number=next_number,
                raffle_date=raffle_date,
                is_active=True,
                created_at=created_at_utc
            )
            session.add(raffle)
            await session.commit()
            
            logger.info(f"Создан розыгрыш #{next_number} на дату {raffle_date}")
            return raffle
            
    except Exception as e:
        logger.error(f"Ошибка при создании розыгрыша: {e}")
        return None


async def is_raffle_active(raffle_date: str) -> bool:
    """Проверяет, активен ли розыгрыш
    
    Розыгрыш считается неактивным, если:
    1. Он был остановлен администратором (is_active = False)
    2. Текущее время > 23:59 даты розыгрыша (автоматическое закрытие)
    """
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Raffle).where(Raffle.raffle_date == raffle_date)
            )
            raffle = result.scalar_one_or_none()
            
            if not raffle:
                # Если розыгрыша нет, проверяем только время закрытия
                raffle_date_obj = datetime.strptime(raffle_date, "%Y-%m-%d").date()
                close_time = datetime.combine(raffle_date_obj, dt_time(hour=23, minute=59))
                close_time = close_time.replace(tzinfo=MOSCOW_TZ)
                moscow_now = datetime.now(MOSCOW_TZ)
                
                # Если время закрытия прошло, розыгрыш неактивен
                if moscow_now > close_time:
                    return False
                return True
            
            # Проверяем, остановлен ли розыгрыш администратором
            if not raffle.is_active:
                return False
            
            # Проверяем время закрытия (23:59 даты розыгрыша)
            raffle_date_obj = datetime.strptime(raffle_date, "%Y-%m-%d").date()
            close_time = datetime.combine(raffle_date_obj, dt_time(hour=23, minute=59))
            close_time = close_time.replace(tzinfo=MOSCOW_TZ)
            moscow_now = datetime.now(MOSCOW_TZ)
            
            # Если время закрытия прошло, розыгрыш неактивен
            if moscow_now > close_time:
                return False
            
            return True
            
    except Exception as e:
        logger.error(f"Ошибка при проверке активности розыгрыша: {e}")
        return True  # По умолчанию считаем активным


async def auto_close_raffle(raffle_date: str) -> bool:
    """Автоматически закрывает розыгрыш в 23:59 его даты"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Raffle).where(Raffle.raffle_date == raffle_date)
            )
            raffle = result.scalar_one_or_none()
            
            if not raffle:
                logger.warning(f"Розыгрыш для даты {raffle_date} не найден для автоматического закрытия")
                return False
            
            if not raffle.is_active:
                logger.debug(f"Розыгрыш #{raffle.raffle_number} ({raffle_date}) уже остановлен")
                return True
            
            raffle.is_active = False
            # Убираем timezone для PostgreSQL (TIMESTAMP WITHOUT TIME ZONE)
            moscow_now = datetime.now(MOSCOW_TZ)
            raffle.stopped_at = moscow_now.astimezone(timezone.utc).replace(tzinfo=None)
            await session.commit()
            
            logger.info(f"✅ Розыгрыш #{raffle.raffle_number} ({raffle_date}) автоматически закрыт в 23:59")
            return True
            
    except Exception as e:
        logger.error(f"Ошибка при автоматическом закрытии розыгрыша {raffle_date}: {e}")
        return False


async def stop_raffle(raffle_date: str) -> bool:
    """Останавливает розыгрыш и сбрасывает участие пользователей"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Raffle).where(Raffle.raffle_date == raffle_date)
            )
            raffle = result.scalar_one_or_none()
            
            if not raffle:
                return False
            
            raffle.is_active = False
            # Убираем timezone для PostgreSQL (TIMESTAMP WITHOUT TIME ZONE)
            moscow_now = datetime.now(MOSCOW_TZ)
            raffle.stopped_at = moscow_now.astimezone(timezone.utc).replace(tzinfo=None)
            
            # Сбрасываем участие всех пользователей для этого розыгрыша
            # Это позволит им принять участие снова при перезапуске
            participants_result = await session.execute(
                select(RaffleParticipant).where(
                    RaffleParticipant.raffle_date == raffle_date
                )
            )
            participants = participants_result.scalars().all()
            
            reset_count = 0
            for participant in participants:
                # Сбрасываем question_id на 0, чтобы разрешить повторное участие
                # Очищаем ответ, если он был дан
                # question_id = 0 означает, что пользователь получил объявление, но еще не нажал кнопку
                participant.question_id = 0
                participant.question_text = ""  # Пустая строка вместо None (поле nullable=False)
                participant.answer = None
                participant.is_correct = None
                
                # Отменяем задачу таймаута для этого пользователя, если она существует
                if participant.user_id in raffle_timeout_tasks:
                    timeout_task = raffle_timeout_tasks.pop(participant.user_id)
                    timeout_task.cancel()
                    logger.debug(f"Задача таймаута отменена для пользователя {participant.user_id} при остановке розыгрыша")
                
                reset_count += 1
            
            await session.commit()
            
            logger.info(
                f"Розыгрыш #{raffle.raffle_number} ({raffle_date}) остановлен. "
                f"Сброшено участие для {reset_count} пользователей"
            )
            return True
            
    except Exception as e:
        logger.error(f"Ошибка при остановке розыгрыша: {e}")
        return False


async def get_raffle_by_date(raffle_date: str) -> Optional[Raffle]:
    """Получает розыгрыш по дате"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Raffle).where(Raffle.raffle_date == raffle_date)
            )
            return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Ошибка при получении розыгрыша: {e}")
        return None


async def get_last_active_raffle() -> Optional[Raffle]:
    """Получает последний активный розыгрыш"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Raffle)
                .where(Raffle.is_active == True)
                .order_by(Raffle.created_at.desc())
            )
            return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Ошибка при получении последнего активного розыгрыша: {e}")
        return None


async def send_raffle_announcement(bot, user_id: int, raffle_date: str, force_send: bool = False, is_automatic: bool = False) -> Optional[int]:
    """Отправляет объявление о розыгрыше пользователю
    
    Args:
        bot: Экземпляр бота
        user_id: ID пользователя
        raffle_date: Дата розыгрыша (YYYY-MM-DD)
        force_send: Если True, отправляет объявление даже если оно уже было отправлено сегодня
        is_automatic: Если True, это автоматический запуск из scheduler - всегда отправляет в запланированное время
    
    Returns:
        message_id если успешно, None в противном случае
    """
    # Проверяем, не было ли уже отправлено объявление сегодня
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(RaffleParticipant).where(
                and_(
                    RaffleParticipant.user_id == user_id,
                    RaffleParticipant.raffle_date == raffle_date,
                    RaffleParticipant.announcement_time.isnot(None)
                )
            )
        )
        existing_participant = result.scalar_one_or_none()
        
        # Определяем текущее время в МСК для проверок
        moscow_now = datetime.now(MOSCOW_TZ)
        
        # Если это автоматический запуск - ВСЕГДА отправляем объявления в запланированное время
        if is_automatic:
            if existing_participant and existing_participant.announcement_time:
                announcement_utc = existing_participant.announcement_time.replace(tzinfo=timezone.utc)
                announcement_moscow = announcement_utc.astimezone(MOSCOW_TZ)
                logger.info(
                    f"🔄 Автоматический запуск: объявление о розыгрыше {raffle_date} уже было отправлено пользователю {user_id} "
                    f"в {announcement_moscow.strftime('%H:%M:%S')} МСК, но отправляем повторно в запланированное время."
                )
            # Продолжаем отправку (не возвращаемся)
        elif existing_participant and existing_participant.announcement_time and not force_send:
            # Если это не запланированное время (например, ручной запуск), проверяем дубликаты
            announcement_utc = existing_participant.announcement_time.replace(tzinfo=timezone.utc)
            announcement_moscow = announcement_utc.astimezone(MOSCOW_TZ)
            
            # Если объявление было отправлено сегодня, не отправляем повторно (для ручных запусков)
            if announcement_moscow.date() == moscow_now.date():
                logger.info(
                    f"⏭️ Объявление о розыгрыше {raffle_date} уже отправлено пользователю {user_id} "
                    f"сегодня в {announcement_moscow.strftime('%H:%M:%S')} МСК. Пропускаем повторную отправку."
                )
                return existing_participant.message_id  # Возвращаем существующий message_id
    
    # Создаем или получаем розыгрыш
    # При автоматическом запуске активируем розыгрыш, если он был остановлен
    raffle = await create_or_get_raffle(raffle_date, force_activate=is_automatic)
    raffle_number = raffle.raffle_number if raffle else "?"
    
    text = (
        f"🎉 <b>Розыгрыш #{raffle_number} начался!</b>\n\n"
        "У тебя есть 2 часа, чтобы принять участие.\n\n"
        "Нажми на кнопку ниже, чтобы начать!"
    )
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(
            text="✅ Принять участие",
            callback_data=f"raffle_join_{raffle_date}"
        )]
    ])
    
    try:
        message = await bot.send_message(
            user_id,
            text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        
        # Сохраняем время отправки объявления (МСК -> UTC для БД)
        announcement_time_moscow = datetime.now(MOSCOW_TZ)
        announcement_time_utc = announcement_time_moscow.astimezone(timezone.utc).replace(tzinfo=None)
        try:
            async with AsyncSessionLocal() as session:
                # Проверяем, есть ли уже запись (может быть создана ранее)
                result = await session.execute(
                    select(RaffleParticipant).where(
                        and_(
                            RaffleParticipant.user_id == user_id,
                            RaffleParticipant.raffle_date == raffle_date
                        )
                    )
                )
                participant = result.scalar_one_or_none()
                
                if participant:
                    # Обновляем время отправки и message_id
                    participant.announcement_time = announcement_time_utc
                    participant.message_id = message.message_id
                else:
                    # Создаем временную запись для хранения времени отправки
                    # question_id=0 означает, что пользователь еще не нажал кнопку
                    participant = RaffleParticipant(
                        user_id=user_id,
                        raffle_date=raffle_date,
                        question_id=0,  # Временно, будет обновлено при нажатии кнопки
                        question_text="",  # Временно
                        message_id=message.message_id,
                        announcement_time=announcement_time_utc,
                        timestamp=announcement_time_utc  # Устанавливаем timestamp для совместимости
                    )
                    session.add(participant)
                
                await session.commit()
        except Exception as e:
            logger.error(f"Ошибка при сохранении времени отправки объявления: {e}", exc_info=True)
            # Не прерываем выполнение, просто логируем ошибку
        
        logger.info(f"✅ Отправлено объявление о розыгрыше {raffle_date} пользователю {user_id}")
        return message.message_id
    except Exception as e:
        logger.error(f"Ошибка при отправке объявления о розыгрыше пользователю {user_id}: {e}")
        return None


async def send_raffle_reminder(bot, user_id: int, raffle_date: str):
    """Отправляет напоминание о розыгрыше"""
    text = (
        "⏰ <b>Напоминание о розыгрыше!</b>\n\n"
        "У тебя еще есть время принять участие.\n\n"
        "Нажми на кнопку ниже!"
    )
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(
            text="✅ Принять участие",
            callback_data=f"raffle_join_{raffle_date}"
        )]
    ])
    
    await safe_send_message(
        bot,
        user_id,
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


async def handle_raffle_participation(bot, user_id: int, message_id: int, raffle_date: str) -> bool:
    """Обрабатывает нажатие кнопки 'Принять участие'
    
    Returns:
        True если успешно, False в противном случае
    """
    try:
        # Проверяем, активен ли розыгрыш
        if not await is_raffle_active(raffle_date):
            logger.warning(f"Попытка участия в остановленном розыгрыше {raffle_date}")
            return False
        
        # Получаем случайный вопрос для этой даты розыгрыша
        question = get_random_question(raffle_date)
        if not question:
            logger.error(f"Не удалось получить вопрос для розыгрыша {raffle_date}")
            return False
        
        # Проверяем, не участвовал ли уже пользователь в этом розыгрыше
        async with AsyncSessionLocal() as session:
            existing = await session.execute(
                select(RaffleParticipant).where(
                    and_(
                        RaffleParticipant.user_id == user_id,
                        RaffleParticipant.raffle_date == raffle_date
                    )
                )
            )
            existing_participant = existing.scalar_one_or_none()
            
            if existing_participant:
                # Если уже есть запись с question_id != 0, значит уже участвует
                if existing_participant.question_id != 0:
                    return False
                
                # Если запись есть, но question_id == 0, обновляем её
                existing_participant.question_id = question["id"]
                existing_participant.question_text = question["text"]
                existing_participant.message_id = message_id
                # Сохраняем время в UTC для совместимости с БД
                moscow_time = datetime.now(MOSCOW_TZ)
                existing_participant.timestamp = moscow_time.astimezone(timezone.utc).replace(tzinfo=None)
            else:
                # Создаем новую запись об участии
                # Сохраняем время в UTC для совместимости с БД
                moscow_time = datetime.now(MOSCOW_TZ)
                participant = RaffleParticipant(
                    user_id=user_id,
                    raffle_date=raffle_date,
                    question_id=question["id"],
                    question_text=question["text"],
                    message_id=message_id,
                    timestamp=moscow_time.astimezone(timezone.utc).replace(tzinfo=None)
                )
                session.add(participant)
            
            await session.commit()
        
        # Редактируем сообщение с объявлением
        warning_text = (
            "⚠️ <b>Внимание!</b> Ты можешь ответить только один раз.\n"
            "У тебя есть 15 минут с момента получения вопроса."
        )
        
        question_text = (
            f"❓ <b>{question['title']}</b>\n\n"
            f"{question['text']}\n\n"
            f"{warning_text}"
        )
        
        try:
            keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])  # Убираем кнопку
            await bot.edit_message_text(
                question_text,
                chat_id=user_id,
                message_id=message_id,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения {message_id}: {e}")
            # Если не удалось отредактировать, отправляем новое сообщение
            await safe_send_message(bot, user_id, question_text, parse_mode="HTML")
        
        # Запускаем задачу для проверки ответа через 15 минут
        timeout_task = asyncio.create_task(check_answer_timeout(bot, user_id, raffle_date, RAFFLE_ANSWER_TIME))
        # Сохраняем задачу, чтобы можно было её отменить при ответе
        raffle_timeout_tasks[user_id] = timeout_task
        
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при обработке участия в розыгрыше: {e}")
        return False


async def save_user_answer(user_id: int, raffle_date: str, answer: str) -> bool:
    """Сохраняет ответ пользователя"""
    try:
        async with AsyncSessionLocal() as session:
            participant = await session.execute(
                select(RaffleParticipant).where(
                    and_(
                        RaffleParticipant.user_id == user_id,
                        RaffleParticipant.raffle_date == raffle_date
                    )
                )
            )
            participant = participant.scalar_one_or_none()
            
            if not participant:
                logger.warning(f"Попытка сохранить ответ для несуществующего участника {user_id}")
                return False
            
            if participant.answer is not None:
                logger.warning(f"Пользователь {user_id} уже ответил на вопрос")
                return False
            
            # Проверяем, не истекло ли время на ответ (15 минут с момента получения вопроса)
            moscow_now = datetime.now(MOSCOW_TZ)
            # timestamp сохраняется в UTC (без timezone), конвертируем в МСК
            if participant.timestamp.tzinfo is None:
                # timestamp без timezone - предполагаем что это UTC
                timestamp_utc = participant.timestamp.replace(tzinfo=timezone.utc)
                timestamp_moscow = timestamp_utc.astimezone(MOSCOW_TZ)
            else:
                # Если есть timezone, конвертируем в МСК
                timestamp_moscow = participant.timestamp.astimezone(MOSCOW_TZ)
            
            time_since_question = (moscow_now - timestamp_moscow).total_seconds() / 60
            
            logger.info(
                f"Проверка времени для пользователя {user_id}: "
                f"прошло {time_since_question:.2f} минут, лимит: {RAFFLE_ANSWER_TIME} минут, "
                f"timestamp: {timestamp_moscow}, сейчас: {moscow_now}"
            )
            
            # Используем >= вместо > для более строгой проверки
            if time_since_question >= RAFFLE_ANSWER_TIME:
                logger.warning(
                    f"❌ ОТКЛОНЕНО: Попытка сохранить ответ после истечения времени для пользователя {user_id}. "
                    f"Прошло {time_since_question:.2f} минут (лимит: {RAFFLE_ANSWER_TIME} минут)"
                )
                return False
            
            logger.info(
                f"✅ Время в пределах лимита для пользователя {user_id}: "
                f"{time_since_question:.2f} минут < {RAFFLE_ANSWER_TIME} минут"
            )
            
            # Сохраняем ответ (timestamp уже установлен при получении вопроса)
            participant.answer = answer
            # Не обновляем timestamp - он должен оставаться временем получения вопроса (МСК)
            await session.commit()
            
            # Отменяем задачу таймаута, если она существует
            if user_id in raffle_timeout_tasks:
                timeout_task = raffle_timeout_tasks.pop(user_id)
                timeout_task.cancel()
                try:
                    await timeout_task
                except asyncio.CancelledError:
                    pass  # Ожидаемое исключение при отмене задачи
                logger.debug(f"Задача таймаута отменена для пользователя {user_id}")
            
            # Пересылаем ответ админам
            from config import ADMIN_IDS
            if ADMIN_IDS:
                from aiogram import Bot
                from config import TG_TOKEN
                bot = Bot(TG_TOKEN)
                
                admin_text = (
                    f"📨 <b>Ответ на розыгрыш</b>\n\n"
                    f"👤 Пользователь: {user_id}\n"
                    f"📅 Дата розыгрыша: {raffle_date}\n"
                    f"❓ Вопрос: {participant.question_text}\n"
                    f"💬 Ответ: {answer}"
                )
                
                # Создаем клавиатуру с кнопками для проверки
                from aiogram import types
                keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
                    [
                        types.InlineKeyboardButton(
                            text="✅ Принять",
                            callback_data=f"admin_approve_{user_id}_{raffle_date}"
                        ),
                        types.InlineKeyboardButton(
                            text="❌ Отклонить",
                            callback_data=f"admin_deny_{user_id}_{raffle_date}"
                        )
                    ]
                ])
                
                for admin_id in ADMIN_IDS:
                    await safe_send_message(
                        bot, 
                        admin_id, 
                        admin_text, 
                        parse_mode="HTML",
                        reply_markup=keyboard
                    )
                
                await bot.session.close()
            
            return True
            
    except Exception as e:
        logger.error(f"Ошибка при сохранении ответа: {e}")
        return False


async def get_participants_by_question(raffle_date: str, question_id: int) -> List[RaffleParticipant]:
    """Получает список участников по вопросу"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(RaffleParticipant).where(
                    and_(
                        RaffleParticipant.raffle_date == raffle_date,
                        RaffleParticipant.question_id == question_id
                    )
                )
            )
            return list(result.scalars().all())
    except Exception as e:
        logger.error(f"Ошибка при получении участников: {e}")
        return []


async def approve_answer(user_id: int, raffle_date: str) -> bool:
    """Принимает ответ пользователя"""
    try:
        async with AsyncSessionLocal() as session:
            participant = await session.execute(
                select(RaffleParticipant).where(
                    and_(
                        RaffleParticipant.user_id == user_id,
                        RaffleParticipant.raffle_date == raffle_date
                    )
                )
            )
            participant = participant.scalar_one_or_none()
            
            if not participant:
                return False
            
            participant.is_correct = True
            await session.commit()
            
            # Отправляем пользователю сообщение и картинку
            from aiogram import Bot
            from config import TG_TOKEN
            bot = Bot(TG_TOKEN)
            
            await safe_send_message(bot, user_id, "✅ Ты ответил правильно!")
            
            # Отправляем картинку билет.png
            from aiogram.types import FSInputFile
            ticket_path = Path("data/билет.png")
            if not ticket_path.exists():
                # Пробуем разные варианты написания
                for variant in ["biлет.png", "билет.PNG", "biлет.PNG", "ticket.png"]:
                    alt_path = Path(f"data/{variant}")
                    if alt_path.exists():
                        ticket_path = alt_path
                        break
            
            if ticket_path.exists():
                photo_file = FSInputFile(ticket_path)
                await safe_send_photo(bot, user_id, photo_file, caption="🎫 Твой билет!")
            else:
                logger.warning(f"Файл билет.png не найден в data/")
            
            await bot.session.close()
            return True
            
    except Exception as e:
        logger.error(f"Ошибка при принятии ответа: {e}")
        return False


async def deny_answer(user_id: int, raffle_date: str) -> bool:
    """Отклоняет ответ пользователя"""
    try:
        async with AsyncSessionLocal() as session:
            participant = await session.execute(
                select(RaffleParticipant).where(
                    and_(
                        RaffleParticipant.user_id == user_id,
                        RaffleParticipant.raffle_date == raffle_date
                    )
                )
            )
            participant = participant.scalar_one_or_none()
            
            if not participant:
                return False
            
            participant.is_correct = False
            await session.commit()
            
            # Отправляем пользователю сообщение и картинку
            from aiogram import Bot
            from config import TG_TOKEN
            bot = Bot(TG_TOKEN)
            
            await safe_send_message(bot, user_id, "❌ Повтори ценности")
            
            # Отправляем картинку ценности.jpg
            from aiogram.types import FSInputFile
            values_path = Path("data/ценности.jpg")
            if not values_path.exists():
                # Пробуем разные варианты написания
                for variant in ["ценности.JPG", "ценности.jpeg", "ценности.JPEG", "values.jpg"]:
                    alt_path = Path(f"data/{variant}")
                    if alt_path.exists():
                        values_path = alt_path
                        break
            
            if values_path.exists():
                photo_file = FSInputFile(values_path)
                await safe_send_photo(bot, user_id, photo_file)
            else:
                logger.warning(f"Файл ценности.jpg не найден в data/")
            
            await bot.session.close()
            return True
            
    except Exception as e:
        logger.error(f"Ошибка при отклонении ответа: {e}")
        return False
