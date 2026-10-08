from __future__ import annotations

import json
import re
from typing import Any

from core.operations import Operation, OperationResult, OperationState, RiskLevel, ReversibilityLevel
from .utils import run_powershell


_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _run_json(script: str) -> tuple[bool, Any, str]:
    ok, out, err = run_powershell(script)
    if not ok:
        return False, None, err or out or "PowerShell encerrou com falha sem detalhes."
    if not out:
        return False, None, "PowerShell não retornou os dados de estado esperados."
    try:
        return True, json.loads(out), ""
    except json.JSONDecodeError as exc:
        return False, None, f"Resposta JSON inválida do PowerShell: {exc}; saída: {out[:500]}"


class RemoveAppxPackageOperation(Operation):
    def __init__(self, package_name: str, friendly_name: str, risk: RiskLevel, description: str):
        if not _SAFE_ID.fullmatch(package_name):
            raise ValueError("Identificador Appx inválido.")
        super().__init__(
            id=f"win_rm_appx_{package_name}",
            name=f"Remover {friendly_name}",
            description=description,
            category="Aplicativos",
            platform="windows",
            risk=risk,
            reversible=ReversibilityLevel.PARTIAL,
            requires_admin=True,
        )
        self.package_name = package_name

    def check_state(self) -> dict[str, Any]:
        name = _ps_quote(self.package_name)
        script = (
            f"$items = @(Get-AppxPackage -AllUsers -Name {name} -ErrorAction Stop | "
            "Sort-Object PackageFullName -Unique | Select-Object Name, PackageFullName, Version, InstallLocation); "
            "if ($items.Count -eq 0) { [Console]::Out.WriteLine('[]') } "
            "else { ConvertTo-Json -InputObject $items -Compress }"
        )
        ok, data, err = _run_json(script)
        if not ok:
            return {"known": False, "error": err}
        packages = data if isinstance(data, list) else [data]
        return {"known": True, "installed": bool(packages), "packages": packages}

    @classmethod
    def inspect_many(cls, operations: list[Operation]) -> dict[Operation, Any]:
        names = ",".join(_ps_quote(op.package_name) for op in operations)
        script = (
            f"$names = @({names}); "
            "$items = @(Get-AppxPackage -AllUsers -ErrorAction Stop | Where-Object { $names -contains $_.Name } | "
            "Sort-Object PackageFullName -Unique | Select-Object Name, PackageFullName, Version, InstallLocation); "
            "if ($items.Count -eq 0) { [Console]::Out.WriteLine('[]') } "
            "else { ConvertTo-Json -InputObject $items -Compress }"
        )
        ok, data, err = _run_json(script)
        if not ok:
            return {op: {"known": False, "error": err} for op in operations}
        items = data if isinstance(data, list) else [data]
        by_name: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("Name"), str):
                by_name.setdefault(item["Name"].casefold(), []).append(item)
        return {
            op: {
                "known": True,
                "installed": bool(by_name.get(op.package_name.casefold())),
                "packages": by_name.get(op.package_name.casefold(), []),
            }
            for op in operations
        }

    def is_applicable_state(self, state: Any) -> bool:
        return isinstance(state, dict) and state.get("known") and bool(state.get("installed"))

    def is_desired_state(self, state: Any) -> bool:
        return isinstance(state, dict) and state.get("known") and not state.get("installed", True)

    def capture_pre_state(self) -> Any:
        state = self.check_state()
        if not state.get("known") or not state.get("installed"):
            raise RuntimeError("O pacote Appx não foi confirmado como instalado.")
        return {"package_name": self.package_name, "packages": state["packages"]}

    def execute(self) -> OperationResult:
        name = _ps_quote(self.package_name)
        script = (
            f"$items = @(Get-AppxPackage -AllUsers -Name {name} -ErrorAction Stop | Sort-Object PackageFullName -Unique); "
            "if ($items.Count -eq 0) { throw 'O pacote desapareceu antes da remoção.' }; "
            "foreach ($item in $items) { Remove-AppxPackage -Package $item.PackageFullName -AllUsers -ErrorAction Stop }"
        )
        ok, out, err = run_powershell(script)
        if ok:
            return OperationResult(OperationState.SUCCESS, f"{self.name} removido dos perfis em que estava instalado; a verificação será feita em seguida.")
        return OperationResult(OperationState.FAILED, f"Falha ao remover {self.name}: {err or out or 'erro sem detalhes'}")

    def _describe_action(self) -> str:
        return f"Remover o pacote Appx de nome exato {self.package_name} dos perfis em que estiver instalado. Não remove a imagem provisionada para novos usuários."

    def _describe_impact(self) -> str:
        return f"{self.description} A operação pode depender da edição/build do Windows e pode exigir reinstalação manual pela Microsoft Store."

    def _describe_rollback(self) -> str:
        return "Reversibilidade parcial: os metadados do pacote são registrados, mas o Purify não promete reinstalação automática. Reinstale pela Microsoft Store se disponível."


