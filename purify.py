#!/usr/bin/env python3
import sys
import os


def relaunch_as_administrator():
    """Solicita elevação UAC no Windows e informa se o processo atual deve sair."""
    if os.name != "nt":
        return False
    import ctypes
    import subprocess

    if ctypes.windll.shell32.IsUserAnAdmin():
        return False
    if getattr(sys, "frozen", False):
        executable = sys.executable
        args = sys.argv[1:]
    else:
        executable = sys.executable
        args = sys.argv
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", executable, subprocess.list2cmdline(args), None, 1
    )
    if result <= 32:
        raise OSError(f"A solicitação UAC foi recusada ou falhou (código {result}).")
    return True

def main():
    try:
        if relaunch_as_administrator():
            return
    except Exception as exc:
        print(f"Não foi possível iniciar como administrador: {exc}", file=sys.stderr)
        raise SystemExit(1)
    
    # Try to import GUI dependencies
    try:
        import tkinter
    except ImportError:
        print("Erro: Tkinter não está instalado.")
        print("No Debian/Ubuntu, tente instalar o pacote python3-tk.")
        raise SystemExit(1)

    from gui.app import run_gui
    run_gui()

if __name__ == "__main__":
    main()
