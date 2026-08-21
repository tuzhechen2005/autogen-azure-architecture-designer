# 安全修复台账

本文件只记录修复执行状态；原始证据以 `docs/security-audit-issues.md` 为准。

| ID | 标题 | 风险 | 被破坏的不变量 | 状态 | 失败测试 | 修复文件 | Commit | Push | 剩余风险 |
|---|---|---|---|---|---|---|---|---|---|
| SEC-01 | Phi-3 保留 token 可突破用户角色边界 | P1 | 用户输入不能改变消息角色边界 | needs-real-runtime-validation | `tests/test_local_model_client.py` | `src/local_model_client.py`; `src/prompts.py` | `8df755621e83ada0ffa195123a921d3366e3ed97` | pushed | 普通自然语言注入的服从率需真实模型验证；协议边界已由代码拒绝 |
| SEC-02 | 矛盾审查仍被标记为通过 | P1 | 任何未解决 finding 都不能 approved | pushed | `tests/test_schemas.py` | `src/schemas.py`; `src/prompts.py` | `6cfc4845440a5742b62ac8704932490fa4917f53` | pushed | 确定性架构完整性检查分别由后续问题处理 |
| SEC-03 | JSON 扫描器接受非唯一、非完整顶层对象 | P1 | 歧义、截断和重复键输出不得静默接受 | pushed | `tests/test_output_parser.py`; `tests/test_local_model_client.py` | `src/output_parser.py`; `src/local_model_client.py` | `3fb200b7e48bdf9e8dc583afe448cae8bb75ba9d` | pushed | 未知 finish reason 的策略仍保守保留为 unknown |
| SEC-04 | 全局无界模型缓存导致 OOM 与并发访问 | P1 | 缓存有界且同一可变模型 context 不并发 | needs-real-runtime-validation | `tests/test_local_model_client.py` | `src/local_model_client.py`; `app.py` | `6e7c703b7e5006ce1be3718500d2dbe7809f092a` | pushed | 真实 GGUF 峰值内存和原生并发行为需本地运行验证 |
| SEC-05 | Schema 校验不严格且不验证依赖图 | P2 | 格式合法不等于架构正确 | pushed | `tests/test_schemas.py`; `tests/test_output_parser.py` | `src/schemas.py`; `src/output_parser.py`; `app.py` | `bb8b8d9fca786638b1fe3ebe4ccd0d02d3a2286a` | pushed | 修订身份和必改项迁移约束由 SEC-06 处理 |
| SEC-06 | 修订阶段没有强制状态迁移约束 | P2 | 修订不得静默改变资源身份或忽略必改项 | pushed | `tests/test_orchestrator_revision.py`; `scripts/orchestrator_smoke_test.py` | `src/orchestrator.py`; `src/schemas.py`; `src/prompts.py`; `src/ui.py` | `9236359c12bc6ad8d1936775ae0ba792f80295da` | pushed | 术语约束证明设计文本已包含要求，不证明真实 Azure 行为 |
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

## SEC-03 第一性原则记录

- **资产：** 模型原始输出与实际解析决策的一致性，以及审批输入的完整性。
- **不可信入口：** 模型返回的任意文本、JSON 对象和原生 `finish_reason`。
- **信任边界：** llama.cpp 响应进入应用 Schema 与审批状态机。
- **被破坏的不变量：** 只接受唯一、完整、无重复键的顶层 JSON 对象；截断输出不得进入成功路径。
- **最小失败路径：** 在包装对象内部放置合法对象、在合法对象后追加损坏 JSON，或重复同名键；扫描器只选取一个 Schema-valid 候选并忽略其余原文。
- **当前代码为何允许：** 从每个 `{` 调用 `raw_decode`，未消费全文；标准 decoder 默认以最后一个重复键覆盖前值；`finish_reason=length` 仍返回 `CreateResult`。
- **根本原因：** 把结构化响应当成可搜索的候选集合，而不是一个必须原子验证的完整消息。
- **修复前失败测试：** `tests/test_output_parser.py` 中嵌套提升、数组提升、前后缀、截断尾部和重复键用例失败；`tests/test_local_model_client.py` 的 length 终止用例失败。
- **最小根本修复：** 去除可选完整外层代码围栏后只调用一次 `json.loads`；用 `object_pairs_hook` 在所有层拒绝重复键；length 终止直接抛出协议错误。
- **修复后证明：** 目标测试 9 项通过；正常完整对象和完整 JSON 代码围栏仍被接受，原始漏洞及相邻包装路径均被拒绝。
- **文档与代码差异：** 无；审计列出的三类解析绕过和 length 路径均可复现。
- **剩余风险：** Schema 的严格类型与依赖图语义属于 SEC-05；本项不通过默认值或纠错掩盖模型输出。

## SEC-04 第一性原则记录

