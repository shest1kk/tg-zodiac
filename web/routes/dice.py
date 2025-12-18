"""
API роуты для управления Dice (игральный кубик)
"""
from fastapi import APIRouter, Depends, HTTPException, Body
from typing import List, Dict, Optional
from web.auth import get_current_user
from dice import (
    load_all_dice_data, get_all_dice_events, get_dice_event,
    create_dice_event, update_dice_event, delete_dice_event,
    get_dice_start_datetime_moscow
)

router = APIRouter()


@router.get("/list")
async def get_dice_list(username: str = Depends(get_current_user)):
    """Получает список всех событий dice"""
    try:
        all_data = load_all_dice_data()
        if not all_data or "dice_events" not in all_data:
            return {"dice_events": []}
        
        dice_events = []
        for dice_id, event_data in all_data["dice_events"].items():
            starts_at = get_dice_start_datetime_moscow(dice_id)
            starts_at_msk = starts_at.strftime("%Y-%m-%d %H:%M") if starts_at else None
            
            dice_events.append({
                "dice_id": dice_id,
                "title": event_data.get("title", ""),
                "starts_at": event_data.get("starts_at"),
                "starts_at_msk": starts_at_msk,
                "enabled": event_data.get("enabled", True)
            })
        
        # Сортируем по дате старта
        dice_events.sort(key=lambda x: x.get("starts_at", ""))
        
        return {"dice_events": dice_events}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при получении списка dice: {str(e)}")


@router.get("/{dice_id}")
async def get_dice_details(dice_id: str, username: str = Depends(get_current_user)):
    """Получает детали события dice"""
    try:
        event = get_dice_event(dice_id)
        if not event:
            raise HTTPException(status_code=404, detail="Событие dice не найдено")
        
        starts_at = get_dice_start_datetime_moscow(dice_id)
        starts_at_msk = starts_at.strftime("%Y-%m-%dT%H:%M") if starts_at else None
        
        return {
            "dice_id": dice_id,
            "title": event.get("title", ""),
            "starts_at": event.get("starts_at"),
            "starts_at_msk": starts_at_msk,
            "enabled": event.get("enabled", True)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при получении события dice: {str(e)}")


@router.post("/create")
async def create_dice(data: dict = Body(...), username: str = Depends(get_current_user)):
    """Создает новое событие dice"""
    try:
        dice_id = data.get("dice_id", "").strip()
        starts_at_local = data.get("starts_at_local", "").strip()
        title = data.get("title", "").strip()
        
        if not dice_id:
            raise HTTPException(status_code=400, detail="dice_id обязателен")
        if not starts_at_local:
            raise HTTPException(status_code=400, detail="starts_at_local обязателен")
        if not title:
            raise HTTPException(status_code=400, detail="title обязателен")
        
        result = create_dice_event(dice_id, starts_at_local, title)
        if result.get("success"):
            # Автоматически планируем dice в scheduler
            from scheduler import reschedule_dice_jobs_if_running
            reschedule_dice_jobs_if_running(dice_id)
            return {"success": True, "dice_id": dice_id, "message": "Событие dice создано"}
        else:
            raise HTTPException(status_code=400, detail=result.get("error", "Не удалось создать событие"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при создании события dice: {str(e)}")


@router.put("/{dice_id}")
async def update_dice(dice_id: str, data: dict = Body(...), username: str = Depends(get_current_user)):
    """Обновляет событие dice"""
    try:
        starts_at_local = data.get("starts_at_local")
        title = data.get("title")
        enabled = data.get("enabled")
        
        result = update_dice_event(
            dice_id,
            starts_at_local=starts_at_local,
            title=title,
            enabled=enabled
        )
        
        if result.get("success"):
            # Автоматически перепланируем dice в scheduler
            from scheduler import reschedule_dice_jobs_if_running
            reschedule_dice_jobs_if_running(dice_id)
            return {"success": True, "message": "Событие dice обновлено"}
        else:
            raise HTTPException(status_code=400, detail=result.get("error", "Не удалось обновить событие"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при обновлении события dice: {str(e)}")


@router.delete("/{dice_id}")
async def delete_dice(dice_id: str, username: str = Depends(get_current_user)):
    """Удаляет событие dice"""
    try:
        result = delete_dice_event(dice_id)
        if result.get("success"):
            return {"success": True, "message": f"Событие dice {dice_id} удалено"}
        else:
            raise HTTPException(status_code=404, detail=result.get("error", "Событие не найдено"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при удалении события dice: {str(e)}")


@router.post("/{dice_id}/toggle")
async def toggle_dice(dice_id: str, username: str = Depends(get_current_user)):
    """Включает/выключает событие dice"""
    try:
        event = get_dice_event(dice_id)
        if not event:
            raise HTTPException(status_code=404, detail="Событие dice не найдено")
        
        current_enabled = event.get("enabled", True)
        result = update_dice_event(dice_id, enabled=not current_enabled)
        
        if result.get("success"):
            return {
                "success": True,
                "enabled": not current_enabled,
                "message": f"Событие dice {'включено' if not current_enabled else 'отключено'}"
            }
        else:
            raise HTTPException(status_code=400, detail=result.get("error", "Не удалось изменить статус"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при изменении статуса dice: {str(e)}")

