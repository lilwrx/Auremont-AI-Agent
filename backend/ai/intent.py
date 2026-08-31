"""Classify what a question needs before any model is called.

Keyword matching rather than an LLM classifier, deliberately. Routing decides whether the
real-time inventory API is consulted, and a misroute silently answers a stock question
from a stale PDF. A deterministic rule is auditable and adds no latency; a classifier call
would add both a failure mode and a round trip to every question.
"""

import re

from backend.utils.text import strip_diacritics

_REALTIME_INTENT_KEYWORDS = (
    "tìm căn",
    "lọc căn",
    "tìm nhà",
    "lọc nhà",
    "tìm đất",
    "lọc đất",
    "tìm văn phòng",
    "tìm mặt bằng",
    "tìm kho",
    "những căn",
    "các căn",
    "cho tôi căn",
    "còn căn",
    "còn bao nhiêu",
    "còn không",
    "còn trống",
    "trống không",
    "tồn kho",
    "bảng hàng",
    "sẵn hàng",
    "còn hàng",
    "hết hàng",
    "đã bán",
    "chưa bán",
    "giữ chỗ",
    "căn nào",
    "suất nào",
    "mã căn",
    "diện tích",
    "trạng thái",
    "loại căn",
    "unit_code",
    "project_id",
    "subdivision",
    "unit_type",
    "area_m2",
    "price_vnd",
    "status",
    "m2",
    "m²",
)

_INVENTORY_FOLLOWUP_FIELD_KEYWORDS = (
    "mã căn",
    "diện tích",
    "giá",
    "trạng thái",
    "loại căn",
    "tầng",
    "tòa",
    "hướng",
    "view",
    "unit_code",
    "project_id",
    "subdivision",
    "unit_type",
    "area_m2",
    "price_vnd",
    "status",
    "tower",
    "floor",
    "direction",
    "view_type",
    "m2",
    "m²",
)

_INVENTORY_FOLLOWUP_FIELD_PATTERN = re.compile(
    "|".join(
        rf"(?<![a-z0-9]){re.escape(strip_diacritics(keyword))}(?![a-z0-9])"
        for keyword in _INVENTORY_FOLLOWUP_FIELD_KEYWORDS
    )
)

_FILTERED_UNIT_QUERY_PATTERN = re.compile(
    r"\b(?:nhung|cac)\s+can\b|\b(?:can|nha)(?:\s+ho)?\b.{0,32}\b(?:duoi|tren|toi da|toi thieu|tu)\s*\d",
    re.IGNORECASE,
)

_NATURAL_SEARCH_REQUEST_PATTERN = re.compile(
    r"\b(?:tim|kiem)(?:\s+\w+){0,3}\s+(?:mot\s+)?(?:can|nha)\b",
    re.IGNORECASE,
)

_PRICE_DOCUMENT_QUERY_PATTERN = re.compile(
    r"\b(?:gia|ngan\s+sach|tam\s+gia)\b"
    r"|\b(?:duoi|tren|toi\s+da|toi\s+thieu|tu)\b.{0,32}\b(?:ty|ti|trieu|vnd|dong)\b",
    re.IGNORECASE,
)

_UNIT_CODE_PATTERN = re.compile(r"\b[a-z]+\d[a-z0-9]*(?:[.-][a-z0-9]+)+\b", re.IGNORECASE)

_PROPERTY_DOCUMENT_ATTRIBUTE_PATTERN = re.compile(
    r"\b(?:view|tam\s+nhin|huong\s+nhin|huong\s+can|canh\s+quan|tien\s+ich|noi\s+that|"
    r"ban\s+giao|so\s+huu|phap\s+ly)\b",
    re.IGNORECASE,
)

_PRICE_THRESHOLD_PATTERN = re.compile(r"\b(?:duoi|tren|khong qua|toi da)\s*\d+(?:[.,]\d+)?\s*(?:ty|trieu|tr)\b")
_PRICE_RANGE_PATTERN = re.compile(
    r"\b(?:tu\s*)?\d+(?:[.,]\d+)?\s*(?:ty|trieu|tr)?\s*(?:-|den|toi)\s*\d+(?:[.,]\d+)?\s*(?:ty|trieu|tr)\b"
)

