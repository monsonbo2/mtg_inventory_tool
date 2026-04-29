from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from ..dependencies import ApiSettings, get_settings
from ..response_models import HealthResponse
from ._common import _error_responses

router = APIRouter()


@router.get("/health", response_model=HealthResponse, responses=_error_responses(500))
def health(settings: Annotated[ApiSettings, Depends(get_settings)]) -> dict[str, Any]:
    return {
        "status": "ok",
        "auto_migrate": settings.auto_migrate,
        "trusted_actor_headers": settings.trust_actor_headers,
    }
