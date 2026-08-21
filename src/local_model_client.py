"""AutoGen model client backed by an in-process llama.cpp Phi-3 model."""

from __future__ import annotations

import atexit
import asyncio
import re
import threading
import time
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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
from .config import AppConfig


if TYPE_CHECKING:
    from llama_cpp import Llama


class LocalModelProtocolError(RuntimeError):
    """Raised when AutoGen asks the local text-only model for unsupported behavior."""


class LocalModelTimeoutError(TimeoutError):
    """Raised when local inference exceeds its configured wall-clock deadline."""


_PHI3_PROTOCOL_TOKEN = re.compile(r"<\|[A-Za-z0-9_.:-]+\|>")


def _reject_phi3_protocol_tokens(content: str) -> None:
    """Keep untrusted message text from creating Phi-3 protocol boundaries."""

    if _PHI3_PROTOCOL_TOKEN.search(content):
        raise LocalModelProtocolError(
            "Message content contains a reserved Phi-3 protocol token"
        )


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
        _reject_phi3_protocol_tokens(item["content"])
        parts.append(f"<|{role}|>\n{item['content']}<|end|>\n")
    parts.append("<|assistant|>\n")
    return "".join(parts)


@dataclass(frozen=True, slots=True)
class ModelRuntimeIdentity:
    """The settings that determine one native llama.cpp weight/context load."""

    model_path: str
    n_ctx: int
    n_gpu_layers: int
    seed: int

    @classmethod
    def from_config(cls, config: AppConfig) -> "ModelRuntimeIdentity":
        return cls(
            model_path=str(config.model_path.expanduser().resolve()),
            n_ctx=config.n_ctx,
            n_gpu_layers=config.n_gpu_layers,
            seed=config.seed,
        )


