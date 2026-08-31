"""Read-only consistency audit for document metadata and vector payloads.

The ingestion pipeline writes one logical document to MySQL, MinIO and Qdrant.  Those
systems cannot share a transaction, so this module deliberately treats MySQL as the
metadata source of truth and reports drift without changing anything by default.

Automatic repair is limited to safe Qdrant payload synchronisation and explicitly
selected, reversible orphan quarantine. Deleting vectors, selecting a duplicate to keep,
or applying a new classification all require a human decision (and category changes may
require re-chunking/re-embedding).
"""

from __future__ import annotations

import hashlib
import json
import logging
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any

from qdrant_client import models

from backend.core.enums import DocumentReviewStatus, DocumentStatus, LegalStatus
from backend.services.document_category_service import document_categories
from backend.services.document_classification_service import DocumentClassification, classify_document
from backend.services.parser_service import parse_document

logger = logging.getLogger(__name__)

_VECTOR_METADATA_FIELDS = (
    "document_id",
    "project_id",
    "visibility",
    "title",
    "category",
    "primary_category",
    "document_categories",
    "review_status",
    "legal_status",
    "is_current",
)

_PAYLOAD_SYNC_FIELDS = tuple(field for field in _VECTOR_METADATA_FIELDS if field != "category")

_CLASSIFICATION_FIELDS = (
    "category",
    "subcategory",
    "subdivision_names",
    "building_codes",
    "unit_types",
    "applicable_area",
    "version_label",
    "issued_date",
    "effective_date",
    "expiry_date",
    "applicable_period",
    "legal_document_type",
    "legal_document_number",
    "legal_issuer",
    "legal_domain",
    "legal_status",
)


class MetadataAuditError(RuntimeError):
    """The audit could not safely obtain a required system snapshot."""


@dataclass
class VectorDocumentSnapshot:
    """Compact aggregate of all Qdrant points for one document."""

    document_id: int
    point_count: int = 0
    payload_values: dict[str, Counter[tuple[bool, str]]] = field(
        default_factory=lambda: {key: Counter() for key in _VECTOR_METADATA_FIELDS}
    )
    chunk_hashes: list[tuple[int, str, str]] = field(default_factory=list)

    def add_point(self, *, point_id: Any, payload: dict[str, Any]) -> None:
        self.point_count += 1
        for key in _VECTOR_METADATA_FIELDS:
            self.payload_values[key][_payload_token(payload, key)] += 1

        content = payload.get("content")
        if isinstance(content, str) and content.strip():
            raw_index = payload.get("chunk_index")
            try:
                chunk_index = int(raw_index)  # type: ignore[arg-type]  # guarded by the except below
            except (TypeError, ValueError):
                chunk_index = 2**31 - 1
            self.chunk_hashes.append(
                (
                    chunk_index,
                    str(point_id),
                    _sha256_text(_normalise_content(content)),
                )
            )

    @property
    def indexed_content_sha256(self) -> str | None:
        """Stable fingerprint of the indexed chunks, without retaining their content."""

        if not self.chunk_hashes:
            return None
        ordered_hashes = [item[2] for item in sorted(self.chunk_hashes)]
        return _sha256_text(json.dumps(ordered_hashes, separators=(",", ":")))


@dataclass(frozen=True)
class VectorScan:
    collection_exists: bool
    point_count: int
    documents: dict[int, VectorDocumentSnapshot]
    invalid_document_id_points: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContentProbe:
    """Hashes and classifier suggestion obtained from one source object in MinIO."""

    document_id: int
    source_sha256: str | None = None
    parsed_text_sha256: str | None = None
    classification: DocumentClassification | None = None
    error: str | None = None


@dataclass(frozen=True)
class AuditFinding:
    code: str
    severity: str
    message: str
    document_ids: tuple[int, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "document_ids": list(self.document_ids),
            "details": _json_value(self.details),
        }


