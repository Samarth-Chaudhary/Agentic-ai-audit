"""Foundation tests for Task Policy loader and deterministic resolution."""

import tempfile
from pathlib import Path

import pytest

from auditor.policy_loader import (
    ConfigurationError,
    PolicyLoader,
    PolicyValidationError,
    TaskPolicy,
    UnknownTaskTypeError,
    load_task_policy,
)


def test_policy_loading_success(config_dir: Path):
    """Ensure task_policies.yaml loads and validates all declared policies."""
    loader = PolicyLoader(task_policy_path=config_dir / "task_policies.yaml")
    config = loader.load_policies_config()

    assert config.version == "1.0.0"
    assert "customer_support" in config.policies
    assert "data_retrieval" in config.policies
    assert "financial_reporting" in config.policies


def test_policy_deterministic_content(config_dir: Path):
    """Ensure resolved policy object returns deterministic values matching configuration."""
    loader = PolicyLoader(task_policy_path=config_dir / "task_policies.yaml")
    policy = loader.get_policy("customer_support")

    assert isinstance(policy, TaskPolicy)
    assert "lookup_order_status" in policy.allowed_tools
    assert "search_knowledge_base" in policy.allowed_tools
    assert "customer_orders_api" in policy.allowed_data_sources
    assert policy.max_calls == 10
    assert "no_direct_refunds" in policy.business_rules


def test_unknown_task_type_raises_error(config_dir: Path):
    """Ensure unknown task types raise UnknownTaskTypeError and NEVER silently return empty/permissive."""
    loader = PolicyLoader(task_policy_path=config_dir / "task_policies.yaml")

    with pytest.raises(UnknownTaskTypeError) as exc_info:
        loader.get_policy("rogue_autonomous_task")

    msg = str(exc_info.value)
    assert "rogue_autonomous_task" in msg
    assert "Available registered task types" in msg


def test_empty_or_whitespace_task_type_raises_error(config_dir: Path):
    """Ensure empty or whitespace task types raise error immediately."""
    loader = PolicyLoader(task_policy_path=config_dir / "task_policies.yaml")

    with pytest.raises(UnknownTaskTypeError):
        loader.get_policy("")

    with pytest.raises(UnknownTaskTypeError):
        loader.get_policy("   ")


def test_load_task_policy_convenience_function(config_dir: Path):
    """Ensure module-level helper loads correct policy."""
    policy = load_task_policy("data_retrieval", policy_path=config_dir / "task_policies.yaml")
    assert "execute_sql_query" in policy.allowed_tools
    assert policy.max_calls == 15


def test_malformed_yaml_raises_validation_error():
    """Ensure malformed YAML or schema invalid policy raises PolicyValidationError."""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tmp:
        tmp.write("invalid: [broken yaml: 123")
        tmp_path = Path(tmp.name)

    try:
        loader = PolicyLoader(task_policy_path=tmp_path)
        with pytest.raises(PolicyValidationError):
            loader.load_policies_config()
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def test_missing_file_raises_configuration_error():
    """Ensure pointing to non-existent policy file raises ConfigurationError."""
    loader = PolicyLoader(task_policy_path=Path("non_existent_dir/task_policies.yaml"))
    with pytest.raises(ConfigurationError):
        loader.load_policies_config()
