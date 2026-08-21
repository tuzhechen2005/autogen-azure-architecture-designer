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
- 实现事件回调、消息记录和可选 JSONL trace。

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

## 下一版本：完整测试和 ZIP 验收

下列内容不属于当前 Goal 的完成条件：

1. 建立完整单元与集成测试矩阵。
2. 增加更多 Azure 架构场景和回归数据。
3. 评测推理耗时、内存、输出合法率和审查收敛率。
4. 执行全新环境复现验收。
5. 生成不含 GGUF、`.venv`、密钥、缓存和 Git 数据的最终源码 ZIP。
6. 检查 ZIP 清单、哈希和 README 命令的可复现性。
