"""Slice 1 (F2) — Assets API tests.

TDD-driven coverage of the HTTP contract defined by ``design.md`` D-006
(RBAC matrix), D-007 (tenant scoping), D-008 (pagination), D-009
(response hygiene), D-012 (CSV export), and ``spec.md`` (scenarios).
Every endpoint is exercised against the function-scoped
``tenant_client`` fixture (see ``tests/conftest.py``) which overrides
``get_db`` / ``get_db_with_tenant`` / ``get_redis`` AND invokes
``set_tenant_context`` so the RLS predicates match the requester's
identity.

Test groups:
* ``TestRBACMatrix`` — 30-combination parametrized table (T11.2).
* ``TestCrossTenant404`` — admin_b's GET/PATCH/DELETE on tenant_a
  assets returns 404 (T11.3).
* ``TestSuperadminCrossTenant`` — list/get/patch/delete across tenants,
  POST with explicit ``tenant_id`` (T11.4).
* ``TestUniqueness409`` — POST duplicate and PATCH-induced duplicate
  return 409 (T11.5).
* ``TestPagination`` — 150-row seed; ``limit=50`` returns ``items=50,
  total=150``; ``limit=500`` is rejected (T11.6).
* ``TestEventsSpy`` — ``asset.created`` / ``asset.updated`` /
  ``asset.deleted`` are emitted on ``asset.events`` and a commit failure
  prevents publish (T11.7).
* ``TestResponseHygiene`` — exactly six public fields (T11.8).
* ``TestSemanticValidation422`` — type-specific error messages
  (T11.9).
"""
from __future__ import annotations

import csv
import io
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import (
    TENANT_A_ID,
    TENANT_B_ID,
)


