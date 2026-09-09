import json
from dataclasses import dataclass
from pathlib import Path


ALLOWED_STATES = {
    "received", "input_validation", "planning", "review", "revision",
    "rereview", "completed", "degraded", "timeout", "failed",
}


@dataclass(frozen=True)
class StateTransitionRule:
    rule_id: str
    from_state: str
    to_state: str
    trigger: str
    preconditions: tuple[str, ...]
    output_contract: str
    termination_condition: str


def load_state_rules(path: Path) -> list[StateTransitionRule]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("state rule catalog must be a list")
    rules: list[StateTransitionRule] = []
    for index, item in enumerate(payload, 1):
        if not isinstance(item, dict):
            raise ValueError("state rule must be an object")
        expected_id = f"TR-{index:03d}"
        if item.get("ruleId") != expected_id:
            raise ValueError(f"state rule IDs must be sequential: expected {expected_id}")
        from_state, to_state = item.get("fromState"), item.get("toState")
        if from_state not in ALLOWED_STATES or to_state not in ALLOWED_STATES:
            raise ValueError("unknown state in transition catalog")
        preconditions = item.get("preconditions")
        if not isinstance(preconditions, list) or not preconditions:
            raise ValueError("transition preconditions must be non-empty")
        rule = StateTransitionRule(
            rule_id=expected_id,
            from_state=str(from_state),
            to_state=str(to_state),
            trigger=str(item.get("trigger", "")),
            preconditions=tuple(str(value) for value in preconditions),
            output_contract=str(item.get("outputContract", "")),
            termination_condition=str(item.get("terminationCondition", "")),
        )
        if not rule.trigger or not rule.output_contract or not rule.termination_condition:
            raise ValueError("transition fields must be non-empty")
        rules.append(rule)
    return rules


def rule_catalog_summary(rules: list[StateTransitionRule]) -> dict[str, object]:
    states = sorted({state for rule in rules for state in (rule.from_state, rule.to_state)})
    return {"ruleCount": len(rules), "states": states, "terminalStates": sorted({"completed", "degraded", "timeout", "failed"})}
