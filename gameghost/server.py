import os
import sys
import asyncio
import threading
from pathlib import Path
from rich.console import Console

from .config import load_config, get_local_ip
from .stream_server import GameStreamServer
from .audio_server import GameAudioServer
from .discovery import GameDiscovery
from .launcher import list_games, launch_game

console = Console()


class GameGhostHost:
    def __init__(self, fps: int = 60, quality: int = 80, scale: float = 0.85):
        self.cfg = load_config()
        self.stream_port = self.cfg.get("stream_port", 8900)
        self.audio_port = self.cfg.get("audio_port", 8901)
        self.local_ip = get_local_ip()

        self.stream_server = GameStreamServer(
            host="0.0.0.0",
            port=self.stream_port,
            fps=fps or self.cfg.get("target_fps", 60),
            quality=quality or self.cfg.get("screen_quality", 80),
            scale=scale or self.cfg.get("screen_scale", 0.85)
        )

        self.audio_server = GameAudioServer(
            host="0.0.0.0",
            port=self.audio_port
        )

        self.discovery = GameDiscovery()
        self.running = False

    async def run_async(self):
        self.running = True

        console.print("")
        console.print("[bold cyan]==================================================================[/bold cyan]")
        console.print("[bold green]       [GAMEGHOST HANDHELD STREAMING HOST ONLINE][/bold green]")
        console.print("[bold cyan]==================================================================[/bold cyan]")
        console.print(f" [HOST IP]              : [bold white]{self.local_ip}[/bold white]")
        console.print(f" [STREAM WEBSOCKET]     : ws://{self.local_ip}:{self.stream_port}")
        console.print(f" [AUDIO WEBSOCKET]      : ws://{self.local_ip}:{self.audio_port}")
        console.print(f" [VIRTUAL CONTROLLER]   : [bold green]Active (Hardware Xbox 360 Pad via uinput)[/bold green]")
        console.print(f" [HOTSPOT BEACON]       : UDP Broadcast Active")
        console.print("[bold cyan]==================================================================[/bold cyan]")
        console.print(f"\n[bold green][CONNECT] Run this on your Phone / Termux:[/bold green]")
        console.print(f"   [bold yellow]gameghost client {self.local_ip}[/bold yellow]\n")

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

    def stop(self):
        self.running = False
        self.discovery.stop()
        self.stream_server.stop()
        self.audio_server.stop()
        console.print("[HOST] GameGhost Host stopped.")
