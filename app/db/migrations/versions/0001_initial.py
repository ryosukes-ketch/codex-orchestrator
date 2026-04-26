"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-15 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "release_calendar",
        sa.Column("release_id", sa.String(length=128), nullable=False),
        sa.Column("release_type", sa.String(length=32), nullable=False),
        sa.Column("release_name", sa.String(length=255), nullable=False),
        sa.Column("scheduled_time_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("release_id"),
    )
    op.create_index(op.f("ix_release_calendar_release_type"), "release_calendar", ["release_type"], unique=False)
    op.create_index(
        op.f("ix_release_calendar_scheduled_time_utc"),
        "release_calendar",
        ["scheduled_time_utc"],
        unique=False,
    )
    op.create_index(op.f("ix_release_calendar_status"), "release_calendar", ["status"], unique=False)

    op.create_table(
        "release_actuals",
        sa.Column("release_id", sa.String(length=128), nullable=False),
        sa.Column("actual_value_raw", sa.Text(), nullable=False),
        sa.Column("actual_value_num", sa.Float(), nullable=True),
        sa.Column("parsed_payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("parsed_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["release_id"], ["release_calendar.release_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("release_id"),
    )
    op.create_index(op.f("ix_release_actuals_parsed_at_utc"), "release_actuals", ["parsed_at_utc"], unique=False)

    op.create_table(
        "market_catalog",
        sa.Column("market_ticker", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("subtitle", sa.String(length=512), nullable=True),
        sa.Column("close_time_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("release_type", sa.String(length=32), nullable=True),
        sa.Column("mapping_confidence", sa.Float(), nullable=False),
        sa.Column("mapping_payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("market_ticker"),
    )
    op.create_index(op.f("ix_market_catalog_close_time_utc"), "market_catalog", ["close_time_utc"], unique=False)
    op.create_index(op.f("ix_market_catalog_platform"), "market_catalog", ["platform"], unique=False)
    op.create_index(op.f("ix_market_catalog_release_type"), "market_catalog", ["release_type"], unique=False)
    op.create_index(op.f("ix_market_catalog_status"), "market_catalog", ["status"], unique=False)

    op.create_table(
        "market_snapshots",
        sa.Column("snapshot_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("market_ticker", sa.String(length=64), nullable=False),
        sa.Column("captured_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("yes_bid", sa.Float(), nullable=True),
        sa.Column("yes_ask", sa.Float(), nullable=True),
        sa.Column("mid", sa.Float(), nullable=True),
        sa.Column("spread", sa.Float(), nullable=True),
        sa.Column("last_price", sa.Float(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["market_ticker"], ["market_catalog.market_ticker"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("snapshot_id"),
        sa.UniqueConstraint("market_ticker", "captured_at_utc", name="uq_market_snapshots_ticker_captured"),
    )
    op.create_index(op.f("ix_market_snapshots_captured_at_utc"), "market_snapshots", ["captured_at_utc"], unique=False)
    op.create_index("ix_market_snapshots_ticker_captured", "market_snapshots", ["market_ticker", "captured_at_utc"], unique=False)

    op.create_table(
        "signals",
        sa.Column("signal_id", sa.String(length=128), nullable=False),
        sa.Column("release_id", sa.String(length=128), nullable=False),
        sa.Column("market_ticker", sa.String(length=64), nullable=False),
        sa.Column("signal_type", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("reason_codes_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metrics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("emitted_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["market_ticker"], ["market_catalog.market_ticker"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["release_id"], ["release_calendar.release_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("signal_id"),
    )
    op.create_index(op.f("ix_signals_emitted_at_utc"), "signals", ["emitted_at_utc"], unique=False)
    op.create_index(op.f("ix_signals_market_ticker"), "signals", ["market_ticker"], unique=False)
    op.create_index(op.f("ix_signals_release_id"), "signals", ["release_id"], unique=False)
    op.create_index("ix_signals_release_market_type", "signals", ["release_id", "market_ticker", "signal_type"], unique=False)
    op.create_index(op.f("ix_signals_severity"), "signals", ["severity"], unique=False)
    op.create_index(op.f("ix_signals_signal_type"), "signals", ["signal_type"], unique=False)

    op.create_table(
        "notifications",
        sa.Column("notification_id", sa.String(length=128), nullable=False),
        sa.Column("signal_id", sa.String(length=128), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("sent_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivery_status", sa.String(length=32), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.signal_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("notification_id"),
        sa.UniqueConstraint("signal_id", "channel", name="uq_notifications_signal_channel"),
    )
    op.create_index(op.f("ix_notifications_channel"), "notifications", ["channel"], unique=False)
    op.create_index(op.f("ix_notifications_delivery_status"), "notifications", ["delivery_status"], unique=False)
    op.create_index("ix_notifications_sent_at", "notifications", ["sent_at_utc"], unique=False)
    op.create_index(op.f("ix_notifications_signal_id"), "notifications", ["signal_id"], unique=False)

    op.create_table(
        "evaluation_results",
        sa.Column("evaluation_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("signal_id", sa.String(length=128), nullable=False),
        sa.Column("horizon_sec", sa.Integer(), nullable=False),
        sa.Column("move_after_horizon", sa.Float(), nullable=False),
        sa.Column("success_bool", sa.Boolean(), nullable=False),
        sa.Column("evaluated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.signal_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("evaluation_id"),
        sa.UniqueConstraint("signal_id", "horizon_sec", name="uq_evaluation_signal_horizon"),
    )
    op.create_index(op.f("ix_evaluation_results_evaluated_at_utc"), "evaluation_results", ["evaluated_at_utc"], unique=False)
    op.create_index(op.f("ix_evaluation_results_signal_id"), "evaluation_results", ["signal_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_evaluation_results_signal_id"), table_name="evaluation_results")
    op.drop_index(op.f("ix_evaluation_results_evaluated_at_utc"), table_name="evaluation_results")
    op.drop_table("evaluation_results")

    op.drop_index(op.f("ix_notifications_signal_id"), table_name="notifications")
    op.drop_index("ix_notifications_sent_at", table_name="notifications")
    op.drop_index(op.f("ix_notifications_delivery_status"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_channel"), table_name="notifications")
    op.drop_table("notifications")

    op.drop_index(op.f("ix_signals_signal_type"), table_name="signals")
    op.drop_index(op.f("ix_signals_severity"), table_name="signals")
    op.drop_index("ix_signals_release_market_type", table_name="signals")
    op.drop_index(op.f("ix_signals_release_id"), table_name="signals")
    op.drop_index(op.f("ix_signals_market_ticker"), table_name="signals")
    op.drop_index(op.f("ix_signals_emitted_at_utc"), table_name="signals")
    op.drop_table("signals")

    op.drop_index("ix_market_snapshots_ticker_captured", table_name="market_snapshots")
    op.drop_index(op.f("ix_market_snapshots_captured_at_utc"), table_name="market_snapshots")
    op.drop_table("market_snapshots")

    op.drop_index(op.f("ix_market_catalog_status"), table_name="market_catalog")
    op.drop_index(op.f("ix_market_catalog_release_type"), table_name="market_catalog")
    op.drop_index(op.f("ix_market_catalog_platform"), table_name="market_catalog")
    op.drop_index(op.f("ix_market_catalog_close_time_utc"), table_name="market_catalog")
    op.drop_table("market_catalog")

    op.drop_index(op.f("ix_release_actuals_parsed_at_utc"), table_name="release_actuals")
    op.drop_table("release_actuals")

    op.drop_index(op.f("ix_release_calendar_status"), table_name="release_calendar")
    op.drop_index(op.f("ix_release_calendar_scheduled_time_utc"), table_name="release_calendar")
    op.drop_index(op.f("ix_release_calendar_release_type"), table_name="release_calendar")
    op.drop_table("release_calendar")
