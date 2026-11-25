"""Client IP resolution behind trusted proxies (S8 / H4).

Rules under test:
1. ``X-Forwarded-For`` is honoured only when the socket peer is a configured
   trusted proxy; the default configuration works for the bundled nginx in
   ``docker-compose.app.yml``.
2. ``X-Forwarded-For`` from an untrusted peer is ignored and a client-supplied
   (spoofed) chain never wins over the address the trusted proxy appended.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path

import pytest
import yaml
from starlette.requests import Request

from app.core.client_ip import is_trusted_proxy, resolve_client_ip
from app.core.config import settings

_COMPOSE_FILE = Path(__file__).resolve().parents[2] / "docker-compose.app.yml"
# nginx is the only service on the dedicated `edge` network, pinned to this
# small range so the API trusts exactly nginx and nothing else.
_EDGE_VAR = "${SOC360_EDGE_SUBNET:-10.203.17.0/29}"
_EDGE_SUBNET = "10.203.17.0/29"
_EDGE_PEER = "10.203.17.2"  # the nginx container inside `edge`
# Any container on the ordinary bridge network must never pick the client IP.
_DEFAULT_NETWORK_PEER = "172.18.0.7"
_LOOPBACK_ONLY = ["127.0.0.1/32", "::1/128"]
_CLIENT = "203.0.113.7"
_ATTACKER = "198.51.100.9"


def _compose() -> dict:
    return yaml.safe_load(_COMPOSE_FILE.read_text(encoding="utf-8"))


def _request(peer_host: str, forwarded_for: str | None = None) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/login",
        "headers": headers,
        "client": (peer_host, 54321),
        "scheme": "http",
        "server": ("test", 80),
        "query_string": b"",
    }
    return Request(scope)


class TestTrustedProxyForwardedFor:
    """R1 — X-Forwarded-For from a configured trusted proxy is honoured."""

    def test_forwarded_for_honoured_from_trusted_proxy(self) -> None:
        resolved = resolve_client_ip(_EDGE_PEER, _CLIENT, trusted=[_EDGE_SUBNET])
        assert resolved == _CLIENT

    def test_forwarded_for_honoured_from_trusted_single_ip(self) -> None:
        resolved = resolve_client_ip(
            "10.0.0.1", _CLIENT, trusted=["10.0.0.1"]
        )
        assert resolved == _CLIENT

    def test_loopback_peer_trusted_by_default(self) -> None:
        """Local dev (Vite proxy -> uvicorn) resolves the forwarded client."""
        assert is_trusted_proxy("127.0.0.1") is True
        assert is_trusted_proxy("::1") is True

    def test_ipv6_loopback_forwarded_for_honoured(self) -> None:
        assert resolve_client_ip("::1", "2001:db8::1") == "2001:db8::1"

    def test_router_uses_forwarded_for_from_trusted_proxy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.auth.router import _get_client_ip

        monkeypatch.setattr(settings, "TRUSTED_PROXIES", [_EDGE_SUBNET])
        assert _get_client_ip(_request(_EDGE_PEER, _CLIENT)) == _CLIENT


class TestUntrustedForwardedForIgnored:
    """R2 — X-Forwarded-For from an untrusted peer is ignored / spoof rejected."""

    def test_forwarded_for_ignored_from_untrusted_peer(self) -> None:
        resolved = resolve_client_ip(_ATTACKER, _CLIENT, trusted=[_EDGE_SUBNET])
        assert resolved == _ATTACKER

    def test_forwarded_for_ignored_with_empty_trusted_list(self) -> None:
        assert resolve_client_ip(_EDGE_PEER, _CLIENT, trusted=[]) == _EDGE_PEER

    def test_spoofed_leftmost_entry_behind_nginx_is_rejected(self) -> None:
        """nginx appends the real peer, so the rightmost untrusted hop wins."""
        chain = f"6.6.6.6, {_CLIENT}"
        resolved = resolve_client_ip(_EDGE_PEER, chain, trusted=[_EDGE_SUBNET])
        assert resolved == _CLIENT
        assert resolved != "6.6.6.6"

    def test_garbage_forwarded_header_is_ignored(self) -> None:
        resolved = resolve_client_ip(
            _EDGE_PEER, "not-an-ip, also-bad", trusted=[_EDGE_SUBNET]
        )
        assert resolved == _EDGE_PEER

    def test_unparsable_peer_is_returned_unchanged(self) -> None:
        assert resolve_client_ip("unknown", _CLIENT) == "unknown"

    def test_router_ignores_forwarded_for_from_untrusted_peer(self) -> None:
        from app.modules.auth.router import _get_client_ip

        assert _get_client_ip(_request(_ATTACKER, _CLIENT)) == _ATTACKER


class TestDefaultConfigurationAndComposeWiring:
    """R3 — the code default trusts loopback only; compose trusts nginx alone."""

    def test_config_default_trusts_loopback_only(self) -> None:
        from app.core.config import Settings

        default = Settings.model_fields["TRUSTED_PROXIES"].default
        assert default == _LOOPBACK_ONLY
        # No Docker range in the default: a fixed range both collides with
        # other stacks and trusts every container of that network.
        assert all(
            ipaddress.ip_network(entry, strict=False).is_loopback for entry in default
        )

    def test_edge_peer_trusted_when_trusted_proxies_is_edge_subnet(self) -> None:
        resolved = resolve_client_ip(_EDGE_PEER, _CLIENT, trusted=[_EDGE_SUBNET])
        assert resolved == _CLIENT

    def test_default_network_peer_cannot_set_forwarded_for(self) -> None:
        resolved = resolve_client_ip(
            _DEFAULT_NETWORK_PEER, _CLIENT, trusted=[_EDGE_SUBNET]
        )
        assert resolved == _DEFAULT_NETWORK_PEER

    def test_default_ignores_forwarded_for_from_public_peer(self) -> None:
        assert resolve_client_ip(_ATTACKER, _CLIENT) == _ATTACKER

    def test_edge_network_and_api_trust_share_one_variable(self) -> None:
        """Network and trust cannot drift: both read SOC360_EDGE_SUBNET."""
        compose = _compose()
        subnet = compose["networks"]["edge"]["ipam"]["config"][0]["subnet"]
        trusted = compose["services"]["api"]["environment"]["TRUSTED_PROXIES"]
        assert subnet == _EDGE_VAR
        assert trusted == f'["{_EDGE_VAR}"]'

    def test_only_frontend_and_api_join_the_edge_network(self) -> None:
        """Guard: another container on `edge` could pick the client IP."""
        services = _compose()["services"]
        members = {
            name
            for name, service in services.items()
            if "edge" in (service.get("networks") or ())
        }
        assert members == {"frontend", "api"}
        assert services["frontend"]["networks"] == ["edge"]
        assert set(services["api"]["networks"]) == {"default", "edge"}

    def test_default_network_is_not_pinned_to_a_fixed_range(self) -> None:
        networks = _compose().get("networks") or {}
        assert "ipam" not in (networks.get("default") or {})


class TestEdgeSubnetDefaultAvoidsDockerPools:
    """R4 — the default `edge` range must not sit inside a Docker auto pool.

    Docker hands out 172.16.0.0/12 and 192.168.0.0/16 on its own, so a fixed
    default inside either one eventually collides with a network the host
    already owns and `docker compose up` fails on network creation.
    """

    _DOCKER_AUTO_POOLS = ("172.16.0.0/12", "192.168.0.0/16")

    def _default_edge_subnet(self) -> ipaddress.IPv4Network:
        subnet = _compose()["networks"]["edge"]["ipam"]["config"][0]["subnet"]
        assert isinstance(subnet, str)
        assert subnet.startswith("${") and ":-" in subnet
        default = subnet.split(":-", 1)[1].rstrip("}")
        return ipaddress.ip_network(default, strict=False)

    def test_default_edge_subnet_is_outside_docker_auto_pools(self) -> None:
        default = self._default_edge_subnet()
        for pool in self._DOCKER_AUTO_POOLS:
            overlapping = default.overlaps(ipaddress.ip_network(pool))
            assert not overlapping, (
                f"edge default {default} overlaps Docker pool {pool}: "
                "network creation fails on hosts that already use it"
            )


class TestTrustedProxiesSettingValidation:
    """A misconfigured TRUSTED_PROXIES entry must fail loudly at boot."""

    @pytest.mark.parametrize("bad", ["not-a-cidr", "10.0.0.0/99"])
    def test_invalid_entry_rejected(self, bad: str) -> None:
        from pydantic import ValidationError

        from app.core.config import Settings

        with pytest.raises(ValidationError):
            Settings(TRUSTED_PROXIES=[bad])