- **资产：** 本机内存、llama.cpp 可变 context、跨会话输出隔离和 usage 计数。
- **不可信入口/故障：** 用户切换模型路径、上下文、CPU/Metal 或生成参数，以及多个会话同时推理。
- **信任边界：** Streamlit 全局资源生命周期与每个会话/运行的生成调用之间。
- **被破坏的不变量：** 进程最多保留一个模型 runtime；同一可变 context 最大并发必须为 1；被替换资源必须显式关闭。
- **最小失败路径：** 两个线程同时调用共享客户端；修复前假模型记录到 `max_active=2`。改变 `max_tokens` 等缓存键还会创建新的全局模型对象。
- **当前代码为何允许：** 无界 `st.cache_resource` 同时缓存权重和生成配置；共享 `_model` 的 reset、生成、分词与 usage 更新没有共同互斥锁或生命周期所有者。
- **根本原因：** 把有状态、昂贵且需显式释放的原生 context 当作普通纯函数缓存值。
- **修复前失败测试：** `SharedModelConcurrencyTests.test_serializes_calls_to_one_mutable_model_context` 稳定失败，观测值为 2、期望为 1。
- **最小根本修复：** 用进程级单槽注册表拥有 runtime；缓存身份只含规范化路径、`n_ctx`、GPU 层数和 seed；生成参数留在每次运行的轻量客户端；runtime 锁覆盖 reset/生成/分词/close；替换前和进程退出时显式 close。
- **修复后证明：** 双线程最大并发为 1 且 usage 完整；生成参数变化复用同一 runtime；身份变化按 close-old→load-new 顺序执行；close 幂等且关闭后调用安全失败。
- **文档与代码差异：** 无；无锁并发和生成参数参与缓存键均可复现。
- **验证限制：** 未加载真实 GGUF，尚未测量 3–5 个历史键的实际峰值内存，也未验证 llama.cpp 原生崩溃形态；代码级单槽和串行不变量已离线证明。

## SEC-05 第一性原则记录

- **资产：** 架构计划字段的原始语义、资源依赖完整性以及审批输入可信度。
- **不可信入口：** 模型 JSON 中的类型、缺失字段、资源名称和依赖边。
- **信任边界：** 严格 JSON 解析结果进入 Pydantic 数据契约和调度器。
- **被破坏的不变量：** 格式可解析不等于架构有效；模型输出不得被类型转换、默认值或推断逻辑静默修复。
- **最小失败路径：** `revision` 使用字符串/浮点/布尔，省略关键字段，或提交重名、悬空、自依赖/循环资源图；旧 Schema 全部接受。
- **当前代码为何允许：** `StrictModel` 未启用 strict；模型字段带默认值；before-validator 会包装标量并从 recommendation 推断缺失字段；计划没有图校验器。
- **根本原因：** 数据契约承担了容错修复职责，并只验证局部字段形状，没有表达跨资源语义。
- **修复前失败测试：** `ArchitecturePlanStrictnessTests` 共 16 个子用例失败；审查字段默认/派生共 4 个子用例失败。
- **最小根本修复：** 全局 StrictModel 开启严格模式；所有模型输出字段改为显式必填；删除标量包装和字段推断；计划 after-validator 强制名称唯一、依赖无重复、引用闭包、无自依赖且无环。
- **修复后证明：** 严格 Schema 和解析器 13 项测试通过；完整正常计划、无 finding 审批及脚本化 plan→review→revision→approval 流程通过。
- **文档与代码差异：** 无；审计列出的类型转换、默认值和依赖图问题均可复现。
- **剩余风险：** 修订阶段保持资源身份并落实 required_changes 的状态迁移约束属于 SEC-06。

## SEC-06 第一性原则记录

- **资产：** 计划资源身份、依赖语义、审查必改项以及状态机从 revision_required 到 approved 的可信度。
- **不可信入口：** planner 生成的修订计划，以及 reviewer 生成的 required_changes。
- **信任边界：** 已验证的当前计划/审查进入下一版计划，再进入后续审批。
- **被破坏的不变量：** 修订必须保持资源身份与依赖关系、产生实质变化，并落实每个机器可验证的必改项。
- **最小失败路径：** 只增加 revision 数字，或改名、增删资源、改变依赖，或仅在无关字段复述要求；旧调度器只检查 revision 数字，下一轮可直接 approved。
- **当前代码为何允许：** “保持名称和数量”只存在于提示词；required_changes 是不可验证的自由文本；解析成功后没有前后状态比较。
- **根本原因：** 状态迁移契约没有代码表示，控制流把两份各自合法的快照误当作合法迁移。
- **修复前失败测试：** 完整假模型调度器中未修改、改名、新增、删除、依赖变化和错误目标字段 6 个子用例全部得到 `completed/approved`，期望 failed。
- **最小根本修复：** required_changes 改为受限目标字段、资源名和必含术语；修订解析边界比较名称集合、类型、依赖边和除 revision 外的内容，并逐项验证目标字段。
- **修复后证明：** 6 个非法迁移均失败；正确 API high_availability 目标含 `two instances` 的脚本化全流程通过；UI 仍显示人类可读 description。
- **文档与代码差异：** 无；审计列出的改名、增删和忽略修改均可复现。
- **剩余风险：** 本工具只输出设计文本；字段术语约束证明输出落实了审查要求，不等同于真实 Azure 部署或运行验证。
