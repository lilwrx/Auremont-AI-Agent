"""Correcting a document's category — the controlled path the review endpoint refuses.

The category is not a label: `chunk_sections` splits legal documents by Article/Clause and
price lists by table rows, conflict comparison branches on it, and retrieval filters on it
in the Qdrant payload. So changing it means re-chunking from the original file and scanning
for conflicts again, with the document quarantined throughout.

These tests cover the ordering, because that is what makes a partial failure safe: a
document that stops halfway must not still be answering from chunks built for the category
it no longer has.
"""

import pytest

from backend.core.enums import DocumentCategory, DocumentReviewStatus, DocumentStatus
from backend.models.document import Document
from backend.models.project import Project
from backend.services import ingestion_service, vector_store_service
from backend.services.ingestion_service import (
    ConflictScanOutcome,
    DocumentIngestionError,
    reclassify_document,
)


@pytest.fixture
def document(db_session):
    row = Document(
        title="bang-gia.pdf",
        file_path="documents/1/bang-gia.pdf",
        status=DocumentStatus.COMPLETED,
        review_status=DocumentReviewStatus.APPROVED,
        category=DocumentCategory.OTHER,
        visibility="internal",
        is_current=True,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


@pytest.fixture
def recorder(monkeypatch):
    """Replaces everything that leaves the process, recording the order it was called in."""
    events: list[tuple] = []

    monkeypatch.setattr(ingestion_service, "_read_original_file", lambda _key: b"file-bytes")
    monkeypatch.setattr(ingestion_service, "parse_document", lambda _title, _bytes: ["section"])
    monkeypatch.setattr(
        ingestion_service,
        "chunk_sections_by_classification",
        lambda sections, primary_category, section_classifications=None: (
            events.append(("chunk", primary_category)) or ["chunk"]
        ),
    )
    monkeypatch.setattr(
        ingestion_service,
        "delete_document_vectors",
        lambda document_id: events.append(("delete_vectors", document_id)),
    )
    monkeypatch.setattr(
        ingestion_service,
        "_embed_and_index",
        lambda doc, chunks, is_current=None: events.append(("index", is_current)),
    )
    # Patch both the imported and source bindings.
    record_sync = lambda document_id, **kwargs: events.append(  # noqa: E731
        ("sync", kwargs["category"], kwargs["is_current"])
    )
    monkeypatch.setattr(ingestion_service, "update_document_vector_metadata", record_sync)
    monkeypatch.setattr(vector_store_service, "update_document_vector_metadata", record_sync)
    monkeypatch.setattr(
        ingestion_service,
        "scan_conflicts_for",
        lambda db, doc, raw_text=None, commit=True: events.append(("scan", doc.category)) or ConflictScanOutcome(),
    )
    return events


class TestHappyPath:
    def test_the_category_is_corrected_and_the_document_answers_again(self, db_session, document, recorder):
        result = reclassify_document(
            db_session, document_id=document.id, category=DocumentCategory.PRICE_LIST, reviewed_by=1
        )

        assert result.category == DocumentCategory.PRICE_LIST
        assert result.review_status == DocumentReviewStatus.APPROVED
        assert result.is_current is True

    def test_it_quarantines_before_touching_anything_else(self, db_session, document, recorder):
        """A document answering from stale chunks mid-change is the failure this ordering
        exists to prevent."""
        reclassify_document(db_session, document_id=document.id, category=DocumentCategory.PRICE_LIST, reviewed_by=1)

        assert recorder[0] == ("sync", DocumentCategory.OTHER, False)

    def test_the_new_chunks_are_built_for_the_new_category(self, db_session, document, recorder):
        """The whole reason a plain UPDATE is refused: price-list chunking differs."""
        reclassify_document(db_session, document_id=document.id, category=DocumentCategory.PRICE_LIST, reviewed_by=1)

        assert ("chunk", DocumentCategory.PRICE_LIST) in recorder

    def test_old_vectors_go_before_the_new_ones_arrive(self, db_session, document, recorder):
        reclassify_document(db_session, document_id=document.id, category=DocumentCategory.PRICE_LIST, reviewed_by=1)
        kinds = [event[0] for event in recorder]

        assert kinds.index("delete_vectors") < kinds.index("index")

    def test_new_vectors_arrive_quarantined_and_are_published_only_after_the_scan(self, db_session, document, recorder):
        reclassify_document(db_session, document_id=document.id, category=DocumentCategory.PRICE_LIST, reviewed_by=1)
        kinds = [event[0] for event in recorder]

        assert ("index", False) in recorder
        assert kinds.index("index") < kinds.index("scan") < len(kinds) - 1
        assert recorder[-1] == ("sync", DocumentCategory.PRICE_LIST, True)

    def test_first_pending_approval_builds_vectors_even_when_metadata_is_unchanged(
        self, db_session, document, recorder
    ):
        document.category = DocumentCategory.PRICE_LIST
        document.review_status = DocumentReviewStatus.PENDING
        document.is_current = False
        db_session.commit()

        result = reclassify_document(
            db_session,
            document_id=document.id,
            category=DocumentCategory.PRICE_LIST,
            reviewed_by=1,
        )

        assert result.review_status == DocumentReviewStatus.APPROVED
        assert result.is_current is True
        assert ("chunk", DocumentCategory.PRICE_LIST) in recorder
        assert ("index", False) in recorder
        assert recorder[-1] == ("sync", DocumentCategory.PRICE_LIST, True)
        assert not any(event[0] == "sync" for event in recorder[:-1])

    def test_conflicts_are_rescanned_under_the_new_category(self, db_session, document, recorder):
        """The comparison set changed, so the previous scan's verdict no longer applies."""
        reclassify_document(db_session, document_id=document.id, category=DocumentCategory.PRICE_LIST, reviewed_by=1)

        assert ("scan", DocumentCategory.PRICE_LIST) in recorder

    def test_scope_correction_is_quarantined_and_rescanned_without_reembedding(self, db_session, document, recorder):
        result = reclassify_document(
            db_session,
            document_id=document.id,
            category=DocumentCategory.OTHER,
            reviewed_by=1,
            metadata_updates={
                "subdivision_names": ["The Beverly"],
                "building_codes": ["BE1"],
                "unit_types": ["2PN"],
            },
        )

        assert result.subdivision_names == ["The Beverly"]
        assert result.building_codes == ["BE1"]
        assert result.unit_types == ["2PN"]
        assert result.review_status == DocumentReviewStatus.APPROVED
        assert recorder[0] == ("sync", DocumentCategory.OTHER, False)
        assert ("scan", DocumentCategory.OTHER) in recorder
        assert not any(event[0] in {"chunk", "delete_vectors", "index"} for event in recorder)
        assert recorder[-1] == ("sync", DocumentCategory.OTHER, False)

    def test_project_correction_reindexes_vectors_with_the_catalogue_project(self, db_session, document, recorder):
        db_session.add(Project(id="the-beverly", name="The Beverly"))
        db_session.commit()

        result = reclassify_document(
            db_session,
            document_id=document.id,
            category=DocumentCategory.OTHER,
            reviewed_by=1,
            metadata_updates={"project_id": "the-beverly"},
        )

        assert result.project_id == "the-beverly"
        assert ("chunk", DocumentCategory.OTHER) in recorder
        assert ("index", False) in recorder
        assert ("scan", DocumentCategory.OTHER) in recorder


class TestConflictOutcome:
    def test_a_conflict_found_after_the_change_keeps_it_quarantined(self, db_session, document, recorder, monkeypatch):
        monkeypatch.setattr(
            ingestion_service,
            "scan_conflicts_for",
            lambda db, doc, raw_text=None, commit=True: ConflictScanOutcome(conflict_ids=(7,)),
        )

        result = reclassify_document(
            db_session, document_id=document.id, category=DocumentCategory.PRICE_LIST, reviewed_by=1
        )

        assert result.is_current is False


class TestFailuresStayQuarantined:
    def test_a_parse_failure_rolls_back_metadata_and_can_be_retried(self, db_session, document, recorder, monkeypatch):
        def _boom(_title, _bytes):
            raise RuntimeError("corrupt file")

        monkeypatch.setattr(ingestion_service, "parse_document", _boom)

        with pytest.raises(DocumentIngestionError):
            reclassify_document(
                db_session, document_id=document.id, category=DocumentCategory.PRICE_LIST, reviewed_by=1
            )

        db_session.expire_all()
        stored = db_session.get(Document, document.id)
        assert stored.is_current is False
        assert stored.category == DocumentCategory.OTHER

        monkeypatch.setattr(ingestion_service, "parse_document", lambda _title, _bytes: ["section"])
        retried = reclassify_document(
            db_session,
            document_id=document.id,
            category=DocumentCategory.PRICE_LIST,
            reviewed_by=1,
        )

        assert retried.category == DocumentCategory.PRICE_LIST
        assert retried.is_current is True

    def test_producing_no_chunks_is_a_failure_not_an_empty_document(self, db_session, document, recorder, monkeypatch):
        monkeypatch.setattr(
            ingestion_service,
            "chunk_sections_by_classification",
            lambda sections, primary_category, section_classifications=None: [],
        )

        with pytest.raises(DocumentIngestionError):
            reclassify_document(
                db_session, document_id=document.id, category=DocumentCategory.PRICE_LIST, reviewed_by=1
            )


class TestRejectedRequests:
    def test_the_same_category_is_refused(self, db_session, document, recorder):
        with pytest.raises(DocumentIngestionError, match="already categorised"):
            reclassify_document(db_session, document_id=document.id, category=DocumentCategory.OTHER, reviewed_by=1)

    def test_unknown_project_is_rejected_before_the_document_is_quarantined(self, db_session, document, recorder):
        with pytest.raises(DocumentIngestionError, match="does not exist in the project catalogue"):
            reclassify_document(
                db_session,
                document_id=document.id,
                category=DocumentCategory.OTHER,
                reviewed_by=1,
                metadata_updates={"project_id": "invented-project"},
            )

        db_session.expire_all()
        assert db_session.get(Document, document.id).is_current is True
        assert recorder == []

    def test_pending_other_document_requires_a_supported_category(self, db_session, document, recorder):
        document.review_status = DocumentReviewStatus.PENDING
        document.is_current = False
        db_session.commit()

        with pytest.raises(DocumentIngestionError, match="cannot be approved"):
            reclassify_document(
                db_session,
                document_id=document.id,
                category=DocumentCategory.OTHER,
                reviewed_by=1,
            )

        assert recorder == []

    def test_a_document_still_processing_is_refused(self, db_session, document, recorder):
        document.status = DocumentStatus.PROCESSING
        db_session.commit()

        with pytest.raises(DocumentIngestionError, match="not ready"):
            reclassify_document(
                db_session, document_id=document.id, category=DocumentCategory.PRICE_LIST, reviewed_by=1
            )

    def test_a_document_with_no_stored_original_is_refused(self, db_session, document, recorder):
        """Without the source file there is nothing to re-chunk from."""
        document.file_path = None
        db_session.commit()

        with pytest.raises(DocumentIngestionError, match="no stored original"):
            reclassify_document(
                db_session, document_id=document.id, category=DocumentCategory.PRICE_LIST, reviewed_by=1
            )

    def test_an_unknown_document_is_refused(self, db_session, recorder):
        with pytest.raises(DocumentIngestionError, match="does not exist"):
            reclassify_document(db_session, document_id=999999, category=DocumentCategory.PRICE_LIST, reviewed_by=1)
