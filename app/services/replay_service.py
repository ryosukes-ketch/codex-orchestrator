from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import MarketRepository, ReleaseRepository, SignalRepository, SnapshotRepository
from app.domain.enums import ReleaseType
from app.domain.scoring_models import ScoringInput
from app.domain.types import ContractThreshold
from app.services.evaluation_service import EvaluationService
from app.services.notification_service import NotificationService
from app.services.scoring_engine import ScoringEngine
from app.services.signal_engine import SignalEngine
from app.utils.idempotency import stable_hash


class ReplayService:
    def __init__(
        self,
        signal_engine: SignalEngine,
        scoring_engine: ScoringEngine,
        evaluation_service: EvaluationService,
        notification_service: NotificationService | None = None,
    ) -> None:
        self.signal_engine = signal_engine
        self.scoring_engine = scoring_engine
        self.evaluation_service = evaluation_service
        self.notification_service = notification_service

    async def replay_release(
        self,
        session: AsyncSession,
        release_id: str,
        *,
        send_notifications: bool = False,
    ) -> dict[str, int]:
        release_repo = ReleaseRepository(session)
        market_repo = MarketRepository(session)
        snapshot_repo = SnapshotRepository(session)
        signal_repo = SignalRepository(session)

        release = await release_repo.get_by_id(release_id)
        if release is None:
            return {"signals_saved": 0, "signals_notified": 0}
        actual = await release_repo.get_actual(release_id)
        markets = sorted(
            await market_repo.list_for_release_type(release.release_type),
            key=lambda item: item.market_ticker,
        )
        markets = _filter_markets_for_release(markets, release_id=release_id)
        if not markets:
            return {"signals_saved": 0, "signals_notified": 0}

        start = release.scheduled_time_utc - timedelta(minutes=60)
        end = release.scheduled_time_utc + timedelta(seconds=600)
        snapshots_by_market: dict[str, list] = {}
        for market in markets:
            snapshots_by_market[market.market_ticker] = await snapshot_repo.list_snapshots(
                market.market_ticker, start, end
            )

        saved = 0
        notified = 0
        for market in markets:
            threshold = _threshold_from_mapping(market.mapping_payload_json)
            interpreted_direction_override = _manual_interpreted_direction(
                mapping_payload_json=market.mapping_payload_json,
                release_type=release.release_type,
                actual=actual,
            )
            drafts = self.signal_engine.detect_signals(
                release_id=release_id,
                release_time_utc=release.scheduled_time_utc,
                market_ticker=market.market_ticker,
                snapshots=snapshots_by_market.get(market.market_ticker, []),
                group_snapshots=snapshots_by_market,
                threshold=threshold,
                actual_value_num=actual.actual_value_num if actual else None,
                interpreted_direction_override=interpreted_direction_override,
            )
            for draft in drafts:
                scoring = self.scoring_engine.score(
                    ScoringInput(
                        price_gap=float(
                            max(
                                draft.metrics.get("gap_to_group_median", 0.0),
                                draft.metrics.get("change_120s", 0.0),
                                draft.metrics.get("change_60m", 0.0),
                            )
                        ),
                        speed_seconds=(draft.emitted_at_utc - release.scheduled_time_utc).total_seconds(),
                        spread=float(draft.metrics.get("spread", 0.2) or 0.2),
                        liquidity_depth=float(draft.metrics.get("volume_delta", 0.0) or 0.0),
                        confirmation_strength=1.0 if "confirmation" in ",".join(draft.reason_codes) else 0.7,
                        event_importance=_event_importance(release.release_type),
                    )
                )
                signal_id = stable_hash(
                    release_id,
                    draft.signal_type.value,
                    market.market_ticker,
                    str(int(draft.emitted_at_utc.timestamp())),
                )
                await signal_repo.upsert_signal(
                    signal_id=signal_id,
                    release_id=release_id,
                    market_ticker=market.market_ticker,
                    signal_type=draft.signal_type.value,
                    score=scoring.score,
                    severity=scoring.severity.value,
                    reason_codes_json=draft.reason_codes,
                    metrics_json=draft.metrics | scoring.components,
                    emitted_at_utc=draft.emitted_at_utc,
                )
                saved += 1
                if send_notifications and self.notification_service:
                    signal_record = await signal_repo.get_by_id(signal_id)
                    if signal_record and actual:
                        sent = await self.notification_service.maybe_send_signal_notification(
                            session=session,
                            signal=signal_record,
                            release=release,
                            market=market,
                            actual=actual,
                        )
                        notified += int(sent)
        await session.commit()
        await self.evaluation_service.evaluate_release(session, release_id)
        return {"signals_saved": saved, "signals_notified": notified}


