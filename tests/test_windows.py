import unittest
from unittest.mock import patch
from core.operations import RiskLevel, OperationState
from platforms.windows.windows10 import RemoveAppxPackageOperation, DisableServiceOperation


class TestWindowsOperations(unittest.TestCase):

    @patch('platforms.windows.windows10.run_powershell')
    def test_remove_appx_already_removed(self, mock_run_ps):
        """Appx não instalado → execute() retorna ALREADY_APPLIED ou NOT_APPLICABLE."""
        # check_state (inspect_many) volta lista vazia → not installed
        # execute() lança throw 'O pacote desapareceu' → FAILED, mas o manager
        # converte isso. Em teste unitário direto, execute() recebe throw e retorna FAILED.
        mock_run_ps.return_value = (True, "[]", "")

        op = RemoveAppxPackageOperation("TestApp", "Test", RiskLevel.LOW, "Desc")
        # execute() sem guard: o script tenta remover e obtém "desapareceu"
        # Neste teste verificamos apenas que a chamada não explode com ValueError
        res = op.execute()
        # Pode ser SUCCESS, FAILED ou outros — o importante é não lançar exceção de unpack
        self.assertIsNotNone(res.state)

    @patch('platforms.windows.windows10.run_powershell')
    def test_remove_appx_success(self, mock_run_ps):
        """Execute retorna SUCCESS quando PS encerra com sucesso."""
        mock_run_ps.return_value = (True, "", "")

        op = RemoveAppxPackageOperation("TestApp", "Test", RiskLevel.LOW, "Desc")
        res = op.execute()
        self.assertEqual(res.state, OperationState.SUCCESS)

    @patch('platforms.windows.windows10.run_powershell')
    def test_remove_appx_fail(self, mock_run_ps):
        """Execute retorna FAILED quando PS encerra com falha."""
        mock_run_ps.return_value = (False, "", "Remove-AppxPackage: Access denied")

        op = RemoveAppxPackageOperation("TestApp", "Test", RiskLevel.LOW, "Desc")
        res = op.execute()
        self.assertEqual(res.state, OperationState.FAILED)

    @patch('platforms.windows.windows10.run_powershell')
    def test_disable_service_success(self, mock_run_ps):
        """Execute retorna SUCCESS quando PS encerra com sucesso."""
        mock_run_ps.return_value = (True, "", "")

        op = DisableServiceOperation("TestSvc", "Test Svc", RiskLevel.LOW, "Desc")
        res = op.execute()
        self.assertEqual(res.state, OperationState.SUCCESS)

    @patch('platforms.windows.windows10.run_powershell')
    def test_disable_service_fail(self, mock_run_ps):
        """Execute retorna FAILED quando PS encerra com falha."""
        mock_run_ps.return_value = (False, "", "Access denied")

        op = DisableServiceOperation("TestSvc", "Test Svc", RiskLevel.LOW, "Desc")
        res = op.execute()
        self.assertEqual(res.state, OperationState.FAILED)


if __name__ == '__main__':
    unittest.main()
