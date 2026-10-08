import unittest
from unittest.mock import patch

from core.manager import PurifyManager
from core.operations import Operation, OperationResult, OperationState, RiskLevel, ReversibilityLevel


class FakeOperation(Operation):
    def __init__(self, *, initial=False, applicable=True, execute_state=None, requires_admin=False):
        super().__init__(
            id="fake-operation",
            name="Operação simulada",
            description="Não toca no sistema.",
            category="Testes",
            platform="test",
            risk=RiskLevel.LOW,
            reversible=ReversibilityLevel.FULL,
            requires_admin=requires_admin,
        )
        self.active = initial
        self.applicable = applicable
        self.execute_state = execute_state or OperationState.SUCCESS
        self.execute_calls = 0
        self.check_calls = 0

    def check_state(self):
        self.check_calls += 1
        return {"known": True, "applicable": self.applicable, "active": self.active}

    def is_applicable_state(self, state):
        return state.get("known") and state.get("applicable")

    def is_already_applied(self, state):
        return bool(state.get("active"))

    def is_desired_state(self, state):
        return bool(state.get("active"))

    def capture_pre_state(self):
        return {"active": self.active}

    def execute(self):
        self.execute_calls += 1
        if self.execute_state is OperationState.SUCCESS:
            self.active = True
            return OperationResult(OperationState.SUCCESS, "Simulado.")
        return OperationResult(OperationState.FAILED, "Falha simulada.")

    def rollback(self, pre_state=None):
        self.active = bool(pre_state["active"])
        return OperationResult(OperationState.SUCCESS, "Rollback simulado.")

    def matches_pre_state(self, current_state, pre_state):
        return current_state.get("active") == pre_state.get("active")


