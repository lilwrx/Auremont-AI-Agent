from datetime import date

import pytest
from google.genai import errors as genai_errors
from pydantic import ValidationError

from backend.core.enums import DocumentCategory, LegalStatus
from backend.services import document_classification_service as classification_service
from backend.services.document_classification_service import (
    ConflictFact,
    DocumentClassification,
    DocumentClassificationError,
    DocumentClassificationQuotaError,
    SectionClassification,
)


def _classification(**overrides) -> DocumentClassification:
    values = {
        "category": DocumentCategory.SUBDIVISION_INFO,
        "document_summary": "Tổng quan phân khu The Beverly.",
        "legal_status": LegalStatus.UNKNOWN,
        "confidence": 0.94,
        "reason": "Tiêu đề và nội dung chính mô tả tổng quan phân khu.",
        "requires_admin_review": False,
    }
    values.update(overrides)
    return DocumentClassification(**values)


def test_classifier_uses_gemini_structured_output_as_the_authoritative_result(monkeypatch):
    expected = _classification(
        category=DocumentCategory.SALES_POLICY,
        subdivision_names=["The Beverly"],
        building_codes=["BE1"],
        unit_types=["1PN+", "2PN", "3PN"],
        effective_date=date(2026, 8, 1),
        expiry_date=date(2026, 8, 31),
    )
    call: dict = {}

    def fake_generate_json(prompt, schema, system_instruction=None, **generation_options):
        call.update(
            prompt=prompt,
            schema=schema,
            system_instruction=system_instruction,
            generation_options=generation_options,
        )
        return expected

    monkeypatch.setattr(classification_service, "generate_json", fake_generate_json)

    result = classification_service.classify_document(
        "CSBH_The_Beverly_T8_2026.pdf",
        "CHÍNH SÁCH BÁN HÀNG\nPhân khu: The Beverly\nTòa BE1",
    )

    assert result is expected
    assert call["schema"] is DocumentClassification
    assert "CSBH_The_Beverly_T8_2026.pdf" in call["prompt"]
    assert "CHÍNH SÁCH BÁN HÀNG" in call["prompt"]
    assert "KHÔNG ĐÁNG TIN CẬY" in call["system_instruction"]
    assert "subdivision_info" in call["system_instruction"]
    assert call["generation_options"] == {"temperature": 0.0}


def test_classifier_supplies_catalog_and_accepts_only_an_exact_project_id(monkeypatch):
    expected = _classification(project_id="the-beverly", subdivision_names=["The Beverly"])
    captured: dict = {}

    def fake_generate_json(prompt, _schema, **_kwargs):
        captured["prompt"] = prompt
        return expected

    monkeypatch.setattr(classification_service, "generate_json", fake_generate_json)

    result = classification_service.classify_document(
        "Beverly.pdf",
        "Tổng quan phân khu The Beverly",
        project_catalog=[
            {"id": "the-beverly", "name": "The Beverly - Vinhomes Ocean Park"},
            {"id": "the-zurich", "name": "The Zurich - Vinhomes Ocean Park"},
        ],
    )

    assert result.project_id == "the-beverly"
    assert '"id":"the-beverly"' in captured["prompt"]


def test_classifier_quarantines_an_invented_project_id(monkeypatch):
    expected = _classification(project_id="du-an-khong-ton-tai")
    monkeypatch.setattr(classification_service, "generate_json", lambda *_args, **_kwargs: expected)

    result = classification_service.classify_document(
        "du-an.pdf",
        "Nội dung tài liệu",
        project_catalog=[{"id": "the-beverly", "name": "The Beverly"}],
    )

    assert result.project_id is None
    assert result.requires_admin_review is True
    assert "không tồn tại" in result.reason


def test_classifier_discards_conflict_fact_without_verbatim_source_evidence(monkeypatch):
    expected = _classification(
        conflict_facts=[
            ConflictFact(
                fact_key="payment.deadline",
                claim="Thanh toan trong 45 ngay.",
                value="45",
                unit="day",
                polarity="affirmative",
                evidence="Thanh toan trong 45 ngay",
            )
        ]
    )
    monkeypatch.setattr(classification_service, "generate_json", lambda *_args, **_kwargs: expected)

    result = classification_service.classify_document(
        "payment.pdf",
        "Tai lieu chi ghi thanh toan trong 30 ngay.",
    )

    assert result.conflict_facts == []
    assert result.requires_admin_review is True
    assert "discarded" in result.reason


