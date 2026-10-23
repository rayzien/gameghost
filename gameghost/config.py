import os
import sys
import socket
import json
import re
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor

CONFIG_DIR = Path.home() / ".config" / "gameghost"
CONFIG_FILE = CONFIG_DIR / "config.json"
LAST_HOST_FILE = CONFIG_DIR / "last_host.txt"
PID_FILE = CONFIG_DIR / "host.pid"

QUALITY_PRESETS: Dict[str, Dict[str, Any]] = {
    "720p": {
        "id": "720p",
        "name": "720p Fast (Performance)",
        "scale": 0.67,
        "quality": 70,
        "fps": 60,
        "min_fps": 45,
        "max_fps": 60,
    },
    "1080p": {
        "id": "1080p",
        "name": "1080p FHD (Balanced / Standard)",
        "scale": 0.85,
        "quality": 80,
        "fps": 60,
        "min_fps": 50,
        "max_fps": 90,
    },
    "1440p": {
        "id": "1440p",
        "name": "1440p 2K (Ultra HD)",
        "scale": 1.0,
        "quality": 88,
        "fps": 90,
        "min_fps": 60,
        "max_fps": 120,
    },
    "4k": {
        "id": "4k",
        "name": "2160p 4K (Extreme Cinema)",
        "scale": 1.0,
        "quality": 95,
        "fps": 120,
        "min_fps": 60,
        "max_fps": 144,
    },
}

