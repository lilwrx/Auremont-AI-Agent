"""Verifier Agent: score a draft answer against its source documents.

This is the gate between "the LLM said something plausible" and "a Sale reads those
figures out to a customer". The Main Agent generates from context but can still invent
numbers or drift off-topic, so the Verifier independently scores four things:

* **faithfulness** (grounding) — is the answer grounded in the context, or partly invented?
* **relevancy** (correctness) — does the answer actually address the question asked?
* **completeness** — are all parts of a multi-part question answered, or only the first?
* **actionability** — via `failure_mode` / `feedback` / `next_action`, can the regeneration
  step actually act on this verdict?

The final score is the `min` of the three numeric criteria: an answer that is truthful but
off-topic, on-topic but with invented figures, or correct but half-answered must not pass.

A score alone is not enough. A judge that only says "0.4" gives the regeneration step
nothing to correct, so it re-runs the same prompt and usually produces the same answer.
The judge therefore also emits a `failure_mode`, human-readable `feedback` and a
`next_action`, which `agent_pipeline` feeds back into the retry as a correction note —
this is what makes the retry a genuine Reflexion loop rather than a blind repeat. The
structured `failure_mode` additionally lets the Admin dashboard group failures by cause
instead of showing an undifferentiated list of low scores.

Uses LLM-as-judge via Gemini rather than DeepEval inline: DeepEval defaults to calling
OpenAI (this project runs Gemini) and is noticeably slower, while the whole pipeline has
to stay under a 3-second field response budget. DeepEval remains a good fit for offline
batch evaluation under `eval/`.
"""

import logging
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from backend.core.config import settings
from backend.core.gemini_client import generate_json

logger = logging.getLogger(__name__)


class FailureMode(StrEnum):
    """Why an answer failed, in terms the retry and the dashboard can both act on.

    Deliberately a closed set: free-text reasons cannot be grouped or filtered, and the
    whole point of classifying the failure is to be able to count how often each kind
    happens and to route the regeneration differently for each.
    """

    NONE = "none"
    HALLUCINATED_FACT = "hallucinated-fact"
    INCOMPLETE_ANSWER = "incomplete-answer"
    OFF_TOPIC = "off-topic"
    MISSING_EVIDENCE = "missing-evidence"
    UNSUPPORTED_COMMITMENT = "unsupported-commitment"


class NextAction(StrEnum):
    """What the pipeline should do next. The judge proposes; `agent_pipeline` decides."""

    ACCEPT = "accept"
    REGENERATE = "regenerate"
    DECLINE = "decline"


_JUDGE_SYSTEM_INSTRUCTION = (
    "Bạn là bộ chấm điểm độc lập cho hệ thống RAG tư vấn bất động sản. "
    "Bạn KHÔNG trả lời câu hỏi, chỉ chấm điểm câu trả lời của người khác. "
    "Luôn trả về đúng một object JSON, không kèm giải thích."
)

