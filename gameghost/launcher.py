import os
import sys
import glob
import subprocess
import shutil
from pathlib import Path
from typing import Dict, Any, Optional

from .config import log_host

GAMES_CATALOG: Dict[str, Dict[str, Any]] = {
    "dmc5": {
        "id": "dmc5",
        "name": "Devil May Cry 5",
        "exe": "/media/zero/New Volume1/Devil May Cry 5/DevilMayCry5.exe",
        "launcher": "/home/zero/.local/bin/launch-game",
        "desktop": "/home/zero/Desktop/Devil_May_Cry_5.desktop"
    },
    "sekiro": {
        "id": "sekiro",
        "name": "Sekiro: Shadows Die Twice",
        "exe": "/media/zero/New Volume/Sekiro Shadows Die Twice/sekiro.exe",
        "launcher": "/home/zero/.local/bin/launch-game",
        "desktop": "/home/zero/Desktop/Sekiro.desktop"
    },
    "tekken8": {
        "id": "tekken8",
        "name": "Tekken 8",
        "exe": "/media/zero/New Volume/Games/TEKKEN 8/Polaris/Binaries/Win64/Polaris-Win64-Shipping.exe",
        "launcher": "/home/zero/.local/bin/launch-game",
        "desktop": "/home/zero/Desktop/Tekken_8.desktop"
    },
    "mk11": {
        "id": "mk11",
        "name": "Mortal Kombat 11",
        "exe": "/media/zero/New Volume1/Mortal Kombat 11/Binaries/Retail/MK11.exe",
        "launcher": "/home/zero/.local/bin/launch-game",
        "desktop": "/home/zero/Desktop/Mortal_Kombat_11.desktop"
    },
    "mgr": {
        "id": "mgr",
        "name": "Metal Gear Rising: Revengeance",
        "exe": "/media/zero/New Volume/Games/Metal Gear Rising - Revengeance/METAL GEAR RISING REVENGEANCE.exe",
        "launcher": "/home/zero/.local/bin/launch-game",
        "desktop": "/home/zero/Desktop/Metal_Gear_Rising.desktop"
    },
    "rottr": {
        "id": "rottr",
        "name": "Rise of the Tomb Raider",
        "exe": "/media/zero/New Volume/Games/Rise of the Tomb Raider/ROTTR.exe",
        "launcher": "/home/zero/.local/bin/launch-game",
        "desktop": "/home/zero/Desktop/ROTTR.desktop"
    }
}

def parse_desktop_exec(desktop_path: str) -> Optional[list]:
    """Parse Exec= line from a .desktop file, stripping desktop field codes."""
    try:
        with open(desktop_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.startswith("Exec="):
                    cmd_line = line[5:].strip()
                    parts = cmd_line.split()
                    cleaned = [p for p in parts if not p.startswith("%")]
                    return cleaned if cleaned else None
    except Exception:
        pass
    return None

def is_phone_environment() -> bool:
    """Detect if executing on an Android phone (Termux) or Linux PC host."""
    if "TERMUX_VERSION" in os.environ or os.path.exists("/data/data/com.termux"):
        return True
    if os.path.exists("/system/build.prop"):
        return True
    for info in GAMES_CATALOG.values():
        if os.path.exists(info.get("exe", "")):
            return False
    if not os.path.exists("/dev/uinput"):
        return True
    return False

def list_games() -> Dict[str, Dict[str, Any]]:
    """Return available games with their installed status."""
    catalog = {}
    on_phone = is_phone_environment()

    for gid, info in GAMES_CATALOG.items():
        c = info.copy()
        if on_phone:
            c["installed"] = True
            c["remote"] = True
        else:
            installed = False
            if "exe" in info and os.path.exists(info["exe"]):
                installed = True
            elif "desktop" in info and os.path.exists(info["desktop"]):
                installed = True
            c["installed"] = installed
            c["remote"] = False
        catalog[gid] = c
    return catalog

def launch_game(game_id: str = "dmc5") -> Optional[subprocess.Popen]:
    """Launch a game by ID on the PC host with environment propagation."""
    info = GAMES_CATALOG.get(game_id.lower())
    if not info:
        print(f"[LAUNCHER] Game '{game_id}' not found in catalog.")
        log_host(f"Game launch rejected: '{game_id}' not found in catalog")
        return None

    exe_path = info.get("exe")
    launcher = info.get("launcher", "/home/zero/.local/bin/launch-game")
    desktop = info.get("desktop")

    env = os.environ.copy()
    if "DISPLAY" not in env and os.path.exists("/tmp/.X11-unix/X0"):
        env["DISPLAY"] = ":0"
    if "XAUTHORITY" not in env or not os.path.exists(env.get("XAUTHORITY", "")):
        matches = glob.glob(f"/run/user/{os.getuid()}/.mutter-Xwaylandauth*")
        if matches:
            env["XAUTHORITY"] = matches[0]
        elif os.path.exists(os.path.expanduser("~/.Xauthority")):
            env["XAUTHORITY"] = os.path.expanduser("~/.Xauthority")

    # 1. Direct Executable launch via game launcher or Wine
    if exe_path and os.path.exists(exe_path):
        game_dir = os.path.dirname(exe_path)
        if os.path.exists(launcher):
            cmd = [launcher, exe_path]
        elif shutil.which("gamemoderun") and shutil.which("wine"):
            cmd = ["gamemoderun", "wine", exe_path]
        else:
            cmd = ["wine", exe_path]

        print(f"[LAUNCHER] Starting {info['name']} via {cmd[0]}...")
        log_host(f"Starting {info['name']} ({exe_path}) via {cmd[0]}")
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=game_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=env
            )
            log_host(f"Launched {info['name']} successfully (PID {proc.pid})")
            return proc
        except Exception as ex:
            log_host(f"Failed to launch {info['name']}: {ex}")
            return None

    # 2. Desktop file parser fallback
    if desktop and os.path.exists(desktop):
        parsed_cmd = parse_desktop_exec(desktop)
        if parsed_cmd:
            print(f"[LAUNCHER] Launching {info['name']} via parsed desktop Exec...")
            log_host(f"Starting {info['name']} via desktop Exec: {' '.join(parsed_cmd)}")
            try:
                proc = subprocess.Popen(
                    parsed_cmd,
                    cwd=str(Path.home()),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    env=env
                )
                log_host(f"Launched {info['name']} via desktop entry (PID {proc.pid})")
                return proc
            except Exception as ex:
                log_host(f"Desktop launch failed for {info['name']}: {ex}")

        # Fallback to gio / gtk-launch
        if shutil.which("gio"):
            cmd = ["gio", "launch", desktop]
        else:
            cmd = ["gtk-launch", Path(desktop).stem]
        print(f"[LAUNCHER] Launching {info['name']} via system desktop launcher...")
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, env=env)
            log_host(f"Launched {info['name']} via {cmd[0]} (PID {proc.pid})")
            return proc
        except Exception as ex:
            log_host(f"System desktop launch failed for {info['name']}: {ex}")
            return None

    print(f"[LAUNCHER] Executable for '{game_id}' not found at '{exe_path}'.")
    log_host(f"Executable for '{game_id}' not found at '{exe_path}'")
    return None
