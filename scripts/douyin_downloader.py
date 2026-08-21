#!/usr/bin/env python3
"""
抖音链接转写与口播整理工具

功能:
1. HTTP 解析抖音分享链接，失败时自动降级到 Playwright
2. 下载媒体并准备音频
3. 使用本机 faster-whisper-medium 生成逐字稿
4. 使用 DeepSeek 整理成口播文案

环境变量:
- DOUYIN_DEEPSEEK_API_KEY: DeepSeek API 密钥 (用于口播整理)

使用示例:
  # 获取下载链接 (无需 API 密钥)
  python douyin_downloader.py --link "抖音分享链接" --action info

  # 下载视频
  python douyin_downloader.py --link "抖音分享链接" --action download --output ./videos

  # 提取文案并保存到文件 (需要 DOUYIN_DEEPSEEK_API_KEY 环境变量)
  python douyin_downloader.py --link "抖音分享链接" --action extract --output ./output
"""

import os
import re
import sys
import json
import argparse
import tempfile
import shutil
from pathlib import Path
from typing import Optional
from datetime import datetime


def check_dependencies():
    """检查必要的依赖是否已安装"""
    missing = []
    try:
        import requests
    except ImportError:
        missing.append("requests")
    try:
        import ffmpeg
    except ImportError:
        missing.append("ffmpeg-python")

    if missing:
        print(f"缺少依赖: {', '.join(missing)}")
        print(f"请运行: pip install {' '.join(missing)}")
        sys.exit(1)


check_dependencies()

import requests
import ffmpeg

from douyin_mcp_server.workflow import resolve_video_info, run_verified_workflow

# 请求头，模拟移动端访问
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/121.0.2277.107 Version/17.0 Mobile/15E148 Safari/604.1'
}

# 旧版云端 ASR 常量和辅助方法仅为兼容已有 Python 调用保留；
# CLI 的 extract 动作已经统一改走 run_verified_workflow。
DEFAULT_API_BASE_URL = "https://api.siliconflow.cn/v1/audio/transcriptions"
DEFAULT_MODEL = "FunAudioLLM/SenseVoiceSmall"


