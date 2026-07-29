"""Shared Overpass API client: concurrency slots, endpoint failover, identifiable UA."""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# Public Overpass typically allows ~2 concurrent queries per client IP.
# Exceeding that causes queueing, 429s, and silent timeouts.
OVERPASS_MAX_CONCURRENT = int(os.environ.get("OVERPASS_MAX_CONCURRENT", "2"))
OVERPASS_ENDPOINTS = tuple(
    ep.strip()
    for ep in os.environ.get(
        "OVERPASS_ENDPOINTS",
        ",".join(
            (
                "https://overpass-api.de/api/interpreter",
                "https://lz4.overpass-api.de/api/interpreter",
                "https://overpass.kumi.systems/api/interpreter",
            )
        ),
    ).split(",")
    if ep.strip()
)

_OVERPASS_SLOTS = threading.BoundedSemaphore(max(1, OVERPASS_MAX_CONCURRENT))
_CONTACT = os.environ.get("OVERPASS_CONTACT", "").strip()
_UA_BASE = "RapidResponseAgent/1.0 (https://github.com/feizhao19/RapidResponseAgent; disaster assessment)"
USER_AGENT = f"{_UA_BASE}; contact={_CONTACT}" if _CONTACT else _UA_BASE


def overpass_headers() -> dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if _CONTACT:
        headers["From"] = _CONTACT
    return headers


def post_overpass(
    query: str,
    *,
    timeout_sec: float = 45.0,
    label: str = "query",
) -> dict[str, Any]:
    """POST an Overpass QL query with slot limiting and multi-endpoint failover.

    Strategy:
    1. Try each mirror once with a short timeout (fail over quickly).
    2. If all fail, retry each mirror once with the full timeout.
    """
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    headers = overpass_headers()
    last_error: Exception | None = None
    quick_timeout = min(float(timeout_sec), 25.0)
    passes: tuple[float, ...] = (quick_timeout,)
    if timeout_sec > quick_timeout + 1.0:
        passes = (quick_timeout, float(timeout_sec))

    for attempt_timeout in passes:
        for endpoint in OVERPASS_ENDPOINTS:
            request = urllib.request.Request(
                endpoint,
                data=body,
                headers=headers,
                method="POST",
            )
            acquired = _OVERPASS_SLOTS.acquire(timeout=attempt_timeout + 5.0)
            if not acquired:
                last_error = TimeoutError("Overpass concurrency slot wait timed out")
                continue
            try:
                with urllib.request.urlopen(request, timeout=attempt_timeout) as response:
                    raw = response.read().decode("utf-8")
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise json.JSONDecodeError("expected object", raw, 0)
                return payload
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                # Brief pause before the next mirror; avoids stampeding a recovering node.
                time.sleep(0.35)
            finally:
                _OVERPASS_SLOTS.release()

    raise RuntimeError(f"Overpass {label} failed: {last_error}")
