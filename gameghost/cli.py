import sys
import os
import time
import subprocess
import argparse
from pathlib import Path
from rich.console import Console
from rich.table import Table

from .config import load_config, get_local_ip
from .server import GameGhostHost
from .launcher import launch_game, list_games
from .gamepad import VirtualGamepad
from .client import run_client

console = Console()

BANNER = r"""
==================================================================
   ____    _    __  __ _____ ____ _   _  ___  ____ _____ 
  / ___|  / \  |  \/  | ____/ ___| | | |/ _ \/ ___|_   _|
 | | __  / _ \ | |\/| |  _|| |  _| |_| | | | \___ \ | |  
 | |_\ \/ ___ \| |  | | |__| |_| |  _  | |_| |___) || |  
  \____/_/   \_\_|  |_|_____\____|_| |_|\___/|____/ |_|  
==================================================================
   OPEN-SOURCE PC GAME CASTING & HANDHELD TOUCH PORTAL SYSTEM
==================================================================
"""


def check_and_apply_auto_update(silent: bool = True):
    """
    Check GitHub (rayzien/gameghost) for updates and apply them automatically.
    Derived from CPUGhost auto-update architecture.
    """
    project_dir = Path(__file__).resolve().parent.parent
    git_dir = project_dir / ".git"
    if not git_dir.exists():
        if not silent:
            console.print("[INFO] Not a git repository. Skipping update check.")
        return False

    try:
        if not silent:
            console.print("[UPDATE] Checking GitHub (rayzien/gameghost) for updates...")

        res_head = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", "main"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=8.0
        )

        if res_head.returncode == 0 and res_head.stdout:
            remote_hash = res_head.stdout.strip().split()[0]
            local_res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(project_dir),
                capture_output=True,
                text=True
            )
            local_hash = local_res.stdout.strip() if local_res.returncode == 0 else ""

            if remote_hash and local_hash and remote_hash != local_hash:
                console.print("[bold yellow][UPDATE] New version detected on GitHub. Applying update...[/bold yellow]")
                pull_res = subprocess.run(
                    ["git", "pull", "--quiet", "origin", "main"],
                    cwd=str(project_dir),
                    capture_output=True,
                    text=True
                )
                if pull_res.returncode == 0:
                    console.print("[bold green][OK] GameGhost successfully updated to latest version.[/bold green]")
                    return True
                else:
                    if not silent:
                        console.print(f"[ERR] Update pull failed: {pull_res.stderr.strip()}")
            else:
                if not silent:
                    console.print("[bold green][OK] GameGhost is already up to date.[/bold green]")
    except Exception as ex:
        if not silent:
            console.print(f"[ERR] Update check error: {ex}")
    return False


def cmd_update(args):
    """Check and apply latest updates from GitHub."""
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    check_and_apply_auto_update(silent=False)


def cmd_host(args):
    """Start the GameGhost game streaming and virtual controller host."""
    check_and_apply_auto_update(silent=True)
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    host = GameGhostHost(fps=args.fps, quality=args.quality, scale=args.scale)
    try:
        host.start()
    except KeyboardInterrupt:
        host.stop()


def cmd_dmc5(args):
    """Launch Devil May Cry 5 and immediately start the GameGhost portal."""
    check_and_apply_auto_update(silent=True)
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    console.print("[bold red][LAUNCH] Starting Devil May Cry 5...[/bold red]")
    launch_game("dmc5")
    time.sleep(1.5)

    host = GameGhostHost(fps=args.fps or 60, quality=args.quality or 80)
    try:
        host.start()
    except KeyboardInterrupt:
        host.stop()


def cmd_play(args):
    """Launch a specific game from the catalog and start GameGhost."""
    check_and_apply_auto_update(silent=True)
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    game_id = args.game
    console.print(f"[bold green][LAUNCH] Starting {game_id}...[/bold green]")
    launch_game(game_id)
    time.sleep(1.5)

    host = GameGhostHost()
    try:
        host.start()
    except KeyboardInterrupt:
        host.stop()


def cmd_list(args):
    """List detected games and their status."""
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


def cmd_client(args):
    """Launch the native GameGhost handheld client with on-screen touch overlay."""
    check_and_apply_auto_update(silent=True)
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    console.print("[bold green][CLIENT] Starting GameGhost Native Handheld Client...[/bold green]")
    run_client(host_ip=args.ip, fullscreen=args.fullscreen)


def cmd_gamepad(args):
    """Test and verify the hardware virtual gamepad (/dev/uinput)."""
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    console.print("[bold yellow]Testing Virtual Gamepad Initialization...[/bold yellow]")
    gp = VirtualGamepad()
    if gp.active and gp.uinput:
        console.print(f"[bold green][OK] Successfully created hardware virtual device: {gp.uinput.name}[/bold green]")
        console.print("[INFO] Testing button pulses (A, B, X, Y)...")
        for btn in ["A", "B", "X", "Y"]:
            gp.handle_packet({"type": "btn", "name": btn, "val": 1})
            time.sleep(0.05)
            gp.handle_packet({"type": "btn", "name": btn, "val": 0})
        console.print("[bold green][OK] Hardware test complete. All games will recognize this device.[/bold green]")
        gp.close()
    else:
        console.print("[bold red][ERR] Could not create uinput device directly. Ensure /dev/uinput has rw permissions.[/bold red]")


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

    # dmc5 command
    p_dmc5 = subparsers.add_parser("dmc5", help="Launch Devil May Cry 5 & start GameGhost streaming")
    p_dmc5.add_argument("--fps", type=int, default=60, help="Target streaming FPS (default: 60)")
    p_dmc5.add_argument("--quality", type=int, default=80, help="JPEG quality 1-100 (default: 80)")
    p_dmc5.add_argument("--scale", type=float, default=0.85, help="Resolution scale factor (default: 0.85)")

    # play command
    p_play = subparsers.add_parser("play", help="Launch a game by ID and stream to phone")
    p_play.add_argument("game", type=str, help="Game ID (e.g. dmc5, sekiro, tekken8, mk11, mgr)")

    # list command
    subparsers.add_parser("list", help="List detected games on the system")

    # client command
    p_client = subparsers.add_parser("client", help="Launch native handheld client with touch controls")
    p_client.add_argument("ip", type=str, nargs="?", default=None, help="Host PC IP address (auto-discovered if omitted)")
    p_client.add_argument("--fullscreen", "-f", action="store_true", help="Launch in fullscreen mode")

    # update command
    subparsers.add_parser("update", help="Check and apply latest updates from GitHub")

    # gamepad command
    subparsers.add_parser("gamepad", help="Test the virtual gamepad device")

    args = parser.parse_args()

    if args.command == "host":
        cmd_host(args)
    elif args.command == "dmc5":
        cmd_dmc5(args)
    elif args.command == "play":
        cmd_play(args)
    elif args.command == "client":
        cmd_client(args)
    elif args.command == "update":
        cmd_update(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "gamepad":
        cmd_gamepad(args)
    else:
        # Default behavior: run host
        cmd_host(argparse.Namespace(fps=60, quality=80, scale=0.85))


if __name__ == "__main__":
    main()
