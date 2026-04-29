"""Minimal demo routes built directly on the inventory service facade."""

from __future__ import annotations

from fastapi import APIRouter

from .audit import router as audit_router
from .catalog import router as catalog_router
from .health import router as health_router
from .imports import router as imports_router
from .inventories import router as inventories_router
from .memberships import router as memberships_router
from .owned_items import router as owned_items_router
from .sharing import router as sharing_router


router = APIRouter()
router.include_router(health_router)
router.include_router(inventories_router)
router.include_router(imports_router)
router.include_router(memberships_router)
router.include_router(sharing_router)
router.include_router(catalog_router)
router.include_router(owned_items_router)
router.include_router(audit_router)