_JUDGE_PROMPT = """Chấm điểm CÂU TRẢ LỜI dựa trên NGỮ CẢNH được trích từ tài liệu gốc.

Ba tiêu chí, mỗi tiêu chí cho điểm từ 0.0 đến 1.0:
- "faithfulness": mọi thông tin trong câu trả lời có được NGỮ CẢNH chứng minh không?
  Bịa số liệu, thêm cam kết không có trong ngữ cảnh -> điểm thấp.
- "relevancy": câu trả lời có trực tiếp giải đáp CÂU HỎI không?
  Lan man, trả lời sang chuyện khác -> điểm thấp.
- "completeness": câu hỏi có mấy ý thì đã trả lời đủ từng ấy ý chưa?
  Câu hỏi hỏi 2 điều mà chỉ trả lời 1 -> điểm thấp. Câu hỏi chỉ có 1 ý và đã
  được trả lời trọn vẹn -> điểm cao.

Sau đó phân loại lỗi và nêu hướng sửa:
- "failure_mode": chọn ĐÚNG MỘT giá trị:
  "none" (đạt), "hallucinated-fact" (bịa số liệu/thông tin),
  "incomplete-answer" (thiếu ý), "off-topic" (trả lời lệch câu hỏi),
  "missing-evidence" (ngữ cảnh không hề có dữ liệu để trả lời),
  "unsupported-commitment" (hứa hẹn/cam kết không có trong ngữ cảnh).
- "feedback": MỘT câu tiếng Việt nói RÕ sai ở đâu và cần sửa gì, đủ cụ thể để
  người viết lại câu trả lời sửa được ngay. Không viết chung chung kiểu
  "câu trả lời chưa tốt". Nếu đạt thì để chuỗi rỗng.
- "next_action": "accept" (đạt), "regenerate" (viết lại thì cứu được),
  "decline" (ngữ cảnh không có dữ liệu, viết lại cũng vô ích).

NGOẠI LỆ QUAN TRỌNG: nếu CÂU TRẢ LỜI là một lời từ chối trung thực — thẳng thắn nói KHÔNG có
đủ dữ liệu để trả lời đúng điều được hỏi, không bịa số liệu thay thế — thì cho CẢ HAI tiêu chí
đều 1.0, bất kể câu đó có chứa số liệu hay không. Từ chối đúng lúc khi thiếu dữ liệu là hành vi
ĐÚNG của hệ thống, không phải câu trả lời kém chất lượng — không chấm thấp chỉ vì nó là câu giao
tiếp thay vì số liệu cụ thể.

NGOẠI LỆ QUAN TRỌNG THỨ HAI: trợ lý tư vấn bất động sản cho khách hàng được thiết kế để hỏi khảo
sát nhu cầu từng bước (mục đích ở/đầu tư, loại hình bất động sản, ngân sách, phân khu ưu tiên...)
TRƯỚC khi đưa ra gợi ý cụ thể, giống hệt cách một chuyên viên tư vấn thật làm việc — đây không
phải trả lời né tránh. Nếu CÂU TRẢ LỜI là MỘT câu hỏi khảo sát tự nhiên, đúng chủ đề, hỏi về đúng
một điều còn thiếu để tư vấn chính xác hơn (và CÂU HỎI của khách chưa hề cung cấp sẵn thông tin
đó), cho "completeness" và "relevancy" đều 1.0 — KHÔNG chấm là "thiếu ý" chỉ vì câu trả lời chưa
đưa ra số liệu/lựa chọn cụ thể ngay. Ngoại lệ này KHÔNG áp dụng khi: câu trả lời hỏi lại thông tin
khách đã nêu rõ trong CÂU HỎI, câu trả lời hỏi nhiều hơn một điều cùng lúc, hoặc câu hỏi của khách
đã đủ cụ thể để trả lời thẳng mà trợ lý vẫn vòng vo hỏi thêm — những trường hợp đó vẫn chấm điểm
completeness thấp như bình thường.

CÂU HỎI:
{query}

NGỮ CẢNH:
{context}

CÂU TRẢ LỜI:
{answer}

Chỉ trả về JSON đúng định dạng:
{{"faithfulness": <số>, "relevancy": <số>, "completeness": <số>,
"failure_mode": "<mã lỗi>", "feedback": "<một câu>", "next_action": "<hành động>"}}"""


