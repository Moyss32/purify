from __future__ import annotations

import os
import platform


def check_admin_windows() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _linux_os_release() -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        with open("/etc/os-release", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                data[key] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return data


def get_os_info() -> dict[str, object]:
    os_name = platform.system().lower()
    if os_name == "windows":
        return {
            "platform": "windows",
            "release": platform.release(),
            "version": platform.version(),
            "is_admin": check_admin_windows(),
        }
    if os_name == "linux":
        release = _linux_os_release()
        ids = {release.get("ID", "").lower()}
        ids.update(part.lower() for part in release.get("ID_LIKE", "").split())
        supported_ids = {"debian", "ubuntu", "linuxmint", "pop"}
        is_debian_family = bool(ids & supported_ids)
        return {
            "platform": "debian" if is_debian_family else "linux",
            "distribution_id": release.get("ID", "unknown"),
            "distribution_name": release.get("PRETTY_NAME", "Linux"),
            "distribution_version": release.get("VERSION_ID", "unknown"),
            "release": platform.release(),
            "is_admin": os.geteuid() == 0 if hasattr(os, "geteuid") else False,
        }
    return {"platform": "unknown", "release": platform.release(), "is_admin": False}