class DouyinProcessor:
    """抖音视频处理器"""

    def __init__(self, api_key: str = "", api_base_url: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key
        self.api_base_url = api_base_url or DEFAULT_API_BASE_URL
        self.model = model or DEFAULT_MODEL
        self.temp_dir = Path(tempfile.mkdtemp())

    def __del__(self):
        """清理临时目录"""
        if hasattr(self, 'temp_dir') and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def parse_share_url(self, share_text: str) -> dict:
        """从分享文本中提取无水印视频链接"""
        # 提取分享链接
        urls = re.findall(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', share_text)
        if not urls:
            raise ValueError("未找到有效的分享链接")

        share_url = urls[0]
        share_response = requests.get(share_url, headers=HEADERS)
        video_id = share_response.url.split("?")[0].strip("/").split("/")[-1]
        share_url = f'https://www.iesdouyin.com/share/video/{video_id}'

        # 获取视频页面内容
        response = requests.get(share_url, headers=HEADERS)
        response.raise_for_status()

        pattern = re.compile(
            pattern=r"window\._ROUTER_DATA\s*=\s*(.*?)</script>",
            flags=re.DOTALL,
        )
        find_res = pattern.search(response.text)

        if not find_res or not find_res.group(1):
            raise ValueError("从HTML中解析视频信息失败")

        # 解析JSON数据
        json_data = json.loads(find_res.group(1).strip())
        VIDEO_ID_PAGE_KEY = "video_(id)/page"
        NOTE_ID_PAGE_KEY = "note_(id)/page"

        if VIDEO_ID_PAGE_KEY in json_data["loaderData"]:
            original_video_info = json_data["loaderData"][VIDEO_ID_PAGE_KEY]["videoInfoRes"]
        elif NOTE_ID_PAGE_KEY in json_data["loaderData"]:
            original_video_info = json_data["loaderData"][NOTE_ID_PAGE_KEY]["videoInfoRes"]
        else:
            raise Exception("无法从JSON中解析视频或图集信息")

        data = original_video_info["item_list"][0]

        # 获取视频信息
        video_url = data["video"]["play_addr"]["url_list"][0].replace("playwm", "play")
        desc = data.get("desc", "").strip() or f"douyin_{video_id}"

        # 替换文件名中的非法字符
        desc = re.sub(r'[\\/:*?"<>|]', '_', desc)

        return {
            "url": video_url,
            "title": desc,
            "video_id": video_id
        }

    def download_video(self, video_info: dict, output_dir: Optional[Path] = None, show_progress: bool = True) -> Path:
        """下载视频"""
        if output_dir is None:
            output_dir = self.temp_dir
        else:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{video_info['video_id']}.mp4"
        filepath = output_dir / filename

        if show_progress:
            print(f"正在下载视频: {video_info['title']}")

        response = requests.get(video_info['url'], headers=HEADERS, stream=True)
        response.raise_for_status()

        # 获取文件大小
        total_size = int(response.headers.get('content-length', 0))

        # 下载文件
        downloaded = 0
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if show_progress and total_size > 0:
                        progress = downloaded / total_size * 100
                        print(f"\r下载进度: {progress:.1f}%", end="", flush=True)

        if show_progress:
            print(f"\n视频下载完成: {filepath}")
        return filepath

    def extract_audio(self, video_path: Path, show_progress: bool = True) -> Path:
        """从视频文件中提取音频"""
        audio_path = video_path.with_suffix('.mp3')

        if show_progress:
            print("正在提取音频...")
        try:
            (
                ffmpeg
                .input(str(video_path))
                .output(str(audio_path), acodec='libmp3lame', q=0)
                .run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
            )
            if show_progress:
                print(f"音频提取完成: {audio_path}")
            return audio_path
        except Exception as e:
            raise Exception(f"提取音频时出错: {str(e)}")

    def get_audio_info(self, audio_path: Path) -> dict:
        """获取音频文件信息（时长和大小）"""
        try:
            probe = ffmpeg.probe(str(audio_path))
            duration = float(probe['format'].get('duration', 0))
            size = audio_path.stat().st_size
            return {'duration': duration, 'size': size}
        except Exception:
            return {'duration': 0, 'size': audio_path.stat().st_size}

    def split_audio(self, audio_path: Path, segment_duration: int = 600, show_progress: bool = True) -> list:
        """
        将音频分割成多个片段

        参数:
            audio_path: 音频文件路径
            segment_duration: 每段时长（秒），默认 10 分钟
            show_progress: 是否显示进度

        返回:
            分割后的音频文件路径列表
        """
        audio_info = self.get_audio_info(audio_path)
        duration = audio_info['duration']

        if duration <= segment_duration:
            return [audio_path]

        segments = []
        segment_index = 0
        current_time = 0

        if show_progress:
            total_segments = int(duration / segment_duration) + 1
            print(f"音频时长 {duration:.0f} 秒，将分割为 {total_segments} 段...")

        while current_time < duration:
            segment_path = self.temp_dir / f"segment_{segment_index}.mp3"

            try:
                (
                    ffmpeg
                    .input(str(audio_path), ss=current_time, t=segment_duration)
                    .output(str(segment_path), acodec='libmp3lame', q=0)
                    .run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
                )
                segments.append(segment_path)

                if show_progress:
                    print(f"  分割片段 {segment_index + 1}: {current_time:.0f}s - {min(current_time + segment_duration, duration):.0f}s")

            except Exception as e:
                raise Exception(f"分割音频片段 {segment_index} 时出错: {str(e)}")

            current_time += segment_duration
            segment_index += 1

        return segments

    def transcribe_single_audio(self, audio_path: Path) -> str:
        """转录单个音频文件"""
        files = {
            'file': (audio_path.name, open(audio_path, 'rb'), 'audio/mpeg'),
            'model': (None, self.model)
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }

        try:
            response = requests.post(self.api_base_url, files=files, headers=headers)
            response.raise_for_status()

            result = response.json()
            if 'text' in result:
                return result['text']
            else:
                return response.text

        except Exception as e:
            raise Exception(f"提取文字时出错: {str(e)}")
        finally:
            files['file'][1].close()

    def extract_text_from_audio(self, audio_path: Path, show_progress: bool = True) -> str:
        """从音频文件中提取文字（支持大文件自动分段）"""
        if not self.api_key:
            raise ValueError("未设置 API 密钥，请设置环境变量 API_KEY")

        # 检查文件大小和时长
        audio_info = self.get_audio_info(audio_path)
        max_duration = 3600  # 1 小时
        max_size = 50 * 1024 * 1024  # 50MB

        # 判断是否需要分段
        need_split = audio_info['duration'] > max_duration or audio_info['size'] > max_size

        if not need_split:
            # 文件在限制范围内，直接处理
            if show_progress:
                print("正在识别语音...")
            return self.transcribe_single_audio(audio_path)

        # 需要分段处理
        if show_progress:
            print(f"音频文件较大（时长: {audio_info['duration']:.0f}秒, 大小: {audio_info['size'] / 1024 / 1024:.1f}MB）")
            print("将自动分段处理...")

        # 分割音频
        segments = self.split_audio(audio_path, segment_duration=540, show_progress=show_progress)  # 9分钟一段，留余量

        # 逐段转录
        all_texts = []
        for i, segment_path in enumerate(segments):
            if show_progress:
                print(f"正在识别第 {i + 1}/{len(segments)} 段...")

            text = self.transcribe_single_audio(segment_path)
            all_texts.append(text)

            # 清理分段文件
            if segment_path != audio_path:
                self.cleanup_files(segment_path)

        # 合并文本
        merged_text = ''.join(all_texts)

        if show_progress:
            print(f"语音识别完成，共处理 {len(segments)} 个片段")

        return merged_text

    def cleanup_files(self, *file_paths: Path):
        """清理指定的文件"""
        for file_path in file_paths:
            if file_path.exists():
                file_path.unlink()


def get_video_info(share_link: str) -> dict:
    """获取视频信息和下载链接"""
    return resolve_video_info(share_link)


def download_video(share_link: str, output_dir: str = ".") -> Path:
    """下载视频到指定目录"""
    processor = DouyinProcessor()
    video_info = get_video_info(share_link)
    if not video_info.get("url"):
        raise RuntimeError("HTTP 解析未得到视频下载地址；请使用 extract 获取完整音频和文案")
    return processor.download_video(video_info, Path(output_dir))


def extract_text(share_link: str, api_key: Optional[str] = None, output_dir: Optional[str] = None,
                 save_video: bool = False, show_progress: bool = True) -> dict:
    """
    从视频中提取文案并保存到文件

    返回:
        dict: 包含 video_info, text, output_path 的字典
    """
    if save_video and show_progress:
        print("当前浏览器降级链路保存完整音频，不保证能保存视频文件。")
    if show_progress:
        print("正在执行：HTTP/Playwright → 下载 → 音频 → 本地 ASR → DeepSeek...")
    return run_verified_workflow(
        share_link,
        output_dir or "./output",
        deepseek_api_key=api_key,
    )


def main():
    parser = argparse.ArgumentParser(
        description="抖音链接转写与口播整理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 获取视频信息；HTTP 解析失败会降级到 Playwright
  python douyin_downloader.py --link "抖音分享链接" --action info

  # 下载视频
  python douyin_downloader.py --link "抖音分享链接" --action download --output ./videos

  # 本地转写并整理口播（需要 DOUYIN_DEEPSEEK_API_KEY）
  python douyin_downloader.py --link "抖音分享链接" --action extract --output ./output

        """
    )

    parser.add_argument("--link", "-l", required=True, help="抖音分享链接或包含链接的文本")
    parser.add_argument("--action", "-a", choices=["info", "download", "extract"],
                        default="info", help="操作类型: info(获取信息), download(下载视频), extract(转写并整理口播)")
    parser.add_argument("--output", "-o", default="./output", help="输出目录 (默认 ./output)")
    parser.add_argument("--api-key", "-k", help="DeepSeek API 密钥 (推荐通过 DOUYIN_DEEPSEEK_API_KEY 环境变量设置)")
    parser.add_argument("--save-video", "-v", action="store_true",
                        help="兼容旧参数；浏览器降级时只保证保存完整音频")
    parser.add_argument("--quiet", "-q", action="store_true", help="安静模式，减少输出")

    args = parser.parse_args()

    try:
        if args.action == "info":
            info = get_video_info(args.link)
            print("\n" + "=" * 50)
            print("视频信息:")
            print("=" * 50)
            print(f"视频ID: {info['video_id']}")
            print(f"标题: {info['title']}")
            print(f"下载链接: {info['url']}")
            print("=" * 50)

        elif args.action == "download":
            video_path = download_video(args.link, args.output)
            print(f"\n视频已保存到: {video_path}")

        elif args.action == "extract":
            result = extract_text(
                args.link,
                args.api_key,
                output_dir=args.output,
                save_video=args.save_video,
                show_progress=not args.quiet
            )

            if not args.quiet:
                print("\n" + "=" * 50)
                print("提取完成!")
                print("=" * 50)
                print(f"视频ID: {result['video_info']['video_id']}")
                print(f"标题: {result['video_info']['title']}")
                if result['output_path']:
                    print(f"保存位置: {result['output_path']}")
                print("=" * 50)
                print("\n文案内容:\n")
                print(result['text'][:500] + "..." if len(result['text']) > 500 else result['text'])
                print("\n" + "=" * 50)

    except Exception as e:
        print(f"\n错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
