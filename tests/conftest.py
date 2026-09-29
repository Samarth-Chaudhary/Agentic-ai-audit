"""Pytest configuration and shared fixtures for foundation test suite."""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
FIXTURES_DIR = PROJECT_ROOT / "fixtures"
SCHEMAS_DIR = PROJECT_ROOT / "schemas"
CONFIG_DIR = PROJECT_ROOT / "config"


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def schemas_dir() -> Path:
    return SCHEMAS_DIR


@pytest.fixture
def config_dir() -> Path:
    return CONFIG_DIR


@pytest.fixture
def valid_trace_dict(fixtures_dir: Path) -> dict:
    with open(fixtures_dir / "valid_trace.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def valid_audit_result_dict(fixtures_dir: Path) -> dict:
    with open(fixtures_dir / "valid_audit_result.json", encoding="utf-8") as f:
        return json.load(f)
