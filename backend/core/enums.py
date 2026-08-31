from enum import StrEnum


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class DocumentBlockReason(StrEnum):
    PROMPT_INJECTION = "prompt_injection"
    DUPLICATE_CONTENT = "duplicate_content"
    LEGACY_UNKNOWN = "legacy_unknown"


class DocumentVisibility(StrEnum):
    """RBAC tier: INTERNAL is Sale/Admin only; PUBLIC is safe for Sale to share with customers."""

    INTERNAL = "internal"
    PUBLIC = "public"


class UserRole(StrEnum):
    SALE = "sale"
    ADMIN = "admin"
    CUSTOMER = "customer"


class MessageSender(StrEnum):
    """Sale, Agent, or a Customer chatting directly through the public/customer flow."""

    SALE = "sale"
    AGENT = "agent"
    CUSTOMER = "customer"


class MessageEmotion(StrEnum):
    """Drives AuremontAvatar.tsx's animation for one AGENT-authored message — computed
    deterministically from the pipeline/gate outcome already available, never a separate
    LLM call (matches this codebase's classifier style — see backend/ai/intent.py). Unset
    on a message defaults to a neutral "idle" pose on the frontend.
    """

    HAPPY = "happy"
    REGRETFUL = "regretful"
    RESPECTFUL = "respectful"


class SessionStatus(StrEnum):
    """Who is currently answering a customer-chat session — see ChatSession's docstring
    for how this interacts with the sale_id/customer_id/visitor_token ownership columns.
    """

    BOT_HANDLING = "bot_handling"
    WAITING_SALE = "waiting_sale"
    SALE_HANDLING = "sale_handling"


class SessionChannel(StrEnum):
    """Which conversation a customer session holds. A customer has at most one of each, and
    they are deliberately separate rows rather than one thread split by a timestamp: a Sale
    is never shown the AI conversation (`GET /sale-live/{id}/messages` can only ever read the
    session it was handed), so the isolation survives any future endpoint that forgets to
    filter. See ChatSession's docstring.
    """

    AI = "ai"
    LIVE = "live"


class HitlStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"


class ConflictStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class FeedbackType(StrEnum):
    """A Sale's rating of an Agent answer — feeds the Admin Tab 2 dashboard."""

    HELPFUL = "helpful"
    WRONG = "wrong"
    INCOMPLETE = "incomplete"


class DocumentCategory(StrEnum):
    """Business grouping of a document in the knowledge base."""

    SALES_POLICY = "sales_policy"
    PRICE_LIST = "price_list"
    INVENTORY_SNAPSHOT = "inventory_snapshot"
    SUBDIVISION_INFO = "subdivision_info"
    BUILDING_INFO = "building_info"
    FLOOR_PLAN = "floor_plan"
    PAYMENT_SCHEDULE = "payment_schedule"
    PROMOTION = "promotion"
    LEGAL_DOCUMENT = "legal_document"
    CONTRACT_TEMPLATE = "contract_template"
    INTERNAL_GUIDE = "internal_guide"
    OTHER = "other"


class DocumentReviewStatus(StrEnum):
    """Outcome of the Admin's review of a proposed classification."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class LegalStatus(StrEnum):
    """Only meaningful when the category is LEGAL_DOCUMENT."""

    UNKNOWN = "unknown"
    NOT_YET_EFFECTIVE = "not_yet_effective"
    EFFECTIVE = "effective"
    EXPIRED = "expired"
    REPEALED = "repealed"
    REPLACED = "replaced"


class DocumentRelationType(StrEnum):
    """How a new document relates to one already in the knowledge base."""

    REPLACES = "replaces"
    AMENDS = "amends"
    REPEALS = "repeals"
    UPDATES = "updates"
    SUPERSEDES = "supersedes"
    GUIDES = "guides"
    RELATED_TO = "related_to"


class LeadTier(StrEnum):
    """How ready a customer is to buy — the priority a Sale should give them.

    Describes readiness, NOT spending power: someone asking to book a viewing this week is
    HOT on a 2 tỷ budget, while someone idly browsing 10 tỷ villas is not.

    COLD is the honest default for a lead who has shown no buying signal yet — it never
    means "we failed to score this person". A scoring failure leaves the previous tier
    untouched (see lead_service), because a Sale who cannot trust the badge ignores it.
    """

    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


class LeadUrgency(StrEnum):
    """How soon the customer intends to act, judged from how they talk about timing.

    Only the LLM pass sets this — no regex can tell "đang cần gấp" from "để em xem đã".
    EXPLORING is the conservative fallback for an unparseable or missing verdict: assuming
    someone is in a hurry when they are not sends a Sale chasing the wrong person.
    """

    IMMEDIATE = "immediate"
    NEAR_TERM = "near_term"
    EXPLORING = "exploring"


class LeadPurpose(StrEnum):
    """What the customer wants the property for.

    Values deliberately match the strings `SearchCriteria.purpose` already produces
    (backend/services/search_criteria.py `_PURPOSE_PATTERNS`) — the regex extractor and the
    LLM describe the same fact, and two vocabularies for one fact guarantees they disagree.
    UNKNOWN covers "nobody said yet", which is the common case early in a conversation.
    """

    LIVING = "living"
    INVESTMENT = "investment"
    BUSINESS = "business"
    UNKNOWN = "unknown"


class PlanTier(StrEnum):
    """The three published plans. The string is the primary key in `plans`, so it is part
    of the API contract (`/billing/plans`) and must not be renamed without a migration."""

    STARTER = "starter"
    GROWTH = "growth"
    ENTERPRISE = "enterprise"


class SubscriptionStatus(StrEnum):
    """Where a workspace's subscription sits in its lifecycle.

    TRIALING and ACTIVE both grant access; everything else denies it. CANCELLED means the
    owner asked to stop but the paid period has not run out yet — access continues to
    `current_period_end`, which is why it is distinct from EXPIRED.
    """

    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class SubscriptionRequestStatus(StrEnum):
    """A business's application to subscribe, before any workspace exists.

    The MVP has no payment gateway, so an Admin moves the request by hand: PENDING until
    someone looks at it, then APPROVED (workspace created, subscription activated) or
    REJECTED. CONTACTED is for Enterprise leads that need a call before either verdict.
    """

    PENDING = "pending"
    CONTACTED = "contacted"
    APPROVED = "approved"
    REJECTED = "rejected"


class OrganizationRole(StrEnum):
    """A member's authority inside one workspace, orthogonal to `UserRole`.

    `UserRole` says what the account can do in the product (Sale vs Admin vs Customer);
    this says what they can do to the workspace itself — only an OWNER can change the plan
    or cancel it, and only OWNER/ADMIN can manage members.
    """

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
