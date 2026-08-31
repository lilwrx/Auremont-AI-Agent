"""Reflection memory — lessons learned from rejections, and why they stay short.

The value of this layer is entirely in *not* being chat history: a lesson has to be
compressed, deduplicated, capped, and matched to the question at hand, or it becomes a
prompt tax paid on every question. Each of those properties is asserted here.
"""

import pytest

from backend.services import reflection_memory
from backend.services.reflection_memory import Lesson


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)


class _BrokenRedis:
    def get(self, key):
        raise ConnectionError("redis down")

    def set(self, key, value, ex=None):
        raise ConnectionError("redis down")

    def delete(self, key):
        raise ConnectionError("redis down")


@pytest.fixture
def fake_redis(monkeypatch):
    client = _FakeRedis()
    monkeypatch.setattr(reflection_memory, "get_redis_client", lambda: client)
    return client


@pytest.fixture
def broken_redis(monkeypatch):
    monkeypatch.setattr(reflection_memory, "get_redis_client", lambda: _BrokenRedis())


def _record(query: str, mode: str = "incomplete-answer", feedback: str = "Chua tra loi tien do thanh toan.") -> None:
    reflection_memory.record_lesson(query=query, failure_mode=mode, feedback=feedback)


def test_a_rejection_becomes_a_lesson(fake_redis):
    _record("Chinh sach thanh toan du an The Palma the nao?")

    lessons = reflection_memory.load_lessons()
    assert len(lessons) == 1
    assert lessons[0].failure_mode == "incomplete-answer"
    assert lessons[0].lesson
    assert lessons[0].trigger


def test_a_passing_answer_records_nothing(fake_redis):
    reflection_memory.record_lesson(query="Gia can 2PN?", failure_mode="none", feedback="")

    assert reflection_memory.load_lessons() == []


def test_a_rejection_without_feedback_records_nothing(fake_redis):
    """Khong noi duoc sai o dau thi khong co bai hoc nao de rut ra."""
    reflection_memory.record_lesson(query="Gia can 2PN?", failure_mode="off-topic", feedback="   ")

    assert reflection_memory.load_lessons() == []


def test_the_fix_generalises_from_the_failure_mode(fake_redis):
    """`feedback` noi lan nay sai gi; `fix` phai dung duoc cho cau hoi sau."""
    _record("Chinh sach thanh toan the nao?", mode="hallucinated-fact", feedback="Ghi 4,1 ty nhung ngu canh co 3,6 ty.")

    assert "không suy diễn" in reflection_memory.load_lessons()[0].fix


def test_the_same_mistake_twice_reinforces_one_lesson(fake_redis):
    """Hai lan cung mot loi khong duoc thanh hai dong prompt noi cung mot chuyen."""
    _record("Chinh sach thanh toan du an nay the nao?")
    _record("Chinh sach thanh toan du an nay the nao?")

    lessons = reflection_memory.load_lessons()
    assert len(lessons) == 1
    assert lessons[0].hits == 2


def test_a_long_feedback_is_condensed_to_one_sentence(fake_redis):
    _record(
        "Chinh sach thanh toan the nao?",
        feedback="Cau tra loi chi neu gia. Con thieu tien do thanh toan va dieu kien chiet khau di kem.",
    )

    lesson = reflection_memory.load_lessons()[0].lesson
    assert lesson == "Cau tra loi chi neu gia"


def test_stored_lessons_are_capped(fake_redis):
    """Memory dai qua lam prompt noisy va tang cost — nen phai co tran cung."""
    for index in range(reflection_memory.MAX_LESSONS + 6):
        _record(f"chude{index} khaosat{index} phankhu{index}")

    assert len(reflection_memory.load_lessons()) == reflection_memory.MAX_LESSONS


def test_the_least_reinforced_lesson_is_evicted_first(fake_redis):
    """Bai hoc lap lai nhieu lan la loi that; bai hoc mot lan la re nhat de bo."""
    for index in range(reflection_memory.MAX_LESSONS):
        _record(f"chude{index} khaosat{index} phankhu{index}")
    repeated = "Chinh sach thanh toan the nao"
    _record(repeated)
    _record(repeated)

    for index in range(100, 105):
        _record(f"chude{index} khaosat{index} phankhu{index}")

    triggers = [lesson.trigger for lesson in reflection_memory.load_lessons()]
    assert any("thanh toan" in trigger for trigger in triggers)


def test_a_similar_question_gets_the_lesson(fake_redis):
    _record("Chinh sach thanh toan du an The Palma the nao?")

    lessons = reflection_memory.relevant_lessons("Chinh sach thanh toan cua du an nay ra sao?")

    assert len(lessons) == 1


def test_an_unrelated_question_gets_nothing(fake_redis):
    """Bai hoc khong lien quan van ton token — thà không có còn hơn."""
    _record("Chinh sach thanh toan du an The Palma the nao?")

    assert reflection_memory.relevant_lessons("Tien ich noi khu gom nhung gi?") == []


def test_one_shared_common_word_is_not_a_match(fake_redis):
    """Trung mot tu la trung hop, khong phai lien quan."""
    _record("Chinh sach thanh toan du an the nao?")

    assert reflection_memory.relevant_lessons("Du an co bao nhieu toa?") == []


def test_only_a_couple_of_lessons_reach_one_prompt(fake_redis):
    for index in range(6):
        _record(f"Chinh sach thanh toan dot {index} the nao?")

    lessons = reflection_memory.relevant_lessons("Chinh sach thanh toan the nao?")

    assert len(lessons) <= reflection_memory.MAX_LESSONS_PER_PROMPT


