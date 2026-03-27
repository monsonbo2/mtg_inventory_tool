from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class InventoryDefinition:
    inventory_name: str
    description: str | None = None


@dataclass(slots=True)
class InventoryField:
    field_name: str
    field_type: str = "string"
    required: bool = False
    default_value: str | None = None
    display_order: int = 0


@dataclass(slots=True)
class InventoryItem:
    inventory_name: str
    values: dict[str, str]
