import asyncio
import html
import logging
from datetime import datetime, timezone, timedelta, time as dt_time
from pathlib import Path
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import FSInputFile
from aiogram.filters import Command
from aiogram.types import BotCommand
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select, and_
from database import AsyncSessionLocal, init_db, User, RaffleParticipant, Raffle, Quiz, QuizParticipant, QuizResult
from config import TG_TOKEN, DAILY_HOUR, DAILY_MINUTE, logger, ZODIAC_NAMES, ADMIN_ID, ADMIN_IDS
from scheduler import start_scheduler, stop_scheduler, get_day_number, get_today_prediction, load_predictions
from resilience import safe_send_message, safe_send_photo, RATE_LIMIT_DELAY
from raffle import (
    send_raffle_announcement, send_raffle_reminder, handle_raffle_participation,
    save_user_answer, get_participants_by_question, approve_answer, deny_answer,
    get_all_questions, get_question_by_id, update_question, get_all_raffle_dates,
    is_raffle_date, RAFFLE_ANSWER_TIME, RAFFLE_PARTICIPATION_WINDOW,
    create_or_get_raffle, stop_raffle, is_raffle_active,
    get_raffle_by_date, get_last_active_raffle, has_raffle_started, RAFFLE_DATES,
    get_unchecked_answers, get_users_for_reminder
)
from quiz import (
    send_quiz_announcement, send_quiz_reminder, mark_non_participants,
    load_quiz, get_question_by_id as get_quiz_question, get_total_questions,
    get_next_ticket_number, check_quiz_timeout, QUIZ_ANSWER_TIME, QUIZ_START_DATE,
    QUIZ_END_DATE, QUIZ_MIN_CORRECT_ANSWERS, quiz_timeout_tasks,
    MOSCOW_TZ as QUIZ_MOSCOW_TZ, QUIZ_PARTICIPATION_WINDOW, create_or_get_quiz,
    get_all_questions as get_all_quiz_questions, get_all_quiz_dates,
    update_quiz_question, has_quiz_started, get_quiz,
    QUIZ_HOUR, QUIZ_MINUTE
)

bot = Bot(TG_TOKEN)
dp = Dispatcher()

# Хранилище для отслеживания режима отправки вопроса
user_question_mode = {}

# Хранилище для режима ответа админа пользователю (admin_id -> user_id)
admin_reply_mode = {}

# Хранилище для отслеживания участников розыгрыша (user_id -> raffle_date)
raffle_participants = {}

# ----------------- Keyboard -----------------
def zodiac_keyboard():
    inline_keyboard = [
        [
            types.InlineKeyboardButton(text="♈ Овен", callback_data="z_1"),
            types.InlineKeyboardButton(text="♉ Телец", callback_data="z_2"),
            types.InlineKeyboardButton(text="♊ Близнецы", callback_data="z_3"),
            types.InlineKeyboardButton(text="♋ Рак", callback_data="z_4"),
        ],
        [
            types.InlineKeyboardButton(text="♌ Лев", callback_data="z_5"),
            types.InlineKeyboardButton(text="♍ Дева", callback_data="z_6"),
            types.InlineKeyboardButton(text="♎ Весы", callback_data="z_7"),
            types.InlineKeyboardButton(text="♏ Скорпион", callback_data="z_8"),
        ],
        [
            types.InlineKeyboardButton(text="♐ Стрелец", callback_data="z_9"),
            types.InlineKeyboardButton(text="♑ Козерог", callback_data="z_10"),
            types.InlineKeyboardButton(text="♒ Водолей", callback_data="z_11"),
            types.InlineKeyboardButton(text="♓ Рыбы", callback_data="z_12"),
        ]
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)

# ----------------- Bot Handlers -----------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    # Сбрасываем флаг режима вопроса при использовании других команд
    user_question_mode.pop(message.from_user.id, None)
    try:
        # Проверяем, новый ли пользователь, чтобы сохранить дату первого запуска
        async with AsyncSessionLocal() as session:
            try:
                user = await session.get(User, message.from_user.id)
                is_new_user = user is None
                
                if is_new_user:
                    # Создаем нового пользователя с датой регистрации
                    # НЕ устанавливаем subscribed=True и zodiac - пользователь должен выбрать знак
                    user = User(
                        id=message.from_user.id,
                        username=message.from_user.username,
                        first_name=message.from_user.first_name,
                        subscribed=False,  # Явно не подписан, пока не выберет знак
                        created_at=datetime.utcnow()
                    )
                    session.add(user)
                    await session.commit()
                    logger.info(f"Новый пользователь {message.from_user.id} зарегистрирован")
                    welcome_text = (
                        "Привет! Выбери свой знак зодиака:\n\n"
                        "💡 Используй /help, чтобы узнать все возможности бота"
                    )
                else:
                    # Обновляем информацию о пользователе
                    user.username = message.from_user.username
                    user.first_name = message.from_user.first_name
                    
                    # Проверяем: если подписан, но нет знака - это проблема
                    if user.subscribed and not user.zodiac:
                        logger.warning(f"Пользователь {user.id} подписан, но не выбрал знак зодиака. Отписываем.")
                        user.subscribed = False
                        welcome_text = (
                            "Привет! Ты был подписан, но не выбрал знак зодиака.\n\n"
                            "Выбери свой знак зодиака, чтобы получать ежедневные прогнозы:\n\n"
                            "💡 Используй /help, чтобы узнать все возможности бота"
                        )
                    elif user.subscribed and user.zodiac:
                        zodiac_name = user.zodiac_name or ZODIAC_NAMES.get(user.zodiac, f"Знак #{user.zodiac}")
                        welcome_text = (
                            f"Привет! Твой знак: {zodiac_name}.\n\n"
                            "Хочешь изменить знак зодиака? Выбери новый:\n\n"
                            "💡 Используй /help, чтобы узнать все возможности бота"
                        )
                    else:
                        welcome_text = (
                            "Привет! Выбери свой знак зодиака:\n\n"
                            "💡 Используй /help, чтобы узнать все возможности бота"
                        )
                    
                    await session.commit()
            except SQLAlchemyError as e:
                await session.rollback()
                logger.error(f"Ошибка БД при обработке /start: {e}")
                welcome_text = (
                    "Привет! Выбери свой знак зодиака:\n\n"
                    "💡 Используй /help, чтобы узнать все возможности бота"
                )
        
        await message.answer(
            welcome_text, 
            reply_markup=zodiac_keyboard()
        )
        logger.info(f"Пользователь {message.from_user.id} запустил бота")
    except Exception as e:
        logger.error(f"Ошибка при обработке /start: {e}")
        await message.answer(
            "Привет! Выбери свой знак зодиака:\n\n"
            "💡 Используй /help, чтобы узнать все возможности бота", 
            reply_markup=zodiac_keyboard()
        )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Обработчик команды /help"""
    # Сбрасываем флаг режима вопроса при использовании других команд
    user_question_mode.pop(message.from_user.id, None)
    
    help_text = (
        "🌟 <b>Доступные команды:</b>\n\n"
        "/start - Выбрать знак зодиака и подписаться на рассылку\n"
        "/change_zodiac - Изменить свой знак зодиака\n"
        "/my_info - Информация о твоей подписке\n"
        "/unsubscribe - Отписаться от ежедневных прогнозов\n"
        "/question - Задать вопрос или оставить отзыв\n\n"
        f"📅 Рассылка происходит ежедневно в {DAILY_HOUR:02d}:{DAILY_MINUTE:02d} по МСК"
    )
    
    # Если админ - добавляем админские команды
    if is_admin(message.from_user.id):
        help_text += (
            "\n\n"
            "🔐 <b>Админские команды:</b>\n"
            "<b>/admin</b> - Админ-панель\n"
            "<b>/stats</b> - Статистика бота\n"
            "<b>/reply</b> - Ответить пользователю\n"
            "<b>/broadcast</b> - Массовая рассылка\n"
            "<b>/test_send</b> - Тестовая отправка\n"
            "<b>/set_prediction</b> - Редактировать предсказания"
        )
    
    await message.answer(help_text, parse_mode="HTML")

@dp.message(Command("question"))
async def cmd_question(message: types.Message):
    """Обработчик команды /question - отправляет инструкцию и активирует режим вопроса"""
    # Админы не могут использовать команду /question
    if is_admin(message.from_user.id):
        await message.answer("❌ Эта команда недоступна для администраторов.")
        return
    
    question_text = (
        "Если у тебя что-то не работает или есть предложения по улучшению бота, "
        "просто напиши сюда в чат - мы прочитаем и починим!"
    )
    await message.answer(question_text)
    # Устанавливаем флаг, что пользователь находится в режиме отправки вопроса
    user_question_mode[message.from_user.id] = True

@dp.message(Command("change_zodiac"))
async def cmd_change_zodiac(message: types.Message):
    """Обработчик команды /change_zodiac - изменить знак зодиака"""
    await message.answer(
        "Выбери новый знак зодиака:",
        reply_markup=zodiac_keyboard()
    )

@dp.message(Command("my_info"))
async def cmd_my_info(message: types.Message):
    """Обработчик команды /my_info - информация о пользователе"""
    try:
        async with AsyncSessionLocal() as session:
            user = await session.get(User, message.from_user.id)
            
            if not user:
                await message.answer(
                    "Ты еще не зарегистрирован. Используй /start для начала."
                )
                return
            
            zodiac_name = user.zodiac_name or (ZODIAC_NAMES.get(user.zodiac) if user.zodiac else "Не выбран")
            subscribed_status = "✅ Подписан" if user.subscribed else "❌ Не подписан"
            created_at_str = user.created_at.strftime("%d.%m.%Y %H:%M") if user.created_at else "Неизвестно"
            
            text = (
                f"👤 <b>Информация о тебе:</b>\n\n"
                f"🆔 ID: {user.id}\n"
                f"👤 Имя: {user.first_name or 'Не указано'}\n"
                f"⭐ Знак зодиака: {zodiac_name}\n"
                f"📬 Статус: {subscribed_status}\n"
                f"📅 Дата регистрации: {created_at_str}"
            )
            await message.answer(text, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Ошибка при обработке /my_info: {e}")
        await message.answer("Произошла ошибка. Попробуй позже.")

def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором"""
    return ADMIN_IDS is not None and user_id in ADMIN_IDS

def admin_keyboard():
    """Клавиатура админ-панели"""
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📤 Отправить рассылку сейчас", callback_data="admin_send_now")],
        [types.InlineKeyboardButton(text="📢 Массовая рассылка", callback_data="admin_broadcast")],
        [types.InlineKeyboardButton(text="📝 Редактировать предсказания", callback_data="admin_edit_predictions")],
        [types.InlineKeyboardButton(text="🎁 Розыгрыш", callback_data="admin_raffle")],
        [types.InlineKeyboardButton(text="🎯 Квиз", callback_data="admin_quiz")],
        [types.InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin_users_list")],
        [types.InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [types.InlineKeyboardButton(text="📤 Тестовая отправка", callback_data="admin_test_send")]
    ])

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    """Главное меню админ-панели"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен. Эта команда только для администратора.")
        return
    
    text = (
        "🔐 <b>Админ-панель</b>\n\n"
        "Выбери действие:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=admin_keyboard())

@dp.callback_query(F.data == "admin_send_now")
async def admin_send_now(cb: types.CallbackQuery):
    """Ручная отправка рассылки"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    await cb.answer("Начинаю рассылку...")
    await cb.message.edit_text("⏳ Отправляю рассылку всем подписанным пользователям...")
    
    try:
        from scheduler import send_daily
        await send_daily()
        await cb.message.edit_text("✅ Рассылка успешно отправлена!")
    except Exception as e:
        logger.error(f"Ошибка при ручной рассылке: {e}")
        await cb.message.edit_text(f"❌ Ошибка при рассылке: {e}")

