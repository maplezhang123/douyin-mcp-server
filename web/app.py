#!/usr/bin/env python3
"""Local WebUI for Douyin transcript extraction."""
from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from douyin_mcp_server.workflow import HEADERS, resolve_video_info, run_verified_workflow

app = FastAPI(title="抖音文案提取器", version="1.0.0")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


class VideoRequest(BaseModel):
    url: str
    asr_mode: str = "cloud"
    siliconflow_api_key: str = ""
    deepseek_api_key: str = ""
    local_model: str = "small"


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "asr_mode": os.getenv("DOUYIN_ASR_MODE", "cloud"),
        "siliconflow_configured": bool(os.getenv("SILICONFLOW_API_KEY")),
        "deepseek_configured": bool(os.getenv("DEEPSEEK_API_KEY") or os.getenv("DOUYIN_DEEPSEEK_API_KEY")),
    }


@app.post("/api/video/info")
async def get_info(req: VideoRequest):
    try:
        info = await asyncio.to_thread(resolve_video_info, req.url)
        return {"success": True, "video_id": info["video_id"], "title": info["title"],
                "download_url": info["url"], "parser": info.get("source", "http")}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.post("/api/video/extract")
async def extract_transcript(req: VideoRequest):
    mode = req.asr_mode.lower()
    silicon_key = req.siliconflow_api_key or os.getenv("SILICONFLOW_API_KEY", "")
    if mode == "cloud" and not silicon_key:
        return {"success": False, "error": "SiliconFlow API Key 未填写（云端模式必需）"}
    try:
        result = await asyncio.to_thread(
            run_verified_workflow,
            req.url,
            os.getenv("DOUYIN_OUTPUT_DIR", "./output"),
            "rewrite",
            req.local_model,
            silicon_key,
            req.deepseek_api_key or os.getenv("DEEPSEEK_API_KEY", "") or os.getenv("DOUYIN_DEEPSEEK_API_KEY", ""),
            mode,
        )
        return {"success": True, "video_id": result["video_info"]["video_id"],
                "title": result["video_info"]["title"], "raw_text": result["raw_text"],
                "organized_text": result["organized_text"], "text": result["text"],
                "parser": result["video_info"].get("source", "http"), "asr_mode": result["asr_mode"],
                "asr_model": result["asr_model"], "elapsed_seconds": result["elapsed_seconds"],
                "organizer_error": result["organizer_error"]}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _content_disposition(filename: str) -> str:
    ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename) or "video.mp4"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


@app.get("/api/video/download")
async def download_video(video_id: str, filename: str = "video.mp4"):
    if not re.fullmatch(r"\d+", video_id):
        raise HTTPException(status_code=400, detail="无效的视频 ID")
    try:
        info = await asyncio.to_thread(resolve_video_info, f"https://www.iesdouyin.com/share/video/{video_id}")
        if not info.get("url"):
            raise RuntimeError("浏览器降级只能提取音频，暂时没有视频下载地址")
        response = await asyncio.to_thread(requests.get, info["url"], headers=HEADERS, stream=True, timeout=60)
        response.raise_for_status()
        return StreamingResponse(response.iter_content(8192), media_type="video/mp4",
            headers={"Content-Disposition": _content_disposition(filename)})
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def main():
    port = int(os.getenv("PORT", "8080"))
    print(f"[START] http://localhost:{port}")
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=port)


if __name__ == "__main__":
    main()
