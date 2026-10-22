import os
import sys

# Mesa, EGL, DRI2 & Zink error mitigation:
# Prevents 'failed to choose pdev', 'DRI2 screen failed', and 'zink' crashes in Termux / Linux
os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
os.environ["GALLIUM_DRIVER"] = "llvmpipe"
os.environ["MESA_LOADER_DRIVER_OVERRIDE"] = "llvmpipe"
os.environ["SDL_RENDER_DRIVER"] = "software"
os.environ["SDL_VIDEO_X11_NODIRECTCOLOR"] = "1"
os.environ["SDL_VIDEO_X11_NET_WM_BYPASS_COMPOSITOR"] = "0"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
os.environ["MESA_DEBUG"] = "silent"
os.environ["EGL_LOG_LEVEL"] = "fatal"

# Force Landscape Orientation Environment Hints for SDL2 & Termux-X11
os.environ["SDL_VIDEO_ALLOW_SCREENSAVER"] = "0"
os.environ["SDL_HINT_ORIENTATIONS"] = "LandscapeLeft LandscapeRight"
os.environ["SDL_HINT_QTWAYLAND_CONTENT_ORIENTATION"] = "landscape"

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

# Hardware Gamepad standard button mapping (Xbox 360 / Generic SDL2 layout)
JOY_BTN_MAP = {
    0: "A",
    1: "B",
    2: "X",
    3: "Y",
    4: "LB",
    5: "RB",
    6: "SELECT",
    7: "START",
    8: "HOME",
    9: "L3",
    10: "R3",
}

# Physical Keyboard mapping fallback (DMC5 / Action RPG control scheme)
KEY_BTN_MAP = {
    pygame.K_SPACE: "A",
    pygame.K_RETURN: "START",
    pygame.K_TAB: "SELECT",
    pygame.K_BACKSPACE: "SELECT",
    pygame.K_j: "X",
    pygame.K_k: "B",
    pygame.K_i: "Y",
    pygame.K_u: "A",
    pygame.K_q: "LB",
    pygame.K_e: "RB",
    pygame.K_1: "LT",
    pygame.K_3: "RT",
    pygame.K_z: "L3",
    pygame.K_c: "R3",
}

KEY_DPAD_MAP = {
    pygame.K_UP: (0, -1, "up"),
    pygame.K_DOWN: (0, 1, "down"),
    pygame.K_LEFT: (-1, 0, "left"),
    pygame.K_RIGHT: (1, 0, "right"),
}


def safe_set_mode(size: Tuple[int, int], flags: int) -> pygame.Surface:
    """Initialize display surface while suppressing C-level Mesa/EGL noise to stderr."""
    saved_stderr = None
    try:
        stderr_fd = sys.stderr.fileno()
        saved_stderr = os.dup(stderr_fd)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, stderr_fd)
        os.close(devnull)
    except Exception:
        pass

    try:
        return pygame.display.set_mode(size, flags)
    finally:
        if saved_stderr is not None:
            try:
                os.dup2(saved_stderr, stderr_fd)
                os.close(saved_stderr)
            except Exception:
                pass


def calculate_letterbox(win_w: int, win_h: int, frame_w: int, frame_h: int) -> Tuple[int, int, int, int]:
    """Calculate scaled dimensions preserving aspect ratio."""
    if frame_w <= 0 or frame_h <= 0:
        return win_w, win_h, 0, 0
    scale = min(win_w / frame_w, win_h / frame_h)
    draw_w = max(1, int(frame_w * scale))
    draw_h = max(1, int(frame_h * scale))
    offset_x = (win_w - draw_w) // 2
    offset_y = (win_h - draw_h) // 2
    return draw_w, draw_h, offset_x, offset_y


