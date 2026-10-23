import os
import sys
import asyncio
from pathlib import Path
from typing import Optional
from rich.console import Console

from .config import load_config, get_local_ip, save_host_pid, clear_host_pid, log_host, wait_for_hotspot_ip
from .stream_server import GameStreamServer
from .audio_server import GameAudioServer
from .discovery import GameDiscovery

console = Console()


class GameGhostHost:
    def __init__(
        self,
        fps: Optional[int] = None,
        quality: Optional[int] = None,
        scale: Optional[float] = None,
        preset: Optional[str] = None,
        min_fps: Optional[int] = None,
        max_fps: Optional[int] = None,
        auto_fps: Optional[bool] = None
    ):
        self.cfg = load_config()
        self.stream_port = self.cfg.get("stream_port", 8900)
        self.audio_port = self.cfg.get("audio_port", 8901)
        self.local_ip = wait_for_hotspot_ip(timeout=15.0)
        log_host(f'Host initialized with IP: {self.local_ip}')

        self.stream_server = GameStreamServer(
            host="0.0.0.0",
            port=self.stream_port,
            fps=fps or self.cfg.get("target_fps", 60),
            min_fps=min_fps or self.cfg.get("min_fps", 45),
            max_fps=max_fps or self.cfg.get("max_fps", 120),
            auto_fps=auto_fps if auto_fps is not None else self.cfg.get("auto_fps", True),
            quality=quality or self.cfg.get("screen_quality", 80),
            scale=scale or self.cfg.get("screen_scale", 0.85),
            preset=preset or self.cfg.get("preset", "1080p")
        )

        self.audio_server = GameAudioServer(
            host="0.0.0.0",
            port=self.audio_port
        )

        self.discovery = GameDiscovery()
        self.running = False

    async def run_async(self):
        self.running = True
        save_host_pid(os.getpid())

        console.print("")
        console.print("[bold cyan]==================================================================[/bold cyan]")
        console.print("[bold green]       GAMEGHOST HANDHELD STREAMING HOST ONLINE[/bold green]")
        console.print("[bold cyan]==================================================================[/bold cyan]")
        console.print(f" [HOST IP]              : [bold white]{self.local_ip}[/bold white]")
        console.print(f" [STREAM WEBSOCKET]     : ws://{self.local_ip}:{self.stream_port}")
        console.print(f" [AUDIO WEBSOCKET]      : ws://{self.local_ip}:{self.audio_port}")
        v_status = "[bold green]Active (Hardware Xbox 360 Pad via uinput)[/bold green]" if self.stream_server.gamepad.active else "[bold yellow]Fallback (Keyboard mapper)[/bold yellow]"
        console.print(f" [VIRTUAL CONTROLLER]   : {v_status}")
        console.print(f" [HOTSPOT BEACON]       : [bold green]Active (UDP Auto-Discovery)[/bold green]")
        console.print("[bold cyan]==================================================================[/bold cyan]")
        console.print(f"\n[bold green][CLIENT CONNECT][/bold green] On your phone (Termux), run:")
        console.print(f"  [bold cyan]gameghost client {self.local_ip}[/bold cyan]\n")

        # 1. Start discovery beacon
        self.discovery.start_broadcaster()

        # 2. Start servers concurrently
        tasks = [
            asyncio.create_task(self.stream_server.start()),
            asyncio.create_task(self.audio_server.start())
        ]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            self.stop()

    def start(self):
        try:
            asyncio.run(self.run_async())
        except KeyboardInterrupt:
            self.stop()
        finally:
            clear_host_pid()

    def stop(self):
        self.running = False
        clear_host_pid()
        self.discovery.stop()
        self.stream_server.stop()
        console.print("[INFO] GameGhost Host stopped.")
