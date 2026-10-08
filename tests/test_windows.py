import unittest
from unittest.mock import patch
from core.operations import RiskLevel, OperationState
from platforms.windows.windows10 import RemoveAppxPackageOperation, DisableServiceOperation

class TestWindowsOperations(unittest.TestCase):
    
    @patch('platforms.windows.windows10.run_powershell')
    def test_remove_appx_already_removed(self, mock_run_ps):
        # mock check_state returning False to 'Get-AppxPackage'
        mock_run_ps.return_value = (True, "", "", 0)
        
        op = RemoveAppxPackageOperation("TestApp", "Test", RiskLevel.LOW, "Desc")
        res = op.execute()
        self.assertEqual(res.state, OperationState.ALREADY_APPLIED)

    @patch('platforms.windows.windows10.run_powershell')
    def test_remove_appx_success(self, mock_run_ps):
        # first call is check_state, second is execute
        def side_effect(script):
            if "Get-AppxPackage" in script and "Remove-AppxPackage" not in script:
                return (True, "TestApp_1.0", "", 0)
            return (True, "", "", 0)
        mock_run_ps.side_effect = side_effect
        
        op = RemoveAppxPackageOperation("TestApp", "Test", RiskLevel.LOW, "Desc")
        res = op.execute()
        self.assertEqual(res.state, OperationState.SUCCESS)

    @patch('platforms.windows.windows10.run_powershell')
    def test_remove_appx_fail(self, mock_run_ps):
        def side_effect(script):
            if "Get-AppxPackage" in script and "Remove-AppxPackage" not in script:
                return (True, "TestApp_1.0", "", 0)
            # PS fails (like non-terminating error that makes exit_code=1)
            return (False, "", "Error", 1)
        mock_run_ps.side_effect = side_effect
        
        op = RemoveAppxPackageOperation("TestApp", "Test", RiskLevel.LOW, "Desc")
        res = op.execute()
        self.assertEqual(res.state, OperationState.FAILED)

    @patch('platforms.windows.windows10.run_powershell')
    def test_disable_service_already_disabled(self, mock_run_ps):
        def side_effect(script):
            if "(Get-Service" in script:
                return (True, "Stopped", "", 0)
            if "Win32_Service" in script:
                return (True, "Disabled", "", 0)
            return (True, "", "", 0)
        mock_run_ps.side_effect = side_effect
        
        op = DisableServiceOperation("TestSvc", "Test Svc", RiskLevel.LOW, "Desc")
        res = op.execute()
        self.assertEqual(res.state, OperationState.ALREADY_APPLIED)

if __name__ == '__main__':
    unittest.main()
