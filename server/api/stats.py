"""Global overview routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from server.auth import get_current_user
from server.models import get_db
from server.models.industry import Industry
from server.models.user import User
from server.workers import get_job_status

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/stats/overview")
def overview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    industries = (
        db.query(Industry)
        .filter(Industry.user_id == current_user.id, Industry.is_active == True)
        .all()
    )
    return {
        "industry_count": len(industries),
        "industries": [
            {"id": i.id, "name": i.name, "slug": i.slug, "platforms": i.platforms}
            for i in industries
        ],
    }


@router.get("/tasks/status/{job_id}")
def job_status(job_id: str):
    """Poll a background job's status."""
    status = get_job_status(job_id)
    if status is None:
        return {"status": "not_found"}
    return status
