# 工作日志

## 2026-08-21：仓库整理

- 整理 Task 3 交付范围与本地运行约束。
- 参考 Task 1 的本地 Phi-3 推理方案和 Task 2 的状态循环、trace 与测试组织方式。
- 建立基础目录、开发路线和仓库忽略规则。
- 本阶段未实现任何 AutoGen、Phi-3 或 Streamlit 业务代码。

## 2026-08-21：阶段 0 本地运行时验证

- 固定 Python 3.11 作为项目运行版本。
- 确认 Task 1 的 Phi-3 Mini Q4 GGUF 可用，模型权重不复制到本仓库。
- 采用 AutoGen AgentChat `ChatCompletionClient` 边界直接适配 `llama-cpp-python`，不启动本地 HTTP 代理。
- 本地 Phi-3 不声明原生函数调用或 JSON mode，后续通过受控 JSON 文本协议和确定性校验实现结构化输出。
- 新增配置诊断与真实模型冒烟入口。
- 默认 PyPI 通道一度出现 TLS/503 错误；切换到可达的 PyPI 镜像后完成安装，交付配置不绑定镜像地址。
- 实际运行 AutoGen 0.7.5 `AssistantAgent` 通过自定义客户端调用本地 Phi-3，获得非空响应与 prompt/completion token 用量，阶段 0 验收通过。

## 2026-08-21：阶段 1 结构化方案与双智能体

- 定义严格的架构需求、Azure 资源、完整方案、审查问题和审查决策数据结构。
- 规划与审查角色使用独立 AutoGen `AssistantAgent` 上下文，仅共享本地模型客户端。
- 结构化输出采用受控 JSON 文本协议和 Pydantic 校验，拒绝多余字段与矛盾的审查决策。
- 解析器容忍外层 JSON 代码围栏和单个 JSON 对象前后的简短说明，但拒绝多对象输出，不猜测字段名或修改参数值。
- 真实 Phi-3 冒烟验证生成了 4 个 Azure 资源的可解析方案，审查智能体返回 `revision_required` 及必改项，双角色链路通过。
