"""
Роуты для управления квизами
"""
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy import select, func, and_
from database import AsyncSessionLocal, Quiz, QuizResult, QuizParticipant
from web.auth import get_current_user

router = APIRouter()

def _format_msk(dt) -> str:
    try:
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


@router.get("/dates")
async def get_quiz_dates(username: str = Depends(get_current_user)):
    """Получить список дат квизов"""
    from quiz import get_all_quiz_dates
    dates = get_all_quiz_dates()
    return {"dates": dates}

@router.get("/list")
async def get_quiz_list(username: str = Depends(get_current_user)):
    """Список квизов с метаданными (для админки)."""
    from quiz import get_all_quiz_dates, get_quiz_title, get_quiz_start_datetime_moscow, get_total_questions

    dates = sorted(get_all_quiz_dates())
    items = []
    for d in dates:
        starts_at = get_quiz_start_datetime_moscow(d)
        items.append({
            "quiz_date": d,
            "title": get_quiz_title(d),
            "starts_at": starts_at.isoformat() if starts_at else None,
            "starts_at_msk": _format_msk(starts_at) if starts_at else None,
            "questions_count": get_total_questions(d)
        })
    return {"quizzes": items}


@router.get("/{quiz_date}/meta")
async def get_quiz_meta_api(quiz_date: str, username: str = Depends(get_current_user)):
    """Метаданные квиза (заголовок, дата-время начала)."""
    from quiz import get_quiz_title, get_quiz_start_datetime_moscow
    starts_at = get_quiz_start_datetime_moscow(quiz_date)
    return {
        "quiz_date": quiz_date,
        "title": get_quiz_title(quiz_date),
        "starts_at": starts_at.isoformat() if starts_at else None,
        "starts_at_msk": _format_msk(starts_at) if starts_at else None,
    }


@router.post("/create")
async def create_quiz(
    data: dict = Body(...),
    username: str = Depends(get_current_user)
):
    """Создать новый квиз (с датой/временем, заголовком и вопросами).

    Ожидаем:
    {
      "starts_at_local": "YYYY-MM-DDTHH:MM",
      "title": "...",
      "questions": [
        { "question": "...", "options": {"1":"..","2":"..","3":"..","4":".."}, "correct_answer":"1" }
      ]
    }
    """
    from datetime import datetime, timedelta, timezone
    from quiz import load_all_quiz_data, save_quiz_data, MOSCOW_TZ
    from scheduler import schedule_quiz_jobs_if_running

    starts_at_local = data.get("starts_at_local")
    title = data.get("title")
    questions = data.get("questions")

    if not isinstance(starts_at_local, str) or not starts_at_local.strip():
        raise HTTPException(status_code=400, detail="Поле starts_at_local обязательно")
    if not isinstance(title, str) or not title.strip():
        raise HTTPException(status_code=400, detail="Заголовок обязателен")
    if not isinstance(questions, list) or len(questions) < 1:
        raise HTTPException(status_code=400, detail="Должен быть минимум 1 вопрос")

    try:
        # HTML datetime-local -> naive datetime (интерпретируем как МСК)
        starts_at = datetime.fromisoformat(starts_at_local.strip())
        if starts_at.tzinfo is not None:
            starts_at = starts_at.astimezone(MOSCOW_TZ).replace(tzinfo=MOSCOW_TZ)
        else:
            starts_at = starts_at.replace(tzinfo=MOSCOW_TZ)
    except Exception:
        raise HTTPException(status_code=400, detail="Неверный формат даты/времени (ожидается YYYY-MM-DDTHH:MM)")

    quiz_date = starts_at.date().strftime("%Y-%m-%d")
    starts_at_iso = starts_at.isoformat()

    all_data = load_all_quiz_data()
    if not all_data:
        all_data = {"quiz_dates": {}}
    if "quiz_dates" not in all_data or not isinstance(all_data["quiz_dates"], dict):
        all_data["quiz_dates"] = {}

    if quiz_date in all_data["quiz_dates"]:
        raise HTTPException(status_code=409, detail=f"Квиз на дату {quiz_date} уже существует")

    # Нормализуем вопросы в формат quiz.json
    questions_dict = {}
    for idx, q in enumerate(questions, start=1):
        if not isinstance(q, dict):
            raise HTTPException(status_code=400, detail=f"Вопрос #{idx}: неверный формат")
        q_text = q.get("question")
        options = q.get("options")
        correct = q.get("correct_answer")
        if not isinstance(q_text, str) or not q_text.strip():
            raise HTTPException(status_code=400, detail=f"Вопрос #{idx}: пустой текст")
        if not isinstance(options, dict) or not options:
            raise HTTPException(status_code=400, detail=f"Вопрос #{idx}: варианты ответов обязательны")
        # Требуем 4 варианта как в текущем формате
        for k in ("1", "2", "3", "4"):
            if k not in options or not isinstance(options.get(k), str) or not options.get(k).strip():
                raise HTTPException(status_code=400, detail=f"Вопрос #{idx}: вариант {k} обязателен")
        if str(correct) not in ("1", "2", "3", "4"):
            raise HTTPException(status_code=400, detail=f"Вопрос #{idx}: correct_answer должен быть 1-4")

        questions_dict[str(idx)] = {
            "id": idx,
            "question": q_text.strip(),
            "options": {k: str(options[k]).strip() for k in ("1", "2", "3", "4")},
            "correct_answer": str(correct),
        }

    all_data["quiz_dates"][quiz_date] = {
        "meta": {
            "title": title.strip(),
            "starts_at": starts_at_iso,
        },
        "questions": questions_dict,
    }

    if not save_quiz_data(all_data):
        raise HTTPException(status_code=500, detail="Не удалось сохранить quiz.json")

    scheduled = schedule_quiz_jobs_if_running(quiz_date)
    return {"success": True, "quiz_date": quiz_date, "scheduled": scheduled}


