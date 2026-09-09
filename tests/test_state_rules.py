import json
import tempfile
import unittest
from pathlib import Path

from src.state_rules import load_state_rules, rule_catalog_summary


class StateRuleCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(__file__).resolve().parent.parent / "data" / "state_transition_rules.json"

    def test_rules_are_numbered_complete_and_machine_counted(self) -> None:
        rules = load_state_rules(self.path)
        summary = rule_catalog_summary(rules)

        self.assertGreaterEqual(summary["ruleCount"], 12)
        self.assertEqual(
            [rule.rule_id for rule in rules],
            [f"TR-{index:03d}" for index in range(1, len(rules) + 1)],
        )
        for rule in rules:
            self.assertTrue(rule.preconditions)
            self.assertTrue(rule.output_contract)
            self.assertTrue(rule.termination_condition)
        for state in (
            "input_validation", "planning", "review", "revision", "rereview",
            "completed", "degraded", "timeout", "failed",
        ):
            self.assertIn(state, summary["states"])

    def test_unknown_state_and_duplicate_id_are_rejected(self) -> None:
        payload = json.loads(self.path.read_text())
        payload[1]["ruleId"] = payload[0]["ruleId"]
        payload[1]["toState"] = "invented"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(json.dumps(payload))
            with self.assertRaises(ValueError):
                load_state_rules(path)


if __name__ == "__main__":
    unittest.main()
