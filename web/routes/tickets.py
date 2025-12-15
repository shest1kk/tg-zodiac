"""
Роуты для управления билетиками
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, and_
from database import AsyncSessionLocal, QuizResult, RaffleParticipant
from web.auth import get_current_user

router = APIRouter()

@router.get("/stats")
async def get_ticket_stats(username: str = Depends(get_current_user)):
    """Получить статистику по билетикам"""
    async with AsyncSessionLocal() as session:
        # Общее количество
        total_quiz = await session.scalar(
            select(func.count(QuizResult.ticket_number)).where(
                QuizResult.ticket_number.isnot(None)
            )
        )
        total_raffle = await session.scalar(
            select(func.count(RaffleParticipant.ticket_number)).where(
                RaffleParticipant.ticket_number.isnot(None)
            )
        )
        
        # Минимум и максимум
        min_quiz = await session.scalar(
            select(func.min(QuizResult.ticket_number)).where(
                QuizResult.ticket_number.isnot(None)
            )
        )
        max_quiz = await session.scalar(
            select(func.max(QuizResult.ticket_number)).where(
                QuizResult.ticket_number.isnot(None)
            )
        )
        min_raffle = await session.scalar(
            select(func.min(RaffleParticipant.ticket_number)).where(
                RaffleParticipant.ticket_number.isnot(None)
            )
        )
        max_raffle = await session.scalar(
            select(func.max(RaffleParticipant.ticket_number)).where(
                RaffleParticipant.ticket_number.isnot(None)
            )
        )
        
        min_ticket = None
        max_ticket = None
        if min_quiz is not None:
            min_ticket = min_quiz
        if min_raffle is not None:
            if min_ticket is None or min_raffle < min_ticket:
                min_ticket = min_raffle
        
        if max_quiz is not None:
            max_ticket = max_quiz
        if max_raffle is not None:
            if max_ticket is None or max_raffle > max_ticket:
                max_ticket = max_raffle
        
        # Дубли
        quiz_duplicates = await session.execute(
            select(
                QuizResult.ticket_number,
                func.count(QuizResult.ticket_number).label('count')
            ).where(
                QuizResult.ticket_number.isnot(None)
            ).group_by(QuizResult.ticket_number).having(func.count(QuizResult.ticket_number) > 1)
        )
        
        raffle_duplicates = await session.execute(
            select(
                RaffleParticipant.ticket_number,
                func.count(RaffleParticipant.ticket_number).label('count')
            ).where(
                RaffleParticipant.ticket_number.isnot(None)
            ).group_by(RaffleParticipant.ticket_number).having(func.count(RaffleParticipant.ticket_number) > 1)
        )
        
        # Дубли между таблицами
        quiz_tickets = await session.execute(
            select(QuizResult.ticket_number).where(QuizResult.ticket_number.isnot(None)).distinct()
        )
        quiz_set = {t[0] for t in quiz_tickets.all()}
        
        raffle_tickets = await session.execute(
            select(RaffleParticipant.ticket_number).where(RaffleParticipant.ticket_number.isnot(None)).distinct()
        )
        raffle_set = {t[0] for t in raffle_tickets.all()}
        
        cross_duplicates = list(quiz_set & raffle_set)
        
        return {
            "total": (total_quiz or 0) + (total_raffle or 0),
            "from_quiz": total_quiz or 0,
            "from_raffle": total_raffle or 0,
            "min": min_ticket,
            "max": max_ticket,
            "duplicates": {
                "in_quiz": len(quiz_duplicates.all()),
                "in_raffle": len(raffle_duplicates.all()),
                "cross_table": len(cross_duplicates)
            }
        }

@router.get("/duplicates")
async def get_duplicates(username: str = Depends(get_current_user)):
    """Получить список всех дублей"""
    async with AsyncSessionLocal() as session:
        # Дубли в квизах
        quiz_dups = await session.execute(
            select(
                QuizResult.ticket_number,
                func.count(QuizResult.ticket_number).label('count')
            ).where(
                QuizResult.ticket_number.isnot(None)
            ).group_by(QuizResult.ticket_number).having(func.count(QuizResult.ticket_number) > 1)
        )
        
        # Дубли в розыгрышах
        raffle_dups = await session.execute(
            select(
                RaffleParticipant.ticket_number,
                func.count(RaffleParticipant.ticket_number).label('count')
            ).where(
                RaffleParticipant.ticket_number.isnot(None)
            ).group_by(RaffleParticipant.ticket_number).having(func.count(RaffleParticipant.ticket_number) > 1)
        )
        
        # Дубли между таблицами
        quiz_tickets = await session.execute(
            select(QuizResult.ticket_number).where(QuizResult.ticket_number.isnot(None)).distinct()
        )
        quiz_set = {t[0] for t in quiz_tickets.all()}
        
        raffle_tickets = await session.execute(
            select(RaffleParticipant.ticket_number).where(RaffleParticipant.ticket_number.isnot(None)).distinct()
        )
        raffle_set = {t[0] for t in raffle_tickets.all()}
        
        cross_duplicates = list(quiz_set & raffle_set)
        
        duplicates = []
        
        # Обрабатываем дубли из квизов
        for ticket_num, count in quiz_dups.all():
            users_query = await session.execute(
                select(QuizResult.user_id).where(QuizResult.ticket_number == ticket_num).distinct()
            )
            user_ids = [u[0] for u in users_query.all()]
            duplicates.append({
                "ticket_number": ticket_num,
                "count": count,
                "user_ids": user_ids,
                "source": "quiz"
            })
        
        # Обрабатываем дубли из розыгрышей
        for ticket_num, count in raffle_dups.all():
            users_query = await session.execute(
                select(RaffleParticipant.user_id).where(RaffleParticipant.ticket_number == ticket_num).distinct()
            )
            user_ids = [u[0] for u in users_query.all()]
            duplicates.append({
                "ticket_number": ticket_num,
                "count": count,
                "user_ids": user_ids,
                "source": "raffle"
            })
        
        # Обрабатываем дубли между таблицами
        for ticket_num in cross_duplicates:
            quiz_users = await session.execute(
                select(QuizResult.user_id).where(QuizResult.ticket_number == ticket_num).distinct()
            )
            raffle_users = await session.execute(
                select(RaffleParticipant.user_id).where(RaffleParticipant.ticket_number == ticket_num).distinct()
            )
            user_ids = list(set([u[0] for u in quiz_users.all()] + [u[0] for u in raffle_users.all()]))
            duplicates.append({
                "ticket_number": ticket_num,
                "count": len(user_ids),
                "user_ids": user_ids,
                "source": "cross_table"
            })
        
        return {"duplicates": duplicates}

@router.delete("/{user_id}/{ticket_number}")
async def remove_ticket(user_id: int, ticket_number: int, username: str = Depends(get_current_user)):
    """Удалить билетик у пользователя"""
    async with AsyncSessionLocal() as session:
        # Ищем в квизах
        quiz_result = await session.execute(
            select(QuizResult).where(
                and_(
                    QuizResult.user_id == user_id,
                    QuizResult.ticket_number == ticket_number
                )
            )
        )
        quiz_ticket = quiz_result.scalar_one_or_none()
        
        # Ищем в розыгрышах
        raffle_result = await session.execute(
            select(RaffleParticipant).where(
                and_(
                    RaffleParticipant.user_id == user_id,
                    RaffleParticipant.ticket_number == ticket_number
                )
            )
        )
        raffle_ticket = raffle_result.scalar_one_or_none()
        
        if not quiz_ticket and not raffle_ticket:
            raise HTTPException(status_code=404, detail="Билетик не найден")
        
        if quiz_ticket:
            quiz_ticket.ticket_number = None
        if raffle_ticket:
            raffle_ticket.ticket_number = None
        
        await session.commit()
        
        return {"success": True, "message": f"Билетик №{ticket_number} удален у пользователя {user_id}"}

@router.get("/user/{user_id}")
async def get_user_tickets(user_id: int, username: str = Depends(get_current_user)):
    """Получить все билетики пользователя"""
    async with AsyncSessionLocal() as session:
        quiz_tickets = await session.execute(
            select(QuizResult).where(
                and_(
                    QuizResult.user_id == user_id,
                    QuizResult.ticket_number.isnot(None)
                )
            ).order_by(QuizResult.ticket_number.asc())
        )
        
        raffle_tickets = await session.execute(
            select(RaffleParticipant).where(
                and_(
                    RaffleParticipant.user_id == user_id,
                    RaffleParticipant.ticket_number.isnot(None)
                )
            ).order_by(RaffleParticipant.ticket_number.asc())
        )
        
        tickets = []
        for ticket in quiz_tickets.scalars().all():
            tickets.append({
                "ticket_number": ticket.ticket_number,
                "source": "quiz",
                "date": ticket.quiz_date,
                "completed_at": ticket.completed_at.isoformat() if ticket.completed_at else None
            })
        
        for ticket in raffle_tickets.scalars().all():
            tickets.append({
                "ticket_number": ticket.ticket_number,
                "source": "raffle",
                "date": ticket.raffle_date,
                "timestamp": ticket.timestamp.isoformat() if ticket.timestamp else None
            })
        
        tickets.sort(key=lambda x: x["ticket_number"])
        
        return {"user_id": user_id, "tickets": tickets}

@router.get("/check_time/{ticket_number}")
async def check_ticket_time(ticket_number: int, username: str = Depends(get_current_user)):
    """Проверить время выдачи билетика"""
    from datetime import datetime, timezone, timedelta
    
    async with AsyncSessionLocal() as session:
        # Ищем билетики в квизах
        quiz_result = await session.execute(
            select(QuizResult).where(
                QuizResult.ticket_number == ticket_number
            ).order_by(QuizResult.completed_at.asc())
        )
        quiz_tickets = quiz_result.scalars().all()
        
        # Ищем билетики в розыгрышах
        raffle_result = await session.execute(
            select(RaffleParticipant).where(
                RaffleParticipant.ticket_number == ticket_number
            ).order_by(RaffleParticipant.timestamp.asc())
        )
        raffle_tickets = raffle_result.scalars().all()
        
        if not quiz_tickets and not raffle_tickets:
            raise HTTPException(status_code=404, detail=f"Билетик №{ticket_number} не найден")
        
        moscow_tz = timezone(timedelta(hours=3))
        all_tickets = []
        
        # Обрабатываем квизы
        for ticket in quiz_tickets:
            try:
                date_obj = datetime.strptime(ticket.quiz_date, "%Y-%m-%d")
                date_display = date_obj.strftime("%d.%m.%Y")
            except:
                date_display = ticket.quiz_date
            
            if ticket.completed_at:
                if ticket.completed_at.tzinfo is None:
                    utc_time = ticket.completed_at.replace(tzinfo=timezone.utc)
                    moscow_time = utc_time.astimezone(moscow_tz)
                else:
                    moscow_time = ticket.completed_at.astimezone(moscow_tz)
                time_display = moscow_time.strftime("%d.%m.%Y %H:%M:%S МСК")
            else:
                time_display = "неизвестно"
            
            all_tickets.append({
                'user_id': ticket.user_id,
                'source': 'квиз',
                'date': date_display,
                'time': ticket.completed_at.isoformat() if ticket.completed_at else None,
                'time_display': time_display,
                'db_id': ticket.id
            })
        
        # Обрабатываем розыгрыши
        for ticket in raffle_tickets:
            try:
                date_obj = datetime.strptime(ticket.raffle_date, "%Y-%m-%d")
                date_display = date_obj.strftime("%d.%m.%Y")
            except:
                date_display = ticket.raffle_date
            
            if ticket.timestamp:
                if ticket.timestamp.tzinfo is None:
                    utc_time = ticket.timestamp.replace(tzinfo=timezone.utc)
                    moscow_time = utc_time.astimezone(moscow_tz)
                else:
                    moscow_time = ticket.timestamp.astimezone(moscow_tz)
                time_display = moscow_time.strftime("%d.%m.%Y %H:%M:%S МСК") + " (время вопроса, билетик выдан позже)"
            else:
                time_display = "неизвестно"
            
            all_tickets.append({
                'user_id': ticket.user_id,
                'source': 'розыгрыш',
                'date': date_display,
                'time': ticket.timestamp.isoformat() if ticket.timestamp else None,
                'time_display': time_display,
                'db_id': ticket.id
            })
        
        # Сортируем по времени
        all_tickets.sort(key=lambda x: (
            x['time'] if x['time'] else datetime.min.isoformat(),
            x.get('db_id', 0)
        ))
        
        same_time = len(all_tickets) > 1 and all_tickets[0]['time'] == all_tickets[1]['time']
        first_user = all_tickets[0] if all_tickets else None
        
        return {
            "ticket_number": ticket_number,
            "tickets": all_tickets,
            "first_user": {
                "user_id": first_user['user_id'],
                "source": first_user['source']
            } if first_user else None,
            "same_time": same_time
        }