@dataclass(frozen=True)
class MetadataAuditReport:
    mysql_document_count: int
    qdrant_collection_exists: bool
    qdrant_document_count: int
    qdrant_point_count: int
    orphan_vector_document_ids: tuple[int, ...]
    quarantined_orphan_vector_document_ids: tuple[int, ...]
    payload_sync_document_ids: tuple[int, ...]
    category_reindex_document_ids: tuple[int, ...]
    findings: tuple[AuditFinding, ...]

    @property
    def finding_counts(self) -> dict[str, int]:
        counts = Counter(finding.severity for finding in self.findings)
        return {severity: counts.get(severity, 0) for severity in ("error", "warning", "info")}

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": {
                "mysql_document_count": self.mysql_document_count,
                "qdrant_collection_exists": self.qdrant_collection_exists,
                "qdrant_document_count": self.qdrant_document_count,
                "qdrant_point_count": self.qdrant_point_count,
                "orphan_vector_document_count": len(self.orphan_vector_document_ids),
                "quarantined_orphan_vector_document_count": len(self.quarantined_orphan_vector_document_ids),
                "payload_sync_candidate_count": len(self.payload_sync_document_ids),
                "category_reindex_candidate_count": len(self.category_reindex_document_ids),
                "finding_counts": self.finding_counts,
            },
            "orphan_vector_document_ids": list(self.orphan_vector_document_ids),
            "quarantined_orphan_vector_document_ids": list(self.quarantined_orphan_vector_document_ids),
            "payload_sync_document_ids": list(self.payload_sync_document_ids),
            "category_reindex_document_ids": list(self.category_reindex_document_ids),
            "findings": [finding.to_dict() for finding in self.findings],
        }


