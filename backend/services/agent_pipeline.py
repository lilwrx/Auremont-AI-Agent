"""Multi-Agent orchestration: Cache -> Retrieval -> Tool-Use -> Generation -> Verify -> RiskCheck.

This is the core that wires the existing pieces into one complete answer flow for a
Sale, built as a LangGraph StateGraph following the diagram in ARCHITECTURE.md:

    START -> CacheCheck --hit--> END
                 |miss
             Retrieve --(empty/error)--> END
                 |
          needs real-time? --yes--> ToolCall (inventory API)
                 |no                    |
                 +--------> Generate <--+
                                |
                             Verify --low score--> Generate (at most once)
                                |pass       |retries exhausted -> END
                            RiskCheck -> END

Two principles govern this whole file:

* **Never let an exception escape.** `run_pipeline` sits directly on the Sale's request
  path; an uncaught exception becomes a 500 in the middle of a customer conversation.
  Every failure branch collapses into a readable message with `verifier_score = 0.0`.
* **Fail closed, on the safe side.** Without solid grounding say "not enough
  information" rather than guessing; anything touching price or commitments must be
  flagged for HITL.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from backend.ai import prompts
from backend.ai.answer_cleanup import (
    correct_unit_count,
    drop_false_image_confirmations,
    drop_image_denials,
)
from backend.ai.citations import build_citations
from backend.ai.intent import (
    is_catalog_overview_query,
    is_conversation_meta_query,
    is_customer_memory_query,
    is_search_refinement,
    mentions_inventory_followup_field,
    names_specific_document_topic,
    preflight_policy,
)
from backend.ai.intent import needs_document_retrieval as query_needs_documents
from backend.ai.intent import needs_inventory as query_needs_inventory
from backend.core import tracing
from backend.core.config import get_settings
from backend.core.enums import DocumentVisibility, MessageEmotion, MessageSender
from backend.core.gemini_client import generate_json
from backend.models.project import Project
from backend.services import (
    answer_images_service,
    cache_service,
    catalog_context_service,
    catalog_offer_service,
    memory_service,
    reflection_memory,
    risk_service,
    search_criteria,
    verifier_service,
)
from backend.services.inventory_service import (
    InventoryApiError,
    InventoryProjectUnresolvedError,
    InventoryUnit,
    apply_criteria,
    fetch_units,
    format_preference_coverage,
    has_exact_project_mapping,
    lookup_inventory,
)
from backend.services.rag_service import RetrievalError, retrieve
from backend.utils.text import strip_diacritics, strip_markdown

logger = logging.getLogger(__name__)

RETRIEVAL_TOP_K = 5

MAX_HISTORY_MESSAGES = 16

MAX_GENERATE_RETRIES = 1

EMPTY_STATE_MESSAGE_INTERNAL = "Chưa có dữ liệu dự án, vui lòng báo Admin cập nhật."
EMPTY_STATE_MESSAGE_PUBLIC = (
    "Auremont chưa có đủ thông tin để trả lời câu hỏi này. Bạn thử hỏi cách khác, hoặc để "
    "lại thông tin liên hệ để được chuyên viên hỗ trợ nhé."
)
INVENTORY_UNAVAILABLE_MESSAGE = "Tạm thời không tra được tồn kho."
INVENTORY_NEEDS_PROJECT_MESSAGE_INTERNAL = (
    "Phiên chat này chưa gắn với dự án cụ thể — nêu rõ tên dự án hoặc phân khu trong câu hỏi để tra đúng tồn kho nhé."
)
INVENTORY_NEEDS_PROJECT_MESSAGE_PUBLIC = (
    "Dạ bên em hiện có nhiều dự án khác nhau, anh chị đang quan tâm dự án nào để em kiểm tra "
    "tồn kho chính xác giúp mình ạ?"
)
LOW_CONFIDENCE_MESSAGE_INTERNAL = "Không đủ thông tin, liên hệ Admin."
LOW_CONFIDENCE_MESSAGE_PUBLIC = (
    "Auremont chưa đủ thông tin để trả lời chính xác câu này. Bạn có thể hỏi cụ thể hơn, "
    "hoặc để lại thông tin liên hệ để được hỗ trợ nhanh nhất nhé."
)
RETRIEVAL_ERROR_MESSAGE = "Tạm thời không tra cứu được tài liệu, vui lòng thử lại sau."
GENERATION_ERROR_MESSAGE = "Tạm thời không tạo được câu trả lời, vui lòng thử lại sau."
PREFLIGHT_MESSAGES = {
    "illegal_request": (
        "Mình không thể hỗ trợ lách luật, trốn thuế hoặc làm giả hồ sơ. Mình có thể giúp "
        "anh/chị kiểm tra quy trình giao dịch và các giấy tờ cần chuẩn bị theo hướng hợp pháp."
    ),
    "privacy_request": (
        "Mình không thể cung cấp thông tin cá nhân chưa được phép công khai của chủ nhà hoặc cư dân. "
        "Anh/chị có thể liên hệ qua kênh chính thức của dự án để được kết nối đúng người phụ trách."
    ),
    "discrimination_request": (
        "Mình không thể lọc hoặc đánh giá nơi ở theo dân tộc, tôn giáo hay quốc tịch của cư dân. "
        "Mình có thể giúp so sánh theo các tiêu chí phù hợp như an ninh, tiện ích, ngân sách và thời gian di chuyển."
    ),
    "scam_warning": (
        "Đây là dấu hiệu giao dịch có rủi ro. Anh/chị chưa nên chuyển tiền; hãy kiểm tra giấy tờ gốc, "
        "đối chiếu người nhận tiền với chủ thể có quyền giao dịch và chỉ ký/cọc khi điều khoản, căn hộ và "
        "tài khoản nhận tiền đã được xác minh qua kênh chính thức."
    ),
    "rental_out_of_scope": (
        "Hiện Auremont chỉ có dữ liệu căn hộ dự án đang bán, chưa có nguồn nhà cho thuê để lọc chính xác. "
        "Nếu anh/chị cân nhắc mua để ở hoặc mua đầu tư, mình có thể tiếp tục tư vấn theo ngân sách."
    ),
}

NOTICE_MESSAGES = frozenset(
    {
        EMPTY_STATE_MESSAGE_INTERNAL,
        EMPTY_STATE_MESSAGE_PUBLIC,
        INVENTORY_UNAVAILABLE_MESSAGE,
        LOW_CONFIDENCE_MESSAGE_INTERNAL,
        LOW_CONFIDENCE_MESSAGE_PUBLIC,
        RETRIEVAL_ERROR_MESSAGE,
        GENERATION_ERROR_MESSAGE,
    }
)


def _empty_state_message(clearance: DocumentVisibility) -> str:
    return EMPTY_STATE_MESSAGE_PUBLIC if clearance == DocumentVisibility.PUBLIC else EMPTY_STATE_MESSAGE_INTERNAL


def _low_confidence_message(clearance: DocumentVisibility) -> str:
    return LOW_CONFIDENCE_MESSAGE_PUBLIC if clearance == DocumentVisibility.PUBLIC else LOW_CONFIDENCE_MESSAGE_INTERNAL


def _inventory_needs_project_message(clearance: DocumentVisibility) -> str:
    return (
        INVENTORY_NEEDS_PROJECT_MESSAGE_PUBLIC
        if clearance == DocumentVisibility.PUBLIC
        else INVENTORY_NEEDS_PROJECT_MESSAGE_INTERNAL
    )


@dataclass
class PipelineResult:
    draft_answer: str
    citations: list[dict]
    verifier_score: float
    requires_hitl: bool
    used_cache: bool = False
    faithfulness: float | None = None
    answer_relevancy: float | None = None
    completeness: float | None = None
    failure_mode: str | None = None
    verifier_feedback: str | None = None
    images: list[dict] = field(default_factory=list)
    emotion: str | None = None
    quick_replies: list[str] = field(default_factory=list)
    listings: list[dict] = field(default_factory=list)
    suggested_questions: list[str] = field(default_factory=list)


class PipelineState(TypedDict, total=False):
    """State threaded through the nodes — as described in ARCHITECTURE.md §3."""

    query: str
    session_id: int | None
    project_id: str | None
    resolved_project_ids: list[str]
    excluded_project_ids: list[str]
    memory_profile: str
    memory_profile_data: memory_service.UserProfile
    answered_from_memory: bool
    reflection_lessons: str
    reflection_scope: str | None
    clearance: DocumentVisibility
    history: list[dict]
    retrieved_docs: list[dict]
    catalog_context: str
    catalog_context_complete: bool
    catalog_offers: list[catalog_offer_service.CatalogOffer]
    catalog_offer_context: str
    catalog_overview_context: str
    needs_inventory: bool
    needs_document_retrieval: bool
    inventory_units: list[InventoryUnit]
    all_units: list[InventoryUnit]
    inventory_failed: bool
    criteria: search_criteria.SearchCriteria
    zero_result_diagnosis: search_criteria.ZeroResultDiagnosis
    draft_answer: str
    citations: list[dict]
    quick_replies: list[str]
    listings: list[dict]
    suggested_questions: list[str]
    verifier_score: float
    faithfulness: float
    answer_relevancy: float
    completeness: float
    failure_mode: str
    verifier_feedback: str
    next_action: str
    requires_hitl: bool
    images: list[dict]
    floor_plan_towers_only: list[str] | None
    db: Session | None
    retry_count: int
    notice: str
    notice_emotion: MessageEmotion
    used_cache: bool


def _preflight(state: PipelineState) -> dict[str, Any]:
    """Stop unsafe or unsupported requests before cache, retrieval, and model calls."""
    policy = preflight_policy(state["query"])
    if policy is None:
        if is_customer_memory_query(state["query"]):
            answer = memory_service.format_recall_answer(
                state["query"], state.get("memory_profile_data") or memory_service.UserProfile()
            )
            tracing.step("preflight", decision="memory_recall", has_profile=bool(state.get("memory_profile")))
            return {
                "draft_answer": answer,
                "answered_from_memory": True,
                "verifier_score": 1.0,
                "requires_hitl": False,
            }
        return {}
    tracing.step("preflight", policy=policy)
    return {
        "notice": PREFLIGHT_MESSAGES[policy],
        "notice_emotion": MessageEmotion.RESPECTFUL,
    }


def _scope_resolve(state: PipelineState) -> dict[str, Any]:
    """Resolve project, sub-zone or tower names before cache/RAG/tool selection."""
    db = state.get("db")
    current = state.get("project_id")
    if db is None:
        return {"resolved_project_ids": [current] if current else []}

    references = answer_images_service.resolve_project_references(db, state["query"])
    project_ids = list(references.included_ids)
    excluded_project_ids = list(references.excluded_ids)
    if not project_ids:
        stale_ids: list[str] = []
        for turn in reversed(state.get("history") or []):
            if turn.get("sender") == MessageSender.AGENT:
                continue
            stale_ids = answer_images_service.resolve_project_ids(db, turn.get("content", ""))
            if stale_ids:
                break
        if not stale_ids and current:
            stale_ids = [current]

        category = answer_images_service.named_category(state["query"])
        if category is not None and stale_ids:
            stale_ids = [
                pid
                for pid in stale_ids
                if (project := db.get(Project, pid)) is not None
                and category in answer_images_service.project_categories(project)
            ]

        project_ids = stale_ids

    rag_project_id = project_ids[0] if len(project_ids) == 1 else None
    tracing.step("scope.resolve", project_ids=project_ids, rag_project_id=rag_project_id)
    return {
        "project_id": rag_project_id,
        "resolved_project_ids": project_ids,
        "excluded_project_ids": excluded_project_ids,
    }


def _cache_check(state: PipelineState) -> dict[str, Any]:
    """Check the Semantic Cache before spending any tokens.

    Skipped once there is history: `cache_service` keys on bare query text, so a
    context-dependent follow-up ("giá bao nhiêu?") must never replay to a different
    customer whose same question means something else. Only an opening question is
    eligible.
    """
    if state.get("history"):
        tracing.step("cache_check", hit=False, skipped="has_history")
        return {"used_cache": False}

    if state.get("memory_profile"):
        tracing.step("cache_check", hit=False, skipped="has_memory_profile")
        return {"used_cache": False}

    session_id = state.get("session_id")
    if session_id is not None and get_settings().search_criteria_enabled:
        criteria, _ = search_criteria.load(session_id)
        if not criteria.is_empty():
            tracing.step("cache_check", hit=False, skipped="has_search_criteria")
            return {"used_cache": False, "criteria": criteria}

    clearance = state.get("clearance", DocumentVisibility.INTERNAL)
    cached = cache_service.lookup_cache(state["query"], state.get("project_id"), clearance)
    if cached is None:
        tracing.step("cache_check", hit=False)
        return {"used_cache": False}

    requires_hitl = risk_service.detect_commitment_risk(cached.answer)

    tracing.step("cache_check", hit=True, verifier_score=cached.verifier_score, requires_hitl=requires_hitl)
    return {
        "used_cache": True,
        "draft_answer": cached.answer,
        "citations": cached.citations,
        "verifier_score": cached.verifier_score,
        "requires_hitl": requires_hitl,
        "images": cached.images,
    }


_SHORT_QUERY_WORD_LIMIT = 4

_CONTINUATION_PREFIXES = ("thế ", "vậy ", "còn ", "nếu ")


def _needs_history_fold(query: str) -> bool:
    if len(query.split()) <= _SHORT_QUERY_WORD_LIMIT:
        return True
    return query.strip().lower().startswith(_CONTINUATION_PREFIXES)


def _retrieval_query(query: str, history: list[dict] | None) -> str:
    """Fold recent turns into the string embedded for retrieval — a bare follow-up ("giá
    bao nhiêu?", "có") carries almost no signal alone. Two patterns, neither enough alone:

    1. The topic a HUMAN set with their last (up to two) substantive messages. Two turns,
       not one: a single turn back can itself be an unrelated referential follow-up ("Khu
       này có bãi đỗ xe không?") — a real bug once dropped both project name and budget
       from "Thế tôi muốn mua để đầu tư thì sao?" because only that unrelated turn folded
       in.
    2. A topic the AI itself just asked about ("...chiết khấu này không ạ?" -> "có"). Only
       the AI turn's tail counts, and only when it ends in "?" — a closing statement or
       greeting carries no topic worth folding in.

    Only applied when `_needs_history_fold` says the query needs it, and only up to two
    turns back — an old, resolved topic must not keep dragging retrieval toward it. Never
    changes keyword classification or what the LLM sees as "the question"; `_retrieve` and
    `build_prompt` both keep using the bare `query`.
    """
    if not history or not _needs_history_fold(query):
        return query

    human_turns = [turn.get("content", "") for turn in history if turn.get("sender") != MessageSender.AGENT]
    recent_human_turns = list(dict.fromkeys(human_turns[-2:]))

    last_turn = history[-1]
    last_turn_content = last_turn.get("content", "")
    ai_question_tail = (
        last_turn_content[-160:]
        if last_turn.get("sender") == MessageSender.AGENT and last_turn_content.rstrip().endswith("?")
        else ""
    )

    parts = [part for part in (ai_question_tail, *recent_human_turns) if part]
    return f"{' '.join(parts)} {query}" if parts else query


def _retrieve(state: PipelineState) -> dict[str, Any]:
    """Pull context from Qdrant and decide whether the inventory API is needed.

    Queries at `state["clearance"]`: INTERNAL (Sale/Admin) can read both internal and
    public documents, PUBLIC (customer chat) reads only public ones — `rag_service`
    treats this argument as *the asker's clearance level*, not a label to match exactly.
    """
    query = state["query"]
    clearance = state.get("clearance", DocumentVisibility.INTERNAL)
    project_id = state.get("project_id")

    inventory_context_queries = _inventory_context_queries(state.get("history"))
    continues_inventory_lookup = bool(
        inventory_context_queries
        and mentions_inventory_followup_field(query)
        and any(query_needs_inventory(context_query) for context_query in inventory_context_queries)
    )
    needs_inventory = query_needs_inventory(query) or continues_inventory_lookup
    needs_document_retrieval = query_needs_documents(query)
    catalog_overview_context = (
        catalog_offer_service.build_catalog_overview(state.get("db")) if is_catalog_overview_query(query) else ""
    )
    catalog = catalog_context_service.resolve_tower_context(state.get("db"), state.get("project_id"), query)
    project_profile = catalog_context_service.project_profile_context(state.get("db"), state.get("project_id"), query)
    catalog_context = "\n\n".join(part for part in (project_profile, catalog.text) if part)
    hits: list[dict] = []

    retrieval_query = _retrieval_query(query, state.get("history"))

    inventory_project_id = project_id
    if inventory_project_id is None:
        db = state.get("db")
        if db is not None:
            inventory_project_id = answer_images_service.resolve_project_id(db, retrieval_query)

    tracing.step(
        "intent",
        needs_inventory=needs_inventory,
        needs_document_retrieval=needs_document_retrieval,
        clearance=str(clearance),
    )

    if needs_document_retrieval:
        started = time.perf_counter()
        try:
            hits = retrieve(
                retrieval_query,
                clearance,
                project_id,
                RETRIEVAL_TOP_K,
                focus_query=query,
                project_ids=_rag_project_scope_ids(state.get("db"), state.get("project_id")),
                excluded_project_ids=state.get("excluded_project_ids") or None,
            )
        except RetrievalError:
            logger.exception(
                "Qdrant retrieval failed.",
                extra={
                    "event": "pipeline.retrieve.failed",
                    "project_id": state.get("project_id"),
                    "query_len": len(query),
                },
            )
            tracing.step(
                "retrieve",
                ok=False,
                error="qdrant_unavailable",
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            if not needs_inventory and not catalog_context:
                return {"notice": RETRIEVAL_ERROR_MESSAGE}
        else:
            top_score = hits[0].get("score") if hits else None
            tracing.step(
                "retrieve",
                ok=True,
                doc_count=len(hits),
                top_score=round(top_score, 4) if isinstance(top_score, int | float) else None,
                document_ids=[hit.get("document_id") for hit in hits],
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )

    if not hits and not needs_inventory and not catalog_context and names_specific_document_topic(query):
        tracing.step("empty_state")
        return {"notice": _empty_state_message(clearance)}

    return {
        "retrieved_docs": hits,
        "catalog_context": catalog_context,
        "catalog_context_complete": catalog.complete,
        "catalog_overview_context": catalog_overview_context,
        "needs_inventory": needs_inventory,
        "needs_document_retrieval": needs_document_retrieval,
        "project_id": inventory_project_id,
    }


def _rag_project_scope_ids(db: Session | None, project_id: str | None) -> list[str] | None:
    """The named catalogue project plus every direct child stored beneath it."""
    if not project_id:
        return None
    if db is None:
        return [project_id]

    try:
        ids = [project_id]
        for project in db.query(Project).all():
            info = (project.details or {}).get("project") or {}
            if info.get("parent_project_id") == project_id:
                ids.append(project.id)
        return list(dict.fromkeys(ids))
    except Exception:
        logger.exception(
            "Could not expand parent project scope; using the exact project only.",
            extra={"event": "pipeline.scope.expand.failed", "project_id": project_id},
        )
        return [project_id]


def _criteria_resolve(state: PipelineState) -> dict[str, Any]:
    """Merge this turn's unit filters with the session's working search state."""
    if state.get("session_id") is None or not get_settings().search_criteria_enabled:
        criteria = search_criteria.merge_criteria(
            search_criteria.SearchCriteria(), search_criteria.parse_criteria(state["query"])
        )
        return _catalog_search_result(state, criteria)
    if not state.get("needs_inventory") and not is_search_refinement(state["query"]):
        standalone_criteria = search_criteria.merge_criteria(
            search_criteria.SearchCriteria(), search_criteria.parse_criteria(state["query"])
        )
        return _catalog_search_result(state, standalone_criteria)

    criteria, delta = search_criteria.resolve(state["session_id"], state["query"])
    conflict = search_criteria.detect_conflict(criteria)
    if conflict:
        tracing.step("criteria", ok=False, conflict=True)
        return {
            "criteria": criteria,
            "notice": conflict,
            "notice_emotion": MessageEmotion.RESPECTFUL,
        }

    if delta.unresolved_vague and criteria.is_empty():
        topic = delta.unresolved_vague[0]
        question = (
            "Anh/chị dự kiến ngân sách tối đa khoảng bao nhiêu ạ?"
            if topic == "giá"
            else "Anh/chị mong muốn diện tích tối thiểu khoảng bao nhiêu m² ạ?"
        )
        tracing.step("criteria", ok=False, unresolved=topic)
        return {
            "criteria": criteria,
            "notice": question,
            "notice_emotion": MessageEmotion.RESPECTFUL,
        }

    tracing.step("criteria", ok=True, constraint_count=len(criteria.constraints))
    return {
        "criteria": criteria,
        "needs_inventory": True,
        **_catalog_search_result(state, criteria),
    }


def _catalog_search_result(state: PipelineState, criteria: search_criteria.SearchCriteria) -> dict[str, Any]:
    """Attach structured catalogue tiers for property-search questions."""
    if not state.get("needs_inventory") and criteria.is_empty():
        return {}
    offers = catalog_offer_service.search_offers(
        state.get("db"),
        state["query"],
        project_ids=state.get("resolved_project_ids") or None,
        excluded_project_ids=state.get("excluded_project_ids") or None,
        criteria=criteria,
    )
    tracing.step("catalog.search", offer_count=len(offers))
    return {
        "catalog_offers": offers,
        "catalog_offer_context": catalog_offer_service.format_offers(offers, criteria),
    }


def _tool_call(state: PipelineState) -> dict[str, Any]:
    """Function Calling into the internal inventory API for constantly changing data.

    A missing `project_id` is the common case, not rare — sessions carry no project by
    default. A genuine `InventoryApiError` degrades to answering from whatever documents
    were retrieved, falling back to the "temporarily unavailable" notice only when there
    is nothing else to answer from.
    """
    project_id = state.get("project_id")
    clearance = state.get("clearance", DocumentVisibility.INTERNAL)
    started = time.perf_counter()

    session_id = state.get("session_id")
    stateful = session_id is not None and get_settings().search_criteria_enabled
    all_units: list[InventoryUnit] = []
    if (
        state.get("db") is not None
        and project_id
        and state.get("resolved_project_ids")
        and not has_exact_project_mapping(project_id)
    ):
        tracing.step("tool.inventory", ok=False, skipped="no_exact_project_mapping")
        return {"inventory_failed": True, "inventory_units": [], "all_units": []}
    try:
        if stateful:
            all_units = fetch_units(project_id)
            criteria = state.get("criteria") or search_criteria.SearchCriteria()

            known = sorted({unit.subdivision for unit in all_units if unit.subdivision})
            enriched = search_criteria.merge_criteria(criteria, search_criteria.parse_criteria(state["query"], known))
            conflict = search_criteria.detect_conflict(enriched)
            if conflict:
                return {
                    "criteria": enriched,
                    "all_units": all_units,
                    "notice": conflict,
                    "notice_emotion": MessageEmotion.RESPECTFUL,
                }
            if enriched != criteria:
                if session_id is None:
                    raise RuntimeError("Persisted search criteria require a session id.")
                _, history = search_criteria.load(session_id)
                search_criteria.save(session_id, enriched, history)
                criteria = enriched
            units = apply_criteria(all_units, criteria)
        else:
            context_queries = _inventory_context_queries(state.get("history"))
            units = (
                lookup_inventory(project_id, state["query"], context_queries)
                if context_queries
                else lookup_inventory(project_id, state["query"])
            )
    except InventoryProjectUnresolvedError:
        return {
            "inventory_failed": True,
            "notice": _inventory_needs_project_message(clearance),
            "notice_emotion": MessageEmotion.RESPECTFUL,
        }
    except InventoryApiError:
        logger.warning(
            "Inventory lookup failed for project %s.",
            project_id,
            exc_info=True,
            extra={"event": "pipeline.inventory.failed", "project_id": project_id},
        )
        tracing.step(
            "tool.inventory",
            ok=False,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        if state.get("retrieved_docs"):
            return {"inventory_failed": True, "inventory_units": [], "all_units": []}
        return {"inventory_failed": True, "notice": INVENTORY_UNAVAILABLE_MESSAGE}

    tracing.step(
        "tool.inventory",
        ok=True,
        unit_count=len(units),
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    result: dict[str, Any] = {"inventory_units": units, "inventory_failed": False}
    if stateful:
        result.update({"all_units": all_units, "criteria": criteria})
    return result


def _criteria_diagnose(state: PipelineState) -> dict[str, Any]:
    """Explain an empty filtered set using leave-one-out counts over raw inventory."""
    if state.get("inventory_failed") or state.get("inventory_units"):
        return {}
    criteria = state.get("criteria")
    all_units = state.get("all_units") or []
    if criteria is None or not all_units:
        return {}
    diagnosis = search_criteria.diagnose_zero_results(all_units, criteria)
    if diagnosis is None:
        return {}
    tracing.step(
        "criteria.diagnose",
        active_count=len(diagnosis.active_constraints),
        option_count=len(diagnosis.relax_options),
    )
    return {"zero_result_diagnosis": diagnosis}


def _inventory_context_queries(history: list[dict] | None) -> list[str]:
    """Recent human inventory constraints, newest first, without AI-generated figures."""

    if not history:
        return []
    human_queries = [
        str(turn.get("content", "")).strip()
        for turn in reversed(history)
        if turn.get("sender") != MessageSender.AGENT and str(turn.get("content", "")).strip()
    ]
    return human_queries[:2]


def _generate(state: PipelineState) -> dict[str, Any]:
    """Generate an answer with citations from the collected context."""
    docs = state.get("retrieved_docs") or []
    prompt_docs = (
        []
        if state.get("catalog_context_complete") and catalog_context_service.is_tower_profile_query(state["query"])
        else docs
    )
    units = state.get("inventory_units") or []
    if units:
        criteria = state.get("criteria")
        if criteria is not None:
            status_requested = criteria.get(search_criteria.FIELD_STATUSES) is not None
        else:
            turn = search_criteria.parse_criteria(state["query"])
            status_requested = any(
                constraint.field == search_criteria.FIELD_STATUSES for constraint in turn.constraints
            )
        if not status_requested:
            units = [unit for unit in units if unit.status.strip().lower() == "available"]
    is_public = state.get("clearance", DocumentVisibility.INTERNAL) == DocumentVisibility.PUBLIC
    criteria = state.get("criteria") or search_criteria.SearchCriteria()
    inventory_coverage = format_preference_coverage(units, criteria)
    structured_context = "\n\n".join(part for part in (state.get("catalog_context") or "", inventory_coverage) if part)

    prompt = prompts.build_prompt(
        state["query"],
        prompt_docs,
        units,
        state.get("needs_inventory", False),
        state.get("inventory_failed", False),
        state.get("images") or [],
        state.get("history") or [],
        state.get("memory_profile") or "",
        is_public=is_public,
        correction=state.get("verifier_feedback") or "",
        lessons=state.get("reflection_lessons") or "",
        criteria_summary=search_criteria.format_criteria(criteria),
        zero_result=state.get("zero_result_diagnosis"),
        catalog_context=structured_context,
        catalog_offer_context=state.get("catalog_offer_context") or "",
        catalog_overview_context=state.get("catalog_overview_context") or "",
        floor_plan_towers_only=state.get("floor_plan_towers_only"),
    )
    quick_replies: list[str] = []
    listings: list[dict] = []
    suggested_questions: list[str] = []
    attempt = state.get("retry_count", 0) + 1
    started = time.perf_counter()

    parsed: prompts.ConsultAnswer | prompts.SaleAnswer | None
    try:
        if is_public:
            parsed = generate_json(prompt, prompts.ConsultAnswer, system_instruction=prompts.SYSTEM_INSTRUCTION_PUBLIC)
        else:
            parsed = generate_json(prompt, prompts.SaleAnswer, system_instruction=prompts.SYSTEM_INSTRUCTION)
    except Exception:
        logger.exception(
            "Answer generation failed.",
            extra={
                "event": "pipeline.generate.failed",
                "project_id": state.get("project_id"),
                "doc_count": len(docs),
                "unit_count": len(units),
            },
        )
        tracing.step(
            "generate",
            attempt=attempt,
            ok=False,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return {"notice": GENERATION_ERROR_MESSAGE}

    if parsed is None:
        logger.warning(
            "Consult LLM returned no parseable answer.",
            extra={"event": "pipeline.generate.unparseable", "project_id": state.get("project_id")},
        )
        tracing.step(
            "generate",
            attempt=attempt,
            ok=False,
            empty=True,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return {"notice": GENERATION_ERROR_MESSAGE}

    answer = parsed.text
    suggested_questions = parsed.suggested_questions
    quick_replies = getattr(parsed, "quick_replies", [])
    if isinstance(parsed, prompts.ConsultAnswer | prompts.SaleAnswer):
        listings = _resolve_listing_images(state.get("db"), _drop_figureless_listings(parsed.listings))

    answer = strip_markdown(answer)

    if not answer:
        tracing.step(
            "generate",
            attempt=attempt,
            ok=False,
            empty=True,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return {"notice": GENERATION_ERROR_MESSAGE}

    answer = drop_image_denials(answer, state.get("images") or [])
    answer = drop_false_image_confirmations(answer, state.get("images") or [])
    answer = correct_unit_count(answer, len(listings))

    tracing.step(
        "generate",
        attempt=attempt,
        ok=True,
        answer_len=len(answer),
        doc_count=len(docs),
        unit_count=len(units),
        corrected=bool(state.get("verifier_feedback")),
        with_lessons=bool(state.get("reflection_lessons")),
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return {
        "draft_answer": answer,
        "citations": _citations_for(prompt_docs, answer=answer),
        "quick_replies": quick_replies,
        "listings": listings,
        "suggested_questions": suggested_questions,
        "images": [] if listings else state.get("images") or [],
    }


_HAS_DIGIT = re.compile(r"\d")


def _drop_figureless_listings(listings: list["prompts.PropertyListing"]) -> list["prompts.PropertyListing"]:
    """Discard cards the model filled with words where the figures should be.

    The prompt already says to leave `listings` empty rather than invent a placeholder, but
    the model does it anyway — `eval/deepeval_suite.py` caught one on 5 of 6 runs of a plain
    policy question. Enforced here rather than in the prompt so it survives prompt edits and
    model upgrades. A card with neither figure loses nothing a reader wanted.
    """
    kept = []
    for listing in listings:
        if _HAS_DIGIT.search(listing.area_range) or _HAS_DIGIT.search(listing.price_range):
            kept.append(listing)
            continue

        tracing.step(
            "listing.dropped",
            reason="no_figures",
            project_name=listing.project_name,
            unit_type=listing.unit_type,
        )
    return kept


def _resolve_listing_images(db: Session | None, listings: list["prompts.PropertyListing"]) -> list[dict]:
    """Attach real subdivision photos and amenities to each model-proposed listing.

    The model only ever supplies text fields, never an image URL or amenity name, so it
    cannot hallucinate either. A listing whose project can't be resolved is kept with both
    empty — the frontend renders a placeholder rather than losing the listing.
    """
    resolved: list[dict] = []
    for listing in listings:
        image_urls: list[str] = []
        amenities: list[str] = []
        project_id: str | None = None
        if db is not None:
            try:
                project_id = answer_images_service.resolve_project_id(db, listing.project_name)
                project = db.get(Project, project_id) if project_id else None
                if project is not None:
                    gallery = ((project.details or {}).get("images") or {}).get("gallery") or []
                    gallery = [url for url in gallery if isinstance(url, str)]
                    image_urls = [
                        answer_images_service.public_gallery_url(url)
                        for url in answer_images_service.select_listing_images(
                            gallery,
                            listing.unit_type,
                            project_name=listing.project_name,
                            tower=listing.tower,
                            unit_code=listing.unit_code,
                        )
                    ]
                    amenities = answer_images_service.select_listing_amenities(project)
            except Exception:
                logger.exception(
                    "Could not resolve a listing's photos/amenities; keeping the listing without them.",
                    extra={"event": "pipeline.listing_image.failed", "project_name": listing.project_name},
                )
        resolved.append(
            {
                "project_name": listing.project_name,
                "unit_type": listing.unit_type,
                "area_range": listing.area_range,
                "price_range": listing.price_range,
                "image_urls": image_urls,
                "amenities": amenities,
                "project_id": project_id,
                "unit_code": listing.unit_code,
                "status": listing.status,
                "tower": listing.tower,
            }
        )
    return resolved


_CITATION_TOKEN_PATTERN = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]+(?:\+\d+)?", re.UNICODE)


def _citations_for(docs: list[dict], *, answer: str = "") -> list[dict]:
    """Citations are only worth showing when they point at one coherent source.

    An unscoped search can return hits from several unrelated projects. Chips naming 2-3
    projects under a reply that never engaged with any of them read as false grounding, and
    there's no principled way to know which project the answer actually used — so this
    drops citations entirely rather than pick one to keep.
    """
    project_ids = {doc.get("project_id") for doc in docs if doc.get("project_id")}
    if len(project_ids) > 1:
        return []
    return build_citations(_rank_citation_evidence(docs, answer))


def _rank_citation_evidence(docs: list[dict], answer: str) -> list[dict]:
    """Put the passage that best supports the generated claims first per document.

    Retrieval order alone is not enough: a broad overview can rank first while the exact
    price came from a later chunk. Numeric overlap outweighs prose overlap, since a number
    is the fact a page anchor matters most for. Stable, so unrelated answers keep retrieval
    order.
    """
    answer_tokens = _citation_tokens(answer)
    if not answer_tokens:
        return docs

    def evidence_score(doc: dict) -> tuple[int, int, float]:
        shared = answer_tokens & _citation_tokens(str(doc.get("content") or ""))
        numeric = sum(any(character.isdigit() for character in token) for token in shared)
        lexical = len(shared) - numeric
        retrieval_score = doc.get("score")
        return (
            numeric,
            lexical,
            float(retrieval_score) if isinstance(retrieval_score, int | float) else 0.0,
        )

    return sorted(docs, key=evidence_score, reverse=True)


def _citation_tokens(text: str) -> set[str]:
    return set(_CITATION_TOKEN_PATTERN.findall(strip_diacritics(text)))


def _verify(state: PipelineState) -> dict[str, Any]:
    """The Verifier Agent scores the draft independently of Generate.

    Returns the three numeric criteria plus the structured verdict (`failure_mode`,
    `verifier_feedback`, `next_action`). The feedback is what `_generate` reads on a
    retry, so a regeneration is aimed at the specific defect rather than blind.
    """
    docs = state.get("retrieved_docs") or []
    if state.get("catalog_context_complete") and catalog_context_service.is_tower_profile_query(state["query"]):
        docs = []
    context = [doc["content"] for doc in docs]
    if state.get("catalog_context"):
        context.append(state["catalog_context"])
    if state.get("catalog_offer_context"):
        context.append(state["catalog_offer_context"])
    coverage = format_preference_coverage(
        state.get("inventory_units") or [],
        state.get("criteria") or search_criteria.SearchCriteria(),
    )
    if coverage:
        context.append(coverage)
    if state.get("catalog_overview_context"):
        context.append(state["catalog_overview_context"])
    context.extend(prompts.format_unit_for_verifier(unit) for unit in state.get("inventory_units") or [])
    diagnosis = state.get("zero_result_diagnosis")
    if diagnosis is not None:
        context.append(search_criteria.format_diagnosis_for_verifier(diagnosis))
    query = _retrieval_query(state["query"], state.get("history"))
    started = time.perf_counter()
    listings_summary = "; ".join(
        f"{listing.get('project_name', '')} {listing.get('unit_type', '')} "
        f"{listing.get('area_range', '')} {listing.get('price_range', '')}".strip()
        for listing in state.get("listings") or []
    )
    answer_for_verification = state.get("draft_answer", "")
    if listings_summary:
        answer_for_verification = f"{answer_for_verification}\n[Thẻ căn hộ kèm theo, khách đã thấy]: {listings_summary}"
    result = verifier_service.score_answer(query, answer_for_verification, context)

    tracing.step(
        "verify",
        attempt=state.get("retry_count", 0) + 1,
        score=round(result.score, 4),
        faithfulness=round(result.faithfulness, 4),
        relevancy=round(result.relevancy, 4),
        completeness=round(result.completeness, 4),
        failure_mode=result.failure_mode.value,
        next_action=result.next_action.value,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )

    if _reflection_enabled() and result.failure_mode is not verifier_service.FailureMode.NONE:
        reflection_memory.record_lesson(
            query=state["query"],
            failure_mode=result.failure_mode.value,
            feedback=result.feedback,
            scope=state.get("reflection_scope"),
        )

    return {
        "verifier_score": round(result.score, 4),
        "faithfulness": round(result.faithfulness, 4),
        "answer_relevancy": round(result.relevancy, 4),
        "completeness": round(result.completeness, 4),
        "failure_mode": result.failure_mode.value,
        "verifier_feedback": result.feedback,
        "next_action": result.next_action.value,
    }


def _risk_check(state: PipelineState) -> dict[str, Any]:
    """Touches price/commitment -> raise the HITL flag so the Sale must read and confirm.

    Scans `listings` alongside `draft_answer`: a recommendation's price/area now lives in
    those structured cards rather than in the prose text (see prompts.PropertyListing), and
    a risk check that only read `draft_answer` would miss it entirely — the exact class of
    answer this flag exists to catch.
    """
    listings_text = " ".join(
        f"{listing.get('price_range', '')} {listing.get('area_range', '')}" for listing in state.get("listings") or []
    )
    requires_hitl = risk_service.detect_commitment_risk(f"{state.get('draft_answer', '')} {listings_text}")
    tracing.step("risk_check", requires_hitl=requires_hitl)
    return {"requires_hitl": requires_hitl}


def _image_tool(state: PipelineState) -> dict[str, Any]:
    """Fetch the project photos that belong under this answer.

    Runs *before* Generate, like the inventory tool, so the model knows the photos are
    coming — run afterwards it once told the Sale to ask Admin for pictures, printed
    directly above a strip of those pictures. The project is resolved from the question
    plus retrieved documents, since a Sale often asks "cho xem mặt bằng" without naming
    one.

    Needs a DB session; `run_pipeline` leaves it unset in contexts that have none (unit
    tests calling the pipeline directly), and the tool is simply skipped.
    """
    db = state.get("db")
    if db is None:
        tracing.step("tool.images", ok=False, skipped="no_db_session")
        return {"images": [], "floor_plan_towers_only": None}

    started = time.perf_counter()
    context = "\n".join(
        f"{doc.get('title') or ''} {doc.get('content') or ''}" for doc in state.get("retrieved_docs") or []
    )
    wants_explicit_images = answer_images_service.wants_images(state["query"])
    effective_project_id = state.get("project_id") if wants_explicit_images or context.strip() else None
    images = answer_images_service.collect_images(db, state["query"], context, project_id=effective_project_id)
    floor_plan_towers_only = answer_images_service.floor_plan_only_towers(
        db, state["query"], context, project_id=state.get("project_id")
    )
    tracing.step(
        "tool.images",
        ok=True,
        image_count=len(images),
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return {"images": images, "floor_plan_towers_only": floor_plan_towers_only}


def _route_after_cache(state: PipelineState) -> str:
    return "hit" if state.get("used_cache") else "miss"


def _route_after_preflight(state: PipelineState) -> str:
    if state.get("notice"):
        return "stop"
    if state.get("answered_from_memory"):
        return "answer"
    return "continue"


def _route_after_retrieve(state: PipelineState) -> str:
    if state.get("notice"):
        return "stop"
    return "criteria_resolve"


def _route_after_criteria(state: PipelineState) -> str:
    if state.get("notice"):
        return "stop"
    return "tool_call" if state.get("needs_inventory") or is_search_refinement(state["query"]) else "generate"


def _route_after_tool_call(state: PipelineState) -> str:
    return "stop" if state.get("notice") else "generate"


def _route_after_generate(state: PipelineState) -> str:
    if state.get("notice"):
        return "stop"

    if state.get("images") and answer_images_service.wants_images(state["query"]):
        return "risk_check"

    if state.get("history") and is_conversation_meta_query(state["query"]):
        tracing.step("route.after_generate", decision="skip_verify", reason="conversation_meta_query")
        return "risk_check"

    if (
        not state.get("retrieved_docs")
        and not state.get("inventory_units")
        and not state.get("zero_result_diagnosis")
        and not state.get("catalog_context")
        and not state.get("catalog_offer_context")
    ):
        return "risk_check"

    return "verify"


def _route_after_verify(state: PipelineState) -> str:
    """Low score gets one regeneration; still low means declining beats answering wrongly.

    The Verifier's `next_action` is a proposal this overrides both ways: "decline"
    short-circuits a retry that would just burn a call to reproduce the same gap, but a
    passing score wins regardless — the threshold is tuned on the score, not the verdict.
    """
    score = state.get("verifier_score", 0.0)
    if score >= _threshold():
        tracing.step("route.after_verify", decision="accept", score=score)
        return "risk_check"

    if state.get("next_action") == verifier_service.NextAction.DECLINE.value:
        tracing.step("route.after_verify", decision="decline", score=score, reason="verifier_declined")
        return "low_confidence"

    if state.get("retry_count", 0) < MAX_GENERATE_RETRIES:
        tracing.step("route.after_verify", decision="retry", score=score)
        return "retry"

    tracing.step("route.after_verify", decision="decline", score=score, reason="retries_exhausted")
    return "low_confidence"


def _bump_retry(state: PipelineState) -> dict[str, Any]:
    return {"retry_count": state.get("retry_count", 0) + 1}


def _low_confidence(state: PipelineState) -> dict[str, Any]:
    return {"notice": _low_confidence_message(state.get("clearance", DocumentVisibility.INTERNAL))}


def _build_graph():
    graph = StateGraph(PipelineState)

    graph.add_node("preflight", _preflight)
    graph.add_node("scope_resolve", _scope_resolve)
    graph.add_node("cache_check", _cache_check)
    graph.add_node("retrieve", _retrieve)
    graph.add_node("criteria_resolve", _criteria_resolve)
    graph.add_node("tool_call", _tool_call)
    graph.add_node("criteria_diagnose", _criteria_diagnose)
    graph.add_node("generate", _generate)
    graph.add_node("verify", _verify)
    graph.add_node("risk_check", _risk_check)
    graph.add_node("image_tool", _image_tool)
    graph.add_node("bump_retry", _bump_retry)
    graph.add_node("low_confidence", _low_confidence)

    graph.add_edge(START, "preflight")
    graph.add_conditional_edges(
        "preflight",
        _route_after_preflight,
        {"stop": END, "answer": END, "continue": "scope_resolve"},
    )
    graph.add_edge("scope_resolve", "cache_check")
    graph.add_conditional_edges("cache_check", _route_after_cache, {"hit": END, "miss": "retrieve"})
    graph.add_conditional_edges(
        "retrieve", _route_after_retrieve, {"stop": END, "criteria_resolve": "criteria_resolve"}
    )
    graph.add_conditional_edges(
        "criteria_resolve", _route_after_criteria, {"stop": END, "tool_call": "tool_call", "generate": "image_tool"}
    )
    graph.add_conditional_edges("tool_call", _route_after_tool_call, {"stop": END, "generate": "criteria_diagnose"})
    graph.add_edge("criteria_diagnose", "image_tool")
    graph.add_conditional_edges(
        "generate", _route_after_generate, {"stop": END, "verify": "verify", "risk_check": "risk_check"}
    )
    graph.add_conditional_edges(
        "verify",
        _route_after_verify,
        {"risk_check": "risk_check", "retry": "bump_retry", "low_confidence": "low_confidence"},
    )
    graph.add_edge("bump_retry", "generate")
    graph.add_edge("low_confidence", END)
    graph.add_edge("image_tool", "generate")
    graph.add_edge("risk_check", END)

    return graph.compile()


_COMPILED_GRAPH = None


def _get_graph():
    global _COMPILED_GRAPH
    if _COMPILED_GRAPH is None:
        _COMPILED_GRAPH = _build_graph()
    return _COMPILED_GRAPH


def run_pipeline(
    query: str,
    project_id: str | None = None,
    db: Session | None = None,
    history: list[dict] | None = None,
    memory_profile: str = "",
    clearance: DocumentVisibility = DocumentVisibility.INTERNAL,
    session_id: int | None = None,
    reflection_scope: str | None = None,
    memory_profile_data: memory_service.UserProfile | None = None,
) -> PipelineResult:
    """Entry point for the Sale and customer chat flows.

    `clearance` is the asker's RBAC tier: INTERNAL (default) reads internal+public
    documents; the customer chat flow always passes PUBLIC.

    `db` is only used by the image tool; optional so callers with no session still work,
    just with no photos attached.

    `history` is prior turns, oldest first, from BEFORE this `query` — the caller persists
    the new turn separately, so passing it here too would show the model its own question
    twice. Capped to `MAX_HISTORY_MESSAGES` here so callers needn't think about the limit.

    Never raises: the router builds the response message directly from this, so every
    failure must collapse into a readable `PipelineResult`.
    """
    if not query or not query.strip():
        return PipelineResult(_empty_state_message(clearance), [], 0.0, False, emotion=MessageEmotion.REGRETFUL)

    tracing.start_run(query_len=len(query), project_id=project_id, clearance=str(clearance))
    try:
        return _run_traced(
            query,
            project_id,
            db,
            history,
            memory_profile,
            clearance,
            session_id,
            reflection_scope,
            memory_profile_data,
        )
    finally:
        tracing.finish()


def _run_traced(
    query: str,
    project_id: str | None,
    db: Session | None,
    history: list[dict] | None,
    memory_profile: str,
    clearance: DocumentVisibility,
    session_id: int | None,
    reflection_scope: str | None,
    memory_profile_data: memory_service.UserProfile | None,
) -> PipelineResult:
    """The body of `run_pipeline`, split out so tracing can wrap every exit path."""
    reflection_lessons = _lessons_for(query, reflection_scope) if reflection_scope is not None else _lessons_for(query)
    initial: PipelineState = {
        "query": query.strip(),
        "session_id": session_id,
        "project_id": project_id,
        "resolved_project_ids": [],
        "excluded_project_ids": [],
        "memory_profile": memory_profile,
        "memory_profile_data": memory_profile_data or memory_service.UserProfile(),
        "reflection_lessons": reflection_lessons,
        "reflection_scope": reflection_scope,
        "clearance": clearance,
        "history": (history or [])[-MAX_HISTORY_MESSAGES:],
        "retrieved_docs": [],
        "catalog_context": "",
        "catalog_context_complete": False,
        "catalog_offers": [],
        "catalog_offer_context": "",
        "catalog_overview_context": "",
        "citations": [],
        "verifier_score": 0.0,
        "requires_hitl": False,
        "retry_count": 0,
        "used_cache": False,
        "images": [],
        "db": db,
    }

    try:
        state = _get_graph().invoke(initial)
    except Exception:
        logger.exception(
            "Pipeline sap — tra ve thong bao loi chung.",
            extra={
                "event": "pipeline.crash",
                "project_id": project_id,
                "query_len": len(query),
            },
        )
        tracing.set_outcome(outcome="crash", verifier_score=0.0)
        return PipelineResult(GENERATION_ERROR_MESSAGE, [], 0.0, False, emotion=MessageEmotion.REGRETFUL)

    notice = state.get("notice")
    if notice:
        notice_is_system_failure = notice in (RETRIEVAL_ERROR_MESSAGE, GENERATION_ERROR_MESSAGE)
        tracing.set_outcome(
            outcome="notice",
            verifier_score=state.get("verifier_score", 0.0),
            failure_mode=state.get("failure_mode"),
            retry_count=state.get("retry_count", 0),
        )
        return PipelineResult(
            notice,
            [],
            0.0,
            False,
            images=[] if notice_is_system_failure else state.get("images") or [],
            failure_mode=state.get("failure_mode"),
            verifier_feedback=state.get("verifier_feedback"),
            emotion=state.get("notice_emotion", MessageEmotion.REGRETFUL),
        )

    result = PipelineResult(
        draft_answer=state.get("draft_answer", ""),
        citations=state.get("citations") or [],
        quick_replies=state.get("quick_replies") or [],
        listings=state.get("listings") or [],
        suggested_questions=state.get("suggested_questions") or [],
        verifier_score=state.get("verifier_score", 0.0),
        requires_hitl=state.get("requires_hitl", False),
        used_cache=state.get("used_cache", False),
        faithfulness=state.get("faithfulness"),
        answer_relevancy=state.get("answer_relevancy"),
        completeness=state.get("completeness"),
        failure_mode=state.get("failure_mode"),
        verifier_feedback=state.get("verifier_feedback"),
        images=state.get("images") or [],
        emotion=MessageEmotion.HAPPY,
    )

    active_criteria = state.get("criteria")
    if (
        not result.used_cache
        and not initial["history"]
        and not memory_profile
        and (active_criteria is None or active_criteria.is_empty())
    ):
        _store_cache(query, result, state.get("project_id"), clearance)

    tracing.set_outcome(
        outcome="answered",
        verifier_score=result.verifier_score,
        failure_mode=result.failure_mode,
        requires_hitl=result.requires_hitl,
        used_cache=result.used_cache,
        retry_count=state.get("retry_count", 0),
        citation_count=len(result.citations),
    )
    return result


def _store_cache(query: str, result: PipelineResult, project_id: str | None, clearance: DocumentVisibility) -> None:
    """Cache only answers that pass the Verifier and carry nothing question-specific.

    Price-touching answers ARE cached: RiskCheck just re-runs on a cache hit instead (see
    `_cache_check`) — refusing them once emptied the cache of nearly every real answer.

    Answers carrying photos are never cached: the cache matches on meaning, and "cho xem
    hình ảnh" vs "cho xem mặt bằng" are close enough to collide, serving the wrong photo
    set to a question that asked for something narrower.
    """
    if result.verifier_score < _threshold():
        return

    if result.images:
        return

    if result.listings:
        return

    cache_service.store_cache(
        query=query,
        answer=result.draft_answer,
        citations=result.citations,
        verifier_score=result.verifier_score,
        project_id=project_id,
        images=result.images,
        clearance=clearance,
    )


def _threshold() -> float:
    """Read the threshold at call time so settings changed by tests/Admin take effect immediately."""
    from backend.core.config import get_settings

    return get_settings().verifier_threshold_sale


def _reflection_enabled() -> bool:
    """Read at call time, for the same reason as `_threshold`."""
    from backend.core.config import get_settings

    return get_settings().reflection_memory_enabled


def _lessons_for(query: str, scope: str | None = None) -> str:
    """Lessons from earlier mistakes that apply to this question, rendered for the prompt.

    Never raises: reflection memory is an improvement layer, and a Redis problem here must
    cost the lesson, not the answer.
    """
    if not _reflection_enabled():
        return ""

    try:
        return reflection_memory.format_lessons(reflection_memory.relevant_lessons(query, scope=scope))
    except Exception:  # pragma: no cover - defensive; the service already fails open
        logger.warning(
            "Doc reflection memory that bai; tra loi khong kem bai hoc nao.",
            exc_info=True,
            extra={"event": "pipeline.reflection.failed"},
        )
        return ""
