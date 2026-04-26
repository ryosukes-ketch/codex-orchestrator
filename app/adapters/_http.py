from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx


async def request_with_backoff(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_retries: int,
    base_delay: float,
    logger: logging.Logger,
    log_url: str | None = None,
    redact_values: tuple[str, ...] = (),
    **kwargs: Any,
) -> httpx.Response:
    attempt = 0
    safe_url = _sanitize(log_url or url, redact_values)
    while True:
        attempt += 1
        try:
            response = await client.request(method=method, url=url, **kwargs)
            response.raise_for_status()
            return response
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            safe_error = _sanitize(str(exc), redact_values)
            # Do not retry deterministic client errors (4xx). Retrying a 403 or 404
            # will never succeed and wastes time / generates noise.
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                logger.error(
                    "external_request_failed_client_error",
                    extra={
                        "url": safe_url,
                        "method": method,
                        "status_code": exc.response.status_code,
                        "error": safe_error,
                    },
                )
                raise
            if attempt > max_retries:
                logger.error(
                    "external_request_failed",
                    extra={"url": safe_url, "method": method, "attempt": attempt, "error": safe_error},
                )
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "external_request_retry",
                extra={
                    "url": safe_url,
                    "method": method,
                    "attempt": attempt,
                    "delay_seconds": delay,
                    "error": safe_error,
                },
            )
            await asyncio.sleep(delay)


def _sanitize(value: str, redactions: tuple[str, ...]) -> str:
    output = value
    for secret in redactions:
        if secret:
            output = output.replace(secret, "<redacted>")
    return output
