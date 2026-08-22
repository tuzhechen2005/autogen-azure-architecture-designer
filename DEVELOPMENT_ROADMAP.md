# 开发路线

## 当前版本：Task 3 功能交付

### 阶段 0：本地 AutoGen 运行时（已完成）

- 固定 Python 3.11、AutoGen 0.7.5 和 `llama-cpp-python` 0.3.34。
- 实现 AutoGen `ChatCompletionClient` 到本地 Phi-3 GGUF 的进程内适配。
- 真实验证 Metal 和 CPU 回退路径。

证据：`scripts/smoke_test.py`。

### 阶段 1：结构化方案与双智能体（已完成）

- 定义 Azure 资源、方案、审查问题和审查决策数据契约。
- 实现独立的规划智能体和审查智能体。
- 实现受控 JSON 协议和确定性校验。

证据：`scripts/agent_smoke_test.py`。

### 阶段 2：多智能体协作闭环（已完成）

- 实现规划、审查、修订和再审的显式上下文传递。
- 实现审查通过、最大轮次和错误三类终止路径。
- 实现事件回调、消息记录和可选的逐 run 脱敏 JSON trace。

证据：`scripts/orchestrator_smoke_test.py` 及其 `--real` 路径。

### 阶段 3：Streamlit Web 界面（已完成）

- 实现需求输入、本地配置和任务启动。
- 按智能体阶段展示进度与角色消息。
- 展示最终资源清单、架构策略、审查结论和原始消息。
- 通过模型缓存和 Session State 避免页面重绘触发重复推理。

证据：Streamlit AppTest 和 `/_stcore/health` 启动检查。

### 阶段 4：第一版文档与交付整理（已完成）

- 补齐 README、依赖、模型准备、运行和已知限制。
- 增加模块架构说明与多场景需求示例。
- 确认模型、凭证、虚拟环境和运行数据不进入仓库。

## 安全修复轮次：完整测试和 ZIP 验收（已完成）

本轮已补齐以下验收能力：

1. 建立离线单元与脚本化集成测试矩阵。
2. 执行带 SHA-256 依赖锁的全新环境复现验收。
3. 使用 committed Git tree allowlist 生成源码 ZIP。
4. 自动拒绝 GGUF、`.venv`、密钥、缓存、swap、trace、符号链接和 Git 数据。
5. 检查 ZIP 清单、逐文件内容、大小和 SHA-256。

真实 GGUF 的推理耗时、内存、输出合法率和审查收敛率仍需在模型可用的本机环境验证。
