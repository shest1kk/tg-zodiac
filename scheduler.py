import asyncio
import json
import logging
from datetime import datetime, date, timezone, timedelta, time as dt_time
from pathlib import Path
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, and_
from sqlalchemy.exc import SQLAlchemyError
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from database import AsyncSessionLocal, User, RaffleParticipant
from config import DAILY_HOUR, DAILY_MINUTE, ZODIAC_NAMES
from raffle import (
    send_raffle_announcement, send_raffle_reminder, is_raffle_date, auto_close_raffle,
    RAFFLE_DATES, RAFFLE_HOUR, RAFFLE_MINUTE, RAFFLE_PARTICIPATION_WINDOW, RAFFLE_REMINDER_DELAY
)
from quiz import (
    send_quiz_announcement, send_quiz_reminder, mark_non_participants,
    QUIZ_HOUR, QUIZ_MINUTE, QUIZ_PARTICIPATION_WINDOW, QUIZ_REMINDER_DELAY,
    QUIZ_START_DATE, QUIZ_END_DATE
)

# Московское время (UTC+3)
MOSCOW_TZ = timezone(timedelta(hours=3))
from resilience import (
    safe_send_message,
    safe_load_predictions,
    safe_db_operation,
    should_unsubscribe_user,
    handle_critical_error,
    RATE_LIMIT_DELAY
)

# Импорт bot будет выполнен позже для избежания циклического импорта
bot = None
scheduler = None  # Глобальный экземпляр планировщика

def set_bot(bot_instance):
    """Установка экземпляра бота для использования в scheduler"""
    global bot
    bot = bot_instance

logger = logging.getLogger(__name__)

def _quiz_disabled_file() -> Path:
    # scheduler.py лежит в корне проекта
    base_dir = Path(__file__).parent
    return base_dir / "data" / "quiz_disabled_dates.json"


