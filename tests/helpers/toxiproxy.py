"""Toxiproxy transport controller for fault-injection tests (PR1 #260).

Exposes proxy disable/enable only. Named transport scenarios are added by
later PRs (PR6 timeout, PR7 timeout, PR8 reset_peer, PR9 timeout).

Uses httpx (already a project dependency) to talk to the Toxiproxy admin API.
"""
from __future__ import annotations

import httpx

DEFAULT_ADMIN_URL = "http://localhost:8474"
DEFAULT_LISTEN = "0.0.0.0:26379"
DEFAULT_UPSTREAM = "redis:6379"


class ToxiproxyTransportController:
    """Control Toxiproxy proxies for deterministic fault injection."""

    def __init__(self, admin_url: str = DEFAULT_ADMIN_URL) -> None:
        self._admin_url = admin_url.rstrip("/")

    async def ensure_proxy(
        self,
        name: str,
        listen: str = DEFAULT_LISTEN,
        upstream: str = DEFAULT_UPSTREAM,
    ) -> None:
        """Create the proxy if it does not exist; enable it if disabled."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self._admin_url}/proxies/{name}")
            if resp.status_code == 404:
                response = await client.post(
                    f"{self._admin_url}/proxies",
                    json={
                        "name": name,
                        "listen": listen,
                        "upstream": upstream,
                        "enabled": True,
                    },
                )
                response.raise_for_status()
            elif not resp.json().get("enabled", True):
                await self.enable_proxy(name)

    async def disable_proxy(self, name: str) -> None:
        """Disable a proxy to simulate connection refusal."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._admin_url}/proxies/{name}",
                json={"enabled": False},
            )
            resp.raise_for_status()

    async def enable_proxy(self, name: str) -> None:
        """Re-enable a previously disabled proxy."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._admin_url}/proxies/{name}",
                json={"enabled": True},
            )
            resp.raise_for_status()
