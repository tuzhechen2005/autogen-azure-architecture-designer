"""Graphviz DOT rendering for validated Azure architecture plans.

The planner is a local language model, so every string reaching this module is
untrusted display data. All identifiers and labels are escaped before they are
placed into DOT source; no value is ever interpolated verbatim.
"""

from __future__ import annotations

import re

from .schemas import ArchitecturePlan, AzureResource


# Azure resource families are grouped so the topology reads by tier rather than
# by the order the model happened to emit resources in.
_TIER_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "边缘接入",
        ("front door", "frontdoor", "cdn", "traffic manager", "dns", "waf"),
    ),
    (
        "网络",
        ("application gateway", "load balancer", "virtual network", "vnet", "firewall"),
    ),
    (
        "计算",
        (
            "app service",
            "function",
            "container app",
            "kubernetes",
            "aks",
            "virtual machine",
            "vm scale set",
            "web app",
        ),
    ),
    (
        "数据",
        (
            "sql",
            "postgres",
            "mysql",
            "cosmos",
            "database",
            "redis",
            "cache",
            "storage",
            "blob",
            "data lake",
        ),
    ),
    (
        "集成",
        ("service bus", "event hub", "event grid", "queue", "api management"),
    ),
    (
        "安全与运维",
        ("key vault", "monitor", "log analytics", "app insights", "defender", "entra"),
    ),
)

_TIER_STYLE: dict[str, tuple[str, str]] = {
    "边缘接入": ("#e8f1fb", "#1f6fb2"),
    "网络": ("#eaf4ec", "#2e7d4f"),
    "计算": ("#fdf1e3", "#b96a13"),
    "数据": ("#f2ecfa", "#6b4bab"),
    "集成": ("#fdecef", "#b3305a"),
    "安全与运维": ("#eef0f2", "#4a5568"),
    "其他": ("#f5f5f5", "#555555"),
}

# DOT identifiers accept alphanumerics and underscore; Unicode letters are kept
# so Chinese resource names stay readable in the exported source. Quotes,
# whitespace and punctuation are still replaced.
_UNSAFE_ID = re.compile(r"[^\w]", re.UNICODE)


def classify_tier(resource: AzureResource) -> str:
    """Map an Azure resource type onto a coarse architecture tier."""

    haystack = f"{resource.resource_type} {resource.name}".casefold()
    for tier, keywords in _TIER_RULES:
        if any(keyword in haystack for keyword in keywords):
            return tier
    return "其他"


def _escape_label(value: str) -> str:
    """Escape a value for use inside a quoted DOT label."""

    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", " ")
        .replace("\r", " ")
    )
    # DOT treats these as label markup; neutralize so model text cannot alter layout.
    return escaped.replace("<", "&lt;").replace(">", "&gt;").replace("|", "\\|")


def _wrap(value: str, width: int = 22) -> str:
    """Soft-wrap a label so wide model text does not stretch the diagram."""

    words = value.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\\n".join(lines[:3]) if lines else value


def _node_id(name: str, index: int) -> str:
    """Build a collision-free DOT identifier that never echoes raw model text."""

    slug = _UNSAFE_ID.sub("_", name)[:40]
    return f"res_{index}_{slug}"


def build_topology_dot(plan: ArchitecturePlan) -> str:
    """Render a validated plan as Graphviz DOT source.

    The plan's dependency graph is already schema-validated to be acyclic with
    unique names and resolvable edges, so this function only formats it.
    """

    node_ids: dict[str, str] = {
        resource.name: _node_id(resource.name, index)
        for index, resource in enumerate(plan.resources)
    }

    lines: list[str] = [
        "digraph azure_architecture {",
        "  rankdir=TB;",
        "  bgcolor=transparent;",
        '  node [shape=box style="rounded,filled" fontname="Helvetica" '
        'fontsize=10 margin="0.18,0.12"];',
        '  edge [fontname="Helvetica" fontsize=9 color="#7b8794" '
        'arrowsize=0.7];',
    ]

    grouped: dict[str, list[AzureResource]] = {}
    for resource in plan.resources:
        grouped.setdefault(classify_tier(resource), []).append(resource)

    for tier, _ in (*_TIER_RULES, ("其他", ())):
        members = grouped.get(tier)
        if not members:
            continue
        fill, border = _TIER_STYLE[tier]
        cluster_id = _UNSAFE_ID.sub("_", tier)
        lines.append(f'  subgraph "cluster_{cluster_id}" {{')
        lines.append(f'    label="{_escape_label(tier)}";')
        lines.append('    labeljust="l";')
        lines.append('    fontname="Helvetica";')
        lines.append("    fontsize=11;")
        lines.append(f'    color="{border}";')
        lines.append('    style="rounded";')
        for resource in members:
            label = "\\n".join(
                (
                    _wrap(_escape_label(resource.name)),
                    _escape_label(resource.resource_type),
                    _escape_label(f"{resource.region} · {resource.sku}"),
                )
            )
            lines.append(
                f'    "{node_ids[resource.name]}" [label="{label}" '
                f'fillcolor="{fill}" color="{border}"];'
            )
        lines.append("  }")

    for resource in plan.resources:
        for dependency in resource.depends_on:
            target = node_ids.get(dependency)
            if target is None:
                # Schema validation guarantees resolvable edges; skip defensively
                # rather than emit malformed DOT.
                continue
            lines.append(f'  "{target}" -> "{node_ids[resource.name]}";')

    lines.append("}")
    return "\n".join(lines)