@dp.message(Command("raffle_start"))
async def cmd_raffle_start(message: types.Message):
    """Ручной запуск розыгрыша (только для админа) - запускается немедленно"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен.")
        return
    
    try:
        parts = message.text.split()
        raffle_date = parts[1] if len(parts) > 1 else None
        
        # Если дата не указана, используем текущую дату
        if not raffle_date:
            moscow_tz = timezone(timedelta(hours=3))
            current_date_str = datetime.now(moscow_tz).strftime("%Y-%m-%d")
            raffle_date = current_date_str
        
        # Останавливаем активный розыгрыш, если он есть
        active_raffle = await get_last_active_raffle()
        if active_raffle and active_raffle.raffle_date != raffle_date:
            await stop_raffle(active_raffle.raffle_date)
            await message.answer(
                f"⏸️ Остановлен предыдущий активный розыгрыш #{active_raffle.raffle_number} ({active_raffle.raffle_date})"
            )
        
        # Создаем или получаем розыгрыш (force_activate=True активирует остановленный розыгрыш)
        raffle = await create_or_get_raffle(raffle_date, force_activate=True)
        if raffle:
            raffle_number = raffle.raffle_number
            status = "активирую" if not raffle.is_active else "запускаю"
            await message.answer(f"⏳ {status.capitalize()} розыгрыш #{raffle_number} на {raffle_date} прямо сейчас...")
        else:
            await message.answer(f"⏳ Запускаю розыгрыш на {raffle_date} прямо сейчас...")
        
        # Получаем всех подписанных пользователей
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.subscribed == True)
            )
            users = result.scalars().all()
        
        if not users:
            await message.answer("❌ Нет подписанных пользователей для розыгрыша")
            return
        
        success_count = 0
        error_count = 0
        
        # Отправляем объявления всем подписанным пользователям
        for user in users:
            message_id = await send_raffle_announcement(bot, user.id, raffle_date)
            if message_id:
                success_count += 1
                await asyncio.sleep(RATE_LIMIT_DELAY)
            else:
                error_count += 1
        
        await message.answer(
            f"✅ Розыгрыш на {raffle_date} запущен!\n\n"
            f"✅ Успешно отправлено: {success_count}\n"
            f"❌ Ошибок: {error_count}"
        )
        
        logger.info(f"Админ {message.from_user.id} запустил розыгрыш на {raffle_date}. Успешно: {success_count}, Ошибок: {error_count}")
            
    except Exception as e:
        logger.error(f"Ошибка при ручном запуске розыгрыша: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("raffle_test_status"))
async def cmd_raffle_test_status(message: types.Message):
    """Проверка статуса розыгрыша (только для админа)"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен.")
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer("❌ Использование: /raffle_test_status ДАТА (например: 2025-12-07)")
            return
        
        raffle_date = parts[1]
        
        # Получаем розыгрыш
        raffle = await get_raffle_by_date(raffle_date)
        is_active = await is_raffle_active(raffle_date)
        
        # Вычисляем время закрытия
        from datetime import time as dt_time
        from raffle import MOSCOW_TZ
        raffle_date_obj = datetime.strptime(raffle_date, "%Y-%m-%d").date()
        close_time = datetime.combine(raffle_date_obj, dt_time(hour=23, minute=59))
        close_time = close_time.replace(tzinfo=MOSCOW_TZ)
        moscow_now = datetime.now(MOSCOW_TZ)
        
        status_text = "🟢 Активен" if is_active else "🔴 Закрыт"
        
        text = (
            f"📊 <b>Статус розыгрыша {raffle_date}</b>\n\n"
            f"Статус: {status_text}\n"
        )
        
        if raffle:
            text += f"Номер: #{raffle.raffle_number}\n"
            text += f"Создан: {raffle.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            if raffle.stopped_at:
                text += f"Остановлен: {raffle.stopped_at.strftime('%d.%m.%Y %H:%M')}\n"
        
        text += f"\nВремя закрытия: {close_time.strftime('%d.%m.%Y %H:%M')} МСК\n"
        text += f"Текущее время: {moscow_now.strftime('%d.%m.%Y %H:%M')} МСК\n"
        
        if moscow_now > close_time:
            text += "\n⏰ Время закрытия прошло"
        else:
            time_left = close_time - moscow_now
            hours = int(time_left.total_seconds() // 3600)
            minutes = int((time_left.total_seconds() % 3600) // 60)
            text += f"\n⏳ До закрытия: {hours}ч {minutes}м"
        
        await message.answer(text, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка при проверке статуса розыгрыша: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("raffle_test_list"))
async def cmd_raffle_test_list(message: types.Message):
    """Список всех розыгрышей с их статусами (только для админа)"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен.")
        return
    
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Raffle).order_by(Raffle.raffle_number.asc())
            )
            raffles = result.scalars().all()
        
        if not raffles:
            await message.answer("📋 Розыгрышей пока нет.")
            return
        
        text = "📋 <b>Список всех розыгрышей:</b>\n\n"
        
        from datetime import time as dt_time
        from raffle import MOSCOW_TZ
        moscow_now = datetime.now(MOSCOW_TZ)
        
        for raffle in raffles:
            try:
                date_obj = datetime.strptime(raffle.raffle_date, "%Y-%m-%d")
                date_display = date_obj.strftime("%d.%m.%Y")
            except:
                date_display = raffle.raffle_date
            
            is_active = await is_raffle_active(raffle.raffle_date)
            status_icon = "🟢" if is_active else "🔴"
            
            # Вычисляем время закрытия
            close_time = datetime.combine(date_obj.date(), dt_time(hour=23, minute=59))
            close_time = close_time.replace(tzinfo=MOSCOW_TZ)
            
            text += f"{status_icon} <b>Розыгрыш №{raffle.raffle_number}</b> от {date_display}\n"
            if moscow_now > close_time:
                text += f"   ⏰ Закрыт в 23:59\n"
            else:
                time_left = close_time - moscow_now
                hours = int(time_left.total_seconds() // 3600)
                minutes = int((time_left.total_seconds() % 3600) // 60)
                text += f"   ⏳ Закроется через: {hours}ч {minutes}м\n"
            text += "\n"
        
        await message.answer(text, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка при получении списка розыгрышей: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("raffle_create_retroactive"))
async def cmd_raffle_create_retroactive(message: types.Message):
    """Создание розыгрыша задним числом (только для админа)
    
    Используется для создания розыгрыша, если он не был создан автоматически.
    Все данные участников сохраняются.
    """
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен.")
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer(
                "❌ Использование: /raffle_create_retroactive ДАТА\n\n"
                "Пример: /raffle_create_retroactive 2025-12-08\n\n"
                "⚠️ Внимание: Эта команда создает розыгрыш в БД, если он не был создан.\n"
                "Все данные участников сохраняются."
            )
            return
        
        raffle_date = parts[1]
        
        # Проверяем, существует ли уже розыгрыш
        existing_raffle = await get_raffle_by_date(raffle_date)
        if existing_raffle:
            try:
                date_obj = datetime.strptime(raffle_date, "%Y-%m-%d")
                date_display = date_obj.strftime("%d.%m.%Y")
            except:
                date_display = raffle_date
            
            await message.answer(
                f"✅ Розыгрыш для {date_display} уже существует!\n\n"
                f"Номер: #{existing_raffle.raffle_number}\n"
                f"Статус: {'🟢 Активен' if existing_raffle.is_active else '🔴 Остановлен'}"
            )
            return
        
        # Создаем розыгрыш
        raffle = await create_or_get_raffle(raffle_date, force_activate=False)
        
        if raffle:
            try:
                date_obj = datetime.strptime(raffle_date, "%Y-%m-%d")
                date_display = date_obj.strftime("%d.%m.%Y")
            except:
                date_display = raffle_date
            
            # Проверяем, сколько участников уже есть
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(RaffleParticipant).where(
                        RaffleParticipant.raffle_date == raffle_date
                    )
                )
                participants = result.scalars().all()
                participants_count = len([p for p in participants if p.question_id != 0])
                answered_count = len([p for p in participants if p.answer is not None])
            
            await message.answer(
                f"✅ Розыгрыш #{raffle.raffle_number} для {date_display} успешно создан!\n\n"
                f"📊 Статистика:\n"
                f"   Участников: {participants_count}\n"
                f"   Ответило: {answered_count}\n\n"
                f"Все данные участников сохранены."
            )
            logger.info(f"Админ {message.from_user.id} создал розыгрыш #{raffle.raffle_number} для {raffle_date} задним числом")
        else:
            await message.answer(f"❌ Ошибка при создании розыгрыша для {raffle_date}")
            
    except Exception as e:
        logger.error(f"Ошибка при создании розыгрыша задним числом: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("raffle_reload_scheduler"))
async def cmd_raffle_reload_scheduler(message: types.Message):
    """Перезагрузка планировщика розыгрышей (только для админа)"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен.")
        return
    
    try:
        from scheduler import stop_scheduler, start_scheduler
        
        await message.answer("⏳ Перезагружаю планировщик розыгрышей...")
        
        # Останавливаем планировщик
        stop_scheduler()
        
        # Запускаем заново (задачи пересоздадутся)
        start_scheduler()
        
        await message.answer("✅ Планировщик розыгрышей перезагружен. Задачи обновлены.")
        logger.info(f"Админ {message.from_user.id} перезагрузил планировщик розыгрышей")
        
    except Exception as e:
        logger.error(f"Ошибка при перезагрузке планировщика: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("raffle_stop"))
async def cmd_raffle_stop(message: types.Message):
    """Остановка последнего активного розыгрыша (только для админа)"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен.")
        return
    
    try:
        # Получаем последний активный розыгрыш
        active_raffle = await get_last_active_raffle()
        
        if not active_raffle:
            await message.answer("❌ Нет активных розыгрышей для остановки")
            return
        
        # Останавливаем розыгрыш
        success = await stop_raffle(active_raffle.raffle_date)
        
        if success:
            await message.answer(
                f"✅ Розыгрыш #{active_raffle.raffle_number} ({active_raffle.raffle_date}) остановлен"
            )
            logger.info(f"Админ {message.from_user.id} остановил розыгрыш #{active_raffle.raffle_number} ({active_raffle.raffle_date})")
        else:
            await message.answer("❌ Ошибка при остановке розыгрыша")
            
    except Exception as e:
        logger.error(f"Ошибка при остановке розыгрыша: {e}")
        await message.answer(f"❌ Ошибка при остановке розыгрыша: {e}")

@dp.callback_query(F.data == "admin_edit_predictions")
async def admin_edit_predictions(cb: types.CallbackQuery):
    """Меню редактирования предсказаний"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    start_date, days_data = load_predictions()
    if not start_date or not days_data:
        await cb.answer("Ошибка загрузки данных", show_alert=True)
        return
    
    # Вычисляем даты для каждого дня
    try:
        from datetime import timedelta
        start_datetime = datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError:
        await cb.answer("Ошибка парсинга даты", show_alert=True)
        return
    
    # Создаем клавиатуру с датами (1.12, 2.12 и т.д.)
    buttons = []
    for day in range(1, 32):  # От 1 до 31 включительно (31 день)
        if day % 5 == 1:
            buttons.append([])
        
        # Вычисляем дату для этого дня
        day_date = start_datetime + timedelta(days=day - 1)
        date_str = day_date.strftime("%d.%m")
        
        buttons[-1].append(types.InlineKeyboardButton(
            text=date_str,
            callback_data=f"admin_edit_day_{day}"
        ))
    
    buttons.append([types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")])
    
    start_date_formatted = start_datetime.strftime("%d.%m.%Y")
    text = f"📝 <b>Редактирование предсказаний</b>\n\nВыбери дату (начиная с {start_date_formatted}):"
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
    await cb.answer()

@dp.callback_query(F.data.startswith("admin_edit_day_"))
async def admin_edit_day(cb: types.CallbackQuery):
    """Выбор дня для редактирования"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    day_num = int(cb.data.split("_")[-1])
    start_date, days_data = load_predictions()
    day_predictions = days_data.get(str(day_num), {})
    
    # Вычисляем дату для этого дня
    try:
        from datetime import timedelta
        start_datetime = datetime.strptime(start_date, "%Y-%m-%d")
        day_date = start_datetime + timedelta(days=day_num - 1)
        date_str = day_date.strftime("%d.%m.%Y")
    except ValueError:
        date_str = f"День {day_num}"
    
    # Создаем клавиатуру со знаками зодиака
    buttons = []
    row = []
    for zid in range(1, 13):
        zodiac_name = ZODIAC_NAMES[zid]
        row.append(types.InlineKeyboardButton(
            text=zodiac_name.split()[1] if " " in zodiac_name else zodiac_name,
            callback_data=f"admin_edit_z_{day_num}_{zid}"
        ))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin_edit_predictions")])
    
    text = f"📅 <b>{date_str}</b>\n\nВыбери знак зодиака для редактирования:"
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
    await cb.answer()

@dp.callback_query(F.data.startswith("admin_edit_z_"))
async def admin_edit_zodiac(cb: types.CallbackQuery):
    """Показ текущего предсказания и предложение редактирования"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    parts = cb.data.split("_")
    day_num = int(parts[3])
    zid = int(parts[4])
    
    start_date, days_data = load_predictions()
    day_predictions = days_data.get(str(day_num), {})
    prediction_data = day_predictions.get(str(zid), {})
    
    # Вычисляем дату для этого дня
    try:
        from datetime import timedelta
        start_datetime = datetime.strptime(start_date, "%Y-%m-%d")
        day_date = start_datetime + timedelta(days=day_num - 1)
        date_str = day_date.strftime("%d.%m.%Y")
    except ValueError:
        date_str = f"День {day_num}"
    
    zodiac_name = ZODIAC_NAMES[zid]
    prediction = prediction_data.get("prediction", "Не задано")
    task = prediction_data.get("task", "Не задано")
    
    text = (
        f"📝 <b>Редактирование</b>\n\n"
        f"📅 Дата: {date_str}\n"
        f"⭐ Знак: {zodiac_name}\n\n"
        f"<b>Предсказание:</b>\n{prediction}\n\n"
        f"<b>Задание:</b>\n{task}\n\n"
        f"Для редактирования отправь сообщение в формате:\n"
        f"<code>prediction: новое предсказание\ntask: новое задание</code>\n\n"
        f"Или используй команду:\n"
        f"<code>/set_prediction {day_num} {zid} предсказание | задание</code>"
    )
    
    buttons = [[types.InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_edit_day_{day_num}")]]
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
    await cb.answer()

@dp.message(Command("set_prediction"))
async def cmd_set_prediction(message: types.Message):
    """Установка предсказания через команду"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен.")
        return
    
    try:
        parts = message.text.split(maxsplit=3)
        if len(parts) < 4:
            await message.answer(
                "❌ Неверный формат. Используй:\n"
                "<code>/set_prediction день знак предсказание | задание</code>\n\n"
                "Пример:\n"
                "<code>/set_prediction 1 1 Сегодня отличный день | Сделай что-то хорошее</code>",
                parse_mode="HTML"
            )
            return
        
        day_num = int(parts[1])
        zid = int(parts[2])
        content = parts[3]
        
        if "|" in content:
            prediction, task = content.split("|", 1)
            prediction = prediction.strip()
            task = task.strip()
        else:
            await message.answer("❌ Используй разделитель | между предсказанием и заданием")
            return
        
        # Загружаем и обновляем данные
        start_date, days_data = load_predictions()
        if str(day_num) not in days_data:
            days_data[str(day_num)] = {}
        
        days_data[str(day_num)][str(zid)] = {
            "prediction": prediction,
            "task": task
        }
        
        # Сохраняем в файл
        import json
        from pathlib import Path
        predictions_path = Path("data/predictions.json")
        with open(predictions_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["days"][str(day_num)][str(zid)] = {"prediction": prediction, "task": task}
        with open(predictions_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        
        # Вычисляем дату для отображения
        try:
            from datetime import timedelta
            start_datetime = datetime.strptime(start_date, "%Y-%m-%d")
            day_date = start_datetime + timedelta(days=day_num - 1)
            date_str = day_date.strftime("%d.%m.%Y")
        except ValueError:
            date_str = f"День {day_num}"
        
        zodiac_name = ZODIAC_NAMES[zid]
        await message.answer(
            f"✅ Предсказание обновлено!\n\n"
            f"📅 Дата: {date_str}\n"
            f"⭐ Знак: {zodiac_name}\n"
            f"📝 Предсказание: {prediction}\n"
            f"📋 Задание: {task}"
        )
        logger.info(f"Админ {message.from_user.id} обновил предсказание: день {day_num} ({date_str}), знак {zid}")
        
    except (ValueError, IndexError) as e:
        await message.answer(f"❌ Ошибка в формате команды: {e}")
    except Exception as e:
        logger.error(f"Ошибка при установке предсказания: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.callback_query(F.data == "admin_users_list")
async def admin_users_list(cb: types.CallbackQuery):
    """Список пользователей"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).order_by(User.created_at.desc()).limit(50)
            )
            users = result.scalars().all()
            
            if not users:
                await cb.message.edit_text("👥 Пользователей пока нет.")
                await cb.answer()
                return
            
            text = f"👥 <b>Последние {len(users)} пользователей:</b>\n\n"
            for user in users:
                zodiac_name = user.zodiac_name or (ZODIAC_NAMES.get(user.zodiac) if user.zodiac else "Не выбран")
                status = "✅" if user.subscribed else "❌"
                text += f"{status} {user.first_name or 'Без имени'} (@{user.username or 'нет'})\n"
                text += f"   ID: {user.id} | {zodiac_name}\n\n"
            
            buttons = [[types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]]
            await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
            await cb.answer()
    except Exception as e:
        logger.error(f"Ошибка при получении списка пользователей: {e}")
        await cb.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data == "admin_stats")
async def admin_stats_callback(cb: types.CallbackQuery):
    """Статистика через callback"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        async with AsyncSessionLocal() as session:
            # Подсчет статистики
            from sqlalchemy import func
            
            total_users = await session.scalar(select(func.count(User.id)))
            subscribed_users = await session.scalar(
                select(func.count(User.id)).where(User.subscribed == True)
            )
            
            # Статистика по знакам зодиака
            zodiac_stats = {}
            result = await session.execute(
                select(User.zodiac, func.count(User.id))
                .where(User.zodiac.isnot(None))
                .group_by(User.zodiac)
            )
            for zodiac_id, count in result:
                zodiac_name = ZODIAC_NAMES.get(zodiac_id, f"Знак #{zodiac_id}")
                zodiac_stats[zodiac_name] = count
            
            stats_text = (
                f"📊 <b>Статистика бота:</b>\n\n"
                f"👥 Всего пользователей: {total_users}\n"
                f"📬 Подписанных: {subscribed_users}\n"
                f"❌ Не подписанных: {total_users - subscribed_users}\n\n"
                f"⭐ <b>По знакам зодиака:</b>\n"
            )
            
            for zodiac_name, count in sorted(zodiac_stats.items(), key=lambda x: x[1], reverse=True):
                stats_text += f"{zodiac_name}: {count}\n"
            
            buttons = [[types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]]
            await cb.message.edit_text(stats_text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
            await cb.answer()
            
    except Exception as e:
        logger.error(f"Ошибка при обработке статистики: {e}")
        await cb.message.edit_text("Произошла ошибка при получении статистики.")
        await cb.answer()

@dp.callback_query(F.data == "admin_test_send")
async def admin_test_send(cb: types.CallbackQuery):
    """Тестовая отправка"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    # Формируем подсказку по знакам зодиака
    zodiac_hint = "Знаки зодиака:\n"
    for zid, name in sorted(ZODIAC_NAMES.items()):
        zodiac_hint += f"{zid} - {name}\n"
    
    text = (
        "📤 <b>Тестовая отправка</b>\n\n"
        "Отправь команду в формате:\n"
        "<code>/test_send ID_пользователя знак_зодиака [день]</code>\n\n"
        "Примеры:\n"
        "<code>/test_send 123456789 1</code> - день 1 (для тестирования)\n"
        "<code>/test_send 123456789 1 5</code> - день 5\n\n"
        "Если день не указан, используется день 1.\n\n"
        f"<b>{zodiac_hint}</b>"
    )
    buttons = [[types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]]
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
    await cb.answer()

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(cb: types.CallbackQuery):
    """Массовая рассылка"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    text = (
        "📢 <b>Массовая рассылка</b>\n\n"
        "Отправь сообщение (текст, фото или фото с текстом), которое получит каждый пользователь бота.\n\n"
        "Варианты использования:\n"
        "1️⃣ Текст: <code>/broadcast текст сообщения</code>\n"
        "2️⃣ Фото с текстом: Ответь (reply) на фото и отправь <code>/broadcast текст</code>\n"
        "3️⃣ Только фото: Отправь фото и используй <code>/broadcast_photo</code>\n\n"
        "⚠️ <b>Внимание:</b> Рассылка идет всем пользователям, которые запускали бота!"
    )
    buttons = [[types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]]
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
    await cb.answer()

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    """Массовая рассылка текста или фото с текстом всем пользователям"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен.")
        return
    
    try:
        # Проверяем, есть ли reply на фото
        if message.reply_to_message and message.reply_to_message.photo:
            # Если reply на фото, отправляем фото с подписью
            photo_file_id = message.reply_to_message.photo[-1].file_id
            caption = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else (message.reply_to_message.caption or "")
            
            await message.answer("⏳ Начинаю массовую рассылку фото...")
            
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(User))
                users = result.scalars().all()
            
            if not users:
                await message.answer("❌ Нет пользователей для рассылки")
                return
            
            success_count = 0
            error_count = 0
            
            for user in users:
                success = await safe_send_photo(bot, user.id, photo_file_id, caption=caption if caption else None)
                if success:
                    success_count += 1
                    await asyncio.sleep(RATE_LIMIT_DELAY)  # Throttling
                else:
                    error_count += 1
            
            await message.answer(
                f"✅ Рассылка фото завершена!\n\n"
                f"✅ Успешно: {success_count}\n"
                f"❌ Ошибок: {error_count}"
            )
            logger.info(f"Админ {message.from_user.id} выполнил массовую рассылку фото: {success_count} успешно, {error_count} ошибок")
            return
        
        # Обычная текстовая рассылка
        text = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else None
        if not text:
            await message.answer("❌ Укажи текст для рассылки или ответь (reply) на фото")
            return
        
        await message.answer("⏳ Начинаю массовую рассылку...")
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User))
            users = result.scalars().all()
        
        if not users:
            await message.answer("❌ Нет пользователей для рассылки")
            return
        
        success_count = 0
        error_count = 0
        
        for user in users:
            success = await safe_send_message(bot, user.id, text)
            if success:
                success_count += 1
                await asyncio.sleep(RATE_LIMIT_DELAY)  # Throttling
            else:
                error_count += 1
        
        await message.answer(
            f"✅ Рассылка завершена!\n\n"
            f"✅ Успешно: {success_count}\n"
            f"❌ Ошибок: {error_count}"
        )
        logger.info(f"Админ {message.from_user.id} выполнил массовую рассылку: {success_count} успешно, {error_count} ошибок")
        
    except Exception as e:
        logger.error(f"Ошибка при массовой рассылке: {e}")
        await message.answer(f"❌ Ошибка: {e}")


