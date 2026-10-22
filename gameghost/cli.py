import sys
import os
import time
import subprocess
import argparse
from pathlib import Path
from rich.console import Console
from rich.table import Table

from .config import (
    load_config,
    save_config,
    get_local_ip,
    get_last_host,
    save_last_host,
    get_host_pid,
    clear_host_pid,
    is_host_running,
    scan_network_hosts,
    probe_host
)
from .server import GameGhostHost
from .launcher import list_games, launch_game
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


def cmd_host(args):
    """Start the GameGhost game streaming and virtual controller host."""
    check_and_apply_auto_update(silent=True)
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    if is_host_running():
        pid = get_host_pid()
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


def cmd_stop(args):
    """Stop running GameGhost host service."""
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    pid = get_host_pid()
    if not pid:
        console.print("[yellow]No local GameGhost host process currently running.[/yellow]")
        return

    try:
        os.kill(pid, 15)
        time.sleep(0.5)
        clear_host_pid()
        console.print(f"[bold green][OK] Successfully stopped GameGhost Host (PID {pid}).[/bold green]")
    except Exception as ex:
        console.print(f"[red]Error stopping host (PID {pid}): {ex}[/red]")
        clear_host_pid()


def cmd_status(args):
    """Display connection status, IP addresses, and background processes."""
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    cfg = load_config()
    local_ip = get_local_ip()
    last_host = get_last_host() or "None"
    pid = get_host_pid()
    status_str = f"[bold green]RUNNING (PID {pid})[/bold green]" if pid else "[dim]STOPPED[/dim]"

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
    """Launch the native GameGhost handheld client with on-screen touch overlay."""
    check_and_apply_auto_update(silent=True)
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    try:
        from .client import run_client
    except ImportError as ex:
        console.print(f"[bold red][ERR] Native SDL2 client requires pygame: {ex}[/bold red]")
        console.print("Please install pygame via: pip install pygame-ce (or pkg install python-pygame in Termux)")
        return

    console.print("[bold green][CLIENT] Starting GameGhost Native Handheld Client...[/bold green]")
    run_client(host_ip=args.ip, fullscreen=args.fullscreen)


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
    """Launch a game locally and start the streaming host if not active."""
    check_and_apply_auto_update(silent=True)
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    game_id = args.game.lower()

    console.print(f"[bold green][LAUNCH] Starting {game_id} locally...[/bold green]")
    launch_game(game_id)
    time.sleep(1.2)

    if not is_host_running():
        console.print("[bold green][HOST] Starting GameGhost Host Server for streaming...[/bold green]")
        host = GameGhostHost()
        try:
            host.start()
        except KeyboardInterrupt:
            host.stop()
    else:
        console.print("[bold green][OK] GameGhost Host Server is already running.[/bold green]")


def cmd_dmc5(args):
    args.game = "dmc5"
    cmd_play(args)


def cmd_sekiro(args):
    args.game = "sekiro"
    cmd_play(args)


def cmd_tekken8(args):
    args.game = "tekken8"
    cmd_play(args)


def cmd_list(args):
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    table = Table(title="[bold yellow]Detected Games on System[/bold yellow]")
    table.add_column("Game ID", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Installed", style="green")

    games = list_games()
    for gid, ginfo in games.items():
        status = "[bold green]YES[/bold green]" if ginfo.get("installed") else "[dim]NO[/dim]"
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
    console.print("  [bold cyan][1][/bold cyan] Launch Native SDL2 Touch Client")
    console.print("  [bold cyan][2][/bold cyan] Scan Network for Gaming PC Host")
    console.print("  [bold cyan][3][/bold cyan] Launch & Play Devil May Cry 5")
    console.print("  [bold cyan][4][/bold cyan] Launch & Play Sekiro")
    console.print("  [bold cyan][5][/bold cyan] Launch & Play Tekken 8")
    console.print("  [bold cyan][6][/bold cyan] Start GameGhost Host Server")
    console.print("  [bold cyan][7][/bold cyan] Stop GameGhost Host Server")
    console.print("  [bold cyan][8][/bold cyan] View Status & Configuration")
    console.print("  [bold cyan][9][/bold cyan] Check & Apply GameGhost Updates")
    console.print("  [bold cyan][0][/bold cyan] Exit\n")

    try:
        choice = input("Select an option [0-9]: ").strip()
    except (KeyboardInterrupt, EOFError):
        return

    if choice == "1":
        cmd_client(argparse.Namespace(ip=None, fullscreen=False))
    elif choice == "2":
        cmd_scan(argparse.Namespace())
    elif choice == "3":
        cmd_dmc5(argparse.Namespace())
    elif choice == "4":
        cmd_sekiro(argparse.Namespace())
    elif choice == "5":
        cmd_tekken8(argparse.Namespace())
    elif choice == "6":
        cmd_host(argparse.Namespace(fps=60, quality=80, scale=0.85))
    elif choice == "7":
        cmd_stop(argparse.Namespace())
    elif choice == "8":
        cmd_status(argparse.Namespace())
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

    # stop command
    subparsers.add_parser("stop", help="Stop running GameGhost host")

    # status command
    subparsers.add_parser("status", help="Show GameGhost status and active host IP")

    # client command
    p_client = subparsers.add_parser("client", help="Launch native handheld client with touch controls")
    p_client.add_argument("ip", type=str, nargs="?", default=None, help="Host PC IP address (auto-discovered if omitted)")
    p_client.add_argument("--fullscreen", "-f", action="store_true", help="Launch in fullscreen mode")

    # scan command
    subparsers.add_parser("scan", help="Scan network for GameGhost PC hosts")
    subparsers.add_parser("find", help="Alias for 'scan'")

    # play command
    p_play = subparsers.add_parser("play", help="Launch a game and stream to phone")
    p_play.add_argument("game", type=str, help="Game ID (e.g. dmc5, sekiro, tekken8)")

    # dmc5 command
    subparsers.add_parser("dmc5", help="Launch Devil May Cry 5 & open stream")

    # sekiro command
    subparsers.add_parser("sekiro", help="Launch Sekiro & open stream")

    # tekken8 command
    subparsers.add_parser("tekken8", help="Launch Tekken 8 & open stream")

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
    elif args.command == "stop":
        cmd_stop(args)
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
    main()
