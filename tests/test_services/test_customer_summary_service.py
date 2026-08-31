import json

import pytest

from backend.core.enums import MessageSender, SessionChannel, UserRole
from backend.models.chat_session import ChatSession
from backend.models.user import User
from backend.repositories.message import create_message
from backend.schemas.customer_summary import (
    CustomerNeeds,
    CustomerSummaryMetadata,
    CustomerSummarySnapshot,
    SummaryEvidence,
)
from backend.services import customer_summary_service


def _customer_sessions(db):
    customer = User(
        username="summary-customer",
        email="summary-customer@example.com",
        hashed_password="x",
        role=UserRole.CUSTOMER,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)

    ai_session = ChatSession(customer_id=customer.id, channel=SessionChannel.AI)
    live_session = ChatSession(customer_id=customer.id, channel=SessionChannel.LIVE)
    db.add_all([ai_session, live_session])
    db.commit()
    db.refresh(ai_session)
    db.refresh(live_session)
    return customer, ai_session, live_session


def test_summary_schema_keeps_provider_contract_simple_and_enforces_bounds_after_decode():
    provider_schema = json.dumps(CustomerSummarySnapshot.model_json_schema())

    assert "maxItems" not in provider_schema

    metadata = CustomerSummaryMetadata(
        needs=CustomerNeeds(projects=[f"project-{index}" for index in range(15)]),
        objections=[f"objection-{index}" for index in range(25)],
        next_best_actions=[f"action-{index}" for index in range(15)],
        evidence=[
            SummaryEvidence(
                field=f"field-{index}",
                message_ids=list(range(15)),
                source_role="customer",
            )
            for index in range(55)
        ],
    )

    assert len(metadata.needs.projects) == 10
    assert len(metadata.objections) == 20
    assert len(metadata.next_best_actions) == 10
    assert len(metadata.evidence) == 50
    assert all(len(item.message_ids) == 10 for item in metadata.evidence)


def test_incremental_refresh_reuses_metadata_and_only_sends_new_messages(db_session, monkeypatch):
    customer, ai_session, live_session = _customer_sessions(db_session)
    first_customer_message = create_message(
        db_session,
        ai_session.id,
        sender=MessageSender.CUSTOMER,
        content="Ngân sách của tôi tối đa 4 tỷ, cần căn 2PN.",
    )
    create_message(
        db_session,
        live_session.id,
        sender=MessageSender.SALE,
        content="Em sẽ gửi bảng hàng phù hợp trong chiều nay.",
    )

    prompts: list[dict] = []

    def fake_generate(prompt, schema, system_instruction=None, temperature=None):
        assert schema is CustomerSummarySnapshot
        assert system_instruction
        assert temperature == 0.1
        payload = json.loads(prompt)
        prompts.append(payload)
        return CustomerSummarySnapshot(
            summary_text="Khách cần căn 2PN, ngân sách tối đa 4 tỷ.",
            metadata=CustomerSummaryMetadata(
                needs=CustomerNeeds(unit_types=["2PN"], budget_max=4_000_000_000),
                next_best_actions=["Gửi bảng hàng 2PN"],
                evidence=[
                    SummaryEvidence(
                        field="needs.budget_max",
                        message_ids=[first_customer_message.id, 999_999],
                        source_role="customer",
                    )
                ],
            ),
        )

    monkeypatch.setattr(customer_summary_service, "generate_json", fake_generate)

    first = customer_summary_service.refresh_summary(db_session, customer.id)
    assert first.from_cache is False
    assert first.newly_processed_message_count == 2
    assert len(prompts) == 1
    assert {message["channel"] for message in prompts[0]["new_messages"]} == {"ai", "live"}
    assert first.metadata.evidence[0].message_ids == [first_customer_message.id]

    cached = customer_summary_service.refresh_summary(db_session, customer.id)
    assert cached.from_cache is True
    assert cached.newly_processed_message_count == 0
    assert len(prompts) == 1, "A fresh checkpoint must not spend another LLM call"

    new_message = create_message(
        db_session,
        live_session.id,
        sender=MessageSender.CUSTOMER,
        content="Tôi muốn thêm hướng hồ.",
    )
    updated = customer_summary_service.refresh_summary(db_session, customer.id)

    assert updated.from_cache is False
    assert updated.newly_processed_message_count == 1
    assert len(prompts) == 2
    assert [item["message_id"] for item in prompts[1]["new_messages"]] == [new_message.id]
    assert prompts[1]["previous_snapshot"]["metadata"]["needs"]["budget_max"] == 4_000_000_000
    assert updated.last_processed_message_id == new_message.id


def test_failed_incremental_refresh_preserves_the_last_successful_checkpoint(db_session, monkeypatch):
    customer, ai_session, live_session = _customer_sessions(db_session)
    create_message(db_session, ai_session.id, sender=MessageSender.CUSTOMER, content="Tôi cần căn studio.")

    monkeypatch.setattr(
        customer_summary_service,
        "generate_json",
        lambda *_args, **_kwargs: CustomerSummarySnapshot(
            summary_text="Khách cần căn studio.",
            metadata=CustomerSummaryMetadata(needs=CustomerNeeds(unit_types=["Studio"])),
        ),
    )
    initial = customer_summary_service.refresh_summary(db_session, customer.id)
    initial_checkpoint = initial.last_processed_message_id

    create_message(db_session, live_session.id, sender=MessageSender.CUSTOMER, content="Ưu tiên tầng trung.")

    def fail_generation(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(customer_summary_service, "generate_json", fail_generation)
    with pytest.raises(customer_summary_service.CustomerSummaryGenerationError):
        customer_summary_service.refresh_summary(db_session, customer.id)

    saved = customer_summary_service.get_saved_summary(db_session, customer.id)
    assert saved is not None
    assert saved.last_processed_message_id == initial_checkpoint
    assert saved.summary_text == "Khách cần căn studio."
