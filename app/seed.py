"""Create repeatable local demo users, teams, memberships, and work items.

Run after applying migrations with: python -m app.seed
The demo password is intentionally shared and must only be used for this demo app.
"""
import argparse
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from pwdlib import PasswordHash
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ActivityEvent, Membership, Team, User, WorkItem

DEMO_PASSWORD = "NewtoniteDemo2026!"
TEAM_NAMES = ("Operations", "Engineering", "Payments")
USERS = (
    ("admin.ops@newtonite.local", "Olivia Admin", "Operations", "admin"),
    ("lead.ops@newtonite.local", "Liam Operations Lead", "Operations", "lead"),
    ("member.ops@newtonite.local", "Maya Operations Member", "Operations", "member"),
    ("viewer.ops@newtonite.local", "Victor Operations Viewer", "Operations", "viewer"),
    ("lead.eng@newtonite.local", "Ethan Engineering Lead", "Engineering", "lead"),
    ("member.eng@newtonite.local", "Emma Engineering Member", "Engineering", "member"),
    ("member2.eng@newtonite.local", "Noah Engineering Member", "Engineering", "member"),
    ("lead.payments@newtonite.local", "Priya Payments Lead", "Payments", "lead"),
    ("member.payments@newtonite.local", "Parker Payments Member", "Payments", "member"),
    ("viewer.payments@newtonite.local", "Val Payments Viewer", "Payments", "viewer"),
)
ITEM_TYPES = ("incident", "customer_issue", "payment", "compliance", "task")
PRIORITIES = ("low", "normal", "high", "urgent")
STATUSES = ("open", "in_progress", "awaiting_approval", "resolved", "closed")
TITLES = (
    "Investigate delayed customer request",
    "Review payment reconciliation mismatch",
    "Check service alert and identify owner",
    "Prepare compliance evidence for review",
    "Follow up on account access issue",
    "Confirm operational handoff is complete",
)


def seed(sample_item_count: int) -> None:
    password_hasher = PasswordHash.recommended()
    password_hash = password_hasher.hash(DEMO_PASSWORD)

    with SessionLocal() as session, session.begin():
        teams = {
            name: session.scalar(select(Team).where(Team.name == name))
            for name in TEAM_NAMES
        }
        for name, team in teams.items():
            if team is None:
                team = Team(name=name)
                session.add(team)
                teams[name] = team
        session.flush()

        users_by_email: dict[str, User] = {}
        users_by_team: dict[str, list[tuple[User, str]]] = {name: [] for name in TEAM_NAMES}
        for email, display_name, team_name, role in USERS:
            user = session.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(email=email, display_name=display_name, password_hash=password_hash)
                session.add(user)
                session.flush()
            users_by_email[email] = user
            users_by_team[team_name].append((user, role))

            membership = session.get(Membership, (user.id, teams[team_name].id))
            if membership is None:
                session.add(Membership(user_id=user.id, team_id=teams[team_name].id, role=role))
            else:
                membership.role = role
        session.flush()

        item_specs = []
        for number in range(sample_item_count):
            team_name = TEAM_NAMES[number % len(TEAM_NAMES)]
            team_users = users_by_team[team_name]
            lead = next(user for user, role in team_users if role == "lead")
            member = next(user for user, role in team_users if role == "member")
            creator = member if number % 3 else lead
            assignee = member if number % 4 else None
            item_id = uuid5(NAMESPACE_URL, f"newtonite-demo-item-{number + 1}")
            item_specs.append((number, team_name, lead, creator, assignee, item_id))

        existing_ids = set(
            session.scalars(select(WorkItem.id).where(WorkItem.id.in_([spec[5] for spec in item_specs])))
        ) if item_specs else set()

        activity_events = []
        for number, team_name, _lead, creator, assignee, item_id in item_specs:
            if item_id in existing_ids:
                continue
            item_type = ITEM_TYPES[number % len(ITEM_TYPES)]
            priority = PRIORITIES[(number // 2) % len(PRIORITIES)]
            status = STATUSES[(number // 3) % len(STATUSES)]
            title = f"{TITLES[number % len(TITLES)]} #{number + 1}"
            item = WorkItem(
                id=item_id,
                team_id=teams[team_name].id,
                title=title,
                description=f"Demo work item {number + 1} for the {team_name} team.",
                item_type=item_type,
                priority=priority,
                status=status,
                assignee_id=assignee.id if assignee else None,
                created_by_id=creator.id,
                due_at=datetime.now(timezone.utc) + timedelta(days=(number % 14) - 3),
                version=1,
            )
            session.add(item)
            activity_events.append(
                ActivityEvent(
                    item_id=item_id,
                    actor_id=creator.id,
                    event_type="created",
                    new_value={"title": title, "status": status, "priority": priority},
                )
            )

        # Flush parent rows first; the events reference their work item IDs.
        session.flush()
        session.add_all(activity_events)

    print(f"Demo seed complete: {len(TEAM_NAMES)} teams, {len(USERS)} users, {sample_item_count} sample items requested.")
    print(f"Shared demo password: {DEMO_PASSWORD}")
    print("Demo accounts:")
    for email, _display_name, _team, role in USERS:
        print(f"  {email} ({role})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed repeatable Newtonite demo data.")
    parser.add_argument("--items", type=int, default=3000, help="Number of deterministic sample items (default: 3000).")
    arguments = parser.parse_args()
    if arguments.items < 0:
        parser.error("--items must be zero or greater")
    seed(arguments.items)
