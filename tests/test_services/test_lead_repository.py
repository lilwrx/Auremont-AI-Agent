"""repositories.lead — the persistence layer between lead_scoring_service and the DB row."""

from backend.core.enums import LeadTier
from backend.models.lead import Lead
from backend.repositories.lead import update_lead_score
from backend.services.lead_scoring_service import LeadVerdict


def _verdict(*, signals: dict) -> LeadVerdict:
    return LeadVerdict(
        tier=LeadTier.WARM,
        score=50,
        rule_score=50,
        soft_score=None,
        urgency=None,
        purpose=None,
        confidence=None,
        signals=signals,
        detection_method="rule",
        reason="",
    )


def test_a_rules_only_rescore_keeps_the_previous_llm_reason(db_session):
    """`combine()` rebuilds `signals` from scratch every call, so without this the LLM's
    explanation would vanish the moment a turn goes by without a fresh LLM pass — even
    though nothing the customer said contradicted it."""
    lead = Lead(customer_id=1)
    db_session.add(lead)
    db_session.commit()

    with_reason = _verdict(
        signals={"flags": {}, "weights": {}, "llm_reason": "Khách nói cần chuyển nhà gấp trong tháng này."}
    )
    update_lead_score(db_session, lead, with_reason, turn_count=3, llm_scored=True)
    assert lead.signals["llm_reason"] == "Khách nói cần chuyển nhà gấp trong tháng này."

    rules_only = _verdict(signals={"flags": {"has_phone": True}, "weights": {"has_phone": 10}})
    update_lead_score(db_session, lead, rules_only, turn_count=4, llm_scored=False)

    assert lead.signals["llm_reason"] == "Khách nói cần chuyển nhà gấp trong tháng này."
    assert lead.signals["weights"] == {"has_phone": 10}


def test_a_fresh_llm_pass_replaces_the_old_reason_rather_than_keeping_both(db_session):
    lead = Lead(customer_id=2)
    db_session.add(lead)
    db_session.commit()

    update_lead_score(db_session, lead, _verdict(signals={"llm_reason": "Lý do cũ."}), turn_count=1, llm_scored=True)
    update_lead_score(db_session, lead, _verdict(signals={"llm_reason": "Lý do mới."}), turn_count=2, llm_scored=True)

    assert lead.signals["llm_reason"] == "Lý do mới."
