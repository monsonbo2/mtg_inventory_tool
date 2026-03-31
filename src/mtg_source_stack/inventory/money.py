"""Decimal-based helpers for inventory money values."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def coerce_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, int):
        decimal_value = Decimal(value)
    elif isinstance(value, float):
        decimal_value = Decimal(str(value))
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            decimal_value = Decimal(text)
        except InvalidOperation:
            return None

    if not decimal_value.is_finite():
        return None
    return decimal_value


def parse_decimal_text(value: str | None, *, field_name: str, row_number: int) -> Decimal | None:
    text = value.strip() if value is not None else ""
    if not text:
        return None
    try:
        decimal_value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"CSV row {row_number}: {field_name} must be a number.") from exc
    if not decimal_value.is_finite():
        raise ValueError(f"CSV row {row_number}: {field_name} must be a finite number.")
    return decimal_value


def parse_decimal_argument(value: str) -> Decimal:
    try:
        decimal_value = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("must be a number") from exc
    if not decimal_value.is_finite():
        raise ValueError("must be a finite number")
    return decimal_value


def format_decimal(value: Any) -> str:
    decimal_value = coerce_decimal(value)
    if decimal_value is None:
        return str(value)
    return format(decimal_value, "f")