class GameGhostViewer:
    """
    Native Pygame / SDL2 Handheld Client.
    Connects to GameGhost Host, renders video in Landscape mode,
    supports physical gamepads + keyboards, and provides a native
    multi-touch on-screen gamepad overlay.
    """

    def __init__(self, host_ip: str, port: int = 8900, fullscreen: bool = True, launch_game: Optional[str] = None):
        self.host_ip = host_ip
        self.port = port
        self.uri = f"ws://{host_ip}:{port}"
        self.fullscreen = fullscreen
        self.launch_game = launch_game
        self.running = False
        self.connected = False
        self.latency_ms = 0

        self.win_w = 1280
        self.win_h = 720
        self.frame_queue = queue.Queue(maxsize=2)
        # Bounded input queue prevents memory leak and input burst on reconnect
        self.out_queue = queue.Queue(maxsize=64)

        self.fps = 0
        self.frame_count = 0
        self.last_fps_time = time.time()
        self.show_overlay = True

        # Physical Joysticks / Hardware Controllers (Bluetooth, USB OTG, Kishi, Backbone)
        self.joysticks: Dict[int, pygame.joystick.Joystick] = {}

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

        # Button radius & centers
        btn_r = int(min(w, h) * 0.065)
        face_cx = int(w * 0.87)
        face_cy = int(h * 0.32)
        spacing = int(btn_r * 2.2)

        dpad_cx = int(w * 0.13)
        dpad_cy = int(h * 0.32)
        dpad_s = int(btn_r * 2.0)

        self.buttons = {
            # Face Buttons (Xbox 360 / PS colors)
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
            "L1": {"x": int(w * 0.12), "y": int(h * 0.08), "r": int(btn_r * 1.05), "type": "btn", "name": "LB", "color": (0, 210, 255), "label": "L1"},
            "L2": {"x": int(w * 0.23), "y": int(h * 0.08), "r": int(btn_r * 1.05), "type": "trigger", "name": "LT", "color": (0, 170, 230), "label": "L2"},
            "R1": {"x": int(w * 0.88), "y": int(h * 0.08), "r": int(btn_r * 1.05), "type": "btn", "name": "RB", "color": (0, 210, 255), "label": "R1"},
            "R2": {"x": int(w * 0.77), "y": int(h * 0.08), "r": int(btn_r * 1.05), "type": "trigger", "name": "RT", "color": (0, 170, 230), "label": "R2"},

            # Thumbstick Click Buttons (L3 / R3)
            "L3": {"x": int(ls_x), "y": int(ls_y - ls_r - btn_r * 0.9), "r": int(btn_r * 0.8), "type": "btn", "name": "L3", "color": (120, 180, 230), "label": "L3"},
            "R3": {"x": int(rs_x), "y": int(rs_y - rs_r - btn_r * 0.9), "r": int(btn_r * 0.8), "type": "btn", "name": "R3", "color": (120, 180, 230), "label": "R3"},

            # Center System Buttons
            "SELECT": {"x": int(w * 0.42), "y": int(h * 0.08), "r": int(btn_r * 0.65), "type": "btn", "name": "SELECT", "color": (200, 200, 200), "label": "SHR"},
            "HOME":   {"x": int(w * 0.50), "y": int(h * 0.08), "r": int(btn_r * 0.65), "type": "btn", "name": "HOME", "color": (0, 210, 255), "label": "PS"},
            "START":  {"x": int(w * 0.58), "y": int(h * 0.08), "r": int(btn_r * 0.65), "type": "btn", "name": "START", "color": (200, 200, 200), "label": "OPT"},
        }

    def send_input(self, packet: dict):
        """Queue input packet for delivery to host PC with overflow protection."""
        if not self.connected:
            return
        try:
            if self.out_queue.full():
                try:
                    self.out_queue.get_nowait()
                except queue.Empty:
                    pass
            self.out_queue.put_nowait(packet)
        except Exception:
            pass

    def _network_thread(self):
        """
        Asynchronous background worker communicating with the GameGhost PC host.
        Seamlessly reconnects when PC host is turned on or IP changes.
        """
        async def _client_loop():
            last_search_log = 0.0
            search_attempts = 0

            while self.running:
                # When searching for host, log cleanly without flooding terminal
                if not self.connected:
                    now = time.time()
                    if now - last_search_log >= 10.0:
                        console.print(f"[bold yellow][SEARCH][/bold yellow] Looking for PC host signal at ws://{self.host_ip}:{self.port}...")
                        last_search_log = now

                    # Periodically probe subnet to auto-detect host if PC booted up with new IP
                    if search_attempts > 0 and search_attempts % 6 == 0:
                        try:
                            candidates = scan_hotspot_subnet(port=self.port, timeout=0.15)
                            if candidates and candidates[0] != self.host_ip:
                                new_ip = candidates[0]
                                console.print(f"[bold green][FOUND][/bold green] Detected GameGhost PC host online at: {new_ip}")
                                self.host_ip = new_ip
                                self.uri = f"ws://{new_ip}:{self.port}"
                                save_last_host(new_ip)
                        except Exception:
                            pass

                try:
                    search_attempts += 1
                    async with websockets.connect(
                        self.uri,
                        max_size=20 * 1024 * 1024,
                        ping_interval=20,
                        ping_timeout=20,
                        open_timeout=3.0
                    ) as ws:
                        self.connected = True
                        search_attempts = 0
                        # Clear any stale packets in out_queue
                        while not self.out_queue.empty():
                            try:
                                self.out_queue.get_nowait()
                            except queue.Empty:
                                break

                        console.print(f"[bold green][CONNECTED][/bold green] Stream active: {self.uri}")

                        # Trigger remote launch if game specified
                        if self.launch_game:
                            await ws.send(json.dumps({"type": "launch", "game": self.launch_game}))
                            console.print(f"[bold green][REMOTE LAUNCH][/bold green] Requested PC to launch: {self.launch_game}")

                        async def _recv_frames():
                            while self.running and self.connected:
                                try:
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
                                            mtype = data.get("type")
                                            if mtype == "pong":
                                                t_client = data.get("client_time") or data.get("time") or 0
                                                if t_client:
                                                    self.latency_ms = max(1, int(time.time() * 1000 - t_client))
                                            elif mtype == "launch_ack":
                                                succ = data.get("success", False)
                                                g = data.get("game", "")
                                                status = "Started successfully" if succ else "Failed to start"
                                                console.print(f"[bold green][PC RESPONSE][/bold green] {g}: {status}")
                                        except Exception:
                                            pass
                                except (websockets.ConnectionClosed, asyncio.CancelledError):
                                    break
                                except Exception:
                                    break

                        async def _send_events():
                            last_ping_time = time.time()
                            while self.running and self.connected:
                                try:
                                    # Send user input packets
                                    try:
                                        packet = self.out_queue.get_nowait()
                                        await ws.send(json.dumps(packet))
                                    except queue.Empty:
                                        await asyncio.sleep(0.003)

                                    # Send heartbeat ping every 2 seconds
                                    now = time.time()
                                    if now - last_ping_time >= 2.0:
                                        await ws.send(json.dumps({"type": "ping", "time": now * 1000, "client_time": now * 1000}))
                                        last_ping_time = now
                                except (websockets.ConnectionClosed, asyncio.CancelledError):
                                    break
                                except Exception:
                                    break

                        task_recv = asyncio.create_task(_recv_frames())
                        task_send = asyncio.create_task(_send_events())
                        done, pending = await asyncio.wait(
                            [task_recv, task_send],
                            return_when=asyncio.FIRST_COMPLETED
                        )
                        self.connected = False
                        for p in pending:
                            p.cancel()
                            try:
                                await p
                            except (asyncio.CancelledError, Exception):
                                pass

                except Exception:
                    pass
                finally:
                    if self.connected:
                        console.print(f"[bold yellow][DISCONNECT][/bold yellow] Lost connection to PC ({self.host_ip}). Looking for signal...")
                    self.connected = False
                    self.latency_ms = 0
                    if self.running:
                        await asyncio.sleep(1.5)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_client_loop())

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
            dpad_coords = {
                "up": (0, -1),
                "down": (0, 1),
                "left": (-1, 0),
                "right": (1, 0)
            }
            dx, dy = dpad_coords.get(binfo.get("dir", ""), (0, 0)) if val else (0, 0)
            self.send_input({
                "type": "dpad",
                "dir": binfo.get("dir", ""),
                "val": val,
                "x": dx,
                "y": dy
            })

    def _handle_joy_axis(self, axis: int, value: float):
        """Process analog joystick axes from hardware gamepads with deadzones."""
        deadzone = 0.09
        val = 0.0 if abs(value) < deadzone else value

        # Standard Xbox / DualShock axis mapping:
        # 0: LS X, 1: LS Y, 2: RS X (or LT), 3: RS Y (or RT), 4: LT, 5: RT
        if axis == 0:
            self.send_input({"type": "stick", "which": "left", "x": val, "y": -self.left_stick["val_y"]})
            self.left_stick["val_x"] = val
        elif axis == 1:
            self.send_input({"type": "stick", "which": "left", "x": self.left_stick["val_x"], "y": -val})
            self.left_stick["val_y"] = val
        elif axis == 2:
            self.send_input({"type": "stick", "which": "right", "x": val, "y": -self.right_stick["val_y"]})
            self.right_stick["val_x"] = val
        elif axis == 3:
            self.send_input({"type": "stick", "which": "right", "x": self.right_stick["val_x"], "y": -val})
            self.right_stick["val_y"] = val
        elif axis in (4, 5):
            # Trigger axes range from -1.0 (unpressed) to 1.0 (fully pressed) on some OS
            trig_val = max(0.0, (val + 1.0) / 2.0) if val < 0 else val
            t_name = "LT" if axis == 4 else "RT"
            self.send_input({"type": "trigger", "name": t_name, "val": trig_val})

    def _draw_standby_screen(self, surface: pygame.Surface, font: pygame.font.Font, big_font: pygame.font.Font):
        """
        Draw high-contrast, animated handheld dashboard when waiting for PC stream.
        Clearly indicates that the client is actively looking for inputs from the PC.
        """
        w, h = self.win_w, self.win_h
        surface.fill((8, 12, 20))

        # Glowing border frame
        pygame.draw.rect(surface, (0, 210, 255), (15, 15, w - 30, h - 30), width=2, border_radius=8)

        cx = w // 2
        cy = h // 2

        # Animated pulsing radar / signal ring
        pulse = (time.time() * 2.2) % 2.0
        r_pulse = int(35 + pulse * 50)
        alpha_pulse = max(0, int(220 * (1.0 - pulse / 2.0)))
        radar_surf = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.gfxdraw.aacircle(radar_surf, cx, cy - 40, r_pulse, (0, 210, 255, alpha_pulse))
        pygame.gfxdraw.filled_circle(radar_surf, cx, cy - 40, 28, (0, 180, 240, 200))
        pygame.gfxdraw.aacircle(radar_surf, cx, cy - 40, 28, (255, 255, 255, 255))
        surface.blit(radar_surf, (0, 0))

        # Title & Status
        title_lbl = big_font.render("GAMEGHOST HANDHELD PORTAL", True, (0, 230, 255))
        surface.blit(title_lbl, (cx - title_lbl.get_width() // 2, cy - 120))

        dots = "." * (int(time.time() * 2) % 4)
        status_str = f"LOOKING FOR INPUTS FROM PC (ws://{self.host_ip}:{self.port}){dots}"
        status_lbl = font.render(status_str, True, (255, 195, 0))
        surface.blit(status_lbl, (cx - status_lbl.get_width() // 2, cy + 25))

        # System info lines
        info_lines = [
            f"Display Mode: Forced Landscape | Framebuffer: {w}x{h} @ 60 FPS",
            f"Active Inputs: Multi-Touch Overlay | Physical Controllers: {len(self.joysticks)} Connected",
            "Hint: Power on PC Host or run 'gg start' to cast Devil May Cry 5 immediately."
        ]
        curr_y = cy + 65
        for line in info_lines:
            lbl = font.render(line, True, (160, 180, 200))
            surface.blit(lbl, (cx - lbl.get_width() // 2, curr_y))
            curr_y += 24

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

        # Draw Action Buttons & D-Pad
        for bkey, binfo in self.buttons.items():
            bx, by, br = binfo["x"], binfo["y"], binfo["r"]
            color = binfo["color"]
            pygame.gfxdraw.filled_circle(overlay, bx, by, br, (color[0], color[1], color[2], 120))
            pygame.gfxdraw.aacircle(overlay, bx, by, br, (color[0], color[1], color[2], 220))

            lbl = font.render(binfo["label"], True, (255, 255, 255))
            overlay.blit(lbl, (bx - lbl.get_width() // 2, by - lbl.get_height() // 2))

        # Top Status HUD bar
        if self.connected:
            status_color = (0, 230, 118)
            status_text = f"GAMEGHOST // FPS: {self.fps} | HOST: {self.host_ip} (STREAMING) | PING: {self.latency_ms}ms"
        else:
            status_color = (255, 185, 0)
            status_text = f"GAMEGHOST // LOOKING FOR INPUTS FROM PC ({self.host_ip}:{self.port})..."

        lbl_status = font.render(status_text, True, status_color)
        overlay.blit(lbl_status, (25, 20))

        surface.blit(overlay, (0, 0))

    def start(self):
        """Main Pygame / SDL2 display and event loop (Forced Landscape Mode)."""
        try:
            self._start_inner()
        except KeyboardInterrupt:
            self.running = False
        finally:
            self.running = False
            try:
                pygame.quit()
            except Exception:
                pass

    def _start_inner(self):
        pygame.init()
        pygame.font.init()

        # Query native display resolution to ensure forced landscape
        try:
            display_info = pygame.display.Info()
            dw = display_info.current_w
            dh = display_info.current_h
            if dw > 0 and dh > 0:
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

        screen = None
        try:
            screen = safe_set_mode((self.win_w, self.win_h), flags)
        except Exception:
            try:
                flags = pygame.DOUBLEBUF
                screen = safe_set_mode((self.win_w, self.win_h), flags)
            except Exception:
                screen = safe_set_mode((1280, 720), pygame.DOUBLEBUF)

        pygame.display.set_caption("GameGhost Handheld Portal (Landscape)")
        font = pygame.font.SysFont("monospace", 14, bold=True)
        big_font = pygame.font.SysFont("monospace", 18, bold=True)

        # Initialize physical joysticks / gamepads
        pygame.joystick.init()
        for i in range(pygame.joystick.get_count()):
            try:
                joy = pygame.joystick.Joystick(i)
                joy.init()
                self.joysticks[joy.get_instance_id()] = joy
                console.print(f"[bold green][GAMEPAD][/bold green] Detected hardware controller: {joy.get_name()}")
            except Exception:
                pass

        self._update_layout()
        self.running = True

        # Start network worker thread
        t_net = threading.Thread(target=self._network_thread, daemon=True)
        t_net.start()

        clock = pygame.time.Clock()
        current_game_surface: Optional[pygame.Surface] = None

        while self.running:
            # 1. Process Pygame events (Touches, Hardware Gamepads, Keyboards, Hotkeys)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False

                elif event.type == pygame.VIDEORESIZE:
                    self.win_w = max(event.w, event.h)
                    self.win_h = min(event.w, event.h)
                    screen = safe_set_mode((self.win_w, self.win_h), flags)
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

                # Hardware Gamepad / Controller Events
                elif event.type == pygame.JOYDEVICEADDED:
                    try:
                        joy = pygame.joystick.Joystick(event.device_index)
                        joy.init()
                        self.joysticks[joy.get_instance_id()] = joy
                        console.print(f"[bold green][GAMEPAD][/bold green] Connected hardware controller: {joy.get_name()}")
                    except Exception:
                        pass

                elif event.type == pygame.JOYDEVICEREMOVED:
                    joy = self.joysticks.pop(event.instance_id, None)
                    if joy:
                        console.print(f"[bold yellow][GAMEPAD][/bold yellow] Disconnected controller: {joy.get_name()}")

                elif event.type == pygame.JOYBUTTONDOWN:
                    btn_name = JOY_BTN_MAP.get(event.button)
                    if btn_name:
                        self.send_input({"type": "btn", "name": btn_name, "val": 1})

                elif event.type == pygame.JOYBUTTONUP:
                    btn_name = JOY_BTN_MAP.get(event.button)
                    if btn_name:
                        self.send_input({"type": "btn", "name": btn_name, "val": 0})

                elif event.type == pygame.JOYAXISMOTION:
                    self._handle_joy_axis(event.axis, event.value)

                elif event.type == pygame.JOYHATMOTION:
                    hx, hy = event.value
                    self.send_input({"type": "dpad", "x": hx, "y": -hy, "val": 1 if (hx != 0 or hy != 0) else 0})

                # Mouse Fallback (Single pointer testing on PC)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self._handle_touch_down(999, event.pos[0], event.pos[1])

                elif event.type == pygame.MOUSEMOTION and (event.buttons[0] == 1):
                    self._handle_touch_motion(999, event.pos[0], event.pos[1])

                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    self._handle_touch_up(999)

                # Keyboard hotkeys & controller fallback
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_F11:
                        self.fullscreen = not self.fullscreen
                        flags_fs = pygame.DOUBLEBUF | pygame.RESIZABLE
                        if self.fullscreen:
                            flags_fs |= pygame.FULLSCREEN
                        try:
                            screen = safe_set_mode((self.win_w, self.win_h), flags_fs)
                        except Exception:
                            pass
                        self._update_layout()
                    elif event.key == pygame.K_h:
                        self.show_overlay = not self.show_overlay
                    elif event.key == pygame.K_ESCAPE:
                        self.running = False
                    elif event.key in KEY_BTN_MAP:
                        bname = KEY_BTN_MAP[event.key]
                        self.send_input({"type": "btn", "name": bname, "val": 1})
                    elif event.key in KEY_DPAD_MAP:
                        dx, dy, dname = KEY_DPAD_MAP[event.key]
                        self.send_input({"type": "dpad", "dir": dname, "x": dx, "y": dy, "val": 1})

                elif event.type == pygame.KEYUP:
                    if event.key in KEY_BTN_MAP:
                        bname = KEY_BTN_MAP[event.key]
                        self.send_input({"type": "btn", "name": bname, "val": 0})
                    elif event.key in KEY_DPAD_MAP:
                        dx, dy, dname = KEY_DPAD_MAP[event.key]
                        self.send_input({"type": "dpad", "dir": dname, "x": dx, "y": dy, "val": 0})

            # 2. Decompress latest video frame from network queue
            try:
                frame_bytes = self.frame_queue.get_nowait()
                current_game_surface = pygame.image.load(io.BytesIO(frame_bytes)).convert()
                self.frame_count += 1
            except queue.Empty:
                pass
            except Exception:
                pass

            now = time.time()
            if now - self.last_fps_time >= 1.0:
                self.fps = self.frame_count
                self.frame_count = 0
                self.last_fps_time = now

            # 3. Render Game Screen or Standby Signal Screen
            if self.connected and current_game_surface:
                screen.fill((5, 7, 10))
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
                self._draw_standby_screen(screen, font, big_font)

            # 4. Render On-Screen Gamepad Overlay
            self._draw_hud(screen, font)

            pygame.display.flip()
            # 60 FPS when streaming, 30 FPS when in standby looking for PC
            target_rate = 60 if self.connected else 30
            clock.tick(target_rate)

        pygame.quit()


def run_client(host_ip: Optional[str] = None, fullscreen: bool = True, launch_game: Optional[str] = None):
    """Entry point for native GameGhost handheld client in Landscape Mode."""
    if "DISPLAY" not in os.environ and os.path.exists("/data/data/com.termux/files"):
        os.environ["DISPLAY"] = ":0"

    target_host = host_ip
    if not target_host:
        # Fast-path: Check last connected host
        last = get_last_host()
        if last:
            if probe_host(last, timeout=0.3):
                target_host = last
                console.print(f"[bold green][FOUND] Reconnected to last PC host: {target_host}[/bold green]")
            else:
                # Host currently offline, launch client in standby mode looking for it
                target_host = last
                console.print(f"[bold yellow][STANDBY] Host {target_host} is offline. Starting client looking for PC...[/bold yellow]")
        else:
            console.print("[bold yellow][DISCOVERY] Looking for Gaming PC host on network...[/bold yellow]")
            disc = GameDiscovery()
            disc.start_listener()
            host_info = disc.find_host(timeout=1.5)
            disc.stop()

            if host_info:
                target_host = host_info.get("ip")
                console.print(f"[bold green][FOUND] Detected Gaming PC host: {target_host}[/bold green]")
            else:
                # Subnet scan fallback
                candidates = scan_hotspot_subnet(port=8900)
                if candidates:
                    target_host = candidates[0]
                    console.print(f"[bold green][FOUND] Detected host via subnet scan: {target_host}[/bold green]")
                else:
                    target_host = "10.176.124.73"
                    console.print(f"[bold yellow][STANDBY] No active host found on network. Starting client waiting for PC at {target_host}...[/bold yellow]")

    if target_host:
        save_last_host(target_host)

    viewer = GameGhostViewer(host_ip=target_host, port=8900, fullscreen=fullscreen, launch_game=launch_game)
    viewer.start()
