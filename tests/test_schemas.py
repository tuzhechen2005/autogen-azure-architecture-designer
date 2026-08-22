"""Regression tests for cross-field security invariants in schemas."""

from __future__ import annotations

from copy import deepcopy
import json
import unittest

from pydantic import ValidationError

from src.schemas import ArchitecturePlan, ArchitectureRequest, ArchitectureReview


def valid_plan() -> dict[str, object]:
    return {
        "title": "高可用 API 架构",
        "summary": "使用多可用区计算节点和托管数据库构建高可用服务。",
        "revision": 1,
        "assumptions": [],
        "resources": [
            {
                "name": "api",
                "resource_type": "Microsoft.Web/sites",
                "region": "eastasia",
                "sku": "P1v3",
                "purpose": "承载业务 API 服务",
                "high_availability": ["两个可用区实例"],
                "depends_on": [],
            },
            {
                "name": "database",
                "resource_type": "Microsoft.DBforPostgreSQL/flexibleServers",
                "region": "eastasia",
                "sku": "GeneralPurpose",
                "purpose": "保存交易数据记录",
                "high_availability": ["可用区冗余"],
                "depends_on": ["api"],
            },
        ],
        "data_flow": ["用户访问 API"],
        "high_availability_strategy": ["使用可用区冗余"],
        "security_strategy": [],
        "operations_strategy": [],
        "cost_notes": [],
    }


class ArchitectureReviewInvariantTests(unittest.TestCase):
    def test_rejects_missing_model_fields_instead_of_deriving_defaults(self) -> None:
        approved = {
            "decision": "approved",
            "summary": "方案已满足当前审查范围内的全部可靠性要求。",
            "strengths": [],
            "findings": [],
            "required_changes": [],
        }
        for field_name in ("strengths", "findings", "required_changes"):
            with self.subTest(field_name=field_name):
                review = dict(approved)
                review.pop(field_name)
                with self.assertRaises(ValidationError):
                    ArchitectureReview.model_validate_json(
                        json.dumps(review, ensure_ascii=False)
                    )

        revision_required = {
            "decision": "revision_required",
            "summary": "方案仍然存在必须修复的单点故障风险。",
            "strengths": [],
            "findings": [
                {
                    "severity": "high",
                    "category": "reliability",
                    "issue": "API 服务仍然只有一个实例。",
                    "recommendation": "增加至少两个实例。",
                }
            ],
        }
        with self.assertRaises(ValidationError):
            ArchitectureReview.model_validate_json(
                json.dumps(revision_required, ensure_ascii=False)
            )

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
                    ArchitectureReview.model_validate_json(
                        json.dumps(review, ensure_ascii=False)
                    )

    def test_approved_review_accepts_no_findings_or_required_changes(self) -> None:
        review = ArchitectureReview.model_validate_json(
            json.dumps(
                {
                    "decision": "approved",
                    "summary": "方案已满足当前审查范围内的全部可靠性要求。",
                    "strengths": ["具备区域冗余"],
                    "findings": [],
                    "required_changes": [],
                },
                ensure_ascii=False,
            )
        )

        self.assertEqual(review.findings, [])
        self.assertEqual(review.required_changes, [])


class ArchitecturePlanStrictnessTests(unittest.TestCase):
    def test_rejects_coerced_revision_types(self) -> None:
        for invalid_revision in ("1", 1.0, True):
            with self.subTest(invalid_revision=invalid_revision):
                plan = valid_plan()
                plan["revision"] = invalid_revision
                with self.assertRaises(ValidationError):
                    ArchitecturePlan.model_validate(plan)

    def test_rejects_missing_fields_instead_of_applying_defaults(self) -> None:
        for field_name in (
            "revision",
            "assumptions",
            "security_strategy",
            "operations_strategy",
            "cost_notes",
        ):
            with self.subTest(field_name=field_name):
                plan = valid_plan()
                plan.pop(field_name)
                with self.assertRaises(ValidationError):
                    ArchitecturePlan.model_validate(plan)

        for field_name in ("sku", "high_availability", "depends_on"):
            with self.subTest(resource_field=field_name):
                plan = valid_plan()
                resource = plan["resources"][0]  # type: ignore[index]
                resource.pop(field_name)  # type: ignore[union-attr]
                with self.assertRaises(ValidationError):
                    ArchitecturePlan.model_validate(plan)

    def test_rejects_scalar_strategy_instead_of_wrapping_it(self) -> None:
        plan = valid_plan()
        plan["security_strategy"] = "启用托管身份"

        with self.assertRaises(ValidationError):
            ArchitecturePlan.model_validate(plan)

    def test_rejects_duplicate_resource_names(self) -> None:
        plan = valid_plan()
        duplicate = deepcopy(plan["resources"][0])  # type: ignore[index]
        plan["resources"].append(duplicate)  # type: ignore[union-attr]

        with self.assertRaisesRegex(ValidationError, "resource names must be unique"):
            ArchitecturePlan.model_validate(plan)

    def test_rejects_dangling_self_and_cyclic_dependencies(self) -> None:
        cases = {
            "dangling": ["missing"],
            "self": ["database"],
            "cycle": ["api"],
        }
        for case, dependencies in cases.items():
            with self.subTest(case=case):
                plan = valid_plan()
                resources = plan["resources"]  # type: ignore[assignment]
                resources[1]["depends_on"] = dependencies  # type: ignore[index]
                if case == "cycle":
                    resources[0]["depends_on"] = ["database"]  # type: ignore[index]
                with self.assertRaises(ValidationError):
                    ArchitecturePlan.model_validate(plan)


class ArchitectureRequestValidationTests(unittest.TestCase):
    def test_rejects_visual_whitespace_and_control_only_input(self) -> None:
        invalid_values = (
            "",
            "          ",
            "\n\n\n\n\n\n\n\n\n\n",
            "\u200b" * 10,
            "\x00" * 10,
            "设计系统" + "\x01" * 6,
        )
        for value in invalid_values:
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValidationError):
                    ArchitectureRequest(requirements=value)

    def test_accepts_visible_multiline_input(self) -> None:
        request = ArchitectureRequest(
            requirements="设计高可用 API\n允许使用制表符\t描述容量要求"
        )

        self.assertIn("高可用 API", request.requirements)
