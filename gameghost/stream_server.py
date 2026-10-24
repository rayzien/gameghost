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
from .config import load_config, QUALITY_PRESETS, log_host

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


class _XClassHint(Structure):
    _fields_ = [("res_name", ctypes.c_void_p), ("res_class", ctypes.c_void_p)]


class _XClientMessageEvent(Structure):
    _fields_ = [
        ("type", c_int),
        ("serial", c_ulong),
        ("send_event", c_int),
        ("display", ctypes.c_void_p),
        ("window", c_ulong),
        ("message_type", c_ulong),
        ("format", c_int),
        ("data", c_long * 5)
    ]


def _activate_game_window(win_id: int) -> bool:
    """Send _NET_ACTIVE_WINDOW to ensure the game is focused and rendered on the active workspace."""
    try:
        x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XDefaultRootWindow.restype = c_ulong
        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x11.XInternAtom.restype = c_ulong
        x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, c_int]
        x11.XSendEvent.restype = c_int
        x11.XSendEvent.argtypes = [ctypes.c_void_p, c_ulong, c_int, c_long, ctypes.POINTER(_XClientMessageEvent)]
        x11.XFlush.restype = c_int
        x11.XFlush.argtypes = [ctypes.c_void_p]
        x11.XCloseDisplay.restype = c_int
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]

        disp = x11.XOpenDisplay(None)
        if not disp:
            return False
        root = x11.XDefaultRootWindow(disp)
        atom_active = x11.XInternAtom(disp, b"_NET_ACTIVE_WINDOW", 0)
        ev = _XClientMessageEvent()
        ev.type = 33  # ClientMessage
        ev.window = win_id
        ev.message_type = atom_active
        ev.format = 32
        ev.data[0] = 2  # Source: pager/launcher
        ev.data[1] = 0
        ev.data[2] = 0
        ev.data[3] = 0
        ev.data[4] = 0
        x11.XSendEvent(disp, root, False, (1 << 19) | (1 << 20), byref(ev))
        x11.XFlush(disp)
        x11.XCloseDisplay(disp)
        return True
    except Exception:
        return False


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
        x11.XGetClassHint.restype = c_int
        x11.XGetClassHint.argtypes = [ctypes.c_void_p, c_ulong, POINTER(_XClassHint)]
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
            game_keywords = [
                "devil may cry", "dmc", "sekiro", "tekken", "polaris",
                "mortal kombat", "mk11", "metal gear", "mgr", "tomb raider", "rottr"
            ]
            system_exclusions = [
                "guard window", "desktop", "damx", "conky", "mutter",
                "explorer.exe", "rainmeter.exe", "winedevice.exe"
            ]
            for i in range(nchildren.value - 1, -1, -1):
                wid = children[i]
                attrs = _XWindowAttributes()
                if x11.XGetWindowAttributes(disp, wid, byref(attrs)):
                    if attrs.map_state == 2 and attrs.width >= 400 and attrs.height >= 300:
                        name_ptr = ctypes.c_char_p()
                        title = ""
                        if x11.XFetchName(disp, wid, byref(name_ptr)) and name_ptr.value:
                            title = name_ptr.value.decode("utf-8", "replace").lower()
                            x11.XFree(name_ptr)

                        hint = _XClassHint()
                        res_name, res_class = "", ""
                        if x11.XGetClassHint(disp, wid, byref(hint)):
                            if hint.res_name:
                                res_name = ctypes.string_at(hint.res_name).decode("utf-8", "replace").lower()
                                x11.XFree(hint.res_name)
                            if hint.res_class:
                                res_class = ctypes.string_at(hint.res_class).decode("utf-8", "replace").lower()
                                x11.XFree(hint.res_class)

                        combined = f"{title} {res_name} {res_class}"
                        if any(ex in combined for ex in system_exclusions):
                            continue

                        if any(k in combined for k in game_keywords) or (res_name.endswith(".exe") and not any(ex in res_name for ex in system_exclusions)):
                            best_win = wid
                            best_w, best_h = attrs.width, attrs.height
                            break

            if children:
                x11.XFree(children)
        x11.XCloseDisplay(disp)
        return best_win, best_w, best_h
    except Exception:
        return None, 0, 0


