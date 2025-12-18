"""
Роуты для управления розыгрышами
"""
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy import select, func, and_
from database import AsyncSessionLocal, Raffle, RaffleParticipant
from web.auth import get_current_user

router = APIRouter()

@router.get("/dates")
async def get_raffle_dates(username: str = Depends(get_current_user)):
    """Получить список дат розыгрышей"""
    from raffle import get_all_raffle_dates
    dates = get_all_raffle_dates()
    return {"dates": dates}

@router.get("/{raffle_date}/stats")
async def get_raffle_stats(raffle_date: str, username: str = Depends(get_current_user)):
    """Получить статистику по розыгрышу"""
    async with AsyncSessionLocal() as session:
        # Все участники
        total = await session.scalar(
            select(func.count(RaffleParticipant.id)).where(
                RaffleParticipant.raffle_date == raffle_date
            )
        )
        
        # Принятые
        approved = await session.scalar(
            select(func.count(RaffleParticipant.id)).where(
                and_(
                    RaffleParticipant.raffle_date == raffle_date,
                    RaffleParticipant.is_correct == True
                )
            )
        )
        
        # Отклоненные
        denied = await session.scalar(
            select(func.count(RaffleParticipant.id)).where(
                and_(
                    RaffleParticipant.raffle_date == raffle_date,
                    RaffleParticipant.is_correct == False
                )
            )
        )
        
        # Не проверенные
        unchecked = await session.scalar(
            select(func.count(RaffleParticipant.id)).where(
                and_(
                    RaffleParticipant.raffle_date == raffle_date,
                    RaffleParticipant.is_correct.is_(None),
                    RaffleParticipant.answer.isnot(None)
                )
            )
        )
        
        return {
            "raffle_date": raffle_date,
            "total_participants": total or 0,
            "approved": approved or 0,
            "denied": denied or 0,
            "unchecked": unchecked or 0
        }

@router.get("/{raffle_date}/unchecked")
async def get_unchecked_answers(
    raffle_date: str,
    skip: int = 0,
    limit: int = 50,
    username: str = Depends(get_current_user)
):
    """Получить список непроверенных ответов"""
    from raffle import get_unchecked_answers as get_unchecked
    
    unchecked = await get_unchecked(raffle_date)
    
    result = []
    for p in unchecked[skip:skip+limit]:
        result.append({
            "user_id": p.user_id,
            "question_id": p.question_id,
            "question_text": p.question_text,
            "answer": p.answer,
            "timestamp": p.timestamp.isoformat() if p.timestamp else None
        })
    
    return {
        "total": len(unchecked),
        "skip": skip,
        "limit": limit,
        "unchecked": result
    }

@router.post("/{raffle_date}/approve/{user_id}")
async def approve_answer(
    raffle_date: str,
    user_id: int,
    username: str = Depends(get_current_user)
):
    """Одобрить ответ пользователя"""
    from raffle import approve_answer as approve
    
    success = await approve(user_id, raffle_date)
    if not success:
        raise HTTPException(status_code=400, detail="Не удалось одобрить ответ")
    
    return {"success": True, "message": f"Ответ пользователя {user_id} одобрен"}

@router.post("/{raffle_date}/deny/{user_id}")
async def deny_answer(
    raffle_date: str,
    user_id: int,
    username: str = Depends(get_current_user)
):
    """Отклонить ответ пользователя"""
    from raffle import deny_answer as deny
    
    success = await deny(user_id, raffle_date)
    if not success:
        raise HTTPException(status_code=400, detail="Не удалось отклонить ответ")
    
    return {"success": True, "message": f"Ответ пользователя {user_id} отклонен"}

@router.get("/{raffle_date}/questions")
async def get_raffle_questions(raffle_date: str, username: str = Depends(get_current_user)):
    """Получить вопросы розыгрыша"""
    from raffle import get_all_questions
    questions = get_all_questions(raffle_date)
    return {"raffle_date": raffle_date, "questions": questions}

@router.get("/{raffle_date}/questions/{question_id}")
async def get_raffle_question(
    raffle_date: str,
    question_id: int,
    username: str = Depends(get_current_user)
):
    """Получить конкретный вопрос розыгрыша"""
    from raffle import get_question_by_id
    question = get_question_by_id(question_id, raffle_date)
    if not question:
        raise HTTPException(status_code=404, detail="Вопрос не найден")
    return question

@router.put("/{raffle_date}/questions/{question_id}")
async def update_raffle_question(
    raffle_date: str,
    question_id: int,
    data: dict = Body(...),
    username: str = Depends(get_current_user)
):
    """Обновить вопрос розыгрыша"""
    from raffle import update_question
    try:
        title = data.get("title") or data.get("question_title", "")
        text = data.get("text") or data.get("question_text", "")
        result = update_question(question_id, raffle_date, title, text)
        if result:
            return {"success": True, "message": "Вопрос обновлен"}
        else:
            raise HTTPException(status_code=404, detail="Вопрос не найден")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _format_msk(dt) -> str:
    try:
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


@router.get("/list")
async def get_raffle_list(username: str = Depends(get_current_user)):
    """Список розыгрышей с метаданными (для админки)."""
    from raffle import get_all_raffle_dates, get_raffle_meta, get_raffle_start_datetime_moscow, get_all_questions

    dates = sorted(get_all_raffle_dates())
    items = []
    for d in dates:
        meta = get_raffle_meta(d)
        starts_at = get_raffle_start_datetime_moscow(d)
        questions = get_all_questions(d)
        items.append({
            "raffle_date": d,
            "title": meta.get("title") if meta else None,
            "starts_at": starts_at.isoformat() if starts_at else None,
            "starts_at_msk": _format_msk(starts_at) if starts_at else None,
            "questions_count": len(questions)
        })
    return {"raffles": items}