class VerifierResult(BaseModel):
    """A judgement about one draft answer.

    Doubles as the response schema handed to Gemini, so the model is constrained to emit
    exactly these fields in this range instead of prose that has to be scraped.
    """

    faithfulness: float = Field(ge=0.0, le=1.0, description="Is every claim supported by the context?")
    relevancy: float = Field(ge=0.0, le=1.0, description="Does the answer address the question asked?")
    completeness: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Are all parts of a multi-part question answered?",
    )
    failure_mode: FailureMode = Field(
        default=FailureMode.NONE,
        description="Which kind of failure this is, for the retry and the dashboard.",
    )
    feedback: str = Field(
        default="",
        description="One concrete sentence naming what is wrong, for the regeneration step.",
    )
    next_action: NextAction = Field(
        default=NextAction.ACCEPT,
        description="What the pipeline should do about this verdict.",
    )

    @field_validator("faithfulness", "relevancy", "completeness", mode="before")
    @classmethod
    def _coerce_score(cls, value: object) -> float:
        """Accept the shapes judges actually emit: "0.85", 85, None.

        A model that mistakes the scale and answers 85 means 0.85. Only values clearly on
        a 0-100 scale are converted; a slight overshoot like 1.5 is the judge being loose
        on the 0-1 scale, and dividing that would distort the score more than clamping.
        """
        try:
            score = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0

        if score > 10.0:
            score = score / 100.0
        return max(0.0, min(1.0, score))

    @field_validator("failure_mode", mode="before")
    @classmethod
    def _coerce_failure_mode(cls, value: object) -> object:
        """An unrecognised label must not fail the whole verdict.

        The judge occasionally invents a mode outside the enum. Losing the three numeric
        scores over an unknown string would be a far worse outcome than losing the
        classification, so anything unrecognised degrades to NONE.
        """
        if isinstance(value, FailureMode):
            return value
        if isinstance(value, str):
            candidate = value.strip().lower().replace("_", "-")
            if candidate in {mode.value for mode in FailureMode}:
                return candidate
        return FailureMode.NONE

    @field_validator("next_action", mode="before")
    @classmethod
    def _coerce_next_action(cls, value: object) -> object:
        """Same reasoning as `_coerce_failure_mode`.

        Falls back to REGENERATE rather than ACCEPT: an unreadable verdict must never be
        the reason a low-scoring answer is waved through to the Sale.
        """
        if isinstance(value, NextAction):
            return value
        if isinstance(value, str):
            candidate = value.strip().lower().replace("_", "-")
            if candidate in {action.value for action in NextAction}:
                return candidate
        return NextAction.REGENERATE

    @field_validator("feedback", mode="before")
    @classmethod
    def _coerce_feedback(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @property
    def score(self) -> float:
        """The weakest of the three. An answer that is truthful but off-topic, on-topic
        with invented figures, or correct but half-answered must fail either way."""
        return min(self.faithfulness, self.relevancy, self.completeness)


_FAILED_VERIFICATION = VerifierResult(
    faithfulness=0.0,
    relevancy=0.0,
    completeness=0.0,
    failure_mode=FailureMode.MISSING_EVIDENCE,
    feedback="Không chấm điểm được câu trả lời (Verifier lỗi hoặc thiếu ngữ cảnh).",
    next_action=NextAction.DECLINE,
)


def score_answer(query: str, draft_answer: str, retrieved_context: list[str]) -> VerifierResult:
    """Score a draft answer. Never raises — a scoring failure scores 0.0.

    Failing closed is deliberate: the pipeline then takes the "not enough information"
    branch instead of handing the Sale an unverified answer. Bad advice costs more than a
    refusal does.
    """
    if not draft_answer.strip() or not retrieved_context:
        return _FAILED_VERIFICATION

    prompt = _JUDGE_PROMPT.format(
        query=query,
        context="\n---\n".join(retrieved_context),
        answer=draft_answer,
    )

    try:
        result = generate_json(prompt, VerifierResult, system_instruction=_JUDGE_SYSTEM_INSTRUCTION)
    except Exception:
        logger.exception(
            "Judge LLM call failed; scoring 0.0 (fail closed).",
            extra={"event": "verifier.judge.failed", "context_count": len(retrieved_context)},
        )
        return _FAILED_VERIFICATION

    if result is None:
        logger.warning(
            "Judge returned no parseable verdict; scoring 0.0 (fail closed).",
            extra={"event": "verifier.judge.empty"},
        )
        return _FAILED_VERIFICATION

    if result.failure_mode is not FailureMode.NONE:
        logger.info(
            "Verifier rejected a draft answer.",
            extra={
                "event": "verifier.judge.rejected",
                "failure_mode": result.failure_mode.value,
                "next_action": result.next_action.value,
                "score": round(result.score, 4),
                "faithfulness": round(result.faithfulness, 4),
                "relevancy": round(result.relevancy, 4),
                "completeness": round(result.completeness, 4),
            },
        )

    return result


def passes_threshold(result: VerifierResult) -> bool:
    """Below the threshold -> show the limitation warning instead of giving the Sale the answer."""
    return result.score >= settings.verifier_threshold_sale