def test_accents_do_not_prevent_a_match(fake_redis):
    """Sale go khong dau lien tuc — bai hoc van phai khop."""
    _record("Chính sách thanh toán dự án thế nào?")

    assert reflection_memory.relevant_lessons("chinh sach thanh toan ra sao") != []


def test_rendered_lesson_carries_trigger_lesson_and_fix():
    rendered = Lesson(
        trigger="chinh sach thanh toan",
        lesson="Chua tra loi tien do",
        fix="tra loi du tung y",
        failure_mode="incomplete-answer",
    ).render()

    assert "chinh sach thanh toan" in rendered
    assert "Chua tra loi tien do" in rendered
    assert "tra loi du tung y" in rendered


def test_no_lessons_render_as_an_empty_string():
    assert reflection_memory.format_lessons([]) == ""


def test_redis_down_yields_no_lessons(broken_redis):
    assert reflection_memory.load_lessons() == []
    assert reflection_memory.relevant_lessons("Chinh sach thanh toan the nao?") == []


def test_recording_survives_a_redis_outage(broken_redis):
    """Ghi that bai chi mat bai hoc, khong duoc lam hong cau tra loi dang phuc vu."""
    _record("Chinh sach thanh toan the nao?")


def test_corrupt_value_is_ignored(fake_redis):
    fake_redis.store["reflection:lessons"] = "{not json"

    assert reflection_memory.load_lessons() == []


def test_entries_missing_required_fields_are_skipped(fake_redis):
    fake_redis.store["reflection:lessons"] = '[{"trigger": "", "lesson": "x"}, {"trigger": "y", "lesson": "z"}]'

    assert [lesson.trigger for lesson in reflection_memory.load_lessons()] == ["y"]


def test_forget_all_clears_everything(fake_redis):
    _record("Chinh sach thanh toan the nao?")

    reflection_memory.forget_all()

    assert reflection_memory.load_lessons() == []


def test_sale_session_scopes_are_isolated_and_cleared_independently(fake_redis):
    customer_a = reflection_memory.sale_session_scope(101)
    customer_b = reflection_memory.sale_session_scope(102)

    reflection_memory.record_lesson(
        query="Chinh sach thanh toan the nao?",
        failure_mode="incomplete-answer",
        feedback="Chua neu dieu kien ap dung.",
        scope=customer_a,
    )

    assert len(reflection_memory.load_lessons(customer_a)) == 1
    assert reflection_memory.load_lessons(customer_b) == []
    assert reflection_memory.load_lessons() == []

    reflection_memory.record_lesson(
        query="Tien ich noi khu gom gi?",
        failure_mode="incomplete-answer",
        feedback="Chua neu du tien ich.",
        scope=customer_b,
    )
    reflection_memory.forget_all(customer_a)

    assert reflection_memory.load_lessons(customer_a) == []
    assert len(reflection_memory.load_lessons(customer_b)) == 1


def test_trailing_question_mark_does_not_swallow_the_last_word():
    """Cau hoi tieng Viet nao cung ket thuc bang '?', va tu cuoi thuong la ten du an.

    Loc bang `word.isalnum()` tung loai bo moi token dinh dau cau, nen "Palma?" bien mat
    hoan toan — trigger mat dung tu phan biet du an nay voi du an khac.
    """
    assert reflection_memory._tokenise("Gia can 2PN The Palma?") == ["gia", "can", "2pn", "the", "palma"]
    assert reflection_memory._tokenise("Bang gia the nao!") == ["bang", "gia", "the", "nao"]


def test_two_projects_keep_distinct_triggers(fake_redis):
    """Mat ten du an o trigger khien hai bai hoc khac nhau trong y het nhau."""
    _record("Gia can 2PN The Palma?", feedback="Bia gia Palma")
    _record("Gia can 2PN The Beverly?", feedback="Bia gia Beverly")

    triggers = {lesson.trigger for lesson in reflection_memory.load_lessons()}
    assert triggers == {"gia 2pn palma", "gia 2pn beverly"}


def test_the_right_project_lesson_ranks_first(fake_redis):
    _record("Gia can 2PN The Palma?", feedback="Bia gia Palma")
    _record("Gia can 2PN The Beverly?", feedback="Bia gia Beverly")

    top = reflection_memory.relevant_lessons("Gia can 2PN The Palma?")

    assert top[0].lesson == "Bia gia Palma"


def test_one_defect_labelled_two_ways_stays_one_lesson(fake_redis):
    """Du lieu that tung co 'gia 2pn con' luu hai lan — mot lan incomplete-answer, mot lan
    missing-evidence — cung mot cau chu "Chua tra loi ton kho". Voi
    MAX_LESSONS_PER_PROMPT = 2, hai dong do chiem ca hai slot de noi dung mot y.
    """
    _record("Gia can 2PN con khong?", mode="incomplete-answer", feedback="Chua tra loi ton kho")
    _record("Gia can 2PN con khong?", mode="missing-evidence", feedback="Chua tra loi ton kho")
    _record("Gia can 2PN con khong?", mode="incomplete-answer", feedback="Van chua tra loi ton kho")

    lessons = reflection_memory.load_lessons()

    assert len(lessons) == 1
    assert lessons[0].hits == 3
    assert lessons[0].failure_mode == "incomplete-answer"


def test_prompt_gets_one_line_not_two_copies(fake_redis):
    _record("Gia can 2PN con khong?", mode="incomplete-answer", feedback="Chua tra loi ton kho")
    _record("Gia can 2PN con khong?", mode="missing-evidence", feedback="Chua tra loi ton kho")

    rendered = reflection_memory.format_lessons(reflection_memory.relevant_lessons("Gia can 2PN con khong?"))

    assert rendered.count("Chua tra loi ton kho") == 1
