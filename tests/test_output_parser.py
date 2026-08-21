"""Security regression tests for deterministic structured-output parsing."""

from __future__ import annotations

import unittest

from pydantic import BaseModel, ConfigDict

from src.output_parser import StructuredOutputError, parse_structured_output


class TinyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    value: int


class StrictJsonEnvelopeTests(unittest.TestCase):
    def assert_rejected(self, raw: str) -> None:
        with self.assertRaises(StructuredOutputError):
            parse_structured_output(raw, TinyPayload)

    def test_rejects_nested_object_promotion(self) -> None:
        self.assert_rejected('{"payload":{"value":1}}')
        self.assert_rejected('[{"value":1}]')

    def test_rejects_non_whitespace_prefix_or_suffix(self) -> None:
        self.assert_rejected('comment before {"value":1}')
        self.assert_rejected('{"value":1} comment after')

    def test_rejects_valid_object_followed_by_truncated_json(self) -> None:
        self.assert_rejected('{"value":1}\n{"value":')

    def test_rejects_duplicate_object_keys(self) -> None:
        self.assert_rejected('{"value":0,"value":1}')

    def test_accepts_one_complete_object_with_optional_outer_fence(self) -> None:
        self.assertEqual(parse_structured_output('{"value":1}', TinyPayload).value, 1)
        self.assertEqual(
            parse_structured_output('```json\n{"value":2}\n```', TinyPayload).value,
            2,
        )
