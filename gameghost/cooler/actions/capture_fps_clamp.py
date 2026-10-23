"""Cooler throttle action: capture_fps_clamp."""
class CaptureFpsClampAction:
    def __init__(self):
        self.name = "capture_fps_clamp"
        self.applied_level = 0

    def execute(self, severity: float):
        self.applied_level = severity
