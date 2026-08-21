"""Application configuration loaded from explicit values or environment variables."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when local runtime configuration is missing or invalid."""


MIN_GGUF_BYTES = 1024 * 1024
MAX_GGUF_BYTES = 64 * 1024 * 1024 * 1024


def trusted_model_root_from_env() -> Path:
    """Return the operator-controlled directory allowed to contain model files."""

    configured_root = os.getenv("PHI3_MODEL_ROOT", "").strip()
    if configured_root:
        return Path(configured_root).expanduser()
    configured_model = os.getenv("PHI3_MODEL_PATH", "").strip()
    if configured_model:
        candidate = Path(configured_model).expanduser()
        if candidate.is_absolute():
            return candidate.parent
    return Path("models").resolve()


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
    model_root: Path | None = None
    n_ctx: int = 4096
    max_tokens: int = 768
    temperature: float = 0.0
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
            model_root=trusted_model_root_from_env(),
            n_ctx=_read_int("PHI3_N_CTX", 4096),
            max_tokens=_read_int("PHI3_MAX_TOKENS", 768),
            temperature=_read_float("PHI3_TEMPERATURE", 0.0),
            n_gpu_layers=_read_int("PHI3_N_GPU_LAYERS", -1),
            max_review_rounds=_read_int("ARCHITECTURE_MAX_REVIEW_ROUNDS", 2),
            seed=_read_int("PHI3_SEED", 42),
        )
        config.validate(require_model=require_model)
        return config

    def validate(self, *, require_model: bool = True) -> None:
        if require_model:
            self._validate_model_file()
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

    def _validate_model_file(self) -> None:
        path = self.model_path.expanduser()
        if not path.is_absolute():
            raise ConfigurationError("Local model path must be absolute")
        if path.suffix.lower() != ".gguf":
            raise ConfigurationError("Local model must use the .gguf extension")
        if self.model_root is None:
            raise ConfigurationError("PHI3_MODEL_ROOT must be configured")

        try:
            root = self.model_root.expanduser().resolve(strict=True)
            if not root.is_dir():
                raise ConfigurationError("Configured model root is not a directory")
            if path.is_symlink():
                raise ConfigurationError("Symbolic-link model paths are not allowed")
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root):
                raise ConfigurationError("Local model is outside the configured root")

            flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(resolved, flags)
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise ConfigurationError("Local model must be a regular file")
                if not MIN_GGUF_BYTES <= metadata.st_size <= MAX_GGUF_BYTES:
                    raise ConfigurationError("Local model size is outside safe bounds")
                magic = os.read(descriptor, 4)
                if magic != b"GGUF":
                    raise ConfigurationError("Local model does not have GGUF magic")
            finally:
                os.close(descriptor)
        except ConfigurationError:
            raise
        except OSError as exc:
            raise ConfigurationError(
                "Local model path is unavailable or unsafe"
            ) from exc
