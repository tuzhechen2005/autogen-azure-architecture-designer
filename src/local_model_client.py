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
from .schemas import ArchitecturePlan, ArchitectureReview


if TYPE_CHECKING:
    from llama_cpp import Llama


class LocalModelProtocolError(RuntimeError):
    """Raised when AutoGen asks the local text-only model for unsupported behavior."""


class LocalModelTimeoutError(TimeoutError):
    """Raised when local inference exceeds its configured wall-clock deadline."""


class LocalModelRuntimeConflictError(LocalModelProtocolError):
    """Raised when a live client would be invalidated by a runtime replacement."""


class _LocalModelOperationAborted(RuntimeError):
    """Internal signal used when a queued native operation must not start."""


_PHI3_PROTOCOL_TOKEN = re.compile(r"<\|[A-Za-z0-9_.:-]+\|>")
_STRUCTURED_GRAMMAR_LOCK = threading.Lock()
_STRUCTURED_GRAMMARS: dict[type[ArchitecturePlan] | type[ArchitectureReview], object] = {}

# `ws` and `string` are deliberately bounded. An unbounded quantifier lets the
# model continue forever whenever it wants to avoid closing a construct -- the
# grammar stays satisfiable, so generation runs to the token limit and the
# truncation check rejects the whole response. Observed in practice: the model
# looped on "#ArchitecturePlan #SystemDesign ..." inside a summary string until
# it exhausted max_tokens. The bounds are far above any legitimate value.
#
# GBNF has no comment syntax, so this note has to live outside the string.
_JSON_GRAMMAR_COMMON = r'''
ws ::= [ \t\n\r]{0,20}
string ::= "\"" char{0,320} "\""
char ::= [^"\\\x00-\x1F] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])
integer ::= "-"? [0-9]+
strings ::= "[" ws (string ("," ws string)*)? "]" ws
'''

_PLAN_GRAMMAR = _JSON_GRAMMAR_COMMON + r'''
root ::= "{" ws "\"title\"" ws ":" ws string "," ws "\"summary\"" ws ":" ws string "," ws "\"revision\"" ws ":" ws integer "," ws "\"assumptions\"" ws ":" ws strings "," ws "\"resources\"" ws ":" ws resources "," ws "\"data_flow\"" ws ":" ws strings "," ws "\"high_availability_strategy\"" ws ":" ws strings "," ws "\"security_strategy\"" ws ":" ws strings "," ws "\"operations_strategy\"" ws ":" ws strings "," ws "\"cost_notes\"" ws ":" ws strings "}"
resources ::= "[" ws resource ("," ws resource)* "]" ws
resource ::= "{" ws "\"name\"" ws ":" ws string "," ws "\"resource_type\"" ws ":" ws string "," ws "\"region\"" ws ":" ws string "," ws "\"sku\"" ws ":" ws string "," ws "\"purpose\"" ws ":" ws string "," ws "\"high_availability\"" ws ":" ws strings "," ws "\"depends_on\"" ws ":" ws strings "}" ws
'''

_REVIEW_GRAMMAR = _JSON_GRAMMAR_COMMON + r'''
root ::= "{" ws "\"decision\"" ws ":" ws decision "," ws "\"summary\"" ws ":" ws string "," ws "\"strengths\"" ws ":" ws strings "," ws "\"findings\"" ws ":" ws findings "," ws "\"required_changes\"" ws ":" ws changes "}"
decision ::= "\"approved\"" | "\"revision_required\""
findings ::= "[" ws (finding ("," ws finding)*)? "]" ws
finding ::= "{" ws "\"severity\"" ws ":" ws severity "," ws "\"category\"" ws ":" ws string "," ws "\"issue\"" ws ":" ws string "," ws "\"recommendation\"" ws ":" ws string "}" ws
severity ::= "\"critical\"" | "\"high\"" | "\"medium\"" | "\"low\""
changes ::= "[" ws (change ("," ws change)*)? "]" ws
change ::= "{" ws "\"description\"" ws ":" ws string "," ws "\"target_field\"" ws ":" ws (resource-change | plan-change) "," ws "\"required_terms\"" ws ":" ws strings "}" ws
resource-change ::= resource-target "," ws "\"resource_name\"" ws ":" ws string
plan-change ::= plan-target "," ws "\"resource_name\"" ws ":" ws "null"
resource-target ::= "\"resource.high_availability\"" | "\"resource.sku\"" | "\"resource.region\"" | "\"resource.purpose\""
plan-target ::= "\"plan.high_availability_strategy\"" | "\"plan.security_strategy\"" | "\"plan.operations_strategy\""
'''


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


def _schema_for_messages(
    messages: Sequence[LLMMessage],
) -> type[ArchitecturePlan] | type[ArchitectureReview] | None:
    """Select a grammar only for our trusted, fixed-role agent system prompts."""

    for message in messages:
        if not isinstance(message, SystemMessage):
            continue
        content = _content_to_text(message.content)
        if content.startswith("You are PlannerAgent,"):
            return ArchitecturePlan
        if content.startswith("You are ReviewerAgent,"):
            return ArchitectureReview
    return None


