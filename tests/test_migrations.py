"""Migration phải luôn khớp với model.

Nếu ai đó sửa model mà quên tạo revision, `alembic upgrade head` trên môi trường
mới sẽ dựng ra schema thiếu cột — và lỗi chỉ nổ lúc chạy thật. Test này bắt
tình huống đó ngay từ CI.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from backend.core.mysql_client import Base
from backend.models import (  # noqa: F401  (đăng ký bảng vào Base.metadata)
    audit_log,
    chat_session,
    conflict_flag,
    customer_conversation_summary,
    document,
    document_relation,
    feedback,
    hitl_log,
    lead,
    message,
    news_article,
    observability,
    project,
    user,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {
    "users",
    "projects",
    "documents",
    "chat_sessions",
    "messages",
    "feedback",
    "hitl_logs",
    "conflict_flags",
    "document_relations",
    "leads",
    "pipeline_trace_runs",
    "llm_usage_events",
    "customer_conversation_summaries",
    "news_articles",
}


@pytest.fixture
def migrated_db(tmp_path):
    """Chạy `alembic upgrade head` lên một SQLite trống."""
    db_path = tmp_path / "migrated.db"
    url = f"sqlite:///{db_path}"

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.config_file_name = None
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)

    engine = create_engine(url)
    try:
        command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()


def test_migration_creates_every_business_table(migrated_db):
    tables = set(inspect(migrated_db).get_table_names())
    missing = EXPECTED_TABLES - tables
    assert not missing, f"Migration thiếu bảng: {sorted(missing)}"


def test_hitl_audit_trail_keeps_who_what_when(migrated_db):
    """HITL log là bằng chứng Sale đã đọc & xác nhận trước khi gửi khách."""
    columns = {c["name"] for c in inspect(migrated_db).get_columns("hitl_logs")}
    for column in ("message_id", "sale_id", "status", "confirmed_content", "confirmed_at", "created_at"):
        assert column in columns, f"hitl_logs thiếu cột audit: {column}"


def test_conflict_analysis_metadata_is_persisted(migrated_db):
    conflict_columns = {column["name"] for column in inspect(migrated_db).get_columns("conflict_flags")}
    assert {
        "detection_method",
        "confidence",
        "similarity_score",
        "conflict_type",
        "evidence",
        "analysis_version",
    } <= conflict_columns

    document_columns = {column["name"] for column in inspect(migrated_db).get_columns("documents")}
    assert "conflict_facts" in document_columns


def test_schema_matches_models(migrated_db):
    """Không được có drift giữa migration và model."""
    with migrated_db.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diff = compare_metadata(context, Base.metadata)

    assert diff == [], (
        "Model đã đổi nhưng chưa có migration tương ứng. "
        "Chạy: alembic revision --autogenerate -m '<mô tả>'\n"
        f"Khác biệt: {diff}"
    )


def test_repair_migration_restores_missing_document_relations(tmp_path):
    """Heal a stamped long-lived DB whose relation table was removed or never created."""

    db_path = tmp_path / "drifted.db"
    url = f"sqlite:///{db_path}"
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.config_file_name = None
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)

    engine = create_engine(url)
    try:
        command.upgrade(config, "b3c4d5e6f7a8")
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE document_relations")

        command.upgrade(config, "head")
        assert "document_relations" in inspect(engine).get_table_names()
        indexes = {item["name"] for item in inspect(engine).get_indexes("document_relations")}
        assert "ix_document_relations_target_document_id" in indexes
        assert "ix_document_relations_review_status" in indexes
    finally:
        engine.dispose()


def test_reconciliation_migration_accepts_the_develop_b1_history(tmp_path):
    """Upgrade a DB where b1 meant leads, not customer summaries.

    ``develop`` and the feature branch once published the same revision id with different
    contents.  Reproducing the develop-side schema here prevents a future cleanup from
    reintroducing an upgrade failure for databases that already ran that revision.
    """

    db_path = tmp_path / "develop-history.db"
    url = f"sqlite:///{db_path}"
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.config_file_name = None
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)

    engine = create_engine(url)
    try:
        command.upgrade(config, "a1b2c3d4e5f7")
        lead.Lead.__table__.create(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN full_name VARCHAR(255)")
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN phone VARCHAR(20)")
            connection.exec_driver_sql("CREATE INDEX ix_users_phone ON users (phone)")

        command.stamp(config, "b1c2d3e4f5a6")
        command.upgrade(config, "head")

        tables = set(inspect(engine).get_table_names())
        assert {"leads", "customer_conversation_summaries", "news_articles"} <= tables
        user_columns = {column["name"] for column in inspect(engine).get_columns("users")}
        assert {"full_name", "phone"} <= user_columns
    finally:
        engine.dispose()


def test_news_repair_migration_restores_missing_news_articles(tmp_path):
    """Repair databases that recorded the old duplicate revision without its table."""
    db_path = tmp_path / "missing-news.db"
    url = f"sqlite:///{db_path}"
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.config_file_name = None
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)

    engine = create_engine(url)
    try:
        command.upgrade(config, "d3e4f5a6b7c8")
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE news_articles")

        command.upgrade(config, "head")

        assert "news_articles" in inspect(engine).get_table_names()
        indexes = {item["name"] for item in inspect(engine).get_indexes("news_articles")}
        assert {"ix_news_articles_url_hash", "ix_news_articles_status"} <= indexes
    finally:
        engine.dispose()
