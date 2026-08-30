"""Persist private, per-run architecture traces with atomic publication."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import stat
import threading

from .schemas import ArchitectureRunResult


_SAFE_RUN_ID = re.compile(r"[A-Za-z0-9_-]{8,80}\Z")
_TRACE_WRITE_LOCK = threading.Lock()


def _open_private_directory(output_directory: Path) -> tuple[int, Path]:
    """Create/open a directory without following symlinks in any path component."""

    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory_flag is None:
        raise OSError("Secure trace storage is unsupported on this platform")

    absolute = Path(os.path.abspath(output_directory))
    if absolute == Path(absolute.anchor):
        raise OSError("Trace output must use a dedicated directory")

    current_fd = os.open(absolute.anchor, os.O_RDONLY | directory_flag)
    try:
        relative_parts = absolute.parts[1:]
        for index, part in enumerate(relative_parts):
            try:
                os.mkdir(part, mode=0o700, dir_fd=current_fd)
            except FileExistsError:
                pass
            next_fd = os.open(
                part,
                os.O_RDONLY | directory_flag | no_follow,
                dir_fd=current_fd,
            )
            metadata = os.fstat(next_fd)
            if not stat.S_ISDIR(metadata.st_mode):
                os.close(next_fd)
                raise OSError("Trace path component is not a directory")
            os.close(current_fd)
            current_fd = next_fd
            if index == len(relative_parts) - 1:
                os.fchmod(current_fd, 0o700)
        return current_fd, absolute
    except BaseException:
        os.close(current_fd)
        raise


def _redacted_record(result: ArchitectureRunResult) -> dict[str, object]:
    """Keep operational evidence without storing requirements or model text."""

    record = result.model_dump(mode="json")
    plan = record.get("final_plan")
    review = record.get("final_review")
    spans: list[dict[str, object]] = []
    for message in record.get("messages") or []:
        if not isinstance(message, dict):
            continue
        parsed = message.get("parsed_content")
        spans.append(
            {
                "sequence": message.get("sequence"),
                "review_round": message.get("review_round"),
                "role": message.get("role"),
                "phase": message.get("phase"),
                "input_summary_sha256": message.get("input_summary_sha256"),
                "raw_output_sha256": message.get("raw_output_sha256"),
                "duration_ms": message.get("duration_ms"),
                "prompt_tokens": message.get("prompt_tokens"),
                "completion_tokens": message.get("completion_tokens"),
                "validation_status": message.get("validation_status"),
                "resource_count": (
                    len(parsed.get("resources") or []) if isinstance(parsed, dict) else None
                ),
                "finding_count": (
                    len(parsed.get("findings") or []) if isinstance(parsed, dict) else None
                ),
                "required_change_count": (
                    len(parsed.get("required_changes") or []) if isinstance(parsed, dict) else None
                ),
            }
        )
    return {
        "run_id": record.get("run_id"),
        "status": record.get("status"),
        "termination_reason": record.get("termination_reason"),
        "review_rounds_completed": record.get("review_rounds_completed"),
        "started_at": record.get("started_at"),
        "finished_at": record.get("finished_at"),
        "message_count": len(record.get("messages") or []),
        "spans": spans,
        "plan_revision": plan.get("revision") if isinstance(plan, dict) else None,
        "review_decision": (
            review.get("decision") if isinstance(review, dict) else None
        ),
        "has_error": bool(record.get("error")),
        "review_resolutions": record.get("review_resolutions") or [],
        "sensitive_content_included": False,
    }


def save_trace(
    result: ArchitectureRunResult,
    output_directory: Path,
    *,
    include_sensitive_content: bool = False,
) -> Path:
    """Atomically publish one private JSON file and return its absolute path."""

    run_id = result.run_id
    if _SAFE_RUN_ID.fullmatch(run_id) is None:
        raise ValueError("Run ID is unsafe for trace storage")
    record = (
        result.model_dump(mode="json")
        if include_sensitive_content
        else _redacted_record(result)
    )
    if include_sensitive_content:
        record["sensitive_content_included"] = True
    serialized = json.dumps(
        record,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    final_name = f"{run_id}.json"
    temporary_name = f".tmp-{run_id}-{secrets.token_hex(8)}"
    with _TRACE_WRITE_LOCK:
        directory_fd, absolute_directory = _open_private_directory(output_directory)
        temporary_fd: int | None = None
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
            temporary_fd = os.open(
                temporary_name,
                flags,
                0o600,
                dir_fd=directory_fd,
            )
            os.fchmod(temporary_fd, 0o600)
            view = memoryview(serialized)
            while view:
                written = os.write(temporary_fd, view)
                if written <= 0:
                    raise OSError("Trace write made no progress")
                view = view[written:]
            os.fsync(temporary_fd)
            os.close(temporary_fd)
            temporary_fd = None

            # Hard-link publication is atomic and refuses to overwrite an
            # existing run file, including a malicious symbolic link.
            os.link(
                temporary_name,
                final_name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
            os.unlink(temporary_name, dir_fd=directory_fd)
            os.fsync(directory_fd)
            return absolute_directory / final_name
        except BaseException:
            if temporary_fd is not None:
                os.close(temporary_fd)
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            raise
        finally:
            os.close(directory_fd)
