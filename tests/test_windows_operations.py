import json
import unittest
from unittest.mock import patch

from core.operations import OperationState, ReversibilityLevel, RiskLevel
from platforms.windows.windows10 import DisableServiceOperation, RemoveAppxPackageOperation


class WindowsOperationTests(unittest.TestCase):
    @patch("platforms.windows.windows10.run_powershell")
    def test_bulk_appx_scan_uses_one_read_only_query_for_multiple_packages(self, run):
        run.return_value = (
            True,
            json.dumps([{"Name": "Example.One", "PackageFullName": "Example.One_1.0_x64"}]),
            "",
        )
        one = RemoveAppxPackageOperation("Example.One", "One", RiskLevel.LOW, "test")
        two = RemoveAppxPackageOperation("Example.Two", "Two", RiskLevel.LOW, "test")
        states = RemoveAppxPackageOperation.inspect_many([one, two])
        self.assertEqual(run.call_count, 1)
        self.assertTrue(states[one]["installed"])
        self.assertFalse(states[two]["installed"])
        self.assertIn("Get-AppxPackage", run.call_args.args[0])
        self.assertNotIn("Remove-AppxPackage", run.call_args.args[0])

    @patch("platforms.windows.windows10.run_powershell")
    def test_bulk_service_scan_uses_one_read_only_query_for_multiple_services(self, run):
        run.return_value = (
            True,
            json.dumps([{"Name": "ExampleSvc", "StartMode": "Auto", "State": "Running"}]),
            "",
        )
        one = DisableServiceOperation("ExampleSvc", "One", RiskLevel.LOW, "test")
        two = DisableServiceOperation("MissingSvc", "Two", RiskLevel.LOW, "test")
        states = DisableServiceOperation.inspect_many([one, two])
        self.assertEqual(run.call_count, 1)
        self.assertTrue(states[one]["found"])
        self.assertFalse(states[two]["found"])
        self.assertIn("Get-CimInstance", run.call_args.args[0])
        self.assertNotIn("Set-Service", run.call_args.args[0])

    @patch("platforms.windows.windows10.run_powershell")
    def test_appx_absent_is_not_applicable_and_partial_rollback(self, run):
        run.return_value = (True, "[]", "")
        op = RemoveAppxPackageOperation("Example.App", "Example", RiskLevel.LOW, "test")
        state = op.check_state()
        self.assertFalse(op.is_applicable_state(state))
        self.assertEqual(op.reversibility, ReversibilityLevel.PARTIAL)
        self.assertIsNot(op.reversibility, ReversibilityLevel.FULL)

    @patch("platforms.windows.windows10.run_powershell")
    def test_appx_installed_state_uses_exact_identity(self, run):
        run.return_value = (True, json.dumps([{"Name": "Example.App", "PackageFullName": "Example.App_1.0_x64"}]), "")
        op = RemoveAppxPackageOperation("Example.App", "Example", RiskLevel.LOW, "test")
        self.assertTrue(op.is_applicable_state(op.check_state()))

    @patch("platforms.windows.windows10.run_powershell")
    def test_missing_service_is_not_applicable(self, run):
        run.return_value = (True, '{"known":true,"found":false}', "")
        op = DisableServiceOperation("ExampleSvc", "Example", RiskLevel.LOW, "test")
        self.assertFalse(op.is_applicable_state(op.check_state()))

    @patch("platforms.windows.windows10.run_powershell")
    def test_service_captures_prior_mode_and_status(self, run):
        run.return_value = (True, '{"known":true,"found":true,"service":"ExampleSvc","start_mode":"Auto","status":"Running"}', "")
        op = DisableServiceOperation("ExampleSvc", "Example", RiskLevel.LOW, "test")
        self.assertEqual(op.capture_pre_state(), {"service": "ExampleSvc", "start_mode": "Auto", "status": "Running"})

    def test_invalid_service_name_rejected(self):
        with self.assertRaises(ValueError):
            DisableServiceOperation("foo'; Remove-Item C:\\", "bad", RiskLevel.LOW, "test")

    @patch("platforms.windows.windows10.run_powershell")
    def test_appx_removal_uses_all_users_and_reports_executor_result(self, run):
        run.return_value = (True, "", "")
        op = RemoveAppxPackageOperation("Example.App", "Example", RiskLevel.LOW, "test")
        result = op.execute()
        self.assertEqual(result.state, OperationState.SUCCESS)
        script = run.call_args.args[0]
        self.assertIn("Remove-AppxPackage", script)
        self.assertIn("-AllUsers", script)

    @patch("platforms.windows.windows10.run_powershell")
    def test_service_disable_uses_validated_service_identifier(self, run):
        run.return_value = (True, "", "")
        op = DisableServiceOperation("ExampleSvc", "Example", RiskLevel.LOW, "test")
        result = op.execute()
        self.assertEqual(result.state, OperationState.SUCCESS)
        script = run.call_args.args[0]
        self.assertIn("Set-Service", script)
        self.assertIn("Stop-Service", script)
        self.assertIn("ExampleSvc", script)

    @patch("platforms.windows.windows10.run_powershell")
    def test_service_rollback_restores_start_mode_and_running_status(self, run):
        run.return_value = (True, "", "")
        op = DisableServiceOperation("ExampleSvc", "Example", RiskLevel.LOW, "test")
        result = op.rollback({"service": "ExampleSvc", "start_mode": "Auto", "status": "Running"})
        self.assertEqual(result.state, OperationState.SUCCESS)
        script = run.call_args.args[0]
        self.assertIn("Set-Service", script)
        self.assertIn("Automatic", script)
        self.assertIn("Start-Service", script)


if __name__ == "__main__":
    unittest.main()
