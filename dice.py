"""
Модуль для управления Dice (игральный кубик)
"""
import json
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, List
from aiogram import types
from sqlalchemy import select, and_
from sqlalchemy.exc import SQLAlchemyError
from database import AsyncSessionLocal, User, RaffleParticipant
from resilience import safe_send_message, safe_send_message_with_result, safe_edit_message_text
from raffle import get_next_raffle_ticket_number
from quiz import _ticket_number_lock

logger = logging.getLogger(__name__)

# Московское время (UTC+3)
MOSCOW_TZ = timezone(timedelta(hours=3))

# Путь к файлу с событиями dice
DICE_JSON_PATH = Path("data/dice.json")

# Словарь для хранения ожидаемых ответов пользователей: {user_id: {"dice_id": str, "expected_number": int, "message_id": int}}
dice_waiting_responses = {}


def load_all_dice_data() -> Optional[Dict]:
    """Загружает все данные dice из dice.json"""
    dice_path = DICE_JSON_PATH
    if not dice_path.exists():
        logger.debug("Файл dice.json не найден, создаем пустую структуру")
        return {"dice_events": {}}
    
    try:
        with open(dice_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Ошибка при загрузке dice.json: {e}")
        return None


def save_dice_data(dice_data: Dict) -> bool:
    """Сохраняет данные dice в dice.json"""
    dice_path = DICE_JSON_PATH
    try:
        dice_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dice_path, "w", encoding="utf-8") as f:
            json.dump(dice_data, f, ensure_ascii=False, indent=4)
        logger.info(f"Dice данные успешно сохранены в {dice_path}")
        return True
    except (IOError, json.JSONEncodeError) as e:
        logger.error(f"Ошибка при сохранении dice.json: {e}")
        return False


def get_all_dice_events() -> List[str]:
    """Получает список всех ID событий dice"""
    all_data = load_all_dice_data()
    if not all_data or "dice_events" not in all_data:
        return []
    return list(all_data["dice_events"].keys())


def get_dice_event(dice_id: str) -> Optional[Dict]:
    """Получает событие dice по ID"""
    all_data = load_all_dice_data()
    if not all_data or "dice_events" not in all_data:
        return None
    return all_data["dice_events"].get(dice_id)


def get_dice_start_datetime_moscow(dice_id: str) -> Optional[datetime]:
    """Получает дату и время старта события dice в МСК"""
    event = get_dice_event(dice_id)
    if not event or "starts_at" not in event:
        return None
    
    try:
        starts_at_str = event["starts_at"]
        if isinstance(starts_at_str, str):
            dt = datetime.fromisoformat(starts_at_str.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=MOSCOW_TZ)
            else:
                dt = dt.astimezone(MOSCOW_TZ)
            return dt
    except Exception as e:
        logger.warning(f"Ошибка при парсинге starts_at для dice {dice_id}: {e}")
        return None


def create_dice_event(dice_id: str, starts_at_local: str, title: str) -> Dict:
    """Создает новое событие dice
    
    Args:
        dice_id: Уникальный ID события
        starts_at_local: Дата и время старта в формате YYYY-MM-DDTHH:MM (МСК)
        title: Заголовок события
        
    Returns:
        {"success": bool, "error": str или None}
    """
    try:
        starts_at = datetime.fromisoformat(starts_at_local.strip())
        if starts_at.tzinfo is not None:
            starts_at = starts_at.astimezone(MOSCOW_TZ).replace(tzinfo=MOSCOW_TZ)
        else:
            starts_at = starts_at.replace(tzinfo=MOSCOW_TZ)
        
        all_data = load_all_dice_data()
        if not all_data:
            all_data = {"dice_events": {}}
        if "dice_events" not in all_data:
            all_data["dice_events"] = {}
        
        if dice_id in all_data["dice_events"]:
            return {"success": False, "error": f"Событие с ID {dice_id} уже существует"}
        
        all_data["dice_events"][dice_id] = {
            "dice_id": dice_id,
            "title": title.strip(),
            "starts_at": starts_at.isoformat(),
            "enabled": True
        }
        
        if save_dice_data(all_data):
            return {"success": True, "dice_id": dice_id}
        else:
            return {"success": False, "error": "Не удалось сохранить dice.json"}
            
    except Exception as e:
        logger.error(f"Ошибка при создании события dice: {e}")
        return {"success": False, "error": str(e)}


