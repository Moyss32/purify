import unittest
from unittest.mock import Mock, patch

from platforms.windows.utils import run_powershell


class WindowsExecutorTests(unittest.TestCase):
    @patch("platforms.windows.utils.shutil.which", return_value="/fake/powershell")
    @patch("platforms.windows.utils.subprocess.run")
    def test_executes_without_shell_and_uses_stop_on_errors(self, run, which):
        run.return_value = Mock(returncode=0, stdout="ok", stderr="")
        ok, out, _ = run_powershell("Write-Output 'ok'")
        self.assertTrue(ok)
        self.assertEqual(out, "ok")
        args = run.call_args.args[0]
        self.assertEqual(args[0], "/fake/powershell")
        self.assertIn("$ErrorActionPreference = 'Stop'", args[-1])
        self.assertNotIn("shell", run.call_args.kwargs)

    @patch("platforms.windows.utils.shutil.which", return_value="/fake/powershell")
    @patch("platforms.windows.utils.subprocess.run")
    def test_nonzero_exit_is_failure(self, run, which):
        run.return_value = Mock(returncode=1, stdout="", stderr="access denied")
        ok, _, err = run_powershell("throw 'access denied'")
        self.assertFalse(ok)
        self.assertIn("access denied", err)

    @patch("platforms.windows.utils.shutil.which", return_value=None)
    def test_missing_powershell_returns_clear_failure(self, which):
        ok, _, err = run_powershell("Get-Service")
        self.assertFalse(ok)
        self.assertIn("não foi encontrado", err)


if __name__ == "__main__":
    unittest.main()
