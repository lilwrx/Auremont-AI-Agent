"""Reflection memory reaching the pipeline: the agent stops repeating a past mistake.

The Reflexion loop already fixes a draft *within* one question. What these tests cover is
the loop one level wider: a lesson learned while answering an earlier question arriving in
a later question's prompt, before the model generates — so the second question does not
have to earn the same rejection and pay for the same extra Gemini call to fix it.
"""

import pytest

from backend.ai import prompts
from backend.core.config import settings
from backend.services import agent_pipeline, reflection_memory
from backend.services.verifier_service import FailureMode, NextAction, VerifierResult

DOCS = [{"document_id": 1, "title": "csbh.pdf", "page": 2, "content": "Chinh sach thanh toan 5 dot.", "score": 0.8}]
COMPLAINT = "Chua neu dieu kien ap dung kem con so."


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)


@pytest.fixture
def reflection_redis(monkeypatch):
    client = _FakeRedis()
    monkeypatch.setattr(reflection_memory, "get_redis_client", lambda: client)
    monkeypatch.setattr(settings, "reflection_memory_enabled", True)
    return client


def _verdict(score: float, **overrides) -> VerifierResult:
    base = {
        "faithfulness": score,
        "relevancy": score,
        "completeness": score,
        "failure_mode": FailureMode.NONE if score >= 0.7 else FailureMode.INCOMPLETE_ANSWER,
        "feedback": "" if score >= 0.7 else COMPLAINT,
        "next_action": NextAction.ACCEPT if score >= 0.7 else NextAction.REGENERATE,
    }
    return VerifierResult(**(base | overrides))


def _run(
    monkeypatch,
    query: str,
    *,
    verdicts: list[VerifierResult],
    reflection_scope: str | None = None,
) -> list[str]:
    """Run one question with scripted verdicts; return the Generate prompts it produced."""
    seen: list[str] = []
    remaining = list(verdicts)

    monkeypatch.setattr(agent_pipeline, "retrieve", lambda *a, **k: DOCS)
    monkeypatch.setattr(agent_pipeline.cache_service, "lookup_cache", lambda *a, **k: None)
    monkeypatch.setattr(agent_pipeline, "_store_cache", lambda *a, **k: None)
    monkeypatch.setattr(agent_pipeline, "query_needs_documents", lambda query: True)
    monkeypatch.setattr(agent_pipeline, "query_needs_inventory", lambda query: False)
    monkeypatch.setattr(agent_pipeline.risk_service, "detect_commitment_risk", lambda answer: False)

    def _generate_json(prompt, schema, system_instruction=None):
        seen.append(prompt)
        return schema(text="- Chinh sach thanh toan chia 5 dot.")

    monkeypatch.setattr(agent_pipeline, "generate_json", _generate_json)
    monkeypatch.setattr(
        agent_pipeline.verifier_service,
        "score_answer",
        lambda *a, **k: remaining.pop(0) if remaining else _verdict(0.9),
    )

    agent_pipeline.run_pipeline(query, reflection_scope=reflection_scope)
    return seen


def test_a_lesson_from_one_question_reaches_the_next(reflection_redis, monkeypatch):
    """Diem cot loi: cau hoi sau duoc nhac ve loi cua cau hoi truoc, TRUOC khi sinh."""
    _run(monkeypatch, "Chinh sach thanh toan the nao?", verdicts=[_verdict(0.3), _verdict(0.9)])

    later = _run(monkeypatch, "Chinh sach thanh toan ra sao?", verdicts=[_verdict(0.9)])

    assert "BÀI HỌC TỪ CÁC LỖI TRƯỚC ĐÂY" in later[0]


def test_the_first_question_ever_asked_carries_no_lessons(reflection_redis, monkeypatch):
    seen = _run(monkeypatch, "Chinh sach thanh toan the nao?", verdicts=[_verdict(0.9)])

    assert "BÀI HỌC TỪ CÁC LỖI TRƯỚC ĐÂY" not in seen[0]


def test_an_unrelated_later_question_carries_no_lessons(reflection_redis, monkeypatch):
    """Bai hoc khong lien quan van ton token tren moi cau hoi."""
    _run(monkeypatch, "Chinh sach thanh toan the nao?", verdicts=[_verdict(0.3), _verdict(0.9)])

    later = _run(monkeypatch, "Tien ich noi khu gom nhung gi?", verdicts=[_verdict(0.9)])

    assert "BÀI HỌC TỪ CÁC LỖI TRƯỚC ĐÂY" not in later[0]


