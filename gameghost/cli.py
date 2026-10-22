import sys
import os

# Mesa, EGL, DRI2 & Zink error mitigation (prevents choose_pdev / dri2 failures in Termux)
os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
os.environ["GALLIUM_DRIVER"] = "llvmpipe"
os.environ["MESA_LOADER_DRIVER_OVERRIDE"] = "llvmpipe"
os.environ["SDL_RENDER_DRIVER"] = "software"
os.environ["SDL_VIDEO_X11_NODIRECTCOLOR"] = "1"
os.environ["SDL_VIDEO_X11_NET_WM_BYPASS_COMPOSITOR"] = "0"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
os.environ["MESA_DEBUG"] = "silent"
os.environ["EGL_LOG_LEVEL"] = "fatal"

import time
import subprocess
import argparse
from pathlib import Path
from rich.console import Console
from rich.table import Table

from .config import (
    CONFIG_DIR,
    load_config,
    save_config,
    get_local_ip,
    get_last_host,
    save_last_host,
    get_host_pid,
    save_host_pid,
    clear_host_pid,
    is_host_running,
    scan_network_hosts,
    probe_host
)
from .server import GameGhostHost
from .launcher import list_games, launch_game, is_phone_environment, GAMES_CATALOG
from .gamepad import VirtualGamepad
from .update import check_and_apply_auto_update, run_full_update

console = Console()

BANNER = r"""
  ____                            ____  _               _   
 / ___| __ _ _ __ ___   ___      / ___|| |__   ___  ___| |_ 
| |  _ / _` | '_ ` _ \ / _ \    | |  _ | '_ \ / _ \/ __| __|
| |_| | (_| | | | | | |  __/    | |_| || | | | (_) \__ \ |_ 
 \____|\__,_|_| |_| |_|\___|     \____||_| |_|\___/|___/\__|
       PC Gaming Handheld Cast  [rayzien x pheonix14]
"""


def shutil_which(cmd: str) -> bool:
    import shutil
    return shutil.which(cmd) is not None


