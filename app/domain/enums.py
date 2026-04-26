from __future__ import annotations

from enum import Enum


class ReleaseType(str, Enum):
    FOMC = "FOMC"
    CPI = "CPI"
    NFP = "NFP"
    GDP_ADVANCE = "GDP_ADVANCE"


class ReleaseStatus(str, Enum):
    SCHEDULED = "scheduled"
    RELEASED = "released"
    UNKNOWN = "unknown"


class MarketStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    SETTLED = "settled"
    UNKNOWN = "unknown"


class Platform(str, Enum):
    KALSHI = "kalshi"


class SignalType(str, Enum):
    PRE_RELEASE_PRESSURE = "PRE_RELEASE_PRESSURE"
    RELEASE_SHOCK = "RELEASE_SHOCK"
    DELAYED_REPRICING = "DELAYED_REPRICING"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class NotificationChannel(str, Enum):
    TELEGRAM = "telegram"


class DeliveryStatus(str, Enum):
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class DecisionClassification(str, Enum):
    HOLD = "HOLD"
    HIKE = "HIKE"
    CUT = "CUT"


class ActualDirection(str, Enum):
    HOTTER_THAN_EXPECTED = "HOTTER_THAN_EXPECTED"
    COOLER_THAN_EXPECTED = "COOLER_THAN_EXPECTED"
    STRONGER_THAN_EXPECTED = "STRONGER_THAN_EXPECTED"
    WEAKER_THAN_EXPECTED = "WEAKER_THAN_EXPECTED"
    HAWKISH = "HAWKISH"
    DOVISH = "DOVISH"
    NEUTRAL_OR_HOLD = "NEUTRAL_OR_HOLD"


class MonitorType(str, Enum):
    LIVE_CYCLE_STALLED = "LIVE_CYCLE_STALLED"
    UPCOMING_RELEASES_EMPTY = "UPCOMING_RELEASES_EMPTY"
    ACTUAL_MISSING_AFTER_RELEASE = "ACTUAL_MISSING_AFTER_RELEASE"
    ACTUAL_PARSE_ERROR_BURST = "ACTUAL_PARSE_ERROR_BURST"
    MARKET_DISCOVERY_EMPTY = "MARKET_DISCOVERY_EMPTY"
    SNAPSHOT_COLLECTION_STALLED = "SNAPSHOT_COLLECTION_STALLED"
    NO_SIGNALS_AFTER_RELEASE = "NO_SIGNALS_AFTER_RELEASE"
    SIGNAL_BURST = "SIGNAL_BURST"
    NOTIFICATION_FAILURE_BURST = "NOTIFICATION_FAILURE_BURST"
    HEALTHCHECK_FAILURE = "HEALTHCHECK_FAILURE"


class MonitorSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class MonitorStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"