def _capture_x11_window(win_id: int, quality: int = 80, scale: float = 1.0) -> Optional[bytes]:
    """Direct hardware capture of an active X11 / Xwayland game window via XGetImage."""
    try:
        x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
        disp = x11.XOpenDisplay(None)
        if not disp:
            return None
        attrs = _XWindowAttributes()
        if not x11.XGetWindowAttributes(disp, win_id, byref(attrs)):
            x11.XCloseDisplay(disp)
            return None
        w, h = attrs.width, attrs.height
        if w < 100 or h < 100:
            x11.XCloseDisplay(disp)
            return None

        x11.XGetImage.restype = ctypes.c_void_p
        x11.XGetImage.argtypes = [ctypes.c_void_p, c_ulong, c_int, c_int, c_uint, c_uint, c_ulong, c_int]
        x11.XDestroyImage.restype = c_int
        x11.XDestroyImage.argtypes = [ctypes.c_void_p]

        img_ptr = x11.XGetImage(disp, win_id, 0, 0, w, h, 0xFFFFFFFF, 2)
        if not img_ptr:
            x11.XCloseDisplay(disp)
            return None

        class _XImage(Structure):
            _fields_ = [
                ("width", c_int), ("height", c_int),
                ("xoffset", c_int), ("format", c_int),
                ("data", ctypes.c_char_p),
                ("byte_order", c_int), ("bitmap_unit", c_int),
                ("bitmap_bit_order", c_int), ("bitmap_pad", c_int),
                ("depth", c_int), ("bytes_per_line", c_int),
                ("bits_per_pixel", c_int)
            ]

        ximage = _XImage.from_address(img_ptr)
        raw_bytes = ctypes.string_at(ximage.data, ximage.bytes_per_line * h)
        x11.XDestroyImage(img_ptr)
        x11.XCloseDisplay(disp)

        img = Image.frombytes("RGB", (w, h), raw_bytes, "raw", "BGRX")
        if scale != 1.0:
            new_w = max(320, int(w * scale))
            new_h = max(240, int(h * scale))
            img = img.resize((new_w, new_h), Image.BILINEAR)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=False)
        return buf.getvalue()
    except Exception:
        return None