@router.put("/{quiz_date}/meta")
async def update_quiz_meta(
    quiz_date: str,
    data: dict = Body(...),
    username: str = Depends(get_current_user)
):
    """Обновить заголовок/время старта квиза (meta) и пересоздать задачи планировщика."""
    from quiz import set_quiz_meta_from_local
    from scheduler import reschedule_quiz_jobs_if_running

    title = data.get("title")
    starts_at_local = data.get("starts_at_local")

    result = set_quiz_meta_from_local(quiz_date, title, starts_at_local)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Ошибка")

    scheduled = reschedule_quiz_jobs_if_running(quiz_date)
    return {"success": True, "quiz_date": quiz_date, "scheduled": scheduled}


@router.post("/duplicate")
async def duplicate_quiz(
    data: dict = Body(...),
    username: str = Depends(get_current_user)
):
    """Дублировать квиз на новую дату/время, копируя вопросы."""
    from quiz import duplicate_quiz_from_local
    from scheduler import schedule_quiz_jobs_if_running

    source_quiz_date = data.get("source_quiz_date")
    starts_at_local = data.get("starts_at_local")
    title = data.get("title")

    result = duplicate_quiz_from_local(source_quiz_date, starts_at_local, title)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Ошибка")

    quiz_date = result["quiz_date"]
    scheduled = schedule_quiz_jobs_if_running(quiz_date)
    return {"success": True, "quiz_date": quiz_date, "scheduled": scheduled}


@router.get("/{quiz_date}/stats")
async def get_quiz_stats(quiz_date: str, username: str = Depends(get_current_user)):
    """Получить статистику по квизу"""
    async with AsyncSessionLocal() as session:
        # Все участники
        total = await session.scalar(
            select(func.count(QuizResult.id)).where(
                QuizResult.quiz_date == quiz_date
            )
        )
        
        # Получили билетик
        with_tickets = await session.scalar(
            select(func.count(QuizResult.id)).where(
                and_(
                    QuizResult.quiz_date == quiz_date,
                    QuizResult.ticket_number.isnot(None)
                )
            )
        )
        
        # Не получили билетик
        no_tickets = await session.scalar(
            select(func.count(QuizResult.id)).where(
                and_(
                    QuizResult.quiz_date == quiz_date,
                    QuizResult.ticket_number.is_(None),
                    QuizResult.total_questions > 0
                )
            )
        )
        
        # Не приняли участие
        non_participants = await session.scalar(
            select(func.count(QuizResult.id)).where(
                and_(
                    QuizResult.quiz_date == quiz_date,
                    QuizResult.correct_answers == 0,
                    QuizResult.total_questions == 0
                )
            )
        )
        
        return {
            "quiz_date": quiz_date,
            "total_participants": total or 0,
            "with_tickets": with_tickets or 0,
            "no_tickets": no_tickets or 0,
            "non_participants": non_participants or 0
        }

