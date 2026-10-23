import os
import io
import time
import json
import glob
import asyncio
import threading
import ctypes
from ctypes import byref, c_uint, c_ulong, c_int, c_long, Structure, POINTER
from typing import Set, Optional
from PIL import Image, ImageDraw
import websockets
from rich.console import Console

from .gamepad import VirtualGamepad
from .launcher import launch_game, list_games
from .config import load_config, QUALITY_PRESETS

console = Console()


class _XWindowAttributes(Structure):
    _fields_ = [
        ("x", c_int), ("y", c_int),
        ("width", c_int), ("height", c_int),
        ("border_width", c_int),
        ("depth", c_int),
        ("visual", ctypes.c_void_p),
        ("root", c_ulong),
        ("class", c_int),
        ("bit_gravity", c_int),
        ("win_gravity", c_int),
        ("backing_store", c_int),
        ("backing_planes", c_ulong),
        ("backing_pixel", c_ulong),
        ("save_under", c_int),
        ("colormap", c_ulong),
        ("map_installed", c_int),
        ("map_state", c_int),
        ("all_event_masks", c_long),
        ("your_event_mask", c_long),
        ("do_not_propagate_mask", c_long),
        ("override_redirect", c_int),
        ("screen", ctypes.c_void_p)
    ]


def _find_target_game_window():
    try:
        x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XDefaultRootWindow.restype = c_ulong
        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x11.XQueryTree.restype = c_int
        x11.XQueryTree.argtypes = [ctypes.c_void_p, c_ulong, POINTER(c_ulong), POINTER(c_ulong), POINTER(POINTER(c_ulong)), POINTER(c_uint)]
        x11.XFetchName.restype = c_int
        x11.XFetchName.argtypes = [ctypes.c_void_p, c_ulong, POINTER(ctypes.c_char_p)]
        x11.XGetWindowAttributes.restype = c_int
        x11.XGetWindowAttributes.argtypes = [ctypes.c_void_p, c_ulong, POINTER(_XWindowAttributes)]
        x11.XFree.restype = c_int
        x11.XFree.argtypes = [ctypes.c_void_p]
        x11.XCloseDisplay.restype = c_int
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]

        disp = x11.XOpenDisplay(None)
        if not disp:
            return None, 0, 0
        root = x11.XDefaultRootWindow(disp)
        root_ret = c_ulong()
        parent_ret = c_ulong()
        children = POINTER(c_ulong)()
        nchildren = c_uint()

        best_win = None
        best_w, best_h = 0, 0

        if x11.XQueryTree(disp, root, byref(root_ret), byref(parent_ret), byref(children), byref(nchildren)):
            game_keywords = ["devil may cry", "dmc", "sekiro", "tekken", "mortal kombat", "metal gear", "tomb raider"]
            for i in range(nchildren.value - 1, -1, -1):
                wid = children[i]
                attrs = _XWindowAttributes()
                if x11.XGetWindowAttributes(disp, wid, byref(attrs)):
                    if attrs.map_state == 2 and attrs.width >= 640 and attrs.height >= 480:
                        name_ptr = ctypes.c_char_p()
                        title = ""
                        if x11.XFetchName(disp, wid, byref(name_ptr)) and name_ptr.value:
                            title = name_ptr.value.decode("utf-8", "replace").lower()
                            x11.XFree(name_ptr)

                        if "guard window" in title or "desktop" in title or "damx" in title or "conky" in title:
                            continue

                        if any(k in title for k in game_keywords):
                            best_win = wid
                            best_w, best_h = attrs.width, attrs.height
                            break

            if children:
                x11.XFree(children)
        x11.XCloseDisplay(disp)
        return best_win, best_w, best_h
    except Exception:
        return None, 0, 0


