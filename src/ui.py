"""Pure Streamlit rendering helpers for validated architecture results."""

from __future__ import annotations

import streamlit as st

from .schemas import (
    AgentRole,
    ArchitecturePlan,
    ArchitectureReview,
    ArchitectureRunResult,
    ReviewDecision,
    TerminationReason,
    TranscriptMessage,
)
from .topology import build_topology_dot, classify_tier


def _bullet_list(items: list[str], *, empty_text: str = "未提供") -> None:
    if not items:
        st.caption(empty_text)
        return
    for item in items:
        st.text(f"• {item}")


def render_transcript_message(
    message: TranscriptMessage,
    *,
    show_raw: bool,
) -> None:
    planner = message.role is AgentRole.PLANNER
    avatar = "🧩" if planner else "🔍"
    title = "规划智能体" if planner else "审查智能体"
    with st.chat_message("assistant", avatar=avatar):
        st.markdown(f"**{title} · {message.phase.value}**")
        if message.parsed_content is None:
            st.warning("本次输出未通过结构校验，调度器已发起有限纠错。")
        else:
            st.json(message.parsed_content, expanded=False)
        if show_raw:
            with st.expander("查看本地模型原始消息"):
                st.code(message.raw_content, language="json")


def render_topology(plan: ArchitecturePlan) -> None:
    """Draw the plan's dependency graph as an Azure topology diagram."""

    st.markdown("**架构拓扑图**")
    st.caption(
        "按 Azure 资源分层分组；箭头方向为「被依赖资源 → 依赖它的资源」，"
        "即数据与调用的下游流向。"
    )
    try:
        dot = build_topology_dot(plan)
    except Exception as exc:  # noqa: BLE001 - diagram must never break the page
        st.info(
            "拓扑图暂时无法生成，可查看下方资源清单中的「依赖」列。"
            f"（原因：{type(exc).__name__}）"
        )
        return

    st.graphviz_chart(dot, use_container_width=True)
    with st.expander("查看拓扑图 DOT 源码"):
        st.caption("可复制到 Graphviz 或粘贴进文档中重绘。")
        st.code(dot, language="dot")


def render_plan(plan: ArchitecturePlan) -> None:
    st.subheader("架构方案")
    st.text(plan.title)
    st.text(plan.summary)
    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("方案修订版本", plan.revision)
    metric_b.metric("Azure 资源数", len(plan.resources))
    metric_c.metric("数据流步骤", len(plan.data_flow))

    render_topology(plan)

    st.markdown("**资源清单**")
    rows = [
        {
            "资源名称": resource.name,
            "分层": classify_tier(resource),
            "Azure 类型": resource.resource_type,
            "区域": resource.region,
            "SKU": resource.sku,
            "用途": resource.purpose,
            "高可用": "；".join(resource.high_availability) or "—",
            "依赖": "；".join(resource.depends_on) or "—",
        }
        for resource in plan.resources
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    flow, availability, security, operations, cost = st.tabs(
        ["数据流", "高可用", "安全", "运维", "成本提示"]
    )
    with flow:
        _bullet_list(plan.data_flow)
    with availability:
        _bullet_list(plan.high_availability_strategy)
    with security:
        _bullet_list(plan.security_strategy)
    with operations:
        _bullet_list(plan.operations_strategy)
    with cost:
        _bullet_list(plan.cost_notes)

    if plan.assumptions:
        with st.expander("方案假设"):
            _bullet_list(plan.assumptions)


def render_review(review: ArchitectureReview) -> None:
    st.subheader("审查结论")
    if review.decision is ReviewDecision.APPROVED:
        st.success("审查通过", icon="✅")
    else:
        st.warning("需要修订", icon="🛠️")
    st.text(review.summary)

    if review.strengths:
        st.markdown("**已确认的优点**")
        _bullet_list(review.strengths)
    if review.findings:
        st.markdown("**审查问题**")
        for index, finding in enumerate(review.findings, start=1):
            with st.expander(
                f"审查问题 {index} · 严重度 {finding.severity.upper()}"
            ):
                st.text(f"类别：{finding.category}")
                st.text(f"问题：{finding.issue}")
                st.text(f"建议：{finding.recommendation}")
    if review.required_changes:
        st.markdown("**下一步必改项**")
        _bullet_list([change.description for change in review.required_changes])


def render_result(result: ArchitectureRunResult) -> None:
    st.divider()
    st.header("最终架构方案")
    st.text(f"运行 ID：{result.run_id}")
    if result.request is not None:
        with st.expander("查看本结果对应的原始需求"):
            st.code(result.request.requirements, language=None)
    if result.termination_reason is TerminationReason.APPROVED:
        st.success(
            f"审查已通过，共完成 {result.review_rounds_completed} 轮审查。",
            icon="✅",
        )
    elif result.termination_reason is TerminationReason.MAX_REVIEW_ROUNDS:
        st.warning(
            "已达到最大审查轮次。下方为最新方案，仍需关注审查中的未解决项。",
            icon="⚠️",
        )

    if result.final_plan is not None:
        render_plan(result.final_plan)
    if result.final_review is not None:
        render_review(result.final_review)

    st.subheader("多智能体消息记录")
    st.caption(
        "仅展示角色消息和结构化结果，不请求或展示隐藏思维链。"
    )
    for message in result.messages:
        render_transcript_message(message, show_raw=True)
