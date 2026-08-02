"""Pure-Python tests for the Toxiproxy admin API helper."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from tests.helpers.toxiproxy import ToxiproxyTransportController


def _controller(requests: list[httpx.Request], response: object):
    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=response, request=request)

    return ToxiproxyTransportController(transport=httpx.MockTransport(handler))


def _assert_toxic(request: httpx.Request, name: str, toxic_type: str, attributes: dict):
    assert json.loads(request.content) == {
        "name": name,
        "type": toxic_type,
        "stream": "downstream",
        "attributes": attributes,
        "toxicity": 1.0,
    }


@pytest.mark.asyncio
async def test_add_latency_payload_uses_downstream_toxic():
    requests: list[httpx.Request] = []
    await _controller(requests, {"name": "latency_downstream"}).add_latency(
        125, jitter_ms=25
    )
    assert requests[0].url.path == "/proxies/redis/toxics"
    _assert_toxic(
        requests[0], "latency_downstream", "latency", {"latency": 125, "jitter": 25}
    )


@pytest.mark.asyncio
async def test_add_timeout_payload_uses_timeout_toxic():
    requests: list[httpx.Request] = []
    await _controller(requests, {"name": "timeout_downstream"}).add_timeout(150)
    _assert_toxic(requests[0], "timeout_downstream", "timeout", {"timeout": 150})


@pytest.mark.asyncio
async def test_add_connection_drop_maps_probability_to_toxicity():
    requests: list[httpx.Request] = []
    await _controller(requests, {"name": "connection_drop"}).add_connection_drop(0.35)
    payload = json.loads(requests[0].content)
    assert payload["type"] == "reset_peer"
    assert payload["stream"] == "downstream"
    assert payload["attributes"] == {}
    assert payload["toxicity"] == 0.35


@pytest.mark.asyncio
@pytest.mark.parametrize("probability", [-0.01, 1.01])
async def test_add_connection_drop_rejects_probability_outside_bounds(
    probability: float,
):
    requests: list[httpx.Request] = []
    with pytest.raises(ValueError, match="probability"):
        await _controller(requests, {}).add_connection_drop(probability)
    assert not requests


@pytest.mark.asyncio
async def test_reset_toxics_only_targets_named_proxy():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json=[{"name": "latency_downstream"}, {"name": "timeout_downstream"}],
                request=request,
            )
        return httpx.Response(204, request=request)

    controller = ToxiproxyTransportController(transport=httpx.MockTransport(handler))
    await controller.reset_toxics()
    assert [request.url.path for request in requests] == [
        "/proxies/redis/toxics",
        "/proxies/redis/toxics/latency_downstream",
        "/proxies/redis/toxics/timeout_downstream",
        "/proxies/redis",
    ]


@pytest.mark.asyncio
async def test_admin_failures_are_redacted_in_logs(caplog):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "admin secret"}, request=request)

    controller = ToxiproxyTransportController(
        admin_url="http://admin:super-secret@toxiproxy.test:8474",
        transport=httpx.MockTransport(handler),
    )
    with caplog.at_level(logging.ERROR), pytest.raises(httpx.HTTPStatusError):
        await controller.add_timeout(150)
    assert "super-secret" not in caplog.text
    assert "admin secret" not in caplog.text
    assert "<redacted>" in caplog.text
