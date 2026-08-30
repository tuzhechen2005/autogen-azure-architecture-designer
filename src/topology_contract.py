from .schemas import ArchitecturePlan


class TopologyContractError(ValueError):
    pass


ALLOWED_RESOURCE_TYPES = frozenset({
    "Microsoft.App/containerApps",
    "Microsoft.Cache/Redis",
    "Microsoft.CDN/profiles/afdEndpoints",
    "Microsoft.Compute/virtualMachines",
    "Microsoft.Compute/virtualMachineScaleSets",
    "Microsoft.ContainerService/managedClusters",
    "Microsoft.DBforPostgreSQL/flexibleServers",
    "Microsoft.DocumentDB/databaseAccounts",
    "Microsoft.EventHub/namespaces",
    "Microsoft.Insights/components",
    "Microsoft.KeyVault/vaults",
    "Microsoft.ManagedIdentity/userAssignedIdentities",
    "Microsoft.Network/applicationGateways",
    "Microsoft.Network/azureFirewalls",
    "Microsoft.Network/loadBalancers",
    "Microsoft.Network/networkSecurityGroups",
    "Microsoft.Network/privateEndpoints",
    "Microsoft.Network/publicIPAddresses",
    "Microsoft.Network/virtualNetworks",
    "Microsoft.OperationalInsights/workspaces",
    "Microsoft.RecoveryServices/vaults",
    "Microsoft.ServiceBus/namespaces",
    "Microsoft.Sql/servers/databases",
    "Microsoft.Storage/storageAccounts",
    "Microsoft.Web/sites",
})

REQUIRED_DEPENDENCY_TYPES = {
    "Microsoft.CDN/profiles/afdEndpoints": frozenset({"Microsoft.Web/sites"}),
}


def validate_topology_policy(plan: ArchitecturePlan) -> None:
    resources = {resource.name: resource for resource in plan.resources}
    for resource in plan.resources:
        if resource.resource_type not in ALLOWED_RESOURCE_TYPES:
            raise TopologyContractError(
                f"resource type is not allowlisted: {resource.resource_type}"
            )
        required_types = REQUIRED_DEPENDENCY_TYPES.get(resource.resource_type)
        if required_types is None:
            continue
        actual_types = {resources[name].resource_type for name in resource.depends_on}
        if not required_types.issubset(actual_types):
            raise TopologyContractError(
                f"resource {resource.name} is missing required dependency types: "
                f"{sorted(required_types - actual_types)}"
            )
