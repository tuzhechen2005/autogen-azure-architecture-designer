"""AutoGen model client backed by an in-process llama.cpp Phi-3 model."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Mapping, Sequence
from typing import Any

from autogen_core import CancellationToken
from autogen_core.models import (
    AssistantMessage,
    ChatCompletionClient,
    CreateResult,
    FunctionExecutionResultMessage,
    LLMMessage,
    ModelCapabilities,
    ModelInfo,
    RequestUsage,
    SystemMessage,
    UserMessage,
)
from llama_cpp import Llama

from .config import AppConfig


class LocalModelProtocolError(RuntimeError):
    """Raised when AutoGen asks the local text-only model for unsupported behavior."""


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif hasattr(item, "content"):
                parts.append(str(item.content))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def _message_to_llama(message: LLMMessage) -> dict[str, str]:
    if isinstance(message, SystemMessage):
        role = "system"
    elif isinstance(message, UserMessage):
        role = "user"
    elif isinstance(message, AssistantMessage):
        role = "assistant"
    elif isinstance(message, FunctionExecutionResultMessage):
        role = "tool"
    else:
        raise LocalModelProtocolError(
            f"Unsupported AutoGen message type: {type(message).__name__}"
        )
    return {"role": role, "content": _content_to_text(message.content)}


def _render_phi3_prompt(messages: Sequence[LLMMessage]) -> str:
    """Render AutoGen messages with Phi-3's native instruct tokens."""

    role_map = {"system": "system", "user": "user", "assistant": "assistant"}
    parts: list[str] = []
    for message in messages:
        item = _message_to_llama(message)
        role = role_map.get(item["role"])
        if role is None:
            raise LocalModelProtocolError(
                "Function results are not supported by the text-only Phi-3 protocol"
            )
        parts.append(f"<|{role}|>\n{item['content']}<|end|>\n")
    parts.append("<|assistant|>\n")
    return "".join(parts)


class LlamaCppChatCompletionClient(ChatCompletionClient):
    """A deterministic text-only AutoGen client for local GGUF models.

    The application intentionally does not expose native function calling. Planner
    and reviewer outputs use a validated JSON text protocol instead, which is more
    reliable for Phi-3 Mini GGUF and keeps all inference in this Python process.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._model = Llama(
            model_path=str(config.model_path),
            n_ctx=config.n_ctx,
            n_gpu_layers=config.n_gpu_layers,
            seed=config.seed,
            verbose=False,
        )
        self._actual_usage = RequestUsage(prompt_tokens=0, completion_tokens=0)
        self._total_usage = RequestUsage(prompt_tokens=0, completion_tokens=0)

    @property
    def model_info(self) -> ModelInfo:
        return {
            "vision": False,
            "function_calling": False,
            "json_output": False,
            "family": "unknown",
            "structured_output": False,
        }

    @property
    def capabilities(self) -> ModelCapabilities:
        return {
            "vision": False,
            "function_calling": False,
            "json_output": False,
        }

    async def create(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Any] = (),
        tool_choice: Any = "auto",
        json_output: bool | type[Any] | None = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: CancellationToken | None = None,
    ) -> CreateResult:
        if tools:
            raise LocalModelProtocolError("Native tool calling is not supported")
        if tool_choice not in ("auto", "none"):
            raise LocalModelProtocolError(
                "A required tool choice is not supported by the local text model"
            )
        if json_output not in (None, False):
            raise LocalModelProtocolError(
                "Native JSON mode is not supported; use the application JSON protocol"
            )
        if cancellation_token is not None and cancellation_token.is_cancelled():
            raise asyncio.CancelledError

        prompt = _render_phi3_prompt(messages)
        allowed_overrides = {"max_tokens", "temperature", "top_p", "stop"}
        unknown = set(extra_create_args) - allowed_overrides
        if unknown:
            raise LocalModelProtocolError(
                f"Unsupported generation arguments: {sorted(unknown)}"
            )

        self._model.reset()
        response = self._model(
            prompt,
            max_tokens=int(extra_create_args.get("max_tokens", self._config.max_tokens)),
            temperature=float(
                extra_create_args.get("temperature", self._config.temperature)
            ),
            top_p=float(extra_create_args.get("top_p", 1.0)),
            stop=extra_create_args.get("stop", ["<|end|>"]),
            seed=self._config.seed,
            echo=False,
        )
        choice = response["choices"][0]
        content = str(choice.get("text") or "").strip()
        raw_usage = response.get("usage", {})
        usage = RequestUsage(
            prompt_tokens=int(raw_usage.get("prompt_tokens", 0)),
            completion_tokens=int(raw_usage.get("completion_tokens", 0)),
        )
        self._actual_usage = usage
        self._total_usage = RequestUsage(
            prompt_tokens=self._total_usage.prompt_tokens + usage.prompt_tokens,
            completion_tokens=(
                self._total_usage.completion_tokens + usage.completion_tokens
            ),
        )
        finish_reason = str(choice.get("finish_reason") or "unknown")
        if finish_reason not in {"stop", "length", "function_calls", "content_filter", "unknown"}:
            finish_reason = "unknown"
        return CreateResult(
            finish_reason=finish_reason,
            content=content,
            usage=usage,
            cached=False,
        )

    async def create_stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Any] = (),
        tool_choice: Any = "auto",
        json_output: bool | type[Any] | None = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: CancellationToken | None = None,
    ) -> AsyncGenerator[str | CreateResult, None]:
        # The first version exposes the framework streaming contract while keeping
        # llama.cpp generation atomic. The UI receives step-level orchestration events.
        yield await self.create(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            json_output=json_output,
            extra_create_args=extra_create_args,
            cancellation_token=cancellation_token,
        )

    async def close(self) -> None:
        self._model.close()

    def actual_usage(self) -> RequestUsage:
        return self._actual_usage

    def total_usage(self) -> RequestUsage:
        return self._total_usage

    def count_tokens(
        self, messages: Sequence[LLMMessage], *, tools: Sequence[Any] = ()
    ) -> int:
        if tools:
            raise LocalModelProtocolError("Native tool calling is not supported")
        prompt = _render_phi3_prompt(messages)
        return len(
            self._model.tokenize(
                prompt.encode("utf-8"), add_bos=True, special=True
            )
        )

    def remaining_tokens(
        self, messages: Sequence[LLMMessage], *, tools: Sequence[Any] = ()
    ) -> int:
        return max(0, self._config.n_ctx - self.count_tokens(messages, tools=tools))
