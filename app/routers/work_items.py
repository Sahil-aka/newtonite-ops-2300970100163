import base64
import binascii
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user, require_team_roles
from app.models import ActivityEvent, Membership, User, WorkItem
from app.schemas import (
    ActivityEventResponse,
    Priority,
    Status,
    WorkItemCreate,
    WorkItemDetailResponse,
    WorkItemPage,
    WorkItemResponse,
)

router = APIRouter(tags=["work items"])


def encode_cursor(item: WorkItem) -> str:
    raw = f"{item.updated_at.isoformat()}|{item.id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(value: str) -> tuple[datetime, UUID]:
    try:
        padded = value + "=" * (-len(value) % 4)
        updated_at_text, item_id_text = base64.urlsafe_b64decode(padded).decode("utf-8").rsplit("|", 1)
        updated_at = datetime.fromisoformat(updated_at_text)
        if updated_at.tzinfo is None:
            raise ValueError("Cursor timestamp must include a timezone")
        return updated_at, UUID(item_id_text)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise HTTPException(status_code=422, detail="Invalid pagination cursor")


@router.post(
    "/teams/{team_id}/items",
    response_model=WorkItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_work_item(
    team_id: UUID,
    payload: WorkItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _membership: Membership = Depends(require_team_roles("member", "lead", "admin")),
) -> WorkItemResponse:
    item = WorkItem(
        team_id=team_id,
        title=payload.title,
        description=payload.description,
        item_type=payload.item_type,
        priority=payload.priority,
        status="open",
        assignee_id=None,
        created_by_id=user.id,
        due_at=payload.due_at,
        version=1,
    )
    db.add(item)
    db.flush()
    db.add(
        ActivityEvent(
            item_id=item.id,
            actor_id=user.id,
            event_type="created",
            new_value={
                "title": item.title,
                "item_type": item.item_type,
                "priority": item.priority,
                "status": item.status,
            },
        )
    )
    db.commit()
    db.refresh(item)
    return item


@router.get("/items", response_model=WorkItemPage)
def list_work_items(
    team_id: UUID | None = None,
    status_filter: Status | None = Query(default=None, alias="status"),
    priority: Priority | None = None,
    assignee_id: UUID | None = None,
    q: str | None = Query(default=None, min_length=1, max_length=100),
    cursor: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkItemPage:
    if team_id is not None and db.get(Membership, (user.id, team_id)) is None:
        raise HTTPException(status_code=404, detail="Team not found")
    statement = (
        select(WorkItem)
        .join(Membership, Membership.team_id == WorkItem.team_id)
        .where(Membership.user_id == user.id)
    )
    if team_id is not None:
        statement = statement.where(WorkItem.team_id == team_id)
    if status_filter is not None:
        statement = statement.where(WorkItem.status == status_filter)
    if priority is not None:
        statement = statement.where(WorkItem.priority == priority)
    if assignee_id is not None:
        statement = statement.where(WorkItem.assignee_id == assignee_id)
    if q and q.strip():
        search = f"%{q.strip()}%"
        statement = statement.where(WorkItem.title.ilike(search) | WorkItem.description.ilike(search))
    if cursor:
        cursor_updated_at, cursor_item_id = decode_cursor(cursor)
        statement = statement.where(
            tuple_(WorkItem.updated_at, WorkItem.id) < tuple_(cursor_updated_at, cursor_item_id)
        )

    statement = statement.order_by(WorkItem.updated_at.desc(), WorkItem.id.desc())
    rows = list(db.scalars(statement.limit(limit + 1)))
    has_more = len(rows) > limit
    items = rows[:limit]
    return WorkItemPage(
        items=items,
        next_cursor=encode_cursor(items[-1]) if has_more and items else None,
        limit=limit,
    )


def get_accessible_item(db: Session, item_id: UUID, user_id: UUID) -> WorkItem:
    item = db.scalar(
        select(WorkItem)
        .join(Membership, Membership.team_id == WorkItem.team_id)
        .where(WorkItem.id == item_id, Membership.user_id == user_id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Work item not found")
    return item


@router.get("/items/{item_id}", response_model=WorkItemDetailResponse)
def read_work_item(
    item_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkItemDetailResponse:
    item = get_accessible_item(db, item_id, user.id)
    activity_rows = db.scalars(
        select(ActivityEvent)
        .where(ActivityEvent.item_id == item.id)
        .order_by(ActivityEvent.id.desc())
        .limit(50)
    )
    return WorkItemDetailResponse(
        **WorkItemResponse.model_validate(item).model_dump(),
        activity=[ActivityEventResponse.model_validate(event) for event in activity_rows],
    )
