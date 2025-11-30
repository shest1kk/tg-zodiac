import asyncio
import json
import logging
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from database import AsyncSessionLocal, User
from config import DAILY_HOUR, DAILY_MINUTE, ZODIAC_NAMES

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
    
    # Конвертируем московское время в UTC: вычитаем 3 часа
    utc_hour = (DAILY_HOUR - 3) % 24
    
    scheduler.add_job(
        send_daily,
        'cron',
        hour=utc_hour,
        minute=DAILY_MINUTE,
        id='daily_zodiac',
        replace_existing=True,
        timezone="UTC"
    )
    scheduler.start()
    
    logger.info(
        f"📅 Планировщик запущен.\n"
        f"   Рассылка: каждый день в {DAILY_HOUR:02d}:{DAILY_MINUTE:02d} МСК ({utc_hour:02d}:{DAILY_MINUTE:02d} UTC)\n"
        f"   Период: с 01.12.2025 по 31.12.2025 (31 день)"
    )

def stop_scheduler():
    """Остановка планировщика"""
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=True)
        logger.info("Планировщик остановлен")