def scan_vector_collection(client: Any, collection_name: str, *, batch_size: int = 256) -> VectorScan:
    """Scroll every document vector and aggregate only data needed by the audit.

    Vectors themselves are explicitly excluded.  Chunk content is hashed immediately so
    the audit does not keep the knowledge base text in memory or in its report.
    """

    if batch_size < 1:
        raise ValueError("batch_size must be positive.")

    try:
        if not client.collection_exists(collection_name):
            return VectorScan(collection_exists=False, point_count=0, documents={})
    except Exception as exc:
        raise MetadataAuditError(f"Could not inspect Qdrant collection '{collection_name}'.") from exc

    documents: dict[int, VectorDocumentSnapshot] = {}
    invalid_point_ids: list[str] = []
    total = 0
    offset: Any = None

    try:
        while True:
            points, next_offset = client.scroll(
                collection_name=collection_name,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            total += len(points)
            for point in points:
                payload = getattr(point, "payload", None) or {}
                document_id = _document_id(payload.get("document_id"))
                if document_id is None:
                    invalid_point_ids.append(str(getattr(point, "id", "unknown")))
                    continue

                snapshot = documents.setdefault(document_id, VectorDocumentSnapshot(document_id=document_id))
                snapshot.add_point(point_id=getattr(point, "id", "unknown"), payload=payload)

            if next_offset is None:
                break
            if next_offset == offset:
                raise MetadataAuditError("Qdrant returned the same scroll offset twice; audit aborted.")
            offset = next_offset
    except MetadataAuditError:
        raise
    except Exception as exc:
        raise MetadataAuditError(f"Could not scroll Qdrant collection '{collection_name}'.") from exc

    return VectorScan(
        collection_exists=True,
        point_count=total,
        documents=documents,
        invalid_document_id_points=tuple(invalid_point_ids),
    )


def probe_document_content(document: Any, minio_client: Any, bucket: str) -> ContentProbe:
    """Read, hash and reclassify one source file without persisting any result."""

    document_id = int(document.id)
    if not document.file_path:
        return ContentProbe(document_id=document_id, error="document has no MinIO object key")

    response = None
    try:
        response = minio_client.get_object(bucket, document.file_path)
        data = response.read()
        sections = parse_document(document.title, data)
        raw_text = "\n\n".join(section.text for section in sections)
        return ContentProbe(
            document_id=document_id,
            source_sha256=hashlib.sha256(data).hexdigest(),
            parsed_text_sha256=_sha256_text(_normalise_content(raw_text)),
            classification=classify_document(document.title, raw_text),
        )
    except Exception as exc:
        logger.warning(
            "Document source could not be inspected during metadata audit.",
            extra={"event": "metadata_audit.content_probe.failed", "document_id": document_id},
        )
        return ContentProbe(document_id=document_id, error=_safe_error(exc))
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                logger.debug("Could not close MinIO audit response.", exc_info=True)
            release_conn = getattr(response, "release_conn", None)
            if callable(release_conn):
                try:
                    release_conn()
                except Exception:
                    logger.debug("Could not release MinIO audit connection.", exc_info=True)


def probe_all_document_content(documents: Iterable[Any], minio_client: Any, bucket: str) -> dict[int, ContentProbe]:
    """Probe documents sequentially so at most one uploaded file is held in memory."""

    return {int(document.id): probe_document_content(document, minio_client, bucket) for document in documents}


def build_metadata_audit_report(
    documents: Iterable[Any],
    vector_scan: VectorScan,
    *,
    content_probes: dict[int, ContentProbe] | None = None,
    open_conflicts: Iterable[Any] | None = None,
) -> MetadataAuditReport:
    """Compare immutable MySQL/Qdrant/MinIO snapshots and create a repair plan."""

    document_list = list(documents)
    documents_by_id = {int(document.id): document for document in document_list}
    probes = content_probes or {}
    findings: list[AuditFinding] = []

    if not vector_scan.collection_exists:
        findings.append(
            AuditFinding(
                code="QDRANT_COLLECTION_MISSING",
                severity="error",
                message="The configured document-vector collection does not exist.",
            )
        )

    if vector_scan.invalid_document_id_points:
        findings.append(
            AuditFinding(
                code="INVALID_VECTOR_DOCUMENT_IDS",
                severity="error",
                message="Some vector points have no valid integer document_id payload.",
                details={"point_ids": list(vector_scan.invalid_document_id_points)},
            )
        )

    unsafe_current_ids = sorted(
        int(document.id)
        for document in document_list
        if bool(document.is_current) and not _is_safe_current_document(document)
    )
    if unsafe_current_ids:
        findings.append(
            AuditFinding(
                code="MYSQL_UNSAFE_CURRENT_STATE",
                severity="error",
                message=(
                    "MySQL marks non-retrievable documents current; Qdrant repair will clamp them to is_current=false."
                ),
                document_ids=tuple(unsafe_current_ids),
                details={
                    "states": {
                        str(document_id): {
                            "status": _enum_value(documents_by_id[document_id].status),
                            "review_status": _enum_value(documents_by_id[document_id].review_status),
                            "legal_status": _enum_value(documents_by_id[document_id].legal_status),
                        }
                        for document_id in unsafe_current_ids
                    },
                    "repair": "Review and correct the MySQL lifecycle state; payload sync only quarantines Qdrant.",
                },
            )
        )

    conflicting_current_pairs = sorted(
        (int(conflict.document_id_a), int(conflict.document_id_b))
        for conflict in (open_conflicts or [])
        if _is_approved_current(documents_by_id.get(int(conflict.document_id_a)))
        and _is_approved_current(documents_by_id.get(int(conflict.document_id_b)))
    )
    if conflicting_current_pairs:
        findings.append(
            AuditFinding(
                code="OPEN_CONFLICT_BOTH_DOCUMENTS_RETRIEVABLE",
                severity="error",
                message="Both endpoints of an OPEN conflict are approved/current in MySQL.",
                document_ids=tuple(sorted({item for pair in conflicting_current_pairs for item in pair})),
                details={"pairs": [list(pair) for pair in conflicting_current_pairs]},
            )
        )
    unsafe_conflict_document_ids = {document_id for pair in conflicting_current_pairs for document_id in pair}

    all_orphan_ids = sorted(set(vector_scan.documents) - set(documents_by_id))
    quarantined_orphan_ids = [
        document_id for document_id in all_orphan_ids if _is_quarantined(vector_scan.documents[document_id])
    ]
    orphan_ids = sorted(set(all_orphan_ids) - set(quarantined_orphan_ids))
    if orphan_ids:
        findings.append(
            AuditFinding(
                code="ORPHAN_VECTOR_DOCUMENTS",
                severity="warning",
                message="Qdrant contains vectors whose document no longer exists in MySQL; no vectors were deleted.",
                document_ids=tuple(orphan_ids),
                details={
                    "point_counts": {
                        str(document_id): vector_scan.documents[document_id].point_count for document_id in orphan_ids
                    },
                    "repair": "Review the IDs, then quarantine them with a payload-only maintenance action.",
                },
            )
        )

    if quarantined_orphan_ids:
        findings.append(
            AuditFinding(
                code="QUARANTINED_ORPHAN_VECTOR_DOCUMENTS",
                severity="info",
                message="Orphan vectors are already excluded from retrieval and require no further quarantine action.",
                document_ids=tuple(quarantined_orphan_ids),
                details={
                    "point_counts": {
                        str(document_id): vector_scan.documents[document_id].point_count
                        for document_id in quarantined_orphan_ids
                    }
                },
            )
        )

    if vector_scan.collection_exists:
        missing_vector_ids = sorted(
            document_id
            for document_id, document in documents_by_id.items()
            if _enum_value(document.status) == DocumentStatus.COMPLETED.value
            and document_id not in vector_scan.documents
        )
        if missing_vector_ids:
            findings.append(
                AuditFinding(
                    code="COMPLETED_DOCUMENTS_WITHOUT_VECTORS",
                    severity="error",
                    message="Completed MySQL documents have no Qdrant points and need controlled re-indexing.",
                    document_ids=tuple(missing_vector_ids),
                )
            )

    payload_sync_ids: list[int] = []
    category_reindex_ids: list[int] = []
    for document_id in sorted(set(documents_by_id) & set(vector_scan.documents)):
        document = documents_by_id[document_id]
        snapshot = vector_scan.documents[document_id]
        expected = expected_vector_payload(document)
        all_drift_counts = {
            key: snapshot.point_count - _matching_payload_count(snapshot, expected, key)
            for key in _VECTOR_METADATA_FIELDS
            if key != "category"
        }
        all_drift_counts = {key: count for key, count in all_drift_counts.items() if count}
        allowed_category_tokens = {
            _payload_token({"category": category}, "category") for category in document_categories(document)
        }
        category_drift_count = sum(
            count
            for token, count in snapshot.payload_values["category"].items()
            if token not in allowed_category_tokens
        )
        if category_drift_count:
            category_reindex_ids.append(document_id)
            findings.append(
                AuditFinding(
                    code="QDRANT_CATEGORY_DRIFT_REQUIRES_REINDEX",
                    severity="warning",
                    message="A Qdrant chunk category is outside the document's approved categories; re-indexing is required.",
                    document_ids=(document_id,),
                    details={
                        "mismatched_point_count": category_drift_count,
                        "point_count": snapshot.point_count,
                        "mysql_primary_category": _enum_value(document.category),
                        "mysql_categories": document_categories(document),
                        "repair": "Review the category, then re-chunk, re-embed and atomically replace the document points.",
                    },
                )
            )

        if document_id in unsafe_conflict_document_ids:
            continue

        drift_counts = {key: count for key, count in all_drift_counts.items() if key in _PAYLOAD_SYNC_FIELDS}
        if drift_counts:
            payload_sync_ids.append(document_id)
            findings.append(
                AuditFinding(
                    code="QDRANT_PAYLOAD_DRIFT",
                    severity="warning",
                    message="Qdrant payload differs from MySQL metadata; payload-only synchronisation is safe.",
                    document_ids=(document_id,),
                    details={
                        "mismatched_point_counts": drift_counts,
                        "point_count": snapshot.point_count,
                    },
                )
            )

    findings.extend(_duplicate_findings(documents_by_id, vector_scan, probes))
    findings.extend(_classification_findings(documents_by_id, probes))

    return MetadataAuditReport(
        mysql_document_count=len(document_list),
        qdrant_collection_exists=vector_scan.collection_exists,
        qdrant_document_count=len(vector_scan.documents),
        qdrant_point_count=vector_scan.point_count,
        orphan_vector_document_ids=tuple(orphan_ids),
        quarantined_orphan_vector_document_ids=tuple(quarantined_orphan_ids),
        payload_sync_document_ids=tuple(payload_sync_ids),
        category_reindex_document_ids=tuple(category_reindex_ids),
        findings=tuple(findings),
    )


def expected_vector_payload(document: Any) -> dict[str, Any]:
    """Payload fields safe to sync without changing chunking or embeddings."""

    return {
        "document_id": int(document.id),
        "project_id": document.project_id,
        "visibility": _enum_value(document.visibility),
        "title": document.title,
        "primary_category": _enum_value(document.category),
        "document_categories": document_categories(document),
        "review_status": _enum_value(document.review_status),
        "legal_status": _enum_value(document.legal_status),
        "is_current": _is_safe_current_document(document),
    }


def synchronize_vector_payloads(
    client: Any,
    collection_name: str,
    documents: Iterable[Any],
    document_ids: Iterable[int],
    *,
    apply: bool = False,
) -> tuple[int, ...]:
    """Plan or apply payload-only repairs for explicitly selected existing documents.

    `apply=False` is intentionally the default.  The function never deletes points and
    never changes vectors, chunks, source objects or MySQL rows.
    """

    documents_by_id = {int(document.id): document for document in documents}
    selected_ids = tuple(sorted(set(int(document_id) for document_id in document_ids)))

    unknown = sorted(set(selected_ids) - set(documents_by_id))
    if unknown:
        raise ValueError(f"Refusing payload sync for unknown MySQL document IDs: {unknown}")

    if not apply:
        return selected_ids

    if not client.collection_exists(collection_name):
        raise MetadataAuditError(f"Cannot synchronise payloads: Qdrant collection '{collection_name}' is missing.")

    repaired: list[int] = []
    for document_id in selected_ids:
        document = documents_by_id[document_id]
        try:
            client.set_payload(
                collection_name=collection_name,
                payload=expected_vector_payload(document),
                points=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="document_id",
                                match=models.MatchValue(value=document_id),
                            )
                        ]
                    )
                ),
                wait=True,
            )
        except Exception as exc:
            raise MetadataAuditError(f"Could not synchronise Qdrant payload for document {document_id}.") from exc
        repaired.append(document_id)

    return tuple(repaired)


