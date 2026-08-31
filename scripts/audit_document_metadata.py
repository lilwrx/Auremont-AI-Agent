"""Audit MySQL/MinIO/Qdrant document consistency without mutating by default.

Examples (run from the repository root):

    python scripts/audit_document_metadata.py
    python scripts/audit_document_metadata.py --json
    python scripts/audit_document_metadata.py --skip-source-check
    python scripts/audit_document_metadata.py --apply-payload-sync
    python scripts/audit_document_metadata.py --apply-orphan-quarantine --orphan-id 30

Apply mode can synchronise non-structural Qdrant payload fields from MySQL or quarantine
explicitly selected orphans. This script intentionally cannot delete vectors, choose
between duplicates, update classification/category, or re-chunk/re-embed content.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.core.config import settings  # noqa: E402
from backend.core.enums import ConflictStatus  # noqa: E402
from backend.core.minio_client import get_minio_client  # noqa: E402
from backend.core.mysql_client import SessionLocal  # noqa: E402
from backend.core.qdrant_client import get_qdrant_client  # noqa: E402
from backend.models.conflict_flag import ConflictFlag  # noqa: E402
from backend.models.document import Document  # noqa: E402
from backend.services.metadata_audit_service import (  # noqa: E402
    MetadataAuditError,
    build_metadata_audit_report,
    probe_all_document_content,
    quarantine_orphan_vectors,
    scan_vector_collection,
    synchronize_vector_payloads,
)


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit document duplicates, classifier suggestion drift, orphan/missing vectors, "
            "and Qdrant payload drift. Default mode is read-only."
        )
    )
    parser.add_argument(
        "--apply-payload-sync",
        action="store_true",
        help="Synchronise Qdrant payload metadata from MySQL for drifted documents.",
    )
    parser.add_argument(
        "--apply-orphan-quarantine",
        action="store_true",
        help=(
            "Set review_status=rejected and is_current=false on vectors absent from MySQL; "
            "points are retained and can be recovered."
        ),
    )
    parser.add_argument(
        "--orphan-id",
        action="append",
        type=int,
        default=[],
        metavar="ID",
        help="Explicit orphan document ID to quarantine; repeat once per ID.",
    )
    parser.add_argument(
        "--skip-source-check",
        action="store_true",
        help="Do not download/parse MinIO originals; classifier and source-hash checks will be skipped.",
    )
    parser.add_argument("--batch-size", type=int, default=256, help="Qdrant scroll page size (default: 256).")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 when the report contains an error or warning; useful in maintenance CI.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    if args.batch_size < 1:
        print("error: --batch-size must be positive", file=sys.stderr)
        return 2
    if SessionLocal is None:
        print("error: database session is not configured", file=sys.stderr)
        return 2
    selected_orphan_ids = tuple(sorted(set(args.orphan_id)))
    if any(document_id <= 0 for document_id in selected_orphan_ids):
        print("error: --orphan-id must be a positive integer", file=sys.stderr)
        return 2
    if args.apply_orphan_quarantine and not selected_orphan_ids:
        print("error: --apply-orphan-quarantine requires at least one explicit --orphan-id", file=sys.stderr)
        return 2
    if selected_orphan_ids and not args.apply_orphan_quarantine:
        print("error: --orphan-id is only valid together with --apply-orphan-quarantine", file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        qdrant = get_qdrant_client()
        documents, vector_scan = _read_state(db, qdrant, batch_size=args.batch_size)
        content_probes = None
        if not args.skip_source_check:
            content_probes = probe_all_document_content(
                documents,
                get_minio_client(),
                settings.minio_bucket_documents,
            )

        report = build_metadata_audit_report(
            documents,
            vector_scan,
            content_probes=content_probes,
            open_conflicts=_read_open_conflicts(db),
        )

        repaired_ids: tuple[int, ...] = ()
        quarantined_ids: tuple[int, ...] = ()
        if args.apply_payload_sync or args.apply_orphan_quarantine:
            documents, vector_scan = _read_state(
                db,
                qdrant,
                batch_size=args.batch_size,
                refresh=True,
            )
            pre_apply_report = build_metadata_audit_report(
                documents,
                vector_scan,
                open_conflicts=_read_open_conflicts(db),
            )

            non_actionable_orphans = sorted(set(selected_orphan_ids) - set(pre_apply_report.orphan_vector_document_ids))
            if non_actionable_orphans:
                raise MetadataAuditError(
                    "Refusing orphan quarantine because these IDs are not current, actionable orphans: "
                    f"{non_actionable_orphans}"
                )

            if args.apply_payload_sync:
                payload_ids = pre_apply_report.payload_sync_document_ids
                if payload_ids:
                    locked_documents = _lock_documents(db, payload_ids)
                    try:
                        repaired_ids = synchronize_vector_payloads(
                            qdrant,
                            settings.qdrant_collection,
                            locked_documents,
                            payload_ids,
                            apply=True,
                        )
                        db.commit()
                    except Exception:
                        db.rollback()
                        raise

            if args.apply_orphan_quarantine:
                documents, vector_scan = _read_state(
                    db,
                    qdrant,
                    batch_size=args.batch_size,
                    refresh=True,
                )
                current_orphan_report = build_metadata_audit_report(
                    documents,
                    vector_scan,
                    open_conflicts=_read_open_conflicts(db),
                )
                non_actionable_orphans = sorted(
                    set(selected_orphan_ids) - set(current_orphan_report.orphan_vector_document_ids)
                )
                if non_actionable_orphans:
                    raise MetadataAuditError(
                        "Refusing orphan quarantine after refresh because these IDs are no longer actionable: "
                        f"{non_actionable_orphans}"
                    )
                quarantined_ids = quarantine_orphan_vectors(
                    qdrant,
                    settings.qdrant_collection,
                    mysql_document_ids=(document.id for document in documents),
                    vector_document_ids=vector_scan.documents,
                    selected_document_ids=selected_orphan_ids,
                    apply=True,
                )

            documents, vector_scan = _read_state(
                db,
                qdrant,
                batch_size=args.batch_size,
                refresh=True,
            )
            content_probes = None
            if not args.skip_source_check:
                content_probes = probe_all_document_content(
                    documents,
                    get_minio_client(),
                    settings.minio_bucket_documents,
                )
            report = build_metadata_audit_report(
                documents,
                vector_scan,
                content_probes=content_probes,
                open_conflicts=_read_open_conflicts(db),
            )

            failed_payload_sync = sorted(
                document_id
                for document_id in repaired_ids
                if document_id not in vector_scan.documents or document_id in report.payload_sync_document_ids
            )
            if failed_payload_sync:
                raise MetadataAuditError(f"Post-repair verification failed for payload sync: {failed_payload_sync}")
            failed_quarantine = sorted(set(quarantined_ids) - set(report.quarantined_orphan_vector_document_ids))
            if failed_quarantine:
                raise MetadataAuditError(f"Post-repair verification failed for orphan quarantine: {failed_quarantine}")

        applied_actions = []
        if args.apply_payload_sync:
            applied_actions.append("payload_sync")
        if args.apply_orphan_quarantine:
            applied_actions.append("orphan_quarantine")

        output = {
            "mode": "+".join(applied_actions) if applied_actions else "dry_run",
            "source_content_audit": "skipped" if args.skip_source_check else "attempted",
            "repaired_qdrant_payload_document_ids": list(repaired_ids),
            "newly_quarantined_orphan_vector_document_ids": list(quarantined_ids),
            **report.to_dict(),
        }
        if args.as_json:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            _print_human(output)

        has_problem = any(finding.severity in {"error", "warning"} for finding in report.findings)
        return 1 if args.strict and has_problem else 0
    except MetadataAuditError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {_bounded(str(exc))}", file=sys.stderr)
        return 2
    finally:
        db.close()


def _print_human(output: dict[str, Any]) -> None:
    summary = output["summary"]
    counts = summary["finding_counts"]
    print(f"Mode: {output['mode']}")
    if output["mode"] == "dry_run":
        print("No data was changed.")
    else:
        repaired = output["repaired_qdrant_payload_document_ids"]
        print(f"Qdrant payloads synchronised: {len(repaired)} document(s) {repaired}")
        quarantined = output["newly_quarantined_orphan_vector_document_ids"]
        print(f"Orphan vector documents quarantined: {len(quarantined)} document(s) {quarantined}")
    print(f"Source content audit: {output['source_content_audit']}")
    print(
        "Documents: "
        f"MySQL={summary['mysql_document_count']}, "
        f"Qdrant={summary['qdrant_document_count']}, "
        f"points={summary['qdrant_point_count']}"
    )
    print(f"Findings: error={counts['error']}, warning={counts['warning']}, info={counts['info']}")

    findings = output["findings"]
    if not findings:
        print("No consistency findings.")
    for finding in findings:
        ids = finding["document_ids"]
        suffix = f" documents={ids}" if ids else ""
        print(f"[{finding['severity'].upper()}] {finding['code']}{suffix}")
        print(f"  {finding['message']}")
        if finding["details"]:
            details = json.dumps(finding["details"], ensure_ascii=False, sort_keys=True)
            print(f"  details={details}")

    candidates = output["payload_sync_document_ids"]
    if output["mode"] == "dry_run" and candidates:
        print(
            f"Safe repair available: rerun with --apply-payload-sync to update only Qdrant payloads for {candidates}."
        )
    orphans = output["orphan_vector_document_ids"]
    if output["mode"] == "dry_run" and orphans:
        print(
            "Reversible orphan repair available: rerun with --apply-orphan-quarantine "
            "and one explicit --orphan-id per reviewed ID to exclude them without deleting vectors. "
            f"Actionable IDs: {orphans}."
        )
    reindex_ids = output["category_reindex_document_ids"]
    if reindex_ids:
        print(f"Category drift requires controlled re-chunk/re-embed; payload sync skipped it: {reindex_ids}")
    print("Orphan deletion, duplicate selection, reclassification and re-embedding remain report-only.")


def _read_state(db: Any, qdrant: Any, *, batch_size: int, refresh: bool = False) -> tuple[list[Any], Any]:
    if refresh:
        db.rollback()
        db.expire_all()
    documents = db.query(Document).order_by(Document.id.asc()).all()
    vector_scan = scan_vector_collection(
        qdrant,
        settings.qdrant_collection,
        batch_size=batch_size,
    )
    return documents, vector_scan


def _lock_documents(db: Any, document_ids: tuple[int, ...]) -> list[Any]:
    db.rollback()
    db.expire_all()
    documents = (
        db.query(Document).filter(Document.id.in_(document_ids)).order_by(Document.id.asc()).with_for_update().all()
    )
    found_ids = {int(document.id) for document in documents}
    missing_ids = sorted(set(document_ids) - found_ids)
    if missing_ids:
        db.rollback()
        raise MetadataAuditError(f"Payload-sync documents disappeared before row lock: {missing_ids}")
    return documents


def _read_open_conflicts(db: Any) -> list[Any]:
    return (
        db.query(ConflictFlag).filter(ConflictFlag.status == ConflictStatus.OPEN).order_by(ConflictFlag.id.asc()).all()
    )


def _bounded(value: str, limit: int = 300) -> str:
    return " ".join(value.split())[:limit]


if __name__ == "__main__":
    raise SystemExit(main())