def update_dice_event(dice_id: str, starts_at_local: str = None, title: str = None, enabled: bool = None) -> Dict:
    """Обновляет событие dice"""
    try:
        all_data = load_all_dice_data()
        if not all_data or "dice_events" not in all_data or dice_id not in all_data["dice_events"]:
            return {"success": False, "error": "Событие не найдено"}
        
        event = all_data["dice_events"][dice_id]
        
        if starts_at_local is not None:
            starts_at = datetime.fromisoformat(starts_at_local.strip())
            if starts_at.tzinfo is not None:
                starts_at = starts_at.astimezone(MOSCOW_TZ).replace(tzinfo=MOSCOW_TZ)
            else:
                starts_at = starts_at.replace(tzinfo=MOSCOW_TZ)
            event["starts_at"] = starts_at.isoformat()
        
        if title is not None:
            event["title"] = title.strip()
        
        if enabled is not None:
            event["enabled"] = enabled
        
        if save_dice_data(all_data):
            return {"success": True}
        else:
            return {"success": False, "error": "Не удалось сохранить dice.json"}
            
    except Exception as e:
        logger.error(f"Ошибка при обновлении события dice: {e}")
        return {"success": False, "error": str(e)}


def delete_dice_event(dice_id: str) -> Dict:
    """Удаляет событие dice"""
    try:
        all_data = load_all_dice_data()
        if not all_data or "dice_events" not in all_data or dice_id not in all_data["dice_events"]:
            return {"success": False, "error": "Событие не найдено"}
        
        del all_data["dice_events"][dice_id]
        
        if save_dice_data(all_data):
            return {"success": True}
        else:
            return {"success": False, "error": "Не удалось сохранить dice.json"}
            
    except Exception as e:
        logger.error(f"Ошибка при удалении события dice: {e}")
        return {"success": False, "error": str(e)}


