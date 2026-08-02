"""Toxiproxy transport controller for fault-injection tests."""

from __future__ import annotations

import logging
import math

import httpx

DEFAULT_ADMIN_URL = "http://localhost:8474"
DEFAULT_LISTEN = "0.0.0.0:26379"
DEFAULT_UPSTREAM = "redis:6379"
DEFAULT_PROXY_NAME = "redis"

logger = logging.getLogger(__name__)


class ToxiproxyTransportController:
    """Control Toxiproxy proxies for deterministic fault injection."""

    def __init__(
        self,
        admin_url: str = DEFAULT_ADMIN_URL,
        proxy_name: str = DEFAULT_PROXY_NAME,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._admin_url = admin_url.rstrip("/")
        self._proxy_name = proxy_name
        self._transport = transport

    @staticmethod
    def _validate_probability(probability: float) -> None:
        if (
            isinstance(probability, bool)
            or not isinstance(probability, (int, float))
            or not math.isfinite(probability)
            or not 0.0 <= probability <= 1.0
        ):
            raise ValueError("probability must be finite and between 0.0 and 1.0")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, object] | None = None,
        allow_status: tuple[int, ...] = (),
    ) -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                **({} if self._transport is None else {"transport": self._transport})
            ) as client:
                response = await client.request(
                    method,
                    f"{self._admin_url}{path}",
                    **({} if json_body is None else {"json": json_body}),
                )
        except httpx.HTTPError:
            logger.error("Toxiproxy admin failure: target=<redacted> error=<redacted>")
            raise
        if response.is_error and response.status_code not in allow_status:
            logger.error(
                "Toxiproxy admin failure: target=<redacted> status=%s detail=<redacted>",
                response.status_code,
            )
            response.raise_for_status()
        return response

    async def _add_toxic(
        self,
        name: str,
        toxic_type: str,
        attributes: dict[str, object],
        toxicity: float = 1.0,
    ) -> dict[str, object]:
        response = await self._request(
            "POST",
            f"/proxies/{self._proxy_name}/toxics",
            json_body={
                "name": name,
                "type": toxic_type,
                "stream": "downstream",
                "attributes": attributes,
                "toxicity": toxicity,
            },
        )
        return response.json()

    async def ensure_proxy(
        self,
        name: str,
        listen: str = DEFAULT_LISTEN,
        upstream: str = DEFAULT_UPSTREAM,
    ) -> None:
        """Create the proxy if it does not exist; enable it if disabled."""
        response = await self._request("GET", f"/proxies/{name}", allow_status=(404,))
        if response.status_code == 404:
            await self._request(
                "POST",
                "/proxies",
                json_body={
                    "name": name,
                    "listen": listen,
                    "upstream": upstream,
                    "enabled": True,
                },
            )
        elif not response.json().get("enabled", True):
            await self.enable_proxy(name)

    async def disable_proxy(self, name: str) -> None:
        """Disable a proxy to simulate connection refusal."""
        await self._request("POST", f"/proxies/{name}", json_body={"enabled": False})

    async def enable_proxy(self, name: str) -> None:
        """Re-enable a previously disabled proxy."""
        await self._request("POST", f"/proxies/{name}", json_body={"enabled": True})

    async def add_latency(self, ms: int, *, jitter_ms: int = 0) -> dict[str, object]:
        return await self._add_toxic(
            "latency_downstream",
            "latency",
            {"latency": ms, "jitter": jitter_ms},
        )

    async def add_timeout(self, ms: int) -> dict[str, object]:
        return await self._add_toxic("timeout_downstream", "timeout", {"timeout": ms})

    async def add_connection_drop(self, probability: float = 1.0) -> dict[str, object]:
        self._validate_probability(probability)
        return await self._add_toxic(
            "connection_drop", "reset_peer", {}, float(probability)
        )

    async def list_toxics(self) -> list[dict[str, object]]:
        response = await self._request("GET", f"/proxies/{self._proxy_name}/toxics")
        return response.json()

    async def delete_toxic(self, name: str) -> None:
        await self._request("DELETE", f"/proxies/{self._proxy_name}/toxics/{name}")

    async def reset_toxics(self) -> None:
        for toxic in await self.list_toxics():
            await self.delete_toxic(str(toxic["name"]))
        await self.enable_proxy(self._proxy_name)
