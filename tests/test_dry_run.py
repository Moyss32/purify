import unittest
from unittest.mock import patch

from core.operations import Operation, OperationResult, ReversibilityLevel, RiskLevel
from platforms.linux.debian import CleanAptCacheOperation


class NoExecuteOperation(Operation):
    def __init__(self):
        super().__init__("dry", "Dry", "read only", "Tests", "test", RiskLevel.LOW, ReversibilityLevel.NONE, False)
        self.execute_calls = 0

    def check_state(self):
        return {"known": True, "active": False}

    def execute(self):
        self.execute_calls += 1
        return OperationResult(True, "should never happen")


class DryRunTests(unittest.TestCase):
    def test_base_dry_run_does_not_execute(self):
        op = NoExecuteOperation()
        preview = op.get_dry_run_description()
        self.assertTrue(preview["available"])
        self.assertEqual(op.execute_calls, 0)

    @patch("platforms.linux.debian.run_shell")
    def test_linux_dry_run_only_runs_read_queries(self, run):
        run.side_effect = [(True, "", ""), (True, "1024 /var/cache/apt/archives", "")]
        op = CleanAptCacheOperation()
        preview = op.get_dry_run_description()
        self.assertTrue(preview["available"])
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertNotEqual(call.args[0][0], "apt-get")


if __name__ == "__main__":
    unittest.main()