class CoreResultTests(unittest.TestCase):
    def _manager(self, op, **os_info):
        op.is_selected = True
        return PurifyManager([op], {"platform": "test", "is_admin": True, **os_info})

    @patch("core.manager.save_pre_state")
    def test_success_requires_verified_post_state(self, save):
        op = FakeOperation()
        result = self._manager(op).execute_operation(op)
        self.assertEqual(result.state, OperationState.SUCCESS)
        self.assertEqual(op.check_calls, 2)
        save.assert_called_once_with(op.id, {"active": False})

    def test_preexisting_target_is_not_executed(self):
        op = FakeOperation(initial=True)
        result = self._manager(op).execute_operation(op)
        self.assertEqual(result.state, OperationState.ALREADY_APPLIED)
        self.assertEqual(op.execute_calls, 0)

    def test_known_but_missing_item_is_not_applicable(self):
        op = FakeOperation(applicable=False)
        result = self._manager(op).execute_operation(op)
        self.assertEqual(result.state, OperationState.NOT_APPLICABLE)
        self.assertEqual(op.execute_calls, 0)

    def test_unknown_pre_state_is_uncertain_and_not_executed(self):
        op = FakeOperation()
        op.check_state = lambda: {"known": False, "error": "mock query error"}
        result = self._manager(op).execute_operation(op)
        self.assertEqual(result.state, OperationState.UNCERTAIN)
        self.assertEqual(op.execute_calls, 0)

    @patch("core.manager._linux_can_elevate", return_value=False)
    def test_missing_linux_elevation_blocks_before_execution(self, can_elevate):
        op = FakeOperation(requires_admin=True)
        manager = self._manager(op, platform="debian", is_admin=False)
        result = manager.execute_operation(op)
        self.assertEqual(result.state, OperationState.FAILED)
        self.assertIn("pkexec", result.message)
        self.assertEqual(op.execute_calls, 0)

    @patch("core.manager.save_pre_state")
    def test_reported_process_success_without_change_is_uncertain(self, save):
        op = FakeOperation()
        op.execute = lambda: OperationResult(OperationState.SUCCESS, "Exit code was zero.")
        result = self._manager(op).execute_operation(op)
        self.assertEqual(result.state, OperationState.UNCERTAIN)

    @patch("core.manager.save_pre_state")
    def test_post_state_query_failure_is_uncertain(self, save):
        op = FakeOperation()
        calls = 0
        def check_state():
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"known": True, "applicable": True, "active": False}
            return {"known": False, "error": "post-check denied"}
        op.check_state = check_state
        result = self._manager(op).execute_operation(op)
        self.assertEqual(result.state, OperationState.UNCERTAIN)
        self.assertIn("post-check denied", result.message)

    @patch("core.manager.save_pre_state")
    def test_reported_failure_after_partial_change_is_uncertain(self, save):
        op = FakeOperation()
        def partial_failure():
            op.active = True
            return OperationResult(OperationState.FAILED, "falha após efeito parcial")
        op.execute = partial_failure
        result = self._manager(op).execute_operation(op)
        self.assertEqual(result.state, OperationState.UNCERTAIN)
        self.assertIn("execução parcial", result.message)

    @patch("core.manager.save_pre_state")
    def test_exception_after_partial_change_is_uncertain(self, save):
        op = FakeOperation()
        def partial_exception():
            op.active = True
            raise RuntimeError("erro após alterar estado")
        op.execute = partial_exception
        result = self._manager(op).execute_operation(op)
        self.assertEqual(result.state, OperationState.UNCERTAIN)

    @patch("core.manager.save_pre_state")
    def test_operation_failure_remains_failure(self, save):
        op = FakeOperation(execute_state=OperationState.FAILED)
        result = self._manager(op).execute_operation(op)
        self.assertEqual(result.state, OperationState.FAILED)
        self.assertIn("Falha simulada", result.message)

    @patch("core.manager.save_pre_state")
    def test_missing_admin_blocks_before_execution(self, save):
        op = FakeOperation(requires_admin=True)
        manager = self._manager(op, platform="windows", is_admin=False)
        result = manager.execute_operation(op)
        self.assertEqual(result.state, OperationState.FAILED)
        self.assertIn("administrador", result.message)
        self.assertEqual(op.execute_calls, 0)

    def test_dry_run_only_reads_state(self):
        op = FakeOperation()
        description = op.get_dry_run_description()
        self.assertTrue(description["available"])
        self.assertEqual(op.execute_calls, 0)
        self.assertEqual(description["reversibility"], ReversibilityLevel.FULL.value)

    def test_catalog_scan_reads_every_operation_without_executing(self):
        one, two = FakeOperation(), FakeOperation(initial=True)
        manager = PurifyManager([one, two], {"platform": "test", "is_admin": True})
        progress = []
        result = manager.inspect_all_states(
            lambda op, state, done, total: progress.append((op.id, done, total)),
            max_workers=2,
        )
        self.assertEqual([op for op, _ in result], [one, two])
        self.assertTrue(all(state["known"] for _, state in result))
        self.assertEqual(len(progress), 2)
        self.assertEqual(sorted(done for _, done, _ in progress), [1, 2])
        self.assertTrue(all(total == 2 for _, _, total in progress))
        self.assertEqual(one.execute_calls + two.execute_calls, 0)

    def test_catalog_scan_keeps_going_after_a_check_raises(self):
        one, two = FakeOperation(), FakeOperation()
        one.check_state = lambda: (_ for _ in ()).throw(RuntimeError("query failed"))
        manager = PurifyManager([one, two], {"platform": "test", "is_admin": True})
        result = manager.inspect_all_states(max_workers=2)
        by_op = dict(result)
        self.assertFalse(by_op[one]["known"])
        self.assertEqual(by_op[one]["error"], "query failed")
        self.assertTrue(by_op[two]["known"])

    def test_cancelled_batch_skips_all_selected_operations(self):
        import threading
        one, two = FakeOperation(), FakeOperation()
        one.is_selected = two.is_selected = True
        event = threading.Event()
        event.set()
        manager = PurifyManager([one, two], {"platform": "test", "is_admin": True})
        results = manager.execute_selected(cancel_event=event)
        self.assertEqual([r.state for _, r in results], [OperationState.CANCELLED, OperationState.CANCELLED])
        self.assertEqual(one.execute_calls + two.execute_calls, 0)

    def test_cancel_requested_during_batch_skips_following_operation(self):
        import threading
        one, two = FakeOperation(), FakeOperation()
        one.is_selected = two.is_selected = True
        event = threading.Event()
        def finish_and_cancel():
            one.execute_calls += 1
            one.active = True
            event.set()
            return OperationResult(OperationState.SUCCESS, "feito")
        one.execute = finish_and_cancel
        manager = PurifyManager([one, two], {"platform": "test", "is_admin": True})
        with patch("core.manager.save_pre_state"):
            results = manager.execute_selected(cancel_event=event)
        self.assertEqual(results[0][1].state, OperationState.SUCCESS)
        self.assertEqual(results[1][1].state, OperationState.CANCELLED)
        self.assertEqual(two.execute_calls, 0)

    @patch("core.manager.clear_pre_state")
    @patch("core.manager.get_pre_state", return_value={"active": False})
    def test_rollback_verifies_restored_state(self, get_state, clear_state):
        op = FakeOperation(initial=True)
        manager = self._manager(op)
        result = manager.rollback_operation(op)
        self.assertEqual(result.state, OperationState.SUCCESS)
        get_state.assert_called_once_with(op.id)
        clear_state.assert_called_once_with(op.id)
        self.assertFalse(op.active)

    @patch("core.manager.get_pre_state", return_value=None)
    def test_rollback_without_saved_state_reports_limitation(self, get_state):
        op = FakeOperation(initial=True)
        result = self._manager(op).rollback_operation(op)
        self.assertEqual(result.state, OperationState.FAILED)
        self.assertIn("pré-estado", result.message.lower())
        self.assertTrue(op.active)

    @patch("core.manager.clear_pre_state")
    @patch("core.manager.get_pre_state", return_value={"active": False})
    def test_uncertain_rollback_is_not_promoted_to_success(self, get_state, clear_state):
        op = FakeOperation(initial=True)
        def uncertain_rollback(pre_state):
            op.active = pre_state["active"]
            return OperationResult(OperationState.UNCERTAIN, "executor incerto")
        op.rollback = uncertain_rollback
        result = self._manager(op).rollback_operation(op)
        self.assertEqual(result.state, OperationState.UNCERTAIN)
        clear_state.assert_not_called()

    @patch("core.manager.clear_pre_state")
    @patch("core.manager.get_pre_state", return_value={"active": False})
    def test_rollback_exception_stays_uncertain_when_state_looks_restored(self, get_state, clear_state):
        op = FakeOperation(initial=True)
        def exception_after_restore(pre_state):
            op.active = pre_state["active"]
            raise RuntimeError("exceção após restauração")
        op.rollback = exception_after_restore
        result = self._manager(op).rollback_operation(op)
        self.assertEqual(result.state, OperationState.UNCERTAIN)
        clear_state.assert_not_called()

    def test_boolean_compatibility_is_conservative(self):
        self.assertTrue(OperationResult(True, "compat").success)
        self.assertFalse(OperationResult(False, "compat").success)
        self.assertFalse(OperationResult(OperationState.UNCERTAIN, "uncertain").success)


if __name__ == "__main__":
    unittest.main()