class DisableServiceOperation(Operation):
    def __init__(self, service_name: str, friendly_name: str, risk: RiskLevel, description: str):
        if not _SAFE_ID.fullmatch(service_name):
            raise ValueError("Identificador de serviço inválido.")
        super().__init__(
            id=f"win_disable_svc_{service_name}",
            name=f"Desativar {friendly_name}",
            description=description,
            category="Serviços",
            platform="windows",
            risk=risk,
            reversible=ReversibilityLevel.FULL,
            requires_admin=True,
        )
        self.service_name = service_name

    def check_state(self) -> dict[str, Any]:
        name = _ps_quote(self.service_name)
        script = (
            f"$item = Get-CimInstance Win32_Service -ErrorAction Stop | Where-Object {{ $_.Name -eq {name} }} | Select-Object -First 1 Name, StartMode, State; "
            "if ($null -eq $item) { [Console]::Out.WriteLine('{\"known\":true,\"found\":false}') } "
            "else { ConvertTo-Json -InputObject @{ known=$true; found=$true; service=$item.Name; start_mode=$item.StartMode; status=$item.State } -Compress }"
        )
        ok, data, err = _run_json(script)
        if not ok:
            return {"known": False, "error": err}
        if not isinstance(data, dict):
            return {"known": False, "error": "PowerShell retornou estrutura de serviço inesperada."}
        return data

    @classmethod
    def inspect_many(cls, operations: list[Operation]) -> dict[Operation, Any]:
        names = ",".join(_ps_quote(op.service_name) for op in operations)
        script = (
            f"$names = @({names}); "
            "$items = @(Get-CimInstance Win32_Service -ErrorAction Stop | Where-Object { $names -contains $_.Name } | "
            "Select-Object Name, StartMode, State); "
            "if ($items.Count -eq 0) { [Console]::Out.WriteLine('[]') } "
            "else { ConvertTo-Json -InputObject $items -Compress }"
        )
        ok, data, err = _run_json(script)
        if not ok:
            return {op: {"known": False, "error": err} for op in operations}
        items = data if isinstance(data, list) else [data]
        by_name = {
            item["Name"].casefold(): item
            for item in items
            if isinstance(item, dict) and isinstance(item.get("Name"), str)
        }
        states: dict[Operation, Any] = {}
        for op in operations:
            item = by_name.get(op.service_name.casefold())
            states[op] = (
                {"known": True, "found": False}
                if item is None
                else {
                    "known": True,
                    "found": True,
                    "service": item["Name"],
                    "start_mode": item["StartMode"],
                    "status": item["State"],
                }
            )
        return states

    def is_applicable_state(self, state: Any) -> bool:
        return isinstance(state, dict) and state.get("known") and bool(state.get("found"))

    def is_already_applied(self, state: Any) -> bool:
        return self.is_applicable_state(state) and state.get("start_mode", "").lower() == "disabled" and state.get("status", "").lower() != "running"

    def is_desired_state(self, state: Any) -> bool:
        return self.is_already_applied(state)

    def capture_pre_state(self) -> Any:
        state = self.check_state()
        if not self.is_applicable_state(state):
            raise RuntimeError("O serviço não foi encontrado ou seu estado não pôde ser confirmado.")
        if state.get("start_mode") not in {"Auto", "Manual", "Disabled"}:
            raise RuntimeError(f"Tipo de inicialização não suportado para rollback: {state.get('start_mode')!r}.")
        return {"service": self.service_name, "start_mode": state["start_mode"], "status": state["status"]}

    def execute(self) -> OperationResult:
        name = _ps_quote(self.service_name)
        script = (
            f"$s = Get-Service -Name {name} -ErrorAction Stop; "
            f"Set-Service -Name {name} -StartupType Disabled -ErrorAction Stop; "
            "if ($s.Status -eq 'Running') { Stop-Service -Name $s.Name -Force -ErrorAction Stop }"
        )
        ok, out, err = run_powershell(script)
        if ok:
            return OperationResult(OperationState.SUCCESS, f"{self.name} desativado; o estado será verificado.")
        return OperationResult(OperationState.FAILED, f"Falha ao desativar {self.name}: {err or out or 'erro sem detalhes'}")

    def rollback(self, pre_state: Any = None) -> OperationResult:
        if not isinstance(pre_state, dict) or pre_state.get("service") != self.service_name:
            return OperationResult(OperationState.FAILED, "Pré-estado ausente ou inválido para este serviço.")
        mode_map = {"Auto": "Automatic", "Manual": "Manual", "Disabled": "Disabled"}
        start_type = mode_map.get(pre_state.get("start_mode"))
        if not start_type:
            return OperationResult(OperationState.FAILED, "Tipo de inicialização original não suportado.")
        name = _ps_quote(self.service_name)
        action = "Start-Service" if pre_state.get("status", "").lower() == "running" else "Stop-Service"
        script = (
            f"Set-Service -Name {name} -StartupType {start_type} -ErrorAction Stop; "
            f"if ((Get-Service -Name {name} -ErrorAction Stop).Status -eq 'Running') {{ "
            f"if ('{action}' -eq 'Stop-Service') {{ Stop-Service -Name {name} -Force -ErrorAction Stop }} "
            f"}} else {{ if ('{action}' -eq 'Start-Service') {{ Start-Service -Name {name} -ErrorAction Stop }} }}"
        )
        ok, out, err = run_powershell(script)
        if ok:
            return OperationResult(OperationState.SUCCESS, f"Estado anterior de {self.name} restaurado; o resultado será verificado.")
        return OperationResult(OperationState.FAILED, f"Falha ao restaurar {self.name}: {err or out or 'erro sem detalhes'}")

    def matches_pre_state(self, current_state: Any, pre_state: Any) -> bool:
        return (
            self.is_applicable_state(current_state)
            and current_state.get("start_mode") == pre_state.get("start_mode")
            and (current_state.get("status", "").lower() == "running") == (pre_state.get("status", "").lower() == "running")
        )

    def _describe_action(self) -> str:
        return f"Definir {self.service_name} como Disabled e interrompê-lo somente se estiver em execução; estado anterior será salvo."

    def _describe_impact(self) -> str:
        return self.description

    def _describe_rollback(self) -> str:
        return "StartupType e estado Running/Stopped são persistidos em ~/.purify e restaurados pelo Purify."


