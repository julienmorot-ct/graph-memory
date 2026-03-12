# -*- coding: utf-8 -*-
"""
MCP Memory Service — Pytest configuration & shared fixtures.
"""

import pytest


@pytest.fixture
def anyio_backend():
    """Force asyncio as the async backend for all async tests."""
    return "asyncio"
