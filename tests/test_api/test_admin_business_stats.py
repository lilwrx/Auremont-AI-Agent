from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.core.deps import get_current_user
from backend.core.mysql_client import Base, get_db
from backend.main import app
from backend.models.chat_session import ChatSession
from backend.models.document import Document
from backend.models.feedback import Feedback
from backend.models.message import Message
from backend.models.project import Project
from backend.models.user import User
from backend.utils.time import utcnow


def test_business_dashboard_excludes_admin_and_e2e_activity():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        admin = User(username="admin", email="admin@example.com", hashed_password="x", role="admin")
        sale = User(
            username="sale_real",
            email="sale@example.com",
            hashed_password="x",
            role="sale",
            is_active=False,
        )
        e2e = User(username="e2e_sale_noise", email="e2e@example.com", hashed_password="x", role="sale")
        db.add_all([admin, sale, e2e])
        db.flush()

        now = utcnow()
        real_session = ChatSession(sale_id=sale.id, customer_name="Khách A", created_at=now)
        old_active_session = ChatSession(sale_id=sale.id, created_at=now - timedelta(days=40))
        previous_session = ChatSession(sale_id=sale.id, created_at=now - timedelta(days=20))
        db.add_all(
            [
                real_session,
                old_active_session,
                previous_session,
                ChatSession(sale_id=admin.id),
                ChatSession(sale_id=e2e.id),
            ]
        )
        db.flush()
        question = Message(session_id=real_session.id, sender="sale", content="Còn căn không?")
        answer = Message(
            session_id=real_session.id,
            sender="agent",
            content="Còn căn.",
            verifier_score=0.8,
            faithfulness=0.9,
            answer_relevancy=0.8,
            requires_hitl=True,
        )
        db.add_all([question, answer])
        db.flush()
        db.add_all(
            [
                Message(
                    session_id=old_active_session.id,
                    sender="sale",
                    content="Giá hôm nay thế nào?",
                    created_at=now,
                ),
                Message(
                    session_id=previous_session.id,
                    sender="sale",
                    content="Câu hỏi kỳ trước",
                    created_at=now - timedelta(days=20),
                ),
                Feedback(
                    message_id=answer.id,
                    user_id=sale.id,
                    type="helpful",
                    created_at=now - timedelta(minutes=2),
                ),
                Feedback(
                    message_id=answer.id,
                    user_id=sale.id,
                    type="wrong",
                    created_at=now - timedelta(minutes=1),
                ),
            ]
        )
        db.commit()

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: admin
        response = TestClient(app).get("/api/v1/admin/stats/business")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["summary"]["sessions"] == 1
        assert payload["summary"]["active_sales"] == 1
        assert payload["summary"]["questions"] == 2
        assert payload["previous_summary"]["sessions"] == 1
        assert payload["previous_summary"]["questions"] == 1
        assert payload["period"]["timezone"] == "Asia/Bangkok"
        assert payload["top_sales"] == [
            {"sale_id": sale.id, "username": "sale_real", "sessions": 1, "customers": 1, "questions": 2}
        ]
        assert payload["feedback_distribution"]["helpful"] == 0
        assert payload["feedback_distribution"]["wrong"] == 1
        current_day = next(point for point in payload["activity"] if point["date"] == payload["period"]["current_end"])
        assert current_day["questions"] == 2
        assert len(payload["quality_trend"]) == 14
    finally:
        app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_document_coverage_uses_llm_subdivision_metadata_and_keeps_parent_scope():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        admin = User(username="admin", email="admin@example.com", hashed_password="x", role="admin")
        sale = User(username="sale", email="sale@example.com", hashed_password="x", role="sale")
        parent = Project(id="ocean-park-3", name="Vinhomes Ocean Park 3")
        hai_au = Project(
            id="hai-au",
            name="Hải Âu - Vinhomes Ocean Park",
            details={
                "project": {
                    "id": "hai-au",
                    "name": "Hải Âu",
                    "full_name": "Tiểu khu Hải Âu - Vinhomes Ocean Park",
                    "parent_project_id": "vinhomes-ocean-park",
                }
            },
        )
        sao_bien = Project(
            id="sao-bien",
            name="Sao Biển - Vinhomes Ocean Park",
            details={"project": {"id": "sao-bien", "name": "Sao Biển"}},
        )
        beverly = Project(
            id="the-beverly",
            name="The Beverly - Vinhomes Ocean Park",
            details={"project": {"id": "the-metropolitan", "name": "The Metropolitan"}},
        )
        london = Project(
            id="the-london",
            name="The London - Vinhomes Ocean Park",
            details={"project": {"id": "the-metropolitan", "name": "The Metropolitan"}},
        )
        db.add_all([admin, sale, parent, hai_au, sao_bien, beverly, london])
        db.flush()
        now = utcnow()
        db.add_all(
            [
                Document(
                    title="HaiAu policy.pdf",
                    project_id=parent.id,
                    subdivision_names=["  HAI AU  "],
                    category="sales_policy",
                    status="completed",
                    review_status="approved",
                    is_current=True,
                ),
                Document(
                    title="HaiAu overview.pdf",
                    project_id=None,
                    subdivision_names=["Hải-Âu"],
                    category="subdivision_info",
                    status="completed",
                    review_status="approved",
                    is_current=True,
                ),
                Document(
                    title="HaiAu price.pdf",
                    project_id=None,
                    subdivision_names=["Hải Âu"],
                    category="price_list",
                    status="completed",
                    review_status="pending",
                    is_current=False,
                    classification_version="llm-v1",
                    created_at=now - timedelta(minutes=3),
                ),
                Document(
                    title="HaiAu old floor review.pdf",
                    project_id=None,
                    subdivision_names=["Hải Âu"],
                    category="floor_plan",
                    status="completed",
                    review_status="pending",
                    is_current=False,
                    classification_version="llm-v1",
                    created_at=now - timedelta(minutes=2),
                ),
                Document(
                    title="HaiAu failed floor.pdf",
                    project_id=None,
                    subdivision_names=["Hải Âu"],
                    category="floor_plan",
                    status="failed",
                    review_status="approved",
                    is_current=False,
                    classification_version="llm-v1",
                    created_at=now - timedelta(minutes=1),
                ),
                Document(
                    title="HaiAu legacy payment.pdf",
                    project_id=None,
                    subdivision_names=["Hải Âu"],
                    category="payment_schedule",
                    status="completed",
                    review_status="pending",
                    is_current=False,
                    classification_version=None,
                    created_at=now,
                ),
                Document(
                    title="HaiAu approved payment.pdf",
                    project_id=hai_au.id,
                    subdivision_names=None,
                    category="payment_schedule",
                    status="completed",
                    review_status="approved",
                    is_current=True,
                    created_at=now,
                ),
                Document(
                    title="HaiAu legal review.pdf",
                    project_id=hai_au.id,
                    subdivision_names=None,
                    category="legal_document",
                    status="completed",
                    review_status="pending",
                    is_current=False,
                    classification_version="llm-v1",
                    created_at=now,
                ),
                Document(
                    title="Unknown floor plan.pdf",
                    project_id=None,
                    subdivision_names=["Hải Âu mở rộng"],
                    category="floor_plan",
                    status="completed",
                    review_status="approved",
                    is_current=True,
                ),
                Document(
                    title="Metropolitan overview.pdf",
                    project_id=None,
                    subdivision_names=["The Metropolitan"],
                    category="subdivision_info",
                    status="completed",
                    review_status="approved",
                    is_current=True,
                ),
            ]
        )
        db.commit()

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: admin
        response = TestClient(app).get("/api/v1/admin/stats/business")
        assert response.status_code == 200, response.text
        coverage = {row["project_id"]: row for row in response.json()["document_coverage"]}

        assert set(coverage["hai-au"]["categories"]) == {
            "subdivision_info",
            "sales_policy",
            "price_list",
            "floor_plan",
            "legal_document",
            "payment_schedule",
        }
        assert coverage["hai-au"]["categories"]["subdivision_info"] == "unavailable"
        assert coverage["hai-au"]["categories"]["sales_policy"] == "unavailable"
        assert coverage["hai-au"]["categories"]["price_list"] == "pending_review"
        assert coverage["hai-au"]["categories"]["floor_plan"] == "unavailable"
        assert coverage["hai-au"]["categories"]["legal_document"] == "pending_review"
        assert coverage["hai-au"]["categories"]["payment_schedule"] == "ready"
        assert coverage["ocean-park-3"]["categories"]["sales_policy"] == "ready"
        assert coverage["ocean-park-3"]["categories"]["subdivision_info"] == "missing"
        assert all(state == "missing" for state in coverage["sao-bien"]["categories"].values())
        assert coverage["the-beverly"]["categories"]["subdivision_info"] == "missing"
        assert coverage["the-london"]["categories"]["subdivision_info"] == "missing"

        filtered = TestClient(app).get("/api/v1/admin/stats/business?project_id=hai-au")
        assert filtered.status_code == 200, filtered.text
        assert [row["project_id"] for row in filtered.json()["document_coverage"]] == ["hai-au"]
        assert filtered.json()["document_coverage"][0]["categories"]["subdivision_info"] == "unavailable"
        assert filtered.json()["summary"]["ready_documents"] == 1

        scoped_documents = TestClient(app).get("/api/v1/documents?coverage_scope=hai-au")
        assert scoped_documents.status_code == 200, scoped_documents.text
        scoped_titles = {row["title"] for row in scoped_documents.json()}
        assert "HaiAu policy.pdf" in scoped_titles
        assert "HaiAu overview.pdf" in scoped_titles
        assert "HaiAu failed floor.pdf" in scoped_titles
        assert "HaiAu approved payment.pdf" in scoped_titles
        assert "Unknown floor plan.pdf" not in scoped_titles

        unknown_scope = TestClient(app).get("/api/v1/documents?coverage_scope=not-a-project")
        assert unknown_scope.status_code == 404
    finally:
        app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)
