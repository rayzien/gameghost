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
    Connects to GameGhost Host, renders video at native FPS,
    and provides a native multi-touch on-screen gamepad overlay.
    """

    def __init__(self, host_ip: str, port: int = 8900, fullscreen: bool = False):
        self.host_ip = host_ip
        self.port = port
        self.uri = f"ws://{host_ip}:{port}"
        self.fullscreen = fullscreen
        self.running = False
        self.connected = False

        self.win_w = 1280
        self.win_h = 720
        self.frame_queue = queue.Queue(maxsize=2)
        self.out_queue = queue.Queue()

        self.fps = 0
        self.frame_count = 0
        self.last_fps_time = time.time()
        self.show_overlay = True

        # Multi-touch tracking: finger_id -> {"target": "left_stick|right_stick|btn", "data": ...}
        self.active_touches: Dict[int, Dict[str, Any]] = {}

        # Touch Layout geometry (calculated dynamically on resize)
        self.controls: Dict[str, Any] = {}
        self.left_stick = {"base_x": 0, "base_y": 0, "knob_x": 0, "knob_y": 0, "radius": 70, "val_x": 0.0, "val_y": 0.0}
        self.right_stick = {"base_x": 0, "base_y": 0, "knob_x": 0, "knob_y": 0, "radius": 70, "val_x": 0.0, "val_y": 0.0}
        self.buttons: Dict[str, Dict[str, Any]] = {}

    def _update_layout(self):
        """Update virtual gamepad positions relative to screen dimensions."""
        w, h = self.win_w, self.win_h

        # Left Stick (Bottom Left)
        ls_radius = int(min(w, h) * 0.11)
        ls_cx = int(w * 0.14)
        ls_cy = int(h * 0.74)
        self.left_stick["radius"] = ls_radius
        self.left_stick["base_x"] = ls_cx
        self.left_stick["base_y"] = ls_cy
        self.left_stick["knob_x"] = ls_cx
        self.left_stick["knob_y"] = ls_cy

        # Right Stick (Bottom Right)
        rs_radius = ls_radius
        rs_cx = int(w * 0.86)
        rs_cy = int(h * 0.74)
        self.right_stick["radius"] = rs_radius
        self.right_stick["base_x"] = rs_cx
        self.right_stick["base_y"] = rs_cy
        self.right_stick["knob_x"] = rs_cx
        self.right_stick["knob_y"] = rs_cy

        btn_r = int(min(w, h) * 0.052)
        self.buttons = {
            # Action Cluster (Above Right Stick)
            "Y": {"x": int(w * 0.86), "y": int(h * 0.35), "r": btn_r, "type": "btn", "name": "Y", "color": (0, 230, 118), "label": "Y"},
            "X": {"x": int(w * 0.79), "y": int(h * 0.44), "r": btn_r, "type": "btn", "name": "X", "color": (245, 0, 87), "label": "X"},
            "B": {"x": int(w * 0.93), "y": int(h * 0.44), "r": btn_r, "type": "btn", "name": "B", "color": (255, 23, 68), "label": "B"},
            "A": {"x": int(w * 0.86), "y": int(h * 0.53), "r": btn_r, "type": "btn", "name": "A", "color": (41, 121, 255), "label": "A"},

            # D-Pad Cluster (Above Left Stick)
            "DPAD_UP":    {"x": int(w * 0.14), "y": int(h * 0.35), "r": btn_r, "type": "dpad", "dir": (0, -1), "color": (160, 180, 210), "label": "U"},
            "DPAD_LEFT":  {"x": int(w * 0.07), "y": int(h * 0.44), "r": btn_r, "type": "dpad", "dir": (-1, 0), "color": (160, 180, 210), "label": "L"},
            "DPAD_RIGHT": {"x": int(w * 0.21), "y": int(h * 0.44), "r": btn_r, "type": "dpad", "dir": (1, 0), "color": (160, 180, 210), "label": "R"},
            "DPAD_DOWN":  {"x": int(w * 0.14), "y": int(h * 0.53), "r": btn_r, "type": "dpad", "dir": (0, 1), "color": (160, 180, 210), "label": "D"},

            # Shoulders (Top Corners)
            "L1": {"x": int(w * 0.18), "y": int(h * 0.12), "r": int(btn_r * 1.1), "type": "btn", "name": "L1", "color": (0, 210, 255), "label": "L1"},
            "L2": {"x": int(w * 0.07), "y": int(h * 0.12), "r": int(btn_r * 1.1), "type": "trigger", "name": "L2", "color": (0, 210, 255), "label": "L2"},
            "R1": {"x": int(w * 0.82), "y": int(h * 0.12), "r": int(btn_r * 1.1), "type": "btn", "name": "R1", "color": (0, 210, 255), "label": "R1"},
            "R2": {"x": int(w * 0.93), "y": int(h * 0.12), "r": int(btn_r * 1.1), "type": "trigger", "name": "R2", "color": (0, 210, 255), "label": "R2"},

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

                        async def _recv_frames():
                            while self.running:
                                msg = await ws.recv()
                                if isinstance(msg, bytes):
                                    if self.frame_queue.full():
                                        try:
                                            self.frame_queue.get_nowait()
                                        except queue.Empty:
                                            pass
                                    self.frame_queue.put(msg)

                        async def _send_events():
                            while self.running:
                                try:
                                    packet = self.out_queue.get_nowait()
                                    await ws.send(json.dumps(packet))
                                except queue.Empty:
                                    await asyncio.sleep(0.005)

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
            binfo = self.buttons.get(bkey)
            if binfo:
                self._dispatch_button(binfo, 0)

    def _update_stick(self, which: str, px: float, py: float):
        stick = self.left_stick if which == "left" else self.right_stick
        bx, by = stick["base_x"], stick["base_y"]
        dx, dy = px - bx, py - by
        dist = math.hypot(dx, dy)
        max_r = stick["radius"]

        if dist > max_r:
            dx = (dx / dist) * max_r
            dy = (dy / dist) * max_r

        stick["knob_x"] = bx + dx
        stick["knob_y"] = by + dy

        norm_x = max(-1.0, min(1.0, dx / max_r))
        norm_y = max(-1.0, min(1.0, dy / max_r))

        # Deadzone
        if abs(norm_x) < 0.05: norm_x = 0.0
        if abs(norm_y) < 0.05: norm_y = 0.0

        self.send_input({
            "type": "stick",
            "which": which,
            "x": round(norm_x, 3),
            "y": round(norm_y, 3)
        })

    def _dispatch_button(self, binfo: dict, val: int):
        btype = binfo["type"]
        if btype == "btn":
            self.send_input({"type": "btn", "name": binfo["name"], "val": val})
        elif btype == "trigger":
            self.send_input({"type": "trigger", "name": binfo["name"], "val": float(val)})
        elif btype == "dpad":
            dx = binfo["dir"][0] if val else 0
            dy = binfo["dir"][1] if val else 0
            self.send_input({"type": "dpad", "x": dx, "y": dy})

    def _draw_hud(self, surface: pygame.Surface, font: pygame.font.Font):
        """Draw the semi-transparent handheld overlay directly onto the screen."""
        if not self.show_overlay:
            return

        overlay = pygame.Surface((self.win_w, self.win_h), pygame.SRCALPHA)

        # 1. Left Analog Stick
        ls = self.left_stick
        pygame.gfxdraw.filled_circle(overlay, ls["base_x"], ls["base_y"], ls["radius"], (12, 18, 28, 140))
        pygame.gfxdraw.aacircle(overlay, ls["base_x"], ls["base_y"], ls["radius"], (0, 210, 255, 180))
        # Knob
        knob_r = int(ls["radius"] * 0.48)
        pygame.gfxdraw.filled_circle(overlay, int(ls["knob_x"]), int(ls["knob_y"]), knob_r, (25, 35, 52, 230))
        pygame.gfxdraw.aacircle(overlay, int(ls["knob_x"]), int(ls["knob_y"]), knob_r, (0, 210, 255, 255))
        txt_ls = font.render("LS", True, (0, 210, 255))
        overlay.blit(txt_ls, (int(ls["knob_x"] - txt_ls.get_width() / 2), int(ls["knob_y"] - txt_ls.get_height() / 2)))

        # 2. Right Analog Stick
        rs = self.right_stick
        pygame.gfxdraw.filled_circle(overlay, rs["base_x"], rs["base_y"], rs["radius"], (12, 18, 28, 140))
        pygame.gfxdraw.aacircle(overlay, rs["base_x"], rs["base_y"], rs["radius"], (0, 210, 255, 180))
        # Knob
        pygame.gfxdraw.filled_circle(overlay, int(rs["knob_x"]), int(rs["knob_y"]), knob_r, (25, 35, 52, 230))
        pygame.gfxdraw.aacircle(overlay, int(rs["knob_x"]), int(rs["knob_y"]), knob_r, (0, 210, 255, 255))
        txt_rs = font.render("RS", True, (0, 210, 255))
        overlay.blit(txt_rs, (int(rs["knob_x"] - txt_rs.get_width() / 2), int(rs["knob_y"] - txt_rs.get_height() / 2)))

        # 3. Buttons (D-Pad, Actions, Shoulders, System)
        active_targets = [t.get("bkey") for t in self.active_touches.values() if t.get("target") == "button"]

        for bkey, binfo in self.buttons.items():
            bx, by, br = binfo["x"], binfo["y"], binfo["r"]
            color = binfo["color"]
            is_pressed = bkey in active_targets

            bg_alpha = 220 if is_pressed else 130
            pygame.gfxdraw.filled_circle(overlay, bx, by, br, (20, 26, 38, bg_alpha))
            border_col = (color[0], color[1], color[2], 255 if is_pressed else 180)
            pygame.gfxdraw.aacircle(overlay, bx, by, br, border_col)

            lbl = font.render(binfo["label"], True, color if not is_pressed else (255, 255, 255))
            overlay.blit(lbl, (bx - lbl.get_width() // 2, by - lbl.get_height() // 2))

        # 4. Status Bar
        status_txt = f"{self.fps} FPS | Host: {self.host_ip}" if self.connected else "Connecting..."
        status_surf = font.render(status_txt, True, (0, 210, 255) if self.connected else (255, 60, 60))
        overlay.blit(status_surf, (16, 12))

        surface.blit(overlay, (0, 0))

    def start(self):
        """Main Pygame / SDL2 display and event loop."""
        pygame.init()
        pygame.font.init()

        flags = pygame.DOUBLEBUF | pygame.HWSURFACE
        if self.fullscreen:
            flags |= pygame.FULLSCREEN

        screen = pygame.display.set_mode((self.win_w, self.win_h), flags)
        pygame.display.set_caption("GameGhost Handheld Portal")
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
                    self.win_w, self.win_h = event.w, event.h
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
                        flags_fs = pygame.DOUBLEBUF | pygame.HWSURFACE
                        if self.fullscreen:
                            flags_fs |= pygame.FULLSCREEN
                        screen = pygame.display.set_mode((self.win_w, self.win_h), flags_fs)
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


def run_client(host_ip: Optional[str] = None, fullscreen: bool = False):
    """Entry point for native GameGhost handheld client."""
    if "DISPLAY" not in os.environ and os.path.exists("/data/data/com.termux/files"):
        os.environ["DISPLAY"] = ":0"

    if not host_ip:
        # Fast-path: Check last connected host
        last = get_last_host()
        if last and probe_host(last):
            host_ip = last
            console.print(f"[bold green][FOUND] Reconnected to last host: {host_ip}[/bold green]")
        else:
            console.print("[bold yellow][DISCOVERY] Scanning local network for GameGhost host...[/bold yellow]")
            disc = GameDiscovery()
            disc.start_listener()
            host_info = disc.find_host(timeout=2.0)
            disc.stop()

            if host_info:
                host_ip = host_info.get("ip")
                console.print(f"[bold green][FOUND] Detected GameGhost host: {host_ip}[/bold green]")
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
    viewer = GameGhostViewer(host_ip=host_ip, port=8900, fullscreen=fullscreen)
    viewer.start()
