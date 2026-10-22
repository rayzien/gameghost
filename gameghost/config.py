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

DEFAULT_CONFIG: Dict[str, Any] = {
    "node_name": "GameGhost-Host",
    "http_port": 8899,
    "stream_port": 8900,
    "audio_port": 8901,
    "target_fps": 60,
    "screen_quality": 80,
    "screen_scale": 0.85,
    "touch_vibration": True,
    "controller_mode": "gamepad", # 'gamepad' (Xbox 360 virtual device) or 'keyboard'
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
    return get_host_pid() is not None


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


def probe_host(ip: str, port: int = 8899, timeout: float = 0.3) -> Optional[Dict[str, Any]]:
    """Probe an IP to verify if a GameGhost server is active."""
    import urllib.request
    url = f"http://{ip}:{port}/api/info"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GameGhost-Scanner"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                return {
                    "ip": ip,
                    "port": port,
                    "url": f"http://{ip}:{port}",
                    "name": data.get("name", "GameGhost Host"),
                    "fps": data.get("fps", 0),
                    "clients": data.get("connected_clients", 0)
                }
    except Exception:
        pass
    return None


def scan_network_hosts(port: int = 8899, timeout: float = 0.3) -> List[Dict[str, Any]]:
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
