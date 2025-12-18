"""
Роуты для операционки / контроля планировщика
"""
from fastapi import APIRouter, Depends, HTTPException
from web.auth import get_current_user

router = APIRouter()


@router.get("/jobs")
async def list_jobs(username: str = Depends(get_current_user)):
    """Список задач APScheduler (id, next_run_time и пр.)."""
    try:
        from scheduler import get_jobs_snapshot
        return get_jobs_snapshot()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quiz/{quiz_date}/reschedule")
async def reschedule_quiz(quiz_date: str, username: str = Depends(get_current_user)):
    """Пересоздать задачи конкретного квиза по данным из quiz.json."""
    try:
        from scheduler import reschedule_quiz_jobs_if_running
        ok = reschedule_quiz_jobs_if_running(quiz_date)
        return {"success": True, "rescheduled": ok}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quiz/{quiz_date}/run/{action}")
async def run_quiz_action(quiz_date: str, action: str, username: str = Depends(get_current_user)):
    """Ручной запуск действий по квизу.

    action:
    - announce: отправить объявления
    - remind: отправить напоминания
    - mark: отметить не участвовавших
    """
    action = (action or "").strip().lower()
    try:
        from scheduler import scheduler
        if not scheduler or not scheduler.running:
            raise HTTPException(status_code=409, detail="Scheduler не запущен")

        if action == "announce":
            from scheduler import send_quiz_announcements_for_date
            await send_quiz_announcements_for_date(quiz_date)
        elif action == "remind":
            from scheduler import send_quiz_reminders_for_date
            await send_quiz_reminders_for_date(quiz_date)
        elif action == "mark":
            from scheduler import mark_quiz_non_participants_for_date
            await mark_quiz_non_participants_for_date(quiz_date)
        else:
            raise HTTPException(status_code=400, detail="Неизвестное действие")

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/raffle/{raffle_date}/reschedule")
async def reschedule_raffle(raffle_date: str, username: str = Depends(get_current_user)):
    """Пересоздать задачи конкретного розыгрыша по данным из question.json."""
    try:
        from scheduler import reschedule_raffle_jobs_if_running
        ok = reschedule_raffle_jobs_if_running(raffle_date)
        return {"success": True, "rescheduled": ok}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/raffle/{raffle_date}/run/{action}")
async def run_raffle_action(raffle_date: str, action: str, username: str = Depends(get_current_user)):
    """Ручной запуск действий по розыгрышу.

    action:
    - announce: отправить объявления
    - remind: отправить напоминания
    - close: закрыть розыгрыш
    """
    action = (action or "").strip().lower()
    try:
        from scheduler import scheduler
        if not scheduler or not scheduler.running:
            raise HTTPException(status_code=409, detail="Scheduler не запущен")

        if action == "announce":
            from scheduler import send_raffle_announcements_for_date
            await send_raffle_announcements_for_date(raffle_date)
        elif action == "remind":
            from scheduler import send_raffle_reminders_for_date
            await send_raffle_reminders_for_date(raffle_date)
        elif action == "close":
            from scheduler import close_raffle_automatically
            await close_raffle_automatically(raffle_date)
        else:
            raise HTTPException(status_code=400, detail="Неизвестное действие")

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