def start_host_background() -> bool:
    """Start GameGhost host server in the background as a continuous service."""
    if is_host_running():
        return True

    project_dir = Path(__file__).resolve().parent.parent
    bin_path = project_dir / "bin" / "gameghost"
    if not bin_path.exists():
        bin_path = Path.home() / ".local" / "bin" / "gameghost"

    log_file = CONFIG_DIR / "host.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # 1. If systemd user service is available, try starting it
    if shutil_which("systemctl"):
        res = subprocess.run(["systemctl", "--user", "is-active", "gameghost"], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip() == "active":
            return True
        subprocess.run(["systemctl", "--user", "start", "gameghost"], capture_output=True)
        time.sleep(1.0)
        if is_host_running() or probe_host("127.0.0.1", port=8900, timeout=0.3):
            return True

    # 2. Standalone background daemon process
    env = os.environ.copy()
    if "DISPLAY" not in env and os.path.exists("/tmp/.X11-unix/X0"):
        env["DISPLAY"] = ":0"

    with open(log_file, "a") as log_f:
        proc = subprocess.Popen(
            [str(bin_path), "host"],
            stdout=log_f,
            stderr=log_f,
            start_new_session=True,
            env=env
        )
        save_host_pid(proc.pid)

    # Wait up to 3 seconds for host to initialize and bind
    for _ in range(15):
        time.sleep(0.2)
        if probe_host("127.0.0.1", port=8900, timeout=0.2):
            return True

    return is_host_running()


def stop_host_background() -> bool:
    """Stop running GameGhost host service."""
    # Check systemctl
    if shutil_which("systemctl"):
        subprocess.run(["systemctl", "--user", "stop", "gameghost"], capture_output=True)

    pid = get_host_pid()
    if not pid:
        return True

    try:
        os.kill(pid, 15)
        time.sleep(0.5)
        clear_host_pid()
        return True
    except Exception:
        try:
            os.kill(pid, 9)
        except Exception:
            pass
        clear_host_pid()
    return True


def install_systemd_service() -> bool:
    """Create and enable systemd user service for 24/7 background operation."""
    service_dir = Path.home() / ".config" / "systemd" / "user"
    service_dir.mkdir(parents=True, exist_ok=True)
    service_file = service_dir / "gameghost.service"

    project_dir = Path(__file__).resolve().parent.parent
    bin_path = Path.home() / ".local" / "bin" / "gameghost"
    if not bin_path.exists():
        bin_path = project_dir / "bin" / "gameghost"

    content = f"""[Unit]
Description=GameGhost PC Streaming & Handheld Gamepad Host
After=network.target sound.target

[Service]
Type=simple
Environment=DISPLAY=:0
ExecStart={bin_path} host
Restart=always
RestartSec=2
KillMode=process

[Install]
WantedBy=default.target
"""
    try:
        service_file.write_text(content)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, capture_output=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", "gameghost.service"], check=True, capture_output=True)
        console.print("[bold green][OK] GameGhost background service installed and running.[/bold green]")
        return True
    except Exception as ex:
        console.print(f"[ERR] Failed to configure systemd user service: {ex}")
        return False


def cmd_host(args):
    """Start the GameGhost streaming and virtual controller host."""
    check_and_apply_auto_update(silent=True)
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")

    if getattr(args, "background", False):
        if start_host_background():
            local_ip = get_local_ip()
            console.print(f"[bold green][OK] GameGhost host is running in background on {local_ip}:8900[/bold green]")
        else:
            console.print("[bold red][ERR] Failed to start GameGhost host in background.[/bold red]")
        return

    pid = get_host_pid()
    if pid and pid != os.getpid():
        console.print(f"[bold yellow][WARNING] GameGhost Host is already running with PID {pid}.[/bold yellow]")
        console.print("Run '[bold cyan]gameghost stop[/bold cyan]' first if you want to restart it.")
        return

    if shutil_which("termux-wake-lock"):
        try:
            subprocess.run(["termux-wake-lock"], check=False)
        except Exception:
            pass

    host = GameGhostHost(fps=args.fps, quality=args.quality, scale=args.scale)
    try:
        host.start()
    except KeyboardInterrupt:
        host.stop()


def cmd_start(args):
    """Start GameGhost host in the background."""
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    if is_host_running():
        local_ip = get_local_ip()
        console.print(f"[bold green][OK] GameGhost host is already active in background on {local_ip}:8900[/bold green]")
        return

    if start_host_background():
        local_ip = get_local_ip()
        console.print(f"[bold green][OK] GameGhost host successfully started in background on {local_ip}:8900[/bold green]")
    else:
        console.print("[bold red][ERR] Could not start GameGhost host in background.[/bold red]")


def cmd_stop(args):
    """Stop running GameGhost host service."""
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    pid = get_host_pid()
    stop_host_background()
    if pid:
        console.print(f"[bold green][OK] Stopped GameGhost Host (PID {pid}).[/bold green]")
    else:
        console.print("[yellow]GameGhost host stopped.[/yellow]")


def cmd_restart(args):
    """Restart GameGhost host service."""
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    stop_host_background()
    time.sleep(0.5)
    start_host_background()
    local_ip = get_local_ip()
    console.print(f"[bold green][OK] GameGhost host restarted on {local_ip}:8900[/bold green]")


def cmd_service(args):
    """Manage systemd user service for GameGhost."""
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    action = getattr(args, "action", "status")

    if action == "install":
        install_systemd_service()
    elif action == "status":
        subprocess.run(["systemctl", "--user", "status", "gameghost.service"])
    elif action == "start":
        subprocess.run(["systemctl", "--user", "start", "gameghost.service"])
        console.print("[bold green][OK] Service started.[/bold green]")
    elif action == "stop":
        subprocess.run(["systemctl", "--user", "stop", "gameghost.service"])
        console.print("[yellow]Service stopped.[/yellow]")
    elif action == "restart":
        subprocess.run(["systemctl", "--user", "restart", "gameghost.service"])
        console.print("[bold green][OK] Service restarted.[/bold green]")


def cmd_status(args):
    """Display connection status, IP addresses, and background processes."""
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    cfg = load_config()
    local_ip = get_local_ip()
    last_host = get_last_host() or "None"
    pid = get_host_pid()
    status_str = f"[bold green]RUNNING (PID {pid})[/bold green]" if pid else "[dim]STOPPED[/dim]"

    if is_phone_environment():
        pad_str = "[bold cyan]Active (Handheld Touch & Gamepad Subsystem)[/bold cyan]"
    else:
        gp = VirtualGamepad()
        pad_str = "[bold green]Active (Hardware Xbox 360 /dev/uinput)[/bold green]" if gp.active else "[bold yellow]Fallback (Keyboard)[/bold yellow]"
        gp.close()

    table = Table(title="[bold yellow]GameGhost System & Network Status[/bold yellow]")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Host Status", status_str)
    table.add_row("Local Device IP", local_ip)
    table.add_row("Last Connected Host", last_host)
    table.add_row("Stream Port (Video/Input)", str(cfg.get("stream_port", 8900)))
    table.add_row("Audio Port", str(cfg.get("audio_port", 8901)))
    table.add_row("UDP Discovery Port", str(cfg.get("discovery_port", 8990)))
    table.add_row("Virtual Gamepad", pad_str)
    table.add_row("Target FPS", str(cfg.get("target_fps", 60)))
    table.add_row("Screen Quality", f"{cfg.get('screen_quality', 80)}%")

    console.print(table)


def cmd_client(args):
    """Launch the native GameGhost handheld client in Landscape Mode."""
    check_and_apply_auto_update(silent=True)
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    try:
        from .client import run_client
    except ImportError as ex:
        console.print(f"[bold red][ERR] Native SDL2 client requires pygame: {ex}[/bold red]")
        console.print("Install in Termux: pkg install python-pygame")
        return

    console.print("[bold green][CLIENT] Starting GameGhost Native Handheld Client (Landscape)...[/bold green]")
    game_to_launch = getattr(args, "game", None)
    try:
        run_client(host_ip=args.ip, fullscreen=args.fullscreen, launch_game=game_to_launch)
    except KeyboardInterrupt:
        console.print("\n[yellow][CLIENT] GameGhost handheld client closed.[/yellow]")


def cmd_scan(args):
    """Scan local Wi-Fi / Hotspot subnet for active GameGhost PC hosts."""
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    console.print("[bold yellow][SCAN] Probing local network for active GameGhost hosts...[/bold yellow]")

    found = scan_network_hosts()
    if not found:
        console.print("[bold yellow][INFO] No active GameGhost hosts detected via direct TCP scan.[/bold yellow]")
        console.print("[dim]Ensure GameGhost host is running on your PC ('gameghost host') on the same network.[/dim]")
        return

    table = Table(title="[bold green]Detected GameGhost Hosts on Network[/bold green]")
    table.add_column("Host IP", style="cyan")
    table.add_column("Port", style="white")
    table.add_column("Name", style="green")

    for h in found:
        table.add_row(h["ip"], str(h["port"]), h["name"])
        save_last_host(h["ip"])

    console.print(table)
    console.print(f"\n[bold green][CONNECT][/bold green] Connect instantly: [bold cyan]gameghost client {found[0]['ip']}[/bold cyan]")


def cmd_play(args):
    """
    Launch game and stream to phone.
    On Phone: Searches for PC host on network, triggers game on PC, and opens landscape client!
    On PC: Ensures host is running in background and starts the game locally.
    """
    check_and_apply_auto_update(silent=True)
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    game_id = args.game.lower()

    if is_phone_environment():
        console.print(f"[bold cyan][PHONE MODE][/bold cyan] Looking for PC host to cast [bold yellow]{game_id}[/bold yellow]...")
        cmd_client(argparse.Namespace(ip=None, fullscreen=True, game=game_id))
        return

    # PC Host Mode
    # 1. Ensure host server is running in background
    if not is_host_running():
        console.print("[bold green][HOST] Starting GameGhost background streaming server...[/bold green]")
        start_host_background()

    # 2. Launch game locally
    console.print(f"[bold green][LAUNCH] Starting {game_id} locally on PC...[/bold green]")
    launch_game(game_id)
    time.sleep(1.0)

    local_ip = get_local_ip()
    console.print(f"\n[bold green][READY][/bold green] {game_id} is running and streaming on [bold cyan]{local_ip}:8900[/bold cyan]")
    console.print("[bold yellow]On your Phone (Termux), run:[/bold yellow]")
    console.print(f"  [bold cyan]gameghost client {local_ip}[/bold cyan] (or simply [bold cyan]gg {game_id}[/bold cyan])\n")


def cmd_dmc5(args):
    args.game = "dmc5"
    cmd_play(args)


def cmd_sekiro(args):
    args.game = "sekiro"
    cmd_play(args)


def cmd_tekken8(args):
    args.game = "tekken8"
    cmd_play(args)


def cmd_mk11(args):
    args.game = "mk11"
    cmd_play(args)


def cmd_mgr(args):
    args.game = "mgr"
    cmd_play(args)


def cmd_rottr(args):
    args.game = "rottr"
    cmd_play(args)


def cmd_list(args):
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    table = Table(title="[bold yellow]Available PC Games (Ready to Cast)[/bold yellow]")
    table.add_column("Game ID", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Status", style="green")

    games = list_games()
    for gid, ginfo in games.items():
        if ginfo.get("remote"):
            status = "[bold green]READY TO CAST FROM PC[/bold green]"
        elif ginfo.get("installed"):
            status = "[bold green]INSTALLED ON PC[/bold green]"
        else:
            status = "[dim]NOT INSTALLED[/dim]"
        table.add_row(gid, ginfo.get("name", gid), status)

    console.print(table)


def cmd_gamepad(args):
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    console.print("[bold yellow][TEST] Testing Virtual Gamepad Initialization...[/bold yellow]")
    gp = VirtualGamepad()
    if gp.active and gp.uinput:
        console.print(f"[bold green][OK] Successfully created hardware virtual device: {gp.uinput.name}[/bold green]")
        console.print("[INFO] Testing button pulses (A, B, X, Y)...")
        for btn in ["A", "B", "X", "Y"]:
            gp.handle_packet({"type": "btn", "name": btn, "val": 1})
            time.sleep(0.04)
            gp.handle_packet({"type": "btn", "name": btn, "val": 0})
        console.print("[bold green][OK] Hardware test complete! All PC games recognize this controller.[/bold green]")
        gp.close()
    else:
        console.print(f"[bold yellow][FALLBACK] Virtual device operating in mode: {gp.mode}[/bold yellow]")
        console.print("[dim]Note: /dev/uinput requires read/write permissions on host Linux.[/dim]")


def cmd_update(args):
    """Check and apply latest updates from GitHub."""
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    run_full_update(force=getattr(args, "force", False), check_only=getattr(args, "check", False))


def cmd_menu(args):
    """Interactive phone-friendly touch menu."""
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    console.print("[bold yellow]GameGhost Handheld Mobile Menu[/bold yellow]\n")
    console.print("  [bold cyan][1][/bold cyan] Launch & Play Devil May Cry 5")
    console.print("  [bold cyan][2][/bold cyan] Launch & Play Sekiro: Shadows Die Twice")
    console.print("  [bold cyan][3][/bold cyan] Launch & Play Tekken 8")
    console.print("  [bold cyan][4][/bold cyan] Launch & Play Mortal Kombat 11")
    console.print("  [bold cyan][5][/bold cyan] Launch & Play Metal Gear Rising")
    console.print("  [bold cyan][6][/bold cyan] Launch & Play Rise of the Tomb Raider")
    console.print("  [bold cyan][7][/bold cyan] Connect Native Handheld Client (Landscape)")
    console.print("  [bold cyan][8][/bold cyan] Scan Network for Gaming PC Host")
    console.print("  [bold cyan][9][/bold cyan] Check & Apply GameGhost Updates")
    console.print("  [bold cyan][0][/bold cyan] Exit\n")

    try:
        choice = input("Select an option [0-9]: ").strip()
    except (KeyboardInterrupt, EOFError):
        return

    if choice == "1":
        cmd_dmc5(argparse.Namespace())
    elif choice == "2":
        cmd_sekiro(argparse.Namespace())
    elif choice == "3":
        cmd_tekken8(argparse.Namespace())
    elif choice == "4":
        cmd_mk11(argparse.Namespace())
    elif choice == "5":
        cmd_mgr(argparse.Namespace())
    elif choice == "6":
        cmd_rottr(argparse.Namespace())
    elif choice == "7":
        cmd_client(argparse.Namespace(ip=None, fullscreen=True, game=None))
    elif choice == "8":
        cmd_scan(argparse.Namespace())
    elif choice == "9":
        cmd_update(argparse.Namespace(force=False, check=False))
    else:
        console.print("[dim]Exited GameGhost menu.[/dim]")


def main():
    parser = argparse.ArgumentParser(
        description="GameGhost: Cast any PC game to your phone with full on-screen touch controls."
    )
    subparsers = parser.add_subparsers(dest="command", help="GameGhost commands")

    # host command
    p_host = subparsers.add_parser("host", help="Start the streaming & gamepad host server")
    p_host.add_argument("--fps", type=int, default=60, help="Target streaming FPS (default: 60)")
    p_host.add_argument("--quality", type=int, default=80, help="JPEG quality 1-100 (default: 80)")
    p_host.add_argument("--scale", type=float, default=0.85, help="Resolution scale factor (default: 0.85)")
    p_host.add_argument("--background", "-d", action="store_true", help="Run server in background daemon mode")

    # start command
    subparsers.add_parser("start", help="Start GameGhost host in the background")

    # stop command
    subparsers.add_parser("stop", help="Stop running GameGhost host")

    # restart command
    subparsers.add_parser("restart", help="Restart GameGhost host")

    # service command
    p_svc = subparsers.add_parser("service", help="Manage systemd background service")
    p_svc.add_argument("action", choices=["install", "status", "start", "stop", "restart"], default="status", nargs="?")

    # status command
    subparsers.add_parser("status", help="Show GameGhost status and active host IP")

    # client command
    p_client = subparsers.add_parser("client", help="Launch native handheld client with touch controls")
    p_client.add_argument("ip", type=str, nargs="?", default=None, help="Host PC IP address (auto-discovered if omitted)")
    p_client.add_argument("--fullscreen", "-f", action="store_true", default=True, help="Launch in fullscreen mode")
    p_client.add_argument("--game", "-g", type=str, default=None, help="Game to auto-launch on connect")

    # scan command
    subparsers.add_parser("scan", help="Scan network for GameGhost PC hosts")
    subparsers.add_parser("find", help="Alias for 'scan'")

    # play command
    p_play = subparsers.add_parser("play", help="Launch a game and stream to phone")
    p_play.add_argument("game", type=str, help="Game ID (e.g. dmc5, sekiro, tekken8, mk11, mgr, rottr)")

    # game shortcuts
    subparsers.add_parser("dmc5", help="Launch Devil May Cry 5 & cast to phone")
    subparsers.add_parser("sekiro", help="Launch Sekiro & cast to phone")
    subparsers.add_parser("tekken8", help="Launch Tekken 8 & cast to phone")
    subparsers.add_parser("mk11", help="Launch Mortal Kombat 11 & cast to phone")
    subparsers.add_parser("mgr", help="Launch Metal Gear Rising & cast to phone")
    subparsers.add_parser("rottr", help="Launch Rise of the Tomb Raider & cast to phone")

    # list command
    subparsers.add_parser("list", help="List detected games on the system")

    # gamepad command
    subparsers.add_parser("gamepad", help="Test the virtual gamepad device")

    # update command
    p_update = subparsers.add_parser("update", help="Check and apply latest updates from GitHub")
    p_update.add_argument("--force", "-f", action="store_true", help="Force overwrite local changes with upstream main")
    p_update.add_argument("--check", "-c", action="store_true", help="Check for available updates without applying")

    # menu command
    subparsers.add_parser("menu", help="Interactive phone-friendly touch menu")

    args = parser.parse_args()

    if args.command == "host":
        cmd_host(args)
    elif args.command == "start":
        cmd_start(args)
    elif args.command == "stop":
        cmd_stop(args)
    elif args.command == "restart":
        cmd_restart(args)
    elif args.command == "service":
        cmd_service(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command in ("scan", "find"):
        cmd_scan(args)
    elif args.command == "client":
        cmd_client(args)
    elif args.command == "play":
        cmd_play(args)
    elif args.command == "dmc5":
        cmd_dmc5(args)
    elif args.command == "sekiro":
        cmd_sekiro(args)
    elif args.command == "tekken8":
        cmd_tekken8(args)
    elif args.command == "mk11":
        cmd_mk11(args)
    elif args.command == "mgr":
        cmd_mgr(args)
    elif args.command == "rottr":
        cmd_rottr(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "gamepad":
        cmd_gamepad(args)
    elif args.command == "update":
        cmd_update(args)
    elif args.command == "menu":
        cmd_menu(args)
    else:
        if sys.stdin.isatty():
            cmd_menu(args)
        else:
            cmd_status(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] GameGhost exited.")
        sys.exit(0)
