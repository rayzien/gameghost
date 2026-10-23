import time
import threading
from typing import Optional, Dict, Any

try:
    import evdev
    from evdev import UInput, ecodes as e
    HAS_EVDEV = True
except ImportError:
    HAS_EVDEV = False

try:
    from pynput.keyboard import Controller as KbdController, Key
    from pynput.mouse import Controller as MouseController, Button
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False


class VirtualGamepad:
    """
    Virtual Xbox 360 Gamepad device created via Linux uinput (/dev/uinput).
    Instantly recognized natively by Devil May Cry 5, Steam, Wine, and all PC games.
    """

    def __init__(self):
        self.uinput: Optional[UInput] = None
        self.active = False
        self.lock = threading.Lock()
        self.keyboard = KbdController() if HAS_PYNPUT else None
        self.mouse = MouseController() if HAS_PYNPUT else None
        self.mode = "gamepad"  # 'gamepad' or 'keyboard_fallback'
        self._init_device()

    def _init_device(self):
        if not HAS_EVDEV:
            print("[GAMEPAD] evdev library not available. Falling back to keyboard simulation.")
            self.mode = "keyboard_fallback"
            return

        try:
            capabilities = {
                e.EV_KEY: [
                    e.BTN_A, e.BTN_B, e.BTN_X, e.BTN_Y,
                    e.BTN_TL, e.BTN_TR,
                    e.BTN_SELECT, e.BTN_START, e.BTN_MODE,
                    e.BTN_THUMBL, e.BTN_THUMBR
                ],
                e.EV_ABS: [
                    (e.ABS_X, evdev.AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)),
                    (e.ABS_Y, evdev.AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)),
                    (e.ABS_RX, evdev.AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)),
                    (e.ABS_RY, evdev.AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)),
                    (e.ABS_Z, evdev.AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
                    (e.ABS_RZ, evdev.AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
                    (e.ABS_HAT0X, evdev.AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
                    (e.ABS_HAT0Y, evdev.AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
                ]
            }

            self.uinput = UInput(
                events=capabilities,
                name="GameGhost Virtual Controller (Xbox 360)",
                vendor=0x045E,  # Microsoft
                product=0x028E, # Xbox 360 controller
                version=0x0110
            )
            self.active = True
            print(f"[GAMEPAD] Created hardware virtual gamepad: {self.uinput.name}")
        except Exception as ex:
            print(f"[GAMEPAD] Warning: Could not create uinput device ({ex}). Falling back to keyboard simulation.")
            self.mode = "keyboard_fallback"

    def handle_packet(self, data: Dict[str, Any]):
        """
        Process incoming controller packet from phone touch screen.
        Format examples:
          {"type": "btn", "name": "A", "val": 1}
          {"type": "trigger", "name": "L2", "val": 1.0}
          {"type": "stick", "which": "left", "x": 0.5, "y": -0.8}
          {"type": "dpad", "x": 0, "y": -1}
        """
        with self.lock:
            p_type = data.get("type")

            if p_type == "btn":
                btn_name = data.get("name", "").upper()
                val = 1 if data.get("val") else 0
                self._handle_button(btn_name, val)

            elif p_type == "stick":
                which = data.get("which", "left")
                # X and Y normalized between -1.0 and 1.0
                nx = float(data.get("x", 0.0))
                ny = float(data.get("y", 0.0))
                self._handle_stick(which, nx, ny)

            elif p_type == "trigger":
                name = data.get("name", "L2").upper()
                # Val between 0.0 and 1.0
                fval = float(data.get("val", 0.0))
                self._handle_trigger(name, fval)

            elif p_type == "dpad":
                if "x" in data or "y" in data:
                    dx = int(data.get("x", 0))
                    dy = int(data.get("y", 0))
                elif "dir" in data:
                    d = str(data.get("dir", "")).lower()
                    val = 1 if data.get("val", 1) else 0
                    dir_coords = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
                    dx, dy = dir_coords.get(d, (0, 0)) if val else (0, 0)
                else:
                    dx, dy = 0, 0
                self._handle_dpad(dx, dy)

            elif p_type == "mouse_move":
                dx = float(data.get("dx", 0.0))
                dy = float(data.get("dy", 0.0))
                if self.mouse:
                    self.mouse.move(dx, dy)

            elif p_type == "mouse_btn":
                btn_str = str(data.get("btn", "left")).lower()
                val = 1 if data.get("val") else 0
                if self.mouse:
                    b_obj = Button.left
                    if btn_str == "right":
                        b_obj = Button.right
                    elif btn_str == "middle":
                        b_obj = Button.middle
                    if val == 1:
                        self.mouse.press(b_obj)
                    else:
                        self.mouse.release(b_obj)

            elif p_type == "mouse_scroll":
                dx = int(data.get("dx", 0))
                dy = int(data.get("dy", 0))
                if self.mouse:
                    self.mouse.scroll(dx, dy)

            elif p_type == "key":
                kname = str(data.get("name", "")).lower()
                val = 1 if data.get("val") else 0
                self._handle_raw_key(kname, val)

    def _handle_raw_key(self, kname: str, val: int):
        if not self.keyboard:
            return
        key_map = {
            "space": Key.space,
            "return": Key.enter,
            "enter": Key.enter,
            "tab": Key.tab,
            "escape": Key.esc,
            "esc": Key.esc,
            "backspace": Key.backspace,
            "shift": Key.shift,
            "shift_r": Key.shift_r,
            "ctrl": Key.ctrl,
            "ctrl_r": Key.ctrl_r,
            "alt": Key.alt,
            "alt_r": Key.alt_r,
            "up": Key.up,
            "down": Key.down,
            "left": Key.left,
            "right": Key.right,
            "f1": Key.f1, "f2": Key.f2, "f3": Key.f3, "f4": Key.f4,
            "f5": Key.f5, "f6": Key.f6, "f7": Key.f7, "f8": Key.f8,
            "f9": Key.f9, "f10": Key.f10, "f11": Key.f11, "f12": Key.f12
        }
        target_k = key_map.get(kname)
        if target_k is None and len(kname) == 1:
            target_k = kname
        if target_k is not None:
            try:
                if val == 1:
                    self.keyboard.press(target_k)
                else:
                    self.keyboard.release(target_k)
            except Exception:
                pass

    def _handle_button(self, name: str, val: int):
        if self.mode == "gamepad" and self.uinput:
            btn_map = {
                "A": e.BTN_A,
                "B": e.BTN_B,
                "X": e.BTN_X,
                "Y": e.BTN_Y,
                "L1": e.BTN_TL,
                "LB": e.BTN_TL,
                "R1": e.BTN_TR,
                "RB": e.BTN_TR,
                "SELECT": e.BTN_SELECT,
                "SHARE": e.BTN_SELECT,
                "START": e.BTN_START,
                "OPTIONS": e.BTN_START,
                "HOME": e.BTN_MODE,
                "GUIDE": e.BTN_MODE,
                "L3": e.BTN_THUMBL,
                "R3": e.BTN_THUMBR,
            }
            code = btn_map.get(name)
            if code is not None:
                self.uinput.write(e.EV_KEY, code, val)
                self.uinput.syn()
                return

        # Fallback to keyboard mapping (DMC5 keyboard controls)
        if self.keyboard:
            kbd_map = {
                "A": Key.space,      # Jump
                "B": 'k',            # Special Attack / Style
                "X": 'j',            # Gun / Ranged
                "Y": 'i',            # Melee Sword
                "L1": Key.shift,     # Devil Trigger
                "R1": 'l',           # Lock-on
                "START": Key.esc,
                "SELECT": Key.tab,
            }
            key = kbd_map.get(name)
            if key:
                if val == 1:
                    self.keyboard.press(key)
                else:
                    self.keyboard.release(key)

    def _handle_stick(self, which: str, nx: float, ny: float):
        # Clamp values
        nx = max(-1.0, min(1.0, nx))
        ny = max(-1.0, min(1.0, ny))

        if self.mode == "gamepad" and self.uinput:
            # Scale to Xbox 360 axis range (-32768 to 32767)
            raw_x = int(nx * 32767)
            raw_y = int(ny * 32767)

            if which == "left":
                self.uinput.write(e.EV_ABS, e.ABS_X, raw_x)
                self.uinput.write(e.EV_ABS, e.ABS_Y, raw_y)
            else:
                self.uinput.write(e.EV_ABS, e.ABS_RX, raw_x)
                self.uinput.write(e.EV_ABS, e.ABS_RY, raw_y)
            self.uinput.syn()
            return

        # Keyboard fallback for left stick (WASD)
        if which == "left" and self.keyboard:
            threshold = 0.35
            if ny < -threshold:
                self.keyboard.press('w')
            else:
                self.keyboard.release('w')

            if ny > threshold:
                self.keyboard.press('s')
            else:
                self.keyboard.release('s')

            if nx < -threshold:
                self.keyboard.press('a')
            else:
                self.keyboard.release('a')

            if nx > threshold:
                self.keyboard.press('d')
            else:
                self.keyboard.release('d')

    def _handle_trigger(self, name: str, fval: float):
        raw = int(max(0.0, min(1.0, fval)) * 255)
        if self.mode == "gamepad" and self.uinput:
            axis = e.ABS_Z if name in ("L2", "LT") else e.ABS_RZ
            self.uinput.write(e.EV_ABS, axis, raw)
            self.uinput.syn()
            return

        # Fallback trigger: L2 = Q, R2 = E
        if self.keyboard:
            key = 'q' if name in ("L2", "LT") else 'e'
            if raw > 128:
                self.keyboard.press(key)
            else:
                self.keyboard.release(key)

    def _handle_dpad(self, dx: int, dy: int):
        dx = max(-1, min(1, dx))
        dy = max(-1, min(1, dy))
        if self.mode == "gamepad" and self.uinput:
            self.uinput.write(e.EV_ABS, e.ABS_HAT0X, dx)
            self.uinput.write(e.EV_ABS, e.ABS_HAT0Y, dy)
            self.uinput.syn()
            return

        # Fallback arrow keys
        if self.keyboard:
            keys = {
                (0, -1): Key.up,
                (0, 1): Key.down,
                (-1, 0): Key.left,
                (1, 0): Key.right
            }
            for (kx, ky), k in keys.items():
                if dx == kx and dy == ky:
                    self.keyboard.press(k)
                else:
                    self.keyboard.release(k)

    def close(self):
        if self.uinput:
            try:
                self.uinput.close()
            except Exception:
                pass
            self.uinput = None
            self.active = False
