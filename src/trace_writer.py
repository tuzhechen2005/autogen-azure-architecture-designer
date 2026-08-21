"""Append complete, local-only architecture run records to JSONL."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .schemas import ArchitectureRunResult


def append_trace(result: ArchitectureRunResult, output_path: Path) -> None:
    """Append and fsync one validated run without changing prior records."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    record = result.model_dump(mode="json")
    serialized = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    with output_path.open("a", encoding="utf-8") as output_file:
        output_file.write(serialized + "\n")
        output_file.flush()
        os.fsync(output_file.fileno())