def test_response_schema_avoids_fields_rejected_by_gemini():
    schema = DocumentClassification.model_json_schema()

    assert "additionalProperties" not in schema
    assert "maxItems" not in schema


def test_classification_caps_conflict_facts_after_structured_decoding():
    result = _classification(
        conflict_facts=[
            ConflictFact(
                fact_key=f"payment.installment.{index}",
                claim=f"Thanh toan dot {index}.",
                value=str(index),
                polarity="affirmative",
                evidence=f"Thanh toan dot {index}",
            )
            for index in range(205)
        ]
    )

    assert len(result.conflict_facts) == 200


def test_classifier_has_no_local_keyword_override(monkeypatch):
    """Even an obvious filename uses the API result; there is no hidden rule fallback."""

    expected = _classification(
        category=DocumentCategory.OTHER,
        confidence=0.41,
        reason="Tài liệu không đủ nội dung để xác định mục đích chính.",
        requires_admin_review=True,
    )
    monkeypatch.setattr(classification_service, "generate_json", lambda *_args, **_kwargs: expected)

    result = classification_service.classify_document(
        "Bang_Gia_The_Zurich.pdf",
        "Một đoạn nội dung không đầy đủ.",
    )

    assert result.category == DocumentCategory.OTHER
    assert result.confidence == 0.41


def test_classifier_sends_the_full_parsed_content(monkeypatch):
    marker = "EVIDENCE_AFTER_OLD_12000_CHARACTER_LIMIT"
    raw_text = ("A" * 12_500) + marker
    captured: dict = {}

    def fake_generate_json(prompt, _schema, system_instruction=None, **_generation_options):
        captured["prompt"] = prompt
        captured["system_instruction"] = system_instruction
        return _classification()

    monkeypatch.setattr(classification_service, "generate_json", fake_generate_json)

    classification_service.classify_document("du-an.pdf", raw_text)

    assert marker in captured["prompt"]


def test_classifier_returns_complete_grounded_section_labels_for_mixed_document(monkeypatch):
    expected = _classification(
        category=DocumentCategory.SALES_POLICY,
        categories=[DocumentCategory.SALES_POLICY, DocumentCategory.PRICE_LIST],
        section_classifications=[
            SectionClassification(section_index=0, category=DocumentCategory.SALES_POLICY, confidence=0.96),
            SectionClassification(section_index=1, category=DocumentCategory.PRICE_LIST, confidence=0.93),
        ],
    )
    captured: dict = {}

    def fake_generate_json(prompt, _schema, **_kwargs):
        captured["prompt"] = prompt
        return expected

    monkeypatch.setattr(classification_service, "generate_json", fake_generate_json)

    result = classification_service.classify_document(
        "mixed.pdf",
        "Chinh sach chiet khau.\nBang gia can A-01.",
        content_units=[
            {"section_index": 0, "page": 1, "content_type": "prose", "content": "Chinh sach chiet khau."},
            {"section_index": 1, "page": 2, "content_type": "table", "content": "Bang gia can A-01."},
        ],
    )

    assert result.categories == [DocumentCategory.SALES_POLICY, DocumentCategory.PRICE_LIST]
    assert [item.category for item in result.section_classifications] == [
        DocumentCategory.SALES_POLICY,
        DocumentCategory.PRICE_LIST,
    ]
    assert result.section_classifications[1].page == 2
    assert result.section_classifications[1].content_type == "table"
    assert '"sections"' in captured["prompt"]


def test_classifier_falls_back_and_requires_review_when_a_section_label_is_missing(monkeypatch):
    expected = _classification(
        category=DocumentCategory.SALES_POLICY,
        section_classifications=[
            SectionClassification(section_index=0, category=DocumentCategory.SALES_POLICY, confidence=0.9),
        ],
    )
    monkeypatch.setattr(classification_service, "generate_json", lambda *_args, **_kwargs: expected)

    result = classification_service.classify_document(
        "mixed.pdf",
        "Chinh sach.\nBang gia.",
        content_units=[
            {"section_index": 0, "content": "Chinh sach."},
            {"section_index": 1, "content": "Bang gia."},
        ],
    )

    assert len(result.section_classifications) == 2
    assert result.section_classifications[1].category == DocumentCategory.SALES_POLICY
    assert result.requires_admin_review is True


