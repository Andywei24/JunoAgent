"""Initial schema: users, sessions, tasks, task_steps, events, approvals, tools, memories.

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-21
"""

from __future__ import annotations

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
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(320), unique=True),
        sa.Column("display_name", sa.String(200)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "tools",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(120), unique=True, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("capability_type", sa.String(40), nullable=False),
        sa.Column("backend_type", sa.String(40), nullable=False),
        sa.Column(
            "input_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "output_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("risk_level", sa.String(20), nullable=False, server_default="low"),
        sa.Column(
            "required_permissions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("timeout_seconds", sa.Integer, nullable=False, server_default="30"),
        sa.Column(
            "retry_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "cost_model",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("version", sa.String(20), nullable=False, server_default="1"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.CheckConstraint("timeout_seconds > 0", name="tools_timeout_positive"),
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.String(64),
            sa.ForeignKey("sessions.id", ondelete="SET NULL"),
        ),
        sa.Column("goal", sa.Text, nullable=False),
        sa.Column("parsed_goal", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("risk_level", sa.String(20), nullable=False, server_default="low"),
        sa.Column(
            "budget_limit",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "budget_used",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("final_output", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("failure_reason", sa.Text),
    )
    op.create_index("ix_tasks_user_id", "tasks", ["user_id"])
    op.create_index("ix_tasks_session_id", "tasks", ["session_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])

    op.create_table(
        "task_steps",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(64),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_step_id",
            sa.String(64),
            sa.ForeignKey("task_steps.id", ondelete="CASCADE"),
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("sequence_order", sa.Integer, nullable=False),
        sa.Column(
            "dependencies",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("assigned_agent_id", sa.String(64)),
        sa.Column("required_capability", sa.String(80)),
        sa.Column(
            "selected_tool_id",
            sa.String(64),
            sa.ForeignKey("tools.id", ondelete="SET NULL"),
        ),
        sa.Column("risk_level", sa.String(20), nullable=False, server_default="low"),
        sa.Column(
            "approval_required", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column("input_payload", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("output_payload", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("error", sa.Text),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_task_steps_task_id", "task_steps", ["task_id"])
    op.create_index("ix_task_steps_parent_step_id", "task_steps", ["parent_step_id"])
    op.create_index("ix_task_steps_status", "task_steps", ["status"])
    op.create_index("ix_task_steps_task_order", "task_steps", ["task_id", "sequence_order"])

    op.create_table(
        "events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "sequence",
            sa.BigInteger,
            sa.Identity(always=False, start=1),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "task_id",
            sa.String(64),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "step_id",
            sa.String(64),
            sa.ForeignKey("task_steps.id", ondelete="CASCADE"),
        ),
        sa.Column("agent_id", sa.String(64)),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("actor_type", sa.String(20)),
        sa.Column("actor_id", sa.String(64)),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("trace_id", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_events_task_id", "events", ["task_id"])
    op.create_index("ix_events_step_id", "events", ["step_id"])
    op.create_index("ix_events_event_type", "events", ["event_type"])
    op.create_index("ix_events_correlation_id", "events", ["correlation_id"])
    op.create_index("ix_events_trace_id", "events", ["trace_id"])
    op.create_index("ix_events_task_seq", "events", ["task_id", "sequence"])
    op.create_index("ix_events_task_created", "events", ["task_id", "created_at"])

    # Append-only: reject UPDATE and DELETE on the events table.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION events_reject_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'events table is append-only (op=%)', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER events_no_update
        BEFORE UPDATE ON events
        FOR EACH ROW EXECUTE FUNCTION events_reject_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER events_no_delete
        BEFORE DELETE ON events
        FOR EACH ROW EXECUTE FUNCTION events_reject_mutation();
        """
    )

    op.create_table(
        "approvals",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(64),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "step_id",
            sa.String(64),
            sa.ForeignKey("task_steps.id", ondelete="CASCADE"),
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("requested_action", sa.Text, nullable=False),
        sa.Column("risk_level", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column(
            "data_involved",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("requested_by", sa.String(64)),
        sa.Column("approved_by", sa.String(64)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_approvals_task_id", "approvals", ["task_id"])
    op.create_index("ix_approvals_step_id", "approvals", ["step_id"])
    op.create_index("ix_approvals_status", "approvals", ["status"])

    op.create_table(
        "memories",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            sa.String(64),
            sa.ForeignKey("tasks.id", ondelete="SET NULL"),
        ),
        sa.Column("memory_type", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("summary", sa.Text),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("embedding_ref", sa.String(200)),
        sa.Column("importance", sa.Float, nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_memories_user_id", "memories", ["user_id"])
    op.create_index("ix_memories_task_id", "memories", ["task_id"])
    op.create_index("ix_memories_memory_type", "memories", ["memory_type"])


def downgrade() -> None:
    op.drop_table("memories")
    op.drop_table("approvals")

    op.execute("DROP TRIGGER IF EXISTS events_no_delete ON events;")
    op.execute("DROP TRIGGER IF EXISTS events_no_update ON events;")
    op.execute("DROP FUNCTION IF EXISTS events_reject_mutation();")
    op.drop_table("events")

    op.drop_table("task_steps")
    op.drop_table("tasks")
    op.drop_table("tools")
    op.drop_table("sessions")
    op.drop_table("users")