def quarantine_orphan_vectors(
    client: Any,
    collection_name: str,
    *,
    mysql_document_ids: Iterable[int],
    vector_document_ids: Iterable[int],
    selected_document_ids: Iterable[int],
    apply: bool = False,
) -> tuple[int, ...]:
    """Plan or reversibly exclude Qdrant documents absent from MySQL.

    Quarantine only changes retrieval-control payloads; points and vectors remain in
    Qdrant for investigation/recovery. Requiring both snapshots and an explicit selected
    subset prevents a caller from quarantining an existing MySQL document or every orphan
    merely because the command was pointed at mismatched environments.
    """

    mysql_ids = {int(document_id) for document_id in mysql_document_ids}
    vector_ids = {int(document_id) for document_id in vector_document_ids}
    orphan_ids = {document_id for document_id in vector_ids - mysql_ids if document_id > 0}
    selected_ids = tuple(sorted(set(int(document_id) for document_id in selected_document_ids)))
    invalid_selection = sorted(set(selected_ids) - orphan_ids)
    if invalid_selection:
        raise ValueError(f"Refusing quarantine for IDs that are not current Qdrant orphans: {invalid_selection}")
    if not apply:
        return selected_ids

    if not client.collection_exists(collection_name):
        raise MetadataAuditError(f"Cannot quarantine orphans: Qdrant collection '{collection_name}' is missing.")

    quarantined: list[int] = []
    for document_id in selected_ids:
        try:
            client.set_payload(
                collection_name=collection_name,
                payload={
                    "review_status": "rejected",
                    "is_current": False,
                    "quarantine_reason": "missing_mysql_document",
                },
                points=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="document_id",
                                match=models.MatchValue(value=document_id),
                            )
                        ]
                    )
                ),
                wait=True,
            )
        except Exception as exc:
            raise MetadataAuditError(f"Could not quarantine orphan vectors for document {document_id}.") from exc
        quarantined.append(document_id)

    return tuple(quarantined)


