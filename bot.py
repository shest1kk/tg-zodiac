import asyncio
import logging
from datetime import datetime, timezone, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import BotCommand
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select
from database import AsyncSessionLocal, init_db, User
from config import TG_TOKEN, DAILY_HOUR, DAILY_MINUTE, logger, ZODIAC_NAMES, ADMIN_ID, ADMIN_IDS
from scheduler import start_scheduler, stop_scheduler, get_day_number, get_today_prediction, load_predictions
from resilience import safe_send_message, safe_send_photo, RATE_LIMIT_DELAY

bot = Bot(TG_TOKEN)
dp = Dispatcher()

# Хранилище для отслеживания режима отправки вопроса
user_question_mode = {}

# Хранилище для режима ответа админа пользователю (admin_id -> user_id)
admin_reply_mode = {}

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

async def main():
    """Главная функция запуска бота"""
    try:
        await init_db()
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
