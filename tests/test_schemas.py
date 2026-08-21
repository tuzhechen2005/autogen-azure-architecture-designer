"""Regression tests for cross-field security invariants in schemas."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from src.schemas import ArchitectureReview


class ArchitectureReviewInvariantTests(unittest.TestCase):
    def test_approved_review_rejects_every_unresolved_finding(self) -> None:
        for severity in ("critical", "high", "medium", "low"):
            with self.subTest(severity=severity):
                review = {
                    "decision": "approved",
                    "summary": "审查声称方案已经满足所有可靠性要求。",
                    "strengths": [],
                    "findings": [
                        {
                            "severity": severity,
                            "category": "reliability",
                            "issue": "仍存在尚未解决的单点故障。",
                            "recommendation": "增加冗余并验证故障转移。",
                        }
                    ],
                    "required_changes": [],
                }

                with self.assertRaisesRegex(
                    ValidationError,
                    "approved reviews cannot contain findings",
                ):
                    ArchitectureReview.model_validate(review)

    def test_approved_review_accepts_no_findings_or_required_changes(self) -> None:
        review = ArchitectureReview.model_validate(
            {
                "decision": "approved",
                "summary": "方案已满足当前审查范围内的全部可靠性要求。",
                "strengths": ["具备区域冗余"],
                "findings": [],
                "required_changes": [],
            }
        )

        self.assertEqual(review.findings, [])
        self.assertEqual(review.required_changes, [])
