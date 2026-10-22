import os
import io
import time
import json
import queue
import math
import threading
import asyncio
from typing import Optional, Tuple, Dict, Any, List

import pygame
import pygame.gfxdraw
import websockets
from rich.console import Console

from .config import load_config, get_last_host, save_last_host, probe_host
from .discovery import GameDiscovery, scan_hotspot_subnet

console = Console()


def calculate_letterbox(win_w: int, win_h: int, frame_w: int, frame_h: int) -> Tuple[int, int, int, int]:
    """Calculate scaled dimensions preserving aspect ratio."""
    scale = min(win_w / frame_w, win_h / frame_h)
    draw_w = int(frame_w * scale)
    draw_h = int(frame_h * scale)
    offset_x = (win_w - draw_w) // 2
    offset_y = (win_h - draw_h) // 2
    return draw_w, draw_h, offset_x, offset_y


class GameGhostViewer:
    """
    Native Pygame / SDL2 Handheld Client.
    Connects to GameGhost Host, renders video in Landscape mode,
    and provides a native multi-touch on-screen gamepad overlay.
    """

    def __init__(self, host_ip: str, port: int = 8900, fullscreen: bool = True, launch_game: Optional[str] = None):
        self.host_ip = host_ip
        self.port = port
        self.uri = f"ws://{host_ip}:{port}"
        self.fullscreen = fullscreen
        self.launch_game = launch_game
        self.running = False
        self.connected = False

        # Mesa, EGL, DRI2 & Zink error mitigation:
        # Prevents 'failed to choose pdev', 'DRI2 screen failed', and 'zink' crashes in Termux / Linux
        if "LIBGL_ALWAYS_SOFTWARE" not in os.environ:
            os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
        if "GALLIUM_DRIVER" not in os.environ:
            os.environ["GALLIUM_DRIVER"] = "llvmpipe"
        if "MESA_LOADER_DRIVER_OVERRIDE" not in os.environ:
            os.environ["MESA_LOADER_DRIVER_OVERRIDE"] = "llvmpipe"
        if "SDL_RENDER_DRIVER" not in os.environ:
            os.environ["SDL_RENDER_DRIVER"] = "software"
        os.environ["SDL_VIDEO_X11_NODIRECTCOLOR"] = "1"
        os.environ["SDL_VIDEO_X11_NET_WM_BYPASS_COMPOSITOR"] = "0"

        # Force Landscape Orientation Environment Hints for SDL2 & Termux-X11
        os.environ["SDL_VIDEO_ALLOW_SCREENSAVER"] = "0"
        os.environ["SDL_HINT_ORIENTATIONS"] = "LandscapeLeft LandscapeRight"
        os.environ["SDL_HINT_QTWAYLAND_CONTENT_ORIENTATION"] = "landscape"

        self.win_w = 1280
        self.win_h = 720
        self.frame_queue = queue.Queue(maxsize=2)
        self.out_queue = queue.Queue()

        self.fps = 0
        self.frame_count = 0
        self.last_fps_time = time.time()
        self.show_overlay = True

        # Multi-touch tracking: finger_id -> {"target": "left_stick|right_stick|button", "data": ...}
        self.active_touches: Dict[int, Dict[str, Any]] = {}

        # Touch Layout geometry
        self.controls: Dict[str, Any] = {}
        self.left_stick = {"base_x": 0, "base_y": 0, "knob_x": 0, "knob_y": 0, "radius": 75, "val_x": 0.0, "val_y": 0.0}
        self.right_stick = {"base_x": 0, "base_y": 0, "knob_x": 0, "knob_y": 0, "radius": 75, "val_x": 0.0, "val_y": 0.0}
        self.buttons: Dict[str, Dict[str, Any]] = {}

    def _update_layout(self):
        """Update virtual gamepad positions relative to screen dimensions (Landscape layout)."""
        w, h = self.win_w, self.win_h

        # Left Thumbstick (Bottom Left)
        ls_x = int(w * 0.14)
        ls_y = int(h * 0.72)
        ls_r = int(min(w, h) * 0.14)
        self.left_stick = {
            "base_x": ls_x,
            "base_y": ls_y,
            "knob_x": ls_x,
            "knob_y": ls_y,
            "radius": ls_r,
            "val_x": 0.0,
            "val_y": 0.0
        }

        # Right Thumbstick (Bottom Right)
        rs_x = int(w * 0.86)
        rs_y = int(h * 0.72)
        rs_r = int(min(w, h) * 0.14)
        self.right_stick = {
            "base_x": rs_x,
            "base_y": rs_y,
            "knob_x": rs_x,
            "knob_y": rs_y,
            "radius": rs_r,
            "val_x": 0.0,
            "val_y": 0.0
        }

        # Face Buttons (Y, X, B, A)
        btn_r = int(min(w, h) * 0.065)
        face_cx = int(w * 0.87)
        face_cy = int(h * 0.32)
        spacing = int(btn_r * 2.2)

        # D-Pad
        dpad_cx = int(w * 0.13)
        dpad_cy = int(h * 0.32)
        dpad_s = int(btn_r * 2.0)

        self.buttons = {
            # Face Buttons
            "Y": {"x": face_cx, "y": face_cy - spacing, "r": btn_r, "type": "btn", "name": "Y", "color": (255, 220, 0), "label": "Y"},
            "A": {"x": face_cx, "y": face_cy + spacing, "r": btn_r, "type": "btn", "name": "A", "color": (50, 220, 50), "label": "A"},
            "X": {"x": face_cx - spacing, "y": face_cy, "r": btn_r, "type": "btn", "name": "X", "color": (50, 150, 255), "label": "X"},
            "B": {"x": face_cx + spacing, "y": face_cy, "r": btn_r, "type": "btn", "name": "B", "color": (255, 60, 60), "label": "B"},

            # D-Pad
            "DPAD_UP":    {"x": dpad_cx, "y": dpad_cy - dpad_s, "r": btn_r, "type": "dpad", "name": "DPAD_UP", "dir": "up", "color": (160, 160, 160), "label": "^"},
            "DPAD_DOWN":  {"x": dpad_cx, "y": dpad_cy + dpad_s, "r": btn_r, "type": "dpad", "name": "DPAD_DOWN", "dir": "down", "color": (160, 160, 160), "label": "v"},
            "DPAD_LEFT":  {"x": dpad_cx - dpad_s, "y": dpad_cy, "r": btn_r, "type": "dpad", "name": "DPAD_LEFT", "dir": "left", "color": (160, 160, 160), "label": "<"},
            "DPAD_RIGHT": {"x": dpad_cx + dpad_s, "y": dpad_cy, "r": btn_r, "type": "dpad", "name": "DPAD_RIGHT", "dir": "right", "color": (160, 160, 160), "label": ">"},

            # Shoulders & Triggers
            "L1": {"x": int(w * 0.12), "y": int(h * 0.08), "r": int(btn_r * 1.1), "type": "btn", "name": "LB", "color": (0, 210, 255), "label": "L1"},
            "L2": {"x": int(w * 0.23), "y": int(h * 0.08), "r": int(btn_r * 1.1), "type": "trigger", "name": "LT", "color": (0, 170, 230), "label": "L2"},
            "R1": {"x": int(w * 0.88), "y": int(h * 0.08), "r": int(btn_r * 1.1), "type": "btn", "name": "RB", "color": (0, 210, 255), "label": "R1"},
            "R2": {"x": int(w * 0.77), "y": int(h * 0.08), "r": int(btn_r * 1.1), "type": "trigger", "name": "RT", "color": (0, 170, 230), "label": "R2"},

            # Center System Buttons
            "SELECT": {"x": int(w * 0.42), "y": int(h * 0.08), "r": int(btn_r * 0.7), "type": "btn", "name": "SELECT", "color": (200, 200, 200), "label": "SHR"},
            "HOME":   {"x": int(w * 0.50), "y": int(h * 0.08), "r": int(btn_r * 0.7), "type": "btn", "name": "HOME", "color": (0, 210, 255), "label": "PS"},
            "START":  {"x": int(w * 0.58), "y": int(h * 0.08), "r": int(btn_r * 0.7), "type": "btn", "name": "START", "color": (200, 200, 200), "label": "OPT"},
        }

    def _network_thread(self):
        """Asynchronous background worker communicating with the GameGhost host."""
        async def _client_loop():
            while self.running:
                try:
                    console.print(f"[bold cyan][CONNECT][/bold cyan] Connecting to GameGhost host at {self.uri}...")
                    async with websockets.connect(
                        self.uri,
                        max_size=15 * 1024 * 1024,
                        ping_interval=20,
                        ping_timeout=20
                    ) as ws:
                        self.connected = True
                        console.print(f"[bold green][CONNECTED][/bold green] Stream active: {self.uri}")

                        # Trigger remote launch if game specified
                        if self.launch_game:
                            await ws.send(json.dumps({"type": "launch", "game": self.launch_game}))
                            console.print(f"[bold green][REMOTE LAUNCH][/bold green] Requested PC to launch: {self.launch_game}")

                        async def _recv_frames():
                            while self.running and self.connected:
                                msg = await ws.recv()
                                if isinstance(msg, bytes):
                                    if self.frame_queue.full():
                                        try:
                                            self.frame_queue.get_nowait()
                                        except queue.Empty:
                                            pass
                                    self.frame_queue.put(msg)
                                elif isinstance(msg, str):
                                    try:
                                        data = json.loads(msg)
                                        if data.get("type") == "launch_ack":
                                            succ = data.get("success", False)
                                            g = data.get("game", "")
                                            status = "Started successfully" if succ else "Failed to start"
                                            console.print(f"[bold green][PC RESPONSE][/bold green] {g}: {status}")
                                    except Exception:
                                        pass

                        async def _send_events():
                            while self.running and self.connected:
                                try:
                                    packet = self.out_queue.get_nowait()
                                    await ws.send(json.dumps(packet))
                                except queue.Empty:
                                    await asyncio.sleep(0.004)

                        await asyncio.gather(_recv_frames(), _send_events())

                except Exception as ex:
                    self.connected = False
                    if self.running:
                        await asyncio.sleep(1.5)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_client_loop())

    def send_input(self, packet: dict):
        self.out_queue.put(packet)

    def _handle_touch_down(self, finger_id: int, px: float, py: float):
        """Process touch down event at screen coordinates (px, py)."""
        # 1. Check left stick zone
        ls = self.left_stick
        dist_ls = math.hypot(px - ls["base_x"], py - ls["base_y"])
        if dist_ls <= ls["radius"] * 1.5:
            self.active_touches[finger_id] = {"target": "left_stick"}
            self._update_stick("left", px, py)
            return

        # 2. Check right stick zone
        rs = self.right_stick
        dist_rs = math.hypot(px - rs["base_x"], py - rs["base_y"])
        if dist_rs <= rs["radius"] * 1.5:
            self.active_touches[finger_id] = {"target": "right_stick"}
            self._update_stick("right", px, py)
            return

        # 3. Check buttons
        for bkey, binfo in self.buttons.items():
            dist = math.hypot(px - binfo["x"], py - binfo["y"])
            if dist <= binfo["r"] * 1.3:
                self.active_touches[finger_id] = {"target": "button", "bkey": bkey}
                self._dispatch_button(binfo, 1)
                return

    def _handle_touch_motion(self, finger_id: int, px: float, py: float):
        """Process touch drag/motion for sticks."""
        touch = self.active_touches.get(finger_id)
        if not touch:
            return

        target = touch.get("target")
        if target == "left_stick":
            self._update_stick("left", px, py)
        elif target == "right_stick":
            self._update_stick("right", px, py)

    def _handle_touch_up(self, finger_id: int):
        """Process touch release."""
        touch = self.active_touches.pop(finger_id, None)
        if not touch:
            return

        target = touch.get("target")
        if target == "left_stick":
            self.left_stick["knob_x"] = self.left_stick["base_x"]
            self.left_stick["knob_y"] = self.left_stick["base_y"]
            self.send_input({"type": "stick", "which": "left", "x": 0.0, "y": 0.0})
        elif target == "right_stick":
            self.right_stick["knob_x"] = self.right_stick["base_x"]
            self.right_stick["knob_y"] = self.right_stick["base_y"]
            self.send_input({"type": "stick", "which": "right", "x": 0.0, "y": 0.0})
        elif target == "button":
            bkey = touch.get("bkey")
            if bkey in self.buttons:
                self._dispatch_button(self.buttons[bkey], 0)

    def _update_stick(self, which: str, px: float, py: float):
        st = self.left_stick if which == "left" else self.right_stick
        dx = px - st["base_x"]
        dy = py - st["base_y"]
        dist = math.hypot(dx, dy)
        max_r = st["radius"]

        if dist > max_r:
            angle = math.atan2(dy, dx)
            dx = math.cos(angle) * max_r
            dy = math.sin(angle) * max_r

        st["knob_x"] = int(st["base_x"] + dx)
        st["knob_y"] = int(st["base_y"] + dy)

        norm_x = dx / max_r
        norm_y = -(dy / max_r)
        self.send_input({"type": "stick", "which": which, "x": norm_x, "y": norm_y})

    def _dispatch_button(self, binfo: dict, val: int):
        btype = binfo["type"]
        if btype == "btn":
            self.send_input({"type": "btn", "name": binfo["name"], "val": val})
        elif btype == "trigger":
            self.send_input({"type": "trigger", "name": binfo["name"], "val": 1.0 if val else 0.0})
        elif btype == "dpad":
            self.send_input({"type": "dpad", "dir": binfo["dir"], "val": val})

    def _draw_hud(self, surface: pygame.Surface, font: pygame.font.Font):
        if not self.show_overlay:
            return

        overlay = pygame.Surface((self.win_w, self.win_h), pygame.SRCALPHA)

        # Draw Left Stick
        ls = self.left_stick
        pygame.gfxdraw.filled_circle(overlay, ls["base_x"], ls["base_y"], ls["radius"], (30, 40, 55, 120))
        pygame.gfxdraw.aacircle(overlay, ls["base_x"], ls["base_y"], ls["radius"], (0, 210, 255, 180))
        knob_r = int(ls["radius"] * 0.45)
        pygame.gfxdraw.filled_circle(overlay, ls["knob_x"], ls["knob_y"], knob_r, (0, 210, 255, 190))
        pygame.gfxdraw.aacircle(overlay, ls["knob_x"], ls["knob_y"], knob_r, (255, 255, 255, 220))

        # Draw Right Stick
        rs = self.right_stick
        pygame.gfxdraw.filled_circle(overlay, rs["base_x"], rs["base_y"], rs["radius"], (30, 40, 55, 120))
        pygame.gfxdraw.aacircle(overlay, rs["base_x"], rs["base_y"], rs["radius"], (0, 210, 255, 180))
        pygame.gfxdraw.filled_circle(overlay, rs["knob_x"], rs["knob_y"], knob_r, (0, 210, 255, 190))
        pygame.gfxdraw.aacircle(overlay, rs["knob_x"], rs["knob_y"], knob_r, (255, 255, 255, 220))

        # Draw Action Buttons
        for bkey, binfo in self.buttons.items():
            bx, by, br = binfo["x"], binfo["y"], binfo["r"]
            color = binfo["color"]
            pygame.gfxdraw.filled_circle(overlay, bx, by, br, (color[0], color[1], color[2], 120))
            pygame.gfxdraw.aacircle(overlay, bx, by, br, (color[0], color[1], color[2], 220))

            lbl = font.render(binfo["label"], True, (255, 255, 255))
            overlay.blit(lbl, (bx - lbl.get_width() // 2, by - lbl.get_height() // 2))

        # Status text
        status_color = (0, 230, 118) if self.connected else (255, 82, 82)
        status_text = f"GAMEGHOST // FPS: {self.fps} | {'CONNECTED' if self.connected else 'SEARCHING'}"
        lbl_status = font.render(status_text, True, status_color)
        overlay.blit(lbl_status, (20, 20))

        surface.blit(overlay, (0, 0))

    def start(self):
        """Main Pygame / SDL2 display and event loop (Forced Landscape Mode)."""
        # Set landscape orientation hints before initializing pygame display
        os.environ["SDL_VIDEO_ALLOW_SCREENSAVER"] = "0"
        os.environ["SDL_HINT_ORIENTATIONS"] = "LandscapeLeft LandscapeRight"
        os.environ["SDL_HINT_QTWAYLAND_CONTENT_ORIENTATION"] = "landscape"

        pygame.init()
        pygame.font.init()

        # Query native display resolution to ensure landscape
        try:
            display_info = pygame.display.Info()
            dw = display_info.current_w
            dh = display_info.current_h
            if dw > 0 and dh > 0:
                # Force landscape: width must always be the larger dimension
                self.win_w = max(dw, dh)
                self.win_h = min(dw, dh)
            else:
                self.win_w = 1280
                self.win_h = 720
        except Exception:
            self.win_w = 1280
            self.win_h = 720

        flags = pygame.DOUBLEBUF | pygame.RESIZABLE
        if self.fullscreen:
            flags |= pygame.FULLSCREEN

        try:
            screen = pygame.display.set_mode((self.win_w, self.win_h), flags)
        except pygame.error:
            flags = pygame.DOUBLEBUF
            screen = pygame.display.set_mode((self.win_w, self.win_h), flags)
        pygame.display.set_caption("GameGhost Handheld Portal (Landscape)")
        font = pygame.font.SysFont("monospace", 14, bold=True)

        self._update_layout()
        self.running = True

        # Start network worker thread
        t_net = threading.Thread(target=self._network_thread, daemon=True)
        t_net.start()

        clock = pygame.time.Clock()
        current_game_surface: Optional[pygame.Surface] = None

        while self.running:
            # 1. Process Pygame events (Touches, Gamepads, Resize, Keys)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False

                elif event.type == pygame.VIDEORESIZE:
                    # Enforce landscape dimensions
                    self.win_w = max(event.w, event.h)
                    self.win_h = min(event.w, event.h)
                    screen = pygame.display.set_mode((self.win_w, self.win_h), flags)
                    self._update_layout()

                # Native Multi-Touch Events (SDL2 / Termux / Touchscreens)
                elif event.type == pygame.FINGERDOWN:
                    px = event.x * self.win_w
                    py = event.y * self.win_h
                    self._handle_touch_down(event.finger_id, px, py)

                elif event.type == pygame.FINGERMOTION:
                    px = event.x * self.win_w
                    py = event.y * self.win_h
                    self._handle_touch_motion(event.finger_id, px, py)

                elif event.type == pygame.FINGERUP:
                    self._handle_touch_up(event.finger_id)

                # Mouse Fallback (Single pointer testing on PC)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self._handle_touch_down(999, event.pos[0], event.pos[1])

                elif event.type == pygame.MOUSEMOTION and (event.buttons[0] == 1):
                    self._handle_touch_motion(999, event.pos[0], event.pos[1])

                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    self._handle_touch_up(999)

                # Keyboard hotkeys
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_F11:
                        self.fullscreen = not self.fullscreen
                        flags_fs = pygame.DOUBLEBUF | pygame.RESIZABLE
                        if self.fullscreen:
                            flags_fs |= pygame.FULLSCREEN
                        try:
                            screen = pygame.display.set_mode((self.win_w, self.win_h), flags_fs)
                        except pygame.error:
                            pass
                        self._update_layout()
                    elif event.key == pygame.K_h:
                        self.show_overlay = not self.show_overlay
                    elif event.key == pygame.K_ESCAPE:
                        self.running = False

            # 2. Decompress latest video frame from queue
            try:
                frame_bytes = self.frame_queue.get_nowait()
                current_game_surface = pygame.image.load(io.BytesIO(frame_bytes)).convert()
                self.frame_count += 1
            except queue.Empty:
                pass

            now = time.time()
            if now - self.last_fps_time >= 1.0:
                self.fps = self.frame_count
                self.frame_count = 0
                self.last_fps_time = now

            # 3. Render Game Screen
            screen.fill((5, 7, 10))

            if current_game_surface:
                draw_w, draw_h, off_x, off_y = calculate_letterbox(
                    self.win_w, self.win_h,
                    current_game_surface.get_width(),
                    current_game_surface.get_height()
                )
                if draw_w != current_game_surface.get_width() or draw_h != current_game_surface.get_height():
                    scaled = pygame.transform.scale(current_game_surface, (draw_w, draw_h))
                    screen.blit(scaled, (off_x, off_y))
                else:
                    screen.blit(current_game_surface, (off_x, off_y))
            else:
                loading_msg = font.render(f"Waiting for Game Stream from {self.host_ip}...", True, (0, 210, 255))
                screen.blit(loading_msg, (self.win_w // 2 - loading_msg.get_width() // 2, self.win_h // 2))

            # 4. Render On-Screen Gamepad Overlay
            self._draw_hud(screen, font)

            pygame.display.flip()
            clock.tick(60)

        pygame.quit()


def run_client(host_ip: Optional[str] = None, fullscreen: bool = True, launch_game: Optional[str] = None):
    """Entry point for native GameGhost handheld client in Landscape Mode."""
    if "DISPLAY" not in os.environ and os.path.exists("/data/data/com.termux/files"):
        os.environ["DISPLAY"] = ":0"

    if not host_ip:
        # Fast-path: Check last connected host
        last = get_last_host()
        if last and probe_host(last):
            host_ip = last
            console.print(f"[bold green][FOUND] Reconnected to last PC host: {host_ip}[/bold green]")
        else:
            console.print("[bold yellow][DISCOVERY] Looking for Gaming PC host on network...[/bold yellow]")
            disc = GameDiscovery()
            disc.start_listener()
            host_info = disc.find_host(timeout=2.0)
            disc.stop()

            if host_info:
                host_ip = host_info.get("ip")
                console.print(f"[bold green][FOUND] Detected Gaming PC host: {host_ip}[/bold green]")
            else:
                # Subnet scan fallback
                candidates = scan_hotspot_subnet(port=8900)
                if candidates:
                    host_ip = candidates[0]
                    console.print(f"[bold green][FOUND] Detected host via subnet scan: {host_ip}[/bold green]")
                else:
                    console.print("[bold red][ERR] Could not auto-detect GameGhost host. Please specify IP directly:[/bold red]")
                    console.print("   gameghost client <HOST_IP>")
                    return

    save_last_host(host_ip)
    viewer = GameGhostViewer(host_ip=host_ip, port=8900, fullscreen=fullscreen, launch_game=launch_game)
    viewer.start()