_DOCUMENT_INTENT_KEYWORDS = (
    "chinh sach",
    "chính sách",
    "csbh",
    "chiet khau",
    "chiết khấu",
    "uu dai",
    "ưu đãi",
    "khuyen mai",
    "khuyến mại",
    "thanh toan",
    "thanh toán",
    "phap ly",
    "pháp lý",
    "hop dong",
    "hợp đồng",
    "bang gia",
    "bảng giá",
)


def _mentions_price_threshold(normalized: str) -> bool:
    return bool(_PRICE_THRESHOLD_PATTERN.search(normalized) or _PRICE_RANGE_PATTERN.search(normalized))


def needs_inventory(query: str) -> bool:
    """Diacritic-insensitive matching: a Sale typing fast on a phone rarely uses accents.

    "con can 2pn nao trong khong" must be recognised as an inventory question exactly
    like its fully accented form — otherwise the Agent quietly answers with stale unit
    counts from a PDF.
    """
    normalized = strip_diacritics(query)
    return (
        any(strip_diacritics(keyword) in normalized for keyword in _REALTIME_INTENT_KEYWORDS)
        or bool(_FILTERED_UNIT_QUERY_PATTERN.search(normalized))
        or bool(_NATURAL_SEARCH_REQUEST_PATTERN.search(normalized))
        or bool(_UNIT_CODE_PATTERN.search(normalized))
        or _mentions_price_threshold(normalized)
    )


def mentions_inventory_followup_field(query: str) -> bool:
    """Whether a follow-up asks for another field of the inventory rows already in scope.

    Matched on word boundaries, not raw substrings: several of these keywords are short
    enough to hide inside unrelated words once diacritics are stripped — "tòa" sits inside
    "thanh toán", which would route every payment-policy question into an inventory lookup.
    """

    normalized = strip_diacritics(query)
    return bool(_INVENTORY_FOLLOWUP_FIELD_PATTERN.search(normalized))


def needs_document_retrieval(query: str) -> bool:
    """Keep document RAG independent from the live-inventory decision.

    Price-filter requests intentionally use both paths: inventory for current availability
    and uploaded project/price documents for the customer-facing explanation.
    """
    normalized = strip_diacritics(query)
    return (
        any(strip_diacritics(keyword) in normalized for keyword in _DOCUMENT_INTENT_KEYWORDS)
        or bool(_PRICE_DOCUMENT_QUERY_PATTERN.search(normalized))
        or bool(_PROPERTY_DOCUMENT_ATTRIBUTE_PATTERN.search(normalized))
        or _mentions_price_threshold(normalized)
        or not needs_inventory(query)
    )


_CUSTOMER_MEMORY_REFERENCE_PATTERN = re.compile(
    r"\b(?:khach(?:\s+hang)?(?:\s+(?:cua\s+toi|nay|do))?|ho\s+so\s+khach|nhu\s+cau\s+khach)\b",
    re.IGNORECASE,
)
_CUSTOMER_MEMORY_ATTRIBUTE_PATTERN = re.compile(
    r"\b(?:quan\s+tam|nhu\s+cau|ngan\s+sach|tai\s+chinh|tam\s+gia|loai\s+can"
    r"|phan\s+khu|du\s+an|uu\s+tien|so\s+thich|mong\s+muon|tim\s+mua|muon\s+mua)\b",
    re.IGNORECASE,
)
_MEMORY_RECALL_PATTERN = re.compile(
    r"\b(?:nao|gi|bao\s+nhieu|ra\s+sao|the\s+nao|nhac\s+lai|tom\s+tat"
    r"|cho\s+toi\s+biet|xem\s+lai)\b",
    re.IGNORECASE,
)


def is_customer_memory_query(query: str) -> bool:
    """True for a Sale recalling the represented customer's profile.

    Requiring a customer reference, a remembered attribute and a recall signal avoids
    stealing recommendation questions such as "phân khu nào phù hợp với khách của tôi?"
    or statements such as "khách này quan tâm The Pavilion" from the normal pipeline.
    """
    normalized = strip_diacritics(query)
    if any(term in normalized for term in ("phu hop", "nen chon", "tu van", "de xuat", "goi y")):
        return False
    return bool(
        _CUSTOMER_MEMORY_REFERENCE_PATTERN.search(normalized)
        and _CUSTOMER_MEMORY_ATTRIBUTE_PATTERN.search(normalized)
        and _MEMORY_RECALL_PATTERN.search(normalized)
    )


