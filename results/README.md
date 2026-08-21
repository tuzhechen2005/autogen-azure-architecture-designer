# 本地运行结果

在 Streamlit 侧边栏启用“保存脱敏的本地运行记录”后，每次 run 会原子发布到独立文件：

```text
results/architecture_runs/<run_id>.json
```

默认文件只包含运行所需的脱敏元数据：

- `run_id`：本地运行标识。
- `status`：`completed` 或 `failed`。
- `termination_reason`：`approved`、`max_review_rounds` 或 `error`。
- `message_count`、`plan_revision`、`review_decision`：不含正文的流程摘要。
- `started_at` / `finished_at`：UTC 时间。
- `has_error`：是否存在错误，不保存可能含路径的错误正文。

目录固定为 `0700`、文件固定为 `0600`，拒绝符号链接并先完整写入临时文件再原子发布。
记录目录默认由 `.gitignore` 排除。底层 API 虽支持显式保存敏感正文，Streamlit UI 不启用该选项；
含敏感内容的记录不得提交或分享。
