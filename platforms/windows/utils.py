from __future__ import annotations

import shutil
import subprocess


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
