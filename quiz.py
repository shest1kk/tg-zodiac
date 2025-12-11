"""
Модуль для управления квизами
"""
import json
import logging
import asyncio
from datetime import datetime, timezone, timedelta, time as dt_time
from pathlib import Path
from typing import Optional, Dict, List
from aiogram import types
from sqlalchemy import select, and_, func
from sqlalchemy.exc import SQLAlchemyError
from database import AsyncSessionLocal, User, Quiz, QuizParticipant, QuizResult
from resilience import safe_send_message, safe_send_photo

logger = logging.getLogger(__name__)

# Московское время (UTC+3)
MOSCOW_TZ = timezone(timedelta(hours=3))

# Настройки квизов
QUIZ_HOUR = 12 # 12:00 МСК
QUIZ_MINUTE = 0
QUIZ_PARTICIPATION_WINDOW = 6  # 6 часов на участие (до 18:00)
QUIZ_REMINDER_DELAY = 3  # 3 часа до напоминания (в 15:00)
QUIZ_ANSWER_TIME = 15  # 15 минут на ответ на весь квиз
QUIZ_START_DATE = "2025-12-11"  # Первая дата квиза
QUIZ_END_DATE = "2025-12-16"  # Последняя дата квиза (включительно)
QUIZ_MIN_CORRECT_ANSWERS = 3  # Минимальное количество правильных ответов для получения билетика
TICKET_START_NUMBER = 100  # Начальный номер билетика (первый получит 101)

# Словарь для хранения задач таймаута: {user_id: task}
quiz_timeout_tasks = {}


def load_quiz(quiz_date: str) -> Optional[Dict]:
    """Загружает квиз для указанной даты из quiz.json"""
    quiz_path = Path("data/quiz.json")
    if not quiz_path.exists():
        logger.error("Файл quiz.json не найден!")
        return None
    
    try:
        with open(quiz_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        quiz_dates = data.get("quiz_dates", {})
        quiz_data = quiz_dates.get(quiz_date)
        
        if not quiz_data:
            logger.warning(f"Квиз для даты {quiz_date} не найден в quiz.json")
            return None
        
        return quiz_data
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Ошибка при загрузке квиза: {e}")
        return None


def get_question_by_id(question_id: int, quiz_date: str) -> Optional[Dict]:
    """Получает вопрос по ID для указанной даты"""
    quiz_data = load_quiz(quiz_date)
    if not quiz_data:
        return None
    
    question = quiz_data.get(str(question_id))
    return question


def get_total_questions(quiz_date: str) -> int:
    """Возвращает общее количество вопросов в квизе для указанной даты"""
    quiz_data = load_quiz(quiz_date)
    if not quiz_data:
        return 0
    
    return len(quiz_data)


def load_all_quiz_data() -> Optional[Dict]:
    """Загружает все данные квизов из quiz.json"""
    quiz_path = Path("data/quiz.json")
    if not quiz_path.exists():
        logger.error("Файл quiz.json не найден!")
        return None
    
    try:
        with open(quiz_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Ошибка при загрузке квизов: {e}")
        return None


def get_all_questions(quiz_date: str) -> List[Dict]:
    """Получает все вопросы для указанной даты"""
    quiz_data = load_quiz(quiz_date)
    if not quiz_data:
        return []
    
    return list(quiz_data.values())


def get_all_quiz_dates() -> List[str]:
    """Получает список всех дат квизов из quiz.json"""
    all_data = load_all_quiz_data()
    if not all_data or "quiz_dates" not in all_data:
        return []
    
    return list(all_data["quiz_dates"].keys())


def save_quiz_data(quiz_data: Dict) -> bool:
    """Сохраняет данные квизов в quiz.json
    
    Args:
        quiz_data: Полная структура данных с quiz_dates
        
    Returns:
        True если успешно, False в противном случае
    """
    quiz_path = Path("data/quiz.json")
    try:
        with open(quiz_path, "w", encoding="utf-8") as f:
            json.dump(quiz_data, f, ensure_ascii=False, indent=4)
        logger.info(f"Квизы успешно сохранены в {quiz_path}")
        return True
    except (IOError, json.JSONEncodeError) as e:
        logger.error(f"Ошибка при сохранении квизов: {e}")
        return False


def update_quiz_question(question_id: int, quiz_date: str, question_text: str, options: Dict[str, str], correct_answer: str) -> bool:
    """Обновляет вопрос квиза по ID для указанной даты
    
    Args:
        question_id: ID вопроса
        quiz_date: Дата квиза
        question_text: Новый текст вопроса
        options: Словарь с вариантами ответов {"A": "...", "Б": "...", ...}
        correct_answer: Правильный ответ (A, Б, В, Г)
        
    Returns:
        True если успешно, False в противном случае
    """
    all_data = load_all_quiz_data()
    if not all_data or "quiz_dates" not in all_data:
        return False
    
    quiz_dates = all_data["quiz_dates"]
    if quiz_date not in quiz_dates:
        return False
    
    questions = quiz_dates[quiz_date]
    for question_key, question in questions.items():
        if question.get("id") == question_id:
            question["question"] = question_text
            question["options"] = options
            question["correct_answer"] = correct_answer
            return save_quiz_data(all_data)
    
    return False


async def has_quiz_started(quiz_date: str) -> bool:
    """Проверяет, начался ли квиз (были ли отправлены объявления)
    
    Args:
        quiz_date: Дата квиза в формате YYYY-MM-DD
        
    Returns:
        True если квиз начался (есть участники с announcement_time), False иначе
    """
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(QuizParticipant).where(
                    and_(
                        QuizParticipant.quiz_date == quiz_date,
                        QuizParticipant.announcement_time.isnot(None)
                    )
                ).limit(1)
            )
            participant = result.scalar_one_or_none()
            return participant is not None
    except Exception as e:
        logger.error(f"Ошибка при проверке начала квиза: {e}")
        return False


async def get_quiz(quiz_date: str) -> Optional[Quiz]:
    """Получает квиз для указанной даты (без создания)"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Quiz).where(Quiz.quiz_date == quiz_date)
            )
            quiz = result.scalar_one_or_none()
            return quiz
    except SQLAlchemyError as e:
        logger.error(f"Ошибка при получении квиза: {e}")
        return None


async def create_or_get_quiz(quiz_date: str) -> Optional[Quiz]:
    """Создает или получает квиз для указанной даты"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Quiz).where(Quiz.quiz_date == quiz_date)
            )
            quiz = result.scalar_one_or_none()
            
            if not quiz:
                # Создаем новый квиз
                current_time_utc = datetime.now(MOSCOW_TZ).astimezone(timezone.utc).replace(tzinfo=None)
                quiz = Quiz(
                    quiz_date=quiz_date,
                    is_active=True,
                    created_at=current_time_utc
                )
                session.add(quiz)
                await session.commit()
                await session.refresh(quiz)
                logger.info(f"Создан новый квиз для даты {quiz_date}")
            
            return quiz
    except SQLAlchemyError as e:
        logger.error(f"Ошибка при создании/получении квиза: {e}")
        return None