async def admin_send_photo_broadcast(message: types.Message, photo_file_id: str, caption: str = ""):
    """Вспомогательная функция для рассылки фото"""
    await message.answer("⏳ Начинаю массовую рассылку фото...")
    
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User))
            users = result.scalars().all()
        
        if not users:
            await message.answer("❌ Нет пользователей для рассылки")
            return
        
        success_count = 0
        error_count = 0
        
        for user in users:
            success = await safe_send_photo(bot, user.id, photo_file_id, caption=caption if caption else None)
            if success:
                success_count += 1
                await asyncio.sleep(RATE_LIMIT_DELAY)  # Throttling
            else:
                error_count += 1
        
        await message.answer(
            f"✅ Рассылка фото завершена!\n\n"
            f"✅ Успешно: {success_count}\n"
            f"❌ Ошибок: {error_count}"
        )
        logger.info(f"Админ {message.from_user.id} выполнил массовую рассылку фото: {success_count} успешно, {error_count} ошибок")
        
    except Exception as e:
        logger.error(f"Ошибка при массовой рассылке фото: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("broadcast_photo"))
async def cmd_broadcast_photo(message: types.Message):
    """Массовая рассылка последнего отправленного фото"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен.")
        return
    
    try:
        # Получаем сохраненное фото или из reply
        photo_file_id = None
        caption = ""
        
        if message.reply_to_message and message.reply_to_message.photo:
            # Если reply на фото
            photo_file_id = message.reply_to_message.photo[-1].file_id
            caption = message.reply_to_message.caption or ""
            # Если указан новый текст в команде, используем его
            if len(message.text.split()) > 1:
                caption = message.text.split(maxsplit=1)[1]
        elif message.from_user.id in admin_photo_storage:
            # Используем сохраненное фото
            stored = admin_photo_storage[message.from_user.id]
            photo_file_id = stored["file_id"]
            caption = stored["caption"]
            # Если указан новый текст в команде, используем его
            if len(message.text.split()) > 1:
                caption = message.text.split(maxsplit=1)[1]
        
        if not photo_file_id:
            await message.answer(
                "❌ Сначала отправь фото, затем используй команду:\n"
                "<code>/broadcast_photo</code> - разослать фото\n"
                "<code>/broadcast_photo текст</code> - разослать фото с текстом",
                parse_mode="HTML"
            )
            return
        
        await admin_send_photo_broadcast(message, photo_file_id, caption)
        
    except Exception as e:
        logger.error(f"Ошибка при рассылке фото: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("test_send"))
async def cmd_test_send(message: types.Message):
    """Тестовая отправка сообщения конкретному пользователю
    
    Формат: /test_send ID_пользователя знак_зодиака [день]
    Если день не указан, используется день 1 (для тестирования до начала рассылки)
    """
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен.")
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 3:
            # Формируем подсказку по знакам зодиака
            zodiac_hint = "Знаки зодиака:\n"
            for zid, name in sorted(ZODIAC_NAMES.items()):
                zodiac_hint += f"{zid} - {name}\n"
            
            await message.answer(
                "❌ Формат: /test_send ID_пользователя знак_зодиака [день]\n\n"
                "Примеры:\n"
                "<code>/test_send 123456789 1</code> - отправит день 1\n"
                "<code>/test_send 123456789 1 5</code> - отправит день 5\n\n"
                f"<b>{zodiac_hint}</b>",
                parse_mode="HTML"
            )
            return
        
        user_id = int(parts[1])
        zodiac_id = int(parts[2])
        force_day = int(parts[3]) if len(parts) > 3 else 1  # По умолчанию день 1 для тестирования
        
        if force_day < 1 or force_day > 31:
            await message.answer("❌ День должен быть от 1 до 31")
            return
        
        prediction_data, day_num = get_today_prediction(zodiac_id, force_day=force_day)
        if not prediction_data:
            await message.answer(f"❌ Прогноз не найден для дня {force_day}, знака {zodiac_id}")
            return
        
        zodiac_name = ZODIAC_NAMES.get(zodiac_id, f"Знак #{zodiac_id}")
        text = (
            f"🌟 Гороскоп на сегодня - {zodiac_name}\n"
            f"📅 День {day_num} из 31\n\n"
            f"🥠 Предсказание: {prediction_data.get('prediction', '')}\n\n"
            f"📝 {prediction_data.get('task', '')}"
        )
        
        success = await safe_send_message(bot, user_id, text)
        if success:
            await message.answer(f"✅ Тестовое сообщение отправлено пользователю {user_id} (день {day_num})")
            logger.info(f"Админ {message.from_user.id} отправил тестовое сообщение пользователю {user_id}, день {day_num}")
        else:
            await message.answer(f"❌ Не удалось отправить тестовое сообщение пользователю {user_id}")
        
    except Exception as e:
        logger.error(f"Ошибка при тестовой отправке: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.callback_query(F.data.startswith("quick_reply_"))
async def quick_reply_callback(cb: types.CallbackQuery):
    """Обработчик кнопки 'Быстро ответить' - активирует режим ответа"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        # Извлекаем ID пользователя из callback_data
        user_id = int(cb.data.split("_")[-1])
        
        # Активируем режим ответа
        admin_reply_mode[cb.from_user.id] = user_id
        
        await cb.answer("✅ Режим ответа активирован", show_alert=False)
        await cb.message.answer(
            f"💬 Режим ответа активирован для пользователя {user_id}.\n\n"
            "Теперь можешь отправить:\n"
            "• Текст - будет отправлен как ответ\n"
            "• Фото + текст - будет отправлено фото с текстом\n"
            "• Только фото - будет отправлено фото\n\n"
            "Для отмены используй: /reply cancel"
        )
        logger.info(f"Админ {cb.from_user.id} активировал режим ответа для пользователя {user_id} через кнопку")
    except (ValueError, IndexError) as e:
        logger.error(f"Ошибка при обработке quick_reply: {e}")
        await cb.answer("❌ Ошибка при активации режима ответа", show_alert=True)

@dp.message(Command("reply"))
async def cmd_reply(message: types.Message):
    """Ответ администратора пользователю на его вопрос
    
    Формат: /reply USER_ID [текст]
    Если текст указан - отправляется сразу
    Если текст не указан - активируется режим ответа, можно отправить фото+текст
    """
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен.")
        return
    
    try:
        parts = message.text.split(maxsplit=2)
        
        if len(parts) < 2:
            await message.answer(
                "❌ Формат: /reply USER_ID [текст]\n\n"
                "Примеры:\n"
                "/reply 123456789 Привет! - отправит ответ сразу\n"
                "/reply 123456789 - активирует режим ответа, можно отправить фото+текст\n\n"
                "Для отмены режима ответа используй: /reply cancel"
            )
            return
        
        # Отмена режима ответа
        if parts[1].lower() == "cancel":
            admin_reply_mode.pop(message.from_user.id, None)
            await message.answer("✅ Режим ответа отменен")
            return
        
        user_id = int(parts[1])
        
        # Если текст указан - отправляем сразу
        if len(parts) > 2:
            reply_text = parts[2]
            success = await safe_send_message(bot, user_id, reply_text)
            if success:
                await message.answer(f"✅ Ответ отправлен пользователю {user_id}")
                logger.info(f"Админ {message.from_user.id} отправил ответ пользователю {user_id}")
            else:
                await message.answer(f"❌ Не удалось отправить ответ пользователю {user_id}")
        else:
            # Активируем режим ответа
            admin_reply_mode[message.from_user.id] = user_id
            await message.answer(
                f"💬 Режим ответа активирован для пользователя {user_id}.\n\n"
                "Теперь можешь отправить:\n"
                "• Текст - будет отправлен как ответ\n"
                "• Фото + текст - будет отправлено фото с текстом\n"
                "• Только фото - будет отправлено фото\n\n"
                "Для отмены используй: /reply cancel"
            )
        
    except ValueError:
        await message.answer("❌ Неверный формат USER_ID. Должно быть число.")
    except Exception as e:
        logger.error(f"Ошибка при ответе пользователю: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.callback_query(F.data == "admin_back")
async def admin_back(cb: types.CallbackQuery):
    """Возврат в главное меню админа"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    text = (
        "🔐 <b>Админ-панель</b>\n\n"
        "Выбери действие:"
    )
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=admin_keyboard())
    await cb.answer()

@dp.callback_query(F.data == "admin_edit_questions")
async def admin_edit_questions_menu(cb: types.CallbackQuery):
    """Меню редактирования вопросов - выбор даты"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        raffle_dates = get_all_raffle_dates()
        
        if not raffle_dates:
            text = "❌ Даты розыгрышей не найдены."
            buttons = [[types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin_raffle")]]
            await cb.message.edit_text(text, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
            await cb.answer()
            return
        
        text = "❓ <b>Редактирование вопросов</b>\n\nВыбери дату розыгрыша:\n\n"
        
        buttons = []
        for raffle_date in sorted(raffle_dates):
            try:
                date_obj = datetime.strptime(raffle_date, "%Y-%m-%d")
                date_display = date_obj.strftime("%d.%m.%Y")
            except:
                date_display = raffle_date
            
            # Проверяем, начался ли розыгрыш (асинхронно)
            raffle_started = await has_raffle_started(raffle_date)
            status_icon = "⛔" if raffle_started else "📅"
            
            buttons.append([
                types.InlineKeyboardButton(
                    text=f"{status_icon} {date_display}" + (" (начат)" if raffle_started else ""),
                    callback_data=f"admin_questions_date_{raffle_date}"
                )
            ])
        
        buttons.append([types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin_raffle")])
        
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
        await cb.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при открытии меню редактирования вопросов: {e}", exc_info=True)
        await cb.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data.startswith("admin_questions_date_"))
async def admin_questions_date_menu(cb: types.CallbackQuery):
    """Меню вопросов для конкретной даты"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        raffle_date = cb.data.split("_")[-1]
        questions = get_all_questions(raffle_date)
        
        if not questions:
            try:
                date_obj = datetime.strptime(raffle_date, "%Y-%m-%d")
                date_display = date_obj.strftime("%d.%m.%Y")
            except:
                date_display = raffle_date
            
            text = f"❓ <b>Вопросы для {date_display}</b>\n\nВопросы не найдены."
            buttons = [[types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin_edit_questions")]]
            await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
            await cb.answer()
            return
        
        try:
            date_obj = datetime.strptime(raffle_date, "%Y-%m-%d")
            date_display = date_obj.strftime("%d.%m.%Y")
        except:
            date_display = raffle_date
        
        # Проверяем, начался ли розыгрыш
        raffle_started = await has_raffle_started(raffle_date)
        
        text = f"❓ <b>Вопросы для {date_display}</b>\n\n"
        
        if raffle_started:
            text += "⛔ <b>Розыгрыш уже начался!</b> Редактирование недоступно.\n\n"
        
        text += "Выбери вопрос для просмотра:\n\n"
        
        buttons = []
        for question in questions:
            question_id = question.get('id')
            question_title = question.get('title', f'Вопрос #{question_id}')
            icon = "🔒" if raffle_started else "❓"
            buttons.append([
                types.InlineKeyboardButton(
                    text=f"{icon} {question_title}",
                    callback_data=f"admin_question_edit_{raffle_date}_{question_id}"
                )
            ])
        
        buttons.append([types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin_edit_questions")])
        
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
        await cb.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при открытии меню вопросов для даты: {e}", exc_info=True)
        await cb.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data.startswith("admin_question_edit_"))
async def admin_question_edit(cb: types.CallbackQuery):
    """Просмотр и редактирование вопроса"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        parts = cb.data.split("_")
        if len(parts) == 4:
            # Старый формат без даты (для обратной совместимости)
            question_id = int(parts[-1])
            raffle_date = None
        else:
            # Новый формат с датой
            raffle_date = parts[3]
            question_id = int(parts[4])
        
        if not raffle_date:
            await cb.answer("Необходимо указать дату розыгрыша", show_alert=True)
            return
        
        question = get_question_by_id(question_id, raffle_date)
        
        if not question:
            await cb.answer("Вопрос не найден", show_alert=True)
            return
        
        try:
            date_obj = datetime.strptime(raffle_date, "%Y-%m-%d")
            date_display = date_obj.strftime("%d.%m.%Y")
        except:
            date_display = raffle_date
        
        # Проверяем, начался ли розыгрыш
        raffle_started = await has_raffle_started(raffle_date)
        
        text = (
            f"❓ <b>Вопрос #{question_id}</b>\n"
            f"📅 Дата: {date_display}\n\n"
        )
        
        if raffle_started:
            text += "⛔ <b>Розыгрыш уже начался!</b> Редактирование недоступно.\n\n"
        
        text += (
            f"<b>Название:</b> {question.get('title', '')}\n"
            f"<b>Текст:</b> {question.get('text', '')}\n\n"
        )
        
        if not raffle_started:
            text += (
                f"Для редактирования отправь команду:\n"
                f"<code>/edit_question {raffle_date} {question_id} Название | Текст вопроса</code>\n\n"
                f"Пример:\n"
                f"<code>/edit_question {raffle_date} {question_id} Забота о гостях | Назови ключевые слова, описывающие ценность 'забота о гостях'</code>"
            )
        else:
            text += "⚠️ Вопросы можно редактировать только до начала розыгрыша."
        
        buttons = [
            [types.InlineKeyboardButton(text="◀️ Назад к списку", callback_data=f"admin_questions_date_{raffle_date}")]
        ]
        
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
        await cb.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при просмотре вопроса: {e}", exc_info=True)
        await cb.answer("Ошибка", show_alert=True)

@dp.message(Command("edit_question"))
async def cmd_edit_question(message: types.Message):
    """Редактирование вопроса через команду"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен.")
        return
    
    try:
        parts = message.text.split(maxsplit=3)
        if len(parts) < 4:
            await message.answer(
                "❌ Неверный формат. Используй:\n"
                "<code>/edit_question ДАТА ID Название | Текст</code>\n\n"
                "Пример:\n"
                "<code>/edit_question 2025-12-07 1 Забота о гостях | Назови ключевые слова, описывающие ценность 'забота о гостях'</code>",
                parse_mode="HTML"
            )
            return
        
        raffle_date = parts[1]
        question_id = int(parts[2])
        content = parts[3]
        
        if "|" not in content:
            await message.answer("❌ Используй разделитель | между названием и текстом вопроса")
            return
        
        title, text = content.split("|", 1)
        title = title.strip()
        text = text.strip()
        
        if not title or not text:
            await message.answer("❌ Название и текст вопроса не могут быть пустыми")
            return
        
        # Проверяем, начался ли розыгрыш
        raffle_started = await has_raffle_started(raffle_date)
        if raffle_started:
            try:
                date_obj = datetime.strptime(raffle_date, "%Y-%m-%d")
                date_display = date_obj.strftime("%d.%m.%Y")
            except:
                date_display = raffle_date
            
            await message.answer(
                f"⛔ <b>Невозможно редактировать вопрос!</b>\n\n"
                f"Розыгрыш на {date_display} уже начался (объявления были отправлены пользователям).\n\n"
                f"Вопросы можно редактировать только до начала розыгрыша.",
                parse_mode="HTML"
            )
            return
        
        # Проверяем, существует ли вопрос
        existing_question = get_question_by_id(question_id, raffle_date)
        if not existing_question:
            await message.answer(f"❌ Вопрос с ID {question_id} для даты {raffle_date} не найден")
            return
        
        # Обновляем вопрос
        success = update_question(question_id, raffle_date, title, text)
        
        if success:
            try:
                date_obj = datetime.strptime(raffle_date, "%Y-%m-%d")
                date_display = date_obj.strftime("%d.%m.%Y")
            except:
                date_display = raffle_date
            
            await message.answer(
                f"✅ Вопрос #{question_id} для {date_display} успешно обновлен!\n\n"
                f"<b>Название:</b> {title}\n"
                f"<b>Текст:</b> {text}",
                parse_mode="HTML"
            )
            logger.info(f"Админ {message.from_user.id} обновил вопрос #{question_id} для даты {raffle_date}")
        else:
            await message.answer("❌ Ошибка при сохранении вопроса")
            
    except ValueError:
        await message.answer("❌ ID вопроса должен быть числом")
    except Exception as e:
        logger.error(f"Ошибка при редактировании вопроса: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    """Обработчик команды /stats - статистика (только для админа)"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Эта команда доступна только администратору.")
        return
    
    try:
        async with AsyncSessionLocal() as session:
            # Подсчет статистики
            from sqlalchemy import func
            
            total_users = await session.scalar(select(func.count(User.id)))
            subscribed_users = await session.scalar(
                select(func.count(User.id)).where(User.subscribed == True)
            )
            
            # Статистика по знакам зодиака
            zodiac_stats = {}
            result = await session.execute(
                select(User.zodiac, func.count(User.id))
                .where(User.zodiac.isnot(None))
                .group_by(User.zodiac)
            )
            for zodiac_id, count in result:
                zodiac_name = ZODIAC_NAMES.get(zodiac_id, f"Знак #{zodiac_id}")
                zodiac_stats[zodiac_name] = count
            
            stats_text = (
                f"📊 <b>Статистика бота:</b>\n\n"
                f"👥 Всего пользователей: {total_users}\n"
                f"📬 Подписанных: {subscribed_users}\n"
                f"❌ Не подписанных: {total_users - subscribed_users}\n\n"
                f"⭐ <b>По знакам зодиака:</b>\n"
            )
            
            for zodiac_name, count in sorted(zodiac_stats.items(), key=lambda x: x[1], reverse=True):
                stats_text += f"{zodiac_name}: {count}\n"
            
            await message.answer(stats_text, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Ошибка при обработке /stats: {e}")
        await message.answer("Произошла ошибка при получении статистики.")

@dp.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: types.Message):
    """Обработчик команды /unsubscribe для отписки от рассылки"""
    try:
        async with AsyncSessionLocal() as session:
            try:
                user = await session.get(User, message.from_user.id)
                if user:
                    user.subscribed = False
                    await session.commit()
                    await message.answer("Ты отписался от ежедневных прогнозов. Используй /start для повторной подписки.")
                    logger.info(f"Пользователь {message.from_user.id} отписался")
                else:
                    await message.answer("Ты не подписан на рассылку. Используй /start для подписки.")
            except SQLAlchemyError as e:
                await session.rollback()
                logger.error(f"Ошибка БД при отписке: {e}")
                await message.answer("Произошла ошибка. Попробуй позже.")
    except Exception as e:
        logger.error(f"Ошибка при обработке /unsubscribe: {e}")
        await message.answer("Произошла ошибка. Попробуй позже.")

@dp.callback_query(F.data.startswith("z_"))
async def choose_zodiac(cb: types.CallbackQuery):
    """Обработчик выбора знака зодиака"""
    try:
        zid = int(cb.data.split("_")[1])
        if zid < 1 or zid > 12:
            await cb.answer("Неверный знак зодиака!", show_alert=True)
            return

        async with AsyncSessionLocal() as session:
            try:
                user = await session.get(User, cb.from_user.id)
                zodiac_name = ZODIAC_NAMES.get(zid, f"Знак #{zid}")
                
                if not user:
                    # Создаем нового пользователя с датой регистрации
                    user = User(
                        id=cb.from_user.id,
                        username=cb.from_user.username,
                        first_name=cb.from_user.first_name,
                        zodiac=zid,
                        zodiac_name=zodiac_name,
                        subscribed=True,
                        created_at=datetime.utcnow()
                    )
                    session.add(user)
                    logger.info(f"Создан новый пользователь {cb.from_user.id} со знаком {zodiac_name}")
                else:
                    # Обновляем знак зодиака
                    user.zodiac = zid
                    user.zodiac_name = zodiac_name
                    user.subscribed = True
                    user.username = cb.from_user.username
                    user.first_name = cb.from_user.first_name
                    logger.info(f"Обновлен пользователь {cb.from_user.id}, знак: {zodiac_name}")
                
                await session.commit()
                
                # Проверяем, нужно ли отправить текущий прогноз
                # Если время >= 09:00 и рассылка уже началась, отправляем прогноз сразу
                moscow_tz = timezone(timedelta(hours=3))  # UTC+3 для Москвы
                current_time_moscow = datetime.now(moscow_tz)
                current_hour = current_time_moscow.hour
                current_minute = current_time_moscow.minute
                
                # Проверяем, прошло ли время рассылки сегодня
                should_send_now = False
                if current_hour > DAILY_HOUR or (current_hour == DAILY_HOUR and current_minute >= DAILY_MINUTE):
                    # Проверяем, началась ли рассылка (дата >= 01.12.2025)
                    start_date, _ = load_predictions()
                    if start_date:
                        try:
                            start_datetime = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=moscow_tz)
                            if current_time_moscow.date() >= start_datetime.date():
                                should_send_now = True
                        except ValueError:
                            pass
                
                # Редактируем сообщение, убираем клавиатуру и меняем текст
                # Добавляем кнопку для изменения знака
                change_keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="🔄 Изменить знак", callback_data="change_zodiac")]
                ])
                await cb.message.edit_text(
                    f"Отлично! Твой знак: {zodiac_name}. Буду присылать прогнозы ежедневно в {DAILY_HOUR:02d}:{DAILY_MINUTE:02d} по МСК.",
                    reply_markup=change_keyboard
                )
                await cb.answer()
                
                # Если время после 09:00 и рассылка началась, отправляем текущий прогноз
                if should_send_now:
                    try:
                        prediction_data, day_num = get_today_prediction(zid)
                        if prediction_data:
                            text = (
                                f"🌟 <b>Гороскоп на сегодня - {zodiac_name}</b>\n"
                                f"📅 День {day_num} из 31\n\n"
                                f"🥠 Предсказание: {prediction_data.get('prediction', '')}\n\n"
                                f"📝 {prediction_data.get('task', '')}"
                            )
                            await cb.message.answer(text, parse_mode="HTML")
                            logger.info(f"Отправлен текущий прогноз пользователю {cb.from_user.id} после выбора знака")
                    except Exception as e:
                        logger.error(f"Ошибка при отправке текущего прогноза: {e}")
            except SQLAlchemyError as e:
                await session.rollback()
                logger.error(f"Ошибка БД при выборе знака: {e}")
                await cb.answer("Произошла ошибка. Попробуй позже.", show_alert=True)
    except ValueError:
        await cb.answer("Неверный формат данных!", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка при выборе знака зодиака: {e}")
        await cb.answer("Произошла ошибка. Попробуй позже.", show_alert=True)

@dp.callback_query(F.data == "change_zodiac")
async def callback_change_zodiac(cb: types.CallbackQuery):
    """Обработчик кнопки изменения знака зодиака"""
    await cb.message.edit_text(
        "Выбери новый знак зодиака:",
        reply_markup=zodiac_keyboard()
    )
    await cb.answer()

# Хранилище последних фото от админа для рассылки
admin_photo_storage = {}

@dp.message(F.photo)
async def admin_photo_handler(message: types.Message):
    """Обработка фото от админа для массовой рассылки или ответа пользователю"""
    if not is_admin(message.from_user.id):
        return
    
    # Если админ в режиме ответа пользователю - обрабатываем как ответ
    if message.from_user.id in admin_reply_mode:
        user_id_to_reply = admin_reply_mode[message.from_user.id]
        
        try:
            has_text = bool(message.text or (message.caption and message.caption.strip()))
            has_photo = bool(message.photo)
            
            # Отправляем ответ пользователю
            if has_photo and has_text:
                # Фото с текстом
                text_content = message.text or message.caption
                success = await safe_send_photo(
                    bot,
                    user_id_to_reply,
                    message.photo[-1].file_id,
                    caption=text_content
                )
            elif has_photo:
                # Только фото
                success = await safe_send_photo(
                    bot,
                    user_id_to_reply,
                    message.photo[-1].file_id
                )
            else:
                # Не должно произойти, так как это обработчик фото
                return
            
            if success:
                await message.answer(f"✅ Ответ отправлен пользователю {user_id_to_reply}")
                logger.info(f"Админ {message.from_user.id} отправил ответ пользователю {user_id_to_reply}")
                # Сбрасываем режим ответа после успешной отправки
                admin_reply_mode.pop(message.from_user.id, None)
            else:
                await message.answer(f"❌ Не удалось отправить ответ пользователю {user_id_to_reply}")
        
        except Exception as e:
            logger.error(f"Ошибка при отправке ответа пользователю: {e}")
            await message.answer(f"❌ Ошибка при отправке ответа: {e}")
        
        return  # Важно! Прерываем обработку, чтобы не сохранять фото для рассылки
    
    # Если НЕ в режиме ответа - сохраняем фото для массовой рассылки
    photo_file_id = message.photo[-1].file_id
    caption = message.caption or ""
    admin_photo_storage[message.from_user.id] = {
        "file_id": photo_file_id,
        "caption": caption
    }
    
    if caption:
        # Если есть подпись, спрашиваем подтверждение
        await message.answer(
            f"📸 Фото сохранено для рассылки.\n\n"
            f"Подпись: {caption}\n\n"
            f"Отправь <code>/broadcast_photo</code> для рассылки всем пользователям.",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "📸 Фото получено. Отправь команду для рассылки:\n"
            "<code>/broadcast_photo</code> - разослать это фото всем\n"
            "<code>/broadcast_photo текст</code> - разослать фото с новым текстом",
            parse_mode="HTML"
        )

@dp.callback_query(F.data.startswith("raffle_join_"))
async def raffle_join_callback(cb: types.CallbackQuery):
    """Обработчик нажатия кнопки 'Принять участие' в розыгрыше"""
    try:
        raffle_date = cb.data.split("_")[-1]
        
        # Проверяем, не истекло ли время (2 часа с момента отправки объявления)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(RaffleParticipant).where(
                    and_(
                        RaffleParticipant.user_id == cb.from_user.id,
                        RaffleParticipant.raffle_date == raffle_date
                    )
                )
            )
            participant = result.scalar_one_or_none()
            
            if participant and participant.announcement_time:
                # Проверяем, прошло ли 2 часа с момента отправки объявления (используем МСК)
                from raffle import MOSCOW_TZ
                moscow_now = datetime.now(MOSCOW_TZ)
                # announcement_time сохраняется в UTC (без timezone), конвертируем в МСК
                if participant.announcement_time.tzinfo is None:
                    # timestamp без timezone - предполагаем что это UTC
                    announcement_utc = participant.announcement_time.replace(tzinfo=timezone.utc)
                    announcement_moscow = announcement_utc.astimezone(MOSCOW_TZ)
                else:
                    # Если есть timezone, конвертируем в МСК
                    announcement_moscow = participant.announcement_time.astimezone(MOSCOW_TZ)
                time_since_announcement = (moscow_now - announcement_moscow).total_seconds() / 3600
                if time_since_announcement > RAFFLE_PARTICIPATION_WINDOW:
                    await cb.answer(
                        f"⏰ Время участия истекло. У тебя было {RAFFLE_PARTICIPATION_WINDOW} часа с момента получения объявления.",
                        show_alert=True
                    )
                    return
            elif not participant:
                # Если записи нет, значит объявление было отправлено недавно, разрешаем участие
                pass
        
        # Проверяем, активен ли розыгрыш
        if not await is_raffle_active(raffle_date):
            await cb.answer("⛔ Розыгрыш остановлен администратором.", show_alert=True)
            return
        
        # Обрабатываем участие
        success = await handle_raffle_participation(bot, cb.from_user.id, cb.message.message_id, raffle_date)
        
        if success:
            await cb.answer("✅ Ты принял участие! Проверь сообщение выше.")
            # Активируем режим ожидания ответа
            raffle_participants[cb.from_user.id] = raffle_date
        else:
            await cb.answer("❌ Произошла ошибка или ты уже участвуешь в этом розыгрыше.", show_alert=True)
            
    except Exception as e:
        logger.error(f"Ошибка при обработке участия в розыгрыше: {e}", exc_info=True)
        await cb.answer("❌ Произошла ошибка. Попробуй позже.", show_alert=True)

