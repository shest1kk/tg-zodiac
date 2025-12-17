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

# Путь к файлу с квизами
QUIZ_JSON_PATH = Path("data/quiz.json")

# Словарь для хранения задач таймаута: {user_id: task}
quiz_timeout_tasks = {}

# Блокировка для предотвращения race condition при выдаче билетиков
_ticket_number_lock = asyncio.Lock()


def load_quiz(quiz_date: str) -> Optional[Dict]:
    """Загружает квиз для указанной даты из quiz.json"""
    quiz_path = QUIZ_JSON_PATH
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

        # Поддержка нового формата:
        # quiz_dates[date] = { "meta": {...}, "questions": {...} }
        if isinstance(quiz_data, dict) and "questions" in quiz_data:
            quiz_data = quiz_data.get("questions") or {}
        
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
    quiz_path = QUIZ_JSON_PATH
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
    
    # Преобразуем словарь в список, сохраняя ID вопроса
    questions = []
    for question_id, question_data in quiz_data.items():
        if isinstance(question_data, dict):
            question_data = question_data.copy()
            question_data['id'] = int(question_id) if question_id.isdigit() else question_id
            questions.append(question_data)
        else:
            # Если данные не словарь, создаем минимальную структуру
            questions.append({
                'id': int(question_id) if question_id.isdigit() else question_id,
                'question': str(question_data) if question_data else 'Нет текста'
            })
    
    return questions


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
    quiz_path = QUIZ_JSON_PATH
    try:
        with open(quiz_path, "w", encoding="utf-8") as f:
            json.dump(quiz_data, f, ensure_ascii=False, indent=4)
        logger.info(f"Квизы успешно сохранены в {quiz_path}")
        return True
    except (IOError, TypeError) as e:
        logger.error(f"Ошибка при сохранении квизов: {e}")
        return False


def _ensure_quiz_date_new_format(all_data: Dict, quiz_date: str) -> bool:
    """Гарантирует новый формат записи по дате: {meta, questions}. Возвращает True если меняли данные."""
    if not all_data or "quiz_dates" not in all_data or not isinstance(all_data["quiz_dates"], dict):
        return False

    entry = all_data["quiz_dates"].get(quiz_date)
    if entry is None:
        return False

    # Уже новый формат
    if isinstance(entry, dict) and "questions" in entry:
        if "meta" not in entry or not isinstance(entry.get("meta"), dict):
            entry["meta"] = {}
            return True
        return False

    # Старый формат: entry = {"1": {...}, ...}
    if isinstance(entry, dict):
        all_data["quiz_dates"][quiz_date] = {"meta": {}, "questions": entry}
        return True

    return False


def set_quiz_meta_from_local(quiz_date: str, title: str, starts_at_local: str) -> Dict:
    """Обновляет meta квиза (title, starts_at) по дате.

    starts_at_local: YYYY-MM-DDTHH:MM (интерпретируем как МСК)
    """
    if not isinstance(title, str) or not title.strip():
        return {"success": False, "error": "Заголовок обязателен"}
    if not isinstance(starts_at_local, str) or not starts_at_local.strip():
        return {"success": False, "error": "Дата/время обязательны"}

    try:
        starts_at_dt = datetime.fromisoformat(starts_at_local.strip())
        if starts_at_dt.tzinfo is not None:
            starts_at_dt = starts_at_dt.astimezone(MOSCOW_TZ)
        else:
            starts_at_dt = starts_at_dt.replace(tzinfo=MOSCOW_TZ)
        starts_at_dt = starts_at_dt.astimezone(MOSCOW_TZ)
    except Exception:
        return {"success": False, "error": "Неверный формат даты/времени (ожидается YYYY-MM-DDTHH:MM)"}

    if starts_at_dt.date().strftime("%Y-%m-%d") != quiz_date:
        return {"success": False, "error": "Дата starts_at должна совпадать с quiz_date. Для переноса используйте дублирование."}

    all_data = load_all_quiz_data()
    if not all_data:
        return {"success": False, "error": "quiz.json не найден или поврежден"}
    if "quiz_dates" not in all_data or not isinstance(all_data["quiz_dates"], dict):
        return {"success": False, "error": "Неверная структура quiz.json"}
    if quiz_date not in all_data["quiz_dates"]:
        return {"success": False, "error": "Квиз не найден"}

    changed = _ensure_quiz_date_new_format(all_data, quiz_date)
    entry = all_data["quiz_dates"][quiz_date]
    if "meta" not in entry or not isinstance(entry.get("meta"), dict):
        entry["meta"] = {}
        changed = True

    entry["meta"]["title"] = title.strip()
    entry["meta"]["starts_at"] = starts_at_dt.isoformat()
    changed = True

    if not save_quiz_data(all_data):
        return {"success": False, "error": "Не удалось сохранить quiz.json"}

    return {"success": True, "quiz_date": quiz_date, "changed": changed}