async def send_quiz_announcement(bot, user_id: int, quiz_date: str, force_send: bool = False, is_automatic: bool = False):
    """Отправляет объявление о квизе пользователю"""
    try:
        moscow_now = datetime.now(MOSCOW_TZ)
        
        # Проверяем, не отправляли ли уже объявление
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(QuizParticipant).where(
                    and_(
                        QuizParticipant.user_id == user_id,
                        QuizParticipant.quiz_date == quiz_date
                    )
                )
            )
            participant = result.scalar_one_or_none()
            
            if participant and participant.announcement_time and not force_send:
                if is_automatic:
                    logger.info(f"🔄 Автоматический запуск квиза для {user_id} (объявление уже было отправлено)")
                else:
                    logger.debug(f"Объявление о квизе {quiz_date} уже отправлено пользователю {user_id}")
                    return False
        
        # Создаем или получаем квиз
        quiz = await create_or_get_quiz(quiz_date)
        if not quiz:
            logger.error(f"Не удалось создать/получить квиз для даты {quiz_date}")
            return False
        
        # Формируем текст объявления
        try:
            date_obj = datetime.strptime(quiz_date, "%Y-%m-%d")
            date_display = date_obj.strftime("%d.%m.%Y")
        except:
            date_display = quiz_date
        
        announcement_text = (
            f"🎯 <b>Квиз начинается!</b>\n\n"
            f"Нажми на кнопку ниже, чтобы принять участие.\n"
            f"У тебя есть 6 часов, чтобы начать квиз!"
        )
        
        # Создаем кнопку "Я готов"
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(
                text="✅ Я готов",
                callback_data=f"quiz_ready_{quiz_date}"
            )]
        ])
        
        # Отправляем сообщение
        message = await bot.send_message(
            user_id,
            announcement_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        
        # Сохраняем или обновляем участника
        announcement_time_utc = moscow_now.astimezone(timezone.utc).replace(tzinfo=None)
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(QuizParticipant).where(
                    and_(
                        QuizParticipant.user_id == user_id,
                        QuizParticipant.quiz_date == quiz_date
                    )
                )
            )
            participant = result.scalar_one_or_none()
            
            if participant:
                participant.message_id = message.message_id
                participant.announcement_time = announcement_time_utc
            else:
                participant = QuizParticipant(
                    user_id=user_id,
                    quiz_date=quiz_date,
                    message_id=message.message_id,
                    announcement_time=announcement_time_utc,
                    current_question=0,
                    completed=False
                )
                session.add(participant)
            
            await session.commit()
        
        logger.info(f"Объявление о квизе {quiz_date} отправлено пользователю {user_id}")
        return True
        
    except TelegramForbiddenError:
        logger.info(f"Пользователь {user_id} заблокировал бота")
        return False
    except Exception as e:
        logger.error(f"Ошибка при отправке объявления о квизе пользователю {user_id}: {e}")
        return False


