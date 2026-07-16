import unittest
from pathlib import Path


class RunaiScriptTests(unittest.TestCase):
    def test_status_and_stop_reconcile_stale_pid_files_with_listening_ports(self):
        text = Path("runai.sh").read_text(encoding="utf-8")

        self.assertIn("resolve_service_pid()", text)
        self.assertIn('stop_one "agent" "$AGENT_PID_FILE" "$PC_AGENT_PORT"', text)
        self.assertIn('stop_one "bridge" "$BRIDGE_PID_FILE" "$BRIDGE_PORT"', text)
        self.assertIn('resolve_service_pid "$pid_file" "$BRIDGE_PORT"', text)
        self.assertIn('resolve_service_pid "$pid_file" "$PC_AGENT_PORT"', text)


if __name__ == "__main__":
    unittest.main()
