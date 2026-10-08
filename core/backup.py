from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BACKUP_FILE = Path.home() / ".purify" / "session_backup.json"


class BackupStoreError(RuntimeError):
    pass


def _read_all(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise BackupStoreError("O arquivo de pré-estado não contém um objeto JSON.")
        return value
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupStoreError(f"Não foi possível ler o pré-estado salvo: {exc}") from exc


def save_pre_state(op_id: str, state: Any, path: Path | str | None = None) -> None:
    """Persiste estado anterior via escrita atômica e permissões restritas no POSIX."""
    target = Path(path) if path else BACKUP_FILE
    try:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(target.parent, 0o700)
        except OSError:
            pass
        all_states = _read_all(target)
        all_states[op_id] = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "state": state,
        }
        fd, temp_name = tempfile.mkstemp(prefix=".purify-", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(all_states, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temp_name, 0o600)
            except OSError:
                pass
            os.replace(temp_name, target)
            try:
                os.chmod(target.parent, 0o700)
            except OSError:
                pass
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
    except (OSError, TypeError, ValueError) as exc:
        raise BackupStoreError(f"Não foi possível salvar o pré-estado: {exc}") from exc


def get_pre_state(op_id: str, path: Path | str | None = None) -> Any | None:
    target = Path(path) if path else BACKUP_FILE
    entry = _read_all(target).get(op_id)
    if not isinstance(entry, dict) or "state" not in entry:
        return None
    return entry["state"]


def clear_pre_state(op_id: str, path: Path | str | None = None) -> None:
    target = Path(path) if path else BACKUP_FILE
    all_states = _read_all(target)
    if op_id not in all_states:
        return
    del all_states[op_id]
    try:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temp_name = tempfile.mkstemp(prefix=".purify-", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(all_states, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temp_name, 0o600)
            except OSError:
                pass
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
    except OSError as exc:
        raise BackupStoreError(f"Não foi possível remover o pré-estado salvo: {exc}") from exc
