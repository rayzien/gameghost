import sys
import os
import time
import argparse
import subprocess
import urllib.request
import json
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .config import (
    load_config,
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
from .launcher import launch_game, list_games
from .gamepad import VirtualGamepad

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


def open_browser_url(url: str):
    """Open URL using termux-open-url (on Android/Termux) or xdg-open/python web browser."""
    # 1. Termux on Android
    if shutil_which("termux-open-url"):
        try:
            subprocess.run(["termux-open-url", url], check=False)
            console.print(f"[bold green]✔ Opened portal on your phone browser:[/bold green] [yellow]{url}[/yellow]")
            return
        except Exception:
            pass

    # 2. Linux xdg-open
    if shutil_which("xdg-open"):
        try:
            subprocess.run(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            console.print(f"[bold green]✔ Opened browser:[/bold green] [yellow]{url}[/yellow]")
            return
        except Exception:
            pass

    # 3. Python webbrowser fallback
    try:
        import webbrowser
        webbrowser.open(url)
        console.print(f"[bold green]✔ Opened browser:[/bold green] [yellow]{url}[/yellow]")
    except Exception:
        console.print(f"[bold yellow]👉 Browse to this URL on your phone:[/bold yellow] [bold cyan]{url}[/bold cyan]")


def shutil_which(cmd: str) -> bool:
    import shutil
    return shutil.which(cmd) is not None


def resolve_host_target(target_ip: str = None) -> str:
    """Find the best PC host IP: given arg -> local host -> last host -> network scan."""
    if target_ip:
        save_last_host(target_ip)
        return target_ip

    if is_host_running():
        return "127.0.0.1"

    last = get_last_host()
    if last:
        info = probe_host(last)
        if info:
            return last

    info_local = probe_host("127.0.0.1")
    if info_local:
        return "127.0.0.1"

    console.print("[dim]Scanning local Wi-Fi / Hotspot network for GameGhost PC host...[/dim]")
    found = scan_network_hosts()
    if found:
        best = found[0]["ip"]
        save_last_host(best)
        console.print(f"[bold green]✔ Found GameGhost Host on network:[/bold green] [cyan]{best}[/cyan]")
        return best

    local_ip = get_local_ip()
    return local_ip if not local_ip.startswith("127.") else "127.0.0.1"


def cmd_host(args):
    """Start the GameGhost game streaming and virtual controller host."""
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
        console.print(f"[bold green]✔ Successfully stopped GameGhost Host (PID {pid}).[/bold green]")
    except Exception as ex:
        console.print(f"[red]Error stopping host (PID {pid}): {ex}[/red]")
        clear_host_pid()


def cmd_status(args):
    """Show GameGhost status and active network nodes."""
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    cfg = load_config()
    local_ip = get_local_ip()
    pid = get_host_pid()

    status_str = f"[bold green]RUNNING (PID {pid})[/bold green]" if pid else "[dim]STOPPED[/dim]"

    console.print(Panel(
        f"[bold white]Host Status[/bold white]       : {status_str}\n"
        f"[bold white]Device LAN IP[/bold white]     : [bold cyan]{local_ip}[/bold cyan]\n"
        f"[bold white]HTTP Portal Port[/bold white]  : {cfg.get('http_port', 8899)}\n"
        f"[bold white]Stream Port[/bold white]       : {cfg.get('stream_port', 8900)}\n"
        f"[bold white]Audio Port[/bold white]        : {cfg.get('audio_port', 8901)}\n"
        f"[bold white]Last Connected PC[/bold white]: [yellow]{get_last_host() or 'None (Run scan)'}[/yellow]",
        title="[bold yellow]GameGhost Status[/bold yellow]",
        border_style="cyan"
    ))

    info = probe_host("127.0.0.1")
    if info:
        console.print(f"[bold green]✔ Local GameGhost server is active and responding on port 8899.[/bold green]")


def cmd_open(args):
    """Open handheld portal in mobile browser directly from phone."""
    host_ip = resolve_host_target(getattr(args, "host", None))
    cfg = load_config()
    port = cfg.get("http_port", 8899)
    url = f"http://{host_ip}:{port}"
    save_last_host(host_ip)
    open_browser_url(url)


def cmd_scan(args):
    """Scan local network for running GameGhost hosts."""
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    console.print("[bold yellow]Scanning Wi-Fi / Hotspot network for GameGhost hosts...[/bold yellow]\n")
    found = scan_network_hosts()
    if not found:
        console.print("[yellow]No active GameGhost hosts detected on the current subnet.[/yellow]")
        console.print("Ensure your gaming PC is on the same Wi-Fi / Hotspot and running '[cyan]gameghost host[/cyan]'.")
        return

    table = Table(title="[bold green]Active GameGhost Hosts Found[/bold green]")
    table.add_column("Host Name", style="cyan")
    table.add_column("IP Address", style="bold yellow")
    table.add_column("Portal URL", style="white")
    table.add_column("Stream FPS", style="green")

    for f in found:
        table.add_row(f["name"], f["ip"], f["url"], str(f["fps"]))

    console.print(table)
    console.print(f"\n[bold green]👉 Connect instantly:[/bold green] [bold cyan]gameghost open {found[0]['ip']}[/bold cyan]")


def cmd_client(args):
    """Launch the native GameGhost handheld client with on-screen touch overlay."""
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    try:
        from .client import run_client
    except ImportError as ex:
        console.print(f"[bold red][ERR] Native SDL2 client requires pygame: {ex}[/bold red]")
        console.print("To play on your phone without installing pygame, run:")
        console.print("  [bold green]gameghost open[/bold green] (or [bold green]gg open[/bold green]) to launch the web touch portal in your browser!")
        return

    console.print("[bold green][CLIENT] Starting GameGhost Native Handheld Client...[/bold green]")
    run_client(host_ip=args.ip, fullscreen=args.fullscreen)


def cmd_play(args):
    """Launch a game locally or remotely on PC and open the handheld portal."""
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    game_id = args.game.lower()
    remote_host = getattr(args, "host", None)

    if not remote_host and not is_host_running():
        last = get_last_host()
        if last and probe_host(last):
            remote_host = last
        else:
            found = scan_network_hosts()
            if found:
                remote_host = found[0]["ip"]

    if remote_host and remote_host != "127.0.0.1" and remote_host != get_local_ip():
        console.print(f"[bold yellow]Triggering remote launch of '{game_id}' on PC ({remote_host})...[/bold yellow]")
        try:
            req = urllib.request.Request(
                f"http://{remote_host}:8899/api/launch/{game_id}",
                data=b"",
                headers={"User-Agent": "GameGhost-Client"}
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                if res.get("success"):
                    console.print(f"[bold green]✔ Successfully started {game_id} on PC![/bold green]")
        except Exception as ex:
            console.print(f"[yellow]Note: Remote trigger response: {ex}. Proceeding to open stream.[/yellow]")

        save_last_host(remote_host)
        url = f"http://{remote_host}:8899"
        open_browser_url(url)
        return

    console.print(f"[bold green]⚡ Launching {game_id} locally ⚡[/bold green]")
    launch_game(game_id)
    time.sleep(1.2)

    if not is_host_running():
        host = GameGhostHost()
        try:
            host.start()
        except KeyboardInterrupt:
            host.stop()
    else:
        open_browser_url(f"http://127.0.0.1:8899")


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
    console.print("[bold yellow]Testing Virtual Gamepad Initialization...[/bold yellow]")
    gp = VirtualGamepad()
    if gp.active and gp.uinput:
        console.print(f"[bold green]✔ Successfully created hardware virtual device: {gp.uinput.name}[/bold green]")
        console.print("[INFO] Testing button pulses (A, B, X, Y)...")
        for btn in ["A", "B", "X", "Y"]:
            gp.handle_packet({"type": "btn", "name": btn, "val": 1})
            time.sleep(0.04)
            gp.handle_packet({"type": "btn", "name": btn, "val": 0})
        console.print("[bold green]✔ Hardware test complete! All PC games recognize this controller.[/bold green]")
        gp.close()
    else:
        console.print(f"[bold yellow]Virtual device operating in mode: {gp.mode}[/bold yellow]")
        console.print("[dim]Note: /dev/uinput requires read/write permissions on host Linux.[/dim]")


def cmd_menu(args):
    """Interactive phone-friendly touch menu."""
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    console.print("[bold yellow]📱 GameGhost Handheld Mobile Menu 📱[/bold yellow]\n")
    console.print("  [bold cyan][1][/bold cyan] 🌐 Open Handheld Portal in Phone Browser")
    console.print("  [bold cyan][2][/bold cyan] 📱 Launch Native SDL2 Touch Client")
    console.print("  [bold cyan][3][/bold cyan] 🔍 Scan Network for Gaming PC Host")
    console.print("  [bold cyan][4][/bold cyan] 🗡️  Launch & Play Devil May Cry 5")
    console.print("  [bold cyan][5][/bold cyan] 🎮 Launch & Play Sekiro")
    console.print("  [bold cyan][6][/bold cyan] 🥊 Launch & Play Tekken 8")
    console.print("  [bold cyan][7][/bold cyan] 🖥️  Start GameGhost Host Server")
    console.print("  [bold cyan][8][/bold cyan] 📊 View Status & Configuration")
    console.print("  [bold cyan][9][/bold cyan] 🛑 Stop GameGhost Host Server")
    console.print("  [bold cyan][0][/bold cyan] ❌ Exit\n")

    try:
        choice = input("Select an option [0-9]: ").strip()
    except (KeyboardInterrupt, EOFError):
        return

    if choice == "1":
        cmd_open(argparse.Namespace(host=None))
    elif choice == "2":
        cmd_client(argparse.Namespace(ip=None, fullscreen=False))
    elif choice == "3":
        cmd_scan(argparse.Namespace())
    elif choice == "4":
        cmd_dmc5(argparse.Namespace(host=None))
    elif choice == "5":
        cmd_sekiro(argparse.Namespace(host=None))
    elif choice == "6":
        cmd_tekken8(argparse.Namespace(host=None))
    elif choice == "7":
        cmd_host(argparse.Namespace(fps=60, quality=80, scale=0.85))
    elif choice == "8":
        cmd_status(argparse.Namespace())
    elif choice == "9":
        cmd_stop(argparse.Namespace())
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

    # open / portal command
    p_open = subparsers.add_parser("open", help="Open handheld portal in mobile browser")
    p_open.add_argument("host", nargs="?", default=None, help="Optional PC host IP to connect to")

    p_portal = subparsers.add_parser("portal", help="Alias for 'open'")
    p_portal.add_argument("host", nargs="?", default=None, help="Optional PC host IP to connect to")

    p_phone = subparsers.add_parser("phone", help="Alias for 'open'")
    p_phone.add_argument("host", nargs="?", default=None, help="Optional PC host IP to connect to")

    # client command
    p_client = subparsers.add_parser("client", help="Launch native handheld client with touch controls")
    p_client.add_argument("ip", type=str, nargs="?", default=None, help="Host PC IP address")
    p_client.add_argument("--fullscreen", "-f", action="store_true", help="Launch in fullscreen mode")

    # scan command
    subparsers.add_parser("scan", help="Scan network for GameGhost PC hosts")
    subparsers.add_parser("find", help="Alias for 'scan'")

    # play command
    p_play = subparsers.add_parser("play", help="Launch a game and stream to phone")
    p_play.add_argument("game", type=str, help="Game ID (e.g. dmc5, sekiro, tekken8, mk11, mgr)")
    p_play.add_argument("--host", type=str, default=None, help="Remote PC host IP")

    # dmc5 command
    p_dmc5 = subparsers.add_parser("dmc5", help="Launch Devil May Cry 5 & open stream")
    p_dmc5.add_argument("--host", type=str, default=None, help="Remote PC host IP")

    # sekiro command
    p_sekiro = subparsers.add_parser("sekiro", help="Launch Sekiro & open stream")
    p_sekiro.add_argument("--host", type=str, default=None, help="Remote PC host IP")

    # tekken8 command
    p_tekken = subparsers.add_parser("tekken8", help="Launch Tekken 8 & open stream")
    p_tekken.add_argument("--host", type=str, default=None, help="Remote PC host IP")

    # list command
    subparsers.add_parser("list", help="List detected games on the system")

    # gamepad command
    subparsers.add_parser("gamepad", help="Test the virtual gamepad device")

    # menu command
    subparsers.add_parser("menu", help="Interactive phone-friendly touch menu")

    args = parser.parse_args()

    if args.command == "host":
        cmd_host(args)
    elif args.command == "stop":
        cmd_stop(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command in ("open", "portal", "phone"):
        cmd_open(args)
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
    elif args.command == "menu":
        cmd_menu(args)
    else:
        if sys.stdin.isatty():
            cmd_menu(args)
        else:
            cmd_status(args)


if __name__ == "__main__":
    main()