@router.get("/{raffle_date}/meta")
async def get_raffle_meta_api(raffle_date: str, username: str = Depends(get_current_user)):
    """Метаданные розыгрыша (заголовок, дата-время начала)."""
    from raffle import get_raffle_meta, get_raffle_start_datetime_moscow
    meta = get_raffle_meta(raffle_date)
    starts_at = get_raffle_start_datetime_moscow(raffle_date)
    return {
        "raffle_date": raffle_date,
        "title": meta.get("title") if meta else None,
        "starts_at": starts_at.isoformat() if starts_at else None,
        "starts_at_msk": _format_msk(starts_at) if starts_at else None,
    }


@router.post("/create")
async def create_raffle(
    data: dict = Body(...),
    username: str = Depends(get_current_user)
):
    """Создать новый розыгрыш (с датой/временем, заголовком и вопросами).

    Ожидаем:
    {
      "starts_at_local": "YYYY-MM-DDTHH:MM",
      "title": "...",
      "questions": [
        { "id": 1, "title": "...", "text": "..." }
      ]
    }
    """
    from raffle import create_raffle_data
    from scheduler import schedule_raffle_jobs_if_running

    starts_at_local = data.get("starts_at_local")
    title = data.get("title")
    questions = data.get("questions")

    if not isinstance(starts_at_local, str) or not starts_at_local.strip():
        raise HTTPException(status_code=400, detail="Поле starts_at_local обязательно")
    if not isinstance(title, str) or not title.strip():
        raise HTTPException(status_code=400, detail="Заголовок обязателен")
    if not isinstance(questions, list) or len(questions) < 1:
        raise HTTPException(status_code=400, detail="Должен быть минимум 1 вопрос")

    result = create_raffle_data(starts_at_local[:10], starts_at_local, title, questions)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Ошибка")

    raffle_date = result["raffle_date"]
    scheduled = schedule_raffle_jobs_if_running(raffle_date)
    return {"success": True, "raffle_date": raffle_date, "scheduled": scheduled}


@router.put("/{raffle_date}/meta")
async def update_raffle_meta(
    raffle_date: str,
    data: dict = Body(...),
    username: str = Depends(get_current_user)
):
    """Обновить заголовок/время старта розыгрыша (meta) и пересоздать задачи планировщика."""
    from raffle import set_raffle_meta_from_local
    from scheduler import reschedule_raffle_jobs_if_running

    title = data.get("title")
    starts_at_local = data.get("starts_at_local")

    result = set_raffle_meta_from_local(raffle_date, title, starts_at_local)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Ошибка")

    scheduled = reschedule_raffle_jobs_if_running(raffle_date)
    return {"success": True, "raffle_date": raffle_date, "scheduled": scheduled}


@router.delete("/{raffle_date}")
async def delete_raffle_api(raffle_date: str, username: str = Depends(get_current_user)):
    """Удалить розыгрыш"""
    from raffle import delete_raffle
    result = await delete_raffle(raffle_date)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Ошибка")
    return {"success": True, "message": f"Розыгрыш {raffle_date} удален"}


@router.post("/{raffle_date}/questions")
async def add_raffle_question(
    raffle_date: str,
    data: dict = Body(...),
    username: str = Depends(get_current_user)
):
    """Добавить вопрос к розыгрышу"""
    from raffle import add_raffle_question
    question_id = data.get("question_id")
    title = data.get("title")
    text = data.get("text")
    
    if not question_id or not title or not text:
        raise HTTPException(status_code=400, detail="question_id, title и text обязательны")
    
    result = add_raffle_question(raffle_date, question_id, title, text)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Ошибка")
    return {"success": True, "message": "Вопрос добавлен"}


@router.delete("/{raffle_date}/questions/{question_id}")
async def remove_raffle_question_api(
    raffle_date: str,
    question_id: int,
    username: str = Depends(get_current_user)
):
    """Удалить вопрос из розыгрыша"""
    from raffle import remove_raffle_question
    result = await remove_raffle_question(raffle_date, question_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Ошибка")
    return {"success": True, "message": "Вопрос удален"}


@router.get("/disabled-dates")
async def get_disabled_dates(username: str = Depends(get_current_user)):
    """Получить список отключенных дат розыгрышей"""
    from pathlib import Path
    import json
    
    base_dir = Path(__file__).parent.parent.parent
    disabled_file = base_dir / "data" / "raffle_disabled_dates.json"
    
    if disabled_file.exists():
        with open(disabled_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {"disabled_dates": data.get("dates", [])}
    return {"disabled_dates": []}


@router.post("/{raffle_date}/toggle")
async def toggle_raffle_date(raffle_date: str, username: str = Depends(get_current_user)):
    """Включить/отключить розыгрыш для даты"""
    from pathlib import Path
    import json
    
    base_dir = Path(__file__).parent.parent.parent
    disabled_file = base_dir / "data" / "raffle_disabled_dates.json"
    
    if disabled_file.exists():
        with open(disabled_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            disabled_dates = set(data.get("dates", []))
    else:
        disabled_dates = set()
    
    if raffle_date in disabled_dates:
        disabled_dates.remove(raffle_date)
        action = "включен"
    else:
        disabled_dates.add(raffle_date)
        action = "отключен"
    
    disabled_file.parent.mkdir(parents=True, exist_ok=True)
    with open(disabled_file, "w", encoding="utf-8") as f:
        json.dump({"dates": sorted(list(disabled_dates))}, f, ensure_ascii=False, indent=2)
    
    return {"success": True, "message": f"Розыгрыш для {raffle_date} {action}", "disabled": raffle_date not in disabled_dates}

