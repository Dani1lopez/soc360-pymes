"""S7 — Nmap process supervision is on unless a deployment turns it off.

Supervision wraps every Nmap run in ``setpriv --pdeathsig TERM timeout``, so an
orphaned child cannot outlive the worker. Secure by default means the settings
default is ``True`` and only an explicit opt-out disables it.
"""

from __future__ import annotations

import pytest


def test_nmap_supervision_defaults_to_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.delenv("NMAP_PROCESS_SUPERVISION", raising=False)

    assert Settings().NMAP_PROCESS_SUPERVISION is True


def test_nmap_supervision_can_be_turned_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("NMAP_PROCESS_SUPERVISION", "false")

    assert Settings().NMAP_PROCESS_SUPERVISION is False
