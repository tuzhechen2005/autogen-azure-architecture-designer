"""Application configuration loaded from explicit values or environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when local runtime configuration is missing or invalid."""


def _read_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer, got {raw!r}") from exc


def _read_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number, got {raw!r}") from exc


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Runtime settings for the local model and collaboration loop."""

    model_path: Path
    n_ctx: int = 4096
    max_tokens: int = 768
    temperature: float = 0.1
    n_gpu_layers: int = -1
    max_review_rounds: int = 2
    seed: int = 42

    @classmethod
    def from_env(cls, *, require_model: bool = True) -> "AppConfig":
        raw_model_path = os.getenv("PHI3_MODEL_PATH", "").strip()
        if require_model and not raw_model_path:
            raise ConfigurationError(
                "PHI3_MODEL_PATH is required and must point to a local GGUF file"
            )

        model_path = Path(raw_model_path).expanduser() if raw_model_path else Path()
        config = cls(
            model_path=model_path,
            n_ctx=_read_int("PHI3_N_CTX", 4096),
            max_tokens=_read_int("PHI3_MAX_TOKENS", 768),
            temperature=_read_float("PHI3_TEMPERATURE", 0.1),
            n_gpu_layers=_read_int("PHI3_N_GPU_LAYERS", -1),
            max_review_rounds=_read_int("ARCHITECTURE_MAX_REVIEW_ROUNDS", 2),
            seed=_read_int("PHI3_SEED", 42),
        )
        config.validate(require_model=require_model)
        return config

    def validate(self, *, require_model: bool = True) -> None:
        if require_model and (not self.model_path.is_file()):
            raise ConfigurationError(
                f"Local model file does not exist: {self.model_path}"
            )
        if self.n_ctx < 1024:
            raise ConfigurationError("PHI3_N_CTX must be at least 1024")
        if not 1 <= self.max_tokens < self.n_ctx:
            raise ConfigurationError("PHI3_MAX_TOKENS must be between 1 and n_ctx - 1")
        if not 0.0 <= self.temperature <= 2.0:
            raise ConfigurationError("PHI3_TEMPERATURE must be between 0 and 2")
        if not 1 <= self.max_review_rounds <= 5:
            raise ConfigurationError(
                "ARCHITECTURE_MAX_REVIEW_ROUNDS must be between 1 and 5"
            )
