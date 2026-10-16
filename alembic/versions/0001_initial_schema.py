"""Create the initial Newtonite operations schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "teams",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "memberships",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('viewer', 'member', 'lead', 'admin')", name="ck_memberships_role"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "team_id"),
    )

    op.create_table(
        "work_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("item_type", sa.String(length=30), nullable=False),
        sa.Column("priority", sa.String(length=20), server_default="normal", nullable=False),
        sa.Column("status", sa.String(length=30), server_default="open", nullable=False),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "item_type IN ('incident', 'customer_issue', 'payment', 'compliance', 'task')",
            name="ck_work_items_type",
        ),
        sa.CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name="ck_work_items_priority"),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'awaiting_approval', 'resolved', 'closed')",
            name="ck_work_items_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_work_items_version_positive"),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_work_items_team_status_updated", "work_items", ["team_id", "status", "updated_at", "id"])
    op.create_index(
        "ix_work_items_team_assignee_updated", "work_items", ["team_id", "assignee_id", "updated_at", "id"]
    )
    op.create_index("ix_work_items_team_priority_created", "work_items", ["team_id", "priority", "created_at"])

    op.create_table(
        "activity_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["item_id"], ["work_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_activity_events_item_id_id", "activity_events", ["item_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_activity_events_item_id_id", table_name="activity_events")
    op.drop_table("activity_events")
    op.drop_index("ix_work_items_team_priority_created", table_name="work_items")
    op.drop_index("ix_work_items_team_assignee_updated", table_name="work_items")
    op.drop_index("ix_work_items_team_status_updated", table_name="work_items")
    op.drop_table("work_items")
    op.drop_table("memberships")
    op.drop_table("teams")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
