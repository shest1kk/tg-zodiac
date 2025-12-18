"""
Модуль отказоустойчивости для Telegram бота.
Обеспечивает retry механизмы, обработку ошибок и graceful degradation.
"""

import asyncio
import logging
import functools
from typing import Callable, Any, Optional, TypeVar, Union
from datetime import datetime, timedelta
from sqlalchemy.exc import SQLAlchemyError, OperationalError, DisconnectionError
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramNetworkError,
    TelegramServerError,
    TelegramAPIError,
    TelegramUnauthorizedError,
)
from aiogram import Bot

logger = logging.getLogger(__name__)

T = TypeVar('T')

# Конфигурация retry
MAX_RETRIES = 3
RETRY_DELAY = 1.0  # секунды
RETRY_BACKOFF = 2.0  # множитель для exponential backoff
MAX_RETRY_DELAY = 60.0  # максимальная задержка

# Время для rate limiting
RATE_LIMIT_DELAY = 0.05


class ResilienceError(Exception):
    """Базовый класс для ошибок отказоустойчивости"""
    pass


class RetryableError(Exception):
    """Ошибка, при которой стоит повторить операцию"""
    pass


class NonRetryableError(Exception):
    """Ошибка, при которой не стоит повторять операцию"""
    pass


def is_retryable_telegram_error(error: Exception) -> bool:
    """Проверяет, можно ли повторить операцию при данной ошибке Telegram API"""
    if isinstance(error, TelegramRetryAfter):
        return True
    if isinstance(error, TelegramNetworkError):
        return True
    if isinstance(error, TelegramServerError):
        return True
    if isinstance(error, TelegramBadRequest):
        # Некоторые ошибки BadRequest можно повторить
        error_msg = str(error).lower()
        if any(keyword in error_msg for keyword in ['timeout', 'network', 'connection', 'temporary']):
            return True
    return False


def is_retryable_db_error(error: Exception) -> bool:
    """Проверяет, можно ли повторить операцию при данной ошибке БД"""
    if isinstance(error, OperationalError):
        return True
    if isinstance(error, DisconnectionError):
        return True
    if isinstance(error, SQLAlchemyError):
        error_msg = str(error).lower()
        if any(keyword in error_msg for keyword in ['connection', 'timeout', 'pool', 'deadlock']):
            return True
    return False


def should_unsubscribe_user(error: Exception) -> bool:
    """Проверяет, нужно ли отписать пользователя при данной ошибке"""
    if isinstance(error, TelegramForbiddenError):
        return True
    if isinstance(error, TelegramUnauthorizedError):
        return True
    if isinstance(error, TelegramBadRequest):
        error_msg = str(error).lower()
        if 'chat not found' in error_msg or 'user is deactivated' in error_msg:
            return True
    return False


