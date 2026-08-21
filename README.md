# AutoGen Azure Architecture Designer

基于 Microsoft AutoGen 和 Streamlit 的本地多智能体 Azure 架构设计 Web 应用。

项目将由两个独立智能体协作完成 Azure 架构方案：

- 规划智能体根据用户需求生成初始 Azure 资源配置和架构方案。
- 审查智能体检查高可用性、安全性和运维风险，并提出修正意见。
- 后端调度器组织有限轮次的协作闭环，最终产生结构化方案。
- Streamlit 前端展示任务进度、智能体消息和最终结果。

## 当前状态

仓库现处于开发准备阶段，已完成任务边界和目录结构整理，尚未实现智能体、本地模型适配或 Web 界面。

原始需求的结构化版本见 [`docs/task3-requirements.md`](docs/task3-requirements.md)，开发顺序见 [`DEVELOPMENT_ROADMAP.md`](DEVELOPMENT_ROADMAP.md)。

## 计划目录

```text
.
├── README.md
├── DEVELOPMENT_ROADMAP.md
├── requirements.txt
├── app.py
├── src/
│   ├── config.py
│   ├── local_model_client.py
│   ├── agents.py
│   ├── orchestrator.py
│   ├── prompts.py
│   ├── schemas.py
│   └── trace_writer.py
├── tests/
├── examples/
├── results/
└── docs/
```

## 本地闭环约束

- 不连接真实 Azure 订阅，不创建或修改云资源。
- 不要求 Azure、OpenAI 或其他云服务凭证。
- 模型权重、虚拟环境、运行记录和密钥不纳入源码仓库。
- 最终 ZIP 只包含可复现源码、必要文档、测试和少量示例。
