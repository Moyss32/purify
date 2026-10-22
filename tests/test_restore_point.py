import unittest
from unittest.mock import patch

from platforms.windows.utils import create_restore_point


class RestorePointTests(unittest.TestCase):
    @patch("platforms.windows.utils.run_powershell")
    def test_primary_method_success_stops_without_using_fallback(self, run_ps):
        run_ps.return_value = (True, "PURIFY_RESTORE_OK:17", "")

        ok, message = create_restore_point("Purify test")

        self.assertTrue(ok)
        self.assertIn("Checkpoint-Computer", message)
        run_ps.assert_called_once()
        self.assertIn("Get-ComputerRestorePoint", run_ps.call_args.args[0])

    @patch("platforms.windows.utils.run_powershell")
    def test_falls_back_to_direct_cim_call_when_primary_fails(self, run_ps):
        run_ps.side_effect = [
            (False, "", "Checkpoint-Computer unavailable"),
            (True, "PURIFY_RESTORE_OK:18", ""),
        ]

        ok, message = create_restore_point("Purify test")

        self.assertTrue(ok)
        self.assertIn("SystemRestore via CIM", message)
        self.assertEqual(run_ps.call_count, 2)
        self.assertIn("Checkpoint-Computer", run_ps.call_args_list[0].args[0])
        self.assertIn("Invoke-CimMethod", run_ps.call_args_list[1].args[0])
        self.assertIn("CreateRestorePoint", run_ps.call_args_list[1].args[0])

    @patch("platforms.windows.utils.run_powershell")
    def test_zero_exit_without_confirmed_new_point_tries_fallback(self, run_ps):
        run_ps.side_effect = [
            (True, "", ""),
            (True, "PURIFY_RESTORE_OK:19", ""),
        ]

        ok, message = create_restore_point()

        self.assertTrue(ok)
        self.assertIn("SystemRestore via CIM", message)
        self.assertEqual(run_ps.call_count, 2)

    @patch("platforms.windows.utils.run_powershell")
    def test_reports_failure_when_both_methods_fail(self, run_ps):
        run_ps.side_effect = [
            (False, "", "cmdlet failed"),
            (False, "", "CIM failed"),
        ]

        ok, message = create_restore_point()

        self.assertFalse(ok)
        self.assertIn("Checkpoint-Computer: cmdlet failed", message)
        self.assertIn("SystemRestore via CIM: CIM failed", message)
        self.assertEqual(run_ps.call_count, 2)


if __name__ == "__main__":
    unittest.main()
