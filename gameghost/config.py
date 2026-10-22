import os
import socket
import json
from pathlib import Path
from typing import Dict, Any, List

CONFIG_DIR = Path.home() / ".config" / "gameghost"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "node_name": "GameGhost-Host",
    "stream_port": 8900,
    "audio_port": 8901,
    "discovery_port": 8990,
    "target_fps": 60,
    "screen_quality": 80,
    "screen_scale": 0.85,
    "last_host_ip": "",
    "controller_mode": "gamepad",
    "games": {
        "dmc5": {
            "name": "Devil May Cry 5",
            "path": "/media/zero/New Volume1/Devil May Cry 5/DevilMayCry5.exe",
            "launcher": "/home/zero/.local/bin/launch-game"
        }
    }
}


def load_config() -> Dict[str, Any]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r") as f:
            cfg = json.load(f)
            merged = DEFAULT_CONFIG.copy()
            merged.update(cfg)
            return merged
    except Exception:
        return DEFAULT_CONFIG.copy()


def save_config(cfg: Dict[str, Any]):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def get_local_ip() -> str:
    """Find the best local IP address for phone connection."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        if not ip.startswith("127."):
            return ip
    except Exception:
        pass

    return "127.0.0.1"


def get_broadcast_ip(ip: str) -> str:
    """Derive subnet broadcast IP for a given local IP (assumes /24)."""
    parts = ip.split(".")
    if len(parts) == 4 and parts[0] != "127":
        return f"{parts[0]}.{parts[1]}.{parts[2]}.255"
    return "255.255.255.255"


def get_arp_neighbors() -> List[str]:
    """Read ARP cache to find active neighbor IPs on hotspot network."""
    neighbors = []
    try:
        with open("/proc/net/arp", "r") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) >= 4:
                    ip = parts[0]
                    flags = parts[2]
                    if flags != "0x0" and not ip.startswith("127."):
                        neighbors.append(ip)
    except Exception:
        pass
    return neighbors
