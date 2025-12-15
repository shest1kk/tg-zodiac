"""
Роуты для управления розыгрышами
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, and_
from database import AsyncSessionLocal, Raffle, RaffleParticipant
from web.auth import verify_admin

router = APIRouter()

@router.get("/dates")
async def get_raffle_dates(username: str = Depends(verify_admin)):
    """Получить список дат розыгрышей"""
    from raffle import get_all_raffle_dates
    dates = get_all_raffle_dates()
    return {"dates": dates}

@router.get("/{raffle_date}/stats")
async def get_raffle_stats(raffle_date: str, username: str = Depends(verify_admin)):
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
    username: str = Depends(verify_admin)
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
    username: str = Depends(verify_admin)
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
    username: str = Depends(verify_admin)
):
    """Отклонить ответ пользователя"""
    from raffle import deny_answer as deny
    
    success = await deny(user_id, raffle_date)
    if not success:
        raise HTTPException(status_code=400, detail="Не удалось отклонить ответ")
    
    return {"success": True, "message": f"Ответ пользователя {user_id} отклонен"}

