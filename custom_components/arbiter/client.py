"""HTTP client for Arbiter."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp


class ArbiterClient:
    """Small async client for the Arbiter HTTP API."""

    def __init__(self, session: aiohttp.ClientSession, url: str, token: str | None) -> None:
        self._session = session
        self._url = url.rstrip("/")
        self._token = token

    async def async_send_pulse(self, payload: dict[str, Any]) -> None:
        """Send a pulse to Arbiter."""
        headers = {"content-type": "application/json"}
        if self._token:
            headers["authorization"] = f"Bearer {self._token}"

        async with self._session.post(
            f"{self._url}/v1/pulses",
            json=payload,
            headers=headers,
        ) as response:
            if response.status >= 400:
                body = await response.text()
                raise ArbiterClientError(
                    f"Arbiter returned HTTP {response.status}: {body[:500]}"
                )

    async def async_test_connection(self) -> None:
        """Best-effort connection test.

        Prefer /readyz if present. If your Arbiter does not expose it yet,
        this will still accept 401/403 as proof that the host is reachable.
        """
        headers = {}
        if self._token:
            headers["authorization"] = f"Bearer {self._token}"

        try:
            async with self._session.get(
                f"{self._url}/readyz",
                headers=headers,
            ) as response:
                if response.status in (200, 204, 401, 403):
                    return

                body = await response.text()
                raise ArbiterClientError(
                    f"Arbiter readiness check returned HTTP {response.status}: {body[:500]}"
                )
        except asyncio.TimeoutError as exc:
            raise ArbiterClientError("Timed out connecting to Arbiter") from exc
        except aiohttp.ClientError as exc:
            raise ArbiterClientError(f"Could not connect to Arbiter: {exc}") from exc


class ArbiterClientError(Exception):
    """Raised when Arbiter cannot be reached or rejects a request."""
