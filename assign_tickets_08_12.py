"""
Скрипт для назначения билетов участникам розыгрыша от 08.12.2025
Билеты назначаются начиная с 99 и по убыванию (99, 98, 97, ...)
"""
import asyncio
import logging
from sqlalchemy import select, and_
from database import AsyncSessionLocal, RaffleParticipant, init_db
from config import logger

async def assign_tickets():
    """Назначает билеты участникам розыгрыша от 2025-12-08"""
    raffle_date = "2025-12-08"
    start_ticket = 99
    
    try:
        async with AsyncSessionLocal() as session:
            # Получаем всех участников розыгрыша от 08.12, у которых ответ принят (is_correct = True)
            # и еще не назначен билет (ticket_number IS NULL)
            # Сортируем по timestamp (время участия) для определения порядка
            result = await session.execute(
                select(RaffleParticipant).where(
                    and_(
                        RaffleParticipant.raffle_date == raffle_date,
                        RaffleParticipant.is_correct == True,
                        RaffleParticipant.ticket_number.is_(None)
                    )
                ).order_by(RaffleParticipant.timestamp.asc())
            )
            participants = result.scalars().all()
            
            if not participants:
                logger.info(f"Не найдено участников розыгрыша от {raffle_date} с принятыми ответами без билетов")
                return
            
            logger.info(f"Найдено {len(participants)} участников для назначения билетов")
            
            # Назначаем билеты начиная с 99 и по убыванию
            assigned_count = 0
            current_ticket = start_ticket
            
            for participant in participants:
                if current_ticket < 1:
                    logger.warning(f"Достигнут минимальный номер билета (1). Осталось {len(participants) - assigned_count} участников без билетов")
                    break
                
                participant.ticket_number = current_ticket
                logger.info(f"Назначен билет №{current_ticket} пользователю {participant.user_id} (участник ID: {participant.id})")
                assigned_count += 1
                current_ticket -= 1
            
            if assigned_count > 0:
                await session.commit()
                logger.info(f"✅ Успешно назначено {assigned_count} билетов для розыгрыша от {raffle_date}")
                if assigned_count > 0:
                    last_ticket = start_ticket - assigned_count + 1
                    logger.info(f"📋 Диапазон билетов: №{start_ticket} → №{last_ticket}")
            else:
                logger.info("ℹ️ Не было участников для назначения билетов")
            
    except Exception as e:
        logger.error(f"Ошибка при назначении билетов: {e}", exc_info=True)
        raise

async def main():
    """Главная функция"""
    await init_db()
    await assign_tickets()

if __name__ == "__main__":
    asyncio.run(main())