def duplicate_quiz_from_local(source_quiz_date: str, starts_at_local: str, title: str) -> Dict:
    """Дублирует квиз с новой датой/временем и заголовком, копируя вопросы."""
    if not isinstance(source_quiz_date, str) or not source_quiz_date.strip():
        return {"success": False, "error": "source_quiz_date обязателен"}
    if not isinstance(title, str) or not title.strip():
        return {"success": False, "error": "Заголовок обязателен"}
    if not isinstance(starts_at_local, str) or not starts_at_local.strip():
        return {"success": False, "error": "Дата/время обязательны"}

    try:
        starts_at_dt = datetime.fromisoformat(starts_at_local.strip())
        if starts_at_dt.tzinfo is not None:
            starts_at_dt = starts_at_dt.astimezone(MOSCOW_TZ)
        else:
            starts_at_dt = starts_at_dt.replace(tzinfo=MOSCOW_TZ)
        starts_at_dt = starts_at_dt.astimezone(MOSCOW_TZ)
    except Exception:
        return {"success": False, "error": "Неверный формат даты/времени (ожидается YYYY-MM-DDTHH:MM)"}

    target_quiz_date = starts_at_dt.date().strftime("%Y-%m-%d")

    all_data = load_all_quiz_data()
    if not all_data:
        all_data = {"quiz_dates": {}}
    if "quiz_dates" not in all_data or not isinstance(all_data["quiz_dates"], dict):
        all_data["quiz_dates"] = {}

    if source_quiz_date not in all_data["quiz_dates"]:
        return {"success": False, "error": "Исходный квиз не найден"}
    if target_quiz_date in all_data["quiz_dates"]:
        return {"success": False, "error": f"Квиз на дату {target_quiz_date} уже существует"}

    # Берём вопросы из source (поддержка обоих форматов)
    source_entry = all_data["quiz_dates"][source_quiz_date]
    if isinstance(source_entry, dict) and "questions" in source_entry:
        source_questions = source_entry.get("questions") or {}
    else:
        source_questions = source_entry if isinstance(source_entry, dict) else {}

    # Нормализуем копию вопросов
    questions_dict = {}
    idx = 1
    for k in sorted(source_questions.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x)):
        q = source_questions.get(k)
        if not isinstance(q, dict):
            continue
        questions_dict[str(idx)] = {
            "id": idx,
            "question": q.get("question") or "",
            "options": q.get("options") or {},
            "correct_answer": str(q.get("correct_answer") or "1"),
        }
        idx += 1
    if not questions_dict:
        return {"success": False, "error": "В исходном квизе нет вопросов"}

    all_data["quiz_dates"][target_quiz_date] = {
        "meta": {
            "title": title.strip(),
            "starts_at": starts_at_dt.isoformat(),
        },
        "questions": questions_dict,
    }

    if not save_quiz_data(all_data):
        return {"success": False, "error": "Не удалось сохранить quiz.json"}

    return {"success": True, "quiz_date": target_quiz_date}