class LlamaCppModelRuntime:
    """One serialized, explicitly closable native llama.cpp model context."""

    def __init__(self, config: AppConfig) -> None:
        from llama_cpp import Llama

        self.identity = ModelRuntimeIdentity.from_config(config)
        self._lock = threading.RLock()
        self._closed = False
        self._model: Llama = Llama(
            model_path=self.identity.model_path,
            n_ctx=config.n_ctx,
            n_gpu_layers=config.n_gpu_layers,
            seed=config.seed,
            verbose=False,
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise LocalModelProtocolError("Local model runtime is closed")

    def generate(
        self,
        prompt: str,
        *,
        should_abort: Callable[[], bool] | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        with self._lock:
            self._ensure_open()
            self._model.reset()
            abort_callback: object | None = None
            low_level_context: object | None = None
            llama_cpp_module: object | None = None
            if should_abort is not None:
                from llama_cpp import StoppingCriteriaList, llama_cpp

                kwargs["stopping_criteria"] = StoppingCriteriaList(
                    [lambda _input_ids, _logits: should_abort()]
                )
                model_context = getattr(self._model, "_ctx", None)
                low_level_context = getattr(model_context, "ctx", None)
                if low_level_context is not None:
                    abort_callback = llama_cpp.ggml_abort_callback(
                        lambda _data: should_abort()
                    )
                    llama_cpp.llama_set_abort_callback(
                        low_level_context,
                        abort_callback,
                        None,
                    )
                    llama_cpp_module = llama_cpp
            try:
                return self._model(prompt, **kwargs)
            finally:
                if low_level_context is not None and llama_cpp_module is not None:
                    llama_cpp_module.llama_set_abort_callback(
                        low_level_context,
                        llama_cpp_module.ggml_abort_callback(),
                        None,
                    )
                # Keep the ctypes callback alive until after native generation ends.
                _ = abort_callback

    def count_tokens(self, prompt: str) -> int:
        with self._lock:
            self._ensure_open()
            return len(
                self._model.tokenize(
                    prompt.encode("utf-8"), add_bos=True, special=True
                )
            )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._model.close()
            self._closed = True


RuntimeFactory = Callable[[AppConfig], LlamaCppModelRuntime]


class SingleModelRuntimeRegistry:
    """Own at most one process-wide model runtime and close it on replacement."""

    def __init__(self, factory: RuntimeFactory = LlamaCppModelRuntime) -> None:
        self._factory = factory
        self._lock = threading.RLock()
        self._identity: ModelRuntimeIdentity | None = None
        self._runtime: LlamaCppModelRuntime | None = None

    def acquire(self, config: AppConfig) -> LlamaCppModelRuntime:
        identity = ModelRuntimeIdentity.from_config(config)
        with self._lock:
            if self._identity == identity and self._runtime is not None:
                return self._runtime
            if self._runtime is not None:
                self._runtime.close()
            self._identity = None
            self._runtime = None
            runtime = self._factory(config)
            self._identity = identity
            self._runtime = runtime
            return runtime

    def close(self) -> None:
        with self._lock:
            if self._runtime is not None:
                self._runtime.close()
            self._identity = None
            self._runtime = None


_PROCESS_MODEL_REGISTRY = SingleModelRuntimeRegistry()
atexit.register(_PROCESS_MODEL_REGISTRY.close)


class LlamaCppChatCompletionClient(ChatCompletionClient):
    """A deterministic text-only AutoGen client for local GGUF models.

    The application intentionally does not expose native function calling. Planner
    and reviewer outputs use a validated JSON text protocol instead, which is more
    reliable for Phi-3 Mini GGUF and keeps all inference in this Python process.
    """

    def __init__(
        self,
        config: AppConfig,
        *,
        runtime_registry: SingleModelRuntimeRegistry | None = None,
    ) -> None:
        self._config = config
        self._runtime = (
            runtime_registry or _PROCESS_MODEL_REGISTRY
        ).acquire(config)
        self._usage_lock = threading.Lock()
        self._actual_usage = RequestUsage(
            prompt_tokens=0,
            completion_tokens=0,
        )
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

        max_tokens = int(
            extra_create_args.get("max_tokens", self._config.max_tokens)
        )
        if max_tokens < 1:
            raise LocalModelProtocolError("max_tokens must be at least 1")
        prompt_tokens = await asyncio.to_thread(self._runtime.count_tokens, prompt)
        if prompt_tokens + max_tokens > self._config.n_ctx:
            raise LocalModelProtocolError(
                "Requested prompt and completion exceed the model context budget"
            )

        deadline = time.monotonic() + self._config.inference_timeout_seconds
        abort_event = threading.Event()

        def should_abort() -> bool:
            return (
                abort_event.is_set()
                or (
                    cancellation_token is not None
                    and cancellation_token.is_cancelled()
                )
                or time.monotonic() >= deadline
            )

        try:
            response = await asyncio.to_thread(
                self._runtime.generate,
                prompt,
                should_abort=should_abort,
                max_tokens=max_tokens,
                temperature=float(
                    extra_create_args.get("temperature", self._config.temperature)
                ),
                top_p=float(extra_create_args.get("top_p", 1.0)),
                stop=extra_create_args.get("stop", ["<|end|>"]),
                seed=self._config.seed,
                echo=False,
            )
        except asyncio.CancelledError:
            abort_event.set()
            raise
        except Exception as exc:
            if cancellation_token is not None and cancellation_token.is_cancelled():
                raise asyncio.CancelledError from exc
            if time.monotonic() >= deadline:
                raise LocalModelTimeoutError(
                    "Local model inference exceeded its wall-clock timeout"
                ) from exc
            raise
        if cancellation_token is not None and cancellation_token.is_cancelled():
            raise asyncio.CancelledError
        if time.monotonic() >= deadline:
            raise LocalModelTimeoutError(
                "Local model inference exceeded its wall-clock timeout"
            )
        choice = response["choices"][0]
        content = str(choice.get("text") or "").strip()
        raw_usage = response.get("usage", {})
        usage = RequestUsage(
            prompt_tokens=int(raw_usage.get("prompt_tokens", 0)),
            completion_tokens=int(raw_usage.get("completion_tokens", 0)),
        )
        with self._usage_lock:
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
        if finish_reason == "length":
            raise LocalModelProtocolError(
                "Model output reached the token limit and is truncated"
            )
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
        # The process registry owns the shared runtime. It closes the model when
        # replacing its single slot and again idempotently at process shutdown.
        return None

    def actual_usage(self) -> RequestUsage:
        with self._usage_lock:
            return self._actual_usage

    def total_usage(self) -> RequestUsage:
        with self._usage_lock:
            return self._total_usage

    def count_tokens(
        self, messages: Sequence[LLMMessage], *, tools: Sequence[Any] = ()
    ) -> int:
        if tools:
            raise LocalModelProtocolError("Native tool calling is not supported")
        prompt = _render_phi3_prompt(messages)
        return self._runtime.count_tokens(prompt)

    def remaining_tokens(
        self, messages: Sequence[LLMMessage], *, tools: Sequence[Any] = ()
    ) -> int:
        return max(0, self._config.n_ctx - self.count_tokens(messages, tools=tools))
