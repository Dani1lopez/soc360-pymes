"""Phase 2 unit 2C: Compose healthchecks/limits and nginx security headers."""
from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_APP_FILE = ROOT / "docker-compose.app.yml"
NGINX_CONF_FILE = ROOT / "frontend" / "nginx.conf"
NGINX_HEADERS_FILE = ROOT / "frontend" / "nginx-security-headers.conf"
FRONTEND_DOCKERFILE = ROOT / "frontend" / "Dockerfile"
FRONTEND_INDEX_HTML = ROOT / "frontend" / "index.html"

SECURITY_SNIPPET_INCLUDE = "include /etc/nginx/snippets/security-headers.conf;"


def _load_compose_services() -> dict[str, dict]:
    data = yaml.safe_load(COMPOSE_APP_FILE.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and "services" in data
    return data["services"]


def _extract_nginx_location_blocks(nginx_text: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    for match in re.finditer(r"location\s+([^{]+?)\s*\{([^}]*)\}", nginx_text, re.S):
        location_key = " ".join(match.group(1).split())
        blocks[location_key] = match.group(2)
    return blocks


def test_api_and_frontend_have_healthchecks_and_service_healthy_dependency() -> None:
    services = _load_compose_services()

    api_hc = services["api"]["healthcheck"]
    assert isinstance(api_hc["test"], list)
    assert api_hc["test"][:2] == ["CMD", "python"]
    assert "http://127.0.0.1:8000/health" in " ".join(api_hc["test"])
    assert "curl" not in " ".join(api_hc["test"])
    assert api_hc["start_period"] == "15s"
    assert api_hc["interval"] == "10s"

    fe_hc = services["frontend"]["healthcheck"]
    assert isinstance(fe_hc["test"], list)
    assert "http://127.0.0.1/" in " ".join(fe_hc["test"])
    assert fe_hc["interval"] == "10s"

    assert services["frontend"]["depends_on"]["api"]["condition"] == "service_healthy"


def test_long_running_services_define_resource_limits() -> None:
    services = _load_compose_services()
    bounded_services = (
        "postgres",
        "api",
        "worker",
        "beat",
        "maintenance",
        "enrichment",
        "frontend",
    )
    for name in bounded_services:
        svc = services[name]
        assert "mem_limit" in svc, f"{name} is missing mem_limit"
        assert "cpus" in svc, f"{name} is missing cpus"
        assert "pids_limit" in svc, f"{name} is missing pids_limit"

    assert "mem_limit" in services["redis"]


def test_compose_hardening_posture_preserved() -> None:
    services = _load_compose_services()
    for name in ("api", "beat", "maintenance", "enrichment"):
        svc = services[name]
        assert svc["read_only"] is True
        assert svc["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in svc["security_opt"]
        assert svc["environment"]["DATABASE_URL_MIGRATION"] == ""

    assert services["frontend"]["read_only"] is True
    assert services["frontend"]["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in services["frontend"]["security_opt"]


def test_nginx_hides_server_tokens_and_includes_security_headers_only_on_static_locations() -> None:
    nginx_text = NGINX_CONF_FILE.read_text(encoding="utf-8")
    assert re.search(r"^\s*server_tokens\s+off;\s*$", nginx_text, re.M)

    blocks = _extract_nginx_location_blocks(nginx_text)
    for static_loc in ("/assets/", "= /index.html", "/"):
        assert static_loc in blocks, f"missing static location {static_loc}"
        assert SECURITY_SNIPPET_INCLUDE in blocks[static_loc], (
            f"{static_loc} must include security headers snippet"
        )

    for api_loc in ("= /api/v1/auth/login", "/api/"):
        assert api_loc in blocks, f"missing API location {api_loc}"
        assert SECURITY_SNIPPET_INCLUDE not in blocks[api_loc], (
            f"{api_loc} must not duplicate FastAPI security headers"
        )


def test_nginx_security_headers_snippet_and_csp_inline_script_hash() -> None:
    snippet_text = NGINX_HEADERS_FILE.read_text(encoding="utf-8")
    header_lines = [
        line.strip()
        for line in snippet_text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert len(header_lines) == 5
    for line in header_lines:
        assert line.startswith("add_header "), line
        assert line.endswith(" always;"), f"add_header must use 'always': {line}"

    assert 'add_header X-Content-Type-Options "nosniff" always;' in header_lines
    assert 'add_header X-Frame-Options "DENY" always;' in header_lines
    assert (
        'add_header Referrer-Policy "strict-origin-when-cross-origin" always;'
        in header_lines
    )
    assert (
        'add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;'
        in header_lines
    )

    csp_match = re.search(
        r'add_header Content-Security-Policy "([^"]+)" always;', snippet_text
    )
    assert csp_match, "Content-Security-Policy header missing"
    csp = csp_match.group(1)

    directives = {}
    for part in csp.split(";"):
        tokens = part.strip().split()
        if tokens:
            directives[tokens[0]] = tokens[1:]

    assert directives["default-src"] == ["'self'"]
    assert "'unsafe-inline'" not in directives["script-src"]
    assert "'unsafe-eval'" not in directives["script-src"]
    assert directives["object-src"] == ["'none'"]
    assert directives["frame-ancestors"] == ["'none'"]
    assert directives["base-uri"] == ["'self'"]
    assert directives["form-action"] == ["'self'"]

    # Verify CSP script-src hash matches the actual inline theme script in index.html.
    html = FRONTEND_INDEX_HTML.read_text(encoding="utf-8")
    inline_script = re.search(r"<script>(.*?)</script>", html, re.S)
    assert inline_script, "expected inline theme script in frontend/index.html"
    expected_digest = base64.b64encode(
        hashlib.sha256(inline_script.group(1).encode("utf-8")).digest()
    ).decode("ascii")
    assert f"'sha256-{expected_digest}'" in directives["script-src"]


def test_frontend_dockerfile_copies_security_headers_snippet() -> None:
    dockerfile_text = FRONTEND_DOCKERFILE.read_text(encoding="utf-8")
    assert (
        "COPY nginx-security-headers.conf /etc/nginx/snippets/security-headers.conf"
        in dockerfile_text
    )
