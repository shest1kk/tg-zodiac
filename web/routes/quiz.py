"""
Роуты для управления квизами
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from database import AsyncSessionLocal, Quiz, QuizResult, QuizParticipant
from web.auth import verify_admin

router = APIRouter()

@router.get("/dates")
async def get_quiz_dates(admin_id: int = Depends(verify_admin)):
    """Получить список дат квизов"""
    from quiz import get_all_quiz_dates
    dates = get_all_quiz_dates()
    return {"dates": dates}

@router.get("/{quiz_date}/stats")
async def get_quiz_stats(quiz_date: str, admin_id: int = Depends(verify_admin)):
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
    admin_id: int = Depends(verify_admin)
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

