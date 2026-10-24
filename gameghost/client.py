import os
import sys

# Mesa, EGL, DRI2 & Zink error mitigation:
# Prevents 'failed to choose pdev', 'DRI2 screen failed', and 'zink' crashes in Termux
if "TERMUX_VERSION" in os.environ or os.path.exists("/data/data/com.termux"):
    os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
    os.environ["GALLIUM_DRIVER"] = "llvmpipe"
    os.environ["MESA_LOADER_DRIVER_OVERRIDE"] = "llvmpipe"
    os.environ["SDL_RENDER_DRIVER"] = "software"
    os.environ["SDL_VIDEO_X11_NODIRECTCOLOR"] = "1"
    os.environ["SDL_VIDEO_X11_NET_WM_BYPASS_COMPOSITOR"] = "0"
    os.environ["MESA_DEBUG"] = "silent"
    os.environ["EGL_LOG_LEVEL"] = "fatal"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

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

from .config import (
    log_client,
    load_config,
    get_last_host,
    save_last_host,
    probe_host,
    QUALITY_PRESETS,
    THEME_PRESETS
)
from .discovery import GameDiscovery, scan_hotspot_subnet

console = Console()

# Hardware Gamepad Profiles (Xbox, PlayStation, Nintendo, Generic SDL2)
GAMEPAD_PROFILES = {
    "xbox": {
        0: "A", 1: "B", 2: "X", 3: "Y",
        4: "LB", 5: "RB", 6: "SELECT", 7: "START", 8: "HOME",
        9: "L3", 10: "R3"
    },
    "playstation": {
        0: "A", 1: "B", 2: "X", 3: "Y",
        4: "SELECT", 5: "HOME", 6: "START",
        7: "L3", 8: "R3", 9: "LB", 10: "RB"
    },
    "nintendo": {
        0: "B", 1: "A", 2: "Y", 3: "X",
        4: "SELECT", 6: "START", 9: "LB", 10: "RB",
        11: "L3", 12: "R3", 15: "HOME"
    }
}


def detect_controller_profile(name: str) -> str:
    """Identify controller brand/profile from device name."""
    n = name.lower()
    if any(k in n for k in ("sony", "dualsense", "dualshock", "ps4", "ps5", "playstation")):
        return "playstation"
    if any(k in n for k in ("nintendo", "switch", "pro controller", "joy-con")):
        return "nintendo"
    return "xbox"


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


def calculate_letterbox(win_w: int, win_h: int, frame_w: int, frame_h: int, aspect_mode: str = "auto") -> Tuple[int, int, int, int]:
    """Calculate scaled dimensions based on user-chosen aspect ratio mode."""
    if frame_w <= 0 or frame_h <= 0 or win_w <= 0 or win_h <= 0:
        return win_w, win_h, 0, 0

    if aspect_mode == "stretch":
        return win_w, win_h, 0, 0

    target_ratio = frame_w / frame_h
    if aspect_mode == "16:9":
        target_ratio = 16.0 / 9.0
    elif aspect_mode == "21:9":
        target_ratio = 21.0 / 9.0
    elif aspect_mode == "4:3":
        target_ratio = 4.0 / 3.0

    screen_ratio = win_w / win_h
    if screen_ratio > target_ratio:
        draw_h = win_h
        draw_w = max(1, int(win_h * target_ratio))
    else:
        draw_w = win_w
        draw_h = max(1, int(win_w / target_ratio))

    offset_x = (win_w - draw_w) // 2
    offset_y = (win_h - draw_h) // 2
    return draw_w, draw_h, offset_x, offset_y


