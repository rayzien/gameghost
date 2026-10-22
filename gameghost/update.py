"""
GameGhost High-Performance Auto-Update Engine.
Checks and upgrades GameGhost to the latest GitHub release (rayzien/gameghost).
Derived from CPUGhost auto-update architecture.
Supports force updates, automatic environment healing, launcher relinking,
and background update detection. Strict zero emojis.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple
from rich.console import Console

console = Console()
GITHUB_REPO = "https://github.com/rayzien/gameghost.git"


def get_current_version() -> str:
    try:
        from . import __version__
        return __version__
    except Exception:
        return "1.3.0"


def get_latest_remote_info(project_dir: Path) -> Tuple[Optional[str], Optional[str]]:
    """
    Query GitHub for latest release tags and commit hash on main branch.
    Returns (latest_tag, latest_commit_hash).
    """
    latest_tag = None
    latest_commit = None

    try:
        res_tags = subprocess.run(
            ["git", "ls-remote", "--tags", "origin"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=8.0
        )
        if res_tags.returncode == 0 and res_tags.stdout:
            tags = []
            for line in res_tags.stdout.splitlines():
                if "refs/tags/" in line and not line.endswith("^{}"):
                    t = line.split("refs/tags/")[-1].strip()
                    tags.append(t)
            if tags:
                latest_tag = tags[-1]
    except Exception:
        pass

    try:
        res_heads = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", "main"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=8.0
        )
        if res_heads.returncode == 0 and res_heads.stdout:
            parts = res_heads.stdout.strip().split()
            if parts:
                latest_commit = parts[0]
    except Exception:
        pass

    return latest_tag, latest_commit


def run_full_update(force: bool = False, check_only: bool = False) -> bool:
    """
    Execute upgrade from GitHub repository (rayzien/gameghost).
    Handles git pull, rebase recovery, dependencies reinstallation, and binary relinking.
    """
    project_dir = Path(__file__).resolve().parent.parent
    git_dir = project_dir / ".git"

    current_ver = get_current_version()
    console.print(f"[UPDATE] Current GameGhost version: v{current_ver}")
    console.print("[UPDATE] Querying GitHub repository (rayzien/gameghost)...")

    if not git_dir.exists():
        console.print(f"[ERR] GameGhost is not installed as a git repository at: {project_dir}")
        return False

    latest_tag, latest_commit = get_latest_remote_info(project_dir)
    if latest_tag:
        console.print(f"[INFO] Latest GitHub release tag: {latest_tag}")

    is_behind = False
    try:
        subprocess.run(["git", "fetch", "origin", "main", "--tags"], cwd=str(project_dir), capture_output=True, timeout=12.0)
        diff_res = subprocess.check_output(["git", "rev-list", "HEAD..origin/main", "--count"], cwd=str(project_dir), text=True).strip()
        is_behind = int(diff_res or 0) > 0
    except Exception:
        pass

    if not is_behind and not force:
        console.print("[OK] GameGhost is already up to date with origin/main.")
        return True

    if check_only:
        console.print("[INFO] Update available on GitHub! Run 'gameghost update' to apply.")
        return True

    console.print("[UPDATE] Applying update from GitHub origin/main...")

    try:
        if force:
            subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=str(project_dir), check=True, capture_output=True)
        else:
            res = subprocess.run(["git", "pull", "--rebase", "origin", "main"], cwd=str(project_dir), capture_output=True, text=True)
            if res.returncode != 0:
                console.print("[WARN] Rebase conflict detected. Auto-healing to origin/main...")
                subprocess.run(["git", "rebase", "--abort"], cwd=str(project_dir), capture_output=True)
                subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=str(project_dir), check=True, capture_output=True)

        console.print("[OK] Git codebase updated.")

        # Update environment dependencies
        console.print("[UPDATE] Verifying Python environment packages...")
        deps = ["websockets", "rich", "pillow", "mss"]
        venv_python = project_dir / ".venv" / "bin" / "python"
        shared_venv_python = Path("/home/zero/Desktop/cpughost/.venv/bin/python")

        target_python = None
        if venv_python.exists():
            target_python = venv_python
        elif shared_venv_python.exists():
            target_python = shared_venv_python

        if target_python and shutil.which("uv"):
            subprocess.run(["uv", "pip", "install", "--python", str(target_python)] + deps, capture_output=True)
        elif target_python:
            pip_bin = target_python.parent / "pip"
            if pip_bin.exists():
                subprocess.run([str(pip_bin), "install", "-q"] + deps, capture_output=True)
        else:
            if shutil.which("pip"):
                subprocess.run(["pip", "install", "-q"] + deps, capture_output=True)

        # Relink launcher executable
        bin_source = project_dir / "bin" / "gameghost"
        bin_dest = Path.home() / ".local" / "bin" / "gameghost"
        alias_dest = Path.home() / ".local" / "bin" / "gg"

        if bin_source.exists():
            bin_dest.parent.mkdir(parents=True, exist_ok=True)
            bin_dest.unlink(missing_ok=True)
            bin_dest.symlink_to(bin_source)
            alias_dest.unlink(missing_ok=True)
            alias_dest.symlink_to(bin_source)

        # Termux bin link if applicable
        termux_bin = Path.home() / "bin"
        if termux_bin.exists():
            (termux_bin / "gameghost").unlink(missing_ok=True)
            (termux_bin / "gameghost").symlink_to(bin_source)
            (termux_bin / "gg").unlink(missing_ok=True)
            (termux_bin / "gg").symlink_to(bin_source)

        new_ver = get_current_version()
        console.print(f"[OK] GameGhost successfully upgraded to v{new_ver}!")
        return True

    except Exception as e:
        console.print(f"[ERR] Failed during update: {e}")
        return False


def check_and_apply_auto_update(silent: bool = True):
    """
    Check GitHub for updates automatically.
    Applies updates if a newer commit is found on main.
    """
    project_dir = Path(__file__).resolve().parent.parent
    if not (project_dir / ".git").exists():
        return
    try:
        res = subprocess.run(
            ["timeout", "4", "git", "rev-list", "HEAD..origin/main", "--count"],
            cwd=str(project_dir),
            capture_output=True,
            text=True
        )
        if res.returncode == 0 and int(res.stdout.strip() or 0) > 0:
            console.print("[UPDATE] Newer release detected on GitHub. Applying update...")
            run_full_update(force=False, check_only=False)
    except Exception:
        pass