async def send_quiz_reminder(bot, user_id: int, quiz_date: str):
    """Отправляет напоминание о квизе пользователю"""
    try:
        # Проверяем, начал ли пользователь квиз
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(QuizParticipant).where(
                    and_(
                        QuizParticipant.user_id == user_id,
                        QuizParticipant.quiz_date == quiz_date
                    )
                )
            )
            participant = result.scalar_one_or_none()
            
            # Если пользователь уже начал квиз или завершил его, не отправляем напоминание
            if participant and participant.started_at:
                return False
        
        reminder_text = (
            f"⏰ <b>Напоминание о квизе</b>\n\n"
            f"Сейчас проходит квиз! Ты можешь принять участие, нажав на кнопку \"Я готов\" под сообщением выше."
        )
        
        success = await safe_send_message(bot, user_id, reminder_text, parse_mode="HTML")
        
        if success:
            logger.info(f"Напоминание о квизе {quiz_date} отправлено пользователю {user_id}")
        
        return success
        
    except Exception as e:
        logger.error(f"Ошибка при отправке напоминания о квизе пользователю {user_id}: {e}")
        return False


async def mark_non_participants(quiz_date: str):
    """Отмечает пользователей, которые не приняли участие в квизе (не нажали кнопку за 6 часов)"""
    try:
        moscow_now = datetime.now(MOSCOW_TZ)
        deadline = moscow_now - timedelta(hours=QUIZ_PARTICIPATION_WINDOW)
        deadline_utc = deadline.astimezone(timezone.utc).replace(tzinfo=None)
        
        async with AsyncSessionLocal() as session:
            # Находим всех участников, которые получили объявление, но не начали квиз
            result = await session.execute(
                select(QuizParticipant).where(
                    and_(
                        QuizParticipant.quiz_date == quiz_date,
                        QuizParticipant.announcement_time.isnot(None),
                        QuizParticipant.started_at.is_(None),
                        QuizParticipant.announcement_time <= deadline_utc
                    )
                )
            )
            non_participants = result.scalars().all()
            
            # Записываем их в результаты как не принявших участие
            for participant in non_participants:
                # Проверяем, нет ли уже записи
                existing_result = await session.execute(
                    select(QuizResult).where(
                        and_(
                            QuizResult.user_id == participant.user_id,
                            QuizResult.quiz_date == quiz_date
                        )
                    )
                )
                if existing_result.scalar_one_or_none():
                    continue
                
                # Получаем username
                user_result = await session.execute(
                    select(User).where(User.id == participant.user_id)
                )
                user = user_result.scalar_one_or_none()
                username = user.username if user else None
                
                # Создаем запись о неучастии
                result = QuizResult(
                    user_id=participant.user_id,
                    username=username,
                    quiz_date=quiz_date,
                    correct_answers=0,
                    total_questions=0,
                    ticket_number=None,
                    completed_at=datetime.utcnow()
                )
                session.add(result)
            
            await session.commit()
            logger.info(f"Отмечено {len(non_participants)} пользователей как не принявших участие в квизе {quiz_date}")
            
    except Exception as e:
        logger.error(f"Ошибка при отметке не принявших участие: {e}")


