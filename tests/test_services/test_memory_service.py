"""Long-term memory — what gets remembered, what must never be, and failing open.

Redis is faked with an in-memory dict: these tests are about the remembering rules,
not about redis-py. The one thing genuinely worth testing against a broken client is
that every entry point degrades quietly, so that has its own fixture below.
"""

import json

import pytest

from backend.services import memory_service


class _FakeRedis:
    """Minimal stand-in for the handful of Redis commands this service uses."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.set_calls = 0

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.set_calls += 1
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)


class _BrokenRedis:
    """Every call blows up — stands in for a Redis outage."""

    def get(self, key):
        raise ConnectionError("redis down")

    def set(self, key, value, ex=None):
        raise ConnectionError("redis down")

    def delete(self, key):
        raise ConnectionError("redis down")


@pytest.fixture
def fake_redis(monkeypatch):
    client = _FakeRedis()
    monkeypatch.setattr(memory_service, "get_redis_client", lambda: client)
    return client


@pytest.fixture
def broken_redis(monkeypatch):
    monkeypatch.setattr(memory_service, "get_redis_client", lambda: _BrokenRedis())


def test_unit_type_and_budget_are_extracted():
    profile = memory_service.extract_facts("Ngan sach 3,6 ty thi nen xem can 2PN nao?")

    assert profile.unit_types == ["2PN"]
    assert profile.budgets == ["3,6 ty"]


def test_price_question_is_not_stored_as_a_budget():
    """'Gia can 2PN 3,6 ty co dat khong?' hoi GIA CAN, khong phai tien cua khach."""
    profile = memory_service.extract_facts("Gia can 2PN 3,6 ty co dat khong?")

    assert profile.budgets == []
    assert profile.unit_types == ["2PN"]


def test_comparison_of_two_prices_stores_neither():
    """Cau so sanh hai can — chon nham con so nao cung sai hon la khong chon."""
    profile = memory_service.extract_facts("Tai sao can 5 ty lai dat hon can 3 ty?")

    assert profile.budgets == []


def test_budget_and_price_in_one_sentence_stores_neither():
    """Vua co ngan sach vua co gia can: mo ho, khong doan bua."""
    profile = memory_service.extract_facts("Ngan sach 3 ty thi can 5 ty co hop khong?")

    assert profile.budgets == []


def test_budget_phrasings_are_recognised():
    for question, expected in [
        ("Toi co ngan sach 3 ty", "3 ty"),
        ("Tam gia 4 ty co can nao khong?", "4 ty"),
        ("Toi muon mua can tam 2 ty", "2 ty"),
        ("Tai chinh cua toi khoang 800 trieu", "800 trieu"),
    ]:
        assert memory_service.extract_facts(question).budgets == [expected], question


def test_budget_range_is_remembered_as_one_value():
    profile = memory_service.extract_facts("Tài chính khoảng 3.5 - 4 tỷ")

    assert profile.budgets == ["3.5 - 4 tỷ"]


def test_spacing_variants_normalise_to_one_token():
    """'3 PN' va '3pn' phai la cung mot thu, khong tich thanh hai muc rieng."""
    spaced = memory_service.extract_facts("Con 3 PN thi sao?")
    tight = memory_service.extract_facts("con 3pn thi sao?")

    assert spaced.unit_types == tight.unit_types == ["3PN"]


def test_project_is_remembered_when_the_session_has_one():
    profile = memory_service.extract_facts("Gia bao nhieu?", project_id="ocean-park-3")

    assert profile.projects == ["ocean-park-3"]


def test_a_question_with_nothing_durable_yields_an_empty_profile():
    assert memory_service.extract_facts("Chao ban, cho hoi chut").is_empty()
    assert memory_service.extract_facts("   ").is_empty()


def test_remember_then_load(fake_redis):
    key = memory_service.customer_key(7)
    memory_service.remember(key, "Ngan sach 3,6 ty muon xem can 2PN", project_id="ocean-park-3")

    profile = memory_service.load_profile(key)
    assert profile.unit_types == ["2PN"]
    assert profile.budgets == ["3,6 ty"]
    assert profile.projects == ["ocean-park-3"]


def test_remember_many_backfills_oldest_to_newest_with_one_redis_write(fake_redis):
    key = memory_service.sale_session_key(151)

    memory_service.remember_many(
        key,
        ["Khách muốn căn 2PN", "Khách chuyển sang căn 3PN", "Tài chính khoảng 3.5 - 4 tỷ"],
    )

    profile = memory_service.load_profile(key)
    assert profile.unit_types == ["3PN", "2PN"]
    assert profile.budgets == ["3.5 - 4 tỷ"]
    assert fake_redis.set_calls == 1


def test_newest_interest_is_read_first(fake_redis):
    """Khach chuyen tu 2PN sang 3PN — 3PN phai dung truoc."""
    key = memory_service.customer_key(7)
    memory_service.remember(key, "Gia can 2PN?")
    memory_service.remember(key, "Con 3PN thi sao?")

    assert memory_service.load_profile(key).unit_types == ["3PN", "2PN"]


def test_repeating_the_same_interest_does_not_duplicate_it(fake_redis):
    key = memory_service.customer_key(7)
    memory_service.remember(key, "Gia can 2PN?")
    memory_service.remember(key, "Can 2PN con khong?")

    assert memory_service.load_profile(key).unit_types == ["2PN"]


def test_profile_is_capped(fake_redis):
    """Ho so dai thi khong con la goi y — no lan at chinh cau hoi hien tai."""
    key = memory_service.customer_key(7)
    for size in range(1, 8):
        memory_service.remember(key, f"Gia can {size}PN?")

    assert len(memory_service.load_profile(key).unit_types) == memory_service.MAX_ITEMS_PER_FIELD


def test_customers_and_sales_use_separate_namespaces(fake_redis):
    """Ho so cua khach va cua sale khong duoc dinh vao nhau."""
    memory_service.remember(memory_service.customer_key(1), "Gia can 2PN?")
    memory_service.remember(memory_service.sale_key(1), "Gia can 3PN?")

    assert memory_service.load_profile(memory_service.customer_key(1)).unit_types == ["2PN"]
    assert memory_service.load_profile(memory_service.sale_key(1)).unit_types == ["3PN"]


def test_one_sale_never_reads_another_sales_profile(fake_redis):
    memory_service.remember(memory_service.sale_key(1), "Gia can 2PN?")

    assert memory_service.load_profile(memory_service.sale_key(2)).is_empty()


def test_forget_clears_the_profile(fake_redis):
    key = memory_service.customer_key(7)
    memory_service.remember(key, "Gia can 2PN?")

    memory_service.forget(key)

    assert memory_service.load_profile(key).is_empty()


def test_load_returns_an_empty_profile_when_redis_is_down(broken_redis):
    assert memory_service.load_profile(memory_service.customer_key(7)).is_empty()


def test_remember_never_raises_when_redis_is_down(broken_redis):
    """Ghi ho so that bai khong duoc lam hong cau tra loi dang phuc vu."""
    memory_service.remember(memory_service.customer_key(7), "Gia can 2PN?")


def test_forget_never_raises_when_redis_is_down(broken_redis):
    memory_service.forget(memory_service.customer_key(7))


def test_memory_disabled_yields_an_empty_profile(monkeypatch):
    """redis_url de trong = tat han tinh nang, khong phai loi."""
    monkeypatch.setattr(memory_service, "get_redis_client", lambda: None)

    memory_service.remember(memory_service.customer_key(7), "Gia can 2PN?")
    assert memory_service.load_profile(memory_service.customer_key(7)).is_empty()


def test_corrupt_json_is_ignored(fake_redis):
    key = memory_service.customer_key(7)
    fake_redis.store[key] = "{not json at all"

    assert memory_service.load_profile(key).is_empty()


def test_unexpected_shape_is_ignored(fake_redis):
    """Gia tri bi sua tay trong redis-cli khong duoc lam sap pipeline."""
    key = memory_service.customer_key(7)
    fake_redis.store[key] = json.dumps({"unit_types": "2PN", "budgets": None})

    assert memory_service.load_profile(key).is_empty()


def test_empty_profile_renders_as_nothing():
    """Chuoi rong => prompt khong doi mot ky tu nao."""
    assert memory_service.format_profile(memory_service.UserProfile()) == ""


def test_rendered_profile_lists_what_is_known():
    profile = memory_service.UserProfile(unit_types=["2PN"], budgets=["3,6 ty"])

    rendered = memory_service.format_profile(profile)

    assert "2PN" in rendered
    assert "3,6 ty" in rendered


def test_recall_answer_selects_only_the_requested_profile_dimension():
    profile = memory_service.UserProfile(
        unit_types=["2PN+1"],
        budgets=["3.5 - 4 tỷ"],
        projects=["the-pavilion", "the-sapphire"],
    )

    answer = memory_service.format_recall_answer("Khách đang quan tâm phân khu nào?", profile)

    assert "The Pavilion" in answer
    assert "The Sapphire" in answer
    assert "2PN+1" not in answer
    assert "3.5 - 4 tỷ" not in answer
