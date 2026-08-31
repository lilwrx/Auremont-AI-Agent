from backend.core.enums import (
    DocumentCategory,
    DocumentReviewStatus,
    LegalStatus,
)
from backend.models.document import Document
from backend.models.document_relation import DocumentRelation


def test_document_supports_project_specific_metadata():
    document = Document(
        title="CSBH The Beverly T8-2026.pdf",
        project_id="ocean-park-3",
        category=DocumentCategory.SALES_POLICY,
        subdivision_names=["The Beverly"],
        building_codes=["BE1", "BE2"],
        unit_types=["1PN+", "2PN", "3PN"],
        applicable_period="08/2026",
        review_status=DocumentReviewStatus.PENDING,
    )

    assert document.category == "sales_policy"
    assert document.subdivision_names == ["The Beverly"]
    assert document.building_codes == ["BE1", "BE2"]
    assert document.review_status == "pending"


def test_legal_document_has_optional_legal_metadata():
    document = Document(
        title="Nghi-dinh-96-2024-ND-CP.pdf",
        category=DocumentCategory.LEGAL_DOCUMENT,
        legal_document_type="Nghị định",
        legal_document_number="96/2024/NĐ-CP",
        legal_status=LegalStatus.EFFECTIVE,
    )

    assert document.category == "legal_document"
    assert document.legal_document_number == "96/2024/NĐ-CP"
    assert document.legal_status == "effective"


def test_document_relation_links_new_and_old_documents():
    relation = DocumentRelation(
        source_document_id=20,
        target_document_id=10,
        relation_type="replaces",
        scope_note="Áp dụng cho phân khu The Beverly",
    )

    assert relation.source_document_id == 20
    assert relation.target_document_id == 10
    assert relation.relation_type == "replaces"
