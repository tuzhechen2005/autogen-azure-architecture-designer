# 本地运行结果

在 Streamlit 侧边栏启用“保存本地 JSONL 运行记录”后，每次运行会追加到：

```text
results/architecture_runs.jsonl
```

每行是一次完整运行，包含：

- `run_id`：本地运行标识。
- `request`：用户输入的架构需求。
- `status`：`completed` 或 `failed`。
- `termination_reason`：`approved`、`max_review_rounds` 或 `error`。
- `final_plan`：最新通过结构校验的架构方案。
- `final_review`：最新审查决策和问题。
- `messages`：角色、阶段、轮次、原始消息和解析结果。
- `started_at` / `finished_at`：UTC 时间。
- `error`：失败时的结构化错误摘要。

JSONL 默认由 `.gitignore` 排除。其中可能包含用户需求和本地模型原始输出，不应在未脱敏的情况下提交或分享。
