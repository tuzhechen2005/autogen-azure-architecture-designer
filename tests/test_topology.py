"""Regression tests for Azure architecture topology rendering."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.schemas import ArchitecturePlan, AzureResource
from src.topology import build_topology_dot, classify_tier


def _resource(
    name: str,
    resource_type: str = "Azure App Service",
    depends_on: list[str] | None = None,
) -> AzureResource:
    return AzureResource(
        name=name,
        resource_type=resource_type,
        region="eastus",
        sku="P1v3",
        purpose="serve API traffic",
        high_availability=["zone redundant"],
        depends_on=depends_on or [],
    )


def _plan(resources: list[AzureResource]) -> ArchitecturePlan:
    return ArchitecturePlan(
        title="demo",
        summary="a demonstration architecture plan",
        revision=1,
        resources=resources,
        data_flow=["client to api"],
        high_availability_strategy=["zone redundancy"],
        security_strategy=["private endpoints"],
        operations_strategy=["azure monitor"],
        cost_notes=["reserved instances"],
        assumptions=[],
    )


class TopologyDotTests(unittest.TestCase):
    def test_dependency_edges_point_from_dependency_to_dependent(self) -> None:
        plan = _plan(
            [
                _resource("db", "Azure SQL Database"),
                _resource("api", "Azure App Service", depends_on=["db"]),
            ]
        )
        dot = build_topology_dot(plan)

        db_id = "res_0_db"
        api_id = "res_1_api"
        self.assertIn(f"{db_id} -> {api_id};", dot)
        self.assertNotIn(f"{api_id} -> {db_id};", dot)

    def test_every_resource_becomes_exactly_one_node(self) -> None:
        plan = _plan([_resource("api"), _resource("db", "Azure SQL Database")])
        dot = build_topology_dot(plan)

        self.assertEqual(dot.count("[label="), 2)
        self.assertTrue(dot.startswith("digraph azure_architecture {"))
        self.assertTrue(dot.rstrip().endswith("}"))

    def test_quotes_in_model_output_cannot_break_out_of_the_label(self) -> None:
        plan = _plan([_resource('api" ];  malicious [label="pwned')])
        dot = build_topology_dot(plan)

        # The injected quote must be escaped, never closing the label early.
        self.assertNotIn('" ];  malicious', dot)
        self.assertIn('\\"', dot)
        self.assertNotIn("pwned\"]", dot)

    def test_node_identifiers_never_contain_raw_model_characters(self) -> None:
        plan = _plan([_resource("api-gateway prod/eu")])
        dot = build_topology_dot(plan)

        self.assertIn("res_0_api_gateway_prod_eu", dot)

    def test_angle_brackets_are_neutralized(self) -> None:
        plan = _plan([_resource("api<b>bold</b>")])
        dot = build_topology_dot(plan)

        self.assertNotIn("<b>", dot)
        self.assertIn("&lt;b&gt;", dot)

    def test_duplicate_slugs_stay_distinct_nodes(self) -> None:
        plan = _plan([_resource("api/1"), _resource("api-1")])
        dot = build_topology_dot(plan)

        self.assertIn("res_0_api_1", dot)
        self.assertIn("res_1_api_1", dot)
        self.assertEqual(dot.count("[label="), 2)

    def test_tiers_group_known_azure_families(self) -> None:
        self.assertEqual(
            classify_tier(_resource("db", "Azure SQL Database")), "数据"
        )
        self.assertEqual(
            classify_tier(_resource("fdoor", "Azure Front Door")), "边缘接入"
        )
        self.assertEqual(
            classify_tier(_resource("xx", "Contoso Custom Widget")), "其他"
        )


if __name__ == "__main__":
    unittest.main()
