from __future__ import annotations

from typing import Any

from core.operations import Operation, OperationResult, OperationState, RiskLevel, ReversibilityLevel
from .utils import run_shell


def _known(state: Any) -> bool:
    return isinstance(state, dict) and bool(state.get("known"))


class CleanAptCacheOperation(Operation):
    def __init__(self):
        super().__init__(
            id="deb_clean_apt",
            name="Limpar Cache do APT",
            description="Remove arquivos de pacote .deb baixados no cache do APT; não remove pacotes instalados.",
            category="Limpeza",
            platform="debian",
            risk=RiskLevel.VERY_LOW,
            reversible=ReversibilityLevel.NONE,
            requires_admin=True,
        )

    def check_state(self) -> dict[str, Any]:
        ok, out, err = run_shell(["find", "/var/cache/apt/archives", "-maxdepth", "1", "-type", "f", "-name", "*.deb", "-printf", "x"])
        if not ok:
            return {"known": False, "error": err or out or "Não foi possível listar o cache do APT."}
        ok_size, size_out, size_err = run_shell(["du", "-sb", "/var/cache/apt/archives"])
        if not ok_size:
            return {"known": False, "error": size_err or size_out or "Não foi possível medir o cache do APT."}
        try:
            size_bytes = int(size_out.split()[0])
        except (ValueError, IndexError):
            return {"known": False, "error": "A saída de du não pôde ser interpretada."}
        return {"known": True, "deb_count": len(out), "size_bytes": size_bytes}

    def is_applicable_state(self, state: Any) -> bool:
        return _known(state)

    def is_already_applied(self, state: Any) -> bool:
        return _known(state) and state.get("deb_count") == 0

    def is_desired_state(self, state: Any) -> bool:
        return self.is_already_applied(state)

    def execute(self) -> OperationResult:
        ok, out, err = run_shell(["apt-get", "clean"], use_sudo=True)
        if ok:
            return OperationResult(OperationState.SUCCESS, "Cache do APT limpo; o resultado será confirmado por nova consulta.")
        return OperationResult(OperationState.FAILED, f"Falha ao limpar cache do APT: {err or out or 'erro sem detalhes'}")

    def _describe_action(self) -> str:
        return "Executar `apt-get clean`; a prévia apenas consulta quantos arquivos .deb estão no cache."

    def _describe_impact(self) -> str:
        return "Libera espaço removendo arquivos baixados. Os pacotes instalados permanecem; o cache terá de ser baixado novamente se necessário."


class RemoveSnapOperation(Operation):
    def __init__(self):
        super().__init__(
            id="deb_remove_snapd",
            name="Remover Snapd",
            description="Remove o pacote gerenciador snapd via APT. Não apaga manualmente diretórios de dados nem garante a remoção de snaps instalados.",
            category="Gerenciadores de Pacotes",
            platform="debian",
            risk=RiskLevel.MEDIUM,
            reversible=ReversibilityLevel.NONE,
            requires_admin=True,
        )

    def check_state(self) -> dict[str, Any]:
        ok, out, err = run_shell(["dpkg-query", "-s", "snapd"])
        if ok:
            status_line = next((line.split(":", 1)[1].strip() for line in out.splitlines() if line.startswith("Status:")), "")
            return {"known": True, "installed": status_line.endswith("installed"), "status": status_line}
        low = err.lower()
        if "is not installed" in low or "no information is available" in low or "not installed" in low:
            return {"known": True, "installed": False, "status": "not installed"}
        return {"known": False, "error": err or out or "Não foi possível consultar o pacote snapd."}

    def is_applicable_state(self, state: Any) -> bool:
        return _known(state) and bool(state.get("installed"))

    def is_desired_state(self, state: Any) -> bool:
        return _known(state) and not state.get("installed", True)

    def capture_pre_state(self) -> Any:
        ok, out, err = run_shell(["snap", "list", "--all"])
        return {"snap_list_available": ok, "snap_list": out if ok else "", "snapshot_error": err if not ok else ""}

    def execute(self) -> OperationResult:
        ok, out, err = run_shell(["apt-get", "purge", "-y", "snapd"], use_sudo=True)
        if ok:
            return OperationResult(OperationState.SUCCESS, "Pacote snapd removido pelo APT; confira o estado e os snaps/dados remanescentes.")
        return OperationResult(OperationState.FAILED, f"Falha ao remover snapd: {err or out or 'erro sem detalhes'}")

    def _describe_action(self) -> str:
        return "Executar `apt-get purge snapd`. Nenhum `rm -rf` de diretórios é executado."

    def _describe_impact(self) -> str:
        return "Pode afetar a instalação e execução de aplicativos Snap. A operação é irreversível pelo Purify; dados e snaps existentes podem exigir recuperação manual."

    def _describe_rollback(self) -> str:
        return "Irreversível pelo Purify. O pré-estado da lista de snaps é guardado apenas como referência; não permite reinstalar/restaurar automaticamente."


