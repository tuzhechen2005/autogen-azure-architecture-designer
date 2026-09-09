"""Task 3 adapter for shared Phase 7 collaboration evidence contracts."""

from __future__ import annotations

import hashlib
import resource
import sys
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from .schemas import ArchitectureRunResult, MessagePhase, RunStatus, TerminationReason


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHARED_ROOT = PROJECT_ROOT.parent.parent / "微软" / "微软task1 & 2"
SHARED_EVALUATION = SHARED_ROOT / "evaluation"
TRACE_SCHEMA = SHARED_EVALUATION / "contracts" / "trace_event.schema.json"
ERROR_TAXONOMY = SHARED_EVALUATION / "contracts" / "error_taxonomy.yaml"
SECURITY_CANARIES = SHARED_EVALUATION / "contracts" / "security_canaries.yaml"
FAULT_SCHEMA = SHARED_EVALUATION / "contracts" / "fault_injection_case.schema.json"
STATE_RULES = PROJECT_ROOT / "data" / "state_transition_rules.json"
SCHEMA_VERSION = "task3-collaboration-v1"
PROMPT_VERSION = "task3-collaboration-v1"
CACHE_VERSION = "task3-no-content-cache-v1"
SECURITY_DOMAIN = "local-private-architecture"
REDACTED = "[REDACTED]"

_PHASE_STEPS = {
    MessagePhase.INITIAL_PLAN: "planning",
    MessagePhase.REVIEW: "review",
    MessagePhase.REVISION: "revision",
}
_TERMINAL_STATES = {
    RunStatus.COMPLETED: "completed",
    RunStatus.DEGRADED: "degraded",
    RunStatus.TIMEOUT: "timeout",
    RunStatus.FAILED: "failed",
}
_TERMINAL_ERRORS = {
    TerminationReason.APPROVED: None,
    TerminationReason.MAX_REVIEW_ROUNDS: "state",
    TerminationReason.NO_PROGRESS: "state",
    TerminationReason.TIMEOUT: "timeout",
    TerminationReason.ERROR: "model",
}


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"required contract is missing: {path.name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_shared_manifest_extension() -> dict[str, str]:
    """Pin shared contracts and the Task 3 state-machine catalog."""
    return {
        "contract_version": "phase7-v1",
        "trace_schema_sha256": _sha256(TRACE_SCHEMA),
        "error_taxonomy_sha256": _sha256(ERROR_TAXONOMY),
        "security_canaries_sha256": _sha256(SECURITY_CANARIES),
        "fault_schema_sha256": _sha256(FAULT_SCHEMA),
        "state_rules_sha256": _sha256(STATE_RULES),
        "schema_version": SCHEMA_VERSION,
        "cache_version": CACHE_VERSION,
        "security_domain": SECURITY_DOMAIN,
    }


def build_loop_fault_case(*, timeout_ms: float) -> dict[str, Any]:
    """Describe the repeated-review loop fault using the shared fault schema."""
    return {
        "case_id": "task3-repeated-review-no-progress",
        "task": "task3",
        "category": "state",
        "injection_point": "reviewer.required_changes",
        "stimulus": "repeat the same validated required_changes after one revision",
        "expected_retry_max": 0,
        "expected_terminal": "degraded",
        "expected_error_category": "state",
        "preserve_data": True,
        "trace_steps": ["planning", "review", "revision", "review", "termination"],
        "timeout_ms": timeout_ms,
    }


@lru_cache(maxsize=1)
def _shared_canary_values() -> tuple[str, ...]:
    if str(SHARED_ROOT) not in sys.path:
        sys.path.insert(0, str(SHARED_ROOT))
    from evaluation.contract_validator import load_canary_registry

    registry = load_canary_registry(SECURITY_CANARIES)
    return tuple(str(value) for value in registry["canaries"].values())


