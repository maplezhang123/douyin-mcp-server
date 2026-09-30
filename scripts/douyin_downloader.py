#!/usr/bin/env python3
"""Command-line entry point for Douyin extraction."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from douyin_mcp_server.workflow import download_video as download_media
from douyin_mcp_server.workflow import resolve_video_info, run_verified_workflow

HEADERS = {}


def get_video_info(share_link: str) -> dict:
    return resolve_video_info(share_link)


def download_video(share_link: str, output_dir: str = ".") -> Path:
    info = resolve_video_info(share_link)
    if not info.get("url"):
        raise RuntimeError("浏览器降级未得到视频下载地址；请使用 extract 提取文案")
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{info['video_id']}.mp4"
    download_media(info, target)
    return target


def extract_text(share_link: str, api_key: str | None = None, output_dir: str | None = None,
                 save_video: bool = False, show_progress: bool = True, asr_mode: str | None = None,
                 deepseek_api_key: str | None = None, model: str = "small") -> dict:
    del save_video
    callback = print if show_progress else None
    return run_verified_workflow(
        share_link, output_dir or "./output", model_name=model,
        siliconflow_api_key=api_key, deepseek_api_key=deepseek_api_key,
        asr_mode=asr_mode, progress=callback,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="抖音链接转写与文案整理")
    parser.add_argument("--link", "-l", required=True, help="抖音链接或包含链接的分享文本")
    parser.add_argument("--action", "-a", choices=["info", "download", "extract"], default="info")
    parser.add_argument("--output", "-o", default="./output")
    parser.add_argument("--asr-mode", choices=["cloud", "local"], default=os.getenv("DOUYIN_ASR_MODE", "cloud"))
    parser.add_argument("--siliconflow-api-key", help="建议改用 SILICONFLOW_API_KEY 环境变量")
    parser.add_argument("--deepseek-api-key", help="可选；建议改用 DEEPSEEK_API_KEY 环境变量")
    parser.add_argument("--model", default="small", help="本地模式的 Whisper 模型")
    parser.add_argument("--quiet", "-q", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "info":
            info = get_video_info(args.link)
            print(f"视频 ID: {info['video_id']}\n标题: {info['title']}\n解析方式: {info.get('source', 'http')}")
        elif args.action == "download":
            print(f"视频已保存到: {download_video(args.link, args.output)}")
        else:
            result = extract_text(
                args.link, args.siliconflow_api_key, args.output, show_progress=not args.quiet,
                asr_mode=args.asr_mode, deepseek_api_key=args.deepseek_api_key, model=args.model,
            )
            print(result["text"])
            print(f"\n结果目录: {result['output_path']}")
            if result["organizer_error"]:
                print(f"提示: DeepSeek 整理失败，已保留原始逐字稿：{result['organizer_error']}", file=sys.stderr)
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