async def get_next_ticket_number() -> int:
    """Получает следующий номер билетика (начиная с 101)"""
    try:
        async with AsyncSessionLocal() as session:
            # Находим максимальный номер билетика
            result = await session.execute(
                select(func.max(QuizResult.ticket_number)).where(
                    QuizResult.ticket_number.isnot(None)
                )
            )
            max_ticket = result.scalar_one_or_none()
            
            if max_ticket is None:
                return TICKET_START_NUMBER + 1  # Первый билетик = 101
            
            return max_ticket + 1
            
    except Exception as e:
        logger.error(f"Ошибка при получении следующего номера билетика: {e}")
        return TICKET_START_NUMBER + 1


async def check_quiz_timeout(bot, user_id: int, quiz_date: str):
    """Проверяет, завершил ли пользователь квиз в течение указанного времени"""
    try:
        # Ждем указанное количество минут
        await asyncio.sleep(QUIZ_ANSWER_TIME * 60)
        
        # Проверяем, завершил ли пользователь квиз
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(QuizParticipant).where(
                    and_(
                        QuizParticipant.user_id == user_id,
                        QuizParticipant.quiz_date == quiz_date
                    )
                )
            )
            participant = result.scalar_one_or_none()
            
            if not participant:
                quiz_timeout_tasks.pop(user_id, None)
                return
            
            # Если квиз не завершен, редактируем сообщение с вопросами
            if not participant.completed:
                timeout_message = "⏰ Вы не успели завершить квиз в течение 15 минут."
                
                # Пытаемся отредактировать сообщение с вопросами
                if participant.message_id:
                    try:
                        await bot.edit_message_text(
                            chat_id=user_id,
                            message_id=participant.message_id,
                            text=timeout_message
                        )
                        logger.info(f"Сообщение о таймауте квиза отредактировано для пользователя {user_id}")
                    except Exception as e:
                        logger.warning(f"Не удалось отредактировать сообщение о таймауте для пользователя {user_id}: {e}")
                        # Если не удалось отредактировать, отправляем новое сообщение
                        await safe_send_message(bot, user_id, timeout_message)
                else:
                    # Если нет message_id, отправляем новое сообщение
                    await safe_send_message(bot, user_id, timeout_message)
                
                # Помечаем квиз как завершенный (чтобы пользователь не мог продолжать отвечать)
                participant.completed = True
                participant.current_question = 0
                
                # Подсчитываем правильные ответы из уже данных ответов
                import json
                answers = json.loads(participant.answers or "{}")
                total_questions = get_total_questions(quiz_date)
                correct_count = 0
                
                # Загружаем квиз для проверки правильности ответов
                quiz_data = load_quiz(quiz_date)
                if quiz_data:
                    for q_num_str, user_answer in answers.items():
                        q_num = int(q_num_str)
                        question = quiz_data.get(str(q_num))
                        if question and question['correct_answer'] == user_answer:
                            correct_count += 1
                
                # Получаем информацию о пользователе
                user_result = await session.execute(
                    select(User).where(User.id == user_id)
                )
                user = user_result.scalar_one_or_none()
                username = user.username if user else None
                
                # Проверяем, нет ли уже записи в результатах
                existing_result = await session.execute(
                    select(QuizResult).where(
                        and_(
                            QuizResult.user_id == user_id,
                            QuizResult.quiz_date == quiz_date
                        )
                    )
                )
                existing = existing_result.scalar_one_or_none()
                
                # Сохраняем результат в QuizResult (не получил билетик из-за таймаута)
                if not existing:
                    result = QuizResult(
                        user_id=user_id,
                        username=username,
                        quiz_date=quiz_date,
                        correct_answers=correct_count,
                        total_questions=total_questions,
                        ticket_number=None,  # Не получил билетик из-за таймаута
                        completed_at=datetime.utcnow()
                    )
                    session.add(result)
                    logger.info(f"Результат квиза по таймауту сохранен для пользователя {user_id}: {correct_count}/{total_questions}")
                
                await session.commit()
                logger.info(f"Квиз помечен как завершенный по таймауту для пользователя {user_id}")
            
            quiz_timeout_tasks.pop(user_id, None)
            
    except asyncio.CancelledError:
        logger.debug(f"Задача проверки таймаута квиза отменена для пользователя {user_id}")
        quiz_timeout_tasks.pop(user_id, None)
    except Exception as e:
        logger.error(f"Ошибка при проверке таймаута квиза для пользователя {user_id}: {e}")
        quiz_timeout_tasks.pop(user_id, None)
