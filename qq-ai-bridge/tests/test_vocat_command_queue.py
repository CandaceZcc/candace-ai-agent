import unittest

from apps.qq_ai_bridge.services import vocat_command_queue as queue


class VocatCommandQueueTest(unittest.TestCase):
    def tearDown(self):
        for command in queue.get_vocat_queue_status()["commands"]:
            queue.ack_vocat_command(command["id"])

    def test_enqueue_poll_ack_tts(self):
        result = queue.enqueue_vocat_tts("该出门上课了", source="test")

        self.assertTrue(result["ok"])
        command = queue.poll_vocat_command()
        self.assertEqual(command["type"], "tts")
        self.assertEqual(command["text"], "该出门上课了")
        self.assertIn(command["expression"], {"happy", "dizzy", "sleep", "angry", "blink"})

        ack = queue.ack_vocat_command(command["id"])
        self.assertTrue(ack["ok"])
        self.assertIsNone(queue.poll_vocat_command())

    def test_expression_selection(self):
        self.assertEqual(queue.select_vocat_expression("晚安，该睡觉了"), "sleep")
        self.assertEqual(queue.select_vocat_expression("稍等，我查一下"), "dizzy")
        self.assertEqual(queue.select_vocat_expression("这也太离谱了"), "angry")

    def test_runtime_status_records_webhook_poll_ack(self):
        queued = queue.enqueue_vocat_expression("blink", source="test")
        command = queue.poll_vocat_command()

        queue.record_vocat_poll(command=command, queue_size=queue.get_vocat_queue_status()["queue_size"])
        queue.record_vocat_webhook(
            query="测试",
            reply="收到",
            expression="happy",
            source="test",
            remote_addr="127.0.0.1",
            trace_id="trace1234",
            model_reply="模型回复",
        )
        ack = queue.ack_vocat_command(queued["command_id"])
        queue.record_vocat_ack(queued["command_id"], ack)

        status = queue.get_vocat_runtime_status()
        self.assertTrue(status["ok"])
        self.assertTrue(status["device_online"])
        self.assertEqual(status["last_query"], "测试")
        self.assertEqual(status["last_reply"], "收到")
        self.assertEqual(status["last_trace_id"], "trace1234")
        self.assertEqual(status["last_model_reply"], "模型回复")
        self.assertEqual(status["last_expression"], "happy")
        self.assertEqual(status["last_command_id"], queued["command_id"])
        self.assertGreaterEqual(status["poll_count"], 1)
        self.assertGreaterEqual(status["ack_count"], 1)


if __name__ == "__main__":
    unittest.main()
