"""
Роуты для управления пользователями
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func
from database import AsyncSessionLocal, User
from web.auth import get_current_user

router = APIRouter()

@router.get("/")
async def get_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    username: str = Depends(get_current_user)
):
    """Получить список пользователей"""
    async with AsyncSessionLocal() as session:
        total = await session.scalar(select(func.count(User.id)))
        
        users_query = await session.execute(
            select(User).offset(skip).limit(limit).order_by(User.created_at.desc())
        )
        users = users_query.scalars().all()
        
        result = []
        for user in users:
            result.append({
                "id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "zodiac": user.zodiac,
                "subscribed": user.subscribed,
                "registration_completed": user.registration_completed,
                "created_at": user.created_at.isoformat() if user.created_at else None
            })
        
        return {
            "total": total,
            "skip": skip,
            "limit": limit,
            "users": result
        }

@router.get("/{user_id}")
async def get_user(user_id: int, username: str = Depends(get_current_user)):
    """Получить информацию о пользователе"""
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        return {
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "zodiac": user.zodiac,
            "subscribed": user.subscribed,
            "registration_completed": user.registration_completed,
            "registration_status": user.registration_status,
            "created_at": user.created_at.isoformat() if user.created_at else None
        }

@router.get("/stats/overview")
async def get_users_stats(username: str = Depends(get_current_user)):
    """Получить общую статистику по пользователям"""
    async with AsyncSessionLocal() as session:
        total = await session.scalar(select(func.count(User.id)))
        subscribed = await session.scalar(
            select(func.count(User.id)).where(User.subscribed == True)
        )
        registered = await session.scalar(
            select(func.count(User.id)).where(User.registration_completed == True)
        )
        
        return {
            "total": total,
            "subscribed": subscribed,
            "not_subscribed": total - subscribed,
            "registered": registered,
            "not_registered": total - registered
        }

@router.get("/new")
async def get_new_users(
    days: int = Query(1, ge=1, le=30),
    limit: int = Query(100, ge=1, le=500),
    username: str = Depends(get_current_user)
):
    """Получить список новых пользователей"""
    from datetime import datetime, timedelta
    async with AsyncSessionLocal() as session:
        cutoff_date = datetime.now() - timedelta(days=days)
        
        users_query = await session.execute(
            select(User).where(
                User.created_at >= cutoff_date
            ).order_by(User.created_at.desc()).limit(limit)
        )
        users = users_query.scalars().all()
        
        result = []
        for user in users:
            result.append({
                "id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "zodiac": user.zodiac,
                "subscribed": user.subscribed,
                "registration_completed": user.registration_completed,
                "created_at": user.created_at.isoformat() if user.created_at else None
            })
        
        return {"users": result, "count": len(result)}

@router.get("/registered")
async def get_registered_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    username: str = Depends(get_current_user)
):
    """Получить список авторизованных пользователей"""
    async with AsyncSessionLocal() as session:
        total = await session.scalar(
            select(func.count(User.id)).where(User.registration_completed == True)
        )
        
        users_query = await session.execute(
            select(User).where(
                User.registration_completed == True
            ).offset(skip).limit(limit).order_by(User.created_at.desc())
        )
        users = users_query.scalars().all()
        
        result = []
        for user in users:
            result.append({
                "id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "zodiac": user.zodiac,
                "subscribed": user.subscribed,
                "created_at": user.created_at.isoformat() if user.created_at else None
            })
        
        return {
            "total": total,
            "skip": skip,
            "limit": limit,
            "users": result
        }