def get_quiz_meta(quiz_date: str) -> Dict:
    """Возвращает метаданные квиза для даты (title, starts_at и т.д.).

    Поддерживает оба формата:
    - старый: quiz_dates[date] = { "1": {...}, ... }
    - новый:  quiz_dates[date] = { "meta": {...}, "questions": {...} }
    """
    all_data = load_all_quiz_data()
    if not all_data or "quiz_dates" not in all_data:
        return {}

    date_entry = all_data["quiz_dates"].get(quiz_date)
    if not isinstance(date_entry, dict):
        return {}

    if "meta" in date_entry and isinstance(date_entry.get("meta"), dict):
        return date_entry.get("meta") or {}
    return {}


def get_quiz_title(quiz_date: str) -> Optional[str]:
    meta = get_quiz_meta(quiz_date)
    title = meta.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return None


def get_quiz_start_datetime_moscow(quiz_date: str) -> Optional[datetime]:
    """Возвращает datetime начала квиза в МСК (timezone-aware).

    - Если в meta есть starts_at (ISO), используем его.
    - Иначе — комбинируем quiz_date + QUIZ_HOUR/QUIZ_MINUTE.
    """
    # starts_at в ISO, например: 2025-12-17T12:00:00+03:00
    meta = get_quiz_meta(quiz_date)
    starts_at = meta.get("starts_at")
    if isinstance(starts_at, str) and starts_at.strip():
        try:
            dt = datetime.fromisoformat(starts_at.strip())
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=MOSCOW_TZ)
            return dt.astimezone(MOSCOW_TZ)
        except Exception:
            logger.warning(f"Не удалось распарсить meta.starts_at для {quiz_date}: {starts_at}")

    try:
        date_obj = datetime.strptime(quiz_date, "%Y-%m-%d").date()
        dt = datetime.combine(date_obj, dt_time(hour=QUIZ_HOUR, minute=QUIZ_MINUTE))
        return dt.replace(tzinfo=MOSCOW_TZ)
    except Exception:
        return None


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
    
    date_entry = quiz_dates[quiz_date]
    # Новый формат: {meta, questions}
    if isinstance(date_entry, dict) and "questions" in date_entry:
        questions = date_entry.get("questions") or {}
    else:
        questions = date_entry

    if not isinstance(questions, dict):
        return False
    # Ищем вопрос по ID или по ключу
    question_found = False
    for question_key, question in questions.items():
        if not isinstance(question, dict):
            continue
        # Проверяем по ID (может быть число или строка)
        question_id_in_data = question.get("id")
        if (question_id_in_data == question_id or 
            str(question_id_in_data) == str(question_id) or
            str(question_key) == str(question_id)):
            question["question"] = question_text
            question["options"] = options
            question["correct_answer"] = correct_answer
            question_found = True
            break
    
    if question_found:
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
        
        quiz_title = get_quiz_title(quiz_date)
        title_block = f"<b>{quiz_title}</b>\n\n" if quiz_title else ""
        announcement_text = (
            f"🎯 <b>Квиз начинается!</b>\n\n"
            f"{title_block}"
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


async def get_next_ticket_number(session=None) -> int:
    """Получает следующий номер билетика (начиная с 101)
    Ищет максимальный номер из QuizResult и RaffleParticipant
    
    Использует блокировку для предотвращения race condition при одновременных запросах
    Проверяет на дубли и уведомляет админов при обнаружении
    
    Args:
        session: Опциональная сессия БД. Если не указана, создается новая.
                 Если указана, блокировка удерживается до завершения транзакции.
    """
    # Если сессия передана, используем её (блокировка уже должна быть захвачена вызывающим кодом)
    # Если нет, создаем новую сессию и захватываем блокировку
    if session is None:
        async with _ticket_number_lock:
            try:
                async with AsyncSessionLocal() as new_session:
                    return await _get_next_ticket_number_internal(new_session, start_number=TICKET_START_NUMBER + 1)
            except Exception as e:
                logger.error(f"Ошибка при получении следующего номера билетика: {e}")
                return TICKET_START_NUMBER + 1
    else:
        # Сессия передана - предполагаем, что блокировка уже захвачена
        return await _get_next_ticket_number_internal(session, start_number=TICKET_START_NUMBER + 1)


async def _get_next_ticket_number_internal(session, start_number: int = None) -> int:
    """Внутренняя функция для получения следующего номера билетика
    
    Args:
        session: Сессия БД
        start_number: Начальный номер, если билетов еще нет. Если None, используется TICKET_START_NUMBER + 1
    """
    # Находим максимальный номер билетика из квизов
    quiz_result = await session.execute(
        select(func.max(QuizResult.ticket_number)).where(
            QuizResult.ticket_number.isnot(None)
        )
    )
    max_quiz_ticket = quiz_result.scalar_one_or_none()
    
    # Находим максимальный номер билетика из розыгрышей
    from database import RaffleParticipant
    raffle_result = await session.execute(
        select(func.max(RaffleParticipant.ticket_number)).where(
            RaffleParticipant.ticket_number.isnot(None)
        )
    )
    max_raffle_ticket = raffle_result.scalar_one_or_none()
    
    # Берем максимальный из двух
    max_ticket = None
    if max_quiz_ticket is not None:
        max_ticket = max_quiz_ticket
    if max_raffle_ticket is not None:
        if max_ticket is None or max_raffle_ticket > max_ticket:
            max_ticket = max_raffle_ticket
    
    # Если нет билетов, используем переданный start_number или значение по умолчанию
    if max_ticket is None:
        if start_number is not None:
            next_ticket = start_number
        else:
            next_ticket = TICKET_START_NUMBER + 1  # Первый билетик = 101
    else:
        next_ticket = max_ticket + 1
    
    # Проверяем на дубли (на всякий случай, хотя блокировка должна предотвратить)
    duplicate_check_quiz = await session.execute(
        select(QuizResult).where(QuizResult.ticket_number == next_ticket)
    )
    duplicate_quiz = duplicate_check_quiz.scalars().first()
    
    duplicate_check_raffle = await session.execute(
        select(RaffleParticipant).where(RaffleParticipant.ticket_number == next_ticket)
    )
    duplicate_raffle = duplicate_check_raffle.scalars().first()
    
    if duplicate_quiz or duplicate_raffle:
        # Обнаружен дубль! Уведомляем админов
        await _notify_admins_about_duplicate_ticket(next_ticket, duplicate_quiz, duplicate_raffle)
        # Выдаем следующий номер
        next_ticket += 1
        logger.error(f"⚠️ Обнаружен дубль билетика №{next_ticket - 1}! Выдан следующий номер: {next_ticket}")
    
    return next_ticket


async def _notify_admins_about_duplicate_ticket(ticket_number: int, duplicate_quiz, duplicate_raffle):
    """Уведомляет админов о обнаруженном дубле билетика"""
    try:
        from config import ADMIN_IDS, TG_TOKEN
        if not ADMIN_IDS:
            return
        
        from aiogram import Bot
        from aiogram.types import FSInputFile
        from pathlib import Path
        
        bot = Bot(TG_TOKEN)
        
        # Формируем информацию о дублях
        duplicate_info = []
        if duplicate_quiz:
            duplicate_info.append(f"Квиз: ID {duplicate_quiz.user_id}, дата {duplicate_quiz.quiz_date}")
        if duplicate_raffle:
            duplicate_info.append(f"Розыгрыш: ID {duplicate_raffle.user_id}, дата {duplicate_raffle.raffle_date}")
        
        admin_text = (
            f"⚠️ <b>ОБНАРУЖЕН ДУБЛЬ БИЛЕТИКА!</b>\n\n"
            f"🎟 Билетик №{ticket_number} уже существует:\n"
            f"{chr(10).join(duplicate_info)}\n\n"
            f"Система автоматически выдаст следующий номер.\n"
            f"Проверьте вручную с помощью команды:\n"
            f"<code>/check_ticket_time {ticket_number}</code>"
        )
        
        for admin_id in ADMIN_IDS:
            try:
                await safe_send_message(bot, admin_id, admin_text, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления админу {admin_id} о дубле билетика: {e}")
        
        await bot.session.close()
        
    except Exception as e:
        logger.error(f"Ошибка при уведомлении админов о дубле билетика: {e}", exc_info=True)


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
