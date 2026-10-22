import os
import sys
import asyncio
import threading
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import uvicorn
from rich.console import Console

from .config import load_config, get_local_ip
from .stream_server import GameStreamServer
from .audio_server import GameAudioServer
from .launcher import list_games, launch_game

console = Console()


def create_app(cfg: dict, server_instance) -> FastAPI:
    app = FastAPI(title="GameGhost Handheld Portal", docs_url=None, redoc_url=None)

    web_dir = Path(__file__).resolve().parent.parent / "web"

    @app.get("/api/info")
    async def get_info():
        import socket
        return {
            "status": "online",
            "name": cfg.get("node_name", "GameGhost"),
            "host_ip": server_instance.local_ip,
            "http_port": server_instance.http_port,
            "stream_port": server_instance.stream_port,
            "audio_port": server_instance.audio_port,
            "connected_clients": server_instance.stream_server.stats["clients"],
            "fps": server_instance.stream_server.stats["fps"],
            "virtual_gamepad": server_instance.stream_server.gamepad.active
        }

    @app.get("/api/games")
    async def get_games():
        return list_games()

    @app.post("/api/launch/{game_id}")
    async def trigger_launch(game_id: str):
        proc = launch_game(game_id)
        if proc:
            return {"success": True, "message": f"Started {game_id}"}
        return JSONResponse(status_code=404, content={"success": False, "message": f"Game {game_id} not found."})

    if web_dir.exists():
        app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")

        @app.get("/")
        async def root():
            return FileResponse(str(web_dir / "index.html"))

    return app


class GameGhostHost:
    def __init__(self, fps: int = 60, quality: int = 80, scale: float = 0.85):
        self.cfg = load_config()
        self.http_port = self.cfg.get("http_port", 8899)
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

        self.app = create_app(self.cfg, self)
        self.running = False

    def start(self):
        self.running = True

        portal_url = f"http://{self.local_ip}:{self.http_port}"

        console.print("")
        console.print("[bold cyan]==================================================================[/bold cyan]")
        console.print("[bold green]       [GAMEGHOST HANDHELD STREAMING HOST ONLINE][/bold green]")
        console.print("[bold cyan]==================================================================[/bold cyan]")
        console.print(f" [HOST IP]              : [bold white]{self.local_ip}[/bold white]")
        console.print(f" [PHONE PORTAL URL]     : [bold yellow]{portal_url}[/bold yellow]")
        console.print(f" [STREAM WEBSOCKET]     : ws://{self.local_ip}:{self.stream_port}")
        console.print(f" [AUDIO WEBSOCKET]      : ws://{self.local_ip}:{self.audio_port}")
        console.print(f" [VIRTUAL CONTROLLER]   : [bold green]Active (Hardware Xbox 360 Pad via uinput)[/bold green]")
        console.print("[bold cyan]==================================================================[/bold cyan]")
        console.print(f"\n[bold green][CONNECT] Open this on your Phone's browser (or Termux):[/bold green]")
        console.print(f"   [bold yellow]{portal_url}[/bold yellow]\n")

        # 1. Start stream server thread
        def _run_stream():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.stream_server.start())

        stream_thread = threading.Thread(target=_run_stream, daemon=True)
        stream_thread.start()

        # 2. Start audio server thread
        def _run_audio():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.audio_server.start())

        audio_thread = threading.Thread(target=_run_audio, daemon=True)
        audio_thread.start()

        # 3. Start FastAPI server
        uvicorn_config = uvicorn.Config(
            app=self.app,
            host="0.0.0.0",
            port=self.http_port,
            log_level="warning"
        )
        server = uvicorn.Server(uvicorn_config)
        try:
            server.run()
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self.running = False
        self.stream_server.stop()
        self.audio_server.stop()
        console.print("[HOST] GameGhost Host stopped.")
