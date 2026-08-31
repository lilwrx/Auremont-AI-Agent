from datetime import datetime

from pydantic import BaseModel

from backend.core.enums import MessageEmotion, MessageSender


class Citation(BaseModel):
    document_id: int
    title: str
    qualifier: str | None = None
    page: int | None = None
    y_position: float | None = None


class AnswerImage(BaseModel):
    """One project photo shown in the swipeable strip under an answer."""

    url: str
    project_id: str
    project_name: str


class PropertyListing(BaseModel):
    """One recommended unit, rendered as its own card (with paging arrows between cards)
    instead of as a bullet line in `content` — see prompts.PropertyListing and
    agent_pipeline._resolve_listing_images, which is what fills in `image_urls`/
    `amenities`/`project_id`. All three default empty: a listing whose project/gallery
    could not be resolved is still shown, just without photos or amenity tags.

    `unit_code`/`status`/`tower` are non-empty only for a listing built from one confirmed
    TỒN KHO REAL-TIME record (see prompts.PropertyListing) — a catalogue-only
    project/subdivision summary card leaves all three "".

    `tower` is both what selected `image_urls` (see answer_images_service.select_listing_images)
    and what the card shows, so a viewer can check the photo against the tower it claims.
    """

    project_name: str
    unit_type: str
    area_range: str
    price_range: str
    image_urls: list[str] = []
    amenities: list[str] = []
    project_id: str | None = None
    unit_code: str = ""
    status: str = ""
    tower: str = ""


class MessageCreate(BaseModel):
    session_id: int | None = None
    content: str


class MessageResponse(BaseModel):
    id: int
    session_id: int | None = None
    sender: MessageSender
    content: str
    citations: list[Citation] | None = None
    images: list[AnswerImage] | None = None
    verifier_score: float | None = None
    requires_hitl: bool
    hitl_confirmed: bool = False
    emotion: MessageEmotion | None = None
    quick_replies: list[str] | None = None
    listings: list[PropertyListing] | None = None
    suggested_questions: list[str] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
