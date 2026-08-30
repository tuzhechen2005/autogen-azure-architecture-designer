import unittest
from copy import deepcopy

from src.schemas import ArchitecturePlan
from src.topology_contract import TopologyContractError, validate_topology_policy
from tests.test_orchestrator_revision import initial_plan


class TopologyPolicyTests(unittest.TestCase):
    def test_rejects_non_allowlisted_resource_type(self) -> None:
        payload = initial_plan()
        payload["resources"][0]["resource_type"] = "Evil.Cloud/unknown"
        with self.assertRaisesRegex(TopologyContractError, "not allowlisted"):
            validate_topology_policy(ArchitecturePlan.model_validate(payload))

    def test_required_dependency_type_must_be_referenced(self) -> None:
        payload = initial_plan()
        payload["resources"].append({
            "name": "frontdoor", "resource_type": "Microsoft.CDN/profiles/afdEndpoints",
            "region": "global", "sku": "Standard_AzureFrontDoor",
            "purpose": "Global ingress", "high_availability": ["global edge"],
            "depends_on": [],
        })
        with self.assertRaisesRegex(TopologyContractError, "required dependency"):
            validate_topology_policy(ArchitecturePlan.model_validate(payload))
        payload["resources"][-1]["depends_on"] = ["api"]
        validate_topology_policy(ArchitecturePlan.model_validate(payload))

    def test_existing_reference_cycle_and_self_loop_schema_still_apply(self) -> None:
        payload = deepcopy(initial_plan())
        payload["resources"][0]["depends_on"] = ["database"]
        with self.assertRaises(Exception):
            ArchitecturePlan.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