class GameStreamServer:
    """
    High-performance, low-latency game video & input streaming server.
    Captures PC screen at high FPS, pushes JPEG frames over WebSockets,
    and ingests real-time touch gamepad events directly into the virtual controller.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8900,
        fps: int = 60,
        min_fps: int = 45,
        max_fps: int = 120,
        auto_fps: bool = True,
        quality: int = 80,
        scale: float = 0.85,
        preset: str = "1080p"
    ):
        self.host = host
        self.port = port
        self.preset = preset
        if preset in QUALITY_PRESETS:
            p_cfg = QUALITY_PRESETS[preset]
            scale = p_cfg.get("scale", scale)
            quality = p_cfg.get("quality", quality)
            fps = p_cfg.get("fps", fps)
            min_fps = p_cfg.get("min_fps", min_fps)
            max_fps = p_cfg.get("max_fps", max_fps)

        self.fps = fps
        self.target_fps = fps
        self.min_fps = min_fps
        self.max_fps = max_fps
        self.auto_fps = auto_fps
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
        def _try_init_sct():
            if "DISPLAY" not in os.environ and os.path.exists("/tmp/.X11-unix/X0"):
                os.environ["DISPLAY"] = ":0"
            if "XAUTHORITY" not in os.environ or not os.path.exists(os.environ.get("XAUTHORITY", "")):
                matches = glob.glob(f"/run/user/{os.getuid()}/.mutter-Xwaylandauth*")
                if matches:
                    os.environ["XAUTHORITY"] = matches[0]
                elif os.path.exists(os.path.expanduser("~/.Xauthority")):
                    os.environ["XAUTHORITY"] = os.path.expanduser("~/.Xauthority")
            try:
                import mss
                s = mss.mss()
                m = s.monitors[1] if len(s.monitors) > 1 else s.monitors[0]
                console.print(f"[bold green][STREAM] Display capture active ({m.get('width', 0)}x{m.get('height', 0)})[/bold green]")
                return s, m
            except Exception:
                return None, None

        sct, monitor = _try_init_sct()
        last_init_attempt = time.time()
        current_target_win = None
        last_win_check = 0

        if not sct:
            console.print("[STREAM] Display capture not immediately ready. Activating standby game visualizer until display connects.")

        frame_count = 0
        last_fps_time = time.time()
        fps_adjust_interval = 0

        while self.running:
            t0 = time.time()
            jpeg_bytes = None

            if sct is None or monitor is None:
                if t0 - last_init_attempt >= 1.5:
                    last_init_attempt = t0
                    sct, monitor = _try_init_sct()
                    current_target_win = None

            # Periodically scan for active game window to grab directly on Xwayland/X11
            if sct and (t0 - last_win_check >= 1.5 or current_target_win is None):
                last_win_check = t0
                twin, tw, th = _find_target_game_window()
                if twin and twin != current_target_win:
                    current_target_win = twin
                    if hasattr(sct, "_impl") and hasattr(sct._impl, "root") and hasattr(sct._impl.root, "value"):
                        sct._impl.root.value = twin
                        monitor = {"left": 0, "top": 0, "width": tw, "height": th}
                        console.print(f"[bold green][STREAM] Direct capture attached to game window {hex(twin)} ({tw}x{th})[/bold green]")
                elif not twin and current_target_win is not None:
                    current_target_win = None
                    try:
                        sct.close()
                    except Exception:
                        pass
                    sct, monitor = _try_init_sct()

            if sct and monitor and current_target_win:
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
                except Exception as ex:
                    try:
                        sct.close()
                    except Exception:
                        pass
                    sct = None
                    monitor = None
                    current_target_win = None
                    last_init_attempt = t0

            if not jpeg_bytes:
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

            work_time = time.time() - t0
            target_delay = 1.0 / max(self.min_fps, self.fps)
            rem = target_delay - work_time

            # Dynamic Auto-FPS adjustment (never drops below min_fps)
            if self.auto_fps:
                fps_adjust_interval += 1
                if fps_adjust_interval >= 10:
                    fps_adjust_interval = 0
                    if work_time > target_delay * 0.90:
                        # Capture is heavy, lower FPS towards min_fps
                        self.fps = max(self.min_fps, self.fps - 2)
                    elif work_time < target_delay * 0.65 and self.fps < self.max_fps:
                        # Plenty of headroom, scale up FPS towards max_fps
                        self.fps = min(self.max_fps, self.fps + 1)

            if rem > 0.001:
                time.sleep(rem)

    async def _broadcast_loop(self):
        """Asynchronously push the latest frame to connected phone clients."""
        interval = 1.0 / max(1, self.fps)
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
                            t_client = data.get("client_time") or data.get("time") or 0
                            await websocket.send(json.dumps({
                                "type": "pong",
                                "time": t_client,
                                "client_time": t_client,
                                "server_time": time.time() * 1000,
                                "fps": self.stats["fps"],
                                "target_fps": self.fps,
                                "quality": self.quality,
                                "preset": self.preset,
                                "auto_fps": self.auto_fps,
                            }))

                        elif msg_type == "settings":
                            if "preset" in data:
                                p_id = str(data["preset"]).lower()
                                if p_id in QUALITY_PRESETS:
                                    self.preset = p_id
                                    p_cfg = QUALITY_PRESETS[p_id]
                                    self.scale = p_cfg.get("scale", self.scale)
                                    self.quality = p_cfg.get("quality", self.quality)
                                    self.fps = p_cfg.get("fps", self.fps)
                                    self.target_fps = self.fps
                                    self.min_fps = p_cfg.get("min_fps", self.min_fps)
                                    self.max_fps = p_cfg.get("max_fps", self.max_fps)
                            if "quality" in data:
                                self.quality = max(30, min(100, int(data["quality"])))
                            if "fps" in data:
                                self.fps = max(30, min(144, int(data["fps"])))
                                self.target_fps = self.fps
                            if "min_fps" in data:
                                self.min_fps = max(24, min(60, int(data["min_fps"])))
                            if "auto_fps" in data:
                                self.auto_fps = bool(data["auto_fps"])
                            if "scale" in data:
                                self.scale = max(0.4, min(1.0, float(data["scale"])))
                            if "mode" in data:
                                self.gamepad.mode = data["mode"]

                            await websocket.send(json.dumps({
                                "type": "settings_ack",
                                "preset": self.preset,
                                "fps": self.fps,
                                "min_fps": self.min_fps,
                                "quality": self.quality,
                                "scale": self.scale,
                                "auto_fps": self.auto_fps,
                            }))
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
