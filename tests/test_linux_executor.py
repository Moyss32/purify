import unittest
from unittest.mock import patch, Mock

from platforms.linux.utils import run_shell


class LinuxExecutorTests(unittest.TestCase):
    @patch("platforms.linux.utils.subprocess.run")
    def test_uses_argument_vector_without_shell(self, run):
        run.return_value = Mock(returncode=0, stdout="done\n", stderr="")
        ok, out, err = run_shell(["apt-get", "clean"])
        self.assertTrue(ok)
        self.assertEqual(out, "done")
        kwargs = run.call_args.kwargs
        self.assertNotIn("shell", kwargs)
        self.assertEqual(run.call_args.args[0], ["apt-get", "clean"])

    @patch("platforms.linux.utils.os.geteuid", return_value=1000)
    @patch("platforms.linux.utils.shutil.which", return_value="/usr/bin/pkexec")
    @patch("platforms.linux.utils.subprocess.run")
    def test_elevated_gui_command_uses_pkexec(self, run, which, geteuid):
        run.return_value = Mock(returncode=0, stdout="", stderr="")
        ok, _, _ = run_shell(["systemctl", "disable", "cups"], use_sudo=True)
        self.assertTrue(ok)
        self.assertEqual(run.call_args.args[0], ["/usr/bin/pkexec", "systemctl", "disable", "cups"])

    @patch("platforms.linux.utils.os.geteuid", return_value=1000)
    @patch("platforms.linux.utils.shutil.which", return_value=None)
    @patch("platforms.linux.utils.subprocess.run")
    def test_missing_pkexec_fails_without_running_command(self, run, which, geteuid):
        ok, _, err = run_shell(["apt-get", "clean"], use_sudo=True)
        self.assertFalse(ok)
        self.assertIn("pkexec", err)
        run.assert_not_called()

    @patch("platforms.linux.utils.subprocess.run")
    def test_legacy_string_is_split_without_shell(self, run):
        run.return_value = Mock(returncode=0, stdout="", stderr="")
        run_shell("systemctl is-enabled cups")
        self.assertEqual(run.call_args.args[0], ["systemctl", "is-enabled", "cups"])
        self.assertNotIn("shell", run.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
