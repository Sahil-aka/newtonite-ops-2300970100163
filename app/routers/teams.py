from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models import Membership, Team, User
from app.schemas import TeamMembershipResponse

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("", response_model=list[TeamMembershipResponse])
def list_my_teams(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TeamMembershipResponse]:
    rows = db.execute(
        select(Team.id, Team.name, Membership.role)
        .join(Membership, Membership.team_id == Team.id)
        .where(Membership.user_id == user.id)
        .order_by(Team.name)
    )
    return [
        TeamMembershipResponse(team_id=team_id, team_name=name, role=role)
        for team_id, name, role in rows
    ]