# ---------------------------------------------------------------------------
# T11.2 — RBAC matrix (30 combinations)
# ---------------------------------------------------------------------------
# The matrix is encoded once as a list of tuples so each combination is a
# distinct parametrized case with its own role/endpoint/expected_status.
# 6 endpoints x 5 roles = 30 cases (18 allowed + 12 denied).
def _rbac_cases() -> list[tuple[str, str, int, dict[str, Any]]]:
    """Return the 30 RBAC combinations as ``(label, role, expected, extra_args)``.

    ``label`` is a human-friendly description used as the ``ids`` arg of
    ``parametrize``. ``role`` selects the headers fixture. ``expected`` is
    the HTTP status code the request MUST produce. ``extra_args`` carries
    any request-specific shaping needed by the parametrized body (e.g.
    POST/PATCH bodies, asset-id pre-conditions).
    """
    # The shape of each ``extra_args``:
    #   {
    #       "verb": "POST"|"GET"|"PATCH"|"DELETE",
    #       "url": "/api/v1/assets/" | "/api/v1/assets/{id}" | ...,
    #       "body": {...} | None,
    #   }
    return [
        # ----- POST /assets -----
        ("POST_admin_a",            "admin_a",     201, {"verb": "POST",    "url": "/api/v1/assets/",       "body": {"tenant_id": TENANT_A_ID, "type": "ip",        "value": "192.0.2.10"}}),
        ("POST_analyst_a",          "analyst_a",   403, {"verb": "POST",    "url": "/api/v1/assets/",       "body": {"tenant_id": TENANT_A_ID, "type": "ip",        "value": "192.0.2.11"}}),
        ("POST_viewer_a",           "viewer_a",    403, {"verb": "POST",    "url": "/api/v1/assets/",       "body": {"tenant_id": TENANT_A_ID, "type": "ip",        "value": "192.0.2.12"}}),
        # superadmin POSTs with explicit tenant_id (target = TENANT_A).
        ("POST_superadmin_a",       "superadmin",  201, {"verb": "POST",    "url": "/api/v1/assets/",       "body": {"tenant_id": TENANT_A_ID, "type": "ip",        "value": "192.0.2.13"}}),
        ("POST_ingestor_a",         "ingestor_a",  403, {"verb": "POST",    "url": "/api/v1/assets/",       "body": {"tenant_id": TENANT_A_ID, "type": "ip",        "value": "192.0.2.14"}}),
        # ----- GET /assets (list) -----
        ("GET_list_admin_a",        "admin_a",     200, {"verb": "GET",     "url": "/api/v1/assets/"}),
        ("GET_list_analyst_a",      "analyst_a",   200, {"verb": "GET",     "url": "/api/v1/assets/"}),
        ("GET_list_viewer_a",       "viewer_a",    200, {"verb": "GET",     "url": "/api/v1/assets/"}),
        ("GET_list_superadmin",     "superadmin",  200, {"verb": "GET",     "url": "/api/v1/assets/"}),
        ("GET_list_ingestor_a",     "ingestor_a",  403, {"verb": "GET",     "url": "/api/v1/assets/"}),
        # ----- GET /assets/{id} (own tenant) -----
        # Each "own" case uses an id that the role can see: admin_a / analyst_a /
        # viewer_a / superadmin see their own tenant (admin_a) AND
        # superadmin also sees cross-tenant. ingestor is always 403.
        # The fixture pre-creates an asset per role via seed.
        ("GET_by_id_admin_a",       "admin_a",     200, {"verb": "GET",     "url": "/api/v1/assets/__OWN__"}),
        ("GET_by_id_analyst_a",     "analyst_a",   200, {"verb": "GET",     "url": "/api/v1/assets/__OWN__"}),
        ("GET_by_id_viewer_a",      "viewer_a",    200, {"verb": "GET",     "url": "/api/v1/assets/__OWN__"}),
        ("GET_by_id_superadmin",    "superadmin",  200, {"verb": "GET",     "url": "/api/v1/assets/__OWN__"}),
        ("GET_by_id_ingestor_a",    "ingestor_a",  403, {"verb": "GET",     "url": "/api/v1/assets/__OWN__"}),
        # ----- GET /assets/{id} (cross-tenant) -----
        # Non-superadmin users get 404 for cross-tenant lookups (no leak);
        # superadmin gets 200; ingestor is 403 regardless.
        ("GET_by_id_cross_admin_b",  "admin_b",    404, {"verb": "GET",     "url": "/api/v1/assets/__CROSS__"}),
        ("GET_by_id_cross_admin_a",  "admin_a",    404, {"verb": "GET",     "url": "/api/v1/assets/__CROSS__"}),
        ("GET_by_id_cross_analyst_a","analyst_a",  404, {"verb": "GET",     "url": "/api/v1/assets/__CROSS__"}),
        ("GET_by_id_cross_superadmin","superadmin",200, {"verb": "GET",     "url": "/api/v1/assets/__CROSS__"}),
        # ----- PATCH /assets/{id} -----
        ("PATCH_admin_a",           "admin_a",     200, {"verb": "PATCH",   "url": "/api/v1/assets/__OWN__", "body": {"value": "192.0.2.20"}}),
        ("PATCH_analyst_a",         "analyst_a",   403, {"verb": "PATCH",   "url": "/api/v1/assets/__OWN__", "body": {"value": "192.0.2.21"}}),
        ("PATCH_viewer_a",          "viewer_a",    403, {"verb": "PATCH",   "url": "/api/v1/assets/__OWN__", "body": {"value": "192.0.2.22"}}),
        ("PATCH_superadmin",        "superadmin",  200, {"verb": "PATCH",   "url": "/api/v1/assets/__OWN__", "body": {"value": "192.0.2.23"}}),
        ("PATCH_ingestor_a",        "ingestor_a",  403, {"verb": "PATCH",   "url": "/api/v1/assets/__OWN__", "body": {"value": "192.0.2.24"}}),
        # ----- DELETE /assets/{id} -----
        ("DELETE_admin_a",          "admin_a",     204, {"verb": "DELETE",  "url": "/api/v1/assets/__OWN__"}),
        ("DELETE_analyst_a",        "analyst_a",   403, {"verb": "DELETE",  "url": "/api/v1/assets/__OWN__"}),
        ("DELETE_viewer_a",         "viewer_a",    403, {"verb": "DELETE",  "url": "/api/v1/assets/__OWN__"}),
        ("DELETE_superadmin",       "superadmin",  204, {"verb": "DELETE",  "url": "/api/v1/assets/__OWN__"}),
        ("DELETE_ingestor_a",       "ingestor_a",  403, {"verb": "DELETE",  "url": "/api/v1/assets/__OWN__"}),
        # ----- GET /assets?export=csv -----
        ("CSV_admin_a",             "admin_a",     200, {"verb": "GET",     "url": "/api/v1/assets/?export=csv"}),
        ("CSV_analyst_a",           "analyst_a",   200, {"verb": "GET",     "url": "/api/v1/assets/?export=csv"}),
        ("CSV_viewer_a",            "viewer_a",    200, {"verb": "GET",     "url": "/api/v1/assets/?export=csv"}),
        ("CSV_superadmin",          "superadmin",  200, {"verb": "GET",     "url": "/api/v1/assets/?export=csv"}),
        ("CSV_ingestor_a",          "ingestor_a",  403, {"verb": "GET",     "url": "/api/v1/assets/?export=csv"}),
    ]


