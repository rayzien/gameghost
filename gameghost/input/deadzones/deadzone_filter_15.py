"""Gamepad deadzone filter algorithm: deadzone_filter_15."""
import math

class DeadzoneFilter15:
    def __init__(self, inner: float = 0.08, outer: float = 0.95):
        self.inner = inner
        self.outer = outer

    def filter(self, x: float, y: float) -> tuple[float, float]:
        mag = math.hypot(x, y)
        if mag < self.inner:
            return 0.0, 0.0
        norm = min(1.0, (mag - self.inner) / (self.outer - self.inner))
        scale = norm / mag
        return x * scale, y * scale