@dp.callback_query(F.data == "admin_raffle")
async def admin_raffle_menu(cb: types.CallbackQuery):
    """Меню админ-панели для розыгрышей - список всех возможных дат"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        # RAFFLE_DATES уже импортирован в начале файла
        # Проверяем, что RAFFLE_DATES загружен
        logger.debug(f"RAFFLE_DATES: {RAFFLE_DATES}, тип: {type(RAFFLE_DATES)}, длина: {len(RAFFLE_DATES) if RAFFLE_DATES else 0}")
        
        if not RAFFLE_DATES or len(RAFFLE_DATES) == 0:
            logger.error("RAFFLE_DATES пустой или не загружен!")
            text = (
                "🎁 <b>Розыгрыш</b>\n\n"
                "❌ Ошибка: даты розыгрышей не найдены в конфигурации.\n\n"
                "Проверьте файл raffle.py и убедитесь, что RAFFLE_DATES определен."
            )
            buttons = [[types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]]
            await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
            await cb.answer()
            return
        
        # Получаем все розыгрыши из базы данных для проверки статуса
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Raffle)
            )
            raffles_db = {r.raffle_date: r for r in result.scalars().all()}
        
        text = "🎁 <b>Розыгрыш</b>\n\nВыбери дату розыгрыша:\n\n"
        
        buttons = []
        for raffle_date in RAFFLE_DATES:
            # Форматируем дату для отображения
            try:
                date_obj = datetime.strptime(raffle_date, "%Y-%m-%d")
                date_display = date_obj.strftime("%d.%m")
            except:
                date_display = raffle_date
            
            # Проверяем, есть ли розыгрыш в БД
            raffle = raffles_db.get(raffle_date)
            if raffle:
                # Проверяем активность с учетом времени закрытия
                is_active = await is_raffle_active(raffle_date)
                status_icon = "🟢" if is_active else "🔴"
                button_text = f"{status_icon} Розыгрыш №{raffle.raffle_number} от {date_display}"
            else:
                # Розыгрыш еще не создан
                status_icon = "⚪"
                button_text = f"{status_icon} {date_display} (не создан)"
            
            buttons.append([types.InlineKeyboardButton(
                text=button_text,
                callback_data=f"admin_raffle_date_{raffle_date}"
            )])
        
        if not buttons:
            # Если по какой-то причине кнопки не созданы
            text = "🎁 <b>Розыгрыш</b>\n\n❌ Не удалось загрузить даты розыгрышей."
            buttons = [[types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]]
        else:
            buttons.append([types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")])
        
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
        await cb.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при открытии меню розыгрыша: {e}", exc_info=True)
        logger.error(f"RAFFLE_DATES при ошибке: {RAFFLE_DATES if 'RAFFLE_DATES' in locals() else 'не загружен'}")
        await cb.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data.startswith("admin_raffle_date_"))
async def admin_raffle_date_menu(cb: types.CallbackQuery):
    """Меню для конкретной даты розыгрыша - вопросы и управление"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        raffle_date = cb.data.split("_")[-1]
        
        # Получаем информацию о розыгрыше (может быть None, если еще не создан)
        raffle = await get_raffle_by_date(raffle_date)
        
        # Получаем все вопросы для этой даты
        questions = get_all_questions(raffle_date)
        
        # Форматируем дату для отображения
        try:
            date_obj = datetime.strptime(raffle_date, "%Y-%m-%d")
            date_display = date_obj.strftime("%d.%m.%Y")
        except:
            date_display = raffle_date
        
        # Формируем текст
        if raffle:
            is_active = await is_raffle_active(raffle_date)
            status = "🟢 Активен" if is_active else "🔴 Остановлен"
            text = (
                f"🎁 <b>Розыгрыш от {date_display}</b>\n"
                f"#{raffle.raffle_number} | {status}\n\n"
            )
        else:
            text = (
                f"🎁 <b>Розыгрыш от {date_display}</b>\n"
                f"⚪ Розыгрыш еще не создан\n\n"
            )
        
        # Проверяем, начался ли розыгрыш
        raffle_started = await has_raffle_started(raffle_date)
        
        if questions:
            if raffle and not raffle_started:
                text += "Выбери действие:\n\n"
            elif raffle:
                text += "Выбери вопрос для просмотра участников:\n\n"
            else:
                text += "Вопросы для этого розыгрыша:\n\n"
        else:
            text += "Вопросы не найдены.\n\n"
        
        buttons = []
        
        # Если розыгрыш создан и начался - показываем вопросы для просмотра участников
        if raffle and raffle_started:
            for question in questions:
                buttons.append([types.InlineKeyboardButton(
                    text=f"❓ {question['title']}",
                    callback_data=f"admin_raffle_question_{raffle_date}_{question['id']}"
                )])
        # Если розыгрыш создан, но не начался - показываем вопросы для редактирования
        elif raffle and not raffle_started:
            for question in questions:
                buttons.append([types.InlineKeyboardButton(
                    text=f"❓ {question['title']}",
                    callback_data=f"admin_question_edit_{raffle_date}_{question['id']}"
                )])
        # Если розыгрыш не создан - показываем вопросы для редактирования
        else:
            for question in questions:
                buttons.append([types.InlineKeyboardButton(
                    text=f"❓ {question['title']}",
                    callback_data=f"admin_question_edit_{raffle_date}_{question['id']}"
                )])
        
        # Добавляем кнопку редактирования вопросов (всегда доступна)
        buttons.append([types.InlineKeyboardButton(
            text="✏️ Редактировать вопросы",
            callback_data=f"admin_questions_date_{raffle_date}"
        )])
        
        # Добавляем кнопку для отправки напоминания тем, кто не ответил за 15 минут
        try:
            users_for_reminder = await get_users_for_reminder(raffle_date)
            reminder_count = len(users_for_reminder)
            logger.debug(f"Пользователей для напоминания для {raffle_date}: {reminder_count}")
            
            if reminder_count > 0:
                buttons.append([types.InlineKeyboardButton(
                    text=f"📨 Направить напоминание ({reminder_count})",
                    callback_data=f"admin_send_reminder_all_{raffle_date}"
                )])
        except Exception as e:
            logger.error(f"Ошибка при получении списка пользователей для напоминания для {raffle_date}: {e}", exc_info=True)
        
        # Кнопка остановки убрана - доступна только через команду /raffle_stop
        
        buttons.append([types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin_raffle")])
        
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
        await cb.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при открытии меню вопросов для даты: {e}", exc_info=True)
        await cb.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data.startswith("admin_raffle_question_"))
async def admin_raffle_question(cb: types.CallbackQuery):
    """Просмотр участников по вопросу"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        parts = cb.data.split("_")
        raffle_date = parts[3]
        question_id = int(parts[4])
        
        question = get_question_by_id(question_id, raffle_date)
        if not question:
            await cb.answer("Вопрос не найден", show_alert=True)
            return
        
        participants = await get_participants_by_question(raffle_date, question_id)
        
        # Фильтруем только тех, кто нажал кнопку (question_id != 0)
        active_participants = [p for p in participants if p.question_id != 0]
        
        text = f"📋 <b>{question['title']}</b>\n\n"
        text += f"👥 Участников: {len(active_participants)}\n\n"
        
        if active_participants:
            text += "Список участников:\n"
            for i, p in enumerate(active_participants[:20], 1):  # Показываем первые 20
                if p.is_correct is True:
                    status = "✅ принят"
                elif p.is_correct is False:
                    status = "❌ отклонен"
                elif p.answer is None:
                    status = "⏳ не ответил"
                else:
                    status = "⏳ не проверен"
                text += f"{i}. ID: {p.user_id} - {status}\n"
            
            if len(active_participants) > 20:
                text += f"\n... и еще {len(active_participants) - 20} участников"
        else:
            text += "Участников пока нет."
        
        # Подсчитываем тех, кто не ответил
        not_answered_count = len([p for p in active_participants if p.answer is None])
        
        buttons = [
            [types.InlineKeyboardButton(
                text="🔍 Проверить результаты",
                callback_data=f"admin_raffle_results_{raffle_date}_{question_id}"
            )]
        ]
        
        # Добавляем кнопку напоминания только если есть те, кто не ответил
        if not_answered_count > 0:
            buttons.append([
                types.InlineKeyboardButton(
                    text=f"📨 Отправить напоминание ({not_answered_count})",
                    callback_data=f"admin_send_reminder_{raffle_date}_{question_id}"
                )
            ])
        
        buttons.append([types.InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_raffle_date_{raffle_date}")])
        
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
        await cb.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при просмотре участников: {e}")
        await cb.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data.startswith("admin_raffle_stop_"))
async def admin_raffle_stop(cb: types.CallbackQuery):
    """Остановка розыгрыша"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        raffle_date = cb.data.split("_")[-1]
        
        # Подтверждение остановки
        raffle = await get_raffle_by_date(raffle_date)
        if not raffle:
            await cb.answer("Розыгрыш не найден", show_alert=True)
            return
        
        if not raffle.is_active:
            await cb.answer("Розыгрыш уже остановлен", show_alert=True)
            return
        
        # Останавливаем розыгрыш
        success = await stop_raffle(raffle_date)
        
        if success:
            await cb.answer("✅ Розыгрыш остановлен", show_alert=False)
            # Возвращаемся в меню дат розыгрышей
            await admin_raffle_menu(cb)
        else:
            await cb.answer("❌ Ошибка при остановке розыгрыша", show_alert=True)
            
    except Exception as e:
        logger.error(f"Ошибка при остановке розыгрыша: {e}")
        await cb.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data.startswith("admin_raffle_results_"))