def _threshold_from_mapping(mapping_payload_json: dict) -> ContractThreshold | None:
    threshold = mapping_payload_json.get("threshold")
    if not isinstance(threshold, dict):
        if not bool(mapping_payload_json.get("manual_seed")):
            return None
        comparator = mapping_payload_json.get("comparator")
        value = mapping_payload_json.get("value")
        if comparator not in {"above", "below"}:
            return None
        if value is None:
            return None
        return ContractThreshold(comparator=str(comparator), value=float(value), unit=mapping_payload_json.get("unit"))
    comparator = threshold.get("comparator")
    value = threshold.get("value")
    if comparator not in {"above", "below"}:
        return None
    if value is None:
        return None
    return ContractThreshold(comparator=str(comparator), value=float(value), unit=threshold.get("unit"))


def _event_importance(release_type: str) -> float:
    mapping = {
        ReleaseType.FOMC.value: 1.0,
        ReleaseType.CPI.value: 1.0,
        ReleaseType.NFP.value: 0.95,
        ReleaseType.GDP_ADVANCE.value: 0.8,
    }
    return mapping.get(release_type, 0.7)


def _filter_markets_for_release(markets: list[Any], *, release_id: str) -> list[Any]:
    filtered: list[Any] = []
    for market in markets:
        payload = market.mapping_payload_json if isinstance(market.mapping_payload_json, dict) else {}
        if bool(payload.get("manual_seed")):
            payload_release_id = payload.get("release_id")
            if isinstance(payload_release_id, str) and payload_release_id != release_id:
                continue
        filtered.append(market)
    return filtered


def _manual_interpreted_direction(
    *,
    mapping_payload_json: dict[str, Any],
    release_type: str,
    actual: Any | None,
) -> str | None:
    if release_type != ReleaseType.FOMC.value:
        return None
    if not bool(mapping_payload_json.get("manual_seed")):
        return None
    contract_interpretation = str(mapping_payload_json.get("contract_interpretation", "")).lower()
    if contract_interpretation == "":
        return None
    decision = _resolve_fomc_decision(actual)
    if decision is None:
        return None

    expected = None
    if "hold" in contract_interpretation or "pause" in contract_interpretation:
        expected = "HOLD"
    elif "hike" in contract_interpretation or "raise" in contract_interpretation or "increase" in contract_interpretation:
        expected = "HIKE"
    elif "cut" in contract_interpretation or "lower" in contract_interpretation or "reduce" in contract_interpretation:
        expected = "CUT"
    if expected is None:
        return None
    return "YES" if decision == expected else "NO"


def _resolve_fomc_decision(actual: Any | None) -> str | None:
    if actual is None:
        return None
    payload = getattr(actual, "parsed_payload_json", None)
    if isinstance(payload, dict):
        decision = payload.get("decision_classification")
        if isinstance(decision, str) and decision in {"HOLD", "HIKE", "CUT"}:
            return decision
    text_parts: list[str] = []
    raw = getattr(actual, "actual_value_raw", None)
    if isinstance(raw, str):
        text_parts.append(raw.lower())
    if isinstance(payload, dict):
        text_actual = payload.get("actual_value_text")
        if isinstance(text_actual, str):
            text_parts.append(text_actual.lower())
    text = " ".join(text_parts)
    if text == "":
        return None
    if "hold" in text or "maintain" in text or "unchanged" in text:
        return "HOLD"
    if "hike" in text or "raise" in text or "increase" in text:
        return "HIKE"
    if "cut" in text or "lower" in text or "reduce" in text:
        return "CUT"
    return None
