"""Actionable diagnostics for local runtime and model-loading failures.

The runtime raises precise but terse English errors. Operators running this app
locally need to know what to change, so each known failure is mapped to a cause
and concrete remediation steps. Unknown failures still surface their real type
and message rather than being swallowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Diagnosis:
    """A human-readable explanation of one runtime failure."""

    title: str
    cause: str
    remedies: tuple[str, ...] = field(default=())
    env_hint: str | None = None


# Ordered: the first matching fragment wins, so put specific rules before
# generic ones.
_MODEL_RULES: tuple[tuple[str, Diagnosis], ...] = (
    (
        "must be absolute",
        Diagnosis(
            title="模型路径不是绝对路径",
            cause="出于安全考虑，模型路径必须是以 / 开头的绝对路径，不接受相对路径。",
            remedies=(
                "在侧边栏填写完整路径，例如 /Users/你的用户名/models/Phi-3-mini-4k-instruct-q4.gguf",
                "可在终端执行 `realpath 模型文件` 获取绝对路径。",
            ),
            env_hint="PHI3_MODEL_PATH",
        ),
    ),
    (
        "gguf extension",
        Diagnosis(
            title="模型文件扩展名不是 .gguf",
            cause="本应用只加载 GGUF 格式的本地量化模型。",
            remedies=(
                "确认下载的是 GGUF 文件，而不是 .bin、.safetensors 或 .zip。",
                "推荐文件：Phi-3-mini-4k-instruct-q4.gguf。",
            ),
            env_hint="PHI3_MODEL_PATH",
        ),
    ),
    (
        "PHI3_MODEL_ROOT must be configured",
        Diagnosis(
            title="未配置模型根目录 PHI3_MODEL_ROOT",
            cause=(
                "应用要求模型必须位于一个显式声明的可信目录内，"
                "以防止加载任意路径下的文件。"
            ),
            remedies=(
                "启动前设置：export PHI3_MODEL_ROOT=\"/你的/模型目录\"",
                "该目录必须是模型文件所在目录本身或其上级目录。",
            ),
            env_hint="PHI3_MODEL_ROOT",
        ),
    ),
    (
        "outside the configured root",
        Diagnosis(
            title="模型不在可信根目录内",
            cause=(
                "模型文件的真实路径不在 PHI3_MODEL_ROOT 指定的目录范围内，"
                "这是防止路径穿越的安全边界。"
            ),
            remedies=(
                "把 PHI3_MODEL_ROOT 设为模型所在目录的上级目录。",
                "或把模型移动到当前 PHI3_MODEL_ROOT 目录内。",
                "注意两者都会先解析符号链接再比较。",
            ),
            env_hint="PHI3_MODEL_ROOT",
        ),
    ),
    (
        "Symbolic-link",
        Diagnosis(
            title="模型路径是符号链接",
            cause="为避免链接目标在校验后被替换，应用拒绝符号链接形式的模型路径。",
            remedies=(
                "改为填写模型文件的真实路径。",
                "可执行 `readlink -f 当前路径` 得到真实路径。",
            ),
            env_hint="PHI3_MODEL_PATH",
        ),
    ),
    (
        "not a directory",
        Diagnosis(
            title="PHI3_MODEL_ROOT 不是目录",
            cause="模型根目录必须指向一个目录，而当前指向了文件或不存在的路径。",
            remedies=("确认该路径存在且是目录，而不是模型文件本身。",),
            env_hint="PHI3_MODEL_ROOT",
        ),
    ),
    (
        "regular file",
        Diagnosis(
            title="模型路径不是普通文件",
            cause="目标是目录、设备或管道等特殊文件，无法作为模型加载。",
            remedies=("确认路径指向 .gguf 文件本身，而不是它所在的目录。",),
            env_hint="PHI3_MODEL_PATH",
        ),
    ),
    (
        "size is outside safe bounds",
        Diagnosis(
            title="模型文件大小异常",
            cause=(
                "文件体积超出合理范围，通常说明下载不完整、被截断，"
                "或指向了错误的文件。"
            ),
            remedies=(
                "检查文件大小，Phi-3-mini-4k-instruct-q4.gguf 约为 2.2 GiB。",
                "若明显偏小，请重新完整下载模型。",
            ),
            env_hint="PHI3_MODEL_PATH",
        ),
    ),
    (
        "GGUF magic",
        Diagnosis(
            title="文件不是有效的 GGUF 模型",
            cause="文件头部缺少 GGUF 标识，说明内容不是 GGUF 模型或已损坏。",
            remedies=(
                "重新下载模型文件，下载过程中断会导致此问题。",
                "确认下载的不是 HTML 错误页或压缩包。",
            ),
            env_hint="PHI3_MODEL_PATH",
        ),
    ),
    (
        "unavailable or unsafe",
        Diagnosis(
            title="模型文件无法访问",
            cause="路径不存在，或当前用户没有读取权限。",
            remedies=(
                "确认文件确实存在：`ls -l 模型路径`",
                "确认当前用户有读权限。",
                "若模型在外接磁盘上，确认磁盘已挂载。",
            ),
            env_hint="PHI3_MODEL_PATH",
        ),
    ),
    (
        "PHI3_N_CTX",
        Diagnosis(
            title="上下文长度配置无效",
            cause="PHI3_N_CTX 至少需要 1024。",
            remedies=("设置为 4096（推荐）或不设置以使用默认值。",),
            env_hint="PHI3_N_CTX",
        ),
    ),
    (
        "PHI3_MAX_TOKENS",
        Diagnosis(
            title="生成 token 上限配置无效",
            cause="PHI3_MAX_TOKENS 必须在 1 与 n_ctx - 1 之间。",
            remedies=("在侧边栏下调单次最大生成 token，或增大 PHI3_N_CTX。",),
            env_hint="PHI3_MAX_TOKENS",
        ),
    ),
    (
        "PHI3_TEMPERATURE",
        Diagnosis(
            title="采样温度配置无效",
            cause="PHI3_TEMPERATURE 必须在 0 到 2 之间。",
            remedies=("结构化输出建议使用 0，以获得稳定可解析的结果。",),
            env_hint="PHI3_TEMPERATURE",
        ),
    ),
    (
        "PHI3_INFERENCE_TIMEOUT_SECONDS",
        Diagnosis(
            title="推理超时配置无效",
            cause="超时时间必须在 0.01 到 600 秒之间。",
            remedies=("本地 CPU 推理建议设为 120 秒或更长。",),
            env_hint="PHI3_INFERENCE_TIMEOUT_SECONDS",
        ),
    ),
)

_RUNTIME_RULES: tuple[tuple[str, Diagnosis], ...] = (
    (
        "LocalModelTimeoutError",
        Diagnosis(
            title="本地推理超时",
            cause=(
                "模型在配置的时限内没有完成生成。"
                "CPU 模式或较长的生成任务容易触发。"
            ),
            remedies=(
                "调大 PHI3_INFERENCE_TIMEOUT_SECONDS，例如 240。",
                "在侧边栏调小单次最大生成 token。",
                "启用 Metal 加速（不要设置 PHI3_N_GPU_LAYERS=0）。",
                "减少最大审查轮次以缩短整体耗时。",
            ),
            env_hint="PHI3_INFERENCE_TIMEOUT_SECONDS",
        ),
    ),
    (
        "LocalModelRuntimeConflictError",
        Diagnosis(
            title="运行时配置与正在使用的模型冲突",
            cause=(
                "已有一个使用不同参数的模型实例在运行，"
                "为避免影响进行中的任务，本次不会替换它。"
            ),
            remedies=(
                "等待当前运行结束后重试。",
                "或保持与当前实例一致的模型路径与上下文参数。",
            ),
        ),
    ),
    (
        "LocalModelProtocolError",
        Diagnosis(
            title="模型调用协议错误",
            cause="向纯文本模型请求了它不支持的能力，例如函数调用或图像输入。",
            remedies=("确认未启用需要多模态或工具调用的功能。",),
        ),
    ),
    (
        "StructuredOutputError",
        Diagnosis(
            title="模型输出未通过结构校验",
            cause=(
                "本地小模型多次未能生成符合严格 JSON schema 的方案，"
                "或修订内容未真正满足审查智能体提出的必改项。"
                "系统选择明确报错，而不是放行一个不合格的方案。"
            ),
            remedies=(
                "重新点击生成，模型每次采样结果不同。",
                "把需求描述得更简洁具体，减少模型发挥空间。",
                "把最大审查轮次调为 1，减少修订失败的机会。",
                "适当增大单次最大生成 token，避免方案被截断。",
            ),
        ),
    ),
    (
        "MemoryError",
        Diagnosis(
            title="内存不足",
            cause="加载 GGUF 模型需要数 GiB 可用内存。",
            remedies=(
                "关闭占用内存较大的其他程序后重试。",
                "调小 PHI3_N_CTX 以降低内存占用。",
            ),
            env_hint="PHI3_N_CTX",
        ),
    ),
)


_UNKNOWN = Diagnosis(
    title="本地运行失败",
    cause="发生了未预期的错误，下方为原始错误信息，可用于进一步排查。",
    remedies=(
        "确认模型路径与 PHI3_MODEL_ROOT 配置正确。",
        "查看运行终端输出以获取完整堆栈。",
    ),
)


def _match(rules: tuple[tuple[str, Diagnosis], ...], haystack: str) -> Diagnosis | None:
    for fragment, diagnosis in rules:
        if fragment.casefold() in haystack.casefold():
            return diagnosis
    return None


def diagnose_text(message: str) -> Diagnosis:
    """Explain a failure that was already reduced to a stored message string.

    Run records keep the error as text, so the same rules are applied to it.
    """

    matched = _match(_MODEL_RULES, message) or _match(_RUNTIME_RULES, message)
    if matched is not None:
        return matched
    if "failed after" in message.casefold() or "schema" in message.casefold():
        return _match(_RUNTIME_RULES, "StructuredOutputError") or _UNKNOWN
    return _UNKNOWN


def diagnose(error: BaseException) -> Diagnosis:
    """Explain a runtime failure in operator-facing terms.

    Matching considers both the exception type name and its message so that
    configuration errors and runtime errors are both recognised.
    """

    haystack = f"{type(error).__name__}: {error}"
    matched = _match(_MODEL_RULES, haystack) or _match(_RUNTIME_RULES, haystack)
    if matched is not None:
        return matched
    return _UNKNOWN