def names_specific_document_topic(query: str) -> bool:
    """True for the keyword-matched half of `needs_document_retrieval` above, plus a
    budget threshold — both name something (policy, discount, legal, price list, a price
    range...) that should live in an ingested document, as opposed to
    `needs_document_retrieval`'s generic catch-all (True for almost anything that isn't a
    plain availability question, including a bare "tư vấn giúp em" with nothing to look up
    yet).

    Used to decide whether zero retrieval hits means "genuinely missing data, say so
    plainly" versus "nothing specific was asked for, let the model have a normal
    conversation instead" — see agent_pipeline._retrieve.
    """
    normalized = strip_diacritics(query)
    if any(strip_diacritics(keyword) in normalized for keyword in _DOCUMENT_INTENT_KEYWORDS):
        return True
    return _mentions_price_threshold(normalized)


_SEARCH_REFINEMENT_KEYWORDS = (
    "giu nguyen",
    "van giu",
    "tang gia",
    "giam gia",
    "tang len",
    "giam xuong",
    "nang len",
    "ha xuong",
    "bo yeu cau",
    "bo dieu kien",
    "bo tieu chi",
    "khong can",
    "thoi khong can",
    "doi lai",
    "thay vao do",
    "re hon",
    "dat hon",
    "rong hon",
    "nho hon",
    "gia mem",
    "de o",
    "dau tu",
    "gia dinh",
    "gia thap den cao",
    "gia cao den thap",
    "re nhat",
    "dat nhat",
    "dien tich lon nhat",
    "don gia thap nhat",
    "quay lai bo loc",
    "bo loc cu",
    "dieu kien cu",
    "xoa bo loc",
    "xoa toan bo",
    "xoa tat ca",
    "bo toan bo",
    "xoa het dieu kien",
    "tim lai tu dau",
    "nhu luc nay",
)


def is_search_refinement(query: str) -> bool:
    """`True` when the turn adjusts an existing unit search instead of opening a new topic.

    Deliberately narrow. A false positive keeps stale filters alive on an unrelated
    question — a failure with no visible symptom, because the answer still looks
    plausible while quietly hiding units. A false negative merely costs the person one
    repeated condition.
    """
    normalized = strip_diacritics(query)
    return any(keyword in normalized for keyword in _SEARCH_REFINEMENT_KEYWORDS)


_CATALOG_OVERVIEW_PATTERN = re.compile(
    r"\b(?:co\s+nhung|co\s+bao\s+nhieu|danh\s+sach|liet\s+ke|gom\s+nhung|toan\s+bo)\b"
    r".{0,20}\b(?:du\s+an|phan\s+khu|khu|loai\s+hinh|san\s+pham|danh\s+muc)\b",
    re.IGNORECASE,
)


def is_catalog_overview_query(query: str) -> bool:
    """True for a broad "what projects/product types do you have" survey question.

    Requires both a quantifier/listing verb ("có những", "danh sách", "liệt kê"...) and a
    catalogue-scope noun ("dự án", "phân khu", "loại hình"...) close together, so it does
    not fire on a specific-project question that merely mentions "dự án" in passing (e.g.
    "dự án The Beverly có tiện ích gì" — no quantifier there).
    """
    normalized = strip_diacritics(query)
    return bool(_CATALOG_OVERVIEW_PATTERN.search(normalized))


_ILLEGAL_REQUEST_KEYWORDS = (
    "lam gia giay to",
    "khai gia thap",
    "tron thue",
    "lach luat",
    "ne dieu kien vay",
    "gia mao giay to",
)
_PRIVACY_REQUEST_KEYWORDS = (
    "so dien thoai chu nha",
    "cccd chu nha",
    "thong tin ca nhan chu nha",
    "thong tin ca nhan cu dan",
    "danh sach cu dan",
)
_DISCRIMINATION_PATTERN = re.compile(
    r"\b(hang xom|cu dan|khu nay).{0,30}(dan toc|ton giao|quoc tich|nguoi nuoc nao)\b",
    re.IGNORECASE,
)
_SCAM_SIGNAL_KEYWORDS = (
    "lua dao",
    "coc truoc khi xem",
    "khong cho xem giay to",
    "tai khoan nguoi khac",
    "nguoi nhan tien khong phai chu",
    "thu phi xem nha",
    "moi gioi tu nhan chinh chu",
)
_RENTAL_SEARCH_PATTERN = re.compile(
    r"\b(?:tim|can|muon)\s+(?:can ho|can|nha|phong)?\s*(?:de\s+)?thue\b|\bthue\s+(?:nha|can ho|can|phong)\b",
    re.IGNORECASE,
)


