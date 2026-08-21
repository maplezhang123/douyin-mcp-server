# 贡献指南

感谢贡献。请保持改动小而聚焦，并在提交前运行：

```bash
uv sync --extra web
uv run python -m unittest discover -s tests -v
uv run python -m compileall -q douyin_mcp_server scripts web tests
```

请不要提交 API Key、模型权重、音视频素材、`output/`、`.venv/` 或 `dist/`。

涉及抖音链接转写的改动，应保留 HTTP 解析失败后降级到 Playwright 的行为，并在 `run-report.json` 中保留可核对的阶段信息。