class WaylandScreenCapture:
    """
    Direct hardware-accelerated screen capture on Wayland (GNOME/Mutter).
    Pulls video frames via Mutter ScreenCast D-Bus and PipeWire without black screen.
    """
    def __init__(self, quality: int = 80, scale: float = 1.0):
        self.quality = quality
        self.scale = scale
        self.bus = None
        self.sc_session_path = None
        self.stream_path = None
        self.pipewire_node = None
        self.pipeline = None
        self.sink = None
        self.width = 1920
        self.height = 1080
        self.active = False
        self.latest_frame: Optional[bytes] = None
        self.frame_id: int = 0
        self.lock = threading.Lock()
        self._reader_thread: Optional[threading.Thread] = None
        self._init_stream()

    def _init_stream(self):
        try:
            import gi
            gi.require_version("Gio", "2.0")
            gi.require_version("Gst", "1.0")
            from gi.repository import Gio, GLib, Gst
            Gst.init(None)

            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

            # Create Mutter ScreenCast session
            res = self.bus.call_sync(
                "org.gnome.Mutter.ScreenCast",
                "/org/gnome/Mutter/ScreenCast",
                "org.gnome.Mutter.ScreenCast",
                "CreateSession",
                GLib.Variant("(a{sv})", ({},)),
                None, Gio.DBusCallFlags.NONE, -1, None
            )
            self.sc_session_path = res.unpack()[0]

            # Record primary monitor
            res_stream = self.bus.call_sync(
                "org.gnome.Mutter.ScreenCast",
                self.sc_session_path,
                "org.gnome.Mutter.ScreenCast.Session",
                "RecordMonitor",
                GLib.Variant("(sa{sv})", ("", {})),
                None, Gio.DBusCallFlags.NONE, -1, None
            )
            self.stream_path = res_stream.unpack()[0]

            def on_signal(conn, sender_name, object_path, interface_name, signal_name, parameters, user_data):
                if signal_name == "PipeWireStreamAdded":
                    self.pipewire_node = parameters.unpack()[0]

            self.bus.signal_subscribe(
                "org.gnome.Mutter.ScreenCast",
                "org.gnome.Mutter.ScreenCast.Stream",
                "PipeWireStreamAdded",
                self.stream_path,
                None, Gio.DBusSignalFlags.NONE,
                on_signal, None
            )

            # Start session
            self.bus.call_sync(
                "org.gnome.Mutter.ScreenCast",
                self.sc_session_path,
                "org.gnome.Mutter.ScreenCast.Session",
                "Start",
                None, None, Gio.DBusCallFlags.NONE, -1, None
            )

            loop = GLib.MainLoop()
            def check_node():
                if self.pipewire_node is not None:
                    loop.quit()
                    return False
                return True
            GLib.timeout_add(20, check_node)
            GLib.timeout_add(2000, loop.quit)
            loop.run()

            if not self.pipewire_node:
                self.close()
                return

            pipeline_str = (
                f"pipewiresrc path={self.pipewire_node} ! videoconvert n-threads=2 ! "
                f"jpegenc quality={self.quality} idct-method=ifast ! "
                f"appsink name=sink emit-signals=True max-buffers=1 drop=True sync=False"
            )
            self.pipeline = Gst.parse_launch(pipeline_str)
            self.sink = self.pipeline.get_by_name("sink")
            self.pipeline.set_state(Gst.State.PLAYING)
            self.active = True

            self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self._reader_thread.start()

        except Exception:
            self.active = False
            self.close()

    def _reader_loop(self):
        try:
            import gi
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst
        except Exception:
            return

        while self.active and self.sink:
            try:
                sample = self.sink.emit("pull-sample")
                if sample:
                    buf = sample.get_buffer()
                    caps = sample.get_caps()
                    if caps and caps.get_size() > 0:
                        s = caps.get_structure(0)
                        if s.has_field("width") and s.has_field("height"):
                            self.width = s.get_value("width")
                            self.height = s.get_value("height")
                    success, map_info = buf.map(Gst.MapFlags.READ)
                    if success:
                        data = bytes(map_info.data)
                        buf.unmap(map_info)
                        with self.lock:
                            self.latest_frame = data
                            self.frame_id += 1
                else:
                    time.sleep(0.005)
            except Exception:
                time.sleep(0.01)

    def get_latest_frame(self) -> Tuple[int, Optional[bytes]]:
        with self.lock:
            return self.frame_id, self.latest_frame

    def close(self):
        self.active = False
        try:
            if self.pipeline:
                self.pipeline.set_state(0)
        except Exception:
            pass

        try:
            if self.bus and self.sc_session_path:
                from gi.repository import Gio
                self.bus.call_sync(
                    "org.gnome.Mutter.ScreenCast",
                    self.sc_session_path,
                    "org.gnome.Mutter.ScreenCast.Session",
                    "Stop",
                    None, None, Gio.DBusCallFlags.NONE, -1, None
                )
        except Exception:
            pass


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
        is_wayland = bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland")
        wayland_cap = None
        if is_wayland:
            try:
                wayland_cap = WaylandScreenCapture(quality=self.quality, scale=self.scale)
                if wayland_cap.active:
                    console.print(f"[bold green][STREAM] Attached to Wayland screen ({wayland_cap.width}x{wayland_cap.height}) via Mutter ScreenCast + PipeWire[/bold green]")
                else:
                    wayland_cap = None
            except Exception:
                wayland_cap = None

        self.wayland_cap = wayland_cap

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
        last_wayland_frame_id = -1

        if not sct and not (wayland_cap and wayland_cap.active):
            console.print("[STREAM] Display capture not immediately ready. Activating standby game visualizer until display connects.")

        frame_count = 0
        last_fps_time = time.time()
        fps_adjust_interval = 0

        while self.running:
            t0 = time.time()
            jpeg_bytes = None

            # 1. Primary: Wayland ScreenCast capture
            if wayland_cap and wayland_cap.active:
                f_id, f_bytes = wayland_cap.get_latest_frame()
                if f_bytes and f_id != last_wayland_frame_id:
                    last_wayland_frame_id = f_id
                    jpeg_bytes = f_bytes

            # 2. Re-init sct if needed
            if not jpeg_bytes:
                if sct is None or monitor is None:
                    if t0 - last_init_attempt >= 1.5:
                        last_init_attempt = t0
                        sct, monitor = _try_init_sct()
                        current_target_win = None

            # Periodically scan for active game window to bring it to focus and active workspace
            if t0 - last_win_check >= 1.5 or current_target_win is None:
                last_win_check = t0
                twin, tw, th = _find_target_game_window()
                if twin and twin != current_target_win:
                    current_target_win = twin
                    _activate_game_window(twin)
                    console.print(f"[bold green][STREAM] Attached & focused game window {hex(twin)} ({tw}x{th})[/bold green]")
                elif not twin and current_target_win is not None:
                    current_target_win = None

            # 3. MSS Root Window Capture with black-screen detection
            if not jpeg_bytes and sct and monitor:
                try:
                    raw = sct.grab(monitor)
                    is_black = False
                    if len(raw.bgra) > 100:
                        # Fast check for pure black frame from Xwayland/blank monitor
                        is_black = (
                            raw.bgra[0:16] == b'\x00' * 16 and
                            raw.bgra[len(raw.bgra)//2:len(raw.bgra)//2 + 16] == b'\x00' * 16 and
                            raw.bgra[-16:] == b'\x00' * 16
                        )

                    # If root capture is black, try direct window capture of target game
                    if is_black and current_target_win:
                        win_frame = _capture_x11_window(current_target_win, quality=self.quality, scale=self.scale)
                        if win_frame:
                            jpeg_bytes = win_frame

                    if not jpeg_bytes and not is_black:
                        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
                        if self.scale != 1.0:
                            new_w = max(320, int(img.width * self.scale))
                            new_h = max(240, int(img.height * self.scale))
                            img = img.resize((new_w, new_h), Image.BILINEAR)

                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=self.quality, optimize=False)
                        jpeg_bytes = buf.getvalue()
                except Exception:
                    try:
                        sct.close()
                    except Exception:
                        pass
                    sct = None
                    monitor = None
                    last_init_attempt = t0

            # 4. Fallback: Styled Host Standby Frame (never emit raw black void)
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
                        self.fps = max(self.min_fps, self.fps - 2)
                    elif work_time < target_delay * 0.65 and self.fps < self.max_fps:
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

                        if msg_type in ("btn", "stick", "trigger", "dpad", "mouse_move", "mouse_btn", "mouse_scroll", "key"):
                            self.gamepad.handle_packet(data)

                        elif msg_type == "launch":
                            game_id = data.get("game", "dmc5")
                            console.print(f"[bold green][REMOTE LAUNCH][/bold green] Phone requested launch of: {game_id}")
                            log_host(f"Client requested launch of game: {game_id}")
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
            log_host(f"Client disconnected: {client_addr}")

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
        if hasattr(self, "wayland_cap") and self.wayland_cap:
            try:
                self.wayland_cap.close()
            except Exception:
                pass
        self.gamepad.close()
