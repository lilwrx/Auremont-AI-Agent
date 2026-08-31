import uuid

from sqlalchemy.orm import Session

from backend.models.project import Project
from backend.schemas.project import ProjectCreate


def create_project(db: Session, schema: ProjectCreate) -> Project:
    project = Project(
        id=str(uuid.uuid4()),
        name=schema.name,
        location=schema.location,
        description=schema.description,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def ensure_seed_project(
    db: Session,
    project_id: str,
    name: str,
    location: str | None = None,
    description: str | None = None,
) -> Project:
    """Create a project with a fixed id, or bring an existing one back to that state.

    Uses an explicit id rather than the generated UUID from `create_project` because
    seeded projects must be referable by a stable, readable slug: `INVENTORY_API_URL`
    is queried with `project_id`, so the value has to match the mock/internal API's
    data (see README §6.2.1) and stay identical across machines and restarts.
    """
    project = db.query(Project).filter(Project.id == project_id).first()

    if project is None:
        project = Project(id=project_id, name=name, location=location, description=description)
        db.add(project)
    else:
        project.name = name
        project.location = location
        project.description = description

    db.commit()
    db.refresh(project)
    return project


def list_projects(db: Session) -> list[Project]:
    return db.query(Project).order_by(Project.name).all()


def get_project(db: Session, project_id: str) -> Project | None:
    return db.query(Project).filter(Project.id == project_id).first()