def get_operations() -> list[Operation]:
    return [
        RemoveAppxPackageOperation("Microsoft.MicrosoftSolitaireCollection", "Microsoft Solitaire", RiskLevel.VERY_LOW, "Coleção de jogos Solitaire; remova apenas se não a utiliza."),
        RemoveAppxPackageOperation("Microsoft.BingWeather", "MS Clima", RiskLevel.VERY_LOW, "Aplicativo de clima do Windows."),
        RemoveAppxPackageOperation("Microsoft.ZuneVideo", "Filmes e TV", RiskLevel.LOW, "Reprodutor de vídeo; confirme que possui uma alternativa."),
        RemoveAppxPackageOperation("Microsoft.SkypeApp", "Skype", RiskLevel.LOW, "Aplicativo Skype legado, quando instalado."),
        RemoveAppxPackageOperation("Microsoft.BingNews", "Microsoft Notícias", RiskLevel.VERY_LOW, "Aplicativo de notícias do Windows."),
        RemoveAppxPackageOperation("Clipchamp.Clipchamp", "Clipchamp", RiskLevel.LOW, "Editor de vídeo Clipchamp; confirme que não o utiliza."),
        RemoveAppxPackageOperation("Microsoft.People", "Pessoas", RiskLevel.MEDIUM, "Aplicativo de contatos; pode ser usado por integrações do Windows."),
        RemoveAppxPackageOperation("Microsoft.MixedReality.Portal", "Portal de Realidade Mista", RiskLevel.MEDIUM, "Portal de realidade mista; aplicabilidade depende da versão e do hardware."),
        RemoveAppxPackageOperation("Microsoft.ZuneMusic", "Media Player legado (Zune Music)", RiskLevel.LOW, "Aplicativo de música legado; confirme que não o utiliza."),
        RemoveAppxPackageOperation("Microsoft.Office.OneNote", "OneNote", RiskLevel.MEDIUM, "Aplicativo OneNote; confirme que não depende dele ou dos dados associados."),
        RemoveAppxPackageOperation("Microsoft.PowerAutomateDesktop", "Power Automate Desktop", RiskLevel.MEDIUM, "Ferramenta de automação; removê-la interrompe fluxos que dependam dela."),
        RemoveAppxPackageOperation("Microsoft.GetHelp", "Obter Ajuda", RiskLevel.MEDIUM, "Aplicativo de suporte da Microsoft."),
        RemoveAppxPackageOperation("Microsoft.Getstarted", "Dicas do Windows", RiskLevel.VERY_LOW, "Aplicativo de dicas e introdução ao Windows."),
        RemoveAppxPackageOperation("Microsoft.WindowsFeedbackHub", "Hub de Comentários", RiskLevel.MEDIUM, "Aplicativo usado para enviar feedback e diagnóstico voluntário."),
        RemoveAppxPackageOperation("Microsoft.YourPhone", "Vincular ao Celular", RiskLevel.MEDIUM, "Integração do Windows com dispositivos móveis."),
        RemoveAppxPackageOperation("MicrosoftTeams", "Microsoft Teams (legado/inbox)", RiskLevel.MEDIUM, "Identidade de pacote usada por algumas versões; pode não corresponder ao novo Teams."),
        RemoveAppxPackageOperation("Microsoft.MicrosoftOfficeHub", "Microsoft 365/Office Hub", RiskLevel.LOW, "Atalho e hub do Microsoft 365/Office."),
        DisableServiceOperation("WSearch", "Windows Search", RiskLevel.MEDIUM, "Desativar pode tornar a pesquisa/indexação menos útil."),
        DisableServiceOperation("DiagTrack", "Experiências e Telemetria (DiagTrack)", RiskLevel.LOW, "Desativa o serviço DiagTrack; pode afetar diagnósticos e gestão do Windows."),
        DisableServiceOperation("dmwappushservice", "WAP Push Message Routing (dmwappushservice)", RiskLevel.MEDIUM, "Serviço de roteamento de mensagens; o impacto depende dos recursos e políticas do dispositivo."),
        DisableServiceOperation("WerSvc", "Relatório de Erros do Windows", RiskLevel.MEDIUM, "Desativar pode limitar diagnóstico e envio de relatórios de falha."),
        DisableServiceOperation("SysMain", "SysMain (Superfetch)", RiskLevel.MEDIUM, "O impacto depende do dispositivo e do padrão de uso; não é uma otimização universal."),
        DisableServiceOperation("wuauserv", "Windows Update", RiskLevel.CRITICAL, "Desativar interrompe atualizações de segurança e pode afetar a Microsoft Store. Não recomendado."),
    ]
