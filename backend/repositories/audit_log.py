from datetime import datetime

from sqlalchemy.orm import Session

from backend.models.audit_log import AuditLog


def list_audit_logs(
    db: Session,
    *,
    event: str | None = None,
    user_id: int | None = None,
    since: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditLog]:
    """Most recent first — an audit trail is read newest-backwards."""
    query = db.query(AuditLog)

    if event is not None:
        query = query.filter(AuditLog.event == event)
    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    if since is not None:
        query = query.filter(AuditLog.created_at >= since)

    return query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset(offset).limit(limit).all()


def count_audit_logs(db: Session, *, event: str | None = None, since: datetime | None = None) -> int:
    query = db.query(AuditLog)
    if event is not None:
        query = query.filter(AuditLog.event == event)
    if since is not None:
        query = query.filter(AuditLog.created_at >= since)
    return query.count()
