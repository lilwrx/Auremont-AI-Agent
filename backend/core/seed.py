"""Shared test accounts and sample projects seeded on every startup.

The credentials match the hint shown on the login screen
(frontend/src/routes/sale/Login.tsx). Seeding runs on every boot so anyone who
clones the repo and runs `docker compose up` can log in immediately, without
sharing a database or running a manual user-creation script.

Emails must satisfy `EmailStr` on UserResponse: email-validator rejects the
.local/.test domains, and while seeding would still create the user,
/auth/login would then fail with a 500 while serializing the response.

Projects are seeded for the same reason: a Sale cannot open a session without
picking one, and `project_id` is what unlocks real-time inventory lookups. An
empty catalogue would leave the whole chat flow unusable on a fresh install.
"""

import logging

from backend.core.enums import UserRole

logger = logging.getLogger(__name__)

SEED_USERS = [
    {
        "username": "sale_test",
        "email": "sale_test@salesmate.example.com",
        "password": "pass1234",
        "role": UserRole.SALE,
    },
    {
        "username": "admin_test",
        "email": "admin_test@salesmate.example.com",
        "password": "pass1234",
        "role": UserRole.ADMIN,
    },
]


SEED_PROJECTS = [
    {
        "project_id": "ocean-park-3",
        "name": "Vinhomes Ocean Park 3",
        "location": "Hưng Yên",
        "description": "Dự án mẫu dùng cho demo và mock API tồn kho.",
    },
]


def seed_projects() -> None:
    """Create (or reset) the sample projects. Never raises."""
    from backend.core.mysql_client import SessionLocal
    from backend.repositories.project import ensure_seed_project

    if SessionLocal is None:
        return

    db = SessionLocal()
    try:
        for seed in SEED_PROJECTS:
            ensure_seed_project(db, **seed)
        logger.info(
            "Seeded %d demo projects.",
            len(SEED_PROJECTS),
            extra={
                "event": "seed.projects",
                "count": len(SEED_PROJECTS),
                "project_ids": [s["project_id"] for s in SEED_PROJECTS],
            },
        )
    except Exception:  # pragma: no cover - a failed seed must not block startup
        db.rollback()
        logger.warning("Seed du an that bai — bo qua.", exc_info=True, extra={"event": "seed.projects.failed"})
    finally:
        db.close()


def seed_users() -> None:
    """Create (or reset) the shared test accounts. Never raises.

    Imports are local so that importing this module does not pull in a database
    session at module-import time.
    """
    from backend.core.mysql_client import SessionLocal
    from backend.repositories.user import ensure_seed_user

    if SessionLocal is None:
        return

    db = SessionLocal()
    try:
        for seed in SEED_USERS:
            ensure_seed_user(db, **seed)
        logger.info(
            "Seeded %d test accounts.",
            len(SEED_USERS),
            extra={
                "event": "seed.users",
                "count": len(SEED_USERS),
                "usernames": [s["username"] for s in SEED_USERS],
            },
        )
    except Exception:  # pragma: no cover - a failed seed must not block startup
        db.rollback()
        logger.warning("Seed tai khoan test that bai — bo qua.", exc_info=True, extra={"event": "seed.users.failed"})
    finally:
        db.close()
