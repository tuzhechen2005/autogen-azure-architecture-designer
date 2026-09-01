# Phase 5 有限协作与评测说明

本项目只在本地生成和审查 Azure 架构建议，不连接订阅，也不部署资源。

## 状态与终止

`data/state_transition_rules.json` 是状态转换的唯一机器目录。规则 ID 连续使用 `TR-001` 格式；每条包含起止状态、触发器、前置条件、输出契约和终止条件。规则数必须由 `src/state_rules.py` 统计，不在简历中手填。

协作仍受全局墙钟、每次结构解析纠错和最大 Reviewer 轮数约束。达到最大轮数返回 `degraded/max_review_rounds`；相同 required changes 再次出现且没有新进展时返回 `degraded/no_progress`；墙钟耗尽返回独立 `timeout`，不再混入 generic failed。

## 契约与拓扑

Planner、Reviewer、意见处置和终态均由严格 Pydantic 模型约束。资源名称唯一、引用必须存在、依赖不可重复、不可自环且全图无环。额外拓扑策略使用 Azure 类型白名单，并为有明确后端要求的资源校验依赖类型；未知类型或缺少必需依赖会在进入下一 Agent 前被拒绝。

Reviewer 每条 required change 都生成 `implemented` 或 `unresolved` 处置记录，并保留目标字段作为机器证据。只有 required terms 全部出现在目标字段时才计 implemented。

## 数据与指标

有效冻结数据位于共享评测目录：64 条架构需求覆盖规模、可用性、数据、安全、预算、RTO/RPO、区域与冲突约束；32 条故障/对抗用例覆盖持续反驳、重复方案、非法 JSON、超时、未知资源、依赖环、未解决意见和 prompt injection。冻结集在 Phase 9 才允许模型推理。

评分器自动计算结构化输出成功率、需求点覆盖率、依赖合法率、审查落实率、平均轮数、fallback 率与 P50/P95。ablation 已预注册单 Agent、Planner+Reviewer、无契约、完整契约和最大轮数 1/3；正式模型对照必须使用相同冻结前配置和数据，不能把 fixture 测试当成质量提升。

## Trace

每轮消息记录 Agent 角色、阶段、轮次、输入摘要 SHA-256、原始输出 SHA-256、解析状态、耗时和 token 数。默认落盘 trace 不含完整需求或模型文本，只保留这些摘要、资源/问题/必改项数量、意见处置和终止原因。原始模型输出在正式评测中另存唯一 run 目录，不允许覆盖或修复。

Phase 7 已在上述记录之上增加统一 trace、共享错误 taxonomy、状态规则 hash、循环故障契约和精确 canary 脱敏；详细 RED/GREEN 与验证证据见 `docs/phase7_task3_adoption.md`。
