# Phase 7 Task 3 接入证据

日期：2026-09-01

范围：仅 Task 3 的状态机、协作轮次、终止状态、共享 trace 和循环故障；未调用 Azure，也未运行真实模型。

## 接入结果

- `src/phase7_evidence.py` 将每次 Planner/Reviewer 消息映射到 Phase 7 统一 trace 字段，并校验共享 JSON Schema。
- trace 固定记录共享 trace、错误 taxonomy、安全 canary、故障 Schema 和本地状态规则的 SHA-256；本次固定值由代码读取文件后计算，不手填指标。
- 非法 JSON、Schema 失败和非法修订状态分别使用 `parse`、`schema`、`state`；无效输入的终态使用 `input`。
- 重复 Reviewer 意见故障终止为 `degraded/no_progress`，不继续盲目重试，保留最新已校验方案。
- 默认 trace 继续排除完整需求和模型文本；即使显式保存敏感内容，共享 canary 也会替换为 `[REDACTED]`。原始模型输出对象没有被改写。
- Task 3 不使用内容缓存；trace 明确记录 `bypass` 和 `task3-no-content-cache-v1`，不虚构缓存收益。

## RED → GREEN 记录

| 场景 | RED 证据 | GREEN 证据 |
| --- | --- | --- |
| Phase 7 适配器缺失 | 新测试收集时报 `ModuleNotFoundError: src.phase7_evidence` | `tests.test_phase7_evidence` 通过 |
| 共享 YAML 依赖缺失 | 导入共享 validator 报缺少 `yaml` | 明确加入 `PyYAML==6.0.3` 和哈希锁；`pip check` 通过 |
| 非法 JSON 错误层 | `TranscriptMessage` 无 `validation_error_category` | 消息与共享 trace 均为 `parse` |
| 无效输入终态 | 共享 trace 错误地报告 `model` | 终态报告 `input/failed` |
| 私有 span 缺少类别 | span 查询触发 `KeyError` | span 保存精确错误类别 |
| 修订失败终态错误层 | 消息为 `state` 但终态误报 `model` | 消息和终态均为 `state` |

普通工具失败也原样保留：`pip-compile` 与当前 pip 26 / pip-tools 7.5.2 不兼容，因此没有重写完整锁文件；仅加入从官方 PyPI 元数据核验过的 PyYAML wheel/sdist 哈希。首次 RED 命令还误用了 zsh 只读变量 `status`，改为 `rc` 后重新执行，未改变测试结果。

## 验证结果

- 聚焦回归：23 项通过。
- Task 3 全量：125 项 Python 通过；Phase 5 基线为 118，数量增加 7。
- 共享契约：19 项 Python 通过。
- Ruff lint：全仓通过；本次修改的 7 个 Python 文件 Ruff format 通过。
- `compileall`、`pip check`、`git diff --check`：通过。
- 全仓 format 探测发现 25 个既有文件与当前 Ruff 默认格式不同；没有为本任务批量改写无关文件。本次修改文件全部通过格式门禁。

完整命令输出保存在 `/tmp/task3-p7-*.log`，它们是本机过程日志，不纳入交付或 Git。上述数字来自测试运行摘要，不代表真实模型质量或生产容量。

## 差异与安全边界

- 只修改 Task 3 源码、测试、依赖锁和本文件；未删除文件。
- `app.py` 仅把本地模型文件名作为 trace 模型身份，不写入模型绝对路径。
- 没有 Azure SDK 资源写操作、云端模型调用或外部凭据。
- 正式冻结集没有运行、读取后调参或修改；Phase 9 前仍保持冻结。