def _structured_grammar(
    schema: type[ArchitecturePlan] | type[ArchitectureReview],
) -> object:
    """Build and cache llama.cpp's JSON-schema grammar for trusted schemas only."""

    with _STRUCTURED_GRAMMAR_LOCK:
        grammar = _STRUCTURED_GRAMMARS.get(schema)
        if grammar is None:
            from llama_cpp import LlamaGrammar

            grammar = LlamaGrammar.from_string(
                _PLAN_GRAMMAR if schema is ArchitecturePlan else _REVIEW_GRAMMAR,
                verbose=False,
            )
            _STRUCTURED_GRAMMARS[schema] = grammar
        return grammar


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

    def _acquire_lock(self, should_abort: Callable[[], bool] | None) -> None:
        """Acquire the mutable-context lock while permitting queued cancellation."""

        while True:
            if should_abort is not None and should_abort():
                raise _LocalModelOperationAborted()
            if self._lock.acquire(timeout=0.005):
                return

    def generate(
        self,
        prompt: str,
        *,
        should_abort: Callable[[], bool] | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        self._acquire_lock(should_abort)
        try:
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
        finally:
            self._lock.release()

    def count_tokens(
        self, prompt: str, *, should_abort: Callable[[], bool] | None = None
    ) -> int:
        self._acquire_lock(should_abort)
        try:
            self._ensure_open()
            return len(
                self._model.tokenize(
                    prompt.encode("utf-8"), add_bos=True, special=True
                )
            )
        finally:
            self._lock.release()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._model.close()
            self._closed = True


RuntimeFactory = Callable[[AppConfig], LlamaCppModelRuntime]


class SingleModelRuntimeRegistry:
    """Own one runtime and lease it to clients without invalidating live users.

    A different model/backend identity is rejected while any client lease exists.
    Once all clients release their leases, the next acquire replaces the runtime.
    This bounds process model memory to one loaded runtime while making a client's
    lifetime explicit and safe across sessions.
    """

    def __init__(self, factory: RuntimeFactory = LlamaCppModelRuntime) -> None:
        self._factory = factory
        self._lock = threading.RLock()
        self._identity: ModelRuntimeIdentity | None = None
        self._runtime: LlamaCppModelRuntime | None = None
        self._leases = 0

    def acquire(self, config: AppConfig) -> LlamaCppModelRuntime:
        identity = ModelRuntimeIdentity.from_config(config)
        with self._lock:
            if self._identity == identity and self._runtime is not None:
                self._leases += 1
                return self._runtime
            if self._runtime is not None:
                if self._leases:
                    raise LocalModelRuntimeConflictError(
                        "Local model runtime configuration conflicts with active "
                        "clients; close existing clients before switching backend or model"
                    )
                self._runtime.close()
            self._identity = None
            self._runtime = None
            runtime = self._factory(config)
            self._identity = identity
            self._runtime = runtime
            self._leases = 1
            return runtime

    def release(self, runtime: LlamaCppModelRuntime) -> None:
        """Release one client lease without closing a runtime still in use."""

        with self._lock:
            if runtime is self._runtime and self._leases:
                self._leases -= 1

    def close(self) -> None:
        with self._lock:
            if self._runtime is not None:
                self._runtime.close()
            self._identity = None
            self._runtime = None
            self._leases = 0


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
        self._runtime_registry = runtime_registry or _PROCESS_MODEL_REGISTRY
        self._runtime = self._runtime_registry.acquire(config)
        self._released = False
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
        request_started = time.monotonic()
        deadline = request_started + self._config.inference_timeout_seconds
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

        async def await_runtime_operation(operation: Callable[[], Any]) -> Any:
            task = asyncio.create_task(asyncio.to_thread(operation))

            def consume_result(completed: asyncio.Task[Any]) -> None:
                if not completed.cancelled():
                    try:
                        completed.exception()
                    except asyncio.CancelledError:
                        pass

            try:
                while True:
                    if cancellation_token is not None and cancellation_token.is_cancelled():
                        abort_event.set()
                        task.add_done_callback(consume_result)
                        raise asyncio.CancelledError
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        abort_event.set()
                        task.add_done_callback(consume_result)
                        raise LocalModelTimeoutError(
                            "Local model inference exceeded its wall-clock timeout"
                        )
                    done, _ = await asyncio.wait({task}, timeout=min(remaining, 0.01))
                    if done:
                        return task.result()
            except asyncio.CancelledError:
                abort_event.set()
                task.add_done_callback(consume_result)
                raise

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
        schema = _schema_for_messages(messages)
        grammar = _structured_grammar(schema) if schema is not None else None
        try:
            prompt_tokens = await await_runtime_operation(
                lambda: self._runtime.count_tokens(prompt, should_abort=should_abort)
            )
        except _LocalModelOperationAborted as exc:
            if cancellation_token is not None and cancellation_token.is_cancelled():
                raise asyncio.CancelledError from exc
            raise LocalModelTimeoutError(
                "Local model inference exceeded its wall-clock timeout"
            ) from exc
        if prompt_tokens + max_tokens > self._config.n_ctx:
            raise LocalModelProtocolError(
                "Requested prompt and completion exceed the model context budget"
            )

        try:
            response = await await_runtime_operation(
                lambda: self._runtime.generate(
                    prompt,
                    should_abort=should_abort,
                    max_tokens=max_tokens,
                    temperature=float(
                        extra_create_args.get("temperature", self._config.temperature)
                    ),
                    top_p=float(extra_create_args.get("top_p", 1.0)),
                    stop=extra_create_args.get("stop", ["<|end|>"]),
                    grammar=grammar,
                    seed=self._config.seed,
                    echo=False,
                )
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
        """Release this client's runtime lease; process shutdown owns final close."""

        if not self._released:
            self._runtime_registry.release(self._runtime)
            self._released = True

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
