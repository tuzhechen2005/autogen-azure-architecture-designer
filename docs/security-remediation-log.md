# 安全修复台账

本文件只记录修复执行状态；原始证据以 `docs/security-audit-issues.md` 为准。

| ID | 标题 | 风险 | 被破坏的不变量 | 状态 | 失败测试 | 修复文件 | Commit | Push | 剩余风险 |
|---|---|---|---|---|---|---|---|---|---|
| SEC-01 | Phi-3 保留 token 可突破用户角色边界 | P1 | 用户输入不能改变消息角色边界 | needs-real-runtime-validation | `tests/test_local_model_client.py` | `src/local_model_client.py`; `src/prompts.py` | `8df755621e83ada0ffa195123a921d3366e3ed97` | pushed | 普通自然语言注入的服从率需真实模型验证；协议边界已由代码拒绝 |
| SEC-02 | 矛盾审查仍被标记为通过 | P1 | 任何未解决 finding 都不能 approved | pushed | `tests/test_schemas.py` | `src/schemas.py`; `src/prompts.py` | `6cfc4845440a5742b62ac8704932490fa4917f53` | pushed | 确定性架构完整性检查分别由后续问题处理 |
| SEC-03 | JSON 扫描器接受非唯一、非完整顶层对象 | P1 | 歧义、截断和重复键输出不得静默接受 | confirmed | pending | pending | pending | pending | 待处理 |
| SEC-04 | 全局无界模型缓存导致 OOM 与并发访问 | P1 | 缓存有界且同一可变模型 context 不并发 | confirmed | pending | pending | pending | pending | 待处理 |
| SEC-05 | Schema 校验不严格且不验证依赖图 | P2 | 格式合法不等于架构正确 | confirmed | pending | pending | pending | pending | 待处理 |
| SEC-06 | 修订阶段没有强制状态迁移约束 | P2 | 修订不得静默改变资源身份或忽略必改项 | confirmed | pending | pending | pending | pending | 待处理 |
| SEC-07 | 视觉空输入/控制字符通过校验且校验过晚 | P2 | 无效输入不得触发昂贵模型加载 | confirmed | pending | pending | pending | pending | 待处理 |
| SEC-08 | 模型路径校验不足 | P2 | 非 GGUF、相对路径、目录和 symlink 必须拒绝 | confirmed | pending | pending | pending | pending | 待处理 |
| SEC-09 | 推理无超时、生成期取消和上下文预算预检 | P2 | 推理、等待与重试必须有界 | confirmed | pending | pending | pending | pending | 待处理 |
| SEC-10 | 新运行失败后仍展示旧成功结果 | P2 | 新任务失败不能展示旧任务结果 | confirmed | pending | pending | pending | pending | 待处理 |
| SEC-11 | trace 失败与 UI 完成终态矛盾 | P2 | 每个 run 只有一个明确终态 | confirmed | pending | pending | pending | pending | 待处理 |
| SEC-12 | trace 文件隐私、并发和链接安全问题 | P2 | trace 不泄露、不混写、不跟随链接且可恢复 | confirmed | pending | pending | pending | pending | 待处理 |
| SEC-13 | CPU 回退永久污染进程环境 | P2 | 后端配置不得跨运行或会话污染 | confirmed | pending | pending | pending | pending | 待处理 |
| SEC-14 | 模型文本经 Markdown 渲染可触发外部请求 | P2 | 模型输出不得触发外部请求 | confirmed | pending | pending | pending | pending | 待处理 |
| SEC-15 | 依赖未完整锁定 | P3 | 干净环境安装必须可复现 | confirmed | pending | pending | pending | pending | 待处理 |
| SEC-16 | 朴素 ZIP 会包含 Git 忽略的敏感文件 | P3 | 敏感文件不得进入最终交付物 | confirmed | pending | pending | pending | pending | 待处理 |

## SEC-01 第一性原则记录

- **资产：** system/user/assistant 角色边界、系统提示完整性、审查结果可信度。
- **不可信入口：** 用户需求，以及被再次放入消息上下文的模型生成文本。
- **信任边界：** AutoGen `LLMMessage.content` 到 Phi-3 原生 instruct token 字符串。
- **被破坏的不变量：** 消息内容只能是数据，不能创建新的协议角色或结束当前角色。
- **最小失败路径：** 内容包含 `<|end|>` 后跟 `<|system|>` 或 `<|assistant|>`；渲染器原样拼接，形成新的协议段。
- **当前代码为何允许：** `_render_phi3_prompt` 只映射外层消息角色，不检查内层文本中的协议 token。
- **根本原因：** 控制结构和不可信数据共享同一种未经转义或拒绝的字符串表示。
- **修复前失败测试：** `.venv/bin/python -m unittest discover -s tests -p 'test_local_model_client.py' -v`；5 种 token 在用户输入和模型生成文本两条路径共 10 个子用例失败，正常对照通过。
- **最小根本修复：** 在唯一协议渲染边界拒绝任意 `<|…|>` 形式的 token；系统提示同时声明需求和 JSON 为不可信数据。
- **修复后证明：** 同一命令 3 个测试通过；覆盖已知角色/结束 token、通用 token 形态、两类不可信来源和正常渲染。
- **文档与代码差异：** 无；审计描述可在修复前代码稳定复现。
- **验证限制：** 未运行真实 GGUF；普通自然语言 prompt injection 的具体服从率仍需真实本地运行验证。`scripts/agent_smoke_test.py` 因环境未配置 `PHI3_MODEL_PATH` 在加载模型前失败。

## SEC-02 第一性原则记录

- **资产：** 审批终态、绿色成功 UI 和最终架构的可信度。
- **不可信入口：** 审查模型返回的 `decision`、`findings` 和 `required_changes`。
- **信任边界：** 模型 JSON 经 Pydantic Schema 进入 orchestrator 终态判断。
- **被破坏的不变量：** 任何未解决 finding 都不能得到 `approved`。
- **最小失败路径：** `decision="approved"`、一个 finding、`required_changes=[]`；Schema 接受后调度器直接返回 `completed/approved`。
- **当前代码为何允许：** validator 只关联 `decision` 与 `required_changes`，没有关联 `findings`。
- **根本原因：** 把模型声明的决策当作权威，而 Schema 没有表达批准所需的完整跨字段条件。
- **修复前失败测试：** `.venv/bin/python -m unittest discover -s tests -p 'test_schemas.py' -v`；critical、high、medium、low 四个子用例失败，空 findings 正向对照通过。
- **最小根本修复：** Schema 强制 `approved` 同时满足 `findings=[]` 与 `required_changes=[]`；提示契约同步明确该条件。
- **修复后证明：** Schema 回归测试覆盖全部 finding 严重度、无 finding 正常批准，以及既有调度器完整流程。
- **文档与代码差异：** 无；问题可稳定复现。
- **剩余风险：** 资源唯一性、依赖闭包和修订约束属于 SEC-05、SEC-06，尚未在本提交处理。