class GameGhostViewer:
    """
    Native Pygame / SDL2 Handheld Client.
    Connects to GameGhost Host, renders video in Landscape mode up to 4K,
    supports dynamic Auto-FPS, PlayStation / Xbox layout profiles,
    customizable themes and neon borders, physical controllers,
    and an interactive on-screen Quick Settings bar.
    """

    def __init__(
        self,
        host_ip: str,
        port: int = 8900,
        audio_port: int = 8901,
        fullscreen: bool = True,
        launch_game: Optional[str] = None,
        preset: str = "1080p",
        layout: str = "xbox",
        theme: str = "cyan",
        visibility: str = "full",
        target_fps: int = 60,
        min_fps: int = 45,
        max_fps: int = 120,
        auto_fps: bool = True
    ):
        self.host_ip = host_ip
        self.port = port
        self.audio_port = audio_port
        self.uri = f"ws://{host_ip}:{port}"
        self.audio_uri = f"ws://{host_ip}:{audio_port}"
        self.fullscreen = fullscreen
        self.launch_game = launch_game
        self.running = False
        self.connected = False
        self.latency_ms = 0

        # Customization & Quality Settings
        self.preset = preset if preset in QUALITY_PRESETS else "1080p"
        self.controller_theme = "playstation" if layout in ("ps", "playstation") else "xbox"
        self.overlay_theme = theme if theme in THEME_PRESETS else "cyan"
        self.visibility_mode = visibility if visibility in ("full", "minimal", "hidden", "off") else "full"
        self.target_fps = target_fps
        self.min_fps = min_fps
        self.max_fps = max_fps
        self.auto_fps = auto_fps

        self.audio_muted = False
        self.settings_open = False

        self.win_w = 1280
        self.win_h = 720
        self.frame_queue = queue.Queue(maxsize=2)
        # Bounded input queue prevents memory leak and input burst on reconnect
        self.out_queue = queue.Queue(maxsize=64)

        self.fps = 0
        self.frame_count = 0
        self.last_fps_time = time.time()
        self.show_overlay = True
        self.notification_msg = ""
        self.notification_time = 0.0

        # Physical Joysticks / Hardware Controllers (Bluetooth, USB OTG, Kishi, Backbone)
        self.joysticks: Dict[int, pygame.joystick.Joystick] = {}
        self.joystick_profiles: Dict[int, str] = {}

        # Multi-touch tracking: finger_id -> {"target": "left_stick|right_stick|button", "data": ...}
        self.active_touches: Dict[int, Dict[str, Any]] = {}
        self.pressed_buttons: Set[str] = set()
        self.ripples: List[Dict[str, Any]] = []

        # Touch Controls Customization, Aspect Ratio & Mouse Support
        self.touch_scale: float = 1.0  # 0.75, 1.0, 1.25, 1.50
        self.touch_alpha: int = 180    # 76 (30%), 128 (50%), 190 (75%), 255 (100%)
        self.touch_style: str = "classic"  # "classic", "compact", "wide"
        self.aspect_ratio_mode: str = "auto"  # "auto", "stretch", "16:9", "21:9", "4:3"
        self.mouse_captured: bool = False

        # Touch Layout geometry
        self.left_stick = {"base_x": 0, "base_y": 0, "knob_x": 0, "knob_y": 0, "radius": 75, "val_x": 0.0, "val_y": 0.0}
        self.right_stick = {"base_x": 0, "base_y": 0, "knob_x": 0, "knob_y": 0, "radius": 75, "val_x": 0.0, "val_y": 0.0}
        self.buttons: Dict[str, Dict[str, Any]] = {}
        self.settings_btn = pygame.Rect(0, 0, 0, 0)
        self.settings_modal: Dict[str, Any] = {}

    def notify(self, message: str, duration: float = 2.5):
        """Show temporary on-screen HUD notification."""
        self.notification_msg = message
        self.notification_time = time.time() + duration

    def _update_layout(self):
        """Update virtual gamepad positions relative to screen dimensions (Landscape layout)."""
        w, h = self.win_w, self.win_h
        theme_cfg = THEME_PRESETS.get(self.overlay_theme, THEME_PRESETS["cyan"])
        scale = self.touch_scale

        # Position profiles: classic, compact, wide
        if self.touch_style == "compact":
            ls_x = int(w * 0.10)
            ls_y = int(h * 0.78)
            rs_x = int(w * 0.90)
            rs_y = int(h * 0.78)
            face_cx = int(w * 0.90)
            face_cy = int(h * 0.30)
            dpad_cx = int(w * 0.10)
            dpad_cy = int(h * 0.30)
        elif self.touch_style == "wide":
            ls_x = int(w * 0.18)
            ls_y = int(h * 0.70)
            rs_x = int(w * 0.82)
            rs_y = int(h * 0.70)
            face_cx = int(w * 0.84)
            face_cy = int(h * 0.34)
            dpad_cx = int(w * 0.16)
            dpad_cy = int(h * 0.34)
        else:  # classic
            ls_x = int(w * 0.14)
            ls_y = int(h * 0.72)
            rs_x = int(w * 0.86)
            rs_y = int(h * 0.72)
            face_cx = int(w * 0.87)
            face_cy = int(h * 0.32)
            dpad_cx = int(w * 0.13)
            dpad_cy = int(h * 0.32)

        ls_r = int(min(w, h) * 0.14 * scale)
        rs_r = int(min(w, h) * 0.14 * scale)
        btn_r = int(min(w, h) * 0.065 * scale)
        spacing = int(btn_r * 2.2)
        dpad_s = int(btn_r * 2.0)

        self.left_stick = {
            "base_x": ls_x,
            "base_y": ls_y,
            "knob_x": ls_x,
            "knob_y": ls_y,
            "radius": ls_r,
            "val_x": 0.0,
            "val_y": 0.0
        }

        self.right_stick = {
            "base_x": rs_x,
            "base_y": rs_y,
            "knob_x": rs_x,
            "knob_y": rs_y,
            "radius": rs_r,
            "val_x": 0.0,
            "val_y": 0.0
        }

        # Style profiles: Xbox (Y, B, A, X) vs PlayStation (Triangle, Circle, Cross, Square)
        if self.controller_theme == "playstation":
            face_btns = {
                "Y": {"x": face_cx, "y": face_cy - spacing, "r": btn_r, "type": "btn", "name": "Y", "color": (46, 204, 113), "label": "T"},
                "A": {"x": face_cx, "y": face_cy + spacing, "r": btn_r, "type": "btn", "name": "A", "color": (52, 152, 219), "label": "X"},
                "X": {"x": face_cx - spacing, "y": face_cy, "r": btn_r, "type": "btn", "name": "X", "color": (243, 104, 224), "label": "S"},
                "B": {"x": face_cx + spacing, "y": face_cy, "r": btn_r, "type": "btn", "name": "B", "color": (238, 82, 83), "label": "O"},
            }
            shldr_labels = {"L1": "L1", "L2": "L2", "R1": "R1", "R2": "R2"}
            sys_labels = {"SELECT": "SHR", "HOME": "PS", "START": "OPT"}
        else:
            face_btns = {
                "Y": {"x": face_cx, "y": face_cy - spacing, "r": btn_r, "type": "btn", "name": "Y", "color": (255, 215, 0), "label": "Y"},
                "A": {"x": face_cx, "y": face_cy + spacing, "r": btn_r, "type": "btn", "name": "A", "color": (46, 204, 113), "label": "A"},
                "X": {"x": face_cx - spacing, "y": face_cy, "r": btn_r, "type": "btn", "name": "X", "color": (52, 152, 219), "label": "X"},
                "B": {"x": face_cx + spacing, "y": face_cy, "r": btn_r, "type": "btn", "name": "B", "color": (231, 76, 60), "label": "B"},
            }
            shldr_labels = {"L1": "LB", "L2": "LT", "R1": "RB", "R2": "RT"}
            sys_labels = {"SELECT": "VIEW", "HOME": "XBOX", "START": "MENU"}

        accent_color = theme_cfg["accent"]

        self.buttons = {
            **face_btns,

            # D-Pad
            "DPAD_UP":    {"x": dpad_cx, "y": dpad_cy - dpad_s, "r": btn_r, "type": "dpad", "name": "DPAD_UP", "dir": "up", "color": (160, 165, 175), "label": "^"},
            "DPAD_DOWN":  {"x": dpad_cx, "y": dpad_cy + dpad_s, "r": btn_r, "type": "dpad", "name": "DPAD_DOWN", "dir": "down", "color": (160, 165, 175), "label": "v"},
            "DPAD_LEFT":  {"x": dpad_cx - dpad_s, "y": dpad_cy, "r": btn_r, "type": "dpad", "name": "DPAD_LEFT", "dir": "left", "color": (160, 165, 175), "label": "<"},
            "DPAD_RIGHT": {"x": dpad_cx + dpad_s, "y": dpad_cy, "r": btn_r, "type": "dpad", "name": "DPAD_RIGHT", "dir": "right", "color": (160, 165, 175), "label": ">"},

            # Shoulders & Triggers
            "L1": {"x": int(w * 0.12), "y": int(h * 0.08), "r": int(btn_r * 1.05), "type": "btn", "name": "LB", "color": accent_color, "label": shldr_labels["L1"]},
            "L2": {"x": int(w * 0.23), "y": int(h * 0.08), "r": int(btn_r * 1.05), "type": "trigger", "name": "LT", "color": accent_color, "label": shldr_labels["L2"]},
            "R1": {"x": int(w * 0.88), "y": int(h * 0.08), "r": int(btn_r * 1.05), "type": "btn", "name": "RB", "color": accent_color, "label": shldr_labels["R1"]},
            "R2": {"x": int(w * 0.77), "y": int(h * 0.08), "r": int(btn_r * 1.05), "type": "trigger", "name": "RT", "color": accent_color, "label": shldr_labels["R2"]},

            # Thumbstick Click Buttons (L3 / R3)
            "L3": {"x": int(ls_x), "y": int(ls_y - ls_r - btn_r * 0.9), "r": int(btn_r * 0.8), "type": "btn", "name": "L3", "color": (130, 185, 230), "label": "L3"},
            "R3": {"x": int(rs_x), "y": int(rs_y - rs_r - btn_r * 0.9), "r": int(btn_r * 0.8), "type": "btn", "name": "R3", "color": (130, 185, 230), "label": "R3"},

            # Center System Buttons
            "SELECT": {"x": int(w * 0.39), "y": int(h * 0.08), "r": int(btn_r * 0.65), "type": "btn", "name": "SELECT", "color": (190, 200, 210), "label": sys_labels["SELECT"]},
            "HOME":   {"x": int(w * 0.50), "y": int(h * 0.08), "r": int(btn_r * 0.65), "type": "btn", "name": "HOME", "color": accent_color, "label": sys_labels["HOME"]},
            "START":  {"x": int(w * 0.61), "y": int(h * 0.08), "r": int(btn_r * 0.65), "type": "btn", "name": "START", "color": (190, 200, 210), "label": sys_labels["START"]},
        }

        # Playful Interactive Settings Button (Top Right)
        s_btn_w = max(110, int(w * 0.095))
        s_btn_h = max(32, int(h * 0.052))
        self.settings_btn = pygame.Rect(w - s_btn_w - int(w * 0.02), int(h * 0.02), s_btn_w, s_btn_h)

        # Settings Drawer / Modal Dialog (Centered Landscape Panel)
        modal_w = min(int(w * 0.78), 740)
        modal_h = min(int(h * 0.94), 540)
        modal_x = (w - modal_w) // 2
        modal_y = (h - modal_h) // 2
        self.modal_rect = pygame.Rect(modal_x, modal_y, modal_w, modal_h)

        pad_x = int(modal_w * 0.05)
        content_w = modal_w - pad_x * 2
        col_w = (content_w - 16) // 2
        row_h = max(28, int(modal_h * 0.075))
        gap_y = 7

        # Row 1: Controller Layout & Quality Preset
        r1_y = modal_y + 46
        btn_layout = pygame.Rect(modal_x + pad_x, r1_y, col_w, row_h)
        btn_preset = pygame.Rect(modal_x + pad_x + col_w + 16, r1_y, col_w, row_h)

        # Row 2: Target FPS & Overlay Theme
        r2_y = r1_y + row_h + gap_y
        btn_fps = pygame.Rect(modal_x + pad_x, r2_y, col_w, row_h)
        btn_theme = pygame.Rect(modal_x + pad_x + col_w + 16, r2_y, col_w, row_h)

        # Row 3: HUD Visibility & Audio Stream Mute
        r3_y = r2_y + row_h + gap_y
        btn_view = pygame.Rect(modal_x + pad_x, r3_y, col_w, row_h)
        btn_audio = pygame.Rect(modal_x + pad_x + col_w + 16, r3_y, col_w, row_h)

        # Row 4: Touch Scale & Touch Opacity
        r4_y = r3_y + row_h + gap_y
        btn_scale = pygame.Rect(modal_x + pad_x, r4_y, col_w, row_h)
        btn_alpha = pygame.Rect(modal_x + pad_x + col_w + 16, r4_y, col_w, row_h)

        # Row 5: Touch Layout Style & Screen Aspect Ratio
        r5_y = r4_y + row_h + gap_y
        btn_style = pygame.Rect(modal_x + pad_x, r5_y, col_w, row_h)
        btn_ratio = pygame.Rect(modal_x + pad_x + col_w + 16, r5_y, col_w, row_h)

        # Row 6: Mouse & Keyboard Capture Toggle
        r6_y = r5_y + row_h + gap_y
        btn_mouse = pygame.Rect(modal_x + pad_x, r6_y, content_w, row_h)

        # Row 7: Game Quick Launchers
        r7_y = r6_y + row_h + 30
        catalog_games = ["dmc5", "sekiro", "tekken8", "mk11", "mgr", "rottr"]
        game_btn_w = (content_w - (len(catalog_games) - 1) * 8) // len(catalog_games)
        game_btns = {}
        for idx, gid in enumerate(catalog_games):
            gx = modal_x + pad_x + idx * (game_btn_w + 8)
            game_btns[gid] = pygame.Rect(gx, r7_y, game_btn_w, max(26, int(row_h * 0.9)))

        # Bottom: Close / Resume button
        btn_close = pygame.Rect(modal_x + pad_x, modal_y + modal_h - row_h - 14, content_w, row_h)

        # Top close 'X' button
        btn_x_close = pygame.Rect(modal_x + modal_w - 36, modal_y + 12, 24, 24)

        self.settings_modal = {
            "rect": self.modal_rect,
            "layout": btn_layout,
            "preset": btn_preset,
            "fps": btn_fps,
            "theme": btn_theme,
            "view": btn_view,
            "audio": btn_audio,
            "scale": btn_scale,
            "alpha": btn_alpha,
            "style": btn_style,
            "ratio": btn_ratio,
            "mouse": btn_mouse,
            "games": game_btns,
            "close": btn_close,
            "x_close": btn_x_close
        }

    def toggle_layout(self):
        self.controller_theme = "playstation" if self.controller_theme == "xbox" else "xbox"
        self._update_layout()
        self.notify(f"Controller Layout: {self.controller_theme.upper()} MODE")

    def cycle_preset(self):
        presets = ["720p", "1080p", "1440p", "4k"]
        idx = (presets.index(self.preset) + 1) % len(presets) if self.preset in presets else 1
        self.preset = presets[idx]
        p_cfg = QUALITY_PRESETS[self.preset]
        self.target_fps = p_cfg.get("fps", self.target_fps)
        self.min_fps = p_cfg.get("min_fps", self.min_fps)
        self.send_input({
            "type": "settings",
            "preset": self.preset,
            "fps": self.target_fps,
            "min_fps": self.min_fps,
            "auto_fps": self.auto_fps
        })
        self._update_layout()
        self.notify(f"Stream Quality Preset: {QUALITY_PRESETS[self.preset]['name']}")

    def cycle_fps(self):
        if self.auto_fps:
            self.auto_fps = False
            self.target_fps = 60
            mode_str = "Fixed 60 FPS"
        elif self.target_fps == 60:
            self.target_fps = 90
            mode_str = "Fixed 90 FPS"
        elif self.target_fps == 90:
            self.target_fps = 120
            mode_str = "Extreme 120 FPS"
        else:
            self.auto_fps = True
            self.target_fps = 120
            mode_str = f"Dynamic Auto-FPS (Floor: {self.min_fps} FPS)"

        self.send_input({
            "type": "settings",
            "fps": self.target_fps,
            "min_fps": self.min_fps,
            "auto_fps": self.auto_fps
        })
        self._update_layout()
        self.notify(f"FPS Engine: {mode_str}")

    def cycle_theme(self):
        themes = list(THEME_PRESETS.keys())
        idx = (themes.index(self.overlay_theme) + 1) % len(themes) if self.overlay_theme in themes else 0
        self.overlay_theme = themes[idx]
        self._update_layout()
        self.notify(f"Border Theme: {THEME_PRESETS[self.overlay_theme]['name']}")

    def cycle_visibility(self):
        modes = ["full", "minimal", "hidden", "off"]
        idx = (modes.index(self.visibility_mode) + 1) % len(modes) if self.visibility_mode in modes else 0
        self.visibility_mode = modes[idx]
        self.show_overlay = self.visibility_mode != "off"
        self._update_layout()
        self.notify(f"Overlay Visibility: {self.visibility_mode.upper()}")

    def toggle_audio(self):
        self.audio_muted = not self.audio_muted
        state = "MUTED" if self.audio_muted else "ACTIVE (44.1kHz)"
        self.notify(f"Audio Stream: {state}")

    def cycle_touch_scale(self):
        scales = [0.75, 1.0, 1.25, 1.50]
        idx = (scales.index(self.touch_scale) + 1) % len(scales) if self.touch_scale in scales else 1
        self.touch_scale = scales[idx]
        self._update_layout()
        self.notify(f"Touch Scale: {int(self.touch_scale * 100)}%")

    def cycle_touch_alpha(self):
        alphas = [76, 128, 190, 255]
        labels = {76: "30%", 128: "50%", 190: "75%", 255: "100%"}
        idx = (alphas.index(self.touch_alpha) + 1) % len(alphas) if self.touch_alpha in alphas else 2
        self.touch_alpha = alphas[idx]
        self.notify(f"Touch Opacity: {labels.get(self.touch_alpha, '75%')}")

    def cycle_touch_style(self):
        styles = ["classic", "compact", "wide"]
        idx = (styles.index(self.touch_style) + 1) % len(styles) if self.touch_style in styles else 0
        self.touch_style = styles[idx]
        self._update_layout()
        self.notify(f"Touch Layout: {self.touch_style.upper()}")

    def cycle_aspect_ratio(self):
        ratios = ["auto", "stretch", "16:9", "21:9", "4:3"]
        idx = (ratios.index(self.aspect_ratio_mode) + 1) % len(ratios) if self.aspect_ratio_mode in ratios else 0
        self.aspect_ratio_mode = ratios[idx]
        self.notify(f"Aspect Ratio: {self.aspect_ratio_mode.upper()}")

    def toggle_mouse_capture(self):
        self.mouse_captured = not self.mouse_captured
        try:
            pygame.event.set_grab(self.mouse_captured)
            pygame.mouse.set_visible(not self.mouse_captured)
        except Exception:
            pass
        state = "LOCKED (F10 to release)" if self.mouse_captured else "RELEASED"
        self.notify(f"Mouse Capture: {state}")

    def toggle_settings(self):
        self.settings_open = not self.settings_open

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
                                self.audio_uri = f"ws://{new_ip}:{self.audio_port}"
                                save_last_host(new_ip)
                        except Exception:
                            pass

                try:
                    search_attempts += 1
                    async with websockets.connect(
                        self.uri,
                        max_size=20 * 1024 * 1024,
                        ping_interval=15,
                        ping_timeout=15,
                        open_timeout=3.0,
                        close_timeout=3.0
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

                        # Sync active preset and Auto-FPS on connect
                        await ws.send(json.dumps({
                            "type": "settings",
                            "preset": self.preset,
                            "fps": self.target_fps,
                            "min_fps": self.min_fps,
                            "auto_fps": self.auto_fps
                        }))

                        # Trigger remote launch if game specified
                        if self.launch_game:
                            await ws.send(json.dumps({"type": "launch", "game": self.launch_game}))
                            console.print(f"[bold green][REMOTE LAUNCH][/bold green] Requested PC to launch: {self.launch_game}")
                            log_client(f"Requested PC to launch: {self.launch_game}")
                            self.notify(f"Launching {self.launch_game} on PC...", duration=5.0)

                        async def _recv_frames():
                            while self.running and self.connected:
                                try:
                                    msg = await ws.recv()
                                    if isinstance(msg, bytes):
                                        try:
                                            if self.frame_queue.full():
                                                try:
                                                    self.frame_queue.get_nowait()
                                                except queue.Empty:
                                                    pass
                                            self.frame_queue.put_nowait(msg)
                                        except Exception:
                                            pass
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
                                                log_client(f"PC launch response: {g} - {status}")
                                                self.notify(f"PC: {g} {status}", duration=4.0)
                                            elif mtype == "settings_ack":
                                                pass
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
                                        await asyncio.sleep(0.002)

                                    # Send heartbeat ping every 2 seconds
                                    now = time.time()
                                    if now - last_ping_time >= 2.0:
                                        await ws.send(json.dumps({"type": "ping", "time": now * 1000, "client_time": now * 1000}))
                                        last_ping_time = now
                                except (websockets.ConnectionClosed, asyncio.CancelledError):
                                    break
                                except Exception:
                                    await asyncio.sleep(0.005)

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

    def _audio_thread(self):
        """
        Background worker receiving and playing system audio stream over WebSocket.
        Uses low-latency PCM playback through pygame.mixer.
        """
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
            pygame.mixer.set_num_channels(32)
        except Exception as ex:
            console.print(f"[bold yellow][AUDIO][/bold yellow] Audio mixer initialization: {ex}")

        async def _audio_loop():
            while self.running:
                try:
                    async with websockets.connect(
                        self.audio_uri,
                        max_size=2 * 1024 * 1024,
                        ping_interval=15,
                        ping_timeout=15,
                        open_timeout=3.0,
                        close_timeout=3.0
                    ) as ws:
                        console.print(f"[bold green][AUDIO CONNECTED][/bold green] Audio stream active: {self.audio_uri}")
                        while self.running:
                            try:
                                msg = await ws.recv()
                                if isinstance(msg, bytes) and not self.audio_muted:
                                    try:
                                        ch = pygame.mixer.find_channel(True)
                                        if ch:
                                            ch.play(pygame.mixer.Sound(buffer=msg))
                                    except Exception:
                                        pass
                            except (websockets.ConnectionClosed, asyncio.CancelledError):
                                break
                            except Exception:
                                break
                except Exception:
                    pass
                if self.running:
                    await asyncio.sleep(2.0)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_audio_loop())

    def _handle_touch_down(self, finger_id: int, px: float, py: float):
        """Process touch down event at screen coordinates (px, py)."""
        # If settings drawer is open, check modal clicks
        if self.settings_open:
            sm = self.settings_modal
            if not sm:
                return

            if sm["close"].collidepoint(px, py) or sm["x_close"].collidepoint(px, py):
                self.settings_open = False
                return
            if sm["layout"].collidepoint(px, py):
                self.toggle_layout()
                return
            if sm["preset"].collidepoint(px, py):
                self.cycle_preset()
                return
            if sm["fps"].collidepoint(px, py):
                self.cycle_fps()
                return
            if sm["theme"].collidepoint(px, py):
                self.cycle_theme()
                return
            if sm["view"].collidepoint(px, py):
                self.cycle_visibility()
                return
            if sm["audio"].collidepoint(px, py):
                self.toggle_audio()
                return
            if sm["scale"].collidepoint(px, py):
                self.cycle_touch_scale()
                return
            if sm["alpha"].collidepoint(px, py):
                self.cycle_touch_alpha()
                return
            if sm["style"].collidepoint(px, py):
                self.cycle_touch_style()
                return
            if sm["ratio"].collidepoint(px, py):
                self.cycle_aspect_ratio()
                return
            if sm["mouse"].collidepoint(px, py):
                self.toggle_mouse_capture()
                return
            for gid, rect in sm.get("games", {}).items():
                if rect.collidepoint(px, py):
                    self.send_input({"type": "launch", "game": gid})
                    self.notify(f"Launching {gid.upper()} on PC...", duration=4.0)
                    return
            # Tap outside modal closes it
            if not sm["rect"].collidepoint(px, py):
                self.settings_open = False
            return

        # Check Settings Button tap
        if self.settings_btn.collidepoint(px, py):
            self.settings_open = True
            return

        # Visual feedback animation: spawn touch ripple on screen
        theme_cfg = THEME_PRESETS.get(self.overlay_theme, THEME_PRESETS["cyan"])
        accent = theme_cfg["accent"]
        self.ripples.append({
            "x": px,
            "y": py,
            "r": 8,
            "max_r": int(42 * self.touch_scale),
            "alpha": 220,
            "color": accent
        })

        # If visibility is hidden or off, do not consume touches as virtual buttons
        if self.visibility_mode in ("hidden", "off"):
            return

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

        # 3. Check action buttons (if not minimal mode)
        if self.visibility_mode != "minimal":
            for bkey, binfo in self.buttons.items():
                dist = math.hypot(px - binfo["x"], py - binfo["y"])
                if dist <= binfo["r"] * 1.3:
                    self.active_touches[finger_id] = {"target": "button", "bkey": bkey}
                    self.pressed_buttons.add(bkey)
                    self._dispatch_button(binfo, 1)
                    return
        else:
            # Minimal mode still supports L3/R3 and Shoulders
            for bkey in ("L3", "R3", "L1", "R1", "L2", "R2", "SELECT", "START"):
                binfo = self.buttons[bkey]
                dist = math.hypot(px - binfo["x"], py - binfo["y"])
                if dist <= binfo["r"] * 1.3:
                    self.active_touches[finger_id] = {"target": "button", "bkey": bkey}
                    self.pressed_buttons.add(bkey)
                    self._dispatch_button(binfo, 1)
                    return

    def _handle_touch_motion(self, finger_id: int, px: float, py: float):
        """Process touch drag/motion for sticks."""
        if self.settings_open:
            return
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
        if self.settings_open:
            return
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
            if bkey:
                self.pressed_buttons.discard(bkey)
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
        deadzone = 0.08
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
            trig_val = max(0.0, (val + 1.0) / 2.0) if val < 0 else val
            t_name = "LT" if axis == 4 else "RT"
            self.send_input({"type": "trigger", "name": t_name, "val": trig_val})

    def _draw_border_glow(self, surface: pygame.Surface, theme_cfg: dict):
        """Draw sleek glowing neon border around the screen."""
        w, h = self.win_w, self.win_h
        border_col = theme_cfg["border"]

        # If disconnected, make the border breathe gently in warning amber/theme
        if not self.connected:
            pulse = (math.sin(time.time() * 3.5) + 1.0) / 2.0
            border_col = (
                int(border_col[0] * 0.4 + 255 * 0.6 * pulse),
                int(border_col[1] * 0.4 + 180 * 0.6 * pulse),
                int(border_col[2] * 0.4)
            )

        pygame.draw.rect(surface, border_col, (12, 12, w - 24, h - 24), width=2, border_radius=10)

    def _draw_standby_screen(self, surface: pygame.Surface, font: pygame.font.Font, big_font: pygame.font.Font):
        """
        Draw high-contrast, animated handheld dashboard when waiting for PC stream.
        Clearly indicates that the client is actively looking for inputs from the PC.
        """
        w, h = self.win_w, self.win_h
        theme_cfg = THEME_PRESETS.get(self.overlay_theme, THEME_PRESETS["cyan"])
        accent = theme_cfg["accent"]

        surface.fill((8, 12, 20))
        self._draw_border_glow(surface, theme_cfg)

        cx = w // 2
        cy = h // 2

        # Animated pulsing radar / signal ring
        pulse = (time.time() * 2.2) % 2.0
        r_pulse = int(35 + pulse * 50)
        alpha_pulse = max(0, int(220 * (1.0 - pulse / 2.0)))
        radar_surf = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.gfxdraw.aacircle(radar_surf, cx, cy - 40, r_pulse, (accent[0], accent[1], accent[2], alpha_pulse))
        pygame.gfxdraw.filled_circle(radar_surf, cx, cy - 40, 28, (accent[0], accent[1], accent[2], 180))
        pygame.gfxdraw.aacircle(radar_surf, cx, cy - 40, 28, (255, 255, 255, 255))
        surface.blit(radar_surf, (0, 0))

        # Title & Status
        title_lbl = big_font.render("GAMEGHOST HANDHELD PORTAL", True, accent)
        surface.blit(title_lbl, (cx - title_lbl.get_width() // 2, cy - 120))

        dots = "." * (int(time.time() * 2) % 4)
        if self.launch_game:
            status_str = f"CONNECTING TO PC HOST TO CAST {self.launch_game.upper()} (ws://{self.host_ip}:{self.port}){dots}"
        else:
            status_str = f"LOOKING FOR INPUTS FROM PC (ws://{self.host_ip}:{self.port}){dots}"
        status_lbl = font.render(status_str, True, (255, 195, 0))
        surface.blit(status_lbl, (cx - status_lbl.get_width() // 2, cy + 25))

        # System info lines
        info_lines = [
            f"Quality Preset: {QUALITY_PRESETS[self.preset]['name']} | Max FPS: {self.target_fps} (Auto-FPS: {self.auto_fps})",
            f"Layout: {self.controller_theme.upper()} Mode | Theme: {theme_cfg['name']} | Hardware Gamepads: {len(self.joysticks)}",
            "Hint: Power on PC Host or run 'gg start' to mirror and cast Devil May Cry 5 immediately."
        ]
        curr_y = cy + 65
        for line in info_lines:
            lbl = font.render(line, True, (160, 180, 200))
            surface.blit(lbl, (cx - lbl.get_width() // 2, curr_y))
            curr_y += 24

    def _draw_hud(self, surface: pygame.Surface, font: pygame.font.Font, small_font: pygame.font.Font, big_font: pygame.font.Font):
        theme_cfg = THEME_PRESETS.get(self.overlay_theme, THEME_PRESETS["cyan"])
        accent = theme_cfg["accent"]

        # Always draw the neon border frame
        self._draw_border_glow(surface, theme_cfg)

        overlay = pygame.Surface((self.win_w, self.win_h), pygame.SRCALPHA)

        # 1. Sleek Playful [SETTINGS] Button at Top Right (when settings modal is closed)
        if not self.settings_open:
            sb = self.settings_btn
            pygame.draw.rect(overlay, (18, 24, 36, 210), sb, border_radius=6)
            pygame.draw.rect(overlay, (accent[0], accent[1], accent[2], 200), sb, width=1, border_radius=6)
            s_lbl = small_font.render("[SETTINGS]", True, (240, 245, 255))
            overlay.blit(s_lbl, (sb.centerx - s_lbl.get_width() // 2, sb.centery - s_lbl.get_height() // 2))

        # 2. Virtual Gamepad On-Screen Controls (only if settings modal is closed)
        if not self.settings_open and self.show_overlay and self.visibility_mode not in ("hidden", "off"):
            # Visual feedback animations: draw expanding touch ripples
            alive_ripples = []
            for r in self.ripples:
                r["r"] += 3
                r["alpha"] = max(0, r["alpha"] - 14)
                if r["alpha"] > 0 and r["r"] <= r["max_r"]:
                    r_col = (r["color"][0], r["color"][1], r["color"][2], r["alpha"])
                    pygame.gfxdraw.aacircle(overlay, int(r["x"]), int(r["y"]), int(r["r"]), r_col)
                    alive_ripples.append(r)
            self.ripples = alive_ripples

            # Draw Left Stick
            ls = self.left_stick
            base_col = (theme_cfg["stick_base"][0], theme_cfg["stick_base"][1], theme_cfg["stick_base"][2], int(self.touch_alpha * 0.75))
            knob_col = (theme_cfg["stick_knob"][0], theme_cfg["stick_knob"][1], theme_cfg["stick_knob"][2], self.touch_alpha)
            pygame.gfxdraw.filled_circle(overlay, ls["base_x"], ls["base_y"], ls["radius"], base_col)
            pygame.gfxdraw.aacircle(overlay, ls["base_x"], ls["base_y"], ls["radius"], (accent[0], accent[1], accent[2], min(255, self.touch_alpha + 30)))
            knob_r = int(ls["radius"] * 0.45)
            pygame.gfxdraw.filled_circle(overlay, ls["knob_x"], ls["knob_y"], knob_r, knob_col)
            pygame.gfxdraw.aacircle(overlay, ls["knob_x"], ls["knob_y"], knob_r, (255, 255, 255, min(255, self.touch_alpha + 40)))

            # Draw Right Stick
            rs = self.right_stick
            pygame.gfxdraw.filled_circle(overlay, rs["base_x"], rs["base_y"], rs["radius"], base_col)
            pygame.gfxdraw.aacircle(overlay, rs["base_x"], rs["base_y"], rs["radius"], (accent[0], accent[1], accent[2], min(255, self.touch_alpha + 30)))
            pygame.gfxdraw.filled_circle(overlay, rs["knob_x"], rs["knob_y"], knob_r, knob_col)
            pygame.gfxdraw.aacircle(overlay, rs["knob_x"], rs["knob_y"], knob_r, (255, 255, 255, min(255, self.touch_alpha + 40)))

            # Draw Action Buttons & D-Pad (if not minimal, or selective in minimal)
            for bkey, binfo in self.buttons.items():
                if self.visibility_mode == "minimal" and binfo["type"] not in ("trigger",) and bkey not in ("L3", "R3", "L1", "R1", "SELECT", "START"):
                    continue

                is_pressed = bkey in self.pressed_buttons
                bx = binfo["x"]
                by = binfo["y"] + (2 if is_pressed else 0)  # Active button depression
                br = binfo["r"]
                color = binfo["color"]
                alpha_fill = min(255, self.touch_alpha + (65 if is_pressed else 0))
                alpha_border = min(255, self.touch_alpha + (75 if is_pressed else 20))

                # Visual feedback animation: active glow halo when pressed
                if is_pressed:
                    pygame.gfxdraw.filled_circle(overlay, bx, by, br + 4, (color[0], color[1], color[2], 90))
                    pygame.gfxdraw.aacircle(overlay, bx, by, br + 4, (255, 255, 255, 180))

                pygame.gfxdraw.filled_circle(overlay, bx, by, br, (color[0], color[1], color[2], alpha_fill))
                border_color = (255, 255, 255) if is_pressed else color
                pygame.gfxdraw.aacircle(overlay, bx, by, br, (border_color[0], border_color[1], border_color[2], alpha_border))

                lbl = font.render(binfo["label"], True, (255, 255, 180) if is_pressed else (255, 255, 255))
                overlay.blit(lbl, (bx - lbl.get_width() // 2, by - lbl.get_height() // 2))

        # 3. Status HUD Bar (Top Left) (only if settings modal is closed)
        if not self.settings_open:
            if self.connected:
                status_color = (0, 230, 118)
                fps_tag = f"FPS: {self.fps}/{self.target_fps}{' (AUTO)' if self.auto_fps else ''}"
                audio_tag = "MUTED" if self.audio_muted else "AUDIO ON"
                mouse_tag = " [MOUSE LOCKED]" if self.mouse_captured else ""
                status_text = f"GAMEGHOST // {fps_tag} | {self.preset.upper()} | {self.controller_theme.upper()} | {audio_tag}{mouse_tag} | PING: {self.latency_ms}ms"
            else:
                status_color = (255, 185, 0)
                status_text = f"GAMEGHOST // LOOKING FOR INPUTS FROM PC ({self.host_ip}:{self.port})..."

            lbl_status = font.render(status_text, True, status_color)
            overlay.blit(lbl_status, (25, 20))

        # 4. Interactive Settings Modal Drawer
        if self.settings_open:
            sm = self.settings_modal
            m_rect = sm["rect"]

            # Darkened backdrop
            overlay.fill((6, 10, 18, 220))

            # Modal card body
            pygame.draw.rect(overlay, (15, 20, 32, 250), m_rect, border_radius=12)
            pygame.draw.rect(overlay, (accent[0], accent[1], accent[2], 220), m_rect, width=2, border_radius=12)

            # Header Title
            title_lbl = big_font.render("GAMEGHOST CONTROL CENTER", True, accent)
            overlay.blit(title_lbl, (m_rect.centerx - title_lbl.get_width() // 2, m_rect.y + 14))

            # Close 'X' button
            xb = sm["x_close"]
            pygame.draw.rect(overlay, (40, 25, 30, 220), xb, border_radius=4)
            pygame.draw.rect(overlay, (255, 90, 90), xb, width=1, border_radius=4)
            x_lbl = font.render("X", True, (255, 120, 120))
            overlay.blit(x_lbl, (xb.centerx - x_lbl.get_width() // 2, xb.centery - x_lbl.get_height() // 2))

            # Helper to draw interactive setting button
            def _draw_opt_btn(rect, label, val_text, active_accent=False):
                col_bg = (24, 32, 48, 230)
                col_border = (accent[0], accent[1], accent[2], 180) if active_accent else (90, 110, 140, 160)
                pygame.draw.rect(overlay, col_bg, rect, border_radius=6)
                pygame.draw.rect(overlay, col_border, rect, width=1, border_radius=6)
                t_lbl = small_font.render(f"{label}: {val_text}", True, (240, 245, 255))
                overlay.blit(t_lbl, (rect.centerx - t_lbl.get_width() // 2, rect.centery - t_lbl.get_height() // 2))

            _draw_opt_btn(sm["layout"], "PAD LAYOUT", self.controller_theme.upper(), True)
            _draw_opt_btn(sm["preset"], "QUALITY", self.preset.upper(), True)
            _draw_opt_btn(sm["fps"], "FPS ENGINE", "AUTO" if self.auto_fps else f"{self.target_fps} FPS", True)
            _draw_opt_btn(sm["theme"], "COLOR THEME", self.overlay_theme.upper(), True)
            _draw_opt_btn(sm["view"], "HUD OVERLAY", self.visibility_mode.upper(), True)
            _draw_opt_btn(sm["audio"], "AUDIO STREAM", "MUTED" if self.audio_muted else "ACTIVE (44.1kHz)", not self.audio_muted)
            _draw_opt_btn(sm["scale"], "TOUCH SCALE", f"{int(self.touch_scale * 100)}%", True)
            _draw_opt_btn(sm["alpha"], "TOUCH OPACITY", f"{int(self.touch_alpha / 255 * 100)}%", True)
            _draw_opt_btn(sm["style"], "TOUCH STYLE", self.touch_style.upper(), True)
            _draw_opt_btn(sm["ratio"], "SCREEN RATIO", self.aspect_ratio_mode.upper(), True)
            _draw_opt_btn(sm["mouse"], "MOUSE / KEYBOARD CAPTURE", "LOCKED (F10 TO RELEASE)" if self.mouse_captured else "CLICK TO LOCK MOUSE (F10)", self.mouse_captured)

            # Game Quick Launchers Header
            q_lbl = small_font.render("REMOTE LAUNCH GAME ON PC:", True, (160, 185, 210))
            overlay.blit(q_lbl, (m_rect.x + int(m_rect.width * 0.05), sm["games"]["dmc5"].y - 18))

            game_names = {
                "dmc5": "DMC 5",
                "sekiro": "SEKIRO",
                "tekken8": "TEKKEN 8",
                "mk11": "MK 11",
                "mgr": "MGR",
                "rottr": "ROTTR"
            }
            for gid, gr in sm["games"].items():
                pygame.draw.rect(overlay, (20, 28, 42, 230), gr, border_radius=5)
                pygame.draw.rect(overlay, (accent[0], accent[1], accent[2], 150), gr, width=1, border_radius=5)
                g_lbl = small_font.render(game_names.get(gid, gid.upper()), True, (230, 240, 255))
                overlay.blit(g_lbl, (gr.centerx - g_lbl.get_width() // 2, gr.centery - g_lbl.get_height() // 2))

            # Bottom Close / Resume Button
            cb = sm["close"]
            pygame.draw.rect(overlay, (accent[0], accent[1], accent[2], 40), cb, border_radius=6)
            pygame.draw.rect(overlay, accent, cb, width=1, border_radius=6)
            c_lbl = font.render("[RESUME GAMEPLAY]", True, (255, 255, 255))
            overlay.blit(c_lbl, (cb.centerx - c_lbl.get_width() // 2, cb.centery - c_lbl.get_height() // 2))

        # 5. Temporary Notification Banner (Center bottom)
        if time.time() < self.notification_time and self.notification_msg:
            n_lbl = font.render(self.notification_msg, True, (255, 255, 255))
            n_box = pygame.Rect(self.win_w // 2 - n_lbl.get_width() // 2 - 16, self.win_h - 60, n_lbl.get_width() + 32, 34)
            pygame.draw.rect(overlay, (20, 25, 35, 230), n_box, border_radius=8)
            pygame.draw.rect(overlay, accent, n_box, width=1, border_radius=8)
            overlay.blit(n_lbl, (n_box.centerx - n_lbl.get_width() // 2, n_box.centery - n_lbl.get_height() // 2))

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

        is_termux = "TERMUX_VERSION" in os.environ or os.path.exists("/data/data/com.termux")
        flags = pygame.DOUBLEBUF | pygame.RESIZABLE
        if self.fullscreen and not is_termux:
            flags |= pygame.FULLSCREEN
        elif self.fullscreen and is_termux:
            flags |= pygame.NOFRAME

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
        small_font = pygame.font.SysFont("monospace", 11, bold=True)
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

        # Start audio playback worker thread
        t_audio = threading.Thread(target=self._audio_thread, daemon=True)
        t_audio.start()

        clock = pygame.time.Clock()
        current_game_surface: Optional[pygame.Surface] = None
        cached_scaled_surface: Optional[pygame.Surface] = None
        cached_frame_key: Optional[Tuple[int, int]] = None
        last_fps_time = time.time()

        while self.running:
            # 1. Process Pygame events (Touches, Hardware Gamepads, Keyboards, Hotkeys)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False

                elif event.type == pygame.VIDEORESIZE:
                    self.win_w = max(event.w, event.h)
                    self.win_h = min(event.w, event.h)
                    try:
                        screen = safe_set_mode((self.win_w, self.win_h), flags)
                    except Exception:
                        pass
                    cached_scaled_surface = None
                    cached_frame_key = None
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
                        prof = detect_controller_profile(joy.get_name())
                        self.joystick_profiles[joy.get_instance_id()] = prof
                        console.print(f"[bold green][GAMEPAD][/bold green] Connected hardware controller: {joy.get_name()} [{prof.upper()}]")
                        self.notify(f"Connected: {joy.get_name()[:16]} [{prof.upper()}]")
                    except Exception:
                        pass

                elif event.type == pygame.JOYDEVICEREMOVED:
                    joy = self.joysticks.pop(event.instance_id, None)
                    self.joystick_profiles.pop(event.instance_id, None)
                    if joy:
                        console.print(f"[bold yellow][GAMEPAD][/bold yellow] Disconnected controller: {joy.get_name()}")
                        self.notify("Gamepad Disconnected")

                elif event.type == pygame.JOYBUTTONDOWN:
                    prof = self.joystick_profiles.get(event.instance_id, "xbox")
                    btn_map = GAMEPAD_PROFILES.get(prof, GAMEPAD_PROFILES["xbox"])
                    btn_name = btn_map.get(event.button)
                    if btn_name:
                        self.send_input({"type": "btn", "name": btn_name, "val": 1})

                elif event.type == pygame.JOYBUTTONUP:
                    prof = self.joystick_profiles.get(event.instance_id, "xbox")
                    btn_map = GAMEPAD_PROFILES.get(prof, GAMEPAD_PROFILES["xbox"])
                    btn_name = btn_map.get(event.button)
                    if btn_name:
                        self.send_input({"type": "btn", "name": btn_name, "val": 0})

                elif event.type == pygame.JOYAXISMOTION:
                    self._handle_joy_axis(event.axis, event.value)

                elif event.type == pygame.JOYHATMOTION:
                    hx, hy = event.value
                    self.send_input({"type": "dpad", "x": hx, "y": -hy, "val": 1 if (hx != 0 or hy != 0) else 0})

                # Mouse Events (Mouse & Keyboard Forwarding + Touch Fallback)
                elif event.type == pygame.MOUSEMOTION:
                    if self.mouse_captured:
                        dx, dy = event.rel
                        self.send_input({"type": "mouse_move", "dx": dx, "dy": dy})
                    elif event.buttons[0] == 1:
                        self._handle_touch_motion(999, event.pos[0], event.pos[1])

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if self.mouse_captured:
                        b_map = {1: "left", 2: "middle", 3: "right"}
                        btn = b_map.get(event.button, "left")
                        self.send_input({"type": "mouse_btn", "btn": btn, "val": 1})
                    elif event.button == 1:
                        self._handle_touch_down(999, event.pos[0], event.pos[1])

                elif event.type == pygame.MOUSEBUTTONUP:
                    if self.mouse_captured:
                        b_map = {1: "left", 2: "middle", 3: "right"}
                        btn = b_map.get(event.button, "left")
                        self.send_input({"type": "mouse_btn", "btn": btn, "val": 0})
                    elif event.button == 1:
                        self._handle_touch_up(999)

                elif event.type == pygame.MOUSEWHEEL:
                    if self.mouse_captured:
                        self.send_input({"type": "mouse_scroll", "dx": event.x, "dy": event.y})

                # Keyboard hotkeys & controller fallback
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_F10:
                        self.toggle_mouse_capture()
                    elif event.key == pygame.K_F11:
                        self.fullscreen = not self.fullscreen
                        flags_fs = pygame.DOUBLEBUF | pygame.RESIZABLE
                        if self.fullscreen:
                            flags_fs |= pygame.FULLSCREEN
                        try:
                            screen = safe_set_mode((self.win_w, self.win_h), flags_fs)
                        except Exception:
                            pass
                        self._update_layout()
                    elif event.key in (pygame.K_m, pygame.K_s):
                        self.toggle_settings()
                    elif event.key == pygame.K_ESCAPE:
                        if self.mouse_captured:
                            self.toggle_mouse_capture()
                        elif self.settings_open:
                            self.settings_open = False
                        else:
                            self.running = False
                    elif event.key == pygame.K_p:
                        self.toggle_layout()
                    elif event.key == pygame.K_q:
                        self.cycle_preset()
                    elif event.key == pygame.K_f:
                        self.cycle_fps()
                    elif event.key == pygame.K_t:
                        self.cycle_theme()
                    elif event.key == pygame.K_v:
                        self.cycle_visibility()
                    elif event.key == pygame.K_h:
                        self.show_overlay = not self.show_overlay
                    elif self.mouse_captured:
                        kname = pygame.key.name(event.key)
                        self.send_input({"type": "key", "name": kname, "val": 1})
                    elif event.key in KEY_BTN_MAP and not self.settings_open:
                        bname = KEY_BTN_MAP[event.key]
                        self.send_input({"type": "btn", "name": bname, "val": 1})
                    elif event.key in KEY_DPAD_MAP and not self.settings_open:
                        dx, dy, dname = KEY_DPAD_MAP[event.key]
                        self.send_input({"type": "dpad", "dir": dname, "x": dx, "y": dy, "val": 1})

                elif event.type == pygame.KEYUP:
                    if self.mouse_captured:
                        kname = pygame.key.name(event.key)
                        self.send_input({"type": "key", "name": kname, "val": 0})
                    elif event.key in KEY_BTN_MAP and not self.settings_open:
                        bname = KEY_BTN_MAP[event.key]
                        self.send_input({"type": "btn", "name": bname, "val": 0})
                    elif event.key in KEY_DPAD_MAP and not self.settings_open:
                        dx, dy, dname = KEY_DPAD_MAP[event.key]
                        self.send_input({"type": "dpad", "dir": dname, "x": dx, "y": dy, "val": 0})

            # 2. Decompress latest video frame from network queue
            new_frame_arrived = False
            try:
                frame_bytes = self.frame_queue.get_nowait()
                current_game_surface = pygame.image.load(io.BytesIO(frame_bytes)).convert()
                self.frame_count += 1
                new_frame_arrived = True
            except queue.Empty:
                pass
            except Exception:
                pass

            now = time.time()
            if now - last_fps_time >= 1.0:
                self.fps = self.frame_count
                self.frame_count = 0
                self.last_fps_time = now
                last_fps_time = now

            # 3. Render Game Screen or Standby Signal Screen
            if self.connected and current_game_surface:
                screen.fill((5, 7, 10))
                draw_w, draw_h, off_x, off_y = calculate_letterbox(
                    self.win_w, self.win_h,
                    current_game_surface.get_width(),
                    current_game_surface.get_height(),
                    aspect_mode=self.aspect_ratio_mode
                )
                if draw_w != current_game_surface.get_width() or draw_h != current_game_surface.get_height():
                    if new_frame_arrived or cached_scaled_surface is None or cached_frame_key != (draw_w, draw_h):
                        cached_scaled_surface = pygame.transform.scale(current_game_surface, (draw_w, draw_h))
                        cached_frame_key = (draw_w, draw_h)
                    screen.blit(cached_scaled_surface, (off_x, off_y))
                else:
                    screen.blit(current_game_surface, (off_x, off_y))

                # Check if received PC screen is black (e.g. while game / DirectX window is loading on PC)
                try:
                    cw, ch = current_game_surface.get_width(), current_game_surface.get_height()
                    if cw > 20 and ch > 20:
                        p1 = current_game_surface.get_at((cw // 2, ch // 2))[:3]
                        p2 = current_game_surface.get_at((20, 20))[:3]
                        p3 = current_game_surface.get_at((cw - 20, 20))[:3]
                        p4 = current_game_surface.get_at((cw // 4, ch // 4))[:3]
                        if p1 == (0, 0, 0) and p2 == (0, 0, 0) and p3 == (0, 0, 0) and p4 == (0, 0, 0):
                            if getattr(self, "_black_screen_start", None) is None:
                                self._black_screen_start = time.time()
                            # Show loading indicator during first 8 seconds of black screen
                            if time.time() - self._black_screen_start <= 8.0:
                                theme_cfg = THEME_PRESETS.get(self.overlay_theme, THEME_PRESETS["cyan"])
                                accent = theme_cfg["accent"]
                                gname = (self.launch_game or "GAME").upper()
                                dots = "." * (int(time.time() * 2) % 4)
                                load_title = big_font.render(f"STARTING {gname} ON PC{dots}", True, accent)
                                screen.blit(load_title, (self.win_w // 2 - load_title.get_width() // 2, self.win_h // 2 - 40))
                                load_sub = font.render("Connected to PC. Waiting for DirectX / Vulkan game window to render...", True, (255, 200, 50))
                                screen.blit(load_sub, (self.win_w // 2 - load_sub.get_width() // 2, self.win_h // 2 + 5))
                                load_hint = font.render(f"PC Host: ws://{self.host_ip}:{self.port} | Tap [SETTINGS] or press 'm' for options", True, (160, 180, 200))
                                screen.blit(load_hint, (self.win_w // 2 - load_hint.get_width() // 2, self.win_h // 2 + 35))
                        else:
                            self._black_screen_start = None
                except Exception:
                    pass
            else:
                self._draw_standby_screen(screen, font, big_font)

            # 4. Render On-Screen Gamepad Overlay & Interactive Settings
            self._draw_hud(screen, font, small_font, big_font)

            pygame.display.flip()
            # Dynamic frame rate limiter (up to 120 FPS when streaming)
            target_rate = max(30, min(144, self.target_fps)) if self.connected else 30
            clock.tick(target_rate)

        pygame.quit()


def run_client(
    host_ip: Optional[str] = None,
    fullscreen: bool = True,
    launch_game: Optional[str] = None,
    preset: str = "1080p",
    layout: str = "xbox",
    theme: str = "cyan",
    visibility: str = "full",
    target_fps: int = 60,
    min_fps: int = 45,
    max_fps: int = 120,
    auto_fps: bool = True,
    audio_port: Optional[int] = None
):
    """Entry point for native GameGhost handheld client in Landscape Mode."""
    is_termux = "TERMUX_VERSION" in os.environ or os.path.exists("/data/data/com.termux/files")
    if is_termux:
        prefix_tmp = "/data/data/com.termux/files/usr/tmp"
        os.environ.setdefault("TMPDIR", prefix_tmp)
        os.environ["SDL_VIDEODRIVER"] = "x11"
        if "DISPLAY" not in os.environ:
            target_disp = ":0"
            for n in ("0", "1", "2"):
                if os.path.exists(f"{prefix_tmp}/.X11-unix/X{n}") or os.path.exists(f"/tmp/.X11-unix/X{n}"):
                    target_disp = f":{n}"
                    break
            os.environ["DISPLAY"] = target_disp

        # Auto-launch Termux-X11 companion app into the foreground
        try:
            import subprocess
            subprocess.run(["am", "start", "--user", "0", "-n", "com.termux.x11/com.termux.x11.MainActivity"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            try:
                import subprocess
                subprocess.run(["am", "start", "-n", "com.termux.x11/com.termux.x11.MainActivity"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    cfg = load_config()
    default_preset = "720p" if is_termux else "1080p"
    preset = preset or cfg.get("preset", default_preset)
    layout = layout or cfg.get("controller_theme", "xbox")
    theme = theme or cfg.get("overlay_theme", "cyan")
    visibility = visibility or cfg.get("overlay_visibility", "full")
    target_fps = target_fps or cfg.get("target_fps", 60)
    min_fps = min_fps or cfg.get("min_fps", 45)
    max_fps = max_fps or cfg.get("max_fps", 120)
    auto_fps = auto_fps if auto_fps is not None else cfg.get("auto_fps", True)
    audio_port = audio_port or cfg.get("audio_port", 8901)

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

    viewer = GameGhostViewer(
        host_ip=target_host,
        port=8900,
        audio_port=audio_port,
        fullscreen=fullscreen,
        launch_game=launch_game,
        preset=preset,
        layout=layout,
        theme=theme,
        visibility=visibility,
        target_fps=target_fps,
        min_fps=min_fps,
        max_fps=max_fps,
        auto_fps=auto_fps
    )
    viewer.start()
