import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


CATEGORIES = ("scale", "availability", "data", "security", "budget", "rto_rpo", "region", "conflict")
FAULT_TYPES = ("sustained_objection", "repeated_plan", "invalid_json", "timeout", "unknown_resource", "dependency_cycle", "unresolved_review", "prompt_injection")


class EvalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RequirementPoint(EvalModel):
    point_id: str = Field(min_length=3, max_length=80)
    category: Literal["scale", "availability", "data", "security", "budget", "rto_rpo", "region", "conflict"]
    required_terms: list[str] = Field(min_length=1, max_length=6)


class ArchitectureRequirementCase(EvalModel):
    case_id: str
    split: Literal["frozen_test"]
    language: Literal["en", "zh"]
    primary_category: Literal["scale", "availability", "data", "security", "budget", "rto_rpo", "region", "conflict"]
    requirements: str = Field(min_length=20)
    gold_requirement_points: list[RequirementPoint] = Field(min_length=1)


class ArchitectureFaultCase(EvalModel):
    case_id: str
    split: Literal["fault"]
    fault_type: Literal["sustained_objection", "repeated_plan", "invalid_json", "timeout", "unknown_resource", "dependency_cycle", "unresolved_review", "prompt_injection"]
    injection_round: int = Field(ge=0, le=5)
    expected_terminal: Literal["completed", "degraded", "timeout", "failed"]
    expected_max_agent_calls: int = Field(ge=1, le=20)


def build_requirement_cases() -> list[ArchitectureRequirementCase]:
    templates = {
        "scale": ("Serve {n} requests per second with explicit horizontal scaling.", ["requests per second", "scale"]),
        "availability": ("Remain available through one availability-zone failure.", ["availability zone", "redundancy"]),
        "data": ("Store transactional data with backups and point-in-time recovery.", ["backup", "recovery"]),
        "security": ("Use managed identity, private networking, and encryption.", ["managed identity", "private", "encryption"]),
        "budget": ("Keep the monthly design estimate below {n} USD and state trade-offs.", ["budget", "trade-off"]),
        "rto_rpo": ("Meet RTO {n} minutes and RPO 5 minutes.", ["RTO", "RPO"]),
        "region": ("Deploy only in eastasia and do not use cross-region replication.", ["eastasia", "region"]),
        "conflict": ("Use one instance to minimize cost but also tolerate an instance failure; expose the conflict.", ["conflict", "assumption"]),
    }
    cases: list[ArchitectureRequirementCase] = []
    serial = 1
    for category in CATEGORIES:
        template, terms = templates[category]
        for variation in range(1, 9):
            text = template.format(n=variation * 1000 if category == "scale" else variation * 10)
            if variation % 2 == 0:
                language = "zh"
                text = f"请设计本地评审用 Azure 架构。约束 {variation}：{text} 不执行真实部署。"
            else:
                language = "en"
                text = f"Design a locally reviewed Azure architecture. Constraint {variation}: {text} Do not deploy resources."
            cases.append(
                ArchitectureRequirementCase(
                    case_id=f"task3_req_{serial:03d}", split="frozen_test",
                    language=language, primary_category=category,
                    requirements=text,
                    gold_requirement_points=[
                        RequirementPoint(
                            point_id=f"{category}-{variation:02d}",
                            category=category,
                            required_terms=list(terms),
                        )
                    ],
                )
            )
            serial += 1
    return cases


def build_fault_cases() -> list[ArchitectureFaultCase]:
    terminals = {
        "sustained_objection": "degraded", "repeated_plan": "degraded",
        "invalid_json": "failed", "timeout": "timeout", "unknown_resource": "failed",
        "dependency_cycle": "failed", "unresolved_review": "degraded", "prompt_injection": "failed",
    }
    cases: list[ArchitectureFaultCase] = []
    serial = 1
    for fault_type in FAULT_TYPES:
        for variation in range(4):
            cases.append(
                ArchitectureFaultCase(
                    case_id=f"task3_fault_{serial:03d}", split="fault",
                    fault_type=fault_type, injection_round=variation % 3,
                    expected_terminal=terminals[fault_type], expected_max_agent_calls=12,
                )
            )
            serial += 1
    return cases


def validate_datasets(requirements: list[ArchitectureRequirementCase], faults: list[ArchitectureFaultCase], *, require_frozen_gates: bool = False) -> dict[str, object]:
    all_ids = [case.case_id for case in requirements] + [case.case_id for case in faults]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("evaluation case IDs must be unique")
    report = {
        "requirementCaseCount": len(requirements),
        "faultCaseCount": len(faults),
        "requirementCategoryCounts": dict(Counter(case.primary_category for case in requirements)),
        "faultTypeCounts": dict(Counter(case.fault_type for case in faults)),
        "languageCounts": dict(Counter(case.language for case in requirements)),
    }
    if require_frozen_gates:
        if len(requirements) < 50 or len(faults) < 30:
            raise ValueError("dataset size gate failed")
        if any(report["requirementCategoryCounts"].get(name, 0) < 5 for name in CATEGORIES):  # type: ignore[union-attr]
            raise ValueError("requirement category gate failed")
        if any(report["faultTypeCounts"].get(name, 0) < 3 for name in FAULT_TYPES):  # type: ignore[union-attr]
            raise ValueError("fault coverage gate failed")
    return report


def _jsonl_bytes(rows: list[BaseModel]) -> bytes:
    return b"".join((json.dumps(row.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n").encode() for row in rows)


def freeze_architecture_datasets(*, requirement_path: Path, fault_path: Path, manifest_path: Path, frozen_at: str) -> dict[str, object]:
    parsed = datetime.fromisoformat(frozen_at)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("frozen_at requires a timezone")
    targets = (requirement_path, fault_path, manifest_path)
    if any(path.exists() for path in targets):
        raise FileExistsError("architecture freeze target already exists")
    requirements, faults = build_requirement_cases(), build_fault_cases()
    validation = validate_datasets(requirements, faults, require_frozen_gates=True)
    requirement_bytes, fault_bytes = _jsonl_bytes(requirements), _jsonl_bytes(faults)
    for path, payload in ((requirement_path, requirement_bytes), (fault_path, fault_bytes)):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(payload)
    manifest = {
        **validation,
        "datasetName": "task3_frozen_v1",
        "frozenAt": frozen_at,
        "requirementSha256": hashlib.sha256(requirement_bytes).hexdigest(),
        "faultSha256": hashlib.sha256(fault_bytes).hexdigest(),
        "modelOutputsObservedBeforeFreeze": False,
        "frozenResultsMayDrivePromptChanges": False,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest
