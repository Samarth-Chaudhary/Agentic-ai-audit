"""Policy and configuration loader for AI Agent Governance.

Loads declarative task policies and risk weighting configurations safely using YAML.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class ConfigurationError(Exception):
    """Base exception for configuration loading or validation failures."""


class UnknownTaskTypeError(ConfigurationError):
    """Raised when an unknown or unmapped task_type is requested."""


class PolicyValidationError(ConfigurationError):
    """Raised when policy configuration structure fails schema validation."""


class TaskPolicy(BaseModel):
    """Declarative governance policy for a specific agent task type."""
    description: str | None = Field(default=None, description="Human readable description")
    allowed_tools: list[str] = Field(min_length=0, description="List of permitted tool names")
    allowed_data_sources: list[str] = Field(default_factory=list, description="Permitted data sources")
    max_calls: int = Field(gt=0, description="Maximum total allowed tool executions")
    business_rules: list[str] = Field(default_factory=list, description="Domain business constraints")

    @field_validator("allowed_tools")
    @classmethod
    def validate_tools_list(cls, v: list[str]) -> list[str]:
        return [tool.strip() for tool in v if tool.strip()]


class PoliciesConfig(BaseModel):
    """Container for all registered task policies."""
    version: str = Field(description="Policy schema version")
    policies: dict[str, TaskPolicy] = Field(description="Map of task_type to TaskPolicy")


class ControlWeights(BaseModel):
    """Normalized weights for composite risk scoring."""
    scope_violation: float = Field(default=0.35, ge=0.0, le=1.0)
    pii_leakage: float = Field(default=0.35, ge=0.0, le=1.0)
    groundedness: float = Field(default=0.30, ge=0.0, le=1.0)

    @property
    def scope(self) -> float:
        return self.scope_violation

    @property
    def sensitive_data(self) -> float:
        return self.pii_leakage

    @property
    def pii(self) -> float:
        return self.pii_leakage

    @field_validator("groundedness")
    @classmethod
    def check_weights_sum(cls, v: float, info) -> float:
        # Pydantic v2: info.data contains previously validated fields
        scope = info.data.get("scope_violation", 0.0)
        pii = info.data.get("pii_leakage", 0.0)
        total = round(scope + pii + v, 4)
        if total != 1.0:
            raise ValueError(f"Control weights must sum to 1.0 (got {total})")
        return v


class TierThresholds(BaseModel):
    """Score cutoffs for assigning categorical risk tiers."""
    low: float = Field(ge=0.0, le=100.0)
    medium: float = Field(ge=0.0, le=100.0)
    high: float = Field(ge=0.0, le=100.0)
    critical: float = Field(ge=0.0, le=100.0)

    @field_validator("critical")
    @classmethod
    def check_order(cls, v: float, info) -> float:
        low = info.data.get("low", 0.0)
        medium = info.data.get("medium", 0.0)
        high = info.data.get("high", 0.0)
        if not (low < medium < high <= v):
            raise ValueError("Tier thresholds must be strictly monotonic: low < medium < high <= critical")
        return v


class RiskConfig(BaseModel):
    """Risk scoring engine configuration."""
    version: str = Field(description="Risk config version")
    control_weights: ControlWeights
    tier_thresholds: TierThresholds
    groundedness_similarity_threshold: float = Field(ge=0.0, le=1.0)
    severity_mappings: dict[str, dict[str, str]] = Field(default_factory=dict)


def _find_default_config_path(filename: str) -> Path:
    """Find config file relative to project root or current working directory."""
    candidates = [
        Path.cwd() / "config" / filename,
        Path(__file__).resolve().parent.parent / "config" / filename,
        Path("config") / filename,
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            return p.resolve()
    # Default to first candidate
    return candidates[0]


class PolicyLoader:
    """Safely loads and validates declarative governance task policies and risk configuration."""

    def __init__(
        self,
        task_policy_path: str | Path | None = None,
        risk_config_path: str | Path | None = None,
    ) -> None:
        self.task_policy_path = Path(task_policy_path) if task_policy_path else _find_default_config_path("task_policies.yaml")
        self.risk_config_path = Path(risk_config_path) if risk_config_path else _find_default_config_path("risk_config.yaml")
        self._policies_config: PoliciesConfig | None = None
        self._risk_config: RiskConfig | None = None

    def load_policies_config(self) -> PoliciesConfig:
        """Load and validate all task policies from YAML."""
        if not self.task_policy_path.exists():
            raise ConfigurationError(f"Task policies configuration file not found at: {self.task_policy_path}")

        try:
            with open(self.task_policy_path, encoding="utf-8") as f:
                raw_data = yaml.safe_load(f)
        except Exception as e:
            raise PolicyValidationError(f"Failed to safely parse YAML from {self.task_policy_path}: {e}") from e

        if not isinstance(raw_data, dict):
            raise PolicyValidationError(f"Invalid policies config structure: root must be a mapping, got {type(raw_data).__name__}")

        try:
            self._policies_config = PoliciesConfig.model_validate(raw_data)
        except Exception as e:
            raise PolicyValidationError(f"Validation failed for task policies configuration: {e}") from e

        return self._policies_config

    def get_policy(self, task_type: str) -> TaskPolicy:
        """Resolve and return a deterministic policy for the specified task_type.

        Raises UnknownTaskTypeError if task_type is unknown.
        Never returns an empty or permissive policy.
        """
        if not task_type or not task_type.strip():
            raise UnknownTaskTypeError("task_type must be a non-empty string.")

        if self._policies_config is None:
            self.load_policies_config()

        policies = self._policies_config.policies
        clean_task_type = task_type.strip()

        if clean_task_type not in policies:
            available = sorted(policies.keys())
            raise UnknownTaskTypeError(
                f"Unknown task_type '{clean_task_type}'. No policy is defined for this task. "
                f"Available registered task types: {available}"
            )

        return policies[clean_task_type]

    def load_policy_for_task(self, task_type: str) -> TaskPolicy:
        """Resolve and return a deterministic policy for the specified task_type (alias for get_policy)."""
        return self.get_policy(task_type)

    def load_risk_config(self) -> RiskConfig:
        """Load and validate risk scoring configuration from YAML."""
        if not self.risk_config_path.exists():
            raise ConfigurationError(f"Risk configuration file not found at: {self.risk_config_path}")

        try:
            with open(self.risk_config_path, encoding="utf-8") as f:
                raw_data = yaml.safe_load(f)
        except Exception as e:
            raise PolicyValidationError(f"Failed to safely parse YAML from {self.risk_config_path}: {e}") from e

        if not isinstance(raw_data, dict):
            raise PolicyValidationError(f"Invalid risk config structure: root must be a mapping, got {type(raw_data).__name__}")

        try:
            self._risk_config = RiskConfig.model_validate(raw_data)
        except Exception as e:
            raise PolicyValidationError(f"Validation failed for risk configuration: {e}") from e

        return self._risk_config

    def get_risk_config(self) -> RiskConfig:
        """Return the loaded risk configuration, loading if not already cached."""
        if self._risk_config is None:
            self.load_risk_config()
        return self._risk_config


# Convenience module-level loaders
def load_task_policy(task_type: str, policy_path: str | Path | None = None) -> TaskPolicy:
    """Convenience function to load a deterministic policy for a task type."""
    loader = PolicyLoader(task_policy_path=policy_path)
    return loader.get_policy(task_type)


def load_risk_config(config_path: str | Path | None = None) -> RiskConfig:
    """Convenience function to load risk scoring configuration."""
    loader = PolicyLoader(risk_config_path=config_path)
    return loader.get_risk_config()
