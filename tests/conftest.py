from __future__ import annotations

from pathlib import Path

import pytest

from bethero_nba import config

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def cfg() -> config.Config:
    return config.load(ROOT / "rules" / "nba" / "config.yaml")
