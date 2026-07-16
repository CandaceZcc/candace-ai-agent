import unittest
from unittest.mock import MagicMock, patch

import requests

from apps.qq_ai_bridge.services.draw_service import (
    build_draw_payload,
    build_images_payload,
    generate_image,
    poll_draw,
    submit_draw,
    submit_images_draw,
)


class DrawServiceTests(unittest.TestCase):
    def test_build_draw_payload_uses_gemini_async_shape(self):
        payload = build_draw_payload(
            "一只戴太空头盔的橘猫",
            aspect_ratio="16:9",
            image_size="2K",
        )

        self.assertTrue(payload["async"])
        self.assertEqual(payload["contents"][0]["role"], "user")
        self.assertEqual(
            payload["contents"][0]["parts"],
            [{"text": "一只戴太空头盔的橘猫"}],
        )
        self.assertEqual(
            payload["generationConfig"]["imageConfig"],
            {"aspectRatio": "16:9", "imageSize": "2K"},
        )

    def test_build_draw_payload_can_include_reference_image(self):
        payload = build_draw_payload(
            "改成杂志封面",
            reference_image_data="ZmFrZS1pbWFnZQ==",
            reference_mime_type="image/jpeg",
        )

        parts = payload["contents"][0]["parts"]
        self.assertEqual(parts[1]["inline_data"]["mime_type"], "image/jpeg")
        self.assertEqual(parts[1]["inline_data"]["data"], "ZmFrZS1pbWFnZQ==")

    def test_build_images_payload_uses_openai_async_shape(self):
        payload = build_images_payload(
            "原创黄色卡通机器人",
            model="gpt-image-2",
            aspect_ratio="1:1",
            image_size="1K",
        )

        self.assertEqual(
            payload,
            {
                "model": "gpt-image-2",
                "prompt": "原创黄色卡通机器人",
                "n": 1,
                "size": "1:1",
                "imageSize": "1K",
                "async": True,
            },
        )

    def test_build_images_payload_can_include_reference_data_url(self):
        payload = build_images_payload(
            "改成杂志封面",
            model="gpt-image-2",
            reference_image_data="ZmFrZS1pbWFnZQ==",
            reference_mime_type="image/jpeg",
        )

        self.assertEqual(
            payload["image"],
            ["data:image/jpeg;base64,ZmFrZS1pbWFnZQ=="],
        )

    @patch("apps.qq_ai_bridge.services.draw_service.requests.post")
    def test_submit_draw_returns_task_id(self, mock_post):
        response = MagicMock()
        response.ok = True
        response.status_code = 200
        response.text = '{"task_id":"task-123"}'
        response.json.return_value = {"task_id": "task-123", "status": "processing"}
        mock_post.return_value = response

        result = submit_draw(
            "未来城市",
            api_key="sk-test",
            base_url="https://www.right.codes",
            model="nano-banana-2",
        )

        self.assertEqual(result.status, "submitted")
        self.assertEqual(result.task_id, "task-123")
        self.assertEqual(
            mock_post.call_args.args[0],
            "https://www.right.codes/draw/v1beta/models/nano-banana-2:generateContent",
        )
        self.assertEqual(
            mock_post.call_args.kwargs["headers"]["Authorization"],
            "Bearer sk-test",
        )

    @patch("apps.qq_ai_bridge.services.draw_service.requests.post")
    def test_submit_images_draw_returns_task_id(self, mock_post):
        response = MagicMock()
        response.ok = True
        response.status_code = 200
        response.json.return_value = {"task_id": "task-image2", "status": "processing"}
        mock_post.return_value = response

        result = submit_images_draw(
            "原创黄色卡通机器人",
            api_key="sk-test",
            base_url="https://www.right.codes",
            model="gpt-image-2",
        )

        self.assertEqual(result.status, "submitted")
        self.assertEqual(result.task_id, "task-image2")
        self.assertEqual(
            mock_post.call_args.args[0],
            "https://www.right.codes/draw/v1/images/generations",
        )
        self.assertEqual(
            mock_post.call_args.kwargs["json"]["model"],
            "gpt-image-2",
        )

    @patch("apps.qq_ai_bridge.services.draw_service.requests.get")
    def test_poll_draw_extracts_completed_gemini_image_url(self, mock_get):
        response = MagicMock()
        response.ok = True
        response.status_code = 200
        response.text = '{"candidates":[]}'
        response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "https://cdn.example.com/result.png"},
                        ]
                    }
                }
            ]
        }
        mock_get.return_value = response

        result = poll_draw(
            "task-123",
            api_key="sk-test",
            base_url="https://www.right.codes",
            timeout_seconds=10,
            poll_interval_seconds=0,
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.image_url, "https://cdn.example.com/result.png")

    @patch("apps.qq_ai_bridge.services.draw_service.requests.get")
    def test_poll_draw_returns_failed_status_without_retrying(self, mock_get):
        response = MagicMock()
        response.ok = True
        response.status_code = 200
        response.text = '{"status":"failed"}'
        response.json.return_value = {
            "task_id": "task-123",
            "status": "failed",
            "error": {"message": "上游生成失败"},
        }
        mock_get.return_value = response

        result = poll_draw(
            "task-123",
            api_key="sk-test",
            base_url="https://www.right.codes",
            timeout_seconds=10,
            poll_interval_seconds=0,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error, "上游生成失败")
        self.assertEqual(mock_get.call_count, 1)

    @patch("apps.qq_ai_bridge.services.draw_service.requests.get")
    def test_poll_draw_retries_transient_http_failure_then_completes(self, mock_get):
        retry = MagicMock()
        retry.ok = False
        retry.status_code = 502
        completed = MagicMock()
        completed.ok = True
        completed.status_code = 200
        completed.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "https://cdn.example.com/result.png"},
                        ]
                    }
                }
            ]
        }
        mock_get.side_effect = [retry, completed]

        result = poll_draw(
            "task-123",
            api_key="sk-test",
            base_url="https://www.right.codes",
            timeout_seconds=240,
            poll_interval_seconds=0,
            max_transient_errors=2,
            sleep_fn=lambda _seconds: None,
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.image_url, "https://cdn.example.com/result.png")
        self.assertEqual(mock_get.call_count, 2)

    @patch("apps.qq_ai_bridge.services.draw_service.requests.get")
    def test_poll_draw_retries_network_timeout_then_completes(self, mock_get):
        completed = MagicMock()
        completed.ok = True
        completed.status_code = 200
        completed.json.return_value = {
            "data": [{"url": "https://cdn.example.com/result.png"}],
        }
        mock_get.side_effect = [requests.Timeout("temporary timeout"), completed]

        result = poll_draw(
            "task-123",
            api_key="sk-test",
            base_url="https://www.right.codes",
            timeout_seconds=240,
            poll_interval_seconds=0,
            max_transient_errors=2,
            sleep_fn=lambda _seconds: None,
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(mock_get.call_count, 2)

    @patch("apps.qq_ai_bridge.services.draw_service.requests.get")
    def test_poll_draw_keeps_polling_pending_and_running_statuses(self, mock_get):
        responses = []
        for status in ("pending", "running"):
            response = MagicMock()
            response.ok = True
            response.status_code = 200
            response.json.return_value = {"task_id": "task-123", "status": status}
            responses.append(response)
        completed = MagicMock()
        completed.ok = True
        completed.status_code = 200
        completed.json.return_value = {
            "data": [{"url": "https://cdn.example.com/result.png"}],
        }
        responses.append(completed)
        mock_get.side_effect = responses

        result = poll_draw(
            "task-123",
            api_key="sk-test",
            base_url="https://www.right.codes",
            timeout_seconds=240,
            poll_interval_seconds=0,
            max_transient_errors=2,
            sleep_fn=lambda _seconds: None,
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(mock_get.call_count, 3)

    @patch("apps.qq_ai_bridge.services.draw_service.requests.get")
    def test_poll_draw_stops_after_transient_retry_budget(self, mock_get):
        responses = []
        for _index in range(3):
            response = MagicMock()
            response.ok = False
            response.status_code = 502
            responses.append(response)
        mock_get.side_effect = responses

        result = poll_draw(
            "task-123",
            api_key="sk-test",
            base_url="https://www.right.codes",
            timeout_seconds=240,
            poll_interval_seconds=0,
            max_transient_errors=2,
            sleep_fn=lambda _seconds: None,
        )

        self.assertEqual(result.status, "request_failed")
        self.assertEqual(result.http_status, 502)
        self.assertEqual(mock_get.call_count, 3)

    @patch("apps.qq_ai_bridge.services.draw_service.log_warn")
    @patch("apps.qq_ai_bridge.services.draw_service.requests.get")
    def test_poll_draw_logs_transient_retry_without_credentials(self, mock_get, mock_log):
        retry = MagicMock()
        retry.ok = False
        retry.status_code = 502
        completed = MagicMock()
        completed.ok = True
        completed.status_code = 200
        completed.json.return_value = {
            "data": [{"url": "https://cdn.example.com/result.png"}],
        }
        mock_get.side_effect = [retry, completed]

        result = poll_draw(
            "task-1234567890",
            api_key="sk-secret-value",
            base_url="https://www.right.codes",
            timeout_seconds=240,
            poll_interval_seconds=0,
            max_transient_errors=2,
            provider="gemini",
            model="nano-banana-2",
            should_log=True,
            sleep_fn=lambda _seconds: None,
        )

        self.assertEqual(result.status, "completed")
        rendered_logs = "\n".join(
            call.args[1] % call.args[2:]
            for call in mock_log.call_args_list
        )
        self.assertIn("nano-banana-2", rendered_logs)
        self.assertIn("retry=1/2", rendered_logs)
        self.assertNotIn("sk-secret-value", rendered_logs)

    @patch("apps.qq_ai_bridge.services.draw_service.requests.get")
    def test_poll_draw_times_out_after_deadline(self, mock_get):
        response = MagicMock()
        response.ok = True
        response.status_code = 200
        response.text = '{"status":"in_progress"}'
        response.json.return_value = {"task_id": "task-123", "status": "in_progress"}
        mock_get.return_value = response
        now_values = iter((0.0, 0.0, 91.0))

        result = poll_draw(
            "task-123",
            api_key="sk-test",
            base_url="https://www.right.codes",
            timeout_seconds=90,
            poll_interval_seconds=0,
            now_fn=lambda: next(now_values),
            sleep_fn=lambda _seconds: None,
        )

        self.assertEqual(result.status, "timeout")
        self.assertEqual(mock_get.call_count, 1)

    @patch("apps.qq_ai_bridge.services.draw_service.submit_images_draw")
    @patch("apps.qq_ai_bridge.services.draw_service.poll_draw")
    @patch("apps.qq_ai_bridge.services.draw_service.submit_draw")
    def test_generate_image_primary_success_does_not_use_fallback(
        self,
        mock_submit_primary,
        mock_poll,
        mock_submit_fallback,
    ):
        mock_submit_primary.return_value.status = "submitted"
        mock_submit_primary.return_value.task_id = "task-primary"
        mock_poll.return_value.status = "completed"
        mock_poll.return_value.image_url = "https://cdn.example.com/result.png"

        with patch("apps.qq_ai_bridge.services.draw_service.DRAW_FALLBACK_ENABLED", True):
            result = generate_image("原创黄色卡通机器人")

        self.assertEqual(result.status, "completed")
        mock_submit_fallback.assert_not_called()

    @patch("apps.qq_ai_bridge.services.draw_service.submit_images_draw")
    @patch("apps.qq_ai_bridge.services.draw_service.poll_draw")
    @patch("apps.qq_ai_bridge.services.draw_service.submit_draw")
    def test_generate_image_primary_failure_uses_image2_fallback_once(
        self,
        mock_submit_primary,
        mock_poll,
        mock_submit_fallback,
    ):
        mock_submit_primary.return_value.status = "submitted"
        mock_submit_primary.return_value.task_id = "task-primary"
        primary_failure = MagicMock(status="failed", task_id="task-primary", error="upstream failed")
        fallback_success = MagicMock(
            status="completed",
            task_id="task-fallback",
            image_url="https://cdn.example.com/fallback.png",
        )
        mock_poll.side_effect = [primary_failure, fallback_success]
        mock_submit_fallback.return_value.status = "submitted"
        mock_submit_fallback.return_value.task_id = "task-fallback"

        with (
            patch("apps.qq_ai_bridge.services.draw_service.DRAW_FALLBACK_ENABLED", True),
            patch("apps.qq_ai_bridge.services.draw_service.DRAW_FALLBACK_MODEL", "gpt-image-2"),
        ):
            result = generate_image("原创黄色卡通机器人")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.image_url, "https://cdn.example.com/fallback.png")
        mock_submit_fallback.assert_called_once()
        self.assertEqual(mock_poll.call_count, 2)


if __name__ == "__main__":
    unittest.main()