def preflight_policy(query: str) -> str | None:
    """A deterministic policy code for requests that should stop before retrieval."""
    normalized = strip_diacritics(query)
    if any(keyword in normalized for keyword in _ILLEGAL_REQUEST_KEYWORDS):
        return "illegal_request"
    if any(keyword in normalized for keyword in _PRIVACY_REQUEST_KEYWORDS):
        return "privacy_request"
    if _DISCRIMINATION_PATTERN.search(normalized):
        return "discrimination_request"
    if any(keyword in normalized for keyword in _SCAM_SIGNAL_KEYWORDS):
        return "scam_warning"
    if _RENTAL_SEARCH_PATTERN.search(normalized) and "cho thue" not in normalized:
        return "rental_out_of_scope"
    return None


_CONVERSATION_META_KEYWORDS = (
    "vua hoi",
    "vua noi",
    "vua bao",
    "vua nhac",
    "hoi gi",
    "noi gi",
    "cau hoi truoc",
    "cau truoc",
    "luc nay",
    "ban nay",
    "phia tren",
    "o tren",
    "tom tat lai",
    "tom tat cuoc",
    "tom tat hoi thoai",
    "nhac lai",
    "lap lai",
    "noi lai",
    "da hoi",
    "da noi",
    "dang noi ve",
    "dang hoi ve",
    "chung ta noi",
    "chung ta dang",
)


def is_conversation_meta_query(query: str) -> bool:
    """`True` when the question is about the conversation so far, not about a project.

    These are answerable only from the session transcript, so the Verifier's
    document-grounded faithfulness check is meaningless for them — see
    `_CONVERSATION_META_KEYWORDS` above and `agent_pipeline._route_after_generate`.

    Keyword matching on the diacritic-stripped query, same rationale as the rest of this
    module: deterministic, auditable, no extra round trip. The keyword list is already
    stored unaccented since every comparison runs on the stripped form.
    """
    normalized = strip_diacritics(query)
    return any(keyword in normalized for keyword in _CONVERSATION_META_KEYWORDS)


_CLOSING_INTENT_KEYWORDS = (
    "bảng giá chi tiết",
    "xin bảng giá",
    "gửi bảng giá",
    "cho mình bảng giá",
    "mặt bằng chi tiết",
    "xem mặt bằng",
    "đặt lịch",
    "đổi lịch",
    "hủy lịch",
    "huỷ lịch",
    "xác nhận lịch",
    "nhắc lịch",
    "hẹn xem nhà",
    "hẹn xem căn",
    "đi xem dự án",
    "đi xem thực tế",
    "tư vấn trực tiếp",
    "gọi điện",
    "gọi video",
    "gọi lại",
    "gửi zalo",
    "gửi sms",
    "gửi email",
    "số điện thoại",
    "liên hệ em",
    "liên hệ anh",
    "liên hệ chị",
)


def needs_registration_gate(query: str) -> bool:
    """`True` when the question is a sales-closing ask that must trigger the soft paywall
    instead of a direct answer, for an anonymous customer-chat visitor.
    """
    normalized = strip_diacritics(query)
    return any(strip_diacritics(keyword) in normalized for keyword in _CLOSING_INTENT_KEYWORDS)


_WANTS_HUMAN_KEYWORDS = (
    "gặp người thật",
    "nói chuyện với người",
    "nói chuyện với nhân viên",
    "gặp chuyên viên",
    "gặp sale",
    "gặp nhân viên",
    "nhân viên tư vấn",
    "tư vấn viên",
    "nhân viên hỗ trợ",
    "cho gặp người",
    "kết nối nhân viên",
)


