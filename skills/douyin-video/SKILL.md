---
name: douyin-video
description: "抖音链接转写和口播整理工具。HTTP 解析失败自动降级到共享 Playwright，使用本机 faster-whisper-medium 转写，再由 DeepSeek 整理成口播文案。"
---

# 抖音无水印视频下载和文案提取

从抖音分享链接获取媒体，使用本机语音识别生成逐字稿，再整理成可用口播文案。

## 功能概述

- **获取下载链接**: 从抖音分享链接解析出无水印视频的直接下载地址 (无需 API 密钥)
- **下载视频**: 将无水印视频下载到本地指定目录
- **浏览器降级**: HTTP 解析失败时自动使用共享 Playwright 捕获签名音频
- **本地转写**: 使用 `faster-whisper-medium / CPU int8`，不消耗 ASR API
- **整理口播**: 使用 DeepSeek 去重复、补标点和结构，不虚构内容
- **自动保存**: 每个视频的文案自动保存到独立文件夹 (视频ID为文件夹名)

## 环境要求

### 依赖安装

```bash
uv sync --extra web
```

### 系统要求

- FFmpeg/ffprobe 必须可用
- Windows 浏览器降级使用 `D:\AI_Tools\bin\playwright-node.cmd`
- 模型权重默认读取 `D:\AI_Tools\models\huggingface\hub`

### API 密钥配置

本地 ASR 不需要密钥；最后的口播整理需要设置：

```bash
set DEEPSEEK_API_KEY=your-deepseek-api-key
```

密钥只放环境变量，不写入仓库和运行报告。

## 使用方法

### 方法一: 使用脚本 (推荐)

```bash
# 获取视频信息和下载链接 (无需 API 密钥)
python scripts/douyin_downloader.py --link "抖音分享链接" --action info

# 下载视频到指定目录
python scripts/douyin_downloader.py --link "抖音分享链接" --action download --output ./videos

# 提取逐字稿并整理口播 (需要 DEEPSEEK_API_KEY)
python scripts/douyin_downloader.py --link "抖音分享链接" --action extract --output ./output

# 安静模式 (减少输出)
python scripts/douyin_downloader.py --link "抖音分享链接" --action extract --output ./output --quiet
```

### 输出目录结构

提取文案后, 每个视频会保存到独立文件夹:

```
output/
├── 7600361826030865707/      # 视频ID为文件夹名
│   ├── audio.m4a             # 已校验的完整音频
│   ├── transcript-raw.md     # 本机 ASR 原始逐字稿
│   ├── copy.md               # DeepSeek 整理后的口播
│   ├── metadata.json
│   └── run-report.json       # 五阶段状态和验证证据
├── 7581044356631612699/
│   └── ...
└── ...
```

### 方法二: 在 Python 代码中调用

```python
from scripts.douyin_downloader import get_video_info, download_video, extract_text

# 获取视频信息
info = get_video_info("抖音分享链接")
print(f"视频ID: {info['video_id']}")
print(f"标题: {info['title']}")
print(f"下载链接: {info['url']}")

# 下载视频
video_path = download_video("抖音分享链接", output_dir="./videos")

# 提取文案并保存到文件
result = extract_text("抖音分享链接", output_dir="./output")
print(f"文案已保存到: {result['output_path']}")
print(result['text'])
```

## 工作流程

### 获取视频信息

1. 解析抖音分享链接, 提取真实的视频 URL
2. 模拟移动端请求获取页面数据
3. 从页面 JSON 数据中提取无水印视频地址
4. 返回视频 ID, 标题和下载链接

### 提取视频文案

1. 使用 HTTP 解析分享链接；失败时自动降级到 Playwright
2. HTTP 分支下载视频；浏览器分支按 Range 下载签名音频
3. HTTP 分支用 FFmpeg 抽音；浏览器分支用 ffprobe 校验完整音频
4. 使用本机 `faster-whisper-medium / CPU int8` 生成带时间戳逐字稿
5. 使用 DeepSeek 整理成口播文案，并写入运行报告

## 常见问题

### 无法解析链接

- 确保链接是有效的抖音分享链接
- 链接格式通常为 `https://v.douyin.com/xxxxx/` 或完整的抖音视频 URL

### 提取文案失败

- 检查 `DEEPSEEK_API_KEY` 环境变量是否已设置
- 检查本地 medium 模型权重是否完整
- 检查共享 Playwright 包装器与浏览器缓存是否可用
- 确保 FFmpeg 已正确安装

### 下载速度慢

- 这取决于网络条件和视频大小
- 脚本会显示下载进度

## 注意事项

- 本工具仅供学习和研究使用
- 使用时需遵守相关法律法规
- 请勿用于任何侵犯版权或违法的目的
