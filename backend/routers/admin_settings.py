from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.core.config import get_settings
from backend.core.deps import require_role
from backend.core.enums import UserRole

router = APIRouter(
    prefix="/admin/settings", tags=["Admin Settings"], dependencies=[Depends(require_role(UserRole.ADMIN))]
)


class SettingsResponse(BaseModel):
    verifier_threshold_sale: float


class SettingsUpdateRequest(BaseModel):
    verifier_threshold_sale: float | None = None


@router.get("", response_model=SettingsResponse)
async def get_settings_values() -> SettingsResponse:
    settings = get_settings()
    return SettingsResponse(verifier_threshold_sale=settings.verifier_threshold_sale)


@router.put("", response_model=SettingsResponse)
async def update_settings_values(payload: SettingsUpdateRequest) -> SettingsResponse:
    """Not implemented: the Verifier threshold is env-configured, not editable at runtime.

    This used to echo the submitted value back with 200 OK while storing nothing. `Settings`
    is a process-wide, env-driven, `@lru_cache`d object, so there was nowhere for the value
    to go. The Admin saw "Đã lưu" and believed they had moved the threshold that decides
    when the AI refuses to answer — the one setting where a silent no-op is actively unsafe.

    Failing loudly is the honest behaviour until the value has somewhere durable to live
    (a settings table, read at the three `get_settings().verifier_threshold_sale` call
    sites). Until then it is changed via VERIFIER_THRESHOLD_SALE and a restart.
    """
    del payload
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Ngưỡng Verifier hiện được cấu hình qua biến môi trường VERIFIER_THRESHOLD_SALE "
            "và chỉ đổi được khi khởi động lại dịch vụ."
        ),
    )
