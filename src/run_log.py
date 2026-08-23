"""Structured diagnostic logging for local architecture runs.

The orchestrator retries structured output and can exhaust its attempts. When
that happens the operator needs to know which role failed, in which round, and
why. Only bounded, structural facts are recorded: model output is summarised by
length and a short excerpt rather than stored verbatim, so run logs stay small
and do not silently accumulate full transcripts.

Logging is opt-in. Without an explicit handler configured by the application,
records go nowhere.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
from typing import Any


LOGGER_NAME = "azure_architect.run"
_MAX_EXCERPT_CHARS = 240

logger = logging.getLogger(LOGGER_NAME)
# The application owns handler configuration; a library-style null handler keeps
# records from reaching the root logger by default.
logger.addHandler(logging.NullHandler())


@dataclass(frozen=True, slots=True)
class AttemptFailure:
    """One failed structured-output attempt, described without raw content."""

    run_id: str
    role: str
    phase: str
    review_round: int
    attempt: int
    max_attempts: int
    error_type: str
    error_message: str
    raw_output_chars: int
    raw_output_excerpt: str
    recorded_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def as_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


def _excerpt(raw: str) -> str:
    """Return a bounded, single-line excerpt of untrusted model output."""

    collapsed = " ".join(raw.split())
    if len(collapsed) <= _MAX_EXCERPT_CHARS:
        return collapsed
    return f"{collapsed[:_MAX_EXCERPT_CHARS]}…"


def log_attempt_failure(
    *,
    run_id: str,
    role: str,
    phase: str,
    review_round: int,
    attempt: int,
    max_attempts: int,
    error: BaseException,
    raw_output: str,
) -> AttemptFailure:
    """Record one failed parse/validation attempt and return the record."""

    record = AttemptFailure(
        run_id=run_id,
        role=role,
        phase=phase,
        review_round=review_round,
        attempt=attempt,
        max_attempts=max_attempts,
        error_type=type(error).__name__,
        error_message=str(error),
        raw_output_chars=len(raw_output),
        raw_output_excerpt=_excerpt(raw_output),
    )
    logger.warning(
        "structured output rejected: run=%s role=%s phase=%s round=%s "
        "attempt=%s/%s error=%s chars=%s",
        record.run_id,
        record.role,
        record.phase,
        record.review_round,
        record.attempt,
        record.max_attempts,
        record.error_type,
        record.raw_output_chars,
        extra={"diagnostic": record.as_json()},
    )
    return record


def log_run_failure(
    *,
    run_id: str,
    error: BaseException,
    review_rounds_completed: int,
) -> None:
    """Record a run that ended without a usable architecture plan."""

    logger.error(
        "run failed: run=%s rounds=%s error=%s: %s",
        run_id,
        review_rounds_completed,
        type(error).__name__,
        error,
    )


def summarize_failures(failures: list[AttemptFailure]) -> dict[str, Any]:
    """Aggregate attempt failures so the UI can show why a run gave up."""

    by_reason: dict[str, int] = {}
    for failure in failures:
        by_reason[failure.error_message] = by_reason.get(failure.error_message, 0) + 1
    return {
        "total_failed_attempts": len(failures),
        "roles": sorted({failure.role for failure in failures}),
        "rounds": sorted({failure.review_round for failure in failures}),
        "reasons": by_reason,
    }
