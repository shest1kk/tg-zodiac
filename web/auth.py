"""
Модуль аутентификации для веб-интерфейса
"""
from fastapi import HTTPException, Depends, status, Request
from typing import Annotated
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.middleware.sessions import SessionMiddleware
import os

# Настройки авторизации из переменных окружения
WEB_ADMIN_LOGIN = os.getenv("WEB_ADMIN_LOGIN", "admin")
WEB_ADMIN_PASSWORD = os.getenv("WEB_ADMIN_PASSWORD", "admin")

def get_current_user(request: Request) -> str:
    """Получает текущего пользователя из сессии"""
    if not request.session.get("authenticated"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация"
        )
    return request.session.get("username")


def verify_login(login: str, password: str) -> bool:
    """Проверяет логин и пароль"""
    return login == WEB_ADMIN_LOGIN and password == WEB_ADMIN_PASSWORD

