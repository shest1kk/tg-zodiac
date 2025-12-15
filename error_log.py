"""
Модуль для хранения последних ошибок для админ-панели
"""
from datetime import datetime
from typing import List, Dict

# Хранилище последних ошибок
recent_errors: List[Dict] = []
MAX_ERRORS_STORED = 50

def log_error_for_admin(error_msg: str, exc_info=None):
    """Добавляет ошибку в список для отображения админам"""
    error_entry = {
        'time': datetime.now(),
        'message': error_msg,
        'traceback': str(exc_info) if exc_info else None
    }
    recent_errors.append(error_entry)
    # Ограничиваем количество хранимых ошибок
    if len(recent_errors) > MAX_ERRORS_STORED:
        recent_errors.pop(0)

def get_recent_errors(limit: int = 10) -> List[Dict]:
    """Получить последние ошибки"""
    if not recent_errors:
        return []
    
    errors_to_show = recent_errors[-limit:]
    errors_to_show.reverse()  # От новых к старым
    return errors_to_show

def get_errors_count_since(hours: int = 1) -> int:
    """Получить количество ошибок за последние N часов"""
    from datetime import timedelta
    cutoff = datetime.now() - timedelta(hours=hours)
    return len([e for e in recent_errors if e['time'] >= cutoff])

