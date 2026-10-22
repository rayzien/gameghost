import os
import subprocess
import shutil
from pathlib import Path
from typing import Dict, Any, Optional

GAMES_CATALOG = {
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
        "desktop": "/home/zero/Desktop/Sekiro.desktop"
    },
    "tekken8": {
        "id": "tekken8",
        "name": "Tekken 8",
        "desktop": "/home/zero/Desktop/Tekken_8.desktop"
    },
    "mk11": {
        "id": "mk11",
        "name": "Mortal Kombat 11",
        "desktop": "/home/zero/Desktop/Mortal_Kombat_11.desktop"
    },
    "mgr": {
        "id": "mgr",
        "name": "Metal Gear Rising",
        "desktop": "/home/zero/Desktop/Metal_Gear_Rising.desktop"
    }
}


def list_games() -> Dict[str, Dict[str, Any]]:
    """Return available games with their installed status."""
    catalog = {}
    for gid, info in GAMES_CATALOG.items():
        installed = False
        if "exe" in info and os.path.exists(info["exe"]):
            installed = True
        elif "desktop" in info and os.path.exists(info["desktop"]):
            installed = True
        c = info.copy()
        c["installed"] = installed
        catalog[gid] = c
    return catalog


def launch_game(game_id: str = "dmc5") -> Optional[subprocess.Popen]:
    """Launch a game by ID or path."""
    info = GAMES_CATALOG.get(game_id.lower())

    if info and "exe" in info and os.path.exists(info["exe"]):
        exe_path = info["exe"]
        launcher = info.get("launcher", "/home/zero/.local/bin/launch-game")
        if os.path.exists(launcher):
            cmd = [launcher, exe_path]
        else:
            cmd = ["wine", exe_path]

        print(f"[LAUNCHER] Starting {info['name']}...")
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    if info and "desktop" in info and os.path.exists(info["desktop"]):
        print(f"[LAUNCHER] Launching {info['name']} via desktop entry...")
        cmd = ["gtk-launch", Path(info["desktop"]).stem]
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    print(f"[LAUNCHER] Game '{game_id}' not found.")
    return None