def test_classification_model_normalizes_optional_strings_and_lists():
    result = _classification(
        subcategory="  Căn hộ   cao cấp ",
        subdivision_names=[" The Beverly ", "the beverly", "", "The Zurich"],
        building_codes=[" BE1 ", "be1"],
        unit_types=[" 2BR ", "2pn", "3 phòng ngủ"],
        applicable_area="   ",
        reason="  Có   tiêu đề rõ ràng.  ",
    )

    assert result.subcategory == "Căn hộ cao cấp"
    assert result.subdivision_names == ["The Beverly", "The Zurich"]
    assert result.building_codes == ["BE1"]
    assert result.unit_types == ["2PN", "3PN"]
    assert result.applicable_area is None
    assert result.reason == "Có tiêu đề rõ ràng."


def test_classifier_normalizes_and_deduplicates_grounded_conflict_facts():
    result = _classification(
        conflict_facts=[
            ConflictFact(
                fact_key=" Payment / First installment / Deadline ",
                claim="Thanh toan dot mot trong 30 ngay.",
                value="30",
                unit="day",
                scope="The Beverly",
                polarity="affirmative",
                evidence="Thanh toan dot mot trong vong 30 ngay",
            ),
            ConflictFact(
                fact_key="payment.first_installment.deadline",
                claim="Cach viet khac cua cung mot fact.",
                value="30",
                unit="day",
                scope="the beverly",
                polarity="affirmative",
                evidence="Hoan tat dot mot trong 30 ngay",
            ),
        ]
    )

    assert result.conflict_facts[0].fact_key == "payment.first.installment.deadline"
    assert len(result.conflict_facts) == 1


def test_invalid_llm_metadata_is_rejected_by_schema():
    with pytest.raises(ValidationError, match="less than or equal to 1"):
        _classification(confidence=1.2)

    with pytest.raises(ValidationError, match="expiry_date cannot be earlier"):
        _classification(
            effective_date=date(2026, 8, 31),
            expiry_date=date(2026, 8, 1),
        )

    with pytest.raises(ValidationError, match="unit_types"):
        _classification(unit_types=["2PNConstructor"])


def test_llm_review_decision_is_required_instead_of_defaulting_to_safe():
    values = _classification().model_dump()
    values.pop("requires_admin_review")

    with pytest.raises(ValidationError, match="requires_admin_review"):
        DocumentClassification.model_validate(values)


def test_empty_llm_response_fails_closed(monkeypatch):
    monkeypatch.setattr(classification_service, "generate_json", lambda *_args, **_kwargs: None)

    with pytest.raises(DocumentClassificationError, match="no document metadata"):
        classification_service.classify_document("du-an.pdf", "Nội dung tài liệu")


def test_provider_failure_is_wrapped_without_a_rule_fallback(monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(classification_service, "generate_json", fail)

    with pytest.raises(DocumentClassificationError, match="could not classify") as error:
        classification_service.classify_document("du-an.pdf", "Nội dung tài liệu")

    assert isinstance(error.value.__cause__, RuntimeError)


def test_quota_failure_has_a_distinct_safe_classification_error(monkeypatch):
    provider_error = genai_errors.ClientError(
        429,
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "quota failed for secret-key-value",
            }
        },
    )
    monkeypatch.setattr(
        classification_service,
        "generate_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(provider_error),
    )

    with pytest.raises(DocumentClassificationQuotaError) as error:
        classification_service.classify_document("du-an.pdf", "Nội dung tài liệu")

    assert "secret-key-value" not in str(error.value)
    assert error.value.__cause__ is provider_error


@pytest.mark.parametrize(
    ("filename", "raw_text", "message"),
    [
        ("", "Nội dung", "filename is empty"),
        ("du-an.pdf", "   ", "no text"),
    ],
)
def test_missing_classifier_input_is_rejected_before_the_api_call(
    monkeypatch,
    filename,
    raw_text,
    message,
):
    called = False

    def fake_generate(*_args, **_kwargs):
        nonlocal called
        called = True
        return _classification()

    monkeypatch.setattr(classification_service, "generate_json", fake_generate)

    with pytest.raises(DocumentClassificationError, match=message):
        classification_service.classify_document(filename, raw_text)

    assert called is False
