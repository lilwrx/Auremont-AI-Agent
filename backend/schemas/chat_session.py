from datetime import datetime

from pydantic import BaseModel


class ChatSessionCreate(BaseModel):
    title: str | None = None
    customer_name: str | None = None
    project_id: str | None = None


class ChatSessionResponse(BaseModel):
    id: int
    sale_id: int | None
    title: str | None = None
    customer_name: str | None = None
    project_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