def retry_with_backoff(
    max_retries: int = MAX_RETRIES,
    delay: float = RETRY_DELAY,
    backoff: float = RETRY_BACKOFF,
    max_delay: float = MAX_RETRY_DELAY,
    exceptions: tuple = (Exception,),
    retry_check: Optional[Callable[[Exception], bool]] = None,
):
    """
    Декоратор для повторных попыток с exponential backoff
    
    Args:
        max_retries: Максимальное количество попыток
        delay: Начальная задержка в секундах
        backoff: Множитель для exponential backoff
        max_delay: Максимальная задержка в секундах
        exceptions: Кортеж исключений, при которых нужно повторять
        retry_check: Функция для проверки, нужно ли повторять при данной ошибке
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            current_delay = delay
            last_error = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_error = e
                    
                    # Проверяем, нужно ли повторять
                    if retry_check and not retry_check(e):
                        logger.debug(f"Ошибка не является повторяемой: {e}")
                        raise
                    
                    # Если это последняя попытка, выбрасываем ошибку
                    if attempt >= max_retries:
                        logger.error(f"Превышено максимальное количество попыток ({max_retries}) для {func.__name__}: {e}")
                        raise
                    
                    # Специальная обработка для TelegramRetryAfter
                    if isinstance(e, TelegramRetryAfter):
                        wait_time = e.retry_after
                        logger.warning(f"Rate limit достигнут, ждем {wait_time} секунд")
                    else:
                        wait_time = min(current_delay, max_delay)
                    
                    logger.warning(
                        f"Ошибка в {func.__name__} (попытка {attempt + 1}/{max_retries + 1}): {e}. "
                        f"Повтор через {wait_time:.2f} сек."
                    )
                    
                    await asyncio.sleep(wait_time)
                    current_delay *= backoff
            
            # Не должно быть достигнуто, но на всякий случай
            if last_error:
                raise last_error
            raise ResilienceError(f"Неожиданная ошибка в {func.__name__}")
        
        return wrapper
    return decorator


async def safe_send_message(
    bot: Bot,
    user_id: int,
    text: str,
    parse_mode: Optional[str] = None,
    max_retries: int = MAX_RETRIES,
    **kwargs
) -> bool:
    """
    Безопасная отправка сообщения с retry механизмом
    
    Returns:
        True если сообщение отправлено успешно, False в противном случае
    """
    for attempt in range(max_retries + 1):
        try:
            await bot.send_message(
                user_id,
                text,
                parse_mode=parse_mode,
                **kwargs
            )
            return True
            
        except TelegramRetryAfter as e:
            if attempt < max_retries:
                wait_time = e.retry_after
                logger.warning(f"Rate limit для пользователя {user_id}, ждем {wait_time} сек")
                await asyncio.sleep(wait_time)
                continue
            else:
                logger.error(f"Превышен rate limit для пользователя {user_id} после {max_retries} попыток")
                return False
                
        except TelegramForbiddenError:
            logger.info(f"Пользователь {user_id} заблокировал бота")
            return False
            
        except TelegramBadRequest as e:
            error_msg = str(e).lower()
            if 'chat not found' in error_msg or 'user is deactivated' in error_msg:
                logger.info(f"Чат с пользователем {user_id} не найден или деактивирован")
                return False
            elif attempt < max_retries and is_retryable_telegram_error(e):
                wait_time = RETRY_DELAY * (RETRY_BACKOFF ** attempt)
                logger.warning(f"Ошибка Telegram API для {user_id} (попытка {attempt + 1}), повтор через {wait_time:.2f} сек: {e}")
                await asyncio.sleep(min(wait_time, MAX_RETRY_DELAY))
                continue
            else:
                logger.error(f"Неисправимая ошибка Telegram API для пользователя {user_id}: {e}")
                return False
                
        except (TelegramNetworkError, TelegramServerError) as e:
            if attempt < max_retries:
                wait_time = RETRY_DELAY * (RETRY_BACKOFF ** attempt)
                logger.warning(f"Сетевая/серверная ошибка для {user_id} (попытка {attempt + 1}), повтор через {wait_time:.2f} сек: {e}")
                await asyncio.sleep(min(wait_time, MAX_RETRY_DELAY))
                continue
            else:
                logger.error(f"Не удалось отправить сообщение пользователю {user_id} после {max_retries} попыток: {e}")
                return False
                
        except Exception as e:
            logger.error(f"Неожиданная ошибка при отправке сообщения пользователю {user_id}: {e}")
            return False
    
    return False


async def safe_send_message_with_result(
    bot: Bot,
    user_id: int,
    text: str,
    parse_mode: Optional[str] = None,
    max_retries: int = MAX_RETRIES,
    **kwargs
):
    """
    Безопасная отправка сообщения с retry механизмом, возвращает объект Message
    
    Returns:
        Объект Message если сообщение отправлено успешно, None в противном случае
    """
    from aiogram.types import Message
    
    for attempt in range(max_retries + 1):
        try:
            message = await bot.send_message(
                user_id,
                text,
                parse_mode=parse_mode,
                **kwargs
            )
            return message
            
        except TelegramRetryAfter as e:
            if attempt < max_retries:
                wait_time = e.retry_after
                logger.warning(f"Rate limit для пользователя {user_id}, ждем {wait_time} сек")
                await asyncio.sleep(wait_time)
                continue
            else:
                logger.error(f"Превышен rate limit для пользователя {user_id} после {max_retries} попыток")
                return None
                
        except TelegramForbiddenError:
            logger.info(f"Пользователь {user_id} заблокировал бота")
            return None
            
        except TelegramBadRequest as e:
            error_msg = str(e).lower()
            if 'chat not found' in error_msg or 'user is deactivated' in error_msg:
                logger.info(f"Чат с пользователем {user_id} не найден или деактивирован")
                return None
            elif attempt < max_retries and is_retryable_telegram_error(e):
                wait_time = RETRY_DELAY * (RETRY_BACKOFF ** attempt)
                logger.warning(f"Ошибка Telegram API для {user_id} (попытка {attempt + 1}), повтор через {wait_time:.2f} сек: {e}")
                await asyncio.sleep(min(wait_time, MAX_RETRY_DELAY))
                continue
            else:
                logger.error(f"Неисправимая ошибка Telegram API для пользователя {user_id}: {e}")
                return None
                
        except (TelegramNetworkError, TelegramServerError) as e:
            if attempt < max_retries:
                wait_time = RETRY_DELAY * (RETRY_BACKOFF ** attempt)
                logger.warning(f"Сетевая/серверная ошибка для {user_id} (попытка {attempt + 1}), повтор через {wait_time:.2f} сек: {e}")
                await asyncio.sleep(min(wait_time, MAX_RETRY_DELAY))
                continue
            else:
                logger.error(f"Не удалось отправить сообщение пользователю {user_id} после {max_retries} попыток: {e}")
                return None
                
        except Exception as e:
            logger.error(f"Неожиданная ошибка при отправке сообщения пользователю {user_id}: {e}")
            return None
    
    return None


async def safe_edit_message_text(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    parse_mode: Optional[str] = None,
    max_retries: int = MAX_RETRIES,
    **kwargs
) -> bool:
    """
    Безопасное редактирование сообщения с retry механизмом
    
    Returns:
        True если сообщение отредактировано успешно, False в противном случае
    """
    for attempt in range(max_retries + 1):
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=parse_mode,
                **kwargs
            )
            return True
            
        except TelegramRetryAfter as e:
            if attempt < max_retries:
                wait_time = e.retry_after
                logger.warning(f"Rate limit для редактирования сообщения {message_id}, ждем {wait_time} сек")
                await asyncio.sleep(wait_time)
                continue
            else:
                logger.error(f"Превышен rate limit для редактирования сообщения {message_id} после {max_retries} попыток")
                return False
                
        except TelegramForbiddenError:
            logger.info(f"Пользователь {chat_id} заблокировал бота")
            return False
            
        except TelegramBadRequest as e:
            error_msg = str(e).lower()
            if 'chat not found' in error_msg or 'user is deactivated' in error_msg:
                logger.info(f"Чат с пользователем {chat_id} не найден или деактивирован")
                return False
            elif 'message is not modified' in error_msg or 'message to edit not found' in error_msg:
                # Эти ошибки не критичны, сообщение уже отредактировано или удалено
                logger.debug(f"Сообщение {message_id} не может быть отредактировано: {e}")
                return False
            elif attempt < max_retries and is_retryable_telegram_error(e):
                wait_time = RETRY_DELAY * (RETRY_BACKOFF ** attempt)
                logger.warning(f"Ошибка Telegram API при редактировании (попытка {attempt + 1}), повтор через {wait_time:.2f} сек: {e}")
                await asyncio.sleep(min(wait_time, MAX_RETRY_DELAY))
                continue
            else:
                logger.error(f"Неисправимая ошибка Telegram API при редактировании сообщения {message_id}: {e}")
                return False
                
        except (TelegramNetworkError, TelegramServerError) as e:
            if attempt < max_retries:
                wait_time = RETRY_DELAY * (RETRY_BACKOFF ** attempt)
                logger.warning(f"Сетевая/серверная ошибка при редактировании (попытка {attempt + 1}), повтор через {wait_time:.2f} сек: {e}")
                await asyncio.sleep(min(wait_time, MAX_RETRY_DELAY))
                continue
            else:
                logger.error(f"Не удалось отредактировать сообщение {message_id} после {max_retries} попыток: {e}")
                return False
                
        except Exception as e:
            logger.error(f"Неожиданная ошибка при редактировании сообщения {message_id}: {e}")
            return False
    
    return False


async def safe_send_photo(
    bot: Bot,
    user_id: int,
    photo: Union[str, Any],
    caption: Optional[str] = None,
    parse_mode: Optional[str] = None,
    max_retries: int = MAX_RETRIES,
    **kwargs
) -> bool:
    """
    Безопасная отправка фото с retry механизмом
    
    Returns:
        True если фото отправлено успешно, False в противном случае
    """
    for attempt in range(max_retries + 1):
        try:
            await bot.send_photo(
                user_id,
                photo,
                caption=caption,
                parse_mode=parse_mode,
                **kwargs
            )
            return True
            
        except TelegramRetryAfter as e:
            if attempt < max_retries:
                wait_time = e.retry_after
                logger.warning(f"Rate limit для пользователя {user_id}, ждем {wait_time} сек")
                await asyncio.sleep(wait_time)
                continue
            else:
                logger.error(f"Превышен rate limit для пользователя {user_id} после {max_retries} попыток")
                return False
                
        except TelegramForbiddenError:
            logger.info(f"Пользователь {user_id} заблокировал бота")
            return False
            
        except TelegramBadRequest as e:
            error_msg = str(e).lower()
            if 'chat not found' in error_msg or 'user is deactivated' in error_msg:
                logger.info(f"Чат с пользователем {user_id} не найден или деактивирован")
                return False
            elif attempt < max_retries and is_retryable_telegram_error(e):
                wait_time = RETRY_DELAY * (RETRY_BACKOFF ** attempt)
                logger.warning(f"Ошибка Telegram API для {user_id} (попытка {attempt + 1}), повтор через {wait_time:.2f} сек: {e}")
                await asyncio.sleep(min(wait_time, MAX_RETRY_DELAY))
                continue
            else:
                logger.error(f"Неисправимая ошибка Telegram API для пользователя {user_id}: {e}")
                return False
                
        except (TelegramNetworkError, TelegramServerError) as e:
            if attempt < max_retries:
                wait_time = RETRY_DELAY * (RETRY_BACKOFF ** attempt)
                logger.warning(f"Сетевая/серверная ошибка для {user_id} (попытка {attempt + 1}), повтор через {wait_time:.2f} сек: {e}")
                await asyncio.sleep(min(wait_time, MAX_RETRY_DELAY))
                continue
            else:
                logger.error(f"Не удалось отправить фото пользователю {user_id} после {max_retries} попыток: {e}")
                return False
                
        except Exception as e:
            logger.error(f"Неожиданная ошибка при отправке фото пользователю {user_id}: {e}")
            return False
    
    return False


@retry_with_backoff(
    max_retries=3,
    exceptions=(SQLAlchemyError,),
    retry_check=is_retryable_db_error
)
async def safe_db_operation(operation: Callable[[], Any]) -> Any:
    """
    Безопасное выполнение операции с БД с retry механизмом
    
    Args:
        operation: Асинхронная функция для выполнения
        
    Returns:
        Результат выполнения операции
    """
    return await operation()


async def safe_load_predictions(file_path: str, fallback_data: Optional[dict] = None) -> tuple:
    """
    Безопасная загрузка предсказаний из файла с fallback
    
    Args:
        file_path: Путь к файлу с предсказаниями
        fallback_data: Данные по умолчанию, если файл недоступен
        
    Returns:
        Кортеж (start_date, days_data) или (None, None) при ошибке
    """
    import json
    from pathlib import Path
    
    predictions_path = Path(file_path)
    
    for attempt in range(MAX_RETRIES):
        try:
            if not predictions_path.exists():
                logger.error(f"Файл {file_path} не найден!")
                if fallback_data:
                    logger.warning(f"Используются данные по умолчанию")
                    return fallback_data.get("start_date"), fallback_data.get("days", {})
                return None, None
            
            with open(predictions_path, "r", encoding="utf-8") as f:
                predictions_data = json.load(f)
            
            start_date = predictions_data.get("start_date", "2025-12-01")
            days_data = predictions_data.get("days", {})
            
            logger.debug(f"Предсказания успешно загружены из {file_path}")
            return start_date, days_data
            
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON в {file_path} (попытка {attempt + 1}): {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY * (RETRY_BACKOFF ** attempt))
                continue
            else:
                logger.error(f"Не удалось загрузить предсказания после {MAX_RETRIES} попыток")
                if fallback_data:
                    logger.warning(f"Используются данные по умолчанию")
                    return fallback_data.get("start_date"), fallback_data.get("days", {})
                return None, None
                
        except IOError as e:
            logger.error(f"Ошибка чтения файла {file_path} (попытка {attempt + 1}): {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY * (RETRY_BACKOFF ** attempt))
                continue
            else:
                logger.error(f"Не удалось прочитать файл после {MAX_RETRIES} попыток")
                if fallback_data:
                    logger.warning(f"Используются данные по умолчанию")
                    return fallback_data.get("start_date"), fallback_data.get("days", {})
                return None, None
                
        except Exception as e:
            logger.error(f"Неожиданная ошибка при загрузке предсказаний из {file_path}: {e}")
            if fallback_data:
                logger.warning(f"Используются данные по умолчанию")
                return fallback_data.get("start_date"), fallback_data.get("days", {})
            return None, None
    
    return None, None


def handle_critical_error(func_name: str, error: Exception, context: Optional[dict] = None):
    """
    Обработка критических ошибок с логированием контекста
    
    Args:
        func_name: Имя функции, в которой произошла ошибка
        error: Исключение
        context: Дополнительный контекст для логирования
    """
    context_str = f" Контекст: {context}" if context else ""
    logger.critical(
        f"КРИТИЧЕСКАЯ ОШИБКА в {func_name}: {error}{context_str}",
        exc_info=True
    )