THEME_PRESETS: Dict[str, Dict[str, Any]] = {
    "cyan": {
        "id": "cyan",
        "name": "Cyber Cyan",
        "border": (0, 210, 255),
        "accent": (0, 230, 255),
        "hud": (0, 230, 255),
        "stick_base": (30, 45, 65, 130),
        "stick_knob": (0, 210, 255, 190),
    },
    "xbox": {
        "id": "xbox",
        "name": "Xbox Green",
        "border": (16, 124, 65),
        "accent": (46, 204, 113),
        "hud": (46, 204, 113),
        "stick_base": (25, 45, 30, 130),
        "stick_knob": (46, 204, 113, 190),
    },
    "playstation": {
        "id": "playstation",
        "name": "PlayStation Blue",
        "border": (0, 106, 255),
        "accent": (52, 152, 219),
        "hud": (52, 152, 219),
        "stick_base": (20, 35, 65, 130),
        "stick_knob": (0, 140, 255, 190),
    },
    "red": {
        "id": "red",
        "name": "DMC Blood Red",
        "border": (255, 46, 99),
        "accent": (231, 76, 60),
        "hud": (255, 80, 110),
        "stick_base": (55, 20, 25, 130),
        "stick_knob": (255, 46, 99, 190),
    },
    "dark": {
        "id": "dark",
        "name": "Stealth Dark",
        "border": (100, 110, 125),
        "accent": (180, 190, 205),
        "hud": (200, 210, 220),
        "stick_base": (20, 22, 28, 110),
        "stick_knob": (140, 150, 165, 170),
    },
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "node_name": "GameGhost-Host",
    "stream_port": 8900,
    "audio_port": 8901,
    "discovery_port": 8990,
    "preset": "1080p",
    "target_fps": 60,
    "min_fps": 45,
    "max_fps": 120,
    "auto_fps": True,
    "screen_quality": 80,
    "screen_scale": 0.85,
    "controller_theme": "xbox",  # 'xbox' or 'playstation'
    "overlay_theme": "cyan",     # 'cyan', 'xbox', 'playstation', 'red', 'dark'
    "overlay_visibility": "full", # 'full', 'minimal', 'hidden'
    "overlay_opacity": 0.65,
    "border_glow": True,
    "last_host_ip": "",
    "controller_mode": "gamepad",
    "games": {
        "dmc5": {
            "name": "Devil May Cry 5",
            "path": "/media/zero/New Volume1/Devil May Cry 5/DevilMayCry5.exe",
            "launcher": "/home/zero/.local/bin/launch-game"
        },
        "sekiro": {
            "name": "Sekiro: Shadows Die Twice",
            "desktop": "/home/zero/Desktop/Sekiro.desktop"
        },
        "tekken8": {
            "name": "Tekken 8",
            "desktop": "/home/zero/Desktop/Tekken_8.desktop"
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


def get_last_host() -> Optional[str]:
    """Retrieve the last successfully connected PC host IP."""
    try:
        if LAST_HOST_FILE.exists():
            ip = LAST_HOST_FILE.read_text().strip()
            if ip:
                return ip
    except Exception:
        pass
    return None


def save_last_host(ip: str):
    """Save the connected PC host IP for quick reconnects."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        LAST_HOST_FILE.write_text(ip.strip())
    except Exception:
        pass


def get_host_pid() -> Optional[int]:
    """Return running host PID if active."""
    try:
        if PID_FILE.exists():
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            return pid
    except Exception:
        clear_host_pid()
    return None


def save_host_pid(pid: int):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        PID_FILE.write_text(str(pid))
    except Exception:
        pass


def clear_host_pid():
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except Exception:
        pass


def is_host_running() -> bool:
    pid = get_host_pid()
    if pid is not None and pid != os.getpid():
        return True
    return False


def get_local_ip() -> str:
    """
    Find the best local IP address for phone connection.
    Prioritizes real LAN interfaces (swlan0, wlan0, eth0, en0)
    and excludes loopbacks, virtual VPN interfaces (tun, tap, rmnet).
    """
    # 1. Try ifconfig parsing for physical / Wi-Fi / Hotspot interfaces
    try:
        output = subprocess.check_output(["ifconfig"], stderr=subprocess.DEVNULL).decode("utf-8")
        candidates = []
        for block in output.split("\n\n"):
            lines = block.strip().split("\n")
            if not lines or not lines[0]:
                continue
            iface = lines[0].split(":")[0].strip()
            if iface in ("lo", "tun0") or iface.startswith("tun") or iface.startswith("rmnet") or iface.startswith("dummy"):
                continue
            m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", block)
            if m:
                ip = m.group(1)
                if not ip.startswith("127.") and not ip.startswith("169.254."):
                    if "wlan" in iface or "swlan" in iface or "eth" in iface:
                        return ip
                    candidates.append(ip)
        if candidates:
            return candidates[0]
    except Exception:
        pass

    # 2. Try socket UDP connect technique
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if not ip.startswith("127."):
            return ip
    except Exception:
        pass

    # 3. Hostname fallback
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


def probe_host(ip: str, port: int = 8900, timeout: float = 0.3) -> Optional[Dict[str, Any]]:
    """Probe an IP to verify if a GameGhost streaming server is active via TCP port check."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        res = s.connect_ex((ip, port))
        s.close()
        if res == 0:
            return {
                "ip": ip,
                "port": port,
                "name": "GameGhost Host"
            }
    except Exception:
        pass
    return None


def scan_network_hosts(port: int = 8900, timeout: float = 0.3) -> List[Dict[str, Any]]:
    """Scan local network and common hotspot gateways for active GameGhost hosts."""
    found: List[Dict[str, Any]] = []
    candidates = set()

    candidates.add("127.0.0.1")
    last = get_last_host()
    if last:
        candidates.add(last)

    candidates.add("192.168.43.1")
    candidates.add("192.168.1.1")
    candidates.add("192.168.0.1")

    # Add ARP neighbors
    for nip in get_arp_neighbors():
        candidates.add(nip)

    local_ip = get_local_ip()
    if local_ip and not local_ip.startswith("127."):
        candidates.add(local_ip)
        parts = local_ip.split(".")
        if len(parts) == 4:
            base = f"{parts[0]}.{parts[1]}.{parts[2]}."
            curr_host = int(parts[3])
            for offset in range(-20, 21):
                h = curr_host + offset
                if 1 <= h <= 254:
                    candidates.add(f"{base}{h}")
            for h in [1, 2, 3, 4, 10, 20, 50, 73, 100, 101, 102, 110, 150, 200]:
                candidates.add(f"{base}{h}")

    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = [executor.submit(probe_host, ip, port, timeout) for ip in candidates]
        for f in futures:
            res = f.result()
            if res:
                found.append(res)

    return found
