---
name: douyin-video
description: "提取抖音普通、精选或短链接的音频与文案；HTTP 失败自动使用浏览器，默认 SiliconFlow SenseVoice，支持可选本地 Whisper。"
---

# 抖音文案提取

使用项目的统一工作流，不自行复刻抖音页面解析。

## 配置

- 默认模式：DOUYIN_ASR_MODE=cloud
- 云端 ASR：SILICONFLOW_API_KEY（必需）
- 文案整理：DEEPSEEK_API_KEY（可选）
- 本地模式：DOUYIN_ASR_MODE=local，并安装 local 额外依赖

不要要求用户提供维护者电脑上的绝对路径，也不要输出完整 API Key。

## 支持链接

- https://www.douyin.com/video/<video_id>
- https://www.douyin.com/jingxuan?modal_id=<video_id>
- 带 aweme_id 或 item_ids 的链接
- v.douyin.com 短链接

## 执行

命令行：

    uv run python scripts/douyin_downloader.py --link "<链接>" --action extract

处理顺序：

1. HTTP 快速解析。
2. 失败时自动使用 Chrome、Edge 或 Playwright Chromium。
3. 获取并校验音频。
4. 默认使用 SiliconFlow SenseVoiceSmall；本地模式使用 faster-whisper。
5. 有 DeepSeek Key 时整理文案；没有或整理失败时保留原始逐字稿。

向用户返回文案、标题、视频 ID、解析方式和 ASR 模型。错误应使用可理解的中文，不暴露内部绝对路径。