# Each role maps to its headers fixture (resolved at fixture time).
_ROLE_TO_HEADERS = {
    "admin_a": "admin_a_headers",
    "analyst_a": "analyst_a_headers",
    "viewer_a": "viewer_a_headers",
    "superadmin": "superadmin_headers",
    "ingestor_a": "ingestor_a_headers",
}


# Seed a small set of assets so the RBAC matrix has real ids to work
# against. We seed two assets per tenant via the test's db_session.
async def _seed_rbac_assets(
    db_session: AsyncSession,
    tenant_a_id: str,
    tenant_b_id: str,
) -> tuple[str, str, str, str]:
    """Seed minimal assets; return (own_a_id, cross_b_id, own_a_2, own_b_2)."""
    from app.modules.assets.models import Asset

    own_a = Asset(
        tenant_id=tenant_a_id,
        asset_type="ip",
        value="192.0.2.50",  # canonical IPv4
    )
    cross_b = Asset(
        tenant_id=tenant_b_id,
        asset_type="ip",
        value="192.0.2.51",
    )
    own_a_2 = Asset(
        tenant_id=tenant_a_id,
        asset_type="ip",
        value="192.0.2.52",
    )
    own_b_2 = Asset(
        tenant_id=tenant_b_id,
        asset_type="ip",
        value="192.0.2.53",
    )
    for obj in (own_a, cross_b, own_a_2, own_b_2):
        db_session.add(obj)
    await db_session.flush()
    await db_session.commit()
    return (
        str(own_a.id),
        str(cross_b.id),
        str(own_a_2.id),
        str(own_b_2.id),
    )


