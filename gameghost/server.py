import os
import sys
import asyncio
import threading
from pathlib import Path
from rich.console import Console

from .config import load_config, get_local_ip, save_host_pid, clear_host_pid
from .stream_server import GameStreamServer
from .audio_server import GameAudioServer
from .discovery import GameDiscovery
from .launcher import list_games, launch_game

console = Console()

# Try FastAPI or Starlette for Web portal
try:
    from starlette.applications import Starlette
    from starlette.staticfiles import StaticFiles
    from starlette.responses import FileResponse, JSONResponse
    from starlette.routing import Route, Mount
    import uvicorn
    HAS_WEB = True
except Exception:
    HAS_WEB = False


def create_web_app(cfg: dict, server_instance):
    if not HAS_WEB:
        return None

    web_dir = Path(__file__).resolve().parent.parent / "web"

    async def get_info(request=None):
        return JSONResponse({
            "status": "online",
            "name": cfg.get("node_name", "GameGhost"),
            "host_ip": server_instance.local_ip,
            "http_port": server_instance.http_port,
            "stream_port": server_instance.stream_port,
            "audio_port": server_instance.audio_port,
            "connected_clients": server_instance.stream_server.stats["clients"],
            "fps": server_instance.stream_server.stats["fps"],
            "virtual_gamepad": server_instance.stream_server.gamepad.active
        })

    async def get_games(request=None):
        return JSONResponse(list_games())

    async def trigger_launch(request=None):
        game_id = request.path_params.get("game_id", "") if request else ""
        proc = launch_game(game_id)
        if proc:
            return JSONResponse({"success": True, "message": f"Started {game_id}"})
        return JSONResponse(status_code=404, content={"success": False, "message": f"Game '{game_id}' not found."})

    async def root(request=None):
        index_file = web_dir / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return JSONResponse({"error": "web portal assets not found"}, status_code=404)

    async def stop_host(request=None):
        threading.Thread(target=server_instance.stop, daemon=True).start()
        return JSONResponse({"success": True, "message": "Host stopping..."})

    routes = [
        Route("/api/info", get_info, methods=["GET"]),
        Route("/api/games", get_games, methods=["GET"]),
        Route("/api/launch/{game_id}", trigger_launch, methods=["POST"]),
        Route("/api/stop", stop_host, methods=["POST", "GET"]),
        Route("/", root, methods=["GET"])
    ]
    if web_dir.exists():
        routes.append(Mount("/static", StaticFiles(directory=str(web_dir)), name="static"))

    return Starlette(routes=routes)


class GameGhostHost:
    def __init__(self, fps: int = 60, quality: int = 80, scale: float = 0.85):
        self.cfg = load_config()
        self.stream_port = self.cfg.get("stream_port", 8900)
        self.audio_port = self.cfg.get("audio_port", 8901)
        self.http_port = self.cfg.get("http_port", 8899)
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
        self.app = create_web_app(self.cfg, self)
        self.uvicorn_server = None
        if self.app and HAS_WEB:
            u_cfg = uvicorn.Config(app=self.app, host="0.0.0.0", port=self.http_port, log_level="warning")
            self.uvicorn_server = uvicorn.Server(u_cfg)

        self.running = False

    async def run_async(self):
        self.running = True
        save_host_pid(os.getpid())

        portal_url = f"http://{self.local_ip}:{self.http_port}"

        console.print("")
        console.print("[bold cyan]==================================================================[/bold cyan]")
        console.print("[bold green]       🎮 GAMEGHOST HANDHELD STREAMING HOST ONLINE 🎮[/bold green]")
        console.print("[bold cyan]==================================================================[/bold cyan]")
        console.print(f" [HOST IP]              : [bold white]{self.local_ip}[/bold white]")
        console.print(f" [PHONE PORTAL URL]     : [bold yellow]{portal_url}[/bold yellow]")
        console.print(f" [STREAM WEBSOCKET]     : ws://{self.local_ip}:{self.stream_port}")
        console.print(f" [AUDIO WEBSOCKET]      : ws://{self.local_ip}:{self.audio_port}")
        v_status = "[bold green]Active (Hardware Xbox 360 Pad via uinput)[/bold green]" if self.stream_server.gamepad.active else "[bold yellow]Fallback (Keyboard mapper)[/bold yellow]"
        console.print(f" [VIRTUAL CONTROLLER]   : {v_status}")
        console.print(f" [HOTSPOT BEACON]       : [bold green]Active (UDP Auto-Discovery)[/bold green]")
        console.print("[bold cyan]==================================================================[/bold cyan]")
        console.print(f"\n[bold green]👉 Open on your Phone browser:[/bold green]  [bold yellow]{portal_url}[/bold yellow]")
        console.print(f"[bold green]👉 Or run Native Client:[/bold green]         [bold cyan]gameghost client {self.local_ip}[/bold cyan]\n")

        # 1. Start discovery beacon
        self.discovery.start_broadcaster()

        # 2. Start servers concurrently
        tasks = [
            asyncio.create_task(self.stream_server.start()),
            asyncio.create_task(self.audio_server.start())
        ]
        if self.uvicorn_server:
            tasks.append(asyncio.create_task(self.uvicorn_server.serve()))

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
        self.audio_server.stop()
        if self.uvicorn_server:
            self.uvicorn_server.should_exit = True
        console.print("[HOST] GameGhost Host stopped.")
