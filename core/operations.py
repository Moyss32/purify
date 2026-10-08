from __future__ import annotations

from enum import Enum
from typing import Any


class RiskLevel(Enum):
    VERY_LOW = "Muito baixo"
    LOW = "Baixo"
    MEDIUM = "Médio"
    HIGH = "Alto"
    CRITICAL = "Crítico"


class OperationState(Enum):
    PENDING = "Pendente"
    RUNNING = "Executando"
    SUCCESS = "Concluído"
    FAILED = "Falhou"
    ALREADY_APPLIED = "Já estava aplicado"
    NOT_APPLICABLE = "Não aplicável"
    CANCELLED = "Cancelado"
    UNCERTAIN = "Incerto"


class ReversibilityLevel(Enum):
    FULL = "Totalmente reversível"
    PARTIAL = "Parcialmente reversível"
    NONE = "Irreversível"


class OperationResult:
    """Resultado de uma operação. SUCCESS só deve ser usado após verificação."""

    def __init__(
        self,
        state: OperationState | bool,
        message: str,
        data: Any = None,
        before: Any = None,
        after: Any = None,
    ):
        # Compatibilidade temporária com operações legadas que ainda passam bool.
        if isinstance(state, bool):
            state = OperationState.SUCCESS if state else OperationState.FAILED
        self.state = state
        self.message = message
        self.data = data
        self.before = before
        self.after = after

    @property
    def success(self) -> bool:
        """Compatibilidade: só estados efetivamente bem-sucedidos contam como True."""
        return self.state in {OperationState.SUCCESS, OperationState.ALREADY_APPLIED}


class Operation:
    def __init__(
        self,
        id: str,
        name: str,
        description: str,
        category: str,
        platform: str,
        risk: RiskLevel,
        reversible: bool | ReversibilityLevel,
        requires_admin: bool,
    ):
        self.id = id
        self.name = name
        self.description = description
        self.category = category
        self.platform = platform
        self.risk = risk
        if isinstance(reversible, ReversibilityLevel):
            self.reversibility = reversible
        else:
            self.reversibility = ReversibilityLevel.FULL if reversible else ReversibilityLevel.NONE
        self.requires_admin = requires_admin
        self.is_selected = False

    @property
    def reversible(self) -> bool:
        """Compatibilidade para consumidores antigos; PARTIAL não é rollback automático."""
        return self.reversibility is ReversibilityLevel.FULL

    def check_state(self) -> Any:
        """Retorna um snapshot somente de leitura. `known=False` indica falha de consulta."""
        return {"known": False, "error": "Verificação de estado não implementada."}

    @classmethod
    def inspect_many(cls, operations: list[Operation]) -> dict[Operation, Any]:
        """Consulta várias operações do mesmo tipo; subclasses podem agrupar uma única chamada nativa."""
        states: dict[Operation, Any] = {}
        for op in operations:
            try:
                states[op] = op.check_state()
            except Exception as exc:
                states[op] = {"known": False, "error": str(exc)}
        return states

    def is_applicable_state(self, state: Any) -> bool:
        if not isinstance(state, dict):
            return False
        return bool(state.get("known", False))

    def is_already_applied(self, state: Any) -> bool:
        return False

    def is_desired_state(self, state: Any) -> bool:
        return False

    def matches_pre_state(self, current_state: Any, pre_state: Any) -> bool:
        return current_state == pre_state

    def capture_pre_state(self) -> Any:
        """Dados necessários ao rollback. FULL precisa retornar dados persistíveis."""
        return None

    def execute(self) -> OperationResult:
        raise NotImplementedError()

    def rollback(self, pre_state: Any = None) -> OperationResult:
        if self.reversibility is not ReversibilityLevel.FULL:
            return OperationResult(OperationState.FAILED, "Rollback automático não está disponível.")
        raise NotImplementedError()

    def _describe_action(self) -> str:
        return self.description

    def _describe_impact(self) -> str:
        return self.description

    def _describe_rollback(self) -> str:
        if self.reversibility is ReversibilityLevel.FULL:
            return "O estado anterior é salvo antes da alteração e pode ser restaurado pelo Purify."
        if self.reversibility is ReversibilityLevel.PARTIAL:
            return "Restauração automática não garantida; pode exigir ação manual."
        return "Esta alteração não possui rollback automático."

    def get_dry_run_description(self) -> dict[str, Any]:
        """Gera uma prévia somente de leitura; nunca chama execute()."""
        try:
            state = self.check_state()
        except Exception as exc:
            return {
                "available": False,
                "name": self.name,
                "error": f"Não foi possível consultar o estado: {exc}",
            }
        if not self.is_applicable_state(state):
            return {
                "available": False,
                "name": self.name,
                "current_state": state,
                "error": "O estado atual é desconhecido ou a operação não se aplica.",
            }
        return {
            "available": True,
            "name": self.name,
            "current_state": state,
            "planned_action": self._describe_action(),
            "estimated_impact": self._describe_impact(),
            "risk": self.risk.value,
            "reversibility": self.reversibility.value,
            "requires_admin": self.requires_admin,
            "rollback_plan": self._describe_rollback(),
            "already_applied": self.is_already_applied(state),
        }

    def get_impact_description(self) -> str:
        return f"Impacto: {self.description}\nRisco: {self.risk.value}"
