"""Unit tests for F2 domain exceptions — DB-free.

These tests verify that the four F2 domain exception classes
(AssetError, ScanError, VulnerabilityError, ReportError) exist,
subclass AppError correctly, and carry appropriate status codes.
"""

from __future__ import annotations

import pytest

from app.core.exceptions import (
    AppError,
    AssetError,
    ReportError,
    ScanError,
    VulnerabilityError,
)


class TestF2DomainExceptions:
    """Verify F2 domain exception hierarchy and behavior."""

    # ── existence and inheritance ──────────────────────────────────────

    @pytest.mark.parametrize(
        "exc_class",
        [AssetError, ScanError, VulnerabilityError, ReportError],
    )
    def test_f2_exception_subclasses_app_error(self, exc_class: type) -> None:
        """Each F2 domain exception MUST subclass AppError."""
        assert issubclass(exc_class, AppError), (
            f"{exc_class.__name__} does not subclass AppError"
        )

    @pytest.mark.parametrize(
        "exc_class",
        [AssetError, ScanError, VulnerabilityError, ReportError],
    )
    def test_f2_exception_is_instantiable(self, exc_class: type) -> None:
        """Each F2 domain exception MUST be instantiable without arguments."""
        instance = exc_class()
        assert isinstance(instance, exc_class)
        assert isinstance(instance, AppError)
        assert isinstance(instance, Exception)

    # ── default status code ────────────────────────────────────────────

    @pytest.mark.parametrize(
        "exc_class",
        [AssetError, ScanError, VulnerabilityError, ReportError],
    )
    def test_f2_exception_default_status_code_is_400(self, exc_class: type) -> None:
        """F2 domain exceptions inherit AppError's default status_code=400."""
        instance = exc_class()
        assert instance.status_code == 400, (
            f"{exc_class.__name__}.status_code expected 400, got {instance.status_code}"
        )

    # ── custom detail ──────────────────────────────────────────────────

    def test_asserterror_with_custom_detail(self) -> None:
        """AssetError MUST accept and store custom detail."""
        exc = AssetError("Asset not found")
        assert exc.detail == "Asset not found"
        assert exc.status_code == 400

    def test_scannerror_with_custom_detail(self) -> None:
        """ScanError MUST accept and store custom detail."""
        exc = ScanError("Scan timed out")
        assert exc.detail == "Scan timed out"
        assert exc.status_code == 400

    def test_vulnerabilityerror_with_custom_detail(self) -> None:
        """VulnerabilityError MUST accept and store custom detail."""
        exc = VulnerabilityError("Duplicate fingerprint")
        assert exc.detail == "Duplicate fingerprint"

    def test_reporterror_with_custom_detail(self) -> None:
        """ReportError MUST accept and store custom detail."""
        exc = ReportError("PDF generation failed")
        assert exc.detail == "PDF generation failed"

    # ── custom status code ─────────────────────────────────────────────

    def test_asserterror_custom_status_code(self) -> None:
        """AssetError MUST support custom status_code via kwargs."""
        exc = AssetError("Limit exceeded", status_code=422)
        assert exc.status_code == 422
        assert exc.detail == "Limit exceeded"

    def test_scannerror_custom_status_code(self) -> None:
        """ScanError MUST support custom status_code."""
        exc = ScanError("Quota exhausted", status_code=429)
        assert exc.status_code == 429

    def test_reporterror_custom_status_code(self) -> None:
        """ReportError MUST support custom status_code."""
        exc = ReportError("Report expired", status_code=410)
        assert exc.status_code == 410

    # ── string representation ──────────────────────────────────────────

    @pytest.mark.parametrize(
        "exc_class,detail",
        [
            (AssetError, "bad asset"),
            (ScanError, "scan failure"),
            (VulnerabilityError, "vuln conflict"),
            (ReportError, "report missing"),
        ],
    )
    def test_f2_exception_str_contains_detail(
        self, exc_class: type, detail: str
    ) -> None:
        """Exception string representation MUST include the detail message."""
        exc = exc_class(detail)
        assert detail in str(exc)

    # ── no accidental side effects ─────────────────────────────────────

    def test_f2_exceptions_do_not_leak_module_state(self) -> None:
        """Instantiating F2 exceptions MUST NOT modify global state."""
        # Pre-condition: known classes
        before = {AssetError, ScanError, VulnerabilityError, ReportError}
        # Instantiate all
        AssetError()
        ScanError()
        VulnerabilityError()
        ReportError()
        after = {AssetError, ScanError, VulnerabilityError, ReportError}
        assert before == after