def wants_human_agent(query: str) -> bool:
    """`True` when the visitor explicitly asked to talk to a person, regardless of topic."""
    normalized = strip_diacritics(query)
    return any(strip_diacritics(keyword) in normalized for keyword in _WANTS_HUMAN_KEYWORDS)


_CONSIDERATION_PATTERNS = (
    re.compile(r"\b(?:gui|cho|xin)\b.{0,30}\bbang hang\b.{0,40}\b(?:con trong|moi nhat)\b", re.IGNORECASE),
    re.compile(r"\bcan (?:nay|do|[a-z0-9.-]+)\b.{0,24}\b(?:hien )?con (?:khong|trong)\b", re.IGNORECASE),
    re.compile(r"\b(?:gui|cho|xin)\b.{0,30}\b(?:chinh sach|tien do thanh toan)\b", re.IGNORECASE),
    re.compile(
        r"\btinh\b.{0,60}\b(?:thanh toan tung dot|tung dot|khoan vay|tra hang thang|tra moi thang)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:giay to|ho so)\b.{0,50}\b(?:ky hop dong|ky.{0,20}dat coc)\b", re.IGNORECASE),
)


def is_consideration_lead(query: str) -> bool:
    """Whether the visitor is evaluating a concrete unit, payment or human follow-up."""
    normalized = strip_diacritics(query)
    return wants_human_agent(query) or any(pattern.search(normalized) for pattern in _CONSIDERATION_PATTERNS)


_NEAR_TERM_TIMELINE_PATTERN = re.compile(
    r"\b(?:hom nay|ngay mai|tuan nay|cuoi tuan nay|tuan sau|thang nay|thang sau"
    r"|trong(?: vong)?(?: \d+)? (?:ngay|tuan|thang)(?: toi| nay)?)\b",
    re.IGNORECASE,
)


def has_near_term_timeline(query: str) -> bool:
    """Whether the person named a concrete near-term time to act."""
    return bool(_NEAR_TERM_TIMELINE_PATTERN.search(strip_diacritics(query)))


_TRANSACTION_READY_PATTERNS = (
    re.compile(r"\b(?:hom nay|bay gio)\b.{0,50}\bdat coc\b", re.IGNORECASE),
    re.compile(r"\bdat coc\b.{0,50}\b(?:chuyen|can|bao nhieu)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:muon|can|dat|sap xep)\b.{0,40}\b(?:xem can thuc te|xem can mau|tham quan du an)\b", re.IGNORECASE
    ),
    re.compile(
        r"\b(?:dat|hen|sap xep)\s+lich\b.{0,30}\b(?:xem (?:can|nha|du an)|tham quan)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:giu can|giu cho)\b.{0,40}\b(?:den|toi|qua|ngay mai|hom sau)\b", re.IGNORECASE),
    re.compile(r"\b(?:khi nao|muon|co the)\b.{0,50}\b(?:ky thoa thuan dat coc|ky.{0,20}dat coc)\b", re.IGNORECASE),
)


def is_transaction_ready_lead(query: str) -> bool:
    """Whether this turn explicitly asks for a concrete next step toward a purchase.

    The matcher is intentionally narrow. Availability, policy, loan calculations and human
    requests are consideration signals; booking a visit, holding a unit or placing/signing a
    deposit is transaction-ready.
    """
    normalized = strip_diacritics(query)
    return any(pattern.search(normalized) for pattern in _TRANSACTION_READY_PATTERNS)


_FRUSTRATION_KEYWORDS = (
    "bực",
    "khó chịu",
    "không hài lòng",
    "phàn nàn",
    "khiếu nại",
    "chán",
    "thất vọng",
    "trả lời linh tinh",
    "không hiểu",
    "hỏi mãi",
    "vô dụng",
)


def needs_human_handoff(query: str) -> bool:
    """`True` when the customer explicitly needs a person or is frustrated with the AI.

    Detailed price, floor-plan and appointment questions are self-service topics and must
    reach the document pipeline. Treating every closing-adjacent keyword as a handoff made
    normal budget questions disappear behind a generic "contact Sale" response.
    """
    if wants_human_agent(query):
        return True
    normalized = strip_diacritics(query)
    return any(strip_diacritics(keyword) in normalized for keyword in _FRUSTRATION_KEYWORDS)