def _duplicate_findings(
    documents_by_id: dict[int, Any],
    vector_scan: VectorScan,
    probes: dict[int, ContentProbe],
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []

    source_groups = _hash_groups(
        (document_id, probe.source_sha256) for document_id, probe in probes.items() if document_id in documents_by_id
    )
    for digest, document_ids in source_groups.items():
        findings.append(
            AuditFinding(
                code="DUPLICATE_SOURCE_FILES",
                severity="warning",
                message="Multiple MySQL documents contain byte-for-byte identical source files.",
                document_ids=document_ids,
                details={"sha256": digest, "repair": "Choose the authoritative document before removing any copy."},
            )
        )

    parsed_groups = _hash_groups(
        (document_id, probe.parsed_text_sha256)
        for document_id, probe in probes.items()
        if document_id in documents_by_id
    )
    source_sets = {frozenset(group) for group in source_groups.values()}
    for digest, document_ids in parsed_groups.items():
        if frozenset(document_ids) in source_sets:
            continue
        findings.append(
            AuditFinding(
                code="DUPLICATE_PARSED_CONTENT",
                severity="warning",
                message="Different source objects produced the same normalized parsed text.",
                document_ids=document_ids,
                details={"parsed_text_sha256": digest},
            )
        )

    parsed_sets = {frozenset(group) for group in parsed_groups.values()}
    known_duplicate_sets = source_sets | parsed_sets
    indexed_groups = _hash_groups(
        (document_id, snapshot.indexed_content_sha256)
        for document_id, snapshot in vector_scan.documents.items()
        if document_id in documents_by_id
    )
    for digest, document_ids in indexed_groups.items():
        if frozenset(document_ids) in known_duplicate_sets:
            continue
        findings.append(
            AuditFinding(
                code="DUPLICATE_INDEXED_CONTENT",
                severity="warning",
                message="Documents have identical indexed chunk fingerprints.",
                document_ids=document_ids,
                details={"indexed_content_sha256": digest, "evidence": "qdrant_chunk_fingerprint"},
            )
        )

    unavailable = {
        str(document_id): probe.error
        for document_id, probe in probes.items()
        if document_id in documents_by_id and probe.error
    }
    if unavailable:
        findings.append(
            AuditFinding(
                code="SOURCE_CONTENT_UNAVAILABLE",
                severity="warning",
                message="Some source objects could not be parsed; duplicate and classifier checks are incomplete for them.",
                document_ids=tuple(sorted(int(document_id) for document_id in unavailable)),
                details={"errors": unavailable},
            )
        )

    return findings


def _classification_findings(
    documents_by_id: dict[int, Any],
    probes: dict[int, ContentProbe],
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []

    for document_id in sorted(set(documents_by_id) & set(probes)):
        document = documents_by_id[document_id]
        classification = probes[document_id].classification
        if classification is None:
            continue

        current_category = _enum_value(document.category)
        suggested_category = _enum_value(classification.category)
        if current_category != suggested_category:
            findings.append(
                AuditFinding(
                    code="CLASSIFIER_CATEGORY_SUGGESTION_DRIFT",
                    severity="warning",
                    message=(
                        "Stored category differs from the current classifier suggestion; no classification was changed."
                    ),
                    document_ids=(document_id,),
                    details={
                        "stored": current_category,
                        "suggested": suggested_category,
                        "confidence": classification.confidence,
                        "reason": classification.reason,
                        "repair": "Admin review, then re-chunk/re-embed if the category changes chunking strategy.",
                    },
                )
            )

        drift: dict[str, dict[str, Any]] = {}
        for field_name in _CLASSIFICATION_FIELDS:
            if field_name == "category":
                continue
            current = getattr(document, field_name, None)
            suggested = getattr(classification, field_name, None)
            if _comparison_value(current) != _comparison_value(suggested):
                drift[field_name] = {
                    "stored": _json_value(current),
                    "suggested": _json_value(suggested),
                }

        if drift:
            findings.append(
                AuditFinding(
                    code="CLASSIFIER_METADATA_SUGGESTION_DRIFT",
                    severity="info",
                    message="Stored metadata differs from the current classifier suggestion; Admin review is required.",
                    document_ids=(document_id,),
                    details={"fields": drift, "confidence": classification.confidence},
                )
            )

    return findings


def _hash_groups(pairs: Iterable[tuple[int, str | None]]) -> dict[str, tuple[int, ...]]:
    groups: defaultdict[str, list[int]] = defaultdict(list)
    for document_id, digest in pairs:
        if digest:
            groups[digest].append(document_id)
    return {
        digest: tuple(sorted(set(document_ids)))
        for digest, document_ids in sorted(groups.items())
        if len(set(document_ids)) > 1
    }


def _document_id(value: Any) -> int | None:
    if type(value) is not int:
        return None
    return value if value > 0 else None


def _is_quarantined(snapshot: VectorDocumentSnapshot) -> bool:
    if snapshot.point_count <= 0:
        return False
    approved = snapshot.payload_values["review_status"].get(
        _payload_token({"review_status": "approved"}, "review_status"),
        0,
    )
    inactive = snapshot.payload_values["is_current"].get(
        _payload_token({"is_current": False}, "is_current"),
        0,
    )
    return approved == 0 and inactive == snapshot.point_count


def _is_safe_current_document(document: Any) -> bool:
    if not bool(document.is_current):
        return False
    if _enum_value(document.status) != DocumentStatus.COMPLETED.value:
        return False
    if _enum_value(document.review_status) != DocumentReviewStatus.APPROVED.value:
        return False
    return _enum_value(document.legal_status) not in {
        LegalStatus.NOT_YET_EFFECTIVE.value,
        LegalStatus.EXPIRED.value,
        LegalStatus.REPEALED.value,
        LegalStatus.REPLACED.value,
    }


def _is_approved_current(document: Any | None) -> bool:
    return bool(
        document is not None
        and _is_safe_current_document(document)
        and _enum_value(document.review_status) == DocumentReviewStatus.APPROVED.value
    )


def _payload_token(payload: dict[str, Any], key: str) -> tuple[bool, str]:
    if key not in payload:
        return False, ""
    return True, json.dumps(_json_value(payload[key]), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _matching_payload_count(snapshot: VectorDocumentSnapshot, expected: dict[str, Any], key: str) -> int:
    """Treat an omitted nullable Qdrant key as equivalent to an explicit JSON null."""

    count = snapshot.payload_values[key].get(_payload_token(expected, key), 0)
    if expected.get(key) is None:
        count += snapshot.payload_values[key].get((False, ""), 0)
    return count


def _normalise_content(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _comparison_value(value: Any) -> Any:
    if isinstance(value, (list, tuple, set)):
        return tuple(sorted({_comparison_value(item) for item in value}))
    if isinstance(value, str):
        return " ".join(value.split()).casefold()
    if isinstance(value, Enum):
        return _comparison_value(value.value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _enum_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    return value


def _safe_error(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    return f"{type(exc).__name__}: {text[:300]}" if text else type(exc).__name__