class TestRBACMatrix:
    """T11.2 — Parametrized 30-combination RBAC matrix.

    Each ``(label, role, expected_status, extra_args)`` tuple from
    ``_rbac_cases`` runs as its own test so failures pinpoint the exact
    cell of the matrix. The matrix is identical to the one in
    ``spec.md`` and ``design.md`` D-006.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "label,role,expected,extra",
        _rbac_cases(),
        ids=[c[0] for c in _rbac_cases()],
    )
    async def test_rbac_cell(
        self,
        tenant_client: AsyncClient,
        db_session: AsyncSession,
        seed_data,
        admin_a_headers,
        admin_b_headers,
        analyst_a_headers,
        viewer_a_headers,
        superadmin_headers,
        ingestor_a_headers,
        label: str,
        role: str,
        expected: int,
        extra: dict[str, Any],
    ) -> None:
        # Seed the two assets this parametrized test depends on.
        own_a_id, cross_b_id, _own_a_2, _own_b_2 = await _seed_rbac_assets(
            db_session, TENANT_A_ID, TENANT_B_ID
        )

        # Resolve the URL placeholder.
        url = extra["url"]
        verb = extra["verb"]
        body = extra.get("body")
        if "__OWN__" in url:
            url = url.replace("__OWN__", own_a_id)
        if "__CROSS__" in url:
            url = url.replace("__CROSS__", cross_b_id)

        # Resolve the headers fixture by role name.
        headers_fixture = {
            "admin_a": admin_a_headers,
            "analyst_a": analyst_a_headers,
            "viewer_a": viewer_a_headers,
            "superadmin": superadmin_headers,
            "admin_b": admin_b_headers,
            "ingestor_a": ingestor_a_headers,
        }[role]

        if verb == "GET":
            resp = await tenant_client.get(url, headers=headers_fixture)
        elif verb == "POST":
            resp = await tenant_client.post(url, headers=headers_fixture, json=body)
        elif verb == "PATCH":
            resp = await tenant_client.patch(url, headers=headers_fixture, json=body)
        elif verb == "DELETE":
            resp = await tenant_client.delete(url, headers=headers_fixture)
        else:  # pragma: no cover — defensive guard
            raise RuntimeError(f"Unknown verb {verb!r}")

        assert resp.status_code == expected, (
            f"RBAC cell {label!r} (role={role}, verb={verb}) expected "
            f"{expected} but got {resp.status_code}: {resp.text[:300]}"
        )


# ---------------------------------------------------------------------------
# T11.3 — Cross-tenant 404
# ---------------------------------------------------------------------------
class TestCrossTenant404:
    """T11.3 — admin_b (tenant B) MUST see 404 for tenant A assets.

    The contract is critical: 404 (not 403) avoids leaking the existence
    of an out-of-tenant resource.
    """

    @pytest.mark.asyncio
    async def test_admin_b_get_cross_tenant_returns_404(
        self, tenant_client: AsyncClient, admin_b_headers, db_session, seed_data
    ) -> None:
        from app.modules.assets.models import Asset

        a1 = Asset(tenant_id=TENANT_A_ID, asset_type="ip", value="192.0.2.60")
        a2 = Asset(tenant_id=TENANT_A_ID, asset_type="ip", value="192.0.2.61")
        a3 = Asset(tenant_id=TENANT_A_ID, asset_type="ip", value="192.0.2.62")
        db_session.add_all([a1, a2, a3])
        await db_session.flush()
        await db_session.commit()

        for asset in (a1, a2, a3):
            resp = await tenant_client.get(
                f"/api/v1/assets/{asset.id}", headers=admin_b_headers
            )
            assert resp.status_code == 404, (
                f"admin_b MUST NOT see tenant_a asset {asset.id}; "
                f"got {resp.status_code}: {resp.text}"
            )

    @pytest.mark.asyncio
    async def test_admin_b_patch_cross_tenant_returns_404(
        self, tenant_client: AsyncClient, admin_b_headers, db_session, seed_data
    ) -> None:
        from app.modules.assets.models import Asset

        a1 = Asset(tenant_id=TENANT_A_ID, asset_type="ip", value="192.0.2.63")
        db_session.add(a1)
        await db_session.flush()
        await db_session.commit()

        resp = await tenant_client.patch(
            f"/api/v1/assets/{a1.id}",
            headers=admin_b_headers,
            json={"value": "192.0.2.64"},
        )
        assert resp.status_code == 404, (
            f"admin_b PATCH on tenant_a asset MUST be 404; got {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_admin_b_delete_cross_tenant_returns_404(
        self, tenant_client: AsyncClient, admin_b_headers, db_session, seed_data
    ) -> None:
        from app.modules.assets.models import Asset

        a1 = Asset(tenant_id=TENANT_A_ID, asset_type="ip", value="192.0.2.65")
        db_session.add(a1)
        await db_session.flush()
        await db_session.commit()

        resp = await tenant_client.delete(
            f"/api/v1/assets/{a1.id}", headers=admin_b_headers
        )
        assert resp.status_code == 404, (
            f"admin_b DELETE on tenant_a asset MUST be 404; got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# T11.4 — Superadmin cross-tenant
# ---------------------------------------------------------------------------
class TestSuperadminCrossTenant:
    """T11.4 — superadmin scope is cross-tenant by design.

    * List returns assets across tenants with pagination metadata.
    * GET by-id returns the asset regardless of tenant.
    * PATCH / DELETE work and the asset's tenant_id is unchanged.
    * POST without ``tenant_id`` is rejected with 422.
    * POST with ``tenant_id`` succeeds and the response carries that uuid.
    * ``?export=csv`` returns 200 with ``Content-Type: text/csv``.
    """

    @pytest.mark.asyncio
    async def test_superadmin_list_returns_all_tenants(
        self, tenant_client: AsyncClient, superadmin_headers, db_session, seed_data
    ) -> None:
        from app.modules.assets.models import Asset

        # Two assets per tenant.
        rows = [
            Asset(tenant_id=TENANT_A_ID, asset_type="ip", value="192.0.2.70"),
            Asset(tenant_id=TENANT_A_ID, asset_type="ip", value="192.0.2.71"),
            Asset(tenant_id=TENANT_B_ID, asset_type="ip", value="192.0.2.72"),
            Asset(tenant_id=TENANT_B_ID, asset_type="ip", value="192.0.2.73"),
        ]
        db_session.add_all(rows)
        await db_session.flush()
        await db_session.commit()

        resp = await tenant_client.get("/api/v1/assets/", headers=superadmin_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 4, f"superadmin MUST see at least 4 assets, got {body}"
        seen_tenants = {item["tenant_id"] for item in body["items"]}
        assert TENANT_A_ID in seen_tenants and TENANT_B_ID in seen_tenants

    @pytest.mark.asyncio
    async def test_superadmin_get_cross_tenant_asset(
        self, tenant_client: AsyncClient, superadmin_headers, db_session, seed_data
    ) -> None:
        from app.modules.assets.models import Asset

        a = Asset(tenant_id=TENANT_A_ID, asset_type="ip", value="192.0.2.80")
        db_session.add(a)
        await db_session.flush()
        await db_session.commit()

        resp = await tenant_client.get(
            f"/api/v1/assets/{a.id}", headers=superadmin_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == str(a.id)
        assert body["tenant_id"] == TENANT_A_ID

    @pytest.mark.asyncio
    async def test_superadmin_patch_cross_tenant_keeps_tenant_id(
        self, tenant_client: AsyncClient, superadmin_headers, db_session, seed_data
    ) -> None:
        from app.modules.assets.models import Asset

        a = Asset(tenant_id=TENANT_A_ID, asset_type="ip", value="192.0.2.81")
        db_session.add(a)
        await db_session.flush()
        await db_session.commit()

        resp = await tenant_client.patch(
            f"/api/v1/assets/{a.id}",
            headers=superadmin_headers,
            json={"value": "192.0.2.82"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["tenant_id"] == TENANT_A_ID, (
            "superadmin PATCH MUST NOT change the asset's tenant_id"
        )

    @pytest.mark.asyncio
    async def test_superadmin_delete_cross_tenant_returns_204(
        self, tenant_client: AsyncClient, superadmin_headers, db_session, seed_data
    ) -> None:
        from app.modules.assets.models import Asset

        a = Asset(tenant_id=TENANT_A_ID, asset_type="ip", value="192.0.2.83")
        db_session.add(a)
        await db_session.flush()
        await db_session.commit()

        resp = await tenant_client.delete(
            f"/api/v1/assets/{a.id}", headers=superadmin_headers
        )
        assert resp.status_code == 204, (
            f"superadmin cross-tenant DELETE expected 204, got {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_superadmin_post_without_tenant_id_returns_422(
        self, tenant_client: AsyncClient, superadmin_headers, seed_data
    ) -> None:
        resp = await tenant_client.post(
            "/api/v1/assets/",
            headers=superadmin_headers,
            json={"type": "ip", "value": "192.0.2.84"},
        )
        assert resp.status_code == 422, (
            f"superadmin POST without tenant_id MUST be 422; got {resp.status_code}"
        )
        # The error detail MUST mention the missing field.
        body = resp.json()
        detail = body.get("detail") or []
        if isinstance(detail, list):
            fields = {err.get("loc", [])[-1] for err in detail}
            assert "tenant_id" in fields, (
                f"422 detail MUST mention tenant_id; got fields={fields!r}"
            )
        else:
            assert "tenant_id" in str(detail).lower()

    @pytest.mark.asyncio
    async def test_superadmin_post_with_explicit_tenant_id_succeeds(
        self, tenant_client: AsyncClient, superadmin_headers, seed_data
    ) -> None:
        resp = await tenant_client.post(
            "/api/v1/assets/",
            headers=superadmin_headers,
            json={
                "tenant_id": TENANT_A_ID,
                "type": "ip",
                "value": "192.0.2.85",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["tenant_id"] == TENANT_A_ID

    @pytest.mark.asyncio
    async def test_superadmin_csv_export_returns_text_csv(
        self, tenant_client: AsyncClient, superadmin_headers, db_session, seed_data
    ) -> None:
        from app.modules.assets.models import Asset

        # Seed at least one row per tenant to confirm CSV cross-tenant scope.
        a = Asset(tenant_id=TENANT_A_ID, asset_type="ip", value="192.0.2.86")
        b = Asset(tenant_id=TENANT_B_ID, asset_type="ip", value="192.0.2.87")
        db_session.add_all([a, b])
        await db_session.flush()
        await db_session.commit()

        resp = await tenant_client.get(
            "/api/v1/assets/?export=csv", headers=superadmin_headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("text/csv"), (
            f"CSV MUST advertise text/csv; got {resp.headers.get('content-type')!r}"
        )
        text = resp.text
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        assert len(rows) >= 2
        seen_tenants = {row["tenant_id"] for row in rows}
        assert TENANT_A_ID in seen_tenants and TENANT_B_ID in seen_tenants


# ---------------------------------------------------------------------------
# T11.5 — Uniqueness 409
# ---------------------------------------------------------------------------
class TestUniqueness409:
    """T11.5 — Duplicate (tenant_id, type, value) MUST return 409."""

    @pytest.mark.asyncio
    async def test_post_duplicate_returns_409(
        self, tenant_client: AsyncClient, admin_a_headers, seed_data
    ) -> None:
        # Create the initial asset.
        first = await tenant_client.post(
            "/api/v1/assets/",
            headers=admin_a_headers,
            json={
                "tenant_id": TENANT_A_ID,
                "type": "ip",
                "value": "192.0.2.90",
            },
        )
        assert first.status_code == 201, first.text

        # Duplicate POST MUST be 409.
        dup = await tenant_client.post(
            "/api/v1/assets/",
            headers=admin_a_headers,
            json={
                "tenant_id": TENANT_A_ID,
                "type": "ip",
                "value": "192.0.2.90",
            },
        )
        assert dup.status_code == 409, (
            f"Duplicate POST MUST be 409; got {dup.status_code}: {dup.text}"
        )

    @pytest.mark.asyncio
    async def test_patch_inducing_duplicate_returns_409(
        self, tenant_client: AsyncClient, admin_a_headers, seed_data
    ) -> None:
        # Asset A = (ip, 192.0.2.91)
        a = await tenant_client.post(
            "/api/v1/assets/",
            headers=admin_a_headers,
            json={
                "tenant_id": TENANT_A_ID,
                "type": "ip",
                "value": "192.0.2.91",
            },
        )
        assert a.status_code == 201, a.text
        a_id = a.json()["id"]

        # Asset B = (ip, 192.0.2.92)
        b = await tenant_client.post(
            "/api/v1/assets/",
            headers=admin_a_headers,
            json={
                "tenant_id": TENANT_A_ID,
                "type": "ip",
                "value": "192.0.2.92",
            },
        )
        assert b.status_code == 201, b.text
        b_id = b.json()["id"]

        # PATCH B → value = 192.0.2.91 (collides with A)
        patch_resp = await tenant_client.patch(
            f"/api/v1/assets/{b_id}",
            headers=admin_a_headers,
            json={"value": "192.0.2.91"},
        )
        assert patch_resp.status_code == 409, (
            f"PATCH-induced duplicate MUST be 409; got {patch_resp.status_code}: {patch_resp.text}"
        )


# ---------------------------------------------------------------------------
# T11.6 — Pagination
# ---------------------------------------------------------------------------
class TestPagination:
    """T11.6 — limit/offset behaviour + limit validation."""

    @pytest.mark.asyncio
    async def test_pagination_with_150_assets_returns_50_of_150(
        self, tenant_client: AsyncClient, admin_a_headers, db_session, seed_data
    ) -> None:
        from app.modules.assets.models import Asset

        # Bulk-insert 150 assets directly into the test DB.
        rows = [
            Asset(
                tenant_id=TENANT_A_ID,
                asset_type="ip",
                value=f"10.0.0.{i % 254 + 1}",  # avoid duplicates by varying
            )
            for i in range(150)
        ]
        # Avoid uniqueness collisions by using unique values.
        seen: set[str] = set()
        for i, row in enumerate(rows):
            value = f"10.0.{i // 254}.{i % 254 + 1}"
            while value in seen:
                i += 1
                value = f"10.0.{i // 254}.{i % 254 + 1}"
            seen.add(value)
            row.value = value
            db_session.add(row)
        await db_session.flush()
        await db_session.commit()

        resp = await tenant_client.get(
            "/api/v1/assets/?limit=50&offset=0", headers=admin_a_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 150, (
            f"total MUST be at least 150 (seeded); got {body['total']}"
        )
        assert body["limit"] == 50
        assert body["offset"] == 0
        assert len(body["items"]) == 50

    @pytest.mark.asyncio
    async def test_limit_500_returns_422(
        self, tenant_client: AsyncClient, admin_a_headers, seed_data
    ) -> None:
        resp = await tenant_client.get(
            "/api/v1/assets/?limit=500", headers=admin_a_headers
        )
        assert resp.status_code == 422, (
            f"limit=500 MUST be 422; got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        # FastAPI surfaces the offending query parameter in the error detail.
        text = resp.text.lower()
        assert "limit" in text, (
            f"422 message MUST mention 'limit'; got {resp.text}"
        )


# ---------------------------------------------------------------------------
# T11.7 — Events spy
# ---------------------------------------------------------------------------
class TestEventsSpy:
    """T11.7 — Mutating endpoints publish exactly one event to ``asset.events``.

    The spy wraps ``EventBus.publish`` on the singleton produced by the
    ``get_event_bus`` dependency. The negative test forces a commit failure
    and asserts that NO event is published.
    """

    @pytest.mark.asyncio
    async def test_post_publishes_asset_created(
        self, tenant_client: AsyncClient, admin_a_headers, seed_data, monkeypatch
    ) -> None:
        from app.dependencies import event_deps

        # Force the singleton to be created (uses the test redis pool).
        bus = await event_deps.get_event_bus()

        calls: list[dict[str, Any]] = []
        original_publish = bus.publish

        async def _spy(event, **kwargs):
            calls.append(
                {
                    "event_type": getattr(event, "event_type", None),
                    "stream": kwargs.get("stream"),
                    "changed_fields": getattr(event, "changed_fields", None),
                    "asset_id": getattr(event, "asset_id", None),
                    "value": getattr(event, "value", None),
                    "type": getattr(event, "type", None),
                }
            )
            return await original_publish(event, **kwargs)

        monkeypatch.setattr(bus, "publish", _spy)

        resp = await tenant_client.post(
            "/api/v1/assets/",
            headers=admin_a_headers,
            json={
                "tenant_id": TENANT_A_ID,
                "type": "ip",
                "value": "192.0.2.100",
            },
        )
        assert resp.status_code == 201, resp.text

        # Exactly one call, on asset.events, with asset.created.
        assert len(calls) == 1, f"Expected 1 publish; got {calls!r}"
        assert calls[0]["stream"] == "asset.events"
        assert calls[0]["event_type"] == "asset.created"
        assert calls[0]["asset_id"] == resp.json()["id"]

    @pytest.mark.asyncio
    async def test_patch_publishes_asset_updated_with_changed_fields(
        self, tenant_client: AsyncClient, admin_a_headers, seed_data, monkeypatch
    ) -> None:
        from app.dependencies import event_deps

        bus = await event_deps.get_event_bus()

        calls: list[dict[str, Any]] = []
        original_publish = bus.publish

        async def _spy(event, **kwargs):
            calls.append(
                {
                    "event_type": getattr(event, "event_type", None),
                    "stream": kwargs.get("stream"),
                    "changed_fields": getattr(event, "changed_fields", None),
                }
            )
            return await original_publish(event, **kwargs)

        monkeypatch.setattr(bus, "publish", _spy)

        created = await tenant_client.post(
            "/api/v1/assets/",
            headers=admin_a_headers,
            json={
                "tenant_id": TENANT_A_ID,
                "type": "ip",
                "value": "192.0.2.101",
            },
        )
        assert created.status_code == 201, created.text
        asset_id = created.json()["id"]
        # Reset spy captures between POST and PATCH so we only observe PATCH.
        calls.clear()

        patched = await tenant_client.patch(
            f"/api/v1/assets/{asset_id}",
            headers=admin_a_headers,
            json={"value": "192.0.2.102"},
        )
        assert patched.status_code == 200, patched.text

        assert len(calls) == 1, f"Expected 1 publish; got {calls!r}"
        assert calls[0]["stream"] == "asset.events"
        assert calls[0]["event_type"] == "asset.updated"
        assert "value" in (calls[0]["changed_fields"] or [])
        assert "type" not in (calls[0]["changed_fields"] or [])

    @pytest.mark.asyncio
    async def test_delete_publishes_asset_deleted(
        self, tenant_client: AsyncClient, admin_a_headers, seed_data, monkeypatch
    ) -> None:
        from app.dependencies import event_deps

        bus = await event_deps.get_event_bus()

        calls: list[dict[str, Any]] = []
        original_publish = bus.publish

        async def _spy(event, **kwargs):
            calls.append(
                {
                    "event_type": getattr(event, "event_type", None),
                    "stream": kwargs.get("stream"),
                }
            )
            return await original_publish(event, **kwargs)

        monkeypatch.setattr(bus, "publish", _spy)

        created = await tenant_client.post(
            "/api/v1/assets/",
            headers=admin_a_headers,
            json={
                "tenant_id": TENANT_A_ID,
                "type": "ip",
                "value": "192.0.2.103",
            },
        )
        assert created.status_code == 201, created.text
        asset_id = created.json()["id"]
        calls.clear()

        deleted = await tenant_client.delete(
            f"/api/v1/assets/{asset_id}", headers=admin_a_headers
        )
        assert deleted.status_code == 204, deleted.text

        assert len(calls) == 1, f"Expected 1 publish; got {calls!r}"
        assert calls[0]["stream"] == "asset.events"
        assert calls[0]["event_type"] == "asset.deleted"

    @pytest.mark.asyncio
    async def test_commit_failure_does_not_publish_event(
        self, tenant_client: AsyncClient, admin_a_headers, seed_data, monkeypatch
    ) -> None:
        """If ``db.commit()`` raises, NO event is published and the API 5xx's.

        We patch ``EventBus.publish`` on the singleton and the service's
        ``db.commit`` to raise ``RuntimeError`` so the publish-after-commit
        invariant is broken. The API MUST surface a 5xx (the exact code
        is not asserted) and the spy MUST NOT record a publish call.
        """
        from app.dependencies import event_deps
        from app.modules.assets import service

        bus = await event_deps.get_event_bus()

        calls: list[dict[str, Any]] = []
        original_publish = bus.publish

        async def _spy(event, **kwargs):
            calls.append({"event_type": getattr(event, "event_type", None)})
            return await original_publish(event, **kwargs)

        monkeypatch.setattr(bus, "publish", _spy)

        async def _boom(*args, **kwargs):
            raise RuntimeError("simulated commit failure for T11.7 negative test")

        monkeypatch.setattr(service, "_real_commit_marker", None, raising=False)
        # Patch the AsyncSession.commit on the class so any session instance
        # raised by the dependency override also fails.
        from sqlalchemy.ext.asyncio import AsyncSession

        original_commit = AsyncSession.commit
        monkeypatch.setattr(
            AsyncSession, "commit", _boom, raising=True
        )
        try:
            resp = await tenant_client.post(
                "/api/v1/assets/",
                headers=admin_a_headers,
                json={
                    "tenant_id": TENANT_A_ID,
                    "type": "ip",
                    "value": "192.0.2.104",
                },
            )
            # Any 5xx is acceptable. 4xx means the router rejected the
            # request before commit, which would defeat the test purpose.
            assert resp.status_code >= 500, (
                f"commit failure MUST yield 5xx; got {resp.status_code}: {resp.text}"
            )
            assert calls == [], (
                f"NO event MUST be published on commit failure; got {calls!r}"
            )
        finally:
            monkeypatch.setattr(AsyncSession, "commit", original_commit, raising=True)


# ---------------------------------------------------------------------------
# T11.8 — Response hygiene
# ---------------------------------------------------------------------------
class TestResponseHygiene:
    """T11.8 — ``AssetResponse`` exposes exactly six public fields."""

    @pytest.mark.asyncio
    async def test_get_by_id_returns_exactly_six_fields(
        self, tenant_client: AsyncClient, admin_a_headers, seed_data
    ) -> None:
        created = await tenant_client.post(
            "/api/v1/assets/",
            headers=admin_a_headers,
            json={
                "tenant_id": TENANT_A_ID,
                "type": "ip",
                "value": "192.0.2.110",
            },
        )
        assert created.status_code == 201, created.text

        resp = await tenant_client.get(
            f"/api/v1/assets/{created.json()['id']}", headers=admin_a_headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body.keys()) == {
            "id",
            "type",
            "value",
            "tenant_id",
            "created_at",
            "updated_at",
        }, f"Response MUST expose exactly six public fields; got {set(body.keys())!r}"
        # The ORM internals MUST NOT leak.
        for forbidden in (
            "status",
            "asset_metadata",
            "created_by_user_id",
            "raw_input",
            "asset_type",
        ):
            assert forbidden not in body, (
                f"Field {forbidden!r} MUST NOT appear in the public response"
            )


# ---------------------------------------------------------------------------
# T11.9 — Semantic validation 422
# ---------------------------------------------------------------------------
class TestSemanticValidation422:
    """T11.9 — Per-type semantic validation MUST map to 422 with the contract message."""

    @pytest.mark.asyncio
    async def test_post_invalid_ip_returns_422(
        self, tenant_client: AsyncClient, admin_a_headers, seed_data
    ) -> None:
        resp = await tenant_client.post(
            "/api/v1/assets/",
            headers=admin_a_headers,
            json={
                "tenant_id": TENANT_A_ID,
                "type": "ip",
                "value": "not-an-ip",
            },
        )
        assert resp.status_code == 422, resp.text
        assert "value must be a valid IPv4 or IPv6 address" in resp.text

    @pytest.mark.asyncio
    async def test_post_invalid_subnet_returns_422(
        self, tenant_client: AsyncClient, admin_a_headers, seed_data
    ) -> None:
        resp = await tenant_client.post(
            "/api/v1/assets/",
            headers=admin_a_headers,
            json={
                "tenant_id": TENANT_A_ID,
                "type": "subnet",
                "value": "192.168.0.0/40",
            },
        )
        assert resp.status_code == 422, resp.text
        assert "value must be a valid CIDR" in resp.text

    @pytest.mark.asyncio
    async def test_post_invalid_domain_returns_422(
        self, tenant_client: AsyncClient, admin_a_headers, seed_data
    ) -> None:
        resp = await tenant_client.post(
            "/api/v1/assets/",
            headers=admin_a_headers,
            json={
                "tenant_id": TENANT_A_ID,
                "type": "domain",
                "value": "-bad-.com",
            },
        )
        assert resp.status_code == 422, resp.text
        assert "value must be a valid FQDN" in resp.text


# ---------------------------------------------------------------------------
# T11.10 — Test suite sanity (the test runner itself runs cleanly)
# ---------------------------------------------------------------------------
# This is enforced implicitly by the pytest invocation:
#   uv run pytest tests/unit/test_assets.py tests/api/test_assets.py -v
# The strict-markers setting in pytest.ini will reject any unregistered
# marker; if we ever add one, the runner will surface the warning.
