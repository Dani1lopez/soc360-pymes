"""Tests for app/main.py — security integration guards."""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.main import create_app


class TestMainSecurityIntegration:
    """Validate production vs development guards in FastAPI bootstrap."""

    def test_docs_url_none_in_production(self, monkeypatch: pytest.MonkeyPatch):
        """docs_url MUST be None when ENVIRONMENT=production."""
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        app = create_app()
        assert app.docs_url is None

    def test_docs_url_present_in_development(self, monkeypatch: pytest.MonkeyPatch):
        """docs_url MUST retain its configured value when ENVIRONMENT=development."""
        monkeypatch.setattr(settings, "ENVIRONMENT", "development")
        app = create_app()
        assert app.docs_url == "/api/docs"

    def test_redoc_url_none_in_production(self, monkeypatch: pytest.MonkeyPatch):
        """redoc_url MUST be None when ENVIRONMENT=production."""
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        app = create_app()
        assert app.redoc_url is None
