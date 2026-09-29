"""External trace format adapters for ingesting non-native agent execution telemetry."""

from __future__ import annotations

from auditor.adapters.opentelemetry_adapter import OpenTelemetryGenAIAdapter

__all__ = ["OpenTelemetryGenAIAdapter"]
