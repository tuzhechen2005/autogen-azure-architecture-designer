"""Streamlit entry point for the local AutoGen architecture workspace."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import streamlit as st

from src.config import AppConfig, ConfigurationError, trusted_model_root_from_env
from src.local_model_client import LlamaCppChatCompletionClient
from src.orchestrator import ArchitectureOrchestrator, CollaborationEvent, EventType
from src.schemas import (
    ArchitectureRequest,
    ArchitectureRunResult,
    RunStatus,
    TerminationReason,
)
from src.run_log import LOGGER_NAME
from src.trace_writer import save_trace
from src.ui import (
    render_failure,
    render_failure_text,
    render_result,
    render_transcript_message,
)


_LOG_HANDLER_NAME = "azure_architect_console"

SAMPLE_REQUIREMENT = """\
为一个中小型电商 API 设计 Azure 高可用架构：
- 用户通过 HTTPS 访问 Web 入口；
- 后端是 Python API；
- 使用 PostgreSQL 保存交易数据，Blob Storage 保存商品图片；
- 目标可用性 99.9%，优先使用单区域多可用区；
- 不执行真实 Azure 部署，只输出架构方案。
"""


st.set_page_config(
    page_title="Azure Architecture Studio",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="expanded",
)


def load_local_model(
    model_path: str,
    n_ctx: int,
    max_tokens: int,
    temperature: float,
    n_gpu_layers: int,
) -> LlamaCppChatCompletionClient:
    """Create a per-run client backed by the process's bounded model registry."""

    config = AppConfig(
        model_path=Path(model_path).expanduser(),
        model_root=trusted_model_root_from_env(),
        n_ctx=n_ctx,
        max_tokens=max_tokens,
        temperature=temperature,
        n_gpu_layers=n_gpu_layers,
    )
    config.validate()
    return LlamaCppChatCompletionClient(config)


def render_header() -> None:
    st.title("☁️ Azure Architecture Studio")
    st.caption("Microsoft AutoGen · 本地 Phi-3 · 规划智能体 ↔ 审查智能体")
    st.info(
        "本工具只生成架构建议：不连接 Azure 订阅，不执行部署，不需要云端 API Key。",
        icon="🔒",
    )


def render_sidebar() -> dict[str, object]:
    with st.sidebar:
        st.header("本地运行配置")
        model_path = st.text_input(
            "Phi-3 GGUF 绝对路径",
            value=os.getenv("PHI3_MODEL_PATH", ""),
            placeholder="/absolute/path/to/Phi-3-mini-4k-instruct-q4.gguf",
            help="模型仅从本机读取，不会上传。",
        )
        max_rounds = st.slider("最大审查轮次", 1, 3, 2)
        max_tokens = st.slider("单次最大生成 token", 384, 1024, 800, 64)
        backend = st.radio(
            "推理后端",
            options=("Apple Metal", "CPU"),
            horizontal=True,
        )
        save_trace_enabled = st.checkbox("保存脱敏的本地运行记录", value=False)
        verbose_log = st.checkbox(
            "输出详细诊断日志",
            value=False,
            help=(
                "在运行终端打印每次结构校验失败的角色、轮次和原因，"
                "便于排查模型输出问题。日志只记录长度和短摘要，不保存完整输出。"
            ),
        )
        st.divider()
        st.caption("本地模型会占用约 3–5 GiB 内存。首次生成前才会加载。")
    return {
        "model_path": model_path,
        "max_rounds": max_rounds,
        "max_tokens": max_tokens,
        "n_gpu_layers": -1 if backend == "Apple Metal" else 0,
        "save_trace": save_trace_enabled,
        "verbose_log": verbose_log,
    }


def configure_run_logging(*, verbose: bool) -> None:
    """Send diagnostics to the launching terminal when the operator asks for it.

    Handlers are replaced rather than appended so repeated Streamlit reruns do
    not multiply the same record.
    """

    run_logger = logging.getLogger(LOGGER_NAME)
    for handler in list(run_logger.handlers):
        if getattr(handler, "name", None) == _LOG_HANDLER_NAME:
            run_logger.removeHandler(handler)
    if not verbose:
        run_logger.setLevel(logging.CRITICAL)
        return

    handler = logging.StreamHandler()
    handler.name = _LOG_HANDLER_NAME
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s | %(message)s")
    )
    run_logger.addHandler(handler)
    run_logger.setLevel(logging.INFO)


