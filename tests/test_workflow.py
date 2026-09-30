import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from douyin_mcp_server import workflow


class VideoIdTests(unittest.TestCase):
    def test_supported_video_id_formats(self):
        video_id = "7663807936070832121"
        cases = [
            f"https://www.douyin.com/video/{video_id}",
            f"https://www.douyin.com/jingxuan?modal_id={video_id}",
            f"https://www.douyin.com/?aweme_id={video_id}",
            f"https://www.douyin.com/?item_ids={video_id}",
        ]
        for value in cases:
            with self.subTest(value=value):
                self.assertEqual(workflow.extract_video_id(value), video_id)

    def test_invalid_text_has_no_id(self):
        self.assertEqual(workflow.extract_video_id("https://v.douyin.com/abc/"), "")


class AsrTests(unittest.TestCase):
    @patch("douyin_mcp_server.workflow.requests.post")
    def test_siliconflow_request_and_result(self, post):
        response = Mock(status_code=200)
        response.json.return_value = {"text": "识别结果"}
        post.return_value = response
        with tempfile.TemporaryDirectory() as name:
            audio = Path(name) / "audio.mp3"
            audio.write_bytes(b"mock")
            self.assertEqual(workflow.transcribe_single_siliconflow(audio, "secret"), "识别结果")
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(kwargs["files"]["model"][1], workflow.SILICONFLOW_ASR_MODEL)

    @patch("douyin_mcp_server.workflow.requests.post")
    def test_invalid_siliconflow_key_is_friendly(self, post):
        post.return_value = Mock(status_code=401, text="unauthorized")
        with tempfile.TemporaryDirectory() as name:
            audio = Path(name) / "audio.mp3"
            audio.write_bytes(b"mock")
            with self.assertRaisesRegex(RuntimeError, "API Key 无效"):
                workflow.transcribe_single_siliconflow(audio, "bad")

    def test_cloud_mode_requires_its_own_key(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "not-an-asr-key"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "SiliconFlow API Key"):
                workflow.transcribe_cloud_siliconflow(Path("audio"), Path("text"))


class WorkflowTests(unittest.TestCase):
    @patch("douyin_mcp_server.workflow.transcribe_cloud_siliconflow")
    @patch("douyin_mcp_server.workflow.probe_audio")
    @patch("douyin_mcp_server.workflow.run_browser_capture")
    @patch("douyin_mcp_server.workflow.parse_share_url_http")
    def test_http_failure_uses_browser_and_cloud_asr(self, parse_http, browser, probe, transcribe):
        parse_http.side_effect = ValueError("videoInfoRes missing")
        def capture(_url, audio_path):
            audio_path.write_bytes(b"audio")
            return {"ok": True, "video_id": "7663807936070832121", "title": "测试视频",
                    "final_url": "https://www.douyin.com/video/7663807936070832121"}
        browser.side_effect = capture
        probe.return_value = {"duration": 10, "size": 5, "format_name": "mov"}
        def asr(_audio, transcript, _key):
            transcript.write_text("内容", encoding="utf-8")
            return {"engine": "siliconflow", "model": workflow.SILICONFLOW_ASR_MODEL,
                    "segment_count": 1, "character_count": 2, "text": "内容"}
        transcribe.side_effect = asr
        with tempfile.TemporaryDirectory() as name:
            result = workflow.run_verified_workflow(
                "https://v.douyin.com/example/", name, siliconflow_api_key="key"
            )
            report = json.loads(Path(result["run_report_path"]).read_text(encoding="utf-8"))
        self.assertEqual(result["raw_text"], "内容")
        self.assertEqual(result["text"], "内容")
        self.assertEqual(result["video_info"]["source"], "browser")
        self.assertEqual([step["status"] for step in report["stages"]],
                         ["browser-fallback", "browser-audio-ok", "direct-audio",
                          "siliconflow-ok", "skipped-no-key"])

    @patch("douyin_mcp_server.workflow.organize_with_deepseek")
    @patch("douyin_mcp_server.workflow.transcribe_cloud_siliconflow")
    @patch("douyin_mcp_server.workflow.probe_audio")
    @patch("douyin_mcp_server.workflow.extract_audio")
    @patch("douyin_mcp_server.workflow.download_video")
    @patch("douyin_mcp_server.workflow.parse_share_url_http")
    def test_deepseek_failure_keeps_raw_text(self, parse_http, download, extract, probe, transcribe, organize):
        parse_http.return_value = {"url": "media", "video_id": "7663807936070832121",
                                  "title": "标题", "source": "http", "resolved_url": "url"}
        download.side_effect = lambda _info, path: path.write_bytes(b"video")
        extract.side_effect = lambda _video, path: path.write_bytes(b"audio")
        probe.return_value = {"duration": 10, "size": 5, "format_name": "mov"}
        transcribe.side_effect = lambda _audio, transcript, _key: {
            "engine": "siliconflow", "model": workflow.SILICONFLOW_ASR_MODEL,
            "segment_count": 1, "character_count": 4, "text": "原始内容"}
        organize.side_effect = RuntimeError("network")
        with tempfile.TemporaryDirectory() as name:
            result = workflow.run_verified_workflow(
                "https://www.douyin.com/video/7663807936070832121", name,
                siliconflow_api_key="asr", deepseek_api_key="optional"
            )
        self.assertEqual(result["text"], "原始内容")
        self.assertIn("DeepSeek", result["organizer_error"])

    def test_local_model_path_uses_standard_snapshot(self):
        with tempfile.TemporaryDirectory() as name:
            hub = Path(name)
            repo = hub / "models--Systran--faster-whisper-small"
            (repo / "refs").mkdir(parents=True)
            (repo / "refs" / "main").write_text("revision", encoding="utf-8")
            snapshot = repo / "snapshots" / "revision"
            snapshot.mkdir(parents=True)
            self.assertEqual(workflow.local_model_path("small", hub), snapshot)


if __name__ == "__main__":
    unittest.main()
