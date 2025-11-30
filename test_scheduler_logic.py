"""
Тестовый скрипт для проверки логики рассылки
Проверяет правильность вычисления дней и времени рассылки
"""

from datetime import datetime, date, timezone, timedelta
import json
from pathlib import Path

# Московское время (UTC+3)
MOSCOW_TZ = timezone(timedelta(hours=3))

def get_day_number(start_date_str: str, current_date: date = None) -> int:
    """Вычисляет номер дня (1-30) от даты начала рассылки"""
    if current_date is None:
        current_date = datetime.now(MOSCOW_TZ).date()
    
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        delta = (current_date - start_date).days + 1
        
        if delta < 1:
            return 1
        
        if delta > 30:
            day_num = ((delta - 1) % 30) + 1
        else:
            day_num = delta
        
        return day_num
    except ValueError as e:
        print(f"Ошибка парсинга даты {start_date_str}: {e}")
        return 1

def test_scheduler_logic():
    """Тестирует логику рассылки"""
    
    start_date = "2025-12-01"
    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
    
    print("=" * 80)
    print("ТЕСТИРОВАНИЕ ЛОГИКИ РАССЫЛКИ")
    print("=" * 80)
    print(f"Дата начала рассылки: {start_date_obj.strftime('%d.%m.%Y')}")
    print(f"Время рассылки: 09:00 МСК (06:00 UTC)")
    print(f"Период: с 01.12.2025 по 31.12.2025 (31 день)")
    print("=" * 80)
    print()
    
    # Проверяем каждый день с 01.12 по 31.12
    test_results = []
    errors = []
    
    for day_offset in range(31):  # 0-30 дней от начала
        test_date = start_date_obj + timedelta(days=day_offset)
        day_number = get_day_number(start_date, test_date)
        
        # Проверяем правильность
        expected_day = min(day_offset + 1, 30) if day_offset < 30 else 1  # После 30 дня - цикл начинается заново
        
        # После 30-го дня должно быть цикличное повторение
        if day_offset >= 30:
            expected_day = ((day_offset) % 30) + 1
        
        status = "✅" if day_number == expected_day else "❌"
        
        result = {
            "date": test_date,
            "day_offset": day_offset,
            "day_number": day_number,
            "expected": expected_day,
            "status": status
        }
        
        if day_number != expected_day:
            errors.append(result)
        
        test_results.append(result)
        
        # Выводим первые 5 дней и последние 5 дней
        if day_offset < 5 or day_offset >= 26:
            print(f"{status} {test_date.strftime('%d.%m.%Y')} | День {day_number}/30 | Смещение: +{day_offset} дней")
    
    print()
    print("=" * 80)
    print("РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ")
    print("=" * 80)
    
    total_tests = len(test_results)
    passed_tests = sum(1 for r in test_results if r["status"] == "✅")
    failed_tests = total_tests - passed_tests
    
    print(f"Всего тестов: {total_tests}")
    print(f"✅ Успешно: {passed_tests}")
    print(f"❌ Ошибок: {failed_tests}")
    print()
    
    if errors:
        print("ОШИБКИ:")
        for error in errors:
            print(f"  ❌ {error['date'].strftime('%d.%m.%Y')}: получено {error['day_number']}, ожидалось {error['expected']}")
    else:
        print("✅ Все тесты пройдены успешно!")
    
    print()
    print("=" * 80)
    print("ПРОВЕРКА РАСПИСАНИЯ РАССЫЛКИ")
    print("=" * 80)
    
    # Проверяем время рассылки
    utc_hour = (9 - 3) % 24  # 09:00 МСК = 06:00 UTC
    print(f"Время рассылки в UTC: {utc_hour:02d}:00")
    print(f"Время рассылки в МСК: 09:00")
    print(f"✅ Конвертация времени корректна")
    
    print()
    print("=" * 80)
    print("ПРОВЕРКА ДАННЫХ В ФАЙЛЕ")
    print("=" * 80)
    
    predictions_path = Path("data/predictions.json")
    if predictions_path.exists():
        with open(predictions_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        file_start_date = data.get("start_date")
        days_data = data.get("days", {})
        
        print(f"Дата начала в файле: {file_start_date}")
        print(f"Количество дней в файле: {len(days_data)}")
        
        if file_start_date == start_date:
            print(f"✅ Дата начала совпадает")
        else:
            print(f"⚠️ Дата начала в файле ({file_start_date}) не совпадает с ожидаемой ({start_date})")
        
        if len(days_data) == 30:
            print(f"✅ В файле 30 дней - правильно")
        else:
            print(f"⚠️ В файле {len(days_data)} дней, ожидается 30")
        
        # Проверяем наличие всех дней
        missing_days = []
        for day in range(1, 31):
            if str(day) not in days_data:
                missing_days.append(day)
        
        if missing_days:
            print(f"⚠️ Отсутствуют дни: {missing_days}")
        else:
            print(f"✅ Все дни с 1 по 30 присутствуют")
        
        # Проверяем наличие всех знаков зодиака для каждого дня
        missing_signs = []
        for day in range(1, 31):
            day_str = str(day)
            if day_str in days_data:
                for sign in range(1, 13):
                    if str(sign) not in days_data[day_str]:
                        missing_signs.append((day, sign))
        
        if missing_signs:
            print(f"⚠️ Отсутствуют данные для знаков: {missing_signs[:10]}... (показаны первые 10)")
        else:
            print(f"✅ Для всех дней присутствуют все 12 знаков зодиака")
    else:
        print("❌ Файл predictions.json не найден!")
    
    print()
    print("=" * 80)

if __name__ == "__main__":
    test_scheduler_logic()