class DisableSystemdServiceOperation(Operation):
    SUPPORTED_UNIT_STATES = {"enabled", "disabled", "masked"}

    def __init__(self, service_name: str, friendly_name: str, risk: RiskLevel, description: str):
        super().__init__(
            id=f"deb_disable_svc_{service_name}",
            name=f"Desativar {friendly_name}",
            description=description,
            category="Serviços",
            platform="debian",
            risk=risk,
            reversible=ReversibilityLevel.FULL,
            requires_admin=True,
        )
        self.service_name = service_name

    def check_state(self) -> dict[str, Any]:
        ok, out, err = run_shell([
            "systemctl", "show", self.service_name,
            "--property=LoadState", "--property=UnitFileState", "--property=ActiveState",
        ])
        if not ok:
            return {"known": False, "error": err or out or f"systemctl não conseguiu consultar {self.service_name}."}
        values = {}
        for line in out.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value.strip()
        if "LoadState" not in values:
            return {"known": False, "error": f"A resposta de systemctl para {self.service_name} não contém LoadState."}
        return {
            "known": True,
            "service": self.service_name,
            "load_state": values.get("LoadState", "unknown"),
            "unit_file_state": values.get("UnitFileState", "unknown"),
            "active_state": values.get("ActiveState", "unknown"),
        }

    def is_applicable_state(self, state: Any) -> bool:
        return (
            _known(state)
            and state.get("load_state") == "loaded"
            and state.get("unit_file_state") in self.SUPPORTED_UNIT_STATES
            and not (state.get("unit_file_state") == "masked" and state.get("active_state") == "active")
        )

    def is_already_applied(self, state: Any) -> bool:
        return _known(state) and state.get("unit_file_state") == "masked" and state.get("active_state") != "active" or (
            _known(state) and state.get("unit_file_state") == "disabled" and state.get("active_state") != "active"
        )

    def is_desired_state(self, state: Any) -> bool:
        return self.is_already_applied(state)

    def capture_pre_state(self) -> Any:
        state = self.check_state()
        if not _known(state) or not self.is_applicable_state(state):
            raise RuntimeError("O serviço não possui estado inicial que o Purify saiba restaurar com segurança.")
        return {key: state[key] for key in ("service", "unit_file_state", "active_state")}

    def execute(self) -> OperationResult:
        ok, out, err = run_shell(["systemctl", "disable", "--now", self.service_name], use_sudo=True)
        if ok:
            return OperationResult(OperationState.SUCCESS, f"{self.name} desativado; estado será verificado.")
        return OperationResult(OperationState.FAILED, f"Falha ao desativar {self.name}: {err or out or 'erro sem detalhes'}")

    def rollback(self, pre_state: Any = None) -> OperationResult:
        if not isinstance(pre_state, dict) or pre_state.get("service") != self.service_name:
            return OperationResult(OperationState.FAILED, "Pré-estado ausente ou inválido para este serviço.")
        original_unit_state = pre_state.get("unit_file_state")
        if original_unit_state not in self.SUPPORTED_UNIT_STATES:
            return OperationResult(OperationState.FAILED, f"Estado de inicialização original não suportado: {original_unit_state!r}.")

        commands = []
        current = self.check_state()
        if _known(current) and current.get("unit_file_state") == "masked" and original_unit_state != "masked":
            commands.append(["systemctl", "unmask", self.service_name])
        if original_unit_state == "enabled":
            commands.append(["systemctl", "enable", self.service_name])
        elif original_unit_state == "disabled":
            commands.append(["systemctl", "disable", self.service_name])
        elif original_unit_state == "masked":
            commands.append(["systemctl", "mask", self.service_name])

        if pre_state.get("active_state") == "active":
            commands.append(["systemctl", "start", self.service_name])
        else:
            commands.append(["systemctl", "stop", self.service_name])

        for command in commands:
            ok, out, err = run_shell(command, use_sudo=True)
            if not ok:
                return OperationResult(OperationState.FAILED, f"Falha em {' '.join(command)}: {err or out or 'erro sem detalhes'}")
        return OperationResult(OperationState.SUCCESS, f"Estado original de {self.name} restaurado; será verificado.")

    def matches_pre_state(self, current_state: Any, pre_state: Any) -> bool:
        return (
            _known(current_state)
            and current_state.get("unit_file_state") == pre_state.get("unit_file_state")
            and (current_state.get("active_state") == "active") == (pre_state.get("active_state") == "active")
        )

    def _describe_action(self) -> str:
        return f"Executar `systemctl disable --now {self.service_name}` após salvar o estado de inicialização e atividade."

    def _describe_impact(self) -> str:
        return f"Desativa e interrompe o serviço {self.service_name}. Dependências que esperam por esse serviço podem deixar de funcionar."

    def _describe_rollback(self) -> str:
        return "O estado enabled/disabled/masked e active/inactive é salvo em ~/.purify e restaurado pelo Purify."


def get_operations() -> list[Operation]:
    return [
        CleanAptCacheOperation(),
        RemoveSnapOperation(),
        DisableSystemdServiceOperation("cups", "Serviço de Impressão (CUPS)", RiskLevel.LOW, "Desative apenas se não usa impressão local ou em rede."),
        DisableSystemdServiceOperation("bluetooth", "Bluetooth", RiskLevel.LOW, "Desative apenas se não usa Bluetooth neste sistema."),
        DisableSystemdServiceOperation("NetworkManager", "Gerenciador de Rede", RiskLevel.CRITICAL, "Pode interromper a conectividade e impedir acesso remoto. Não desative em uma sessão remota sem alternativa de rede."),
    ]
