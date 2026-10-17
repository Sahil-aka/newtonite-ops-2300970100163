from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models import Membership, Team, User
from app.schemas import TeamMemberResponse, TeamMembershipResponse

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


@router.get("/{team_id}/members", response_model=list[TeamMemberResponse])
def list_team_members(
    team_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TeamMemberResponse]:
    if db.get(Membership, (user.id, team_id)) is None:
        raise HTTPException(status_code=404, detail="Team not found")
    rows = db.execute(
        select(User.id, User.display_name, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.team_id == team_id, User.is_active.is_(True))
        .order_by(User.display_name)
    )
    return [
        TeamMemberResponse(id=user_id, display_name=display_name, role=role)
        for user_id, display_name, role in rows
    ]
