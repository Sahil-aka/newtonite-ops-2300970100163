from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ActivityEvent, User, WorkItem
from app.routers.work_items import assign_work_item, claim_work_item, get_accessible_item, transition_work_item, update_work_item
from app.schemas import WorkItemAssign, WorkItemTransition, WorkItemUpdate
from tests.conftest import Scenario


def test_only_one_concurrent_claim_succeeds(scenario: Scenario) -> None:
    barrier = Barrier(2)

    def try_claim(user_id):
        with Session(scenario.engine) as db:
            user = db.get(User, user_id)
            barrier.wait(timeout=10)
            try:
                claim_work_item(scenario.item_id, db, user)
                return 200
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(try_claim, [scenario.member_id, scenario.lead_id]))

    assert sorted(results) == [200, 409]
    with Session(scenario.engine) as db:
        item = db.get(WorkItem, scenario.item_id)
        events = list(
            db.scalars(select(ActivityEvent).where(ActivityEvent.item_id == scenario.item_id))
        )
        assert item.assignee_id in {scenario.member_id, scenario.lead_id}
        assert item.version == 2
        assert len(events) == 1
        assert events[0].event_type == "claimed"


def test_stale_edit_is_rejected_and_first_change_is_kept(scenario: Scenario) -> None:
    with Session(scenario.engine) as db:
        member = db.get(User, scenario.member_id)
        first = update_work_item(
            scenario.item_id,
            WorkItemUpdate(expected_version=1, title="First update"),
            db,
            member,
        )
    assert first.version == 2

    with Session(scenario.engine) as db:
        member = db.get(User, scenario.member_id)
        with pytest.raises(HTTPException) as error:
            update_work_item(
                scenario.item_id,
                WorkItemUpdate(expected_version=1, title="Stale update"),
                db,
                member,
            )
        assert error.value.status_code == 409

    with Session(scenario.engine) as db:
        item = db.get(WorkItem, scenario.item_id)
        events = list(db.scalars(select(ActivityEvent).where(ActivityEvent.item_id == scenario.item_id)))
        assert item.title == "First update"
        assert item.version == 2
        assert len(events) == 1
        assert events[0].event_type == "updated"


def test_only_lead_can_approve_and_transition_is_recorded(scenario: Scenario) -> None:
    with Session(scenario.engine) as db:
        item = db.get(WorkItem, scenario.item_id)
        item.status = "awaiting_approval"
        item.version = 4
        db.commit()

    with Session(scenario.engine) as db:
        member = db.get(User, scenario.member_id)
        with pytest.raises(HTTPException) as error:
            transition_work_item(
                scenario.item_id,
                WorkItemTransition(expected_version=4, target_status="resolved"),
                db,
                member,
            )
        assert error.value.status_code == 403

    with Session(scenario.engine) as db:
        lead = db.get(User, scenario.lead_id)
        result = transition_work_item(
            scenario.item_id,
            WorkItemTransition(expected_version=4, target_status="resolved"),
            db,
            lead,
        )
        assert result.status == "resolved"
        assert result.version == 5

    with Session(scenario.engine) as db:
        event = db.scalar(select(ActivityEvent).where(ActivityEvent.item_id == scenario.item_id))
        assert event.event_type == "transitioned"
        assert event.old_value == {"status": "awaiting_approval"}
        assert event.new_value == {"status": "resolved"}


def test_user_from_another_team_cannot_read_item(scenario: Scenario) -> None:
    with Session(scenario.engine) as db:
        with pytest.raises(HTTPException) as error:
            get_accessible_item(db, scenario.item_id, scenario.outsider_id)
    assert error.value.status_code == 404


def test_invalid_workflow_jump_is_rejected(scenario: Scenario) -> None:
    with Session(scenario.engine) as db:
        member = db.get(User, scenario.member_id)
        with pytest.raises(HTTPException) as error:
            transition_work_item(
                scenario.item_id,
                WorkItemTransition(expected_version=1, target_status="closed"),
                db,
                member,
            )
    assert error.value.status_code == 422


def test_team_lead_can_assign_item_to_teammate_and_record_history(scenario: Scenario) -> None:
    with Session(scenario.engine) as db:
        lead = db.get(User, scenario.lead_id)
        result = assign_work_item(
            scenario.item_id,
            WorkItemAssign(expected_version=1, assignee_id=scenario.member_id),
            db,
            lead,
        )
        assert result.assignee_id == scenario.member_id
        assert result.version == 2

    with Session(scenario.engine) as db:
        event = db.scalar(select(ActivityEvent).where(ActivityEvent.item_id == scenario.item_id))
        assert event.event_type == "assigned"
        assert event.old_value == {"assignee_id": None}
        assert event.new_value == {"assignee_id": str(scenario.member_id)}


def test_cannot_assign_item_to_user_outside_its_team(scenario: Scenario) -> None:
    with Session(scenario.engine) as db:
        lead = db.get(User, scenario.lead_id)
        with pytest.raises(HTTPException) as error:
            assign_work_item(
                scenario.item_id,
                WorkItemAssign(expected_version=1, assignee_id=scenario.outsider_id),
                db,
                lead,
            )
    assert error.value.status_code == 422
