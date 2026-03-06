from __future__ import annotations

from datetime import date, timedelta

from .models import MonthSlice, WindowSpec


def build_window(today: date) -> WindowSpec:
    current_month_start = today.replace(day=1)
    start_date = add_months(current_month_start, -3)
    months: list[MonthSlice] = []

    cursor = start_date
    while cursor <= current_month_start:
        next_month = add_months(cursor, 1)
        months.append(
            MonthSlice(
                key=cursor.strftime("%Y%m"),
                start_date=cursor,
                end_date=next_month - timedelta(days=1),
                is_current=cursor == current_month_start,
            )
        )
        cursor = next_month

    return WindowSpec(start_date=start_date, end_date=today, months=months)


def add_months(value: date, delta_months: int) -> date:
    total_months = value.year * 12 + value.month - 1 + delta_months
    year = total_months // 12
    month = total_months % 12 + 1
    return date(year, month, 1)

