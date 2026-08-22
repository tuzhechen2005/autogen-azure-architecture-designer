"""Regression tests for deterministic revision state transitions."""

from __future__ import annotations

import asyncio
import json
import unittest
from copy import deepcopy

from scripts.orchestrator_smoke_test import ScriptedModelClient
from src.orchestrator import ArchitectureOrchestrator
from src.schemas import RunStatus


REQUIREMENT = "设计一个包含 API 和数据库的高可用交易系统，不执行真实部署。"


def initial_plan() -> dict[str, object]:
    return {
        "title": "交易 API 架构",
        "summary": "包含 API 服务和托管数据库的第一版架构方案。",
        "revision": 1,
        "assumptions": [],
        "resources": [
            {
                "name": "api",
                "resource_type": "Microsoft.Web/sites",
                "region": "eastasia",
                "sku": "P1v3",
                "purpose": "承载交易 API",
                "high_availability": [],
                "depends_on": [],
            },
            {
                "name": "database",
                "resource_type": "Microsoft.DBforPostgreSQL/flexibleServers",
                "region": "eastasia",
                "sku": "GeneralPurpose",
                "purpose": "保存交易数据",
                "high_availability": ["可用区冗余"],
                "depends_on": ["api"],
            },
        ],
        "data_flow": ["用户访问 API，API 写入数据库"],
        "high_availability_strategy": ["数据库可用区冗余"],
        "security_strategy": [],
        "operations_strategy": [],
        "cost_notes": [],
    }


REVIEW_REQUIRED = {
    "decision": "revision_required",
    "summary": "API 仍然存在必须修复的单点故障。",
    "strengths": ["数据库已配置冗余"],
    "findings": [
        {
            "severity": "high",
            "category": "compute",
            "issue": "API 当前没有任何高可用配置。",
            "recommendation": "为 API 增加两个实例。",
        }
    ],
    "required_changes": [
        {
            "description": "为 API 增加两个实例",
            "target_field": "resource.high_availability",
            "resource_name": "api",
            "required_terms": ["两个实例"],
        }
    ],
}

APPROVED = {
    "decision": "approved",
    "summary": "声称所有必须修改的可靠性问题均已解决。",
    "strengths": ["声称 API 已冗余"],
    "findings": [],
    "required_changes": [],
}


class RevisionTransitionTests(unittest.TestCase):
    def test_retries_invalid_or_truncated_planner_json_without_repairing_it(self) -> None:
        base = initial_plan()
        invalid_with_ran = json.dumps(base, ensure_ascii=False).replace(
            '"name": "api"', 'ran\n"name": "api"', 1
        )
        truncated = json.dumps(base, ensure_ascii=False)[:-12]
        for invalid in (invalid_with_ran, truncated):
            with self.subTest(invalid=invalid[:20]):
                client = ScriptedModelClient(
                    [
                        invalid,
                        json.dumps(base, ensure_ascii=False),
                        json.dumps(APPROVED, ensure_ascii=False),
                    ]
                )
                result = asyncio.run(
                    ArchitectureOrchestrator(
                        client,
                        max_review_rounds=1,
                        max_parse_retries=1,
                    ).run(REQUIREMENT)
                )
                self.assertEqual(result.status, RunStatus.COMPLETED)
                self.assertIsNone(result.messages[0].parsed_content)
                self.assertEqual(result.messages[1].parsed_content["revision"], 1)

    def test_rejects_identity_dependency_and_noop_revisions(self) -> None:
        base = initial_plan()
        cases: dict[str, dict[str, object]] = {}

        unchanged = deepcopy(base)
        cases["unchanged"] = unchanged

        renamed = deepcopy(base)
        renamed["resources"][0]["name"] = "renamed-api"  # type: ignore[index]
        renamed["resources"][1]["depends_on"] = ["renamed-api"]  # type: ignore[index]
        cases["renamed"] = renamed

        added = deepcopy(base)
        added["resources"].append(  # type: ignore[union-attr]
            {
                "name": "storage",
                "resource_type": "Microsoft.Storage/storageAccounts",
                "region": "eastasia",
                "sku": "Standard_ZRS",
                "purpose": "保存对象数据",
                "high_availability": ["区域冗余"],
                "depends_on": [],
            }
        )
        cases["added"] = added

        removed = deepcopy(base)
        removed["resources"] = [removed["resources"][0]]  # type: ignore[index]
        cases["removed"] = removed

        dependency_changed = deepcopy(base)
        dependency_changed["resources"][1]["depends_on"] = []  # type: ignore[index]
        cases["dependency_changed"] = dependency_changed

        change_in_wrong_field = deepcopy(base)
        change_in_wrong_field["high_availability_strategy"].append(  # type: ignore[union-attr]
            "API 使用两个实例"
        )
        cases["change_in_wrong_field"] = change_in_wrong_field

        for case, revised in cases.items():
            with self.subTest(case=case):
                revised["revision"] = 2
                client = ScriptedModelClient(
                    [
                        json.dumps(base, ensure_ascii=False),
                        json.dumps(REVIEW_REQUIRED, ensure_ascii=False),
                        json.dumps(revised, ensure_ascii=False),
                        json.dumps(APPROVED, ensure_ascii=False),
                    ]
                )
                result = asyncio.run(
                    ArchitectureOrchestrator(
                        client,
                        max_review_rounds=2,
                        max_parse_retries=0,
                    ).run(REQUIREMENT)
                )

                self.assertEqual(result.status, RunStatus.FAILED)