def test_a_passing_answer_teaches_nothing(reflection_redis, monkeypatch):
    _run(monkeypatch, "Chinh sach thanh toan the nao?", verdicts=[_verdict(0.9)])

    assert reflection_memory.load_lessons() == []


def test_the_lesson_is_stored_with_its_failure_mode(reflection_redis, monkeypatch):
    _run(monkeypatch, "Chinh sach thanh toan the nao?", verdicts=[_verdict(0.3), _verdict(0.9)])

    stored = reflection_memory.load_lessons()
    assert len(stored) == 1
    assert stored[0].failure_mode == FailureMode.INCOMPLETE_ANSWER.value


def test_pipeline_reads_and_writes_reflections_in_the_same_session_scope(reflection_redis, monkeypatch):
    customer_a = reflection_memory.sale_session_scope(201)
    customer_b = reflection_memory.sale_session_scope(202)

    _run(
        monkeypatch,
        "Chinh sach thanh toan the nao?",
        verdicts=[_verdict(0.3), _verdict(0.9)],
        reflection_scope=customer_a,
    )
    other_customer = _run(
        monkeypatch,
        "Chinh sach thanh toan ra sao?",
        verdicts=[_verdict(0.9)],
        reflection_scope=customer_b,
    )
    same_customer = _run(
        monkeypatch,
        "Chinh sach thanh toan ra sao?",
        verdicts=[_verdict(0.9)],
        reflection_scope=customer_a,
    )

    assert "BÀI HỌC TỪ CÁC LỖI TRƯỚC ĐÂY" not in other_customer[0]
    assert "BÀI HỌC TỪ CÁC LỖI TRƯỚC ĐÂY" in same_customer[0]


def test_disabled_flag_neither_reads_nor_writes(reflection_redis, monkeypatch):
    monkeypatch.setattr(settings, "reflection_memory_enabled", False)

    seen = _run(monkeypatch, "Chinh sach thanh toan the nao?", verdicts=[_verdict(0.3), _verdict(0.9)])

    assert "BÀI HỌC TỪ CÁC LỖI TRƯỚC ĐÂY" not in seen[0]
    assert reflection_memory.load_lessons() == []


def test_redis_outage_still_answers(monkeypatch):
    """Mat bai hoc thi chap nhan duoc; mat cau tra loi thi khong."""
    monkeypatch.setattr(settings, "reflection_memory_enabled", True)
    monkeypatch.setattr(reflection_memory, "get_redis_client", lambda: None)

    seen = _run(monkeypatch, "Chinh sach thanh toan the nao?", verdicts=[_verdict(0.9)])

    assert seen


def test_correction_is_read_after_the_lessons():
    """Bai hoc la chi thi chung; correction noi ve ban nhap vua bi tu choi nen phai doc sau."""
    prompt = prompts.build_prompt(
        "Chinh sach thanh toan the nao?",
        DOCS,
        [],
        False,
        False,
        correction=COMPLAINT,
        lessons="- Khi chinh sach thanh toan: neu dieu kien ap dung",
    )

    assert prompt.index("BÀI HỌC TỪ CÁC LỖI TRƯỚC ĐÂY") < prompt.index("SỬA LỖI CỦA LẦN TRẢ LỜI TRƯỚC")


def test_lessons_are_marked_as_not_being_project_data():
    """Bai hoc khong phai grounding — model khong duoc lay so lieu tu do."""
    prompt = prompts.build_prompt(
        "Chinh sach thanh toan the nao?",
        DOCS,
        [],
        False,
        False,
        lessons="- Khi chinh sach thanh toan: neu dieu kien ap dung",
    )

    assert "KHÔNG phải dữ liệu dự án" in prompt


def test_blank_lessons_leave_the_prompt_untouched():
    without = prompts.build_prompt("Chinh sach thanh toan the nao?", DOCS, [], False, False)
    with_blank = prompts.build_prompt("Chinh sach thanh toan the nao?", DOCS, [], False, False, lessons="  ")

    assert without == with_blank
