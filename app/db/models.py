from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ReleaseCalendarModel(Base):
    __tablename__ = "release_calendar"

    release_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    release_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    release_name: Mapped[str] = mapped_column(String(255), nullable=False)
    scheduled_time_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="scheduled", index=True)

    actual: Mapped["ReleaseActualModel | None"] = relationship(
        back_populates="release",
        cascade="all, delete-orphan",
        uselist=False,
    )


class ReleaseActualModel(Base):
    __tablename__ = "release_actuals"

    release_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("release_calendar.release_id", ondelete="CASCADE"), primary_key=True
    )
    actual_value_raw: Mapped[str] = mapped_column(Text, nullable=False)
    actual_value_num: Mapped[float | None] = mapped_column(Float, nullable=True)
    parsed_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    parsed_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    release: Mapped[ReleaseCalendarModel] = relationship(back_populates="actual")


class MarketCatalogModel(Base):
    __tablename__ = "market_catalog"

    market_ticker: Mapped[str] = mapped_column(String(64), primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="kalshi", index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle: Mapped[str | None] = mapped_column(Text, nullable=True)
    close_time_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", index=True)
    release_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    mapping_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    mapping_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class MarketSnapshotModel(Base):
    __tablename__ = "market_snapshots"
    __table_args__ = (
        UniqueConstraint("market_ticker", "captured_at_utc", name="uq_market_snapshots_ticker_captured"),
        Index("ix_market_snapshots_ticker_captured", "market_ticker", "captured_at_utc"),
    )

    snapshot_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_ticker: Mapped[str] = mapped_column(
        String(64), ForeignKey("market_catalog.market_ticker", ondelete="CASCADE"), nullable=False
    )
    captured_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    yes_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    yes_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    mid: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)


class SignalModel(Base):
    __tablename__ = "signals"
    __table_args__ = (
        Index("ix_signals_release_market_type", "release_id", "market_ticker", "signal_type"),
    )

    signal_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    release_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("release_calendar.release_id", ondelete="CASCADE"), nullable=False, index=True
    )
    market_ticker: Mapped[str] = mapped_column(
        String(64), ForeignKey("market_catalog.market_ticker", ondelete="CASCADE"), nullable=False, index=True
    )
    signal_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    reason_codes_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    emitted_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class NotificationModel(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("signal_id", "channel", name="uq_notifications_signal_channel"),
        Index("ix_notifications_sent_at", "sent_at_utc"),
    )

    notification_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    signal_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("signals.signal_id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    sent_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delivery_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class EvaluationResultModel(Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (
        UniqueConstraint("signal_id", "horizon_sec", name="uq_evaluation_signal_horizon"),
    )

    evaluation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("signals.signal_id", ondelete="CASCADE"), nullable=False, index=True
    )
    horizon_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    move_after_horizon: Mapped[float] = mapped_column(Float, nullable=False)
    success_bool: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evaluated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class MonitorEventModel(Base):
    __tablename__ = "monitor_events"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_monitor_events_dedupe_key"),
        Index("ix_monitor_events_status_severity_created", "status", "severity", "created_at_utc"),
        Index("ix_monitor_events_type_last_seen", "monitor_type", "last_seen_at_utc"),
    )

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    monitor_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    component: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    release_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    market_ticker: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    first_seen_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_seen_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    alert_sent_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
