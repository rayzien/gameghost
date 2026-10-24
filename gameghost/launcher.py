import os
import sys
import glob
import shlex
import subprocess
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

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
        "exe": "/media/zero/New Volume1/Mortal Kombat 11/Binaries/Retail/MK11_DX12.exe",
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

GAME_ALIASES: Dict[str, str] = {
    "dmc": "dmc5",
    "dmc5": "dmc5",
    "devil may cry": "dmc5",
    "devil may cry 5": "dmc5",
    "devilmaycry5": "dmc5",
    "sekiro": "sekiro",
    "shadows die twice": "sekiro",
    "tekken": "tekken8",
    "tekken8": "tekken8",
    "tekken 8": "tekken8",
    "polaris": "tekken8",
    "mk": "mk11",
    "mk11": "mk11",
    "mortal kombat": "mk11",
    "mortal kombat 11": "mk11",
    "mortalkombat11": "mk11",
    "mgr": "mgr",
    "metal gear": "mgr",
    "metal gear rising": "mgr",
    "metal gear rising revengeance": "mgr",
    "revengeance": "mgr",
    "rottr": "rottr",
    "tomb raider": "rottr",
    "rise of the tomb raider": "rottr"
}


def parse_desktop_entry(desktop_path: str) -> Tuple[Optional[List[str]], Optional[str]]:
    """Parse Exec= and Path= lines from a .desktop file, handling shell quotes cleanly."""
    cmd = None
    work_dir = None
    try:
        with open(desktop_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.startswith("Exec=") and not cmd:
                    cmd_line = line[5:].strip()
                    parts = shlex.split(cmd_line)
                    cmd = [p for p in parts if not p.startswith("%")]
                elif line.startswith("Path=") and not work_dir:
                    work_dir = line[5:].strip()
    except Exception:
        pass
    return cmd, work_dir


def parse_desktop_exec(desktop_path: str) -> Optional[List[str]]:
    """Backward-compatible helper returning parsed Exec line."""
    cmd, _ = parse_desktop_entry(desktop_path)
    return cmd


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


def is_game_running(game_id_or_info: Any) -> bool:
    """Check if a game's executable or process is currently active."""
    patterns = []
    if isinstance(game_id_or_info, dict):
        info = game_id_or_info
    else:
        normalized_id = GAME_ALIASES.get(str(game_id_or_info).lower().strip(), str(game_id_or_info).lower().strip())
        info = GAMES_CATALOG.get(normalized_id, {})

    if "exe" in info and info["exe"]:
        exe_path = Path(info["exe"])
        patterns.append(exe_path.name.lower())
        patterns.append(exe_path.stem.lower())
    gid = info.get("id", "")
    if gid:
        patterns.append(gid.lower())

    if not patterns:
        return False

    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/cmdline", "rb") as f:
                    cmdline = f.read().decode("utf-8", errors="ignore").lower()
                for p in patterns:
                    if p and p in cmdline:
                        return True
            except (FileNotFoundError, PermissionError):
                continue
    except Exception:
        pass
    return False


def list_games() -> Dict[str, Dict[str, Any]]:
    """Return available games with their installed and active running status."""
    catalog = {}
    on_phone = is_phone_environment()

    for gid, info in GAMES_CATALOG.items():
        c = info.copy()
        if on_phone:
            c["installed"] = True
            c["remote"] = True
            c["running"] = False
        else:
            installed = False
            if "exe" in info and os.path.exists(info["exe"]):
                installed = True
            elif "desktop" in info and os.path.exists(info["desktop"]):
                installed = True
            c["installed"] = installed
            c["remote"] = False
            c["running"] = is_game_running(info)
        catalog[gid] = c
    return catalog


def close_game(game_id: Optional[str] = None) -> bool:
    """Terminate a running game on the host, closing wine/game processes cleanly."""
    killed_any = False
    targets = []

    if game_id:
        normalized_id = GAME_ALIASES.get(game_id.lower().strip(), game_id.lower().strip())
        info = GAMES_CATALOG.get(normalized_id)
        if info:
            targets.append(info)
    else:
        # Close any active running game from catalog
        for info in GAMES_CATALOG.values():
            if is_game_running(info):
                targets.append(info)

    for info in targets:
        game_name = info.get("name", "Game")
        patterns = []
        if "exe" in info and info["exe"]:
            exe_path = Path(info["exe"])
            patterns.append(exe_path.name)
            patterns.append(exe_path.stem)

        for p in patterns:
            try:
                res = subprocess.run(["pkill", "-f", "-9", p], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if res.returncode == 0:
                    killed_any = True
            except Exception:
                pass

        print(f"[LAUNCHER] Terminated {game_name}.")
        log_host(f"Terminated game process for {game_name}")

    # If closing game or all games, also clean up wineserver if no other catalog game is running
    any_other_running = any(is_game_running(g) for g in GAMES_CATALOG.values())
    if not any_other_running:
        try:
            subprocess.run(["wineserver", "-k"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            killed_any = True
        except Exception:
            pass

    # Unmute audio if muted
    try:
        subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

    return killed_any


def launch_game(game_id: str = "dmc5", mute: bool = False) -> Optional[subprocess.Popen]:
    """Launch a game by ID on the PC host with environment propagation and optional test mute."""
    normalized_id = GAME_ALIASES.get(game_id.lower().strip(), game_id.lower().strip())
    info = GAMES_CATALOG.get(normalized_id)
    if not info:
        print(f"[LAUNCHER] Game '{game_id}' not found in catalog.")
        log_host(f"Game launch rejected: '{game_id}' not found in catalog")
        return None

    exe_path = info.get("exe")
    launcher = info.get("launcher", "/home/zero/.local/bin/launch-game")
    desktop = info.get("desktop")

    env = os.environ.copy()
    # Strip any software rasterizer variables that might poison Vulkan / VKD3D / DX12
    for var in ("LIBGL_ALWAYS_SOFTWARE", "GALLIUM_DRIVER", "MESA_LOADER_DRIVER_OVERRIDE", "SDL_RENDER_DRIVER"):
        env.pop(var, None)
    if "DISPLAY" not in env and os.path.exists("/tmp/.X11-unix/X0"):
        env["DISPLAY"] = ":0"
    if "XAUTHORITY" not in env or not os.path.exists(env.get("XAUTHORITY", "")):
        matches = glob.glob(f"/run/user/{os.getuid()}/.mutter-Xwaylandauth*")
        if matches:
            env["XAUTHORITY"] = matches[0]
        elif os.path.exists(os.path.expanduser("~/.Xauthority")):
            env["XAUTHORITY"] = os.path.expanduser("~/.Xauthority")

    # Mute audio during testing to prevent disturbing user
    mute_mode = mute or os.environ.get("GAMEGHOST_MUTE_TEST") == "1"
    if mute_mode:
        try:
            subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"], check=False)
        except Exception:
            pass
        print(f"[LAUNCHER] MUTE ACTIVE: System audio sink muted completely for testing {info['name']}.")
        log_host(f"Mute test mode active for {info['name']}")

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
        parsed_cmd, work_dir = parse_desktop_entry(desktop)
        if parsed_cmd:
            print(f"[LAUNCHER] Launching {info['name']} via parsed desktop Exec...")
            log_host(f"Starting {info['name']} via desktop Exec: {' '.join(parsed_cmd)}")
            try:
                proc = subprocess.Popen(
                    parsed_cmd,
                    cwd=work_dir if (work_dir and os.path.exists(work_dir)) else str(Path.home()),
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