def run_architecture(
    requirements: str,
    settings: dict[str, object],
) -> ArchitectureRunResult:
    request = ArchitectureRequest(requirements=requirements)
    configure_run_logging(verbose=bool(settings.get("verbose_log")))
    model_path = str(settings["model_path"]).strip()
    if not model_path:
        raise ConfigurationError("请先在侧边栏填写 Phi-3 GGUF 绝对路径。")

    client = load_local_model(
        model_path=model_path,
        n_ctx=4096,
        max_tokens=int(settings["max_tokens"]),
        temperature=0.0,
        n_gpu_layers=int(settings["n_gpu_layers"]),
    )

    status_box = st.status("正在初始化多智能体协作……", expanded=True)
    live_messages = st.container()

    def on_event(event: CollaborationEvent) -> None:
        if event.event_type is EventType.STATUS:
            status_box.update(label=event.text, state="running")
        elif event.event_type is EventType.AGENT_MESSAGE and event.message is not None:
            with live_messages:
                render_transcript_message(event.message, show_raw=False)
        elif event.event_type is EventType.ERROR:
            status_box.update(
                label="架构生成失败，请查看下方错误详情。",
                state="error",
                expanded=True,
            )
        elif event.event_type is EventType.COMPLETED:
            status_box.update(
                label="方案已生成，正在确认本次运行记录……",
                state="running",
            )

    orchestrator = ArchitectureOrchestrator(
        client,
        max_review_rounds=int(settings["max_rounds"]),
        event_sink=on_event,
    )
    result = asyncio.run(orchestrator.run(request.requirements))
    if bool(settings["save_trace"]):
        try:
            save_trace(
                result,
                Path("results/architecture_runs"),
                model_identity=Path(model_path).name,
            )
        except Exception:
            st.warning(
                "方案已生成，但本地运行记录保存失败；当前方案仍可正常查看。",
                icon="⚠️",
            )
    if result.status is RunStatus.COMPLETED:
        approved = result.termination_reason is TerminationReason.APPROVED
        status_box.update(
            label=(
                "审查通过，架构方案已完成。"
                if approved
                else "已达到轮次上限，返回最新方案和未解决意见。"
            ),
            state="complete",
            expanded=False,
        )
    return result


def main() -> None:
    render_header()
    settings = render_sidebar()

    if "architecture_result" not in st.session_state:
        st.session_state.architecture_result = None

    st.subheader("架构需求")
    requirements = st.text_area(
        "请描述业务、数据、流量、可用性和安全要求",
        value=SAMPLE_REQUIREMENT,
        height=210,
        max_chars=6000,
    )
    first, second, spacer = st.columns([1, 1, 4])
    with first:
        generate = st.button("生成并审查方案", type="primary", use_container_width=True)
    with second:
        clear = st.button("清空结果", use_container_width=True)

    if clear:
        st.session_state.architecture_result = None
    if generate:
        # A new attempt immediately invalidates the previously displayed result.
        # If setup or inference fails, the old success must not look like the
        # answer to the new requirements.
        st.session_state.architecture_result = None
        try:
            result = run_architecture(requirements, settings)
            st.session_state.architecture_result = result.model_dump()
        except (ConfigurationError, ValueError) as exc:
            render_failure(exc, context="无法开始本次运行")
        except Exception as exc:
            render_failure(exc, context="本地运行失败")

    stored = st.session_state.architecture_result
    if stored is not None:
        result = ArchitectureRunResult.model_validate(stored)
        if result.status is RunStatus.FAILED:
            if result.error:
                render_failure_text(result.error, context="架构生成失败")
            else:
                st.error("架构生成失败。", icon="⚠️")
        render_result(result)


if __name__ == "__main__":
    main()
