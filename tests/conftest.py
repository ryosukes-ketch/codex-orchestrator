from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _set_required_env() -> None:
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/macro_release_scanner_test")
    os.environ.setdefault("LOG_LEVEL", "INFO")


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