async def send_dice_announcement(bot, user_id: int, dice_id: str) -> Optional[int]:
    """Отправляет объявление о dice пользователю
    
    Returns:
        message_id если успешно, None в противном случае
    """
    try:
        event = get_dice_event(dice_id)
        if not event:
            logger.error(f"Событие dice {dice_id} не найдено")
            return None
        
        if not event.get("enabled", True):
            logger.debug(f"Событие dice {dice_id} отключено")
            return None
        
        title = event.get("title", "")
        title_text = f"<b>{title}</b>\n\n" if title else ""
        
        announcement_text = (
            f"{title_text}"
            f"🎲 <b>Давай проверим твою удачу?</b>"
        )
        
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(
                text="🎲 Давай",
                callback_data=f"dice_start_{dice_id}"
            )]
        ])
        
        message = await safe_send_message_with_result(
            bot,
            user_id,
            announcement_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        
        return message.message_id if message else None
        
    except Exception as e:
        logger.error(f"Ошибка при отправке объявления о dice пользователю {user_id}: {e}")
        return None


async def handle_dice_start(bot, user_id: int, dice_id: str, message_id: int) -> bool:
    """Обрабатывает нажатие кнопки "Давай" в объявлении dice
    
    Returns:
        True если успешно, False в противном случае
    """
    try:
        event = get_dice_event(dice_id)
        if not event:
            logger.error(f"Событие dice {dice_id} не найдено")
            return False
        
        # Редактируем сообщение
        new_text = "🎲 <b>Хорошо, тогда загадай число от 1 до 6 и напиши его в чат</b>"
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])  # Убираем кнопку
        
        edit_success = await safe_edit_message_text(
            bot,
            chat_id=user_id,
            message_id=message_id,
            text=new_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        
        if not edit_success:
            # Если не удалось отредактировать, отправляем новое сообщение
            await safe_send_message(bot, user_id, new_text, parse_mode="HTML")
        
        # Сохраняем информацию о том, что пользователь ожидает ответ
        # Используем message_id для отслеживания
        dice_waiting_responses[user_id] = {
            "dice_id": dice_id,
            "message_id": message_id,
            "timestamp": datetime.now(MOSCOW_TZ)
        }
        
        logger.info(f"Пользователь {user_id} начал dice {dice_id}")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при обработке начала dice для пользователя {user_id}: {e}")
        return False


async def handle_dice_number(bot, user_id: int, number: int) -> bool:
    """Обрабатывает число, загаданное пользователем, и отправляет dice
    
    Returns:
        True если успешно, False в противном случае
    """
    try:
        # Проверяем, ожидает ли пользователь ответа
        if user_id not in dice_waiting_responses:
            return False
        
        user_data = dice_waiting_responses[user_id]
        dice_id = user_data["dice_id"]
        message_id = user_data.get("message_id")
        
        # Проверяем, что число от 1 до 6
        if number < 1 or number > 6:
            await safe_send_message(bot, user_id, "❌ Пожалуйста, загадай число от 1 до 6")
            return False
        
        # ВАЖНО: Проверяем, не загадал ли пользователь уже число и не отправили ли мы уже dice
        # Если dice_message_id уже есть, значит dice уже был отправлен - просто игнорируем повторный ввод
        if user_data.get("expected_number") is not None and user_data.get("dice_message_id") is not None:
            await safe_send_message(bot, user_id, "⏳ Ты уже загадал число и ждешь результата кубика. Дождись результата!")
            return False
        
        # Сохраняем информацию о том, что пользователь загадал число
        # Это будет использовано в обработчике результата dice
        dice_waiting_responses[user_id] = {
            "dice_id": dice_id,
            "expected_number": number,
            "message_id": message_id,
            "timestamp": datetime.now(MOSCOW_TZ)
        }
        
        # Отправляем dice (эмодзи кубика)
        # ВАЖНО: send_dice сразу возвращает результат в dice.value!
        # Анимация видна только пользователю, но бот получает значение мгновенно
        try:
            dice_message = await bot.send_dice(user_id, emoji="🎲")
            if not dice_message or not dice_message.dice:
                logger.warning(f"Не удалось получить dice от send_dice для пользователя {user_id}")
                dice_waiting_responses.pop(user_id, None)
                await safe_send_message(bot, user_id, "❌ Ошибка при отправке кубика. Попробуй еще раз.")
                return False
            
            dice_value = dice_message.dice.value
            dice_message_id = dice_message.message_id
            
            logger.info(f"✅ Отправлен dice пользователю {user_id}: message_id={dice_message_id}, загаданное число={number}, выпало={dice_value}")
            
            # Ждем, чтобы анимация кубика прошла полностью (обычно 2-3 секунды)
            await asyncio.sleep(3.5)
            
            # СРАВНИВАЕМ: загаданное число vs результат dice
            if dice_value == number:
                # ПОБЕДА! Выдаем билетик
                await handle_dice_result(bot, user_id, dice_value, dice_message_id, dice_id)
            else:
                # Не совпало
                message_text = (
                    f"😔 <b>Не повезло</b>\n\n"
                    f"Ты загадал число <b>{number}</b>, а выпало <b>{dice_value}</b>.\n"
                    f"Попробуй в следующий раз!"
                )
                await safe_send_message(bot, user_id, message_text, parse_mode="HTML")
                logger.info(f"Пользователь {user_id} не угадал: загадал {number}, выпало {dice_value}")
            
            # Удаляем из ожидающих после обработки
            dice_waiting_responses.pop(user_id, None)
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при отправке dice пользователю {user_id}: {e}", exc_info=True)
            # Удаляем из ожидающих, если не удалось отправить
            dice_waiting_responses.pop(user_id, None)
            await safe_send_message(bot, user_id, "❌ Ошибка при отправке кубика. Попробуй еще раз.")
            return False
        
        logger.info(f"Пользователь {user_id} загадал число {number} для dice {dice_id}, результат обработан")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при обработке числа dice для пользователя {user_id}: {e}")
        dice_waiting_responses.pop(user_id, None)
        return False


async def handle_dice_result(bot, user_id: int, dice_value: int, dice_message_id: int, dice_id: str) -> bool:
    """Выдает билетик пользователю за победу в dice (число совпало)
    
    Args:
        bot: Экземпляр бота
        user_id: ID пользователя
        dice_value: Значение, выпавшее на кубике (1-6) - совпало с загаданным
        dice_message_id: ID сообщения с dice
        dice_id: ID события dice
        
    Returns:
        True если билетик выдан, False в противном случае
    """
    try:
        expected_number = dice_value  # Уже проверили, что совпало
        
        # Выдаем билетик
        async with _ticket_number_lock:
            async with AsyncSessionLocal() as session:
                # Получаем информацию о пользователе
                user_result = await session.execute(
                    select(User).where(User.id == user_id)
                )
                user = user_result.scalar_one_or_none()
                
                if not user:
                    logger.error(f"Пользователь {user_id} не найден в БД")
                    await safe_send_message(bot, user_id, "❌ Ошибка: пользователь не найден")
                    return False
                
                # Получаем следующий номер билета
                ticket_number = await get_next_raffle_ticket_number(session=session)
                
                # Создаем запись о билете
                from datetime import datetime
                current_date = datetime.now().strftime("%Y-%m-%d")
                
                participant = RaffleParticipant(
                    user_id=user_id,
                    raffle_date=current_date,
                    question_id=0,  # тех. значение для dice
                    question_text=f"dice_{dice_id}",
                    answer=f"dice_win_{expected_number}",
                    ticket_number=ticket_number,
                    is_correct=True,
                    timestamp=datetime.utcnow()
                )
                session.add(participant)
                await session.commit()
        
        # Отправляем сообщение о победе
        message_text = (
            f"🎉 <b>Поздравляю!</b>\n\n"
            f"Ты загадал число <b>{expected_number}</b> и оно выпало!\n"
            f"🎟 Твой билетик: <b>№{ticket_number}</b>"
        )
        
        success = await safe_send_message(bot, user_id, message_text, parse_mode="HTML")
        if not success:
            logger.error(f"Не удалось отправить сообщение о победе пользователю {user_id}")
        
        logger.info(f"Пользователь {user_id} выиграл в dice {dice_id}, получен билетик №{ticket_number}")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при выдаче билетика dice для пользователя {user_id}: {e}", exc_info=True)
        try:
            await safe_send_message(bot, user_id, "❌ Произошла ошибка при выдаче билетика. Попробуй еще раз.")
        except:
            pass
        return False

