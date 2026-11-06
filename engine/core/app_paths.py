from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterable, Optional


APP_DATA_DIR_NAME = "FaceSync"
APP_DATA_SUBDIRS = ("sessions", "logs", "cache", "context", "temp")


def default_app_data_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data).expanduser() / APP_DATA_DIR_NAME
    return Path.home().expanduser() / ".facesync"


def private_config_dir() -> Path:
    return default_app_data_root() / "config"


def private_env_path() -> Path:
    return private_config_dir() / ".env"


def ensure_app_data_root(root: Optional[str | Path] = None) -> Path:
    candidates = [Path(root).expanduser()] if root else [
        default_app_data_root(),
        Path.home().expanduser() / ".facesync",
        Path(tempfile.gettempdir()) / APP_DATA_DIR_NAME,
    ]
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            app_root = candidate.resolve(strict=False)
            app_root.mkdir(parents=True, exist_ok=True)
            for subdir in APP_DATA_SUBDIRS:
                (app_root / subdir).mkdir(parents=True, exist_ok=True)
            return app_root
        except Exception as exc:
            last_error = exc
            if root:
                break
    if last_error:
        raise last_error
    raise RuntimeError("No se pudo resolver app_data_root.")


def path_is_inside(root: str | Path, value: str | Path) -> bool:
    try:
        Path(value).expanduser().resolve(strict=False).relative_to(
            Path(root).expanduser().resolve(strict=False)
        )
        return True
    except Exception:
        return False


def relative_to_root(root: str | Path, value: str | Path) -> str:
    try:
        return str(
            Path(value).expanduser().resolve(strict=False).relative_to(
                Path(root).expanduser().resolve(strict=False)
            )
        ).replace("\\", "/")
    except Exception:
        return str(value).replace("\\", "/")


def filter_internal_names(names: Iterable[str]) -> list[str]:
    return [name for name in names if name not in {"FaceSync_Workspace"}]
