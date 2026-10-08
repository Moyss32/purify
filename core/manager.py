from __future__ import annotations

import os
import shutil
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Iterable

from .backup import BackupStoreError, clear_pre_state, get_pre_state, save_pre_state
from .operations import Operation, OperationResult, OperationState, ReversibilityLevel
from .system_detection import get_os_info


def _linux_can_elevate() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0 or shutil.which("pkexec") is not None


class PurifyManager:
    def __init__(self, operations: Iterable[Operation] | None = None, os_info: dict | None = None):
        self.os_info = os_info or get_os_info()
        self.operations: list[Operation] = list(operations) if operations is not None else []
        if operations is None:
            self._load_operations()

    def _load_operations(self) -> None:
        platform_name = self.os_info.get("platform")
        if platform_name == "windows":
            from platforms.windows.windows10 import get_operations
            self.operations = get_operations()
        elif platform_name == "debian":
            from platforms.linux.debian import get_operations
            self.operations = get_operations()
        else:
            self.operations = []

    def get_operations_by_category(self, category: str) -> list[Operation]:
        return [op for op in self.operations if op.category == category]

    def get_all_categories(self) -> list[str]:
        return sorted({op.category for op in self.operations})

    def get_selected_operations(self) -> list[Operation]:
        return [op for op in self.operations if op.is_selected]

    def inspect_all_states(
        self,
        progress_callback: Callable[[Operation, Any, int, int], None] | None = None,
        max_workers: int = 4,
    ) -> list[tuple[Operation, Any]]:
        """Consulta o estado de todo o catálogo sem executar nenhuma ação modificadora."""
        operations = list(self.operations)
        if not operations:
            return []
        results: dict[Operation, Any] = {}
        groups: dict[type[Operation], list[Operation]] = defaultdict(list)
        for op in operations:
            groups[type(op)].append(op)
        worker_count = max(1, min(int(max_workers), len(groups)))
        completed = 0
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="purify-state") as pool:
            futures = {
                pool.submit(op_type.inspect_many, grouped_ops): grouped_ops
                for op_type, grouped_ops in groups.items()
            }
            for future in as_completed(futures):
                try:
                    group_states = future.result()
                except Exception as exc:
                    group_states = {op: {"known": False, "error": str(exc)} for op in futures[future]}
                for op in futures[future]:
                    state = group_states.get(op, {"known": False, "error": "Consulta não concluída."})
                    results[op] = state
                    completed += 1
                    if progress_callback:
                        try:
                            progress_callback(op, state, completed, len(operations))
                        except Exception:
                            # Um consumidor de progresso não deve interromper as consultas.
                            pass
        return [(op, results.get(op, {"known": False, "error": "Consulta não concluída."})) for op in operations]

    def _privilege_failure(self, op: Operation) -> str | None:
        if not op.requires_admin:
            return None
        platform_name = self.os_info.get("platform")
        if platform_name == "windows" and not self.os_info.get("is_admin", False):
            return "Esta operação exige privilégios de administrador. Feche e reabra o Purify como administrador."
        if platform_name == "debian" and not _linux_can_elevate():
            return "Esta operação exige root, mas `pkexec` não está disponível. Instale/configure um agente de autenticação gráfica ou execute em um ambiente compatível."
        return None

    @staticmethod
    def _log(logger_callback: Callable[[str], None] | None, message: str) -> None:
        if logger_callback:
            logger_callback(message)

    def execute_operation(
        self,
        op: Operation,
        logger_callback: Callable[[str], None] | None = None,
    ) -> OperationResult:
        self._log(logger_callback, f"Executando: {op.name}")
        try:
            before = op.check_state()
        except Exception as exc:
            result = OperationResult(OperationState.UNCERTAIN, f"Não foi possível verificar o estado inicial: {exc}")
            self._log(logger_callback, f"Incerto: {op.name} — {result.message}")
            return result

        if not isinstance(before, dict) or not before.get("known", False):
            detail = before.get("error", "A consulta não confirmou o estado inicial.") if isinstance(before, dict) else "A consulta não retornou um estado estruturado."
            result = OperationResult(OperationState.UNCERTAIN, str(detail), before=before)
            self._log(logger_callback, f"Incerto: {op.name} — {result.message}")
            return result

        if not op.is_applicable_state(before):
            detail = before.get("error", "A operação não se aplica a este sistema ou o estado não pôde ser confirmado.") if isinstance(before, dict) else "Estado inicial inválido."
            result = OperationResult(OperationState.NOT_APPLICABLE, str(detail), before=before)
            self._log(logger_callback, f"Não aplicável: {op.name} — {result.message}")
            return result

        if op.is_already_applied(before):
            result = OperationResult(OperationState.ALREADY_APPLIED, "O sistema já estava no estado desejado.", before=before, after=before)
            self._log(logger_callback, f"Já estava aplicado: {op.name}")
            return result

        privilege_error = self._privilege_failure(op)
        if privilege_error:
            result = OperationResult(OperationState.FAILED, privilege_error, before=before)
            self._log(logger_callback, f"Falhou ao executar {op.name} — motivo: {privilege_error}")
            return result

        try:
            pre_state = op.capture_pre_state()
            if op.reversibility is ReversibilityLevel.FULL and pre_state is None:
                raise BackupStoreError("A operação declara reversibilidade total, mas não produziu pré-estado para rollback.")
            if pre_state is not None:
                save_pre_state(op.id, pre_state)
        except Exception as exc:
            result = OperationResult(OperationState.FAILED, f"Pré-estado não foi salvo; a operação foi bloqueada: {exc}", before=before)
            self._log(logger_callback, f"Falhou ao executar {op.name} — motivo: {result.message}")
            return result

        try:
            raw_result = op.execute()
            if not isinstance(raw_result, OperationResult):
                raise TypeError("execute() deve retornar OperationResult.")
        except Exception as exc:
            try:
                after_exception = op.check_state()
            except Exception as verify_exc:
                after_exception = {"known": False, "error": str(verify_exc)}
            if isinstance(after_exception, dict) and after_exception.get("known") and op.is_desired_state(after_exception):
                result = OperationResult(
                    OperationState.UNCERTAIN,
                    f"A execução gerou exceção ({exc}), embora o estado desejado apareça aplicado; podem ter ocorrido efeitos parciais.",
                    before=before,
                    after=after_exception,
                )
                self._log(logger_callback, f"Incerto: {op.name} — {result.message}")
            elif isinstance(after_exception, dict) and after_exception.get("known") and after_exception == before:
                result = OperationResult(OperationState.FAILED, f"Exceção durante a execução: {exc}", before=before, after=after_exception)
                self._log(logger_callback, f"Falhou ao executar {op.name} — motivo: {result.message}")
            else:
                result = OperationResult(
                    OperationState.UNCERTAIN,
                    f"Exceção durante a execução e não foi possível determinar se houve alteração: {exc}",
                    before=before,
                    after=after_exception,
                )
                self._log(logger_callback, f"Incerto: {op.name} — {result.message}")
            return result

        try:
            after = op.check_state()
        except Exception as exc:
            result = OperationResult(
                OperationState.UNCERTAIN,
                f"A ação terminou, mas a verificação posterior falhou: {exc}",
                data=raw_result.data,
                before=before,
            )
            self._log(logger_callback, f"Incerto: {op.name} — {result.message}")
            return result

        if raw_result.state is not OperationState.SUCCESS:
            after_known = isinstance(after, dict) and after.get("known", False)
            if raw_result.state is OperationState.FAILED and (
                not after_known or after != before or op.is_desired_state(after)
            ):
                result = OperationResult(
                    OperationState.UNCERTAIN,
                    f"O executor reportou falha ({raw_result.message}), mas a verificação não prova que nada mudou; pode ter havido execução parcial.",
                    data=raw_result.data,
                    before=before,
                    after=after,
                )
                self._log(logger_callback, f"Incerto: {op.name} — {result.message}")
                return result
            result = OperationResult(
                raw_result.state,
                raw_result.message,
                data=raw_result.data,
                before=before,
                after=after,
            )
            label = "Falhou" if result.state is OperationState.FAILED else result.state.value
            self._log(logger_callback, f"{label}: {op.name} — motivo: {result.message}")
            return result

        if not isinstance(after, dict) or not after.get("known", False):
            detail = after.get("error", "A verificação não retornou estado conhecido.") if isinstance(after, dict) else "A verificação não retornou um estado válido."
            result = OperationResult(
                OperationState.UNCERTAIN,
                f"A ação foi tentada, mas não foi possível confirmar o resultado: {detail}",
                data=raw_result.data,
                before=before,
                after=after,
            )
            self._log(logger_callback, f"Incerto: {op.name} — {result.message}")
            return result

        if not op.is_desired_state(after):
            result = OperationResult(
                OperationState.UNCERTAIN,
                "O comando não reportou erro, mas a verificação não confirmou o estado desejado.",
                data=raw_result.data,
                before=before,
                after=after,
            )
            self._log(logger_callback, f"Incerto: {op.name} — {result.message}")
            return result

        result = OperationResult(OperationState.SUCCESS, raw_result.message, data=raw_result.data, before=before, after=after)
        self._log(logger_callback, f"Concluído: {op.name}")
        return result

    def execute_selected(
        self,
        logger_callback: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> list[tuple[Operation, OperationResult]]:
        selected = self.get_selected_operations()
        results: list[tuple[Operation, OperationResult]] = []
        cancellation_requested = False
        for op in selected:
            if cancellation_requested or (cancel_event and cancel_event.is_set()):
                cancellation_requested = True
                result = OperationResult(OperationState.CANCELLED, "Cancelado antes de iniciar; a operação atual, se houver, foi concluída antes de verificar o cancelamento.")
                results.append((op, result))
                self._log(logger_callback, f"Cancelado: {op.name}")
                continue
            results.append((op, self.execute_operation(op, logger_callback)))
        return results

    def rollback_operation(
        self,
        op: Operation,
        logger_callback: Callable[[str], None] | None = None,
    ) -> OperationResult:
        if op.reversibility is not ReversibilityLevel.FULL:
            result = OperationResult(OperationState.FAILED, "Esta operação não oferece rollback automático total.")
            self._log(logger_callback, f"Falhou ao reverter {op.name} — motivo: {result.message}")
            return result
        try:
            pre_state = get_pre_state(op.id)
            if pre_state is None:
                raise BackupStoreError("Não há pré-estado persistido para esta operação.")
        except Exception as exc:
            result = OperationResult(OperationState.FAILED, f"Não é possível reverter com segurança: {exc}")
            self._log(logger_callback, f"Falhou ao reverter {op.name} — motivo: {result.message}")
            return result

        self._log(logger_callback, f"Revertendo: {op.name}")
        try:
            raw_result = op.rollback(pre_state)
            if not isinstance(raw_result, OperationResult):
                raise TypeError("rollback() deve retornar OperationResult.")
            after = op.check_state()
        except Exception as exc:
            try:
                after_exception = op.check_state()
            except Exception as verify_exc:
                after_exception = {"known": False, "error": str(verify_exc)}
            if isinstance(after_exception, dict) and after_exception.get("known") and op.matches_pre_state(after_exception, pre_state):
                result = OperationResult(
                    OperationState.UNCERTAIN,
                    f"O rollback gerou uma exceção ({exc}), embora o estado anterior apareça restaurado; o snapshot foi mantido.",
                    after=after_exception,
                )
                self._log(logger_callback, f"Incerto: rollback de {op.name} — {result.message}")
            elif isinstance(after_exception, dict) and after_exception.get("known"):
                result = OperationResult(OperationState.FAILED, f"Falha durante rollback: {exc}; o estado anterior não foi restaurado.", after=after_exception)
                self._log(logger_callback, f"Falhou ao reverter {op.name} — motivo: {result.message}")
            else:
                result = OperationResult(OperationState.UNCERTAIN, f"Falha durante rollback e não foi possível verificar o estado: {exc}", after=after_exception)
                self._log(logger_callback, f"Incerto: rollback de {op.name} — {result.message}")
            return result

        if raw_result.state is not OperationState.SUCCESS:
            result = OperationResult(raw_result.state, raw_result.message, data=raw_result.data, after=after)
        elif not isinstance(after, dict) or not after.get("known", False):
            result = OperationResult(OperationState.UNCERTAIN, "Rollback executado, mas a verificação posterior falhou.", after=after)
        elif not op.matches_pre_state(after, pre_state):
            result = OperationResult(OperationState.UNCERTAIN, "O estado restaurado não corresponde ao pré-estado salvo.", after=after)
        else:
            try:
                clear_pre_state(op.id)
                message = raw_result.message
            except Exception as exc:
                message = f"{raw_result.message} O estado foi restaurado e verificado, mas o snapshot não pôde ser removido: {exc}"
            result = OperationResult(OperationState.SUCCESS, message, after=after)
        label = "Concluído" if result.state is OperationState.SUCCESS else result.state.value
        self._log(logger_callback, f"{label}: rollback de {op.name} — {result.message}")
        return result
