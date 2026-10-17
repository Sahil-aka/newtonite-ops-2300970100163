import base64
import binascii
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, tuple_, update
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user, require_team_roles
from app.models import ActivityEvent, Membership, User, WorkItem
from app.schemas import (
    ActivityEventResponse,
    Priority,
    Status,
    WorkItemCreate,
    WorkItemAssign,
    WorkItemCommentCreate,
    WorkItemDetailResponse,
    WorkItemPage,
    WorkItemResponse,
    WorkItemTransition,
    WorkItemUpdate,
)

router = APIRouter(tags=["work items"])
EDIT_ROLES = ("member", "lead", "admin")
ALLOWED_TRANSITIONS = {
    "open": {"in_progress"},
    "in_progress": {"awaiting_approval"},
    "awaiting_approval": {"resolved"},
    "resolved": {"closed"},
    "closed": set(),
}


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
    unassigned: bool = False,
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
    if unassigned:
        statement = statement.where(WorkItem.assignee_id.is_(None))
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


def require_item_role(db: Session, item: WorkItem, user: User, allowed_roles: tuple[str, ...]) -> None:
    membership = db.get(Membership, (user.id, item.team_id))
    if membership is None:
        raise HTTPException(status_code=404, detail="Work item not found")
    if membership.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Your team role cannot perform this action")


@router.post("/items/{item_id}/assign", response_model=WorkItemResponse)
def assign_work_item(
    item_id: UUID,
    payload: WorkItemAssign,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkItemResponse:
    item = get_accessible_item(db, item_id, user.id)
    require_item_role(db, item, user, EDIT_ROLES)

    if payload.expected_version != item.version:
        raise HTTPException(status_code=409, detail="Work item changed; reload it before assigning")
    if payload.assignee_id is not None:
        target_membership = db.get(Membership, (payload.assignee_id, item.team_id))
        target_user = db.get(User, payload.assignee_id)
        if target_membership is None or target_user is None or not target_user.is_active:
            raise HTTPException(status_code=422, detail="Assignee must be an active member of this team")
    if item.assignee_id == payload.assignee_id:
        return item

    previous_assignee_id = item.assignee_id
    result = db.execute(
        update(WorkItem)
        .where(
            WorkItem.id == item.id,
            WorkItem.team_id == item.team_id,
            WorkItem.version == payload.expected_version,
        )
        .values(
            assignee_id=payload.assignee_id,
            version=WorkItem.version + 1,
            updated_at=func.now(),
        )
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Work item changed; reload it before assigning")

    db.add(
        ActivityEvent(
            item_id=item.id,
            actor_id=user.id,
            event_type="assigned",
            old_value={"assignee_id": str(previous_assignee_id) if previous_assignee_id else None},
            new_value={"assignee_id": str(payload.assignee_id) if payload.assignee_id else None},
        )
    )
    db.commit()
    db.refresh(item)
    return item


@router.post("/items/{item_id}/claim", response_model=WorkItemResponse)
def claim_work_item(
    item_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkItemResponse:
    item = get_accessible_item(db, item_id, user.id)
    require_item_role(db, item, user, EDIT_ROLES)

    result = db.execute(
        update(WorkItem)
        .where(WorkItem.id == item.id, WorkItem.team_id == item.team_id, WorkItem.assignee_id.is_(None))
        .values(
            assignee_id=user.id,
            version=WorkItem.version + 1,
            updated_at=func.now(),
        )
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="This item was already claimed; refresh and try again")

    db.add(
        ActivityEvent(
            item_id=item.id,
            actor_id=user.id,
            event_type="claimed",
            old_value={"assignee_id": None},
            new_value={"assignee_id": str(user.id)},
        )
    )
    db.commit()
    db.refresh(item)
    return item


@router.patch("/items/{item_id}", response_model=WorkItemResponse)
def update_work_item(
    item_id: UUID,
    payload: WorkItemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkItemResponse:
    item = get_accessible_item(db, item_id, user.id)
    require_item_role(db, item, user, EDIT_ROLES)

    changes = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
    old_values = {name: getattr(item, name) for name in changes}
    new_values = {
        name: value.isoformat() if hasattr(value, "isoformat") else value
        for name, value in changes.items()
    }
    result = db.execute(
        update(WorkItem)
        .where(WorkItem.id == item.id, WorkItem.version == payload.expected_version)
        .values(**changes, version=WorkItem.version + 1, updated_at=func.now())
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Work item changed; reload it before saving")

    db.add(
        ActivityEvent(
            item_id=item.id,
            actor_id=user.id,
            event_type="updated",
            old_value={
                name: value.isoformat() if hasattr(value, "isoformat") else value
                for name, value in old_values.items()
            },
            new_value=new_values,
        )
    )
    db.commit()
    db.refresh(item)
    return item


@router.post("/items/{item_id}/transition", response_model=WorkItemResponse)
def transition_work_item(
    item_id: UUID,
    payload: WorkItemTransition,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkItemResponse:
    item = get_accessible_item(db, item_id, user.id)
    require_item_role(db, item, user, EDIT_ROLES)

    if item.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Work item changed; reload it before continuing")
    if payload.target_status not in ALLOWED_TRANSITIONS[item.status]:
        raise HTTPException(
            status_code=422,
            detail=f"Transition from {item.status} to {payload.target_status} is not allowed",
        )
    if item.status == "awaiting_approval" and payload.target_status == "resolved":
        membership = db.get(Membership, (user.id, item.team_id))
        if membership is None or membership.role != "lead":
            raise HTTPException(status_code=403, detail="Only a team Lead can approve this item")

    previous_status = item.status
    result = db.execute(
        update(WorkItem)
        .where(
            WorkItem.id == item.id,
            WorkItem.version == payload.expected_version,
            WorkItem.status == previous_status,
        )
        .values(
            status=payload.target_status,
            version=WorkItem.version + 1,
            updated_at=func.now(),
        )
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Work item changed; reload it before continuing")

    db.add(
        ActivityEvent(
            item_id=item.id,
            actor_id=user.id,
            event_type="transitioned",
            old_value={"status": previous_status},
            new_value={"status": payload.target_status},
        )
    )
    db.commit()
    db.refresh(item)
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


@router.post("/items/{item_id}/comments", response_model=ActivityEventResponse, status_code=201)
def add_work_item_comment(
    item_id: UUID,
    payload: WorkItemCommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ActivityEventResponse:
    item = get_accessible_item(db, item_id, user.id)
    require_item_role(db, item, user, EDIT_ROLES)
    event = ActivityEvent(
        item_id=item.id,
        actor_id=user.id,
        event_type="commented",
        new_value={"comment": payload.comment},
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return ActivityEventResponse.model_validate(event)