def redact_evidence(value: Any) -> Any:
    """Remove exact shared canaries while retaining evidence structure."""
    if isinstance(value, str):
        result = value
        for canary in _shared_canary_values():
            result = result.replace(canary, REDACTED)
        return result
    if isinstance(value, dict):
        return {str(key): redact_evidence(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_evidence(item) for item in value]
    return value


def _retry_decision(*, valid: bool, has_later_attempt: bool) -> str:
    if valid:
        return "none"
    return "retry" if has_later_attempt else "exhausted"


def _terminal_retry_decision(reason: TerminationReason) -> str:
    if reason is TerminationReason.APPROVED:
        return "none"
    if reason is TerminationReason.NO_PROGRESS:
        return "blocked"
    return "exhausted"


def _validate_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if str(SHARED_ROOT) not in sys.path:
        sys.path.insert(0, str(SHARED_ROOT))
    from evaluation.contract_validator import validate_trace_event

    safe_events: list[dict[str, Any]] = []
    for event in events:
        safe_event = redact_evidence(event)
        if not isinstance(safe_event, dict):
            raise TypeError("shared trace event must remain an object")
        validate_trace_event(safe_event)
        safe_events.append(safe_event)
    return safe_events


def build_task3_trace_events(
    result: ArchitectureRunResult,
    *,
    trace_id: str,
    model: str,
    prompt_version: str,
) -> list[dict[str, Any]]:
    """Convert bounded collaboration messages and terminal state to shared spans."""
    peak_rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    groups: dict[tuple[str, str, int], list[int]] = {}
    for index, message in enumerate(result.messages):
        key = (message.role.value, message.phase.value, message.review_round)
        groups.setdefault(key, []).append(index)

    events: list[dict[str, Any]] = []
    attempts_seen: dict[tuple[str, str, int], int] = {}
    for index, message in enumerate(result.messages):
        key = (message.role.value, message.phase.value, message.review_round)
        attempt = attempts_seen.get(key, 0)
        attempts_seen[key] = attempt + 1
        if attempt > 2:
            raise ValueError("structured parse retry attempt cannot exceed two")
        has_later_attempt = index != groups[key][-1]
        ended_at = message.created_at
        started_at = ended_at - timedelta(milliseconds=message.duration_ms)
        valid = message.validation_status == "valid"
        duration_ms = float(message.duration_ms)
        events.append(
            {
                "trace_id": trace_id,
                "run_id": result.run_id,
                "task": "task3",
                "step": _PHASE_STEPS[message.phase],
                "start_at": started_at.isoformat(),
                "end_at": ended_at.isoformat(),
                "duration_ms": duration_ms,
                "model": model,
                "prompt_version": prompt_version,
                "input_hash": message.input_summary_sha256,
                "validation": {
                    "status": "passed" if valid else "failed",
                    "schema_version": SCHEMA_VERSION,
                    "error_category": message.validation_error_category,
                },
                "retry": {
                    "attempt": attempt,
                    "max_retries": 2,
                    "decision": _retry_decision(
                        valid=valid,
                        has_later_attempt=has_later_attempt,
                    ),
                },
                "cache": {
                    "status": "bypass",
                    "key_version": CACHE_VERSION,
                    "reason": "collaboration_generation_is_not_content_cacheable",
                },
                "termination": {
                    "state": "running",
                    "reason": message.phase.value,
                },
                "resource_usage": {
                    "wall_ms": duration_ms,
                    "peak_rss_bytes": peak_rss,
                    "input_tokens": message.prompt_tokens,
                    "output_tokens": message.completion_tokens,
                },
            }
        )

    terminal_error = _TERMINAL_ERRORS[result.termination_reason]
    if result.termination_reason is TerminationReason.ERROR and result.request is None:
        terminal_error = "input"
    elif (
        result.termination_reason is TerminationReason.ERROR
        and result.messages
        and result.messages[-1].validation_status == "invalid"
    ):
        terminal_error = result.messages[-1].validation_error_category
    request_hash = hashlib.sha256(
        (
            result.request.requirements if result.request is not None else result.run_id
        ).encode()
    ).hexdigest()
    events.append(
        {
            "trace_id": trace_id,
            "run_id": result.run_id,
            "task": "task3",
            "step": "termination",
            "start_at": result.finished_at.isoformat(),
            "end_at": result.finished_at.isoformat(),
            "duration_ms": 0.0,
            "model": model,
            "prompt_version": prompt_version,
            "input_hash": request_hash,
            "validation": {
                "status": "passed" if terminal_error is None else "failed",
                "schema_version": SCHEMA_VERSION,
                "error_category": terminal_error,
            },
            "retry": {
                "attempt": 0,
                "max_retries": 2,
                "decision": _terminal_retry_decision(result.termination_reason),
            },
            "cache": {
                "status": "bypass",
                "key_version": CACHE_VERSION,
                "reason": "terminal_state_is_not_cacheable",
            },
            "termination": {
                "state": _TERMINAL_STATES[result.status],
                "reason": result.termination_reason.value,
            },
            "resource_usage": {
                "wall_ms": 0.0,
                "peak_rss_bytes": peak_rss,
                "input_tokens": None,
                "output_tokens": None,
            },
        }
    )
    return _validate_events(events)
