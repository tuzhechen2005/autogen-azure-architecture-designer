"""Deterministic parsing for JSON text returned by the local Phi-3 model."""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class StructuredOutputError(ValueError):
    """Raised when a model response cannot satisfy the requested schema."""


_OUTER_FENCE = re.compile(
    r"^\s*```(?:json)?\s*(?P<body>.*?)\s*```\s*$", re.IGNORECASE | re.DOTALL
)


def _strip_outer_fence(raw: str) -> str:
    match = _OUTER_FENCE.match(raw)
    return match.group("body") if match else raw.strip()


def _reject_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise StructuredOutputError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def extract_json_object(raw: str) -> dict[str, object]:
    """Decode exactly one complete top-level JSON object."""

    if not isinstance(raw, str) or not raw.strip():
        raise StructuredOutputError("model output is empty")

    text = _strip_outer_fence(raw)
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except StructuredOutputError:
        raise
    except json.JSONDecodeError as exc:
        raise StructuredOutputError(
            f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc

    if not isinstance(value, dict):
        raise StructuredOutputError("top-level model output must be a JSON object")
    return value


def parse_structured_output(raw: str, schema: type[SchemaT]) -> SchemaT:
    """Strictly decode a complete response and validate it without repair."""

    value = extract_json_object(raw)
    try:
        return schema.model_validate(value)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors(include_url=False)
        )
        raise StructuredOutputError(f"schema validation failed: {details}") from exc


def compact_json(model: BaseModel) -> str:
    """Serialize validated context compactly to conserve Phi-3's 4K window."""

    return model.model_dump_json(exclude_none=True)
