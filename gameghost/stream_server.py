import io
import time
import json
import asyncio
import threading
from typing import Set, Optional
import mss
from PIL import Image
import websockets
from rich.console import Console

from .gamepad import VirtualGamepad

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
        self.sct = None
        self.latest_frame: Optional[bytes] = None
        self.frame_lock = threading.Lock()
        self.stats = {
            "fps": 0,
            "clients": 0,
            "bytes_sent": 0
        }

    def _capture_worker(self):
        """Dedicated high-speed thread capturing screen frames."""
        try:
            sct = mss.mss()
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            target_delay = 1.0 / max(15, min(90, self.fps))
            frame_count = 0
            last_fps_time = time.time()

            while self.running:
                t0 = time.time()
                # Grab screenshot
                raw = sct.grab(monitor)
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

                # Scale frame for phone streaming performance
                if self.scale != 1.0:
                    new_w = int(img.width * self.scale)
                    new_h = int(img.height * self.scale)
                    img = img.resize((new_w, new_h), Image.BILINEAR)

                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=self.quality, optimize=False)
                jpeg_bytes = buf.getvalue()

                with self.frame_lock:
                    self.latest_frame = jpeg_bytes

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
        except Exception as ex:
            console.print(f"[ERR] Capture worker error: {ex}")

    async def _broadcast_loop(self):
        """Asynchronously push the latest frame to connected phone clients."""
        interval = 1.0 / self.fps
        while self.running:
            if self.clients:
                with self.frame_lock:
                    frame = self.latest_frame

                if frame:
                    disconnected = set()
                    for ws in self.clients:
                        try:
                            await ws.send(frame)
                            self.stats["bytes_sent"] += len(frame)
                        except Exception:
                            disconnected.add(ws)
                    for d in disconnected:
                        self.clients.discard(d)

            await asyncio.sleep(interval)

    async def handler(self, websocket):
        """Handle incoming client WebSocket connection and phone gamepad events."""
        self.clients.add(websocket)
        self.stats["clients"] = len(self.clients)
        client_addr = websocket.remote_address
        console.print(f"[bold green][PHONE CONNECTED][/bold green] Handheld connected from {client_addr}")

        try:
            async for message in websocket:
                if isinstance(message, str):
                    try:
                        data = json.loads(message)
                        msg_type = data.get("type")

                        if msg_type in ("btn", "stick", "trigger", "dpad"):
                            # Fast gamepad input dispatch
                            self.gamepad.handle_packet(data)

                        elif msg_type == "ping":
                            # Latency echo
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
        # Start capture worker thread
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
