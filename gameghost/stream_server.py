import os
import io
import time
import json
import glob
import asyncio
import threading
from typing import Set, Optional
from PIL import Image, ImageDraw
import websockets
from rich.console import Console

from .gamepad import VirtualGamepad
from .launcher import launch_game, list_games

console = Console()


class GameStreamServer:
    """
    High-performance, low-latency game video & input streaming server.
    Captures PC screen at high FPS, pushes JPEG frames over WebSockets,
    and ingests real-time touch gamepad events directly into the virtual controller.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8900, fps: int = 60, quality: int = 75, scale: float = 0.85):
        self.host = host
        self.port = port
        self.fps = fps
        self.quality = quality
        self.scale = scale
        self.running = False
        self.clients: Set[websockets.WebSocketServerProtocol] = set()
        self.gamepad = VirtualGamepad()
        self.latest_frame: Optional[bytes] = None
        self.latest_frame_seq = 0
        self.frame_lock = threading.Lock()
        self.stats = {
            "fps": 0,
            "clients": 0,
            "bytes_sent": 0
        }

    def _render_standby_frame(self, t0: float) -> bytes:
        """Generate high-contrast, low-latency standby frame when display is not available."""
        w, h = 1280, 720
        img = Image.new("RGB", (w, h), color=(10, 14, 23))
        draw = ImageDraw.Draw(img)

        # Subtle background border
        draw.rectangle([20, 20, w - 20, h - 20], outline=(0, 210, 255), width=2)
        draw.text((40, 40), "GAMEGHOST // HANDHELD STREAMING HOST", fill=(0, 210, 255))
        draw.text((40, 70), f"Status: ACTIVE | Target FPS: {self.fps} | Quality: {self.quality}%", fill=(170, 190, 210))
        draw.text((40, 95), f"Controller: {'Xbox 360 Hardware' if self.gamepad.active else 'Keyboard Mapper'}", fill=(0, 230, 118))

        # Animated heartbeat pulse box
        pulse = int((time.time() * 2) % 2)
        p_color = (0, 210, 255) if pulse else (0, 120, 180)
        draw.rectangle([w - 180, 40, w - 40, 90], fill=p_color)
        draw.text((w - 165, 55), "HOST READY", fill=(0, 0, 0))

        # Center banner
        now_str = time.strftime("%H:%M:%S")
        draw.text((w // 2 - 160, h // 2 - 30), "WAITING FOR GAME LAUNCH", fill=(255, 255, 255))
        draw.text((w // 2 - 100, h // 2 + 5), f"HOST CLOCK: {now_str}", fill=(130, 150, 170))
        draw.text((w // 2 - 210, h // 2 + 40), "Select a game on phone to start playing immediately.", fill=(0, 210, 255))

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=60, optimize=False)
        return buf.getvalue()

    def _capture_worker(self):
        """Dedicated thread continuously grabbing desktop frames at high FPS."""
        # Ensure display and auth are available for screen capture
        if "DISPLAY" not in os.environ and os.path.exists("/tmp/.X11-unix/X0"):
            os.environ["DISPLAY"] = ":0"
        if "XAUTHORITY" not in os.environ:
            matches = glob.glob(f"/run/user/{os.getuid()}/.mutter-Xwaylandauth*")
            if matches:
                os.environ["XAUTHORITY"] = matches[0]
            elif os.path.exists(os.path.expanduser("~/.Xauthority")):
                os.environ["XAUTHORITY"] = os.path.expanduser("~/.Xauthority")

        sct = None
        monitor = None
        use_fallback = False

        try:
            import mss
            sct = mss.mss()
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        except Exception as ex:
            console.print(f"[STREAM] Display capture unavailable ({ex}). Activating standby game visualizer.")
            use_fallback = True

        target_delay = 1.0 / max(15, min(90, self.fps))
        frame_count = 0
        last_fps_time = time.time()

        while self.running:
            t0 = time.time()
            jpeg_bytes = None

            if not use_fallback and sct and monitor:
                try:
                    raw = sct.grab(monitor)
                    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

                    if self.scale != 1.0:
                        new_w = max(320, int(img.width * self.scale))
                        new_h = max(240, int(img.height * self.scale))
                        img = img.resize((new_w, new_h), Image.BILINEAR)

                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=self.quality, optimize=False)
                    jpeg_bytes = buf.getvalue()
                except Exception:
                    use_fallback = True

            if use_fallback or not jpeg_bytes:
                jpeg_bytes = self._render_standby_frame(t0)

            with self.frame_lock:
                self.latest_frame = jpeg_bytes
                self.latest_frame_seq += 1

            frame_count += 1
            now = time.time()
            if now - last_fps_time >= 1.0:
                self.stats["fps"] = frame_count
                frame_count = 0
                last_fps_time = now

            elapsed = time.time() - t0
            rem = target_delay - elapsed
            if rem > 0.001:
                time.sleep(rem)

    async def _broadcast_loop(self):
        """Asynchronously push the latest frame to connected phone clients."""
        interval = 1.0 / self.fps
        last_sent_seq = 0

        while self.running:
            if self.clients:
                with self.frame_lock:
                    frame = self.latest_frame
                    seq = self.latest_frame_seq

                if frame and seq != last_sent_seq:
                    last_sent_seq = seq
                    try:
                        websockets.broadcast(self.clients, frame)
                        self.stats["bytes_sent"] += len(frame) * len(self.clients)
                    except Exception:
                        pass

            await asyncio.sleep(interval)

    async def handler(self, websocket):
        """Handle incoming client WebSocket connection and phone gamepad events."""
        self.clients.add(websocket)
        self.stats["clients"] = len(self.clients)
        client_addr = getattr(websocket, "remote_address", "client")
        console.print(f"[bold green][PHONE CONNECTED][/bold green] Handheld connected from {client_addr}")

        try:
            async for message in websocket:
                if isinstance(message, str):
                    try:
                        data = json.loads(message)
                        msg_type = data.get("type")

                        if msg_type in ("btn", "stick", "trigger", "dpad"):
                            self.gamepad.handle_packet(data)

                        elif msg_type == "launch":
                            game_id = data.get("game", "dmc5")
                            console.print(f"[bold green][REMOTE LAUNCH][/bold green] Phone requested launch of: {game_id}")
                            proc = launch_game(game_id)
                            await websocket.send(json.dumps({
                                "type": "launch_ack",
                                "game": game_id,
                                "success": proc is not None
                            }))

                        elif msg_type == "list_games":
                            games = list_games()
                            await websocket.send(json.dumps({
                                "type": "games_list",
                                "games": games
                            }))

                        elif msg_type == "ping":
                            await websocket.send(json.dumps({
                                "type": "pong",
                                "client_time": data.get("time", 0),
                                "server_time": time.time() * 1000,
                                "fps": self.stats["fps"]
                            }))

                        elif msg_type == "settings":
                            if "quality" in data:
                                self.quality = int(data["quality"])
                            if "fps" in data:
                                self.fps = int(data["fps"])
                            if "mode" in data:
                                self.gamepad.mode = data["mode"]
                    except Exception:
                        pass
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)
            self.stats["clients"] = len(self.clients)
            console.print(f"[bold yellow][PHONE DISCONNECTED][/bold yellow] Client left: {client_addr}")

    async def start(self):
        self.running = True
        t = threading.Thread(target=self._capture_worker, daemon=True)
        t.start()

        console.print(f"[STREAM] GameGhost Game Stream listening on ws://{self.host}:{self.port}")
        server = await websockets.serve(
            self.handler,
            self.host,
            self.port,
            max_size=10 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=20
        )
        await asyncio.gather(server.wait_closed(), self._broadcast_loop())

    def stop(self):
        self.running = False
        self.gamepad.close()
