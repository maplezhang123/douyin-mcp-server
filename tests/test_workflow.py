import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from douyin_mcp_server import workflow


class WorkflowTests(unittest.TestCase):
    def test_local_model_path_uses_completed_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_name:
            hub = Path(temp_name)
            repo = hub / "models--Systran--faster-whisper-medium"
            (repo / "refs").mkdir(parents=True)
            (repo / "refs" / "main").write_text("revision", encoding="utf-8")
            snapshot = repo / "snapshots" / "revision"
            snapshot.mkdir(parents=True)
            (snapshot / "model.bin").write_bytes(b"model")

            self.assertEqual(workflow.local_model_path("medium", hub), snapshot)

    @patch("douyin_mcp_server.workflow.requests.post")
    def test_deepseek_organizer_uses_current_model_and_purpose(self, post):
        response = Mock()
        response.json.return_value = {
            "choices": [{"message": {"content": "整理结果"}}],
            "usage": {"total_tokens": 12},
        }
        response.raise_for_status.return_value = None
        post.return_value = response

        result = workflow.organize_with_deepseek(
            "原始逐字稿", "标题", purpose="reference", api_key="test-key"
        )

        self.assertEqual(result["text"], "整理结果")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "deepseek-v4-flash")
        self.assertIn("用途：reference", payload["messages"][1]["content"])

    @patch("douyin_mcp_server.workflow.requests.post")
    def test_deepseek_organizer_uses_douyin_specific_environment_key(self, post):
        response = Mock()
        response.json.return_value = {
            "choices": [{"message": {"content": "整理结果"}}],
        }
        response.raise_for_status.return_value = None
        post.return_value = response

        with patch.dict(
            os.environ,
            {
                "DOUYIN_DEEPSEEK_API_KEY": "personal-key",
                "DEEPSEEK_API_KEY": "company-key",
            },
            clear=False,
        ):
            workflow.organize_with_deepseek("原始逐字稿", "标题")

        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"], "Bearer personal-key"
        )

    @patch("douyin_mcp_server.workflow.requests.post")
    def test_deepseek_organizer_never_falls_back_to_generic_environment_key(self, post):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "company-key"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "DOUYIN_DEEPSEEK_API_KEY"):
                workflow.organize_with_deepseek("原始逐字稿", "标题")

        post.assert_not_called()

    @patch("douyin_mcp_server.workflow.run_browser_capture")
    @patch("douyin_mcp_server.workflow.parse_share_url_http")
    def test_metadata_resolution_falls_back_to_browser(self, parse_http, browser):
        parse_http.side_effect = ValueError("videoInfoRes missing")
        browser.return_value = {
            "video_id": "7663807936070832121",
            "title": "测试视频",
            "final_url": "https://www.douyin.com/video/7663807936070832121",
        }

        result = workflow.resolve_video_info("https://v.douyin.com/example/")

        self.assertEqual(result["source"], "browser")
        self.assertEqual(result["video_id"], "7663807936070832121")
        self.assertEqual(result["url"], "")

    @patch("douyin_mcp_server.workflow.organize_with_deepseek")
    @patch("douyin_mcp_server.workflow.transcribe_local")
    @patch("douyin_mcp_server.workflow.probe_audio")
    @patch("douyin_mcp_server.workflow.run_browser_capture")
    @patch("douyin_mcp_server.workflow.parse_share_url_http")
    def test_http_failure_runs_verified_browser_fallback(
        self, parse_http, browser, probe, transcribe, organize
    ):
        parse_http.side_effect = ValueError("videoInfoRes missing")

        def capture(_url, audio_path):
            audio_path.write_bytes(b"audio")
            return {
                "ok": True,
                "video_id": "7663807936070832121",
                "title": "测试视频",
                "final_url": "https://www.douyin.com/video/7663807936070832121",
                "audio_bytes": 5,
                "media_candidates": 1,
            }

        browser.side_effect = capture
        probe.return_value = {"duration": 153.4, "size": 5, "format_name": "mov"}

        def asr(_audio, transcript_path, _model):
            transcript_path.write_text("# 原始逐字稿\n\n内容\n", encoding="utf-8")
            return {
                "engine": "faster-whisper",
                "model": "medium",
                "segment_count": 92,
                "character_count": 972,
                "text": "内容",
            }

        transcribe.side_effect = asr
        organize.return_value = {
            "model": "deepseek-v4-flash",
            "text": "整理内容",
            "usage": {},
        }

        with tempfile.TemporaryDirectory() as temp_name:
            result = workflow.run_verified_workflow(
                "https://v.douyin.com/example/", temp_name
            )
            report = json.loads(
                Path(result["run_report_path"]).read_text(encoding="utf-8")
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["text"], "整理内容")
        self.assertEqual(
            [item["status"] for item in report["stages"]],
            [
                "browser-fallback",
                "signed-audio-ok",
                "direct-audio",
                "local-ok",
                "deepseek-ok",
            ],
        )


if __name__ == "__main__":
    unittest.main()
