import json
from types import SimpleNamespace

from backend.core.enums import (
    DocumentCategory,
    DocumentReviewStatus,
    DocumentStatus,
    DocumentVisibility,
    LegalStatus,
)
from backend.services.document_classification_service import DocumentClassification
from backend.services.metadata_audit_service import (
    ContentProbe,
    VectorDocumentSnapshot,
    VectorScan,
    build_metadata_audit_report,
    expected_vector_payload,
    quarantine_orphan_vectors,
    scan_vector_collection,
    synchronize_vector_payloads,
)
from scripts import audit_document_metadata as audit_cli


def _document(document_id: int, **overrides):
    values = {
        "id": document_id,
        "title": f"document-{document_id}.pdf",
        "file_path": f"documents/{document_id}/source.pdf",
        "status": DocumentStatus.COMPLETED,
        "project_id": "project-a",
        "visibility": DocumentVisibility.INTERNAL,
        "category": DocumentCategory.PRICE_LIST,
        "categories": [DocumentCategory.PRICE_LIST.value],
        "subcategory": None,
        "subdivision_names": None,
        "building_codes": None,
        "unit_types": None,
        "applicable_area": None,
        "version_label": None,
        "issued_date": None,
        "effective_date": None,
        "expiry_date": None,
        "applicable_period": None,
        "legal_document_type": None,
        "legal_document_number": None,
        "legal_issuer": None,
        "legal_domain": None,
        "review_status": DocumentReviewStatus.APPROVED,
        "legal_status": LegalStatus.UNKNOWN,
        "is_current": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _vector_snapshot(document, *, payload_overrides=None, content="Can A-01 gia 3.5 ty"):
    payload = {
        **expected_vector_payload(document),
        "category": document.category.value if hasattr(document.category, "value") else document.category,
        "chunk_index": 0,
        "content": content,
    }
    payload.update(payload_overrides or {})
    snapshot = VectorDocumentSnapshot(document_id=document.id)
    snapshot.add_point(point_id=f"point-{document.id}", payload=payload)
    return snapshot


class _PagedQdrant:
    def __init__(self):
        self.scroll_calls = []
        self.set_payload_calls = []

    def collection_exists(self, _name):
        return True

    def scroll(self, **kwargs):
        self.scroll_calls.append(kwargs)
        if kwargs["offset"] is None:
            return [SimpleNamespace(id="p1", payload={"document_id": 7, "chunk_index": 0, "content": "mot"})], "p1"
        return [SimpleNamespace(id="p2", payload={"document_id": "8", "content": "hai"})], None

    def set_payload(self, **kwargs):
        self.set_payload_calls.append(kwargs)


def test_vector_scan_paginates_without_loading_vectors():
    qdrant = _PagedQdrant()

    scan = scan_vector_collection(qdrant, "documents", batch_size=1)

    assert scan.collection_exists is True
    assert scan.point_count == 2
    assert scan.documents[7].point_count == 1
    assert scan.invalid_document_id_points == ("p2",)
    assert len(qdrant.scroll_calls) == 2
    assert all(call["with_vectors"] is False for call in qdrant.scroll_calls)


def test_report_finds_orphans_missing_vectors_and_payload_drift():
    first = _document(1)
    missing = _document(2)
    drifted = _vector_snapshot(first, payload_overrides={"category": "other", "visibility": "public"})
    orphan_document = _document(99)
    orphan = _vector_snapshot(orphan_document)
    scan = VectorScan(
        collection_exists=True,
        point_count=2,
        documents={1: drifted, 99: orphan},
    )

    report = build_metadata_audit_report([first, missing], scan)

    codes = {finding.code for finding in report.findings}
    assert "ORPHAN_VECTOR_DOCUMENTS" in codes
    assert "COMPLETED_DOCUMENTS_WITHOUT_VECTORS" in codes
    assert "QDRANT_PAYLOAD_DRIFT" in codes
    assert "QDRANT_CATEGORY_DRIFT_REQUIRES_REINDEX" in codes
    assert report.payload_sync_document_ids == (1,)
    assert report.category_reindex_document_ids == (1,)


def test_category_only_drift_is_never_a_payload_sync_candidate():
    document = _document(1)
    snapshot = _vector_snapshot(document, payload_overrides={"category": "other"})

    report = build_metadata_audit_report(
        [document],
        VectorScan(collection_exists=True, point_count=1, documents={1: snapshot}),
    )

    assert report.payload_sync_document_ids == ()
    assert report.category_reindex_document_ids == (1,)
    assert "category" not in expected_vector_payload(document)


def test_secondary_chunk_category_is_valid_for_a_mixed_document():
    document = _document(
        1,
        category=DocumentCategory.SALES_POLICY,
        categories=[DocumentCategory.SALES_POLICY.value, DocumentCategory.PRICE_LIST.value],
    )
    snapshot = _vector_snapshot(document, payload_overrides={"category": "price_list"})

    report = build_metadata_audit_report(
        [document],
        VectorScan(collection_exists=True, point_count=1, documents={1: snapshot}),
    )

    assert report.category_reindex_document_ids == ()


def test_missing_nullable_project_payload_matches_mysql_null():
    document = _document(1, project_id=None)
    payload = {
        **expected_vector_payload(document),
        "category": DocumentCategory.PRICE_LIST.value,
        "chunk_index": 0,
        "content": "Bang gia ap dung chung.",
    }
    payload.pop("project_id")
    snapshot = VectorDocumentSnapshot(document_id=document.id)
    snapshot.add_point(point_id="point-1", payload=payload)

    report = build_metadata_audit_report(
        [document],
        VectorScan(collection_exists=True, point_count=1, documents={1: snapshot}),
    )

    assert report.payload_sync_document_ids == ()


def test_nonterminal_or_retired_documents_are_never_repaired_to_current_true():
    processing = _document(1, status=DocumentStatus.PROCESSING, is_current=True)
    retired = _document(2, legal_status=LegalStatus.REPEALED, is_current=True)
    future = _document(3, legal_status=LegalStatus.NOT_YET_EFFECTIVE, is_current=True)
    scan = VectorScan(
        collection_exists=True,
        point_count=3,
        documents={
            1: _vector_snapshot(processing, payload_overrides={"is_current": True}),
            2: _vector_snapshot(retired, payload_overrides={"is_current": True}),
            3: _vector_snapshot(future, payload_overrides={"is_current": True}),
        },
    )

    report = build_metadata_audit_report([processing, retired, future], scan)

    finding = next(item for item in report.findings if item.code == "MYSQL_UNSAFE_CURRENT_STATE")
    assert finding.severity == "error"
    assert finding.document_ids == (1, 2, 3)
    assert report.payload_sync_document_ids == (1, 2, 3)
    assert expected_vector_payload(processing)["is_current"] is False
    assert expected_vector_payload(retired)["is_current"] is False
    assert expected_vector_payload(future)["is_current"] is False


def test_open_conflict_with_two_approved_current_documents_is_an_error():
    first = _document(1)
    second = _document(2)
    conflict = SimpleNamespace(document_id_a=1, document_id_b=2)

    report = build_metadata_audit_report(
        [first, second],
        VectorScan(collection_exists=True, point_count=0, documents={}),
        open_conflicts=[conflict],
    )

    finding = next(item for item in report.findings if item.code == "OPEN_CONFLICT_BOTH_DOCUMENTS_RETRIEVABLE")
    assert finding.severity == "error"
    assert finding.details["pairs"] == [[1, 2]]


def test_payload_sync_never_activates_an_endpoint_of_unsafe_open_conflict():
    first = _document(1)
    second = _document(2)
    conflict = SimpleNamespace(document_id_a=1, document_id_b=2)
    scan = VectorScan(
        collection_exists=True,
        point_count=2,
        documents={
            1: _vector_snapshot(first),
            2: _vector_snapshot(second, payload_overrides={"is_current": False}),
        },
    )

    report = build_metadata_audit_report(
        [first, second],
        scan,
        open_conflicts=[conflict],
    )

    assert report.payload_sync_document_ids == ()
    assert any(finding.code == "OPEN_CONFLICT_BOTH_DOCUMENTS_RETRIEVABLE" for finding in report.findings)


def test_report_detects_exact_source_duplicates_without_repeating_parsed_duplicate():
    documents = [_document(1), _document(2)]
    classification = DocumentClassification(
        category=DocumentCategory.PRICE_LIST,
        legal_status=LegalStatus.UNKNOWN,
        requires_admin_review=False,
    )
    probes = {
        1: ContentProbe(
            document_id=1,
            source_sha256="same-file",
            parsed_text_sha256="same-text",
            classification=classification,
        ),
        2: ContentProbe(
            document_id=2,
            source_sha256="same-file",
            parsed_text_sha256="same-text",
            classification=classification,
        ),
    }
    scan = VectorScan(collection_exists=True, point_count=0, documents={})

    report = build_metadata_audit_report(documents, scan, content_probes=probes)

    duplicate_codes = [finding.code for finding in report.findings if finding.code.startswith("DUPLICATE_")]
    assert duplicate_codes == ["DUPLICATE_SOURCE_FILES"]


def test_index_fingerprint_still_finds_duplicate_when_only_one_source_probe_succeeds():
    documents = [_document(1), _document(2)]
    scan = VectorScan(
        collection_exists=True,
        point_count=2,
        documents={
            1: _vector_snapshot(documents[0], content="same indexed text"),
            2: _vector_snapshot(documents[1], content="same indexed text"),
        },
    )
    probes = {
        1: ContentProbe(document_id=1, source_sha256="one", parsed_text_sha256="one-text"),
        2: ContentProbe(document_id=2, error="source unavailable"),
    }

    report = build_metadata_audit_report(documents, scan, content_probes=probes)

    indexed = next(finding for finding in report.findings if finding.code == "DUPLICATE_INDEXED_CONTENT")
    assert indexed.document_ids == (1, 2)
    unavailable = next(finding for finding in report.findings if finding.code == "SOURCE_CONTENT_UNAVAILABLE")
    assert unavailable.severity == "warning"


def test_report_marks_reclassification_as_suggestion_only():
    document = _document(1, category=DocumentCategory.SALES_POLICY)
    probe = ContentProbe(
        document_id=1,
        source_sha256="source",
        parsed_text_sha256="text",
        classification=DocumentClassification(
            category=DocumentCategory.PRICE_LIST,
            confidence=0.93,
            reason="filename: bang gia",
            requires_admin_review=False,
        ),
    )
    scan = VectorScan(collection_exists=True, point_count=1, documents={1: _vector_snapshot(document)})

    report = build_metadata_audit_report([document], scan, content_probes={1: probe})

    finding = next(item for item in report.findings if item.code == "CLASSIFIER_CATEGORY_SUGGESTION_DRIFT")
    assert finding.details["stored"] == "sales_policy"
    assert finding.details["suggested"] == "price_list"
    assert report.payload_sync_document_ids == ()


def test_payload_sync_is_dry_run_by_default_and_apply_is_scoped():
    qdrant = _PagedQdrant()
    document = _document(42, project_id=None, title="bang-gia.pdf")

    planned = synchronize_vector_payloads(qdrant, "documents", [document], [42])

    assert planned == (42,)
    assert qdrant.set_payload_calls == []

    repaired = synchronize_vector_payloads(qdrant, "documents", [document], [42], apply=True)

    assert repaired == (42,)
    assert len(qdrant.set_payload_calls) == 1
    call = qdrant.set_payload_calls[0]
    assert call["payload"] == expected_vector_payload(document)
    assert "category" not in call["payload"]
    assert call["wait"] is True
    condition = call["points"].filter.must[0]
    assert condition.key == "document_id"
    assert condition.match.value == 42


def test_orphan_quarantine_is_reversible_payload_update_and_never_deletes():
    qdrant = _PagedQdrant()

    planned = quarantine_orphan_vectors(
        qdrant,
        "documents",
        mysql_document_ids=[1, 2],
        vector_document_ids=[1, 2, 30, 31],
        selected_document_ids=[30],
    )

    assert planned == (30,)
    assert qdrant.set_payload_calls == []

    quarantined = quarantine_orphan_vectors(
        qdrant,
        "documents",
        mysql_document_ids=[1, 2],
        vector_document_ids=[1, 2, 30, 31],
        selected_document_ids=[30],
        apply=True,
    )

    assert quarantined == (30,)
    assert len(qdrant.set_payload_calls) == 1
    call = qdrant.set_payload_calls[0]
    assert call["payload"] == {
        "review_status": "rejected",
        "is_current": False,
        "quarantine_reason": "missing_mysql_document",
    }
    assert call["points"].filter.must[0].match.value == 30


def test_already_quarantined_orphan_is_informational_not_actionable():
    orphan = _vector_snapshot(
        _document(30),
        payload_overrides={"review_status": "rejected", "is_current": False},
    )

    report = build_metadata_audit_report(
        [],
        VectorScan(collection_exists=True, point_count=1, documents={30: orphan}),
    )

    assert report.orphan_vector_document_ids == ()
    assert report.quarantined_orphan_vector_document_ids == (30,)
    finding = next(item for item in report.findings if item.code == "QUARANTINED_ORPHAN_VECTOR_DOCUMENTS")
    assert finding.severity == "info"


class _MutableQdrant:
    def __init__(self, document):
        self.payload = {
            **expected_vector_payload(document),
            "category": document.category.value,
            "visibility": "public",
            "chunk_index": 0,
            "content": "indexed text",
        }
        self.scroll_calls = 0
        self.set_payload_calls = []

    def collection_exists(self, _name):
        return True

    def scroll(self, **_kwargs):
        self.scroll_calls += 1
        return [SimpleNamespace(id="point-1", payload=dict(self.payload))], None

    def set_payload(self, **kwargs):
        self.set_payload_calls.append(kwargs)
        self.payload.update(kwargs["payload"])


class _DisappearingQdrant(_MutableQdrant):
    def __init__(self, document):
        super().__init__(document)
        self.deleted = False

    def scroll(self, **_kwargs):
        self.scroll_calls += 1
        if self.deleted:
            return [], None
        return [SimpleNamespace(id="point-1", payload=dict(self.payload))], None

    def set_payload(self, **kwargs):
        super().set_payload(**kwargs)
        self.deleted = True


class _FakeQuery:
    def __init__(self, db):
        self.db = db

    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def with_for_update(self):
        self.db.lock_count += 1
        return self

    def all(self):
        self.db.read_count += 1
        return list(self.db.documents)


class _FakeDb:
    def __init__(self, documents):
        self.documents = documents
        self.read_count = 0
        self.rollback_count = 0
        self.expire_count = 0
        self.commit_count = 0
        self.lock_count = 0

    def query(self, *_args):
        return _FakeQuery(self)

    def rollback(self):
        self.rollback_count += 1

    def expire_all(self):
        self.expire_count += 1

    def commit(self):
        self.commit_count += 1

    def close(self):
        pass


def test_cli_rereads_locks_and_reports_verified_post_apply_state(monkeypatch, capsys):
    document = _document(1, visibility=DocumentVisibility.INTERNAL)
    db = _FakeDb([document])
    qdrant = _MutableQdrant(document)
    monkeypatch.setattr(audit_cli, "SessionLocal", lambda: db)
    monkeypatch.setattr(audit_cli, "get_qdrant_client", lambda: qdrant)
    monkeypatch.setattr(audit_cli, "_read_open_conflicts", lambda _db: [])

    exit_code = audit_cli.main(["--skip-source-check", "--apply-payload-sync", "--json"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["repaired_qdrant_payload_document_ids"] == [1]
    assert output["payload_sync_document_ids"] == []
    assert qdrant.payload["visibility"] == "internal"
    assert qdrant.scroll_calls == 3
    assert db.read_count == 4
    assert db.rollback_count >= 3
    assert db.lock_count == 1
    assert db.commit_count == 1


def test_cli_does_not_claim_payload_repair_when_points_disappear(monkeypatch, capsys):
    document = _document(1, visibility=DocumentVisibility.INTERNAL)
    db = _FakeDb([document])
    qdrant = _DisappearingQdrant(document)
    monkeypatch.setattr(audit_cli, "SessionLocal", lambda: db)
    monkeypatch.setattr(audit_cli, "get_qdrant_client", lambda: qdrant)
    monkeypatch.setattr(audit_cli, "_read_open_conflicts", lambda _db: [])

    exit_code = audit_cli.main(["--skip-source-check", "--apply-payload-sync"])

    assert exit_code == 2
    assert "Post-repair verification failed" in capsys.readouterr().err


def test_cli_requires_explicit_orphan_selection(capsys):
    exit_code = audit_cli.main(["--apply-orphan-quarantine"])

    assert exit_code == 2
    assert "requires at least one explicit --orphan-id" in capsys.readouterr().err