def _load_quiz_disabled_dates() -> set[str]:
    disabled_file = _quiz_disabled_file()
    try:
        if disabled_file.exists():
            with open(disabled_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                dates = data.get("dates", [])
                if isinstance(dates, list):
                    return set(str(d).strip() for d in dates if str(d).strip())
    except Exception as e:
        logger.warning(f"Не удалось загрузить quiz_disabled_dates.json: {e}")
    return set()


def _is_quiz_disabled(quiz_date: str) -> bool:
    return quiz_date in _load_quiz_disabled_dates()


def _schedule_quiz_jobs_for_date(quiz_date: str):
    """Планирует объявление/напоминание/отметку для конкретного квиза.

    Время берётся из meta.starts_at в data/quiz.json, иначе из QUIZ_HOUR/QUIZ_MINUTE.
    """
    global scheduler
    if scheduler is None:
        return

    if _is_quiz_disabled(quiz_date):
        logger.info(f"⏭️ Квиз для {quiz_date} отключен (quiz_disabled_dates.json), пропускаю планирование")
        return

    try:
        from quiz import get_quiz_start_datetime_moscow
        starts_at_moscow = get_quiz_start_datetime_moscow(quiz_date)
        if not starts_at_moscow:
            logger.warning(f"Не удалось получить starts_at для квиза {quiz_date}, пропускаю")
            return

        now_utc = datetime.now(timezone.utc)

        announcement_datetime = starts_at_moscow.astimezone(timezone.utc)
        reminder_datetime = (starts_at_moscow + timedelta(hours=QUIZ_REMINDER_DELAY)).astimezone(timezone.utc)
        mark_datetime = (starts_at_moscow + timedelta(hours=QUIZ_PARTICIPATION_WINDOW)).astimezone(timezone.utc)

        if announcement_datetime > now_utc:
            scheduler.add_job(
                send_quiz_announcements_for_date,
                "date",
                run_date=announcement_datetime,
                id=f"quiz_announcements_{quiz_date}",
                replace_existing=True,
                args=[quiz_date],
            )
            logger.info(
                f"✅ Задача объявления квиза для {quiz_date} запланирована на "
                f"{announcement_datetime.strftime('%d.%m.%Y %H:%M')} UTC "
                f"({starts_at_moscow.strftime('%d.%m.%Y %H:%M')} МСК)"
            )
        else:
            logger.debug(f"⏰ Время объявления квиза для {quiz_date} уже прошло, задача не будет создана")

        if reminder_datetime > now_utc:
            scheduler.add_job(
                send_quiz_reminders_for_date,
                "date",
                run_date=reminder_datetime,
                id=f"quiz_reminders_{quiz_date}",
                replace_existing=True,
                args=[quiz_date],
            )
            logger.info(f"✅ Задача напоминания квиза для {quiz_date} запланирована на {reminder_datetime.strftime('%d.%m.%Y %H:%M')} UTC")

        if mark_datetime > now_utc:
            scheduler.add_job(
                mark_quiz_non_participants_for_date,
                "date",
                run_date=mark_datetime,
                id=f"quiz_mark_{quiz_date}",
                replace_existing=True,
                args=[quiz_date],
            )
            logger.info(f"✅ Задача отметки не принявших участие для {quiz_date} запланирована на {mark_datetime.strftime('%d.%m.%Y %H:%M')} UTC")

    except Exception as e:
        logger.error(f"Ошибка при планировании задач квиза {quiz_date}: {e}", exc_info=True)


def schedule_quiz_jobs_if_running(quiz_date: str) -> bool:
    """Публичный хук для web-админки: сразу добавить задачи нового квиза без рестарта бота."""
    global scheduler
    if scheduler is None or not getattr(scheduler, "running", False):
        return False
    _schedule_quiz_jobs_for_date(quiz_date)
    return True


def _schedule_all_quizzes_from_json():
    """Планирует все квизы, которые есть в data/quiz.json."""
    try:
        from quiz import get_all_quiz_dates
        dates = get_all_quiz_dates()
        # Сортируем по дате на всякий случай
        for quiz_date in sorted(dates):
            _schedule_quiz_jobs_for_date(quiz_date)
    except Exception as e:
        logger.error(f"Ошибка при планировании квизов из quiz.json: {e}", exc_info=True)


def get_jobs_snapshot() -> dict:
    """Снимок состояния APScheduler для админки."""
    global scheduler
    if not scheduler:
        return {"running": False, "jobs": []}

    jobs = []
    try:
        for j in scheduler.get_jobs():
            next_run = None
            try:
                next_run = j.next_run_time.isoformat() if j.next_run_time else None
            except Exception:
                next_run = None

            jobs.append({
                "id": j.id,
                "name": getattr(j, "name", None),
                "next_run_time": next_run,
                "trigger": str(j.trigger) if getattr(j, "trigger", None) else None,
            })
    except Exception as e:
        return {"running": bool(getattr(scheduler, "running", False)), "jobs": [], "error": str(e)}

    # Стабильная сортировка: сначала с временем, потом без
    def _sort_key(x):
        return (x["next_run_time"] is None, x["next_run_time"] or "", x["id"])

    jobs.sort(key=_sort_key)
    return {"running": bool(getattr(scheduler, "running", False)), "jobs": jobs}


def reschedule_quiz_jobs_if_running(quiz_date: str) -> bool:
    """Удаляет и пересоздаёт задачи конкретного квиза (если scheduler запущен)."""
    global scheduler
    if not scheduler or not getattr(scheduler, "running", False):
        return False

    for job_id in (f"quiz_announcements_{quiz_date}", f"quiz_reminders_{quiz_date}", f"quiz_mark_{quiz_date}"):
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass

    _schedule_quiz_jobs_for_date(quiz_date)
    return True


def load_predictions():
    """Загружает данные предсказаний из файла (синхронная версия для обратной совместимости)"""
    predictions_path = Path("data/predictions.json")
    if not predictions_path.exists():
        logger.error("Файл predictions.json не найден!")
        return None, None
    
    try:
        with open(predictions_path, "r", encoding="utf-8") as f:
            predictions_data = json.load(f)
        
        start_date = predictions_data.get("start_date", "2025-12-01")
        days_data = predictions_data.get("days", {})
        return start_date, days_data
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Ошибка при загрузке предсказаний: {e}")
        return None, None

def get_today_prediction(zodiac_id: int, force_day: int = None):
    """Получает прогноз на сегодня для указанного знака зодиака
    
    Args:
        zodiac_id: ID знака зодиака (1-12)
        force_day: Принудительный день (1-31). Если None, используется текущий день
    """
    start_date, days_data = load_predictions()
    if not start_date or not days_data:
        return None, None
    
    if force_day is not None:
        current_day = force_day
    else:
        current_day = get_day_number(start_date)
    
    day_predictions = days_data.get(str(current_day), {})
    prediction_data = day_predictions.get(str(zodiac_id))
    
    return prediction_data, current_day

def get_day_number(start_date_str: str, current_date: date = None) -> int:
    """
    Вычисляет номер дня (1-31) от даты начала рассылки
    Использует московское время для корректного определения текущей даты
    Рассылка идет с 01.12.2025 по 31.12.2025 (31 день)
    """
    # Используем московское время для определения текущей даты
    if current_date is None:
        current_date = datetime.now(MOSCOW_TZ).date()
    
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        delta = (current_date - start_date).days + 1
        
        # Если рассылка еще не началась (delta < 1), используем день 1
        if delta < 1:
            logger.debug(f"Рассылка еще не началась. Текущая дата: {current_date}, дата начала: {start_date}")
            return 1
        
        # Если день > 31, используем цикл (день % 31, но не 0)
        if delta > 31:
            day_num = ((delta - 1) % 31) + 1
            logger.debug(f"Прошел 31-й день, используем цикл. Delta: {delta}, Day: {day_num}")
        else:
            day_num = delta
        
        logger.debug(f"Вычислен день рассылки: {day_num} (от {start_date}, текущая дата: {current_date})")
        return day_num
    except ValueError as e:
        logger.error(f"Ошибка парсинга даты {start_date_str}: {e}")
        return 1

async def send_daily(force_day: int = None):
    """Ежедневная рассылка прогнозов подписанным пользователям с отказоустойчивостью"""
    if bot is None:
        logger.error("Бот не инициализирован в scheduler!")
        return
    
    try:
        # Безопасная загрузка предсказаний с fallback
        start_date, days_data = await safe_load_predictions("data/predictions.json")
        if not start_date or not days_data:
            logger.error("Не удалось загрузить предсказания, пропускаем рассылку")
            return
        
        # Получаем текущую дату в московском времени для логирования
        moscow_now = datetime.now(MOSCOW_TZ)
        current_date_moscow = moscow_now.date()
        
        # Вычисляем текущий день (1-31) или используем принудительный день
        if force_day:
            current_day = force_day
            logger.info(f"⚠️ ПРИНУДИТЕЛЬНАЯ рассылка для дня {current_day} (игнорируется текущая дата)")
        else:
            current_day = get_day_number(start_date, current_date_moscow)
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
            
            # Проверяем, что рассылка в допустимом периоде (до 31 дня включительно)
            days_since_start = (current_date_moscow - start_date_obj).days + 1
            if days_since_start > 31:
                logger.warning(
                    f"⚠️ Рассылка рассчитана на 31 день (01.12-31.12). Прошло {days_since_start} дней с {start_date}. "
                    f"Используется циклический день {current_day}."
                )
            
            logger.info(
                f"📅 Рассылка: день {current_day}/31 | "
                f"Дата: {current_date_moscow.strftime('%d.%m.%Y')} (МСК) | "
                f"Время запуска: {moscow_now.strftime('%H:%M:%S')} МСК | "
                f"Начало рассылки: {start_date}"
            )
        
        # Получаем данные для текущего дня
        day_predictions = days_data.get(str(current_day), {})
        
        if not day_predictions:
            logger.warning(f"Нет данных для дня {current_day}")
            return

        # Безопасное получение всех подписанных пользователей
        try:
            users = await _get_subscribed_users()
        except SQLAlchemyError as e:
            logger.error(f"Ошибка БД при получении пользователей: {e}")
            return
        except Exception as e:
            handle_critical_error("send_daily", e, {"operation": "get_users"})
            return

        if not users:
            logger.info("Нет подписанных пользователей для рассылки")
            return

        logger.info(f"Начинаю рассылку для {len(users)} пользователей (день {current_day})")

        success_count = 0
        error_count = 0
        unsubscribe_count = 0

        for user in users:
            # Пропускаем пользователей без знака зодиака
            if not user.zodiac:
                logger.warning(f"Пользователь {user.id} подписан, но не выбрал знак зодиака. Пропускаем.")
                # Отписываем таких пользователей, чтобы не проверять их каждый раз
                await _unsubscribe_user_safe(user.id, reason="нет знака зодиака")
                continue

            zid = str(user.zodiac)
            if zid not in day_predictions:
                logger.warning(f"Нет прогноза для знака {zid} в день {current_day} (пользователь {user.id})")
                continue

            prediction_data = day_predictions[zid]
            # Используем название из базы, если есть, иначе из словаря
            zodiac_name = user.zodiac_name or ZODIAC_NAMES.get(user.zodiac, f"Знак #{user.zodiac}")
            text = (
                f"🌟 Гороскоп на сегодня - {zodiac_name}\n\n"
                f"{prediction_data.get('prediction', '')}\n\n"
                f"📝 Задание: {prediction_data.get('task', '')}"
            )

            # Безопасная отправка сообщения с автоматической обработкой ошибок
            success = await safe_send_message(bot, user.id, text)
            
            if success:
                success_count += 1
                await asyncio.sleep(RATE_LIMIT_DELAY)  # Throttling для избежания rate limit
            else:
                error_count += 1
                # Проверяем, нужно ли отписать пользователя (заблокировал бота и т.д.)
                # Это уже обработано внутри safe_send_message, но проверим еще раз
                try:
                    # Пытаемся отписать, если пользователь заблокировал бота
                    # (это уже сделано в safe_send_message, но добавим для надежности)
                    pass
                except Exception as e:
                    logger.warning(f"Ошибка при обработке ошибки отправки для пользователя {user.id}: {e}")

        logger.info(
            f"Рассылка завершена. Успешно: {success_count}, Ошибок: {error_count}, "
            f"Отписано: {unsubscribe_count}"
        )

    except Exception as e:
        handle_critical_error("send_daily", e, {"force_day": force_day})


async def _get_subscribed_users():
    """Вспомогательная функция для получения подписанных пользователей"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.subscribed == True)
        )
        return result.scalars().all()


async def _unsubscribe_user_safe(user_id: int, reason: str = "неизвестно"):
    """Безопасная отписка пользователя с обработкой ошибок"""
    try:
        async with AsyncSessionLocal() as session:
            try:
                db_user = await session.get(User, user_id)
                if db_user:
                    db_user.subscribed = False
                    await session.commit()
                    logger.info(f"Пользователь {user_id} автоматически отписан ({reason})")
            except SQLAlchemyError as e:
                await session.rollback()
                logger.error(f"Ошибка при отписке пользователя {user_id}: {e}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка при отписке пользователя {user_id}: {e}")

def start_scheduler():
    """
    Запуск планировщика ежедневной рассылки
    
    Работает следующим образом:
    - Рассылка происходит каждый день в 09:00 по Московскому времени (МСК, UTC+3)
    - Период рассылки: с 01.12.2025 по 31.12.2025 (31 день)
    - Каждый день пользователи получают прогноз для своего знака зодиака
    - День вычисляется относительно даты начала рассылки, используя московское время
    """
    global scheduler
    
    # APScheduler работает в UTC, поэтому нужно конвертировать московское время
    # 09:00 МСК (UTC+3) = 06:00 UTC
    scheduler = AsyncIOScheduler(timezone="UTC")
    
    # Конвертируем московское время в UTC через timezone (надежнее, чем простое вычитание)
    daily_time_moscow = dt_time(hour=DAILY_HOUR, minute=DAILY_MINUTE)
    temp_daily_moscow = datetime.combine(datetime(2025, 1, 1).date(), daily_time_moscow)
    temp_daily_moscow = temp_daily_moscow.replace(tzinfo=MOSCOW_TZ)
    temp_daily_utc = temp_daily_moscow.astimezone(timezone.utc)
    daily_utc_hour = temp_daily_utc.hour
    daily_utc_minute = temp_daily_utc.minute
    
    scheduler.add_job(
        send_daily,
        'cron',
        hour=daily_utc_hour,
        minute=daily_utc_minute,
        id='daily_zodiac',
        replace_existing=True,
        timezone="UTC"
    )
    
    # Планировщик для розыгрышей: конкретные даты в указанное время МСК (конвертируется в UTC)
    # Конвертируем МСК в UTC: вычитаем 3 часа
    raffle_time_moscow = dt_time(hour=RAFFLE_HOUR, minute=RAFFLE_MINUTE)
    # Создаем временную дату для конвертации времени
    temp_datetime_moscow = datetime.combine(datetime(2025, 1, 1).date(), raffle_time_moscow)
    temp_datetime_moscow = temp_datetime_moscow.replace(tzinfo=MOSCOW_TZ)
    temp_datetime_utc = temp_datetime_moscow.astimezone(timezone.utc)
    raffle_utc_hour = temp_datetime_utc.hour
    raffle_utc_minute = temp_datetime_utc.minute
    
    # Время напоминания (через час после объявления)
    reminder_time_moscow = dt_time(hour=(RAFFLE_HOUR + RAFFLE_REMINDER_DELAY) % 24, minute=RAFFLE_MINUTE)
    temp_reminder_moscow = datetime.combine(datetime(2025, 1, 1).date(), reminder_time_moscow)
    temp_reminder_moscow = temp_reminder_moscow.replace(tzinfo=MOSCOW_TZ)
    temp_reminder_utc = temp_reminder_moscow.astimezone(timezone.utc)
    reminder_utc_hour = temp_reminder_utc.hour
    reminder_utc_minute = temp_reminder_utc.minute
    
    # Добавляем задачи для каждой конкретной даты розыгрыша
    now_utc = datetime.now(timezone.utc)
    
    # Исключаем завтрашнюю дату из расписания розыгрышей (если она там есть)
    tomorrow_date = (datetime.now(MOSCOW_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")
    filtered_raffle_dates = [d for d in RAFFLE_DATES if d != tomorrow_date]
    if tomorrow_date in RAFFLE_DATES:
        logger.info(f"⏭️ Розыгрыш для {tomorrow_date} исключен из расписания")
    
    for raffle_date_str in filtered_raffle_dates:
        raffle_date_obj = datetime.strptime(raffle_date_str, "%Y-%m-%d")
        
        # Дата и время для объявления (конвертируется из МСК в UTC)
        announcement_datetime = datetime.combine(raffle_date_obj.date(), dt_time(hour=raffle_utc_hour, minute=raffle_utc_minute))
        announcement_datetime = announcement_datetime.replace(tzinfo=timezone.utc)
        
        # Дата и время для напоминания (через час после объявления, конвертируется из МСК в UTC)
        reminder_datetime = datetime.combine(raffle_date_obj.date(), dt_time(hour=reminder_utc_hour, minute=reminder_utc_minute))
        reminder_datetime = reminder_datetime.replace(tzinfo=timezone.utc)
        
        # Проверяем, не прошло ли время для объявления
        # Если время еще не прошло - создаем задачу
        if announcement_datetime > now_utc:
            scheduler.add_job(
                send_raffle_announcements_for_date,
                'date',
                run_date=announcement_datetime,
                id=f'raffle_announcements_{raffle_date_str}',
                replace_existing=True,
                args=[raffle_date_str]  # Передаем дату как аргумент
            )
            logger.info(f"✅ Задача объявления для {raffle_date_str} запланирована на {announcement_datetime.strftime('%d.%m.%Y %H:%M')} UTC ({RAFFLE_HOUR:02d}:{RAFFLE_MINUTE:02d} МСК)")
        else:
            # Время уже прошло - проверяем, было ли уже отправлено объявление
            # Если объявление уже было отправлено (есть участники с announcement_time), не создаем задачу
            logger.debug(f"⏰ Время объявления для {raffle_date_str} уже прошло ({announcement_datetime.strftime('%d.%m.%Y %H:%M')} UTC). Проверяю, было ли уже отправлено объявление...")
            # Проверка будет выполнена в самой функции send_raffle_announcements_for_date через is_automatic=True
            # Не создаем задачу, чтобы избежать повторных уведомлений при перезапуске бота
            logger.info(f"⏭️ Пропускаю создание задачи для {raffle_date_str} - время уже прошло. Используйте /raffle_start для ручного запуска.")
        
        # Проверяем, не прошло ли время для напоминания
        if reminder_datetime > now_utc:
            scheduler.add_job(
                send_raffle_reminders_for_date,
                'date',
                run_date=reminder_datetime,
                id=f'raffle_reminders_{raffle_date_str}',
                replace_existing=True,
                args=[raffle_date_str]  # Передаем дату как аргумент
            )
            logger.info(f"✅ Задача напоминания для {raffle_date_str} запланирована на {reminder_datetime.strftime('%d.%m.%Y %H:%M')} UTC")
        else:
            logger.debug(f"⏰ Время напоминания для {raffle_date_str} уже прошло. Задача не будет создана.")
        
        # Автоматическое закрытие розыгрыша в 23:59 его даты
        close_time_moscow = dt_time(hour=23, minute=59)
        temp_close_moscow = datetime.combine(raffle_date_obj.date(), close_time_moscow)
        temp_close_moscow = temp_close_moscow.replace(tzinfo=MOSCOW_TZ)
        temp_close_utc = temp_close_moscow.astimezone(timezone.utc)
        close_utc_hour = temp_close_utc.hour
        close_utc_minute = temp_close_utc.minute
        
        close_datetime = datetime.combine(raffle_date_obj.date(), dt_time(hour=close_utc_hour, minute=close_utc_minute))
        close_datetime = close_datetime.replace(tzinfo=timezone.utc)
        
        # Проверяем, не прошло ли время для закрытия
        if close_datetime > now_utc:
            scheduler.add_job(
                close_raffle_automatically,
                'date',
                run_date=close_datetime,
                id=f'raffle_close_{raffle_date_str}',
                replace_existing=True,
                args=[raffle_date_str]  # Передаем дату как аргумент
            )
            logger.info(f"✅ Задача закрытия для {raffle_date_str} запланирована на {close_datetime.strftime('%d.%m.%Y %H:%M')} UTC (23:59 МСК)")
        else:
            logger.debug(f"⏰ Время закрытия для {raffle_date_str} уже прошло. Задача не будет создана.")
    
    # Планировщик для квизов: каждый день начиная с 11.12 в 12:00 МСК
    _schedule_all_quizzes_from_json()
    
    scheduler.start()
    
    # Формируем список дат розыгрышей для логирования
    raffle_dates_for_log = ', '.join(filtered_raffle_dates) if 'filtered_raffle_dates' in locals() else ', '.join(RAFFLE_DATES)
    
    logger.info(
        f"📅 Планировщик запущен.\n"
        f"   Рассылка: каждый день в {DAILY_HOUR:02d}:{DAILY_MINUTE:02d} МСК ({daily_utc_hour:02d}:{daily_utc_minute:02d} UTC)\n"
        f"   Период: с 01.12.2025 по 31.12.2025 (31 день)\n"
        f"   🎁 Розыгрыши: в {RAFFLE_HOUR:02d}:{RAFFLE_MINUTE:02d} МСК ({raffle_utc_hour:02d}:{raffle_utc_minute:02d} UTC)\n"
        f"   Даты: {raffle_dates_for_log}\n"
        f"   🎯 Квизы: по расписанию из data/quiz.json (включая meta.starts_at)"
    )

async def send_raffle_announcements_for_date(raffle_date: str):
    """Рассылка объявлений о розыгрыше для конкретной даты
    
    Args:
        raffle_date: Дата розыгрыша в формате YYYY-MM-DD
    """
    if bot is None:
        logger.error("Бот не инициализирован в scheduler!")
        return
    
    try:
        # Проверяем, является ли указанная дата датой розыгрыша
        if not is_raffle_date(raffle_date):
            logger.debug(f"Дата {raffle_date} не является датой розыгрыша")
            return
        
        # Проверяем, было ли уже отправлено объявление для этой даты
        # Если время уже прошло и объявления были отправлены, не отправляем повторно
        moscow_now = datetime.now(MOSCOW_TZ)
        raffle_date_obj = datetime.strptime(raffle_date, "%Y-%m-%d").date()
        announcement_moscow = datetime.combine(raffle_date_obj, dt_time(hour=RAFFLE_HOUR, minute=RAFFLE_MINUTE))
        announcement_moscow = announcement_moscow.replace(tzinfo=MOSCOW_TZ)
        
        # Если время объявления уже прошло, проверяем, были ли уже отправлены объявления
        if announcement_moscow < moscow_now:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(RaffleParticipant).where(
                        and_(
                            RaffleParticipant.raffle_date == raffle_date,
                            RaffleParticipant.announcement_time.isnot(None)
                        )
                    ).limit(1)
                )
                existing = result.scalar_one_or_none()
                
                if existing:
                    logger.info(f"⏭️ Объявления для розыгрыша {raffle_date} уже были отправлены ранее. Пропускаю повторную отправку.")
                    return
        
        logger.info(f"🎁 Начинаю рассылку объявлений о розыгрыше ({raffle_date})")
        
        # Получаем всех подписанных пользователей
        try:
            users = await _get_subscribed_users()
        except Exception as e:
            logger.error(f"Ошибка при получении пользователей для розыгрыша: {e}")
            return
        
        if not users:
            logger.info("Нет подписанных пользователей для розыгрыша")
            return
        
        success_count = 0
        error_count = 0
        
        for user in users:
            # Автоматический запуск всегда отправляет объявления в запланированное время
            message_id = await send_raffle_announcement(bot, user.id, raffle_date, force_send=False, is_automatic=True)
            if message_id:
                success_count += 1
                await asyncio.sleep(RATE_LIMIT_DELAY)
            else:
                error_count += 1
        
        logger.info(
            f"Рассылка объявлений о розыгрыше завершена. "
            f"Обработано: {success_count}, Ошибок: {error_count}, "
            f"Всего пользователей: {len(users)}"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при рассылке объявлений о розыгрыше: {e}", exc_info=True)


async def close_raffle_automatically(raffle_date: str):
    """Автоматическое закрытие розыгрыша в 23:59 его даты"""
    if bot is None:
        logger.error("Бот не инициализирован в scheduler!")
        return
    
    try:
        moscow_now = datetime.now(MOSCOW_TZ)
        current_date_str = moscow_now.strftime("%Y-%m-%d")
        
        # Проверяем, что это правильная дата
        if raffle_date != current_date_str:
            logger.debug(f"Дата розыгрыша {raffle_date} не совпадает с текущей датой {current_date_str}")
            return
        
        logger.info(f"🕐 Автоматически закрываю розыгрыш {raffle_date} в 23:59")
        
        success = await auto_close_raffle(raffle_date)
        if success:
            logger.info(f"✅ Розыгрыш {raffle_date} успешно закрыт автоматически")
        else:
            logger.warning(f"⚠️ Не удалось закрыть розыгрыш {raffle_date}")
            
    except Exception as e:
        logger.error(f"Ошибка при автоматическом закрытии розыгрыша {raffle_date}: {e}", exc_info=True)


async def send_raffle_reminders_for_date(raffle_date: str):
    """Отправка напоминаний о розыгрыше для конкретной даты
    
    Args:
        raffle_date: Дата розыгрыша в формате YYYY-MM-DD
    """
    if bot is None:
        logger.error("Бот не инициализирован в scheduler!")
        return
    
    try:
        # Проверяем, является ли указанная дата датой розыгрыша
        if not is_raffle_date(raffle_date):
            logger.debug(f"Дата {raffle_date} не является датой розыгрыша")
            return
        
        logger.info(f"⏰ Отправляю напоминания о розыгрыше ({raffle_date})")
        
        # Получаем всех подписанных пользователей
        try:
            users = await _get_subscribed_users()
        except Exception as e:
            logger.error(f"Ошибка при получении пользователей для напоминаний: {e}")
            return
        
        if not users:
            return
        
        # Проверяем, кто еще не участвовал (не нажал кнопку)
        # Участник - это тот, у кого question_id != 0 (нажал кнопку и получил вопрос)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(RaffleParticipant).where(
                    and_(
                        RaffleParticipant.raffle_date == raffle_date,
                        RaffleParticipant.question_id != 0  # Участвовал (получил вопрос, нажал кнопку)
                    )
                )
            )
            participants = result.scalars().all()
            participant_ids = {p.user_id for p in participants}
        
        # Отправляем напоминания тем, кто не участвовал
        success_count = 0
        for user in users:
            if user.id not in participant_ids:
                await send_raffle_reminder(bot, user.id, raffle_date)
                success_count += 1
                await asyncio.sleep(RATE_LIMIT_DELAY)
        
        logger.info(f"Напоминания отправлены {success_count} пользователям")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке напоминаний о розыгрыше: {e}", exc_info=True)


async def send_quiz_announcements_for_date(quiz_date: str):
    """Рассылка объявлений о квизе для конкретной даты"""
    if _is_quiz_disabled(quiz_date):
        logger.info(f"⏭️ Квиз для {quiz_date} отключен (quiz_disabled_dates.json), объявления не отправляются")
        return
    
    if bot is None:
        logger.error("Бот не инициализирован в scheduler!")
        return
    
    try:
        logger.info(f"🎯 Отправляю объявления о квизе ({quiz_date})")
        
        # Получаем всех подписанных пользователей
        try:
            users = await _get_subscribed_users()
        except Exception as e:
            logger.error(f"Ошибка при получении пользователей для квиза: {e}")
            return
        
        if not users:
            return
        
        # Отправляем объявления
        success_count = 0
        error_count = 0
        
        for user in users:
            try:
                success = await send_quiz_announcement(bot, user.id, quiz_date, force_send=False, is_automatic=True)
                if success:
                    success_count += 1
                    await asyncio.sleep(RATE_LIMIT_DELAY)
                else:
                    error_count += 1
            except Exception as e:
                logger.error(f"Ошибка при отправке объявления о квизе пользователю {user.id}: {e}")
                error_count += 1
        
        logger.info(f"Объявления о квизе отправлены. Успешно: {success_count}, Ошибок: {error_count}")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке объявлений о квизе: {e}", exc_info=True)


async def send_quiz_reminders_for_date(quiz_date: str):
    """Отправка напоминаний о квизе для конкретной даты"""
    if _is_quiz_disabled(quiz_date):
        logger.info(f"⏭️ Квиз для {quiz_date} отключен (quiz_disabled_dates.json), напоминания не отправляются")
        return
    
    if bot is None:
        logger.error("Бот не инициализирован в scheduler!")
        return
    
    try:
        logger.info(f"⏰ Отправляю напоминания о квизе ({quiz_date})")
        
        # Получаем всех подписанных пользователей
        try:
            users = await _get_subscribed_users()
        except Exception as e:
            logger.error(f"Ошибка при получении пользователей для напоминаний о квизе: {e}")
            return
        
        if not users:
            return
        
        # Отправляем напоминания только тем, кто не начал квиз
        success_count = 0
        error_count = 0
        
        for user in users:
            try:
                success = await send_quiz_reminder(bot, user.id, quiz_date)
                if success:
                    success_count += 1
                    await asyncio.sleep(RATE_LIMIT_DELAY)
                else:
                    error_count += 1
            except Exception as e:
                logger.error(f"Ошибка при отправке напоминания о квизе пользователю {user.id}: {e}")
                error_count += 1
        
        logger.info(f"Напоминания о квизе отправлены. Успешно: {success_count}, Ошибок: {error_count}")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке напоминаний о квизе: {e}", exc_info=True)


async def mark_quiz_non_participants_for_date(quiz_date: str):
    """Отмечает пользователей, которые не приняли участие в квизе"""
    if _is_quiz_disabled(quiz_date):
        logger.info(f"⏭️ Квиз для {quiz_date} отключен (quiz_disabled_dates.json), отметка не принимавших участие не выполняется")
        return
    
    if bot is None:
        logger.error("Бот не инициализирован в scheduler!")
        return
    
    try:
        logger.info(f"📝 Отмечаю не принявших участие в квизе ({quiz_date})")
        await mark_non_participants(quiz_date)
        logger.info(f"Отметка не принявших участие в квизе завершена для {quiz_date}")
    except Exception as e:
        logger.error(f"Ошибка при отметке не принявших участие в квизе: {e}", exc_info=True)


def stop_scheduler():
    """Остановка планировщика"""
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=True)
        logger.info("Планировщик остановлен")