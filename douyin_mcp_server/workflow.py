"""Verified Douyin rewrite workflow used by the CLI, WebUI, and MCP server."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import ffmpeg
import requests


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) "
        "AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"
    )
}
DEFAULT_MODEL_HUB = Path(r"D:\AI_Tools\models\huggingface\hub")
DEFAULT_PLAYWRIGHT_NODE = Path(r"D:\AI_Tools\bin\playwright-node.cmd")
CAPTURE_SCRIPT = Path(__file__).with_name("capture_douyin.js")


def source_url(share_text: str) -> str:
    match = re.search(r"https?://\S+", share_text)
    if not match:
        raise ValueError("未找到有效的抖音分享链接")
    return match.group(0).strip().rstrip("。),，")


def extract_video_id(text: str) -> str:
    for pattern in (
        r"/video/(\d+)",
        r"modal_id=(\d+)",
        r"aweme_id=(\d+)",
        r"item_ids=(\d+)",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    match = re.search(r"\b(\d{16,22})\b", text)
    return match.group(1) if match else ""


def parse_share_url_http(share_text: str) -> dict:
    """Resolve a share URL with the upstream HTTP parser."""
    share_url = source_url(share_text)
    share_response = requests.get(
        share_url, headers=HEADERS, allow_redirects=True, timeout=20
    )
    share_response.raise_for_status()
    video_id = extract_video_id(share_response.url)
    if not video_id:
        raise ValueError("HTTP 解析没有得到视频 ID")

    page_url = f"https://www.iesdouyin.com/share/video/{video_id}"
    response = requests.get(page_url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    match = re.search(
        r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", response.text, re.DOTALL
    )
    if not match:
        raise ValueError("HTTP 页面中没有 _ROUTER_DATA")

    data = json.loads(match.group(1).strip())["loaderData"]
    page = data.get("video_(id)/page") or data.get("note_(id)/page")
    if not page or not page.get("videoInfoRes"):
        raise ValueError("HTTP 页面中没有 videoInfoRes")
    item = page["videoInfoRes"]["item_list"][0]
    video_url = item["video"]["play_addr"]["url_list"][0].replace(
        "playwm", "play"
    )
    title = re.sub(r'[\\/:*?"<>|]', "_", item.get("desc", "").strip())
    return {
        "url": video_url,
        "title": title or f"douyin_{video_id}",
        "video_id": video_id,
        "resolved_url": share_response.url,
        "source": "http",
    }


def run_browser_capture(url: str, audio_path: Optional[Path]) -> dict:
    wrapper = Path(os.getenv("DOUYIN_PLAYWRIGHT_NODE", str(DEFAULT_PLAYWRIGHT_NODE)))
    if not wrapper.exists():
        raise RuntimeError(f"共享 Playwright 入口不存在: {wrapper}")
    if not CAPTURE_SCRIPT.exists():
        raise RuntimeError(f"浏览器采集脚本不存在: {CAPTURE_SCRIPT}")

    env = os.environ.copy()
    env["DOUYIN_CAPTURE_URL"] = url
    env["DOUYIN_AUDIO_PATH"] = str(audio_path) if audio_path else ""
    env["DOUYIN_DOWNLOAD_AUDIO"] = "1" if audio_path else "0"
    process = subprocess.run(
        [str(wrapper), str(CAPTURE_SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=180,
    )
    match = re.search(r"DOUYIN_CAPTURE_JSON=(\{.*\})", process.stdout or "")
    if not match:
        detail = (process.stderr or process.stdout or "无输出").strip()
        raise RuntimeError(f"Playwright 没有返回采集结果: {detail}")
    result = json.loads(match.group(1))
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "Playwright 采集失败")
    return result


def resolve_video_info(share_text: str) -> dict:
    """Resolve metadata with HTTP first, then the verified browser fallback."""
    try:
        return parse_share_url_http(share_text)
    except Exception as exc:
        url = source_url(share_text)
        result = run_browser_capture(url, None)
        return {
            "url": "",
            "title": result.get("title", ""),
            "video_id": result.get("video_id") or extract_video_id(url),
            "resolved_url": result.get("final_url", url),
            "source": "browser",
            "http_error": str(exc),
        }


def download_video(video_info: dict, destination: Path) -> None:
    response = requests.get(
        video_info["url"], headers=HEADERS, stream=True, timeout=60
    )
    response.raise_for_status()
    with destination.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                handle.write(chunk)


def extract_audio(video_path: Path, audio_path: Path) -> None:
    try:
        (
            ffmpeg.input(str(video_path))
            .output(str(audio_path), vn=None, acodec="aac", audio_bitrate="128k")
            .run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
        )
    except ffmpeg.Error as exc:
        detail = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else str(exc)
        raise RuntimeError(f"ffmpeg 抽取音频失败: {detail}") from exc


def probe_audio(audio_path: Path) -> dict:
    try:
        probe = ffmpeg.probe(str(audio_path))
    except ffmpeg.Error as exc:
        detail = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else str(exc)
        raise RuntimeError(f"ffprobe 校验音频失败: {detail}") from exc
    format_info = probe.get("format", {})
    duration = float(format_info.get("duration", 0))
    if duration <= 0 or audio_path.stat().st_size <= 0:
        raise RuntimeError("音频文件为空或时长无效")
    return {
        "duration": duration,
        "size": audio_path.stat().st_size,
        "format_name": format_info.get("format_name", ""),
    }


def local_model_path(model_name: str, model_hub: Optional[Path] = None) -> Path:
    hub = model_hub or Path(os.getenv("DOUYIN_MODEL_HUB", str(DEFAULT_MODEL_HUB)))
    repo = hub / f"models--Systran--faster-whisper-{model_name}"
    ref = repo / "refs" / "main"
    if not ref.exists():
        raise RuntimeError(f"本地 faster-whisper-{model_name} 权重不存在: {hub}")
    snapshot = repo / "snapshots" / ref.read_text(encoding="utf-8").strip()
    if not (snapshot / "model.bin").exists():
        raise RuntimeError(f"本地模型快照不完整: {snapshot}")
    return snapshot


def _timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def transcribe_local(audio_path: Path, transcript_path: Path, model_name: str) -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("缺少 faster-whisper，请重新执行 uv sync") from exc

    model_path = local_model_path(model_name)
    model = WhisperModel(str(model_path), device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        str(audio_path), language="zh", vad_filter=True, beam_size=5
    )
    rows = []
    plain = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            rows.append(f"[{_timestamp(segment.start)}] {text}")
            plain.append(text)
    if not rows:
        raise RuntimeError("本地 ASR 没有识别到语音")
    transcript_path.write_text(
        "# 原始逐字稿\n\n" + "\n\n".join(rows) + "\n", encoding="utf-8"
    )
    return {
        "engine": "faster-whisper",
        "model": model_name,
        "model_path": str(model_path),
        "device": "cpu",
        "compute_type": "int8",
        "language": getattr(info, "language", "zh"),
        "segment_count": len(rows),
        "character_count": len("".join(plain)),
        "text": "".join(plain),
    }


def organize_with_deepseek(
    transcript: str,
    title: str,
    purpose: str = "rewrite",
    api_key: Optional[str] = None,
) -> dict:
    key = api_key or os.getenv("DOUYIN_DEEPSEEK_API_KEY", "")
    if not key:
        raise RuntimeError("未设置 DOUYIN_DEEPSEEK_API_KEY，无法完成口播整理")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    response = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "thinking": {"type": "disabled"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是短视频口播文案编辑。忠实保留原意，只去掉口水词和重复，"
                        "修正明显同音字，补充标点、分段和口播结构。不要虚构原文没有的信息，"
                        "只输出整理后的口播文案。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"标题：{title}\n用途：{purpose}\n\n逐字稿：\n{transcript}",
                },
            ],
        },
        timeout=float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "90")),
    )
    response.raise_for_status()
    payload = response.json()
    try:
        text = payload["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("DeepSeek 返回中没有整理后的文案") from exc
    if not text:
        raise RuntimeError("DeepSeek 返回了空文案")
    return {"model": model, "text": text, "usage": payload.get("usage", {})}


def run_verified_workflow(
    share_text: str,
    output_base: str | Path,
    purpose: str = "rewrite",
    model_name: str = "medium",
    deepseek_api_key: Optional[str] = None,
) -> dict:
    """Run HTTP→browser fallback→audio validation→local ASR→DeepSeek."""
    url = source_url(share_text)
    stages = []
    http_error = ""
    browser_result = {}

    with tempfile.TemporaryDirectory(prefix="douyin-workflow-") as temp_name:
        temp_dir = Path(temp_name)
        temp_audio = temp_dir / "audio.m4a"
        try:
            video_info = parse_share_url_http(share_text)
            stages.append({"stage": "parse", "status": "http-ok"})
            video_path = temp_dir / f"{video_info['video_id']}.mp4"
            download_video(video_info, video_path)
            stages.append({"stage": "download", "status": "video-ok"})
            extract_audio(video_path, temp_audio)
            stages.append({"stage": "audio", "status": "ffmpeg-ok"})
        except Exception as exc:
            http_error = str(exc)
            stages.append(
                {"stage": "parse", "status": "browser-fallback", "http_error": http_error}
            )
            browser_result = run_browser_capture(url, temp_audio)
            video_info = {
                "url": "",
                "title": browser_result.get("title", ""),
                "video_id": browser_result.get("video_id") or extract_video_id(url),
                "resolved_url": browser_result.get("final_url", url),
                "source": "browser",
            }
            stages.append({"stage": "download", "status": "signed-audio-ok"})
            stages.append({"stage": "audio", "status": "direct-audio"})

        video_id = video_info.get("video_id") or datetime.now().strftime("%Y%m%d-%H%M%S")
        output_dir = Path(output_base) / video_id
        output_dir.mkdir(parents=True, exist_ok=True)
        audio_path = output_dir / "audio.m4a"
        shutil.copy2(temp_audio, audio_path)

    audio_probe = probe_audio(audio_path)
    transcript_path = output_dir / "transcript-raw.md"
    asr = transcribe_local(audio_path, transcript_path, model_name)
    stages.append({"stage": "asr", "status": "local-ok"})

    organized = organize_with_deepseek(
        asr["text"], video_info.get("title", ""), purpose, deepseek_api_key
    )
    copy_path = output_dir / "copy.md"
    copy_path.write_text("# 整理后的口播文案\n\n" + organized["text"] + "\n", encoding="utf-8")
    stages.append({"stage": "organize", "status": "deepseek-ok"})

    metadata = {
        "source_url": url,
        "resolved_url": video_info.get("resolved_url", url),
        "video_id": video_id,
        "title": video_info.get("title", ""),
        "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": video_info.get("source", ""),
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = {
        "workflow_version": 3,
        "status": "completed",
        "stages": stages,
        "http_error": http_error,
        "browser": {
            "media_candidates": browser_result.get("media_candidates", 0),
            "audio_bytes": browser_result.get("audio_bytes", 0),
        },
        "audio_probe": audio_probe,
        "asr": {key: value for key, value in asr.items() if key != "text"},
        "organizer": {"model": organized["model"], "usage": organized["usage"]},
        "artifacts": {
            "audio": str(audio_path),
            "transcript_raw": str(transcript_path),
            "copy": str(copy_path),
            "metadata": str(output_dir / "metadata.json"),
        },
    }
    report_path = output_dir / "run-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "video_info": video_info,
        "text": organized["text"],
        "raw_text": asr["text"],
        "output_path": str(output_dir),
        "run_report_path": str(report_path),
        "status": "completed",
    }
