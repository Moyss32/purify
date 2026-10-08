from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Sequence


def run_shell(
    command: str | Sequence[str],
    use_sudo: bool = False,
    timeout: int = 120,
) -> tuple[bool, str, str]:
    """Executa sem shell; para GUI, usa pkexec quando a ação precisa de root."""
    args = shlex.split(command) if isinstance(command, str) else [str(part) for part in command]
    if not args:
        return False, "", "Comando vazio."

    if use_sudo and hasattr(os, "geteuid") and os.geteuid() != 0:
        pkexec = shutil.which("pkexec")
        if not pkexec:
            return False, "", "Esta ação exige root, mas pkexec não está instalado ou disponível."
        args = [pkexec, *args]

    try:
        completed = subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return completed.returncode == 0, completed.stdout.strip(), completed.stderr.strip()
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        detail = stderr.strip() or f"O comando excedeu o limite de {timeout} segundos."
        return False, stdout.strip(), detail
    except OSError as exc:
        return False, "", str(exc)
