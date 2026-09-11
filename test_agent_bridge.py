import tempfile
import unittest
from pathlib import Path

import agent_bridge


class AgentBridgeTests(unittest.TestCase):
    def test_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            result = agent_bridge.handle({"op": "health"}, root, 1)
            self.assertEqual(result["workspace"], str(root))

    def test_exec(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            result = agent_bridge.handle(
                {"op": "exec", "argv": ["python3", "-c", "print('ok')"]},
                root,
                2,
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["returncode"], 0)
            self.assertEqual(result["stdout"], "ok\n")

    def test_cwd_escape_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            result = agent_bridge.handle(
                {"op": "exec", "argv": ["pwd"], "cwd": "../"},
                root,
                2,
            )
            self.assertFalse(result["ok"])
            self.assertIn("inside workspace", result["error"])


if __name__ == "__main__":
    unittest.main()
