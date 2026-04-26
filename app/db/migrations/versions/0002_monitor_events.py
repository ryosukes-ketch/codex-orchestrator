"""add monitor events

Revision ID: 0002_monitor_events
Revises: 0001_initial
Create Date: 2026-04-16 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0002_monitor_events"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monitor_events",
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("monitor_type", sa.String(length=64), nullable=False),
        sa.Column("component", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("release_id", sa.String(length=128), nullable=True),
        sa.Column("market_ticker", sa.String(length=64), nullable=True),
        sa.Column("details_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("first_seen_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("alert_sent_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("dedupe_key", name="uq_monitor_events_dedupe_key"),
    )
    op.create_index(op.f("ix_monitor_events_component"), "monitor_events", ["component"], unique=False)
    op.create_index(op.f("ix_monitor_events_created_at_utc"), "monitor_events", ["created_at_utc"], unique=False)
    op.create_index(op.f("ix_monitor_events_first_seen_at_utc"), "monitor_events", ["first_seen_at_utc"], unique=False)
    op.create_index(op.f("ix_monitor_events_last_seen_at_utc"), "monitor_events", ["last_seen_at_utc"], unique=False)
    op.create_index(op.f("ix_monitor_events_market_ticker"), "monitor_events", ["market_ticker"], unique=False)
    op.create_index(op.f("ix_monitor_events_monitor_type"), "monitor_events", ["monitor_type"], unique=False)
    op.create_index(op.f("ix_monitor_events_release_id"), "monitor_events", ["release_id"], unique=False)
    op.create_index("ix_monitor_events_status_severity_created", "monitor_events", ["status", "severity", "created_at_utc"], unique=False)
    op.create_index(op.f("ix_monitor_events_status"), "monitor_events", ["status"], unique=False)
    op.create_index(op.f("ix_monitor_events_severity"), "monitor_events", ["severity"], unique=False)
    op.create_index("ix_monitor_events_type_last_seen", "monitor_events", ["monitor_type", "last_seen_at_utc"], unique=False)
    op.create_index(op.f("ix_monitor_events_updated_at_utc"), "monitor_events", ["updated_at_utc"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_monitor_events_updated_at_utc"), table_name="monitor_events")
    op.drop_index("ix_monitor_events_type_last_seen", table_name="monitor_events")
    op.drop_index(op.f("ix_monitor_events_severity"), table_name="monitor_events")
    op.drop_index(op.f("ix_monitor_events_status"), table_name="monitor_events")
    op.drop_index("ix_monitor_events_status_severity_created", table_name="monitor_events")
    op.drop_index(op.f("ix_monitor_events_release_id"), table_name="monitor_events")
    op.drop_index(op.f("ix_monitor_events_monitor_type"), table_name="monitor_events")
    op.drop_index(op.f("ix_monitor_events_market_ticker"), table_name="monitor_events")
    op.drop_index(op.f("ix_monitor_events_last_seen_at_utc"), table_name="monitor_events")
    op.drop_index(op.f("ix_monitor_events_first_seen_at_utc"), table_name="monitor_events")
    op.drop_index(op.f("ix_monitor_events_created_at_utc"), table_name="monitor_events")
    op.drop_index(op.f("ix_monitor_events_component"), table_name="monitor_events")
    op.drop_table("monitor_events")
