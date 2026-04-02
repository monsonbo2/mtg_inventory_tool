"""Typed membership models for inventory access helpers."""

from __future__ import annotations

from dataclasses import dataclass

from .response_models import ResponseModel


@dataclass(frozen=True, slots=True)
class InventoryMembershipRow(ResponseModel):
    inventory: str
    actor_id: str
    role: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class InventoryMembershipRemovalResult(ResponseModel):
    inventory: str
    actor_id: str
    role: str
