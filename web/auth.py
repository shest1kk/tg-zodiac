"""
Модуль аутентификации для веб-интерфейса
"""
from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from config import ADMIN_IDS

security = HTTPBasic()

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Проверяет, является ли пользователь админом"""
    if not ADMIN_IDS:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Администраторы не настроены"
        )
    
    # Простая проверка по ID (в реальном приложении лучше использовать токены)
    # Для веб-интерфейса можно использовать пароль из env
    import os
    web_password = os.getenv("WEB_ADMIN_PASSWORD", "admin")
    
    # Проверяем пароль
    if credentials.password != web_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный пароль",
            headers={"WWW-Authenticate": "Basic"},
        )
    
    # Проверяем, что username - это ID админа
    try:
        admin_id = int(credentials.username)
        if admin_id not in ADMIN_IDS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Доступ запрещен"
            )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный формат ID",
            headers={"WWW-Authenticate": "Basic"},
        )
    
    return admin_id