async def admin_raffle_results(cb: types.CallbackQuery):
    """Просмотр результатов (ответов) по вопросу"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        parts = cb.data.split("_")
        raffle_date = parts[3]
        question_id = int(parts[4])
        
        question = get_question_by_id(question_id, raffle_date)
        if not question:
            await cb.answer("Вопрос не найден", show_alert=True)
            return
        
        participants = await get_participants_by_question(raffle_date, question_id)
        
        # Фильтруем только тех, кто нажал кнопку (question_id != 0) и ответил
        answered = [p for p in participants if p.question_id != 0 and p.answer is not None]
        
        text = f"📊 <b>Результаты: {question['title']}</b>\n\n"
        
        if answered:
            # Получаем информацию о пользователях из базы данных
            user_ids = [p.user_id for p in answered]
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(User).where(User.id.in_(user_ids))
                )
                users = {u.id: u for u in result.scalars().all()}
            
            for p in answered:
                status_icon = "✅" if p.is_correct is True else ("❌" if p.is_correct is False else "⏳")
                user = users.get(p.user_id)
                username = f"@{user.username}" if user and user.username else ""
                first_name = user.first_name if user and user.first_name else ""
                
                # Формируем строку с информацией о пользователе
                user_info = f"<b>ID: {p.user_id}</b>"
                if username:
                    user_info += f" {username}"
                if first_name:
                    user_info += f" ({first_name})"
                
                text += f"{status_icon} {user_info}\n"
                text += f"Ответ: {p.answer}\n"
                text += f"Время: {p.timestamp.strftime('%d.%m.%Y %H:%M')}\n\n"
        else:
            text += "Ответов пока нет."
        
        buttons = [
            [types.InlineKeyboardButton(text="◀️ Назад к вопросу", callback_data=f"admin_raffle_question_{raffle_date}_{question_id}")],
            [types.InlineKeyboardButton(text="◀️ К списку дат", callback_data="admin_raffle")]
        ]
        
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
        await cb.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при просмотре результатов: {e}")
        await cb.answer("Ошибка", show_alert=True)


@dp.callback_query(F.data == "admin_quiz")
async def admin_quiz_menu(cb: types.CallbackQuery):
    """Меню админ-панели для квизов - список всех возможных дат"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        # Генерируем список дат квизов с 11.12 по 16.12
        from datetime import timedelta
        start_date = datetime.strptime(QUIZ_START_DATE, "%Y-%m-%d").date()
        end_date = datetime.strptime(QUIZ_END_DATE, "%Y-%m-%d").date()
        
        quiz_dates = []
        current_date = start_date
        while current_date <= end_date:
            quiz_dates.append(current_date.strftime("%Y-%m-%d"))
            current_date += timedelta(days=1)
        
        # Получаем все квизы из базы данных для проверки статуса
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Quiz)
            )
            quizzes_db = {q.quiz_date: q for q in result.scalars().all()}
        
        text = "🎯 <b>Квиз</b>\n\nВыбери дату квиза:\n\n"
        
        buttons = []
        for quiz_date in quiz_dates:
            # Форматируем дату для отображения
            try:
                date_obj = datetime.strptime(quiz_date, "%Y-%m-%d")
                date_display = date_obj.strftime("%d.%m")
            except:
                date_display = quiz_date
            
            # Проверяем, есть ли квиз в БД
            quiz = quizzes_db.get(quiz_date)
            if quiz:
                # Проверяем активность
                moscow_now = datetime.now(QUIZ_MOSCOW_TZ)
                quiz_date_obj = datetime.strptime(quiz_date, "%Y-%m-%d").date()
                
                # Время начала квиза (QUIZ_HOUR:QUIZ_MINUTE МСК)
                quiz_start_time = datetime.combine(quiz_date_obj, dt_time(hour=QUIZ_HOUR, minute=QUIZ_MINUTE))
                quiz_start_time = quiz_start_time.replace(tzinfo=QUIZ_MOSCOW_TZ)
                
                # Время окончания квиза (QUIZ_HOUR:QUIZ_MINUTE + 6 часов МСК)
                quiz_end_time = quiz_start_time + timedelta(hours=QUIZ_PARTICIPATION_WINDOW)
                
                # Проверяем, был ли отправлен announcement
                async with AsyncSessionLocal() as session:
                    announcement_check = await session.execute(
                        select(QuizParticipant).where(
                            and_(
                                QuizParticipant.quiz_date == quiz_date,
                                QuizParticipant.announcement_time.isnot(None)
                            )
                        ).limit(1)
                    )
                    has_announcement = announcement_check.scalar_one_or_none() is not None
                
                if has_announcement:
                    # Квиз начался - проверяем время
                    if quiz.is_active and moscow_now >= quiz_start_time and moscow_now < quiz_end_time:
                        status_icon = "🟢"
                        status_text = "Активен"
                    elif moscow_now >= quiz_end_time:
                        status_icon = "🔵"
                        status_text = "Завершен"
                    else:
                        status_icon = "🔴"
                        status_text = "Остановлен"
                else:
                    # Квиз создан, но еще не начался
                    if moscow_now < quiz_start_time:
                        status_icon = "⏳"
                        status_text = "Ожидает запуска"
                    elif quiz.is_active:
                        status_icon = "🟢"
                        status_text = "Активен"
                    else:
                        status_icon = "🔴"
                        status_text = "Остановлен"
                
                button_text = f"{status_icon} Квиз от {date_display} ({status_text})"
            else:
                # Квиз еще не создан
                status_icon = "⚪"
                button_text = f"{status_icon} {date_display} (не создан)"
            
            buttons.append([types.InlineKeyboardButton(
                text=button_text,
                callback_data=f"admin_quiz_date_{quiz_date}"
            )])
        
        if not buttons:
            text = "🎯 <b>Квиз</b>\n\n❌ Не удалось загрузить даты квизов."
            buttons = [[types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]]
        else:
            buttons.append([types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")])
        
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
        await cb.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при открытии меню квиза: {e}", exc_info=True)
        await cb.answer("Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("admin_quiz_date_"))
async def admin_quiz_date_menu(cb: types.CallbackQuery):
    """Меню для конкретной даты квиза - детальная информация"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        quiz_date = cb.data.split("_")[-1]
        
        # Получаем информацию о квизе (без создания, только для просмотра)
        quiz = await get_quiz(quiz_date)
        
        # Форматируем дату для отображения
        try:
            date_obj = datetime.strptime(quiz_date, "%Y-%m-%d")
            date_display = date_obj.strftime("%d.%m.%Y")
        except:
            date_display = quiz_date
        
        # Проверяем статус
        moscow_now = datetime.now(QUIZ_MOSCOW_TZ)
        quiz_date_obj = datetime.strptime(quiz_date, "%Y-%m-%d").date()
        
        # Время начала квиза (QUIZ_HOUR:QUIZ_MINUTE МСК)
        quiz_start_time = datetime.combine(quiz_date_obj, dt_time(hour=QUIZ_HOUR, minute=QUIZ_MINUTE))
        quiz_start_time = quiz_start_time.replace(tzinfo=QUIZ_MOSCOW_TZ)
        
        # Время окончания квиза (QUIZ_HOUR:QUIZ_MINUTE + 6 часов МСК)
        quiz_end_time = quiz_start_time + timedelta(hours=QUIZ_PARTICIPATION_WINDOW)
        
        if quiz:
            # Проверяем, был ли отправлен announcement (квиз начался)
            async with AsyncSessionLocal() as session:
                announcement_check = await session.execute(
                    select(QuizParticipant).where(
                        and_(
                            QuizParticipant.quiz_date == quiz_date,
                            QuizParticipant.announcement_time.isnot(None)
                        )
                    ).limit(1)
                )
                has_announcement = announcement_check.scalar_one_or_none() is not None
            
            if has_announcement:
                # Квиз начался - проверяем время
                if quiz.is_active and moscow_now >= quiz_start_time and moscow_now < quiz_end_time:
                    status = "🟢 Активен"
                elif moscow_now >= quiz_end_time:
                    status = "🔵 Завершен"
                else:
                    status = "🔴 Остановлен"
            else:
                # Квиз создан, но еще не начался (announcement не отправлен)
                if moscow_now < quiz_start_time:
                    status = "⏳ Ожидает запуска"
                elif quiz.is_active:
                    status = "🟢 Активен"
                else:
                    status = "🔴 Остановлен"
        else:
            status = "⚪ Не создан"
        
        text = f"🎯 <b>Квиз от {date_display}</b>\n{status}\n\n"
        
        # Получаем статистику
        async with AsyncSessionLocal() as session:
            # Все участники
            participants_result = await session.execute(
                select(QuizParticipant).where(QuizParticipant.quiz_date == quiz_date)
            )
            all_participants = participants_result.scalars().all()
            
            # Получили билетик
            tickets_result = await session.execute(
                select(QuizResult).where(
                    and_(
                        QuizResult.quiz_date == quiz_date,
                        QuizResult.ticket_number.isnot(None)
                    )
                )
            )
            with_tickets = tickets_result.scalars().all()
            
            # Не получили билетик (но начали квиз - прошли или не успели)
            no_tickets_result = await session.execute(
                select(QuizResult).where(
                    and_(
                        QuizResult.quiz_date == quiz_date,
                        QuizResult.ticket_number.is_(None),
                        QuizResult.total_questions > 0  # Начали квиз (отличает от не принявших участие)
                    )
                )
            )
            no_tickets = no_tickets_result.scalars().all()
            
            # Не приняли участие
            non_participants_result = await session.execute(
                select(QuizResult).where(
                    and_(
                        QuizResult.quiz_date == quiz_date,
                        QuizResult.correct_answers == 0,
                        QuizResult.total_questions == 0
                    )
                )
            )
            non_participants = non_participants_result.scalars().all()
        
        text += (
            f"📊 <b>Статистика:</b>\n"
            f"👥 Всего участников: {len(all_participants)}\n"
            f"🎫 Получили билетик: {len(with_tickets)}\n"
            f"❌ Не получили билетик: {len(no_tickets)}\n"
            f"⏭️ Не приняли участие: {len(non_participants)}\n"
        )
        
        buttons = [
            [types.InlineKeyboardButton(
                text=f"👥 Все участники ({len(all_participants)})",
                callback_data=f"admin_quiz_participants_{quiz_date}"
            )],
            [types.InlineKeyboardButton(
                text=f"🎫 Получили билетик ({len(with_tickets)})",
                callback_data=f"admin_quiz_tickets_{quiz_date}"
            )],
            [types.InlineKeyboardButton(
                text=f"❌ Не получили билетик ({len(no_tickets)})",
                callback_data=f"admin_quiz_no_tickets_{quiz_date}"
            )],
            [types.InlineKeyboardButton(
                text=f"⏭️ Не приняли участие ({len(non_participants)})",
                callback_data=f"admin_quiz_non_participants_{quiz_date}"
            )]
        ]
        
        # Добавляем кнопку редактирования вопросов только если квиз не начался
        quiz_started = await has_quiz_started(quiz_date)
        if not quiz_started:
            buttons.append([types.InlineKeyboardButton(
                text="✏️ Редактировать вопросы",
                callback_data=f"admin_quiz_questions_date_{quiz_date}"
            )])
        
        buttons.append([types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin_quiz")])
        
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
        await cb.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при открытии меню квиза для даты: {e}", exc_info=True)
        await cb.answer("Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("admin_quiz_participants_"))
async def admin_quiz_participants(cb: types.CallbackQuery):
    """Просмотр всех участников квиза"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        quiz_date = cb.data.split("_")[-1]
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(QuizParticipant).where(QuizParticipant.quiz_date == quiz_date)
            )
            participants = result.scalars().all()
            
            # Получаем информацию о пользователях
            user_ids = [p.user_id for p in participants]
            users_result = await session.execute(
                select(User).where(User.id.in_(user_ids))
            )
            users = {u.id: u for u in users_result.scalars().all()}
        
        try:
            date_obj = datetime.strptime(quiz_date, "%Y-%m-%d")
            date_display = date_obj.strftime("%d.%m.%Y")
        except:
            date_display = quiz_date
        
        text = f"👥 <b>Все участники квиза от {date_display}</b>\n\n"
        
        if participants:
            for i, p in enumerate(participants[:50], 1):  # Показываем первые 50
                user = users.get(p.user_id)
                username = f"@{user.username}" if user and user.username else ""
                first_name = user.first_name if user and user.first_name else ""
                
                user_info = f"<b>ID: {p.user_id}</b>"
                if username:
                    user_info += f" {username}"
                if first_name:
                    user_info += f" ({first_name})"
                
                status = "✅ Завершен" if p.completed else ("⏳ В процессе" if p.started_at else "⏸️ Не начат")
                text += f"{i}. {user_info} - {status}\n"
            
            if len(participants) > 50:
                text += f"\n... и еще {len(participants) - 50} участников"
        else:
            text += "Участников пока нет."
        
        buttons = [[types.InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_quiz_date_{quiz_date}")]]
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
        await cb.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при просмотре участников квиза: {e}", exc_info=True)
        await cb.answer("Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("admin_quiz_tickets_"))
async def admin_quiz_tickets(cb: types.CallbackQuery):
    """Просмотр тех, кто получил билетик"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        quiz_date = cb.data.split("_")[-1]
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(QuizResult).where(
                    and_(
                        QuizResult.quiz_date == quiz_date,
                        QuizResult.ticket_number.isnot(None)
                    )
                ).order_by(QuizResult.ticket_number.asc())
            )
            results = result.scalars().all()
        
        try:
            date_obj = datetime.strptime(quiz_date, "%Y-%m-%d")
            date_display = date_obj.strftime("%d.%m.%Y")
        except:
            date_display = quiz_date
        
        text = f"🎫 <b>Получили билетик (квиз от {date_display})</b>\n\n"
        
        if results:
            for i, r in enumerate(results[:50], 1):  # Показываем первые 50
                user_info = f"<b>ID: {r.user_id}</b>"
                if r.username:
                    user_info += f" @{r.username}"
                
                text += f"{i}. {user_info} - Билетик №{r.ticket_number} ({r.correct_answers}/{r.total_questions})\n"
            
            if len(results) > 50:
                text += f"\n... и еще {len(results) - 50} участников"
        else:
            text += "Никто еще не получил билетик."
        
        buttons = [[types.InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_quiz_date_{quiz_date}")]]
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
        await cb.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при просмотре получивших билетик: {e}", exc_info=True)
        await cb.answer("Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("admin_quiz_no_tickets_"))
async def admin_quiz_no_tickets(cb: types.CallbackQuery):
    """Просмотр тех, кто не получил билетик"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        quiz_date = cb.data.split("_")[-1]
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(QuizResult).where(
                    and_(
                        QuizResult.quiz_date == quiz_date,
                        QuizResult.ticket_number.is_(None),
                        QuizResult.total_questions > 0  # Начали квиз (отличает от не принявших участие)
                    )
                ).order_by(QuizResult.correct_answers.desc())
            )
            results = result.scalars().all()
        
        try:
            date_obj = datetime.strptime(quiz_date, "%Y-%m-%d")
            date_display = date_obj.strftime("%d.%m.%Y")
        except:
            date_display = quiz_date
        
        text = f"❌ <b>Не получили билетик (квиз от {date_display})</b>\n\n"
        
        if results:
            for i, r in enumerate(results[:50], 1):  # Показываем первые 50
                user_info = f"<b>ID: {r.user_id}</b>"
                if r.username:
                    user_info += f" @{r.username}"
                
                text += f"{i}. {user_info} - {r.correct_answers}/{r.total_questions} правильных\n"
            
            if len(results) > 50:
                text += f"\n... и еще {len(results) - 50} участников"
        else:
            text += "Все участники получили билетик или никто не прошел квиз."
        
        buttons = [[types.InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_quiz_date_{quiz_date}")]]
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
        await cb.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при просмотре не получивших билетик: {e}", exc_info=True)
        await cb.answer("Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("admin_quiz_non_participants_"))
async def admin_quiz_non_participants(cb: types.CallbackQuery):
    """Просмотр тех, кто не принял участие"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        quiz_date = cb.data.split("_")[-1]
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(QuizResult).where(
                    and_(
                        QuizResult.quiz_date == quiz_date,
                        QuizResult.correct_answers == 0,
                        QuizResult.total_questions == 0
                    )
                )
            )
            results = result.scalars().all()
        
        try:
            date_obj = datetime.strptime(quiz_date, "%Y-%m-%d")
            date_display = date_obj.strftime("%d.%m.%Y")
        except:
            date_display = quiz_date
        
        text = f"⏭️ <b>Не приняли участие (квиз от {date_display})</b>\n\n"
        
        if results:
            for i, r in enumerate(results[:50], 1):  # Показываем первые 50
                user_info = f"<b>ID: {r.user_id}</b>"
                if r.username:
                    user_info += f" @{r.username}"
                
                text += f"{i}. {user_info}\n"
            
            if len(results) > 50:
                text += f"\n... и еще {len(results) - 50} участников"
        else:
            text += "Все приняли участие в квизе."
        
        buttons = [[types.InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_quiz_date_{quiz_date}")]]
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
        await cb.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при просмотре не принявших участие: {e}", exc_info=True)
        await cb.answer("Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("admin_quiz_questions_date_"))
async def admin_quiz_questions_date_menu(cb: types.CallbackQuery):
    """Меню вопросов квиза для конкретной даты"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        quiz_date = cb.data.split("_")[-1]
        questions = get_all_quiz_questions(quiz_date)
        
        if not questions:
            try:
                date_obj = datetime.strptime(quiz_date, "%Y-%m-%d")
                date_display = date_obj.strftime("%d.%m.%Y")
            except:
                date_display = quiz_date
            
            text = f"❓ <b>Вопросы квиза для {date_display}</b>\n\nВопросы не найдены."
            buttons = [[types.InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_quiz_date_{quiz_date}")]]
            await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
            await cb.answer()
            return
        
        try:
            date_obj = datetime.strptime(quiz_date, "%Y-%m-%d")
            date_display = date_obj.strftime("%d.%m.%Y")
        except:
            date_display = quiz_date
        
        # Проверяем, начался ли квиз
        quiz_started = await has_quiz_started(quiz_date)
        
        text = f"❓ <b>Вопросы квиза для {date_display}</b>\n\n"
        
        if quiz_started:
            text += "⛔ <b>Квиз уже начался!</b> Редактирование недоступно.\n\n"
        
        text += "Выбери вопрос для просмотра:\n\n"
        
        buttons = []
        for question in questions:
            question_id = question.get('id')
            question_text = question.get('question', f'Вопрос #{question_id}')
            # Обрезаем текст вопроса для отображения
            if len(question_text) > 40:
                question_text = question_text[:40] + "..."
            icon = "🔒" if quiz_started else "❓"
            buttons.append([
                types.InlineKeyboardButton(
                    text=f"{icon} Вопрос #{question_id}: {question_text}",
                    callback_data=f"admin_quiz_question_edit_{quiz_date}_{question_id}"
                )
            ])
        
        buttons.append([types.InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_quiz_date_{quiz_date}")])
        
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
        await cb.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при открытии меню вопросов квиза для даты: {e}", exc_info=True)
        await cb.answer("Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("admin_quiz_question_edit_"))
async def admin_quiz_question_edit(cb: types.CallbackQuery):
    """Просмотр и редактирование вопроса квиза"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        # Формат: admin_quiz_question_edit_{quiz_date}_{question_id}
        # quiz_date может содержать дефисы (2025-12-12), поэтому разбиваем правильно
        data_parts = cb.data.split("_", 4)  # Разбиваем только первые 4 части
        if len(data_parts) < 5:
            await cb.answer("❌ Неверный формат данных", show_alert=True)
            return
        
        # data_parts[4] содержит "{quiz_date}_{question_id}"
        remaining = data_parts[4]
        # Разделяем дату и ID вопроса (дата заканчивается, затем идет подчеркивание и ID)
        # Ищем последнее подчеркивание, перед которым идет дата
        last_underscore = remaining.rfind("_")
        if last_underscore == -1:
            await cb.answer("❌ Неверный формат данных", show_alert=True)
            return
        
        quiz_date = remaining[:last_underscore]
        question_id = int(remaining[last_underscore + 1:])
        
        question = get_quiz_question(question_id, quiz_date)
        
        if not question:
            await cb.answer("Вопрос не найден", show_alert=True)
            return
        
        try:
            date_obj = datetime.strptime(quiz_date, "%Y-%m-%d")
            date_display = date_obj.strftime("%d.%m.%Y")
        except:
            date_display = quiz_date
        
        # Проверяем, начался ли квиз
        quiz_started = await has_quiz_started(quiz_date)
        
        text = (
            f"❓ <b>Вопрос #{question_id}</b>\n"
            f"📅 Дата: {date_display}\n\n"
        )
        
        if quiz_started:
            text += "⛔ <b>Квиз уже начался!</b> Редактирование недоступно.\n\n"
        
        question_text = question.get('question', '')
        options = question.get('options', {})
        correct_answer = question.get('correct_answer', '')
        
        # Экранируем HTML-символы для безопасного отображения
        question_text_escaped = html.escape(question_text)
        
        text += f"<b>Вопрос:</b> {question_text_escaped}\n\n"
        text += "<b>Варианты ответов:</b>\n"
        for key, value in sorted(options.items()):
            marker = "✅" if key == correct_answer else "  "
            value_escaped = html.escape(str(value))
            text += f"{marker} {key}: {value_escaped}\n"
        
        text += f"\n<b>Правильный ответ:</b> {correct_answer}\n\n"
        
        if not quiz_started:
            text += (
                f"Для редактирования отправь команду:\n"
                f"<code>/edit_quiz_question {quiz_date} {question_id} Текст вопроса | A:Вариант A | Б:Вариант Б | В:Вариант В | Г:Вариант Г | Правильный ответ</code>\n\n"
                f"Пример:\n"
                f"<code>/edit_quiz_question {quiz_date} {question_id} Какая температура воды? | A:+43+51С | Б:+18+22С | В:+65С | Г:+21+50С | Б</code>"
            )
        else:
            text += "⚠️ Вопросы можно редактировать только до начала квиза."
        
        buttons = [
            [types.InlineKeyboardButton(text="◀️ Назад к списку", callback_data=f"admin_quiz_questions_date_{quiz_date}")]
        ]
        
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
        await cb.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при просмотре вопроса квиза: {e}", exc_info=True)
        await cb.answer("Ошибка", show_alert=True)


@dp.message(Command("edit_quiz_question"))
async def cmd_edit_quiz_question(message: types.Message):
    """Редактирование вопроса квиза через команду"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен.")
        return
    
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            await message.answer(
                "❌ Неверный формат. Используй:\n"
                "<code>/edit_quiz_question ДАТА ID Вопрос | A:Вариант A | Б:Вариант Б | В:Вариант В | Г:Вариант Г | Правильный ответ</code>\n\n"
                "Пример:\n"
                "<code>/edit_quiz_question 2025-12-12 1 Какая температура воды? | A:+43+51С | Б:+18+22С | В:+65С | Г:+21+50С | Б</code>",
                parse_mode="HTML"
            )
            return
        
        quiz_date = parts[1]
        question_id = int(parts[2])
        content = parts[3]
        
        if "|" not in content:
            await message.answer("❌ Используй разделитель | между вопросом, вариантами ответов и правильным ответом")
            return
        
        # Парсим содержимое
        segments = [s.strip() for s in content.split("|")]
        if len(segments) < 6:
            await message.answer("❌ Неверный формат. Нужно: Вопрос | A:... | Б:... | В:... | Г:... | Правильный ответ")
            return
        
        question_text = segments[0]
        options = {}
        correct_answer = None
        
        # Парсим варианты ответов
        for segment in segments[1:5]:
            if ":" not in segment:
                await message.answer(f"❌ Неверный формат варианта ответа: {segment}. Используй формат 'A:Текст'")
                return
            key, value = segment.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key not in ["A", "Б", "В", "Г"]:
                await message.answer(f"❌ Неверный ключ варианта: {key}. Используй A, Б, В или Г")
                return
            options[key] = value
        
        # Правильный ответ
        correct_answer = segments[5].strip()
        if correct_answer not in ["A", "Б", "В", "Г"]:
            await message.answer(f"❌ Неверный правильный ответ: {correct_answer}. Используй A, Б, В или Г")
            return
        
        if not question_text:
            await message.answer("❌ Текст вопроса не может быть пустым")
            return
        
        # Проверяем, начался ли квиз
        quiz_started = await has_quiz_started(quiz_date)
        if quiz_started:
            try:
                date_obj = datetime.strptime(quiz_date, "%Y-%m-%d")
                date_display = date_obj.strftime("%d.%m.%Y")
            except:
                date_display = quiz_date
            
            await message.answer(
                f"⛔ <b>Невозможно редактировать вопрос!</b>\n\n"
                f"Квиз на {date_display} уже начался (объявления были отправлены пользователям).\n\n"
                f"Вопросы можно редактировать только до начала квиза.",
                parse_mode="HTML"
            )
            return
        
        # Проверяем, существует ли вопрос
        existing_question = get_quiz_question(question_id, quiz_date)
        if not existing_question:
            await message.answer(f"❌ Вопрос с ID {question_id} для даты {quiz_date} не найден")
            return
        
        # Обновляем вопрос
        success = update_quiz_question(question_id, quiz_date, question_text, options, correct_answer)
        
        if success:
            try:
                date_obj = datetime.strptime(quiz_date, "%Y-%m-%d")
                date_display = date_obj.strftime("%d.%m.%Y")
            except:
                date_display = quiz_date
            
            options_text = "\n".join([f"{k}: {v}" for k, v in sorted(options.items())])
            await message.answer(
                f"✅ Вопрос #{question_id} для {date_display} успешно обновлен!\n\n"
                f"<b>Вопрос:</b> {question_text}\n\n"
                f"<b>Варианты ответов:</b>\n{options_text}\n\n"
                f"<b>Правильный ответ:</b> {correct_answer}",
                parse_mode="HTML"
            )
        else:
            await message.answer("❌ Ошибка при обновлении вопроса. Проверь логи.")
        
    except ValueError as e:
        await message.answer(f"❌ Ошибка в формате данных: {e}")
    except Exception as e:
        logger.error(f"Ошибка при редактировании вопроса квиза: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка: {e}")


@dp.callback_query(F.data.startswith("admin_send_reminder_all_"))
async def admin_send_reminder_all(cb: types.CallbackQuery):
    """Отправка напоминания всем, кто не ответил за 15 минут для всей даты розыгрыша"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        raffle_date = cb.data.split("_")[-1]
        
        # Получаем список пользователей, которым нужно отправить напоминание
        users_for_reminder = await get_users_for_reminder(raffle_date)
        
        if not users_for_reminder:
            await cb.answer("Нет пользователей, которым нужно отправить напоминание", show_alert=True)
            return
        
        # Текст напоминания
        reminder_text = (
            "⏰ От тебя не поступил ответ на задание.\n\n"
            "Ждем тебя на следующем задании! 💫"
        )
        
        # Отправляем напоминания
        sent_count = 0
        blocked_count = 0
        error_count = 0
        
        await cb.answer("Отправка напоминаний...", show_alert=False)
        
        for participant in users_for_reminder:
            success = await safe_send_message(bot, participant.user_id, reminder_text)
            if success:
                sent_count += 1
            else:
                # Проверяем, заблокирован ли бот
                try:
                    await bot.send_chat_action(participant.user_id, "typing")
                    error_count += 1
                except TelegramForbiddenError:
                    blocked_count += 1
                except Exception:
                    error_count += 1
            
            # Небольшая задержка между отправками
            await asyncio.sleep(RATE_LIMIT_DELAY)
        
        # Формируем отчет для админа
        try:
            date_obj = datetime.strptime(raffle_date, "%Y-%m-%d")
            date_display = date_obj.strftime("%d.%m.%Y")
        except:
            date_display = raffle_date
        
        report_text = (
            f"📨 <b>Напоминания отправлены для {date_display}</b>\n\n"
            f"✅ Отправлено: {sent_count}\n"
        )
        
        if blocked_count > 0:
            report_text += f"🚫 Заблокировали бота: {blocked_count}\n"
        
        if error_count > 0:
            report_text += f"❌ Ошибок: {error_count}\n"
        
        await cb.message.answer(report_text, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке напоминаний: {e}", exc_info=True)
        await cb.answer("Ошибка при отправке", show_alert=True)


@dp.callback_query(F.data.startswith("admin_send_reminder_"))
async def admin_send_reminder(cb: types.CallbackQuery):
    """Отправка напоминания тем, кто не ответил на вопрос (для конкретного вопроса)"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        parts = cb.data.split("_")
        raffle_date = parts[3]
        question_id = int(parts[4])
        
        question = get_question_by_id(question_id, raffle_date)
        if not question:
            await cb.answer("Вопрос не найден", show_alert=True)
            return
        
        participants = await get_participants_by_question(raffle_date, question_id)
        
        # Фильтруем только тех, кто нажал кнопку, но не ответил
        not_answered = [p for p in participants if p.question_id != 0 and p.answer is None]
        
        if not not_answered:
            await cb.answer("Нет участников, которым нужно отправить напоминание", show_alert=True)
            return
        
        # Текст напоминания
        reminder_text = (
            "⏰ От тебя не поступил ответ на задание.\n\n"
            "Ждем тебя на следующем задании! 💫"
        )
        
        # Отправляем напоминания
        sent_count = 0
        blocked_count = 0
        error_count = 0
        
        await cb.answer("Отправка напоминаний...", show_alert=False)
        
        for participant in not_answered:
            success = await safe_send_message(bot, participant.user_id, reminder_text)
            if success:
                sent_count += 1
            else:
                # Проверяем, заблокирован ли бот
                try:
                    await bot.send_chat_action(participant.user_id, "typing")
                    error_count += 1
                except TelegramForbiddenError:
                    blocked_count += 1
                except Exception:
                    error_count += 1
            
            # Небольшая задержка между отправками
            await asyncio.sleep(RATE_LIMIT_DELAY)
        
        # Формируем отчет для админа
        report_text = (
            f"📨 <b>Напоминания отправлены</b>\n\n"
            f"✅ Отправлено: {sent_count}\n"
        )
        
        if blocked_count > 0:
            report_text += f"🚫 Заблокировали бота: {blocked_count}\n"
        
        if error_count > 0:
            report_text += f"❌ Ошибок: {error_count}\n"
        
        await cb.message.answer(report_text, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке напоминаний: {e}", exc_info=True)
        await cb.answer("Ошибка при отправке", show_alert=True)

@dp.callback_query(F.data.startswith("admin_unchecked_"))
async def admin_unchecked_answers(cb: types.CallbackQuery):
    """Просмотр непроверенных ответов для даты розыгрыша"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        # Парсим callback_data: admin_unchecked_{raffle_date} или admin_unchecked_{raffle_date}_{index}
        # Формат: admin_unchecked_2025-12-08 или admin_unchecked_2025-12-08_1
        data_parts = cb.data.split("_", 2)  # Разделяем только первые 2 раза
        if len(data_parts) < 3:
            await cb.answer("Ошибка формата данных", show_alert=True)
            return
        
        # data_parts[2] содержит либо "2025-12-08", либо "2025-12-08_1"
        remaining = data_parts[2]
        if "_" in remaining:
            # Есть индекс
            raffle_date, index_str = remaining.rsplit("_", 1)
            try:
                current_index = int(index_str)
            except ValueError:
                current_index = 0
        else:
            # Нет индекса, начинаем с 0
            raffle_date = remaining
            current_index = 0
        
        # Получаем непроверенные ответы
        unchecked = await get_unchecked_answers(raffle_date)
        
        if not unchecked:
            try:
                date_obj = datetime.strptime(raffle_date, "%Y-%m-%d")
                date_display = date_obj.strftime("%d.%m.%Y")
            except:
                date_display = raffle_date
            
            text = f"⏳ <b>Непроверенные ответы для {date_display}</b>\n\n✅ Все ответы проверены!"
            buttons = [[types.InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_raffle_date_{raffle_date}")]]
            await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
            await cb.answer()
            return
        
        # Проверяем, не вышли ли за пределы списка
        if current_index >= len(unchecked):
            try:
                date_obj = datetime.strptime(raffle_date, "%Y-%m-%d")
                date_display = date_obj.strftime("%d.%m.%Y")
            except:
                date_display = raffle_date
            
            text = f"⏳ <b>Непроверенные ответы для {date_display}</b>\n\n✅ Все ответы проверены!"
            buttons = [[types.InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_raffle_date_{raffle_date}")]]
            await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
            await cb.answer()
            return
        
        # Получаем информацию о пользователях
        user_ids = [p.user_id for p in unchecked]
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.id.in_(user_ids))
            )
            users = {u.id: u for u in result.scalars().all()}
        
        # Показываем участника по текущему индексу
        participant = unchecked[current_index]
        user = users.get(participant.user_id)
        username = f"@{user.username}" if user and user.username else ""
        first_name = user.first_name if user and user.first_name else ""
        
        # Проверяем, заблокирован ли бот пользователем
        user_blocked = False
        try:
            # Пытаемся отправить тестовое сообщение (невидимое для пользователя)
            await bot.send_chat_action(participant.user_id, "typing")
        except TelegramForbiddenError:
            user_blocked = True
            logger.info(f"Пользователь {participant.user_id} заблокировал бота")
        except Exception as e:
            # Другие ошибки игнорируем (может быть временная проблема)
            logger.debug(f"Ошибка при проверке статуса пользователя {participant.user_id}: {e}")
        
        # Получаем вопрос
        question = get_question_by_id(participant.question_id, raffle_date)
        question_title = question.get('title', 'Вопрос') if question else 'Вопрос'
        question_text = question.get('text', '') if question else ''
        
        try:
            date_obj = datetime.strptime(raffle_date, "%Y-%m-%d")
            date_display = date_obj.strftime("%d.%m.%Y")
        except:
            date_display = raffle_date
        
        # Формируем информацию о пользователе
        user_info = f"<b>ID: {participant.user_id}</b>"
        if username:
            user_info += f" {username}"
        if first_name:
            user_info += f" ({first_name})"
        if user_blocked:
            user_info += " 🚫 <b>(заблокировал бота)</b>"
        
        text = (
            f"⏳ <b>Непроверенные ответы для {date_display}</b>\n\n"
        )
        
        if user_blocked:
            text += "⚠️ <b>ВНИМАНИЕ:</b> Пользователь заблокировал бота. Сообщение о результате не будет отправлено.\n\n"
        
        text += (
            f"📋 <b>Вопрос:</b> {question_title}\n"
            f"{question_text}\n\n"
            f"👤 <b>Пользователь:</b> {user_info}\n"
        )
        
        # Проверяем, ответил ли пользователь
        if participant.answer:
            text += (
                f"💬 <b>Ответ:</b> {participant.answer}\n"
                f"⏰ <b>Время ответа:</b> {participant.timestamp.strftime('%d.%m.%Y %H:%M')}\n\n"
            )
        else:
            text += (
                f"⏳ <b>Пользователь еще не ответил на вопрос</b>\n"
                f"⏰ <b>Время получения вопроса:</b> {participant.timestamp.strftime('%d.%m.%Y %H:%M')}\n\n"
            )
        
        text += f"📊 Осталось непроверенных: {len(unchecked) - current_index - 1}"
        
        buttons = []
        
        # Кнопки принятия/отклонения только для тех, кто ответил
        if participant.answer:
            buttons.append([
                types.InlineKeyboardButton(
                    text="✅ Принять",
                    callback_data=f"admin_approve_{participant.user_id}_{raffle_date}"
                ),
                types.InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"admin_deny_{participant.user_id}_{raffle_date}"
                )
            ])
        else:
            # Если пользователь не ответил, показываем кнопку "Пропустить" с индексом следующего участника
            next_index = current_index + 1
            if next_index < len(unchecked):
                buttons.append([
                    types.InlineKeyboardButton(
                        text="⏭️ Пропустить (не ответил)",
                        callback_data=f"admin_unchecked_{raffle_date}_{next_index}"
                    )
                ])
            else:
                # Если это последний участник, показываем кнопку "Назад"
                pass
        
        buttons.append([types.InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_raffle_date_{raffle_date}")])
        
        try:
            await cb.message.edit_text(text, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
        except Exception as e:
            # Игнорируем ошибку "message is not modified"
            if "message is not modified" not in str(e).lower():
                raise
        await cb.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при просмотре непроверенных ответов: {e}", exc_info=True)
        await cb.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data.startswith("admin_approve_"))
async def callback_approve(cb: types.CallbackQuery):
    """Принять ответ пользователя через кнопку"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        parts = cb.data.split("_")
        user_id = int(parts[2])
        raffle_date = parts[3] if len(parts) > 3 else None
        
        # Находим розыгрыш для этого пользователя
        async with AsyncSessionLocal() as session:
            if raffle_date:
                result = await session.execute(
                    select(RaffleParticipant).where(
                        and_(
                            RaffleParticipant.user_id == user_id,
                            RaffleParticipant.raffle_date == raffle_date
                        )
                    )
                )
            else:
                # Если дата не указана, берем последний розыгрыш
                result = await session.execute(
                    select(RaffleParticipant).where(
                        RaffleParticipant.user_id == user_id
                    ).order_by(RaffleParticipant.timestamp.desc())
                )
            participant = result.scalar_one_or_none()
            
            if not participant:
                await cb.answer("❌ Участник не найден", show_alert=True)
                return
            
            if participant.is_correct is not None:
                status = "уже принят" if participant.is_correct else "уже отклонен"
                await cb.answer(f"⚠️ Ответ {status}", show_alert=True)
                return
            
            success = await approve_answer(user_id, participant.raffle_date)
            
            if success:
                await cb.answer("✅ Ответ принят!", show_alert=False)
                
                # Если это было из меню непроверенных ответов, показываем следующий
                if raffle_date:
                    unchecked = await get_unchecked_answers(raffle_date)
                    if unchecked:
                        # Показываем следующий непроверенный ответ
                        class FakeCallback:
                            def __init__(self, original_cb, new_data):
                                self.from_user = original_cb.from_user
                                self.message = original_cb.message
                                self.data = new_data
                            def answer(self, *args, **kwargs):
                                pass  # Не вызываем answer дважды
                        
                        fake_cb = FakeCallback(cb, f"admin_unchecked_{raffle_date}")
                        await admin_unchecked_answers(fake_cb)
                        return
                
                # Редактируем сообщение, убирая кнопки
                try:
                    await cb.message.edit_text(
                        cb.message.text + "\n\n✅ <b>Ответ принят</b>",
                        parse_mode="HTML"
                    )
                except:
                    pass
            else:
                await cb.answer("❌ Ошибка при принятии ответа", show_alert=True)
                
    except (ValueError, IndexError) as e:
        await cb.answer(f"❌ Ошибка: {e}", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка при принятии ответа: {e}")
        await cb.answer("❌ Ошибка", show_alert=True)

@dp.message(Command("approve"))
async def cmd_approve(message: types.Message):
    """Принять ответ пользователя (команда для обратной совместимости)"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен.")
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer("❌ Формат: /approve USER_ID")
            return
        
        user_id = int(parts[1])
        
        # Находим последний розыгрыш для этого пользователя
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(RaffleParticipant).where(
                    RaffleParticipant.user_id == user_id
                ).order_by(RaffleParticipant.timestamp.desc())
            )
            participant = result.scalar_one_or_none()
            
            if not participant:
                await message.answer(f"❌ Участник {user_id} не найден")
                return
            
            if participant.is_correct is not None:
                status = "уже принят" if participant.is_correct else "уже отклонен"
                await message.answer(f"⚠️ Ответ пользователя {user_id} {status}")
                return
            
            success = await approve_answer(user_id, participant.raffle_date)
            
            if success:
                await message.answer(f"✅ Ответ пользователя {user_id} принят!")
            else:
                await message.answer(f"❌ Ошибка при принятии ответа")
                
    except (ValueError, IndexError) as e:
        await message.answer(f"❌ Неверный формат: {e}")
    except Exception as e:
        logger.error(f"Ошибка при принятии ответа: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.callback_query(F.data.startswith("admin_deny_"))
async def callback_deny(cb: types.CallbackQuery):
    """Отклонить ответ пользователя через кнопку"""
    if not is_admin(cb.from_user.id):
        await cb.answer("Доступ запрещен", show_alert=True)
        return
    
    try:
        parts = cb.data.split("_")
        user_id = int(parts[2])
        raffle_date = parts[3] if len(parts) > 3 else None
        
        # Находим розыгрыш для этого пользователя
        async with AsyncSessionLocal() as session:
            if raffle_date:
                result = await session.execute(
                    select(RaffleParticipant).where(
                        and_(
                            RaffleParticipant.user_id == user_id,
                            RaffleParticipant.raffle_date == raffle_date
                        )
                    )
                )
            else:
                # Если дата не указана, берем последний розыгрыш
                result = await session.execute(
                    select(RaffleParticipant).where(
                        RaffleParticipant.user_id == user_id
                    ).order_by(RaffleParticipant.timestamp.desc())
                )
            participant = result.scalar_one_or_none()
            
            if not participant:
                await cb.answer("❌ Участник не найден", show_alert=True)
                return
            
            if participant.is_correct is not None:
                status = "уже принят" if participant.is_correct else "уже отклонен"
                await cb.answer(f"⚠️ Ответ {status}", show_alert=True)
                return
            
            success = await deny_answer(user_id, participant.raffle_date)
            
            if success:
                await cb.answer("❌ Ответ отклонен", show_alert=False)
                
                # Если это было из меню непроверенных ответов, показываем следующий
                if raffle_date:
                    unchecked = await get_unchecked_answers(raffle_date)
                    if unchecked:
                        # Показываем следующий непроверенный ответ
                        class FakeCallback:
                            def __init__(self, original_cb, new_data):
                                self.from_user = original_cb.from_user
                                self.message = original_cb.message
                                self.data = new_data
                            def answer(self, *args, **kwargs):
                                pass  # Не вызываем answer дважды
                        
                        fake_cb = FakeCallback(cb, f"admin_unchecked_{raffle_date}")
                        await admin_unchecked_answers(fake_cb)
                        return
                
                # Редактируем сообщение, убирая кнопки
                try:
                    await cb.message.edit_text(
                        cb.message.text + "\n\n❌ <b>Ответ отклонен</b>",
                        parse_mode="HTML"
                    )
                except:
                    pass
            else:
                await cb.answer("❌ Ошибка при отклонении ответа", show_alert=True)
                
    except (ValueError, IndexError) as e:
        await cb.answer(f"❌ Ошибка: {e}", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка при отклонении ответа: {e}")
        await cb.answer("❌ Ошибка", show_alert=True)

@dp.message(Command("deny"))
async def cmd_deny(message: types.Message):
    """Отклонить ответ пользователя (команда для обратной совместимости)"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещен.")
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer("❌ Формат: /deny USER_ID")
            return
        
        user_id = int(parts[1])
        
        # Находим последний розыгрыш для этого пользователя
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(RaffleParticipant).where(
                    RaffleParticipant.user_id == user_id
                ).order_by(RaffleParticipant.timestamp.desc())
            )
            participant = result.scalar_one_or_none()
            
            if not participant:
                await message.answer(f"❌ Участник {user_id} не найден")
                return
            
            if participant.is_correct is not None:
                status = "уже принят" if participant.is_correct else "уже отклонен"
                await message.answer(f"⚠️ Ответ пользователя {user_id} {status}")
                return
            
            success = await deny_answer(user_id, participant.raffle_date)
            
            if success:
                await message.answer(f"❌ Ответ пользователя {user_id} отклонен")
            else:
                await message.answer(f"❌ Ошибка при отклонении ответа")
                
    except (ValueError, IndexError) as e:
        await message.answer(f"❌ Неверный формат: {e}")
    except Exception as e:
        logger.error(f"Ошибка при отклонении ответа: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@dp.message()
async def handle_unknown(message: types.Message):
    """Обработчик неизвестных команд и сообщений"""
    # Сбрасываем флаг режима вопроса при любой команде
    if message.text and message.text.startswith("/"):
        user_question_mode.pop(message.from_user.id, None)
        admin_reply_mode.pop(message.from_user.id, None)  # Сбрасываем и режим ответа
        await message.answer(
            "Неизвестная команда. Используй /help для списка доступных команд."
        )
        return
    
    # Если админ в режиме ответа пользователю - отправляем ответ
    if is_admin(message.from_user.id) and message.from_user.id in admin_reply_mode:
        user_id_to_reply = admin_reply_mode[message.from_user.id]
        
        try:
            has_text = bool(message.text or (message.caption and message.caption.strip()))
            has_photo = bool(message.photo)
            
            # Отправляем ответ пользователю
            if has_photo and has_text:
                # Фото с текстом
                text_content = message.text or message.caption
                success = await safe_send_photo(
                    bot,
                    user_id_to_reply,
                    message.photo[-1].file_id,
                    caption=text_content
                )
            elif has_photo:
                # Только фото
                success = await safe_send_photo(
                    bot,
                    user_id_to_reply,
                    message.photo[-1].file_id
                )
            elif has_text:
                # Только текст
                text_content = message.text or message.caption
                success = await safe_send_message(bot, user_id_to_reply, text_content)
            else:
                await message.answer("❌ Отправь текст или фото с текстом")
                return
            
            if success:
                await message.answer(f"✅ Ответ отправлен пользователю {user_id_to_reply}")
                logger.info(f"Админ {message.from_user.id} отправил ответ пользователю {user_id_to_reply}")
                # Сбрасываем режим ответа после успешной отправки
                admin_reply_mode.pop(message.from_user.id, None)
            else:
                await message.answer(f"❌ Не удалось отправить ответ пользователю {user_id_to_reply}")
        
        except Exception as e:
            logger.error(f"Ошибка при отправке ответа пользователю: {e}")
            await message.answer(f"❌ Ошибка при отправке ответа: {e}")
        
        return
    
    # Если пользователь участвует в розыгрыше - обрабатываем ответ
    if message.from_user.id in raffle_participants:
        raffle_date = raffle_participants[message.from_user.id]
        
        # Проверяем, активен ли розыгрыш
        if not await is_raffle_active(raffle_date):
            await message.answer("⛔ Розыгрыш остановлен администратором. Твой ответ не может быть принят.")
            raffle_participants.pop(message.from_user.id, None)
            return
        
        # Проверяем, не истекло ли время (15 минут)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(RaffleParticipant).where(
                    and_(
                        RaffleParticipant.user_id == message.from_user.id,
                        RaffleParticipant.raffle_date == raffle_date
                    )
                )
            )
            participant = result.scalar_one_or_none()
            
            if not participant:
                raffle_participants.pop(message.from_user.id, None)
                return
            
            # Проверяем, не ответил ли уже
            if participant.answer is not None:
                await message.answer("⚠️ Ты уже ответил на вопрос. Ответ можно отправить только один раз.")
                return
            
            # Проверяем время (15 минут с момента получения вопроса, используем МСК)
            from raffle import MOSCOW_TZ
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
            # Используем >= вместо > для более строгой проверки
            if time_since_question >= RAFFLE_ANSWER_TIME:
                await message.answer(f"⏰ Время на ответ истекло. У тебя было {RAFFLE_ANSWER_TIME} минут.")
                raffle_participants.pop(message.from_user.id, None)
                logger.info(
                    f"Время истекло для пользователя {message.from_user.id}: "
                    f"прошло {time_since_question:.2f} минут >= {RAFFLE_ANSWER_TIME} минут"
                )
                return
        
        # Сохраняем ответ
        answer_text = message.text or (message.caption if message.caption else "")
        if not answer_text:
            await message.answer("❌ Отправь текстовый ответ на вопрос.")
            return
        
        success = await save_user_answer(message.from_user.id, raffle_date, answer_text)
        
        if success:
            await message.answer("✅ Твой ответ принят! Ожидай проверки.")
            # Удаляем из списка ожидающих ответа (это отменит задачу проверки таймаута, если она еще не выполнилась)
            raffle_participants.pop(message.from_user.id, None)
        else:
            await message.answer("❌ Произошла ошибка при сохранении ответа.")
        
        return
    
    # Если пользователь в режиме вопроса - пересылаем сообщение администраторам
    if user_question_mode.get(message.from_user.id):
        # Формируем информацию о пользователе
        user_info = (
            f"👤 <b>Вопрос от пользователя:</b>\n"
            f"ID: {message.from_user.id}\n"
            f"Имя: {message.from_user.first_name or 'Не указано'}\n"
            f"Username: @{message.from_user.username or 'нет'}\n\n"
        )
        
        # Проверяем тип сообщения
        has_text = bool(message.text or (message.caption and message.caption.strip()))
        has_photo = bool(message.photo)
        
        # Если только фото без текста - просим добавить текст
        if has_photo and not has_text:
            await message.answer(
                "❌ Пожалуйста, напиши текст к фото и отправь фото с текстом вместе. "
                "Мы не можем обработать только фото без описания."
            )
            # Не сбрасываем флаг, пользователь может попробовать еще раз
            return
        
        # Создаем кнопку "Быстро ответить" с ID пользователя
        reply_keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(
                text="💬 Быстро ответить",
                callback_data=f"quick_reply_{message.from_user.id}"
            )]
        ])
        
        # Пересылаем сообщение всем администраторам
        if ADMIN_IDS:
            forwarded_count = 0
            for admin_id in ADMIN_IDS:
                try:
                    success = False
                    # Если есть текст и фото - отправляем фото с текстом
                    if has_photo and has_text:
                        text_content = message.text or message.caption
                        full_caption = f"{user_info}💬 <b>Сообщение:</b>\n{text_content}"
                        success = await safe_send_photo(
                            bot, 
                            admin_id, 
                            message.photo[-1].file_id,
                            caption=full_caption,
                            parse_mode="HTML",
                            reply_markup=reply_keyboard
                        )
                    # Если только текст - отправляем только текст
                    elif has_text:
                        text_content = message.text or message.caption
                        full_message = f"{user_info}💬 <b>Сообщение:</b>\n{text_content}"
                        success = await safe_send_message(bot, admin_id, full_message, parse_mode="HTML", reply_markup=reply_keyboard)
                    else:
                        # Другие типы медиа (видео, документ) - не обрабатываем специально
                        caption = message.caption or ""
                        if caption:
                            full_message = f"{user_info}💬 <b>Сообщение:</b>\n{caption}"
                            success = await safe_send_message(bot, admin_id, full_message, parse_mode="HTML", reply_markup=reply_keyboard)
                        else:
                            # Если нет текста и это не фото - игнорируем
                            continue
                    
                    if success:
                        forwarded_count += 1
                except Exception as e:
                    logger.error(f"Ошибка при пересылке сообщения администратору {admin_id}: {e}")
            
            # Подтверждаем пользователю, что сообщение отправлено
            if forwarded_count > 0:
                await message.answer("✅ Спасибо! Мы получили твое сообщение и обязательно прочитаем его.")
            else:
                await message.answer("❌ Произошла ошибка при отправке сообщения. Попробуй позже.")
        
        # Сбрасываем флаг после отправки
        user_question_mode.pop(message.from_user.id, None)

# ----------------- Main -----------------
async def setup_bot_commands():
    """Настройка команд бота (кнопки меню)"""
    # Команды для обычных пользователей (без админских)
    user_commands = [
        BotCommand(command="start", description="🚀 Начать работу с ботом"),
        BotCommand(command="change_zodiac", description="🔄 Изменить знак зодиака"),
        BotCommand(command="my_info", description="👤 Моя информация"),
        BotCommand(command="unsubscribe", description="❌ Отписаться от рассылки"),
        BotCommand(command="question", description="💬 Задать вопрос"),
        BotCommand(command="help", description="ℹ️ Помощь и справка"),
    ]
    
    # Устанавливаем команды для всех пользователей (только пользовательские, без админских)
    await bot.set_my_commands(user_commands)
    logger.info("Пользовательские команды установлены для всех")
    
    # Добавляем админ-команды ТОЛЬКО для админов через scope
    if ADMIN_IDS:
        try:
            from aiogram.types import BotCommandScopeChat
            # Админские команды включают все пользовательские + админские
            admin_commands = user_commands + [
                BotCommand(command="admin", description="🔐 Админ-панель"),
                BotCommand(command="stats", description="📊 Статистика"),
                BotCommand(command="reply", description="💬 Ответить пользователю"),
            ]
            for admin_id in ADMIN_IDS:
                try:
                    await bot.set_my_commands(
                        admin_commands, 
                        scope=BotCommandScopeChat(chat_id=admin_id)
                    )
                    logger.info(f"Админ-команды настроены для администратора {admin_id}")
                except Exception as e:
                    logger.warning(f"Не удалось установить админ-команды для {admin_id}: {e}")
        except Exception as e:
            logger.warning(f"Ошибка при установке админ-команд: {e}")
    logger.info("Команды бота настроены (админские команды скрыты от обычных пользователей)")

# Хранилище для активных квизов: {user_id: quiz_date}
active_quizzes = {}


@dp.callback_query(F.data.startswith("quiz_ready_"))
async def handle_quiz_ready(cb: types.CallbackQuery):
    """Обработчик нажатия кнопки 'Я готов' для квиза"""
    try:
        quiz_date = cb.data.split("_")[-1]
        user_id = cb.from_user.id
        
        # Проверяем, не истекло ли время (6 часов)
        moscow_now = datetime.now(QUIZ_MOSCOW_TZ)
        
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
            
            if not participant or not participant.announcement_time:
                await cb.answer("❌ Ошибка: объявление не найдено", show_alert=True)
                return
            
            # Проверяем время
            announcement_utc = participant.announcement_time.replace(tzinfo=timezone.utc)
            announcement_moscow = announcement_utc.astimezone(QUIZ_MOSCOW_TZ)
            time_passed = (moscow_now - announcement_moscow).total_seconds() / 3600  # в часах
            
            if time_passed >= QUIZ_PARTICIPATION_WINDOW:
                await cb.answer("⏰ Время на участие истекло. У тебя было 6 часов.", show_alert=True)
                return
            
            # Проверяем, не начал ли уже квиз
            if participant.started_at:
                await cb.answer("⚠️ Ты уже начал этот квиз", show_alert=True)
                return
            
            # Запускаем квиз
            started_at_utc = moscow_now.astimezone(timezone.utc).replace(tzinfo=None)
            participant.started_at = started_at_utc
            participant.current_question = 1
            participant.answers = "{}"  # Начинаем с пустого JSON
            await session.commit()
        
        # Редактируем сообщение с объявлением
        try:
            await cb.message.edit_text(
                "✅ Квиз начат! Отвечай на вопросы ниже.",
                reply_markup=None
            )
        except:
            pass
        
        await cb.answer()
        
        # Запускаем первый вопрос (без message_id, отправим новое сообщение)
        await start_quiz_question(bot, user_id, quiz_date, 1, None)
        
        # Запускаем таймер на 15 минут
        task = asyncio.create_task(check_quiz_timeout(bot, user_id, quiz_date))
        quiz_timeout_tasks[user_id] = task
        
    except Exception as e:
        logger.error(f"Ошибка при обработке 'Я готов' для квиза: {e}", exc_info=True)
        await cb.answer("❌ Ошибка при запуске квиза", show_alert=True)


async def start_quiz_question(bot, user_id: int, quiz_date: str, question_num: int, question_message_id: int = None):
    """Запускает вопрос квиза для пользователя"""
    try:
        question = get_quiz_question(question_num, quiz_date)
        if not question:
            await safe_send_message(bot, user_id, "❌ Ошибка: вопрос не найден")
            return
        
        # Формируем текст вопроса
        total_questions = get_total_questions(quiz_date)
        question_text = f"❓ <b>Вопрос {question_num}/{total_questions}</b>\n\n{question['question']}"
        
        # Создаем кнопки с вариантами ответов
        buttons = []
        for option_key, option_text in question['options'].items():
            buttons.append([types.InlineKeyboardButton(
                text=f"{option_key}. {option_text}",
                callback_data=f"quiz_answer_{quiz_date}_{question_num}_{option_key}"
            )])
        
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
        
        # Если есть message_id - редактируем сообщение, иначе отправляем новое
        if question_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=user_id,
                    message_id=question_message_id,
                    text=question_text,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
            except Exception as e:
                logger.warning(f"Не удалось отредактировать сообщение {question_message_id}, отправляем новое: {e}")
                message = await bot.send_message(user_id, question_text, parse_mode="HTML", reply_markup=keyboard)
                # Обновляем message_id в БД
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
                        await session.commit()
        else:
            message = await bot.send_message(user_id, question_text, parse_mode="HTML", reply_markup=keyboard)
            # Сохраняем message_id в БД
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
                    await session.commit()
        
    except Exception as e:
        logger.error(f"Ошибка при запуске вопроса квиза: {e}", exc_info=True)


@dp.callback_query(F.data.startswith("quiz_answer_"))
async def handle_quiz_answer(cb: types.CallbackQuery):
    """Обработчик ответа на вопрос квиза"""
    try:
        parts = cb.data.split("_")
        quiz_date = parts[2]
        question_num = int(parts[3])
        answer = parts[4]
        user_id = cb.from_user.id
        
        # Получаем вопрос
        question = get_quiz_question(question_num, quiz_date)
        if not question:
            await cb.answer("❌ Вопрос не найден", show_alert=True)
            return
        
        # Проверяем, правильный ли ответ
        is_correct = question['correct_answer'] == answer
        
        # Сохраняем ответ
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
                await cb.answer("❌ Ошибка: участник не найден", show_alert=True)
                return
            
            # Проверяем, не завершен ли квиз (например, по таймауту)
            if participant.completed:
                await cb.answer("⏰ Время на прохождение квиза истекло.", show_alert=True)
                return
            
            # Обновляем ответы
            import json
            answers = json.loads(participant.answers or "{}")
            answers[str(question_num)] = answer
            participant.answers = json.dumps(answers)
            
            # Переходим к следующему вопросу
            total_questions = get_total_questions(quiz_date)
            if question_num < total_questions:
                participant.current_question = question_num + 1
                await session.commit()
                
                # Переходим к следующему вопросу (редактируем то же сообщение)
                await start_quiz_question(bot, user_id, quiz_date, question_num + 1, participant.message_id)
            else:
                # Квиз завершен
                participant.completed = True
                participant.current_question = 0
                await session.commit()
                
                # Отменяем таймер
                if user_id in quiz_timeout_tasks:
                    quiz_timeout_tasks[user_id].cancel()
                    quiz_timeout_tasks.pop(user_id, None)
                
                # Подсчитываем правильные ответы для отображения
                quiz_data = load_quiz(quiz_date)
                total_questions = len(quiz_data) if quiz_data else 0
                correct_count = 0
                
                for q_num_str, user_answer in answers.items():
                    q_num = int(q_num_str)
                    q = quiz_data.get(str(q_num)) if quiz_data else None
                    if q and q['correct_answer'] == user_answer:
                        correct_count += 1
                
                # Редактируем сообщение с результатами (убираем клавиатуру)
                result_text = (
                    f"🎯 <b>Квиз завершен!</b>\n\n"
                    f"📊 Ты ответил правильно на <b>{correct_count} из {total_questions}</b> вопросов.\n\n"
                )
                
                if correct_count == total_questions:
                    result_text += "🌟 <b>Отлично! Все ответы верные!</b>"
                elif correct_count >= QUIZ_MIN_CORRECT_ANSWERS:
                    result_text += f"✅ <b>Отличный результат!</b> Ты получил билетик!"
                else:
                    result_text += "Не расстраивайся! В следующем квизе все получится!"
                
                try:
                    await cb.bot.edit_message_text(
                        chat_id=user_id,
                        message_id=participant.message_id,
                        text=result_text,
                        parse_mode="HTML",
                        reply_markup=None  # Убираем клавиатуру
                    )
                except Exception as e:
                    logger.error(f"Ошибка при редактировании сообщения с результатами квиза: {e}", exc_info=True)
                
                # Подсчитываем результаты и обрабатываем награды
                await finish_quiz(bot, user_id, quiz_date, answers, question)
        
    except Exception as e:
        logger.error(f"Ошибка при обработке ответа на вопрос квиза: {e}", exc_info=True)
        await cb.answer("❌ Ошибка при обработке ответа", show_alert=True)


async def finish_quiz(bot, user_id: int, quiz_date: str, answers: dict, last_question: dict):
    """Завершает квиз и обрабатывает результаты"""
    try:
        # Загружаем все вопросы квиза
        quiz_data = load_quiz(quiz_date)
        if not quiz_data:
            logger.error(f"Не удалось загрузить квиз для даты {quiz_date}")
            return
        
        total_questions = len(quiz_data)
        correct_count = 0
        wrong_answers = []  # Список неправильных ответов: [(номер, вопрос, ответ пользователя, правильный ответ, текст правильного ответа)]
        
        # Подсчитываем правильные ответы и собираем неправильные
        for q_num_str, user_answer in answers.items():
            q_num = int(q_num_str)
            question = quiz_data.get(str(q_num))
            if question:
                if question['correct_answer'] == user_answer:
                    correct_count += 1
                else:
                    # Неправильный ответ - сохраняем информацию
                    correct_answer_key = question['correct_answer']
                    correct_answer_text = question['options'].get(correct_answer_key, correct_answer_key)
                    user_answer_text = question['options'].get(user_answer, user_answer)
                    wrong_answers.append((
                        q_num,
                        question['question'],
                        user_answer_text,
                        correct_answer_text
                    ))
        
        # Получаем информацию о пользователе
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            username = user.username if user else None
        
        # Сохраняем результат
        async with AsyncSessionLocal() as session:
            if correct_count >= QUIZ_MIN_CORRECT_ANSWERS:
                # >= 3/5 - выдаем билетик
                ticket_number = await get_next_ticket_number()
                
                # Отправляем картинку с билетиком
                ticket_path = Path("data/билет.png")
                if ticket_path.exists():
                    caption = f"№{ticket_number}"
                    try:
                        # Открываем файл и отправляем через InputFile
                        photo_file = FSInputFile(str(ticket_path.absolute()))
                        photo_sent = await safe_send_photo(bot, user_id, photo_file, caption=caption)
                        if not photo_sent:
                            # Если не удалось отправить фото, отправляем текстовое сообщение
                            logger.warning(f"Не удалось отправить фото билетика пользователю {user_id}, отправляем текст")
                            await safe_send_message(
                                bot, user_id,
                                f"№{ticket_number}"
                            )
                    except Exception as e:
                        logger.error(f"Ошибка при отправке фото билетика пользователю {user_id}: {e}", exc_info=True)
                        await safe_send_message(
                            bot, user_id,
                            f"№{ticket_number}"
                        )
                else:
                    logger.warning(f"Файл билет.png не найден по пути {ticket_path.absolute()}")
                    await safe_send_message(
                        bot, user_id,
                        f"№{ticket_number}"
                    )
                
                # Уведомляем админов
                admin_message = (
                    f"🎯 Пользователь с ID {user_id}"
                    + (f" @{username}" if username else "")
                    + f" ответил на {correct_count}/{total_questions} вопросов правильно "
                    f"и получил лотерейный билетик №{ticket_number}"
                )
                for admin_id in ADMIN_IDS:
                    await safe_send_message(bot, admin_id, admin_message)
                
                result = QuizResult(
                    user_id=user_id,
                    username=username,
                    quiz_date=quiz_date,
                    correct_answers=correct_count,
                    total_questions=total_questions,
                    ticket_number=ticket_number,
                    completed_at=datetime.utcnow()
                )
            else:
                # Меньше 3 правильных ответов - отправляем детальное сообщение
                if wrong_answers:
                    message_text = "❌ К сожалению, ты ошибся в нескольких вопросах:\n\n"
                    
                    for q_num, question_text, user_answer_text, correct_answer_text in wrong_answers:
                        message_text += (
                            f"<b>№{q_num}</b> | {question_text}\n"
                            f"Твой ответ: {user_answer_text}\n"
                            f"Правильный ответ: {correct_answer_text}\n\n"
                        )
                    
                    message_text += "💪 Уверен, в следующий раз получится ответить без ошибок!"
                    await safe_send_message(bot, user_id, message_text, parse_mode="HTML")
                
                # Уведомляем админов
                admin_message = (
                    f"📊 Пользователь с ID {user_id}"
                    + (f" @{username}" if username else "")
                    + f" прошел квиз, но ответил на {correct_count}/{total_questions} правильных вопросов"
                )
                for admin_id in ADMIN_IDS:
                    await safe_send_message(bot, admin_id, admin_message)
                
                result = QuizResult(
                    user_id=user_id,
                    username=username,
                    quiz_date=quiz_date,
                    correct_answers=correct_count,
                    total_questions=total_questions,
                    ticket_number=None,  # Прочерк
                    completed_at=datetime.utcnow()
                )
            
            session.add(result)
            await session.commit()
        
        logger.info(f"Квиз завершен для пользователя {user_id}: {correct_count}/{total_questions}")
        
    except Exception as e:
        logger.error(f"Ошибка при завершении квиза: {e}", exc_info=True)


async def main():
    """Главная функция запуска бота"""
    try:
        await init_db()
        # Выполняем безопасную миграцию для квизов
        try:
            from safe_migrate_quiz import migrate_quiz_tables
            await migrate_quiz_tables()
            logger.info("✅ Миграция квизов выполнена")
        except Exception as e:
            logger.warning(f"Ошибка при миграции квизов (возможно, таблицы уже существуют): {e}")
        # Выполняем безопасную миграцию для исправления структуры БД
        try:
            from safe_migrate_raffle import safe_migrate
            await safe_migrate()
        except Exception as e:
            logger.warning(f"Не удалось выполнить миграцию (возможно, уже выполнена): {e}")
        # Настраиваем команды меню
        await setup_bot_commands()
        # Передаем экземпляр бота в scheduler
        from scheduler import set_bot
        set_bot(bot)
        start_scheduler()
        logger.info("Бот запущен и готов к работе")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки, завершаем работу...")
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске бота: {e}", exc_info=True)
        raise
    finally:
        logger.info("Закрываем соединения...")
        # Останавливаем планировщик
        try:
            stop_scheduler()
        except Exception as e:
            logger.warning(f"Ошибка при остановке планировщика: {e}")
        # Закрываем FSM storage если он есть
        try:
            if hasattr(dp, 'fsm') and hasattr(dp.fsm, 'storage') and dp.fsm.storage:
                await dp.fsm.storage.close()
        except Exception as e:
            logger.warning(f"Ошибка при закрытии FSM storage: {e}")
        # Закрываем сессию бота
        await bot.session.close()
        logger.info("Бот остановлен")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