@router.get("/{quiz_date}/participants")
async def get_quiz_participants(
    quiz_date: str,
    skip: int = 0,
    limit: int = 50,
    username: str = Depends(get_current_user)
):
    """Получить список участников квиза"""
    async with AsyncSessionLocal() as session:
        participants_query = await session.execute(
            select(QuizResult).where(
                QuizResult.quiz_date == quiz_date
            ).offset(skip).limit(limit).order_by(QuizResult.completed_at.desc())
        )
        participants = participants_query.scalars().all()
        
        result = []
        for p in participants:
            result.append({
                "user_id": p.user_id,
                "username": p.username,
                "correct_answers": p.correct_answers,
                "total_questions": p.total_questions,
                "ticket_number": p.ticket_number,
                "completed_at": p.completed_at.isoformat() if p.completed_at else None
            })
        
        return {"participants": result}

@router.get("/{quiz_date}/questions")
async def get_quiz_questions(quiz_date: str, username: str = Depends(get_current_user)):
    """Получить вопросы квиза"""
    from quiz import get_all_questions
    questions = get_all_questions(quiz_date)
    return {"quiz_date": quiz_date, "questions": questions}

@router.put("/{quiz_date}/questions/{question_id}")
async def update_quiz_question(
    quiz_date: str,
    question_id: int,
    data: dict = Body(...),
    username: str = Depends(get_current_user)
):
    """Обновить вопрос квиза"""
    from quiz import update_quiz_question as update_question
    try:
        question_text = data.get("question_text")
        options = data.get("options")
        correct_answer = data.get("correct_answer")
        # Функция принимает параметры в порядке: question_id, quiz_date, question_text, options, correct_answer
        result = update_question(question_id, quiz_date, question_text, options, correct_answer)
        if result:
            return {"success": True, "message": "Вопрос обновлен"}
        else:
            raise HTTPException(status_code=404, detail="Вопрос не найден")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/disabled-dates")
async def get_disabled_dates(username: str = Depends(get_current_user)):
    """Получить список отключенных дат квизов"""
    from pathlib import Path
    import json
    import os
    
    # Определяем путь к файлу (работает и в Docker, и локально)
    base_dir = Path(__file__).parent.parent.parent
    disabled_file = base_dir / "data" / "quiz_disabled_dates.json"
    
    if disabled_file.exists():
        with open(disabled_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {"disabled_dates": data.get("dates", [])}
    return {"disabled_dates": []}

@router.post("/{quiz_date}/toggle")
async def toggle_quiz_date(quiz_date: str, username: str = Depends(get_current_user)):
    """Включить/отключить квиз для даты"""
    from pathlib import Path
    import json
    
    # Определяем путь к файлу (работает и в Docker, и локально)
    base_dir = Path(__file__).parent.parent.parent
    disabled_file = base_dir / "data" / "quiz_disabled_dates.json"
    
    # Загружаем текущий список
    if disabled_file.exists():
        with open(disabled_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            disabled_dates = set(data.get("dates", []))
    else:
        disabled_dates = set()
    
    # Переключаем состояние
    if quiz_date in disabled_dates:
        disabled_dates.remove(quiz_date)
        action = "включен"
    else:
        disabled_dates.add(quiz_date)
        action = "отключен"
    
    # Сохраняем
    disabled_file.parent.mkdir(parents=True, exist_ok=True)
    with open(disabled_file, "w", encoding="utf-8") as f:
        json.dump({"dates": sorted(list(disabled_dates))}, f, ensure_ascii=False, indent=2)
    
    return {"success": True, "message": f"Квиз для {quiz_date} {action}", "disabled": quiz_date not in disabled_dates}

