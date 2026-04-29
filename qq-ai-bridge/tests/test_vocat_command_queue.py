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


if __name__ == "__main__":
    unittest.main()
