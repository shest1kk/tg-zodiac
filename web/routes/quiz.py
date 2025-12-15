"""
Роуты для управления квизами
"""
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy import select, func, and_
from database import AsyncSessionLocal, Quiz, QuizResult, QuizParticipant
from web.auth import get_current_user

router = APIRouter()

@router.get("/dates")
async def get_quiz_dates(username: str = Depends(get_current_user)):
    """Получить список дат квизов"""
    from quiz import get_all_quiz_dates
    dates = get_all_quiz_dates()
    return {"dates": dates}

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

