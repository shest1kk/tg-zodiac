"""
Роуты для статистики
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta
from database import AsyncSessionLocal, User, QuizResult, RaffleParticipant
from web.auth import verify_admin

router = APIRouter()

@router.get("/system")
async def get_system_stats(admin_id: int = Depends(verify_admin)):
    """Получить статистику системы"""
    async with AsyncSessionLocal() as session:
        # Пользователи
        total_users = await session.scalar(select(func.count(User.id)))
        subscribed = await session.scalar(
            select(func.count(User.id)).where(User.subscribed == True)
        )
        
        # Активные за 24 часа
        day_ago = datetime.now() - timedelta(days=1)
        active_24h = await session.scalar(
            select(func.count(func.distinct(User.id))).where(
                User.created_at >= day_ago
            )
        )
        
        # Билетики
        total_tickets_quiz = await session.scalar(
            select(func.count(QuizResult.ticket_number)).where(
                QuizResult.ticket_number.isnot(None)
            )
        )
        total_tickets_raffle = await session.scalar(
            select(func.count(RaffleParticipant.ticket_number)).where(
                RaffleParticipant.ticket_number.isnot(None)
            )
        )
        
        return {
            "users": {
                "total": total_users,
                "subscribed": subscribed,
                "active_24h": active_24h
            },
            "tickets": {
                "total": (total_tickets_quiz or 0) + (total_tickets_raffle or 0),
                "from_quiz": total_tickets_quiz or 0,
                "from_raffle": total_tickets_raffle or 0
            }
        }

@router.get("/daily")
async def get_daily_report(admin_id: int = Depends(verify_admin)):
    """Ежедневный отчет"""
    async with AsyncSessionLocal() as session:
        today = datetime.now().date()
        
        # Новые пользователи
        new_users = await session.scalar(
            select(func.count(User.id)).where(
                func.date(User.created_at) == today
            )
        )
        
        # Билетики за сегодня
        tickets_quiz = await session.scalar(
            select(func.count(QuizResult.ticket_number)).where(
                and_(
                    QuizResult.ticket_number.isnot(None),
                    func.date(QuizResult.completed_at) == today
                )
            )
        )
        
        tickets_raffle = await session.scalar(
            select(func.count(RaffleParticipant.ticket_number)).where(
                and_(
                    RaffleParticipant.ticket_number.isnot(None),
                    func.date(RaffleParticipant.timestamp) == today
                )
            )
        )
        
        # Активность
        quiz_participants = await session.scalar(
            select(func.count(QuizResult.id)).where(
                func.date(QuizResult.completed_at) == today
            )
        )
        
        raffle_participants = await session.scalar(
            select(func.count(RaffleParticipant.id)).where(
                func.date(RaffleParticipant.timestamp) == today
            )
        )
        
        return {
            "date": today.isoformat(),
            "new_users": new_users or 0,
            "tickets": {
                "total": (tickets_quiz or 0) + (tickets_raffle or 0),
                "from_quiz": tickets_quiz or 0,
                "from_raffle": tickets_raffle or 0
            },
            "activity": {
                "quiz_participants": quiz_participants or 0,
                "raffle_participants": raffle_participants or 0
            }
        }

@router.get("/weekly")
async def get_weekly_report(admin_id: int = Depends(verify_admin)):
    """Еженедельный отчет"""
    async with AsyncSessionLocal() as session:
        today = datetime.now().date()
        week_ago = today - timedelta(days=7)
        
        # Новые пользователи
        new_users = await session.scalar(
            select(func.count(User.id)).where(
                User.created_at >= datetime.combine(week_ago, datetime.min.time())
            )
        )
        
        # Билетики
        tickets_quiz = await session.scalar(
            select(func.count(QuizResult.ticket_number)).where(
                and_(
                    QuizResult.ticket_number.isnot(None),
                    QuizResult.completed_at >= datetime.combine(week_ago, datetime.min.time())
                )
            )
        )
        
        tickets_raffle = await session.scalar(
            select(func.count(RaffleParticipant.ticket_number)).where(
                and_(
                    RaffleParticipant.ticket_number.isnot(None),
                    RaffleParticipant.timestamp >= datetime.combine(week_ago, datetime.min.time())
                )
            )
        )
        
        # Активность
        quiz_participants = await session.scalar(
            select(func.count(QuizResult.id)).where(
                QuizResult.completed_at >= datetime.combine(week_ago, datetime.min.time())
            )
        )
        
        raffle_participants = await session.scalar(
            select(func.count(RaffleParticipant.id)).where(
                RaffleParticipant.timestamp >= datetime.combine(week_ago, datetime.min.time())
            )
        )
        
        return {
            "period": {
                "from": week_ago.isoformat(),
                "to": today.isoformat()
            },
            "new_users": {
                "total": new_users or 0,
                "avg_per_day": (new_users or 0) / 7
            },
            "tickets": {
                "total": (tickets_quiz or 0) + (tickets_raffle or 0),
                "from_quiz": tickets_quiz or 0,
                "from_raffle": tickets_raffle or 0,
                "avg_per_day": ((tickets_quiz or 0) + (tickets_raffle or 0)) / 7
            },
            "activity": {
                "quiz_participants": quiz_participants or 0,
                "raffle_participants": raffle_participants or 0
            }
        }

