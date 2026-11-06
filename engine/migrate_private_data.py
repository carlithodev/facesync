"""Move legacy FaceSync secrets out of the source tree.

Safe to rerun: existing destination files are never overwritten.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from core.app_paths import private_config_dir
from core.path_policy import safe_account_id
from core.private_store import PREFIX, protect_text


ENGINE_DIR = Path(__file__).resolve().parent


def _move_file(source: Path, destination: Path, *, move: bool) -> str:
    if not source.is_file():
        return "missing"
    if destination.exists():
        return "kept-existing"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if move:
        shutil.move(str(source), str(destination))
    else:
        shutil.copy2(source, destination)
    try:
        os.chmod(destination, 0o600)
    except OSError:
        pass
    return "moved" if move else "copied"


def migrate(*, move: bool = False) -> dict:
    config_dir = private_config_dir()
    users_dir = config_dir.parent / "usuarios"
    encrypted_cache = 0
    cache_dir = config_dir.parent / "cache" / "embeddings"
    if cache_dir.is_dir():
        for cache_file in cache_dir.glob("*.json"):
            try:
                content = cache_file.read_text(encoding="utf-8")
                if content.startswith(PREFIX):
                    continue
                tmp = cache_file.with_suffix(".json.tmp")
                tmp.write_text(protect_text(content), encoding="utf-8")
                os.replace(tmp, cache_file)
                encrypted_cache += 1
            except Exception:
                continue

    results = {
        ".env": _move_file(ENGINE_DIR / ".env", config_dir / ".env", move=move),
        "client_secret.json": _move_file(
            ENGINE_DIR / "client_secret.json", config_dir / "client_secret.json", move=move
        ),
        "accounts": {},
        "embedding_cache_encrypted": encrypted_cache,
    }

    legacy_users = ENGINE_DIR / "usuarios"
    if legacy_users.is_dir():
        users_dir.mkdir(parents=True, exist_ok=True)
        for source in legacy_users.iterdir():
            if not source.is_dir():
                continue
            try:
                key = safe_account_id(source.name)
            except ValueError:
                results["accounts"][source.name] = "invalid-name"
                continue
            destination = users_dir / key
            if destination.exists():
                results["accounts"][key] = "kept-existing"
                continue
            if move:
                shutil.move(str(source), str(destination))
                results["accounts"][key] = "moved"
            else:
                shutil.copytree(source, destination)
                results["accounts"][key] = "copied"
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--move", action="store_true", help="remove legacy copies after migration")
    args = parser.parse_args()
    print(migrate(move=args.move))
