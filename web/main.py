"""
FastAPI веб-сервер для управления ботом
"""
from fastapi import FastAPI, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from contextlib import asynccontextmanager
from pathlib import Path
import secrets

from web.auth import get_current_user, verify_login
from web.routes import tickets, users, quiz, raffle, stats

# Глобальные переменные для доступа к боту и dispatcher
bot_instance = None
dp_instance = None

def set_bot_instances(bot, dp):
    """Устанавливает экземпляры бота и dispatcher для использования в роутах"""
    global bot_instance, dp_instance
    bot_instance = bot
    dp_instance = dp

def get_bot():
    """Возвращает экземпляр бота"""
    if bot_instance is None:
        raise HTTPException(status_code=500, detail="Бот не инициализирован")
    return bot_instance

def get_dp():
    """Возвращает экземпляр dispatcher"""
    if dp_instance is None:
        raise HTTPException(status_code=500, detail="Dispatcher не инициализирован")
    return dp_instance

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown

app = FastAPI(
    title="Zodiac Bot Admin Panel",
    description="Веб-интерфейс для управления ботом",
    version="1.0.0",
    lifespan=lifespan
)

# Добавляем middleware для сессий
app.add_middleware(SessionMiddleware, secret_key=secrets.token_urlsafe(32))

# Подключаем статические файлы и шаблоны
base_dir = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(base_dir / "static")), name="static")
templates = Jinja2Templates(directory=str(base_dir / "templates"))

# Подключаем роуты
app.include_router(tickets.router, prefix="/api/tickets", tags=["tickets"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(quiz.router, prefix="/api/quiz", tags=["quiz"])
app.include_router(raffle.router, prefix="/api/raffle", tags=["raffle"])
app.include_router(stats.router, prefix="/api/stats", tags=["stats"])

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Страница входа"""
    # Если уже авторизован, перенаправляем на главную
    if request.session.get("authenticated"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(request: Request, login: str = Form(...), password: str = Form(...)):
    """Обработка входа"""
    if verify_login(login, password):
        request.session["authenticated"] = True
        request.session["username"] = login
        return RedirectResponse(url="/", status_code=303)
    else:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Неверный логин или пароль"},
            status_code=401
        )

@app.get("/logout")
async def logout(request: Request):
    """Выход из системы"""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)

@app.get("/", response_class=HTMLResponse)
async def root(request: Request, username: str = Depends(get_current_user)):
    """Главная страница админ-панели"""
    return templates.TemplateResponse("index.html", {"request": request, "username": username})

@app.get("/health")
async def health():
    """Проверка здоровья сервера"""
    return {"status": "ok"}

