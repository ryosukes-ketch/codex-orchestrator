from __future__ import annotations

import hashlib


def stable_hash(*parts: str) -> str:
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def signal_key(release_id: str, signal_type: str, market_ticker: str) -> str:
    return stable_hash(release_id, signal_type, market_ticker)
