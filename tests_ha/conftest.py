"""Shared fixtures for the tests that boot a real Home Assistant."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant discover custom_components/gaming_assistant."""
    yield


@pytest.fixture
def expected_lingering_timers() -> bool:
    """Allow lingering timers in these tests.

    Home Assistant's own mqtt component (provided here by ``mqtt_mock``)
    schedules a self-rescheduling "misc periodic" timer while connected. It is
    not owned by this integration and cannot be cancelled from the config entry,
    so it would otherwise trip pytest-hacc's cleanup guard.
    """
    return True
