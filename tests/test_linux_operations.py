import unittest
from unittest.mock import patch

from core.operations import OperationState, RiskLevel
from platforms.linux.debian import CleanAptCacheOperation, DisableSystemdServiceOperation, RemoveSnapOperation


class LinuxOperationTests(unittest.TestCase):
    @patch("platforms.linux.debian.run_shell")
    def test_apt_cache_state_counts_deb_files(self, run):
        run.side_effect = [(True, "xx", ""), (True, "4096\t/var/cache/apt/archives", "")]
        state = CleanAptCacheOperation().check_state()
        self.assertTrue(state["known"])
        self.assertEqual(state["deb_count"], 2)

    @patch("platforms.linux.debian.run_shell")
    def test_snap_not_installed_is_not_applicable(self, run):
        run.return_value = (False, "", "dpkg-query: package 'snapd' is not installed")
        op = RemoveSnapOperation()
        state = op.check_state()
        self.assertTrue(state["known"])
        self.assertFalse(state["installed"])
        self.assertFalse(op.is_applicable_state(state))

    @patch("platforms.linux.debian.run_shell")
    def test_static_systemd_unit_is_not_applicable(self, run):
        run.return_value = (True, "LoadState=loaded\nUnitFileState=static\nActiveState=inactive", "")
        op = DisableSystemdServiceOperation("test.service", "Test", __import__("core.operations", fromlist=["RiskLevel"]).RiskLevel.LOW, "test")
        self.assertFalse(op.is_applicable_state(op.check_state()))

    @patch("platforms.linux.debian.run_shell")
    def test_service_disabled_and_inactive_is_already_applied(self, run):
        run.return_value = (True, "LoadState=loaded\nUnitFileState=disabled\nActiveState=inactive", "")
        op = DisableSystemdServiceOperation("cups", "CUPS", __import__("core.operations", fromlist=["RiskLevel"]).RiskLevel.LOW, "test")
        state = op.check_state()
        self.assertTrue(op.is_already_applied(state))
        self.assertTrue(op.is_desired_state(state))

    @patch("platforms.linux.debian.run_shell")
    def test_systemd_snapshot_and_rollback_commands(self, run):
        op = DisableSystemdServiceOperation("cups", "CUPS", __import__("core.operations", fromlist=["RiskLevel"]).RiskLevel.LOW, "test")
        run.return_value = (True, "LoadState=loaded\nUnitFileState=enabled\nActiveState=active", "")
        snapshot = op.capture_pre_state()
        run.side_effect = [
            (True, "LoadState=loaded\nUnitFileState=disabled\nActiveState=inactive", ""),
            (True, "", ""),
            (True, "", ""),
        ]
        result = op.rollback(snapshot)
        self.assertEqual(result.state, OperationState.SUCCESS)
        self.assertEqual(run.call_count, 4)
        self.assertEqual(run.call_args_list[2].args[0], ["systemctl", "enable", "cups"])
        self.assertEqual(run.call_args_list[3].args[0], ["systemctl", "start", "cups"])

    @patch("platforms.linux.debian.run_shell")
    def test_apt_clean_invokes_expected_native_command(self, run):
        run.return_value = (True, "", "")
        result = CleanAptCacheOperation().execute()
        self.assertEqual(result.state, OperationState.SUCCESS)
        self.assertEqual(run.call_args.args[0], ["apt-get", "clean"])
        self.assertTrue(run.call_args.kwargs["use_sudo"])

    @patch("platforms.linux.debian.run_shell")
    def test_snap_purge_invokes_expected_native_command(self, run):
        run.return_value = (True, "", "")
        result = RemoveSnapOperation().execute()
        self.assertEqual(result.state, OperationState.SUCCESS)
        self.assertEqual(run.call_args.args[0], ["apt-get", "purge", "-y", "snapd"])

    @patch("platforms.linux.debian.run_shell")
    def test_service_disable_invokes_separate_systemctl_command(self, run):
        run.return_value = (True, "", "")
        op = DisableSystemdServiceOperation("cups", "CUPS", RiskLevel.LOW, "test")
        result = op.execute()
        self.assertEqual(result.state, OperationState.SUCCESS)
        self.assertEqual(run.call_args.args[0], ["systemctl", "disable", "--now", "cups"])
        self.assertTrue(run.call_args.kwargs["use_sudo"])


if __name__ == "__main__":
    unittest.main()
