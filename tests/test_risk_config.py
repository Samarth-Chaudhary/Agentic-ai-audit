"""Foundation tests for Risk Configuration loading and validation."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from auditor.policy_loader import (
    ControlWeights,
    PolicyLoader,
    RiskConfig,
    TierThresholds,
    load_risk_config,
)


def test_risk_config_loading_success(config_dir: Path):
    """Ensure risk_config.yaml loads correctly with all required sections."""
    loader = PolicyLoader(risk_config_path=config_dir / "risk_config.yaml")
    risk_config = loader.load_risk_config()

    assert isinstance(risk_config, RiskConfig)
    assert risk_config.version == "1.0.0"
    assert risk_config.control_weights.scope_violation == 0.35
    assert risk_config.control_weights.scope == 0.35
    assert risk_config.control_weights.pii_leakage == 0.35
    assert risk_config.control_weights.sensitive_data == 0.35
    assert risk_config.control_weights.groundedness == 0.30
    assert risk_config.tier_thresholds.low == 20.0
    assert risk_config.tier_thresholds.critical == 100.0
    assert risk_config.groundedness_similarity_threshold == 0.70


def test_severity_mappings_present(config_dir: Path):
    """Ensure severity mappings are defined for scope, pii, and groundedness."""
    risk_config = load_risk_config(config_path=config_dir / "risk_config.yaml")

    assert "scope" in risk_config.severity_mappings
    assert "pii" in risk_config.severity_mappings
    assert "groundedness" in risk_config.severity_mappings

    assert risk_config.severity_mappings["scope"]["unauthorized_tool"] == "HIGH"
    assert risk_config.severity_mappings["pii"]["SSN"] == "CRITICAL"
    assert risk_config.severity_mappings["groundedness"]["unsupported_claim"] == "HIGH"


def test_control_weights_validation_fails_if_not_sum_one():
    """Ensure ControlWeights validator catches invalid weights sum."""
    with pytest.raises(ValidationError) as exc:
        ControlWeights(scope_violation=0.5, pii_leakage=0.5, groundedness=0.5)
    assert "Control weights must sum to 1.0" in str(exc.value)


def test_tier_thresholds_validation_fails_if_unordered():
    """Ensure TierThresholds validator catches non-monotonic thresholds."""
    with pytest.raises(ValidationError) as exc:
        TierThresholds(low=50.0, medium=30.0, high=80.0, critical=100.0)
    assert "strictly monotonic" in str(exc.value)
