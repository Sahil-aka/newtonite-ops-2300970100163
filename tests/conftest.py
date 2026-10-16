from dataclasses import dataclass
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from app.models import ActivityEvent, Base, Membership, Team, User, WorkItem


@pytest.fixture(scope="session")
def test_engine() -> Engine:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.fail("Set TEST_DATABASE_URL to a disposable PostgreSQL database named newtonite_test.")
    if make_url(database_url).database != "newtonite_test":
        pytest.fail("Tests only run against a database named newtonite_test to protect development data.")

    parsed_url = make_url(database_url)
    admin_engine = create_engine(parsed_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": "newtonite_test"},
            ).scalar_one_or_none()
            if not exists:
                connection.exec_driver_sql('CREATE DATABASE "newtonite_test"')
    finally:
        admin_engine.dispose()

    engine = create_engine(database_url, pool_pre_ping=True)
    schema_ready = False
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        schema_ready = True
        yield engine
    finally:
        if schema_ready:
            Base.metadata.drop_all(engine)
        engine.dispose()


@dataclass(frozen=True)
class Scenario:
    engine: Engine
    team_id: UUID
    other_team_id: UUID
    item_id: UUID
    member_id: UUID
    lead_id: UUID
    outsider_id: UUID


@pytest.fixture
def scenario(test_engine: Engine):
    suffix = uuid4().hex
    team_id = uuid4()
    other_team_id = uuid4()
    member_id = uuid4()
    lead_id = uuid4()
    outsider_id = uuid4()
    item_id = uuid4()
    team = Team(id=team_id, name=f"Test team {suffix}")
    other_team = Team(id=other_team_id, name=f"Other team {suffix}")
    member = User(
        id=member_id,
        email=f"member-{suffix}@test.local",
        display_name="Test Member",
        password_hash="not-used-by-these-tests",
    )
    lead = User(
        id=lead_id,
        email=f"lead-{suffix}@test.local",
        display_name="Test Lead",
        password_hash="not-used-by-these-tests",
    )
    outsider = User(
        id=outsider_id,
        email=f"outsider-{suffix}@test.local",
        display_name="Other Team User",
        password_hash="not-used-by-these-tests",
    )
    item = WorkItem(
        id=item_id,
        team_id=team_id,
        title="Test work item",
        description="For behavior tests",
        item_type="task",
        priority="normal",
        status="open",
        assignee_id=None,
        created_by_id=member_id,
        version=1,
    )
    with Session(test_engine) as db:
        db.add_all([team, other_team, member, lead, outsider])
        db.flush()
        db.add_all(
            [
                Membership(user_id=member_id, team_id=team_id, role="member"),
                Membership(user_id=lead_id, team_id=team_id, role="lead"),
                Membership(user_id=outsider_id, team_id=other_team_id, role="member"),
                item,
            ]
        )
        db.commit()

    result = Scenario(
        engine=test_engine,
        team_id=team_id,
        other_team_id=other_team_id,
        item_id=item_id,
        member_id=member_id,
        lead_id=lead_id,
        outsider_id=outsider_id,
    )
    yield result

    with Session(test_engine) as db:
        db.execute(delete(ActivityEvent).where(ActivityEvent.item_id == result.item_id))
        db.execute(delete(WorkItem).where(WorkItem.id == result.item_id))
        db.execute(delete(Membership).where(Membership.team_id.in_([result.team_id, result.other_team_id])))
        db.execute(delete(User).where(User.id.in_([result.member_id, result.lead_id, result.outsider_id])))
        db.execute(delete(Team).where(Team.id.in_([result.team_id, result.other_team_id])))
        db.commit()
