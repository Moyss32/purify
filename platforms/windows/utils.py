from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
import re


def run_powershell(script: str, timeout: int = 120) -> tuple[bool, str, str]:
    """Executa PowerShell sem shell e converte erros PowerShell em falha explícita."""
    executable = shutil.which("powershell") or shutil.which("pwsh")
    if not executable:
        return False, "", "PowerShell não foi encontrado."

    wrapped = (
        "$ErrorActionPreference = 'Stop'; "
        "$ProgressPreference = 'SilentlyContinue'; "
        "try {\n" + script + "\n} catch { "
        "[Console]::Error.WriteLine($_.ToString()); exit 1 }"
    )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", wrapped],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=creationflags,
        )
        return completed.returncode == 0, completed.stdout.strip(), completed.stderr.strip()
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return False, stdout.strip(), stderr.strip() or f"PowerShell excedeu o limite de {timeout} segundos."
    except OSError as exc:
        return False, "", str(exc)


def create_restore_point(description: str = "Purify — antes das alterações") -> tuple[bool, str]:
    """
    Tenta criar e confirmar um ponto por Checkpoint-Computer e, se falhar,
    tenta a chamada CIM direta a SystemRestore.CreateRestorePoint.
    Retorna sucesso somente quando a consulta confirma um novo número de sequência.
    """
    safe_desc = re.sub(r'["\x00-\x1f]', '', description).strip()[:180]
    if not safe_desc:
        safe_desc = "Purify — antes das alterações"
    safe_desc = f"{safe_desc} — {datetime.now().strftime('%Y%m%d-%H%M%S')}"
    quoted = "'" + safe_desc.replace("'", "''") + "'"

    common = (
        "$ErrorActionPreference = 'Stop'; "
        f"$description = {quoted}; "
        "$before = @(Get-ComputerRestorePoint -ErrorAction SilentlyContinue); "
        "$beforeMax = [int64]0; "
        "if ($before.Count -gt 0) { "
        "$beforeMax = [int64](($before | Measure-Object -Property SequenceNumber -Maximum).Maximum) "
        "}; "
    )
    verify = (
        "$points = @(Get-ComputerRestorePoint -ErrorAction Stop); "
        "$created = $points | Where-Object { $_.Description -eq $description -and "
        "([int64]$_.SequenceNumber) -gt $beforeMax } | "
        "Sort-Object -Property SequenceNumber -Descending | Select-Object -First 1; "
        "if ($null -eq $created) { throw 'O Windows não confirmou um novo ponto de restauração.' }; "
        "Write-Output ('PURIFY_RESTORE_OK:' + $created.SequenceNumber)"
    )
    attempts = (
        (
            "Checkpoint-Computer",
            common
            + "Enable-ComputerRestore -Drive $env:SystemDrive -ErrorAction SilentlyContinue; "
            + "Checkpoint-Computer -Description $description -RestorePointType MODIFY_SETTINGS -ErrorAction Stop; "
            + verify,
        ),
        (
            "SystemRestore via CIM",
            common
            + "$result = Invoke-CimMethod -Namespace 'root/default' -ClassName 'SystemRestore' "
            + "-MethodName 'CreateRestorePoint' -Arguments @{ Description = $description; "
            + "RestorePointType = [uint32]12; EventType = [uint32]100 }; "
            + "if ($null -eq $result -or [int]$result.ReturnValue -ne 0) { "
            + "throw ('SystemRestore.CreateRestorePoint retornou ' + $result.ReturnValue) }; "
            + verify,
        ),
    )

    errors: list[str] = []
    for method, script in attempts:
        try:
            ok, out, err = run_powershell(script)
        except Exception as exc:
            ok, out, err = False, "", str(exc)
        match = re.search(r"PURIFY_RESTORE_OK:(\d+)", out or "")
        if ok and match:
            return True, f"Ponto de restauração confirmado pelo método {method} (sequência {match.group(1)})."
        detail = err or out or "o comando não confirmou a criação do ponto"
        errors.append(f"{method}: {detail}")

    return False, "Falha nos dois métodos de criação do ponto de restauração. " + " | ".join(errors)
