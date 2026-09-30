# 抖音文案提取器（Windows 维护版）

把抖音视频链接粘贴进 WebUI，自动获取音频并用 SenseVoice 生成逐字稿。HTTP 快速解析失效时，程序会自动使用电脑已有的 Chrome 或 Edge，不需要用户理解页面内部结构。

本项目基于 [yzfly/douyin-mcp-server](https://github.com/yzfly/douyin-mcp-server) 继续维护。感谢原作者和贡献者；本 fork 保留原项目的 Apache-2.0 许可与归属说明。

## 为什么有这个 fork

原项目停止维护后，抖音页面结构、精选链接和浏览器签名流程已经变化。这个版本集中修复新版链接与浏览器降级，并把默认 ASR 改为轻量、快速的 SiliconFlow SenseVoice，清除了维护者工作站的绝对路径依赖。

| 能力 | v1.0 |
|---|:---:|
| 普通 /video/ 链接 | ✅ |
| jingxuan?modal_id= | ✅ |
| aweme_id / item_ids / 短链跳转 | ✅ |
| HTTP 快速解析 | ✅ |
| Chrome → Edge → Playwright Chromium 降级 | ✅ |
| SiliconFlow 云 ASR | ✅ 默认 |
| 本地 Whisper | ✅ 可选 |
| Windows 一键启动 | ✅ |
| 固定 D:\AI_Tools | ❌ 已移除 |

## Windows 快速开始

需要先安装 [uv](https://docs.astral.sh/uv/)、[Node.js 18+](https://nodejs.org/)、[FFmpeg](https://ffmpeg.org/) 以及 Chrome 或 Edge。

    git clone https://github.com/maplezhang123/douyin-mcp-server.git
    cd douyin-mcp-server
    .\start.bat

start.bat 会检查依赖并启动 WebUI，不会永久修改系统环境。启动 WebUI 后访问 http://localhost:8080。

手动启动：

    uv sync --extra web
    npm install
    uv run --extra web python web/app.py

## API Key 配置

### SiliconFlow（云端模式必需）

在 [SiliconFlow](https://cloud.siliconflow.cn/) 创建 Key，然后在 WebUI 的 “SiliconFlow API Key” 输入框填写。Key 只保存在浏览器 localStorage，并发送给本机服务。

也可在当前 PowerShell 设置：

    $env:SILICONFLOW_API_KEY="sk-..."

默认使用 FunAudioLLM/SenseVoiceSmall。上传前转换为 16 kHz、单声道、64 kbps MP3；超出单次限制时自动切片。

### DeepSeek（可选）

DeepSeek 只负责去口水词、补标点和分段：

    $env:DEEPSEEK_API_KEY="sk-..."

没有 DeepSeek Key 时仍会正常返回并保存 SenseVoice 原始逐字稿。DeepSeek 请求失败也不会丢失已完成的 ASR 结果。

环境变量示例见 [.env.example](.env.example)。服务不会把完整 Key 写入日志或输出文件。

## 切换到本地 Whisper

本地模式是可选的离线高级模式，不是默认依赖：

    uv sync --extra web --extra local
    $env:DOUYIN_ASR_MODE="local"
    uv run --extra web --extra local python web/app.py

也可直接在 WebUI 选择“本地 Whisper”。首次使用会按 faster-whisper 的标准方式下载模型；默认使用 small / CPU int8。可用 DOUYIN_MODEL_HUB 指定缓存目录，未设置时使用标准 Hugging Face 缓存，不依赖固定盘符。

## 工作流程

1. 从普通、精选、API 参数或短链接中识别视频 ID。
2. 先尝试 HTTP 解析和下载；失败后自动启动 Chrome、Edge，最后才尝试 Playwright 自带 Chromium。
3. FFmpeg 准备音频。
4. 默认上传 SiliconFlow SenseVoice；本地模式使用 faster-whisper。
5. 有 DeepSeek Key 时整理文案；没有或整理失败时返回原始逐字稿。

输出位于 output/<video_id>/：

    audio.m4a
    transcript-raw.md
    copy.md
    metadata.json
    run-report.json

WebUI 展示标题、视频 ID、原始逐字稿、可选整理文案、耗时、解析方式和 ASR 模型。

## 命令行与 MCP

    uv run python scripts/douyin_downloader.py -l "抖音链接" -a info
    $env:SILICONFLOW_API_KEY="sk-..."
    uv run python scripts/douyin_downloader.py -l "抖音链接" -a extract
    uv run --extra local python scripts/douyin_downloader.py -l "抖音链接" -a extract --asr-mode local

MCP 入口为 douyin-mcp-server，提供 extract_douyin_text、parse_douyin_video_info、get_douyin_download_link 和 recognize_audio_file。

## 常见问题与排错

**HTTP 页面中没有 videoInfoRes / _ROUTER_DATA**
这是页面结构变化导致的快速解析失败。程序会自动进入浏览器降级；只要浏览器成功，无需处理该内部错误。

**未检测到 Node.js**
安装 Node.js 18+，重新打开终端，用 node -v 确认。

**Playwright package 不存在**
运行 npm install。项目优先使用 Chrome/Edge，通常不必额外下载约 200 MB 的 Chromium。

**未检测到 Chrome/Edge**
安装 Chrome 或 Edge。确需自带浏览器时运行 npx playwright install chromium。

**未检测到 ffmpeg**
运行 winget install Gyan.FFmpeg，重新打开终端，再用 ffmpeg -version 确认。

**SiliconFlow Key 未填写、无效或网络失败**
确认 WebUI 输入或 SILICONFLOW_API_KEY，检查余额与网络。自动测试不会调用真实 API。

**faster-whisper-medium 权重不存在**
默认流程不使用 medium，也不要求下载 GB 级模型。本地模式建议先用 small；模型可自动下载或通过 DOUYIN_MODEL_HUB 指定缓存。

**DeepSeek 失败**
结果仍包含原始逐字稿。检查可选的 DEEPSEEK_API_KEY 后可重试。

## 测试

    uv run python -m unittest discover -s tests -v
    uv run python -c "import douyin_mcp_server.server, scripts.douyin_downloader, web.app"

测试使用 mock，不访问抖音，也不消耗付费 API。

## 来源、许可与免责声明

Based on / forked from: [yzfly/douyin-mcp-server](https://github.com/yzfly/douyin-mcp-server).

项目按 [Apache License 2.0](LICENSE) 发布。仅供学习与研究；请遵守平台条款、版权与当地法律，不要处理无权使用的内容。